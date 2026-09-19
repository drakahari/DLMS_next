#!/usr/bin/env python3
"""Provider-neutral DLMS video assembly. No application imports or voice services."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'docs/demo-video'
FPS = 30
WIDTH, HEIGHT = 1920, 1080
SAMPLE_RATE = 48000
# Incoming chapter boundaries from NARRATION.md; short fades replace dissolves.
CHAPTER_STARTS = {6, 9, 11, 14, 18, 21, 26, 28, 31, 33, 34, 36}
FADE_FRAMES = 5  # 1/6 second on each side, 1/3 second through black total.
AUDITION_SCENE_IDS = (1, 13, 14)


class BuildError(ValueError):
    """An actionable input, prerequisite, or media failure."""


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def production_manifest(project=PROJECT):
    """Derive all sequence/text/timing from narration; fail closed on format drift."""
    source = project / 'NARRATION.md'
    text = source.read_text(encoding='utf-8')
    captures = json.loads((project / 'video-manifest.json').read_text(encoding='utf-8'))
    if [r['id'] for r in captures] != list(range(1, 37)):
        raise BuildError('Capture manifest must contain ordered scenes 001–036.')
    blocks = list(re.finditer(r'^## Scene (\d{3}) — ([^\n]+)\n(.*?)(?=^## |\Z)', text, re.M | re.S))
    if [int(m[1]) for m in blocks] != list(range(1, 37)):
        raise BuildError('NARRATION.md must contain exactly the ordered scenes 001–036.')
    scenes = []
    for match, capture in zip(blocks, captures):
        scene_id, title, body = int(match[1]), match[2], match[3]

        def field(name):
            found = re.findall(r'^\*\*' + re.escape(name) + r':\*\* (.+)$', body, re.M)
            if len(found) != 1:
                raise BuildError(f'Scene {scene_id:03}: expected one {name} field.')
            # Markdown layout breaks are presentation, not field values.
            return re.sub(r'<br\s*/?>\s*$', '', found[0]).strip()

        status = field('Status')
        statuses = {
            'Essential — KEEP': ['main', 'long'],
            'Optional — KEEP in main cut': ['main', 'long'],
            'Optional — KEEP FOR LONG VERSION': ['long'],
            'Optional — CUT': [],
        }
        if status not in statuses:
            raise BuildError(f'Scene {scene_id:03}: unknown editorial status: {status}')
        image_match = re.fullmatch(r'\[([^]]+)\]\((captures/[^)]+\.png)\)', field('Image'))
        if not image_match or image_match[2] != capture['image']:
            raise BuildError(f'Scene {scene_id:03}: image differs from capture manifest.')
        image_path = project / capture['image']
        if image_path.resolve().parent != (project / 'captures').resolve():
            raise BuildError(f'Scene {scene_id:03}: image outside canonical captures.')
        if not image_path.is_file() or sha256(image_path) != capture['sha256']:
            raise BuildError(f'Scene {scene_id:03}: missing or changed screenshot: {image_path}')
        png = image_path.read_bytes()[:24]
        if png[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', png[16:24]) != (WIDTH, HEIGHT):
            raise BuildError(f'Scene {scene_id:03}: expected a 1920x1080 PNG.')
        targets = re.fullmatch(r'(\d+) sec(?: in main cut; (\d+) sec if restored)?', field('Target'))
        if not targets:
            raise BuildError(f'Scene {scene_id:03}: unrecognized target duration.')
        target = int(targets[2] or targets[1])
        spoken = re.findall(r'^> (.+)$', body, re.M)
        if len(spoken) != 1 or not spoken[0].strip() or target <= 0:
            raise BuildError(f'Scene {scene_id:03}: expected one nonempty narration paragraph and positive target.')
        words = len(spoken[0].split())
        estimate = re.fullmatch(r'(\d+) words; ([\d.]+) sec at (\d+) WPM', field('Speech estimate'))
        if not estimate or int(estimate[1]) != words:
            raise BuildError(f'Scene {scene_id:03}: narration word count is stale.')
        motion_note = field('Motion')
        if motion_note.startswith('Static hold'):
            motion = 'static'
        elif '2% push' in motion_note:
            motion = 'push'
        elif '2% pull back' in motion_note:
            motion = 'pull'
        else:
            raise BuildError(f'Scene {scene_id:03}: unsupported motion suggestion: {motion_note}')
        scenes.append({
            'id': scene_id, 'title': title, 'image': capture['image'],
            'image_sha256': capture['sha256'], 'editorial_status': status,
            'included_cuts': statuses[status], 'narration': spoken[0],
            'narration_words': words, 'target_seconds': target,
            'audio_filename': f'{scene_id:03}.wav', 'text_filename': f'{scene_id:03}.txt',
            'visual_focus': field('Visual focus'), 'motion': motion,
            'motion_instruction': motion_note,
            'transition_in': 'fade' if scene_id in CHAPTER_STARTS else 'cut',
            'production_note': field('Production / transition note'),
        })
    expected_plain = '\n\n'.join(f"=== SCENE {s['id']:03} ===\n\n{s['narration']}" for s in scenes if 'main' in s['included_cuts']) + '\n'
    if (project / 'NARRATION_PLAIN.txt').read_text(encoding='utf-8') != expected_plain:
        raise BuildError('NARRATION_PLAIN.txt differs from the authoritative main-cut narration.')
    return {
        'schema_version': 1, 'authority': 'docs/demo-video/NARRATION.md',
        'narration_sha256': sha256(source),
        'capture_manifest_sha256': sha256(project / 'video-manifest.json'),
        'image_base': 'docs/demo-video', 'fps': FPS, 'width': WIDTH, 'height': HEIGHT,
        'transition': 'chapter fade-through-black, 5 frames per side; no overlap',
        'scenes': scenes,
    }


def select_scenes(manifest, cut):
    return [s for s in manifest['scenes'] if cut in s['included_cuts']]


def audition_scenes(manifest):
    """A fixed, ordered sample of the main cut, without changing either cut."""
    main = select_scenes(manifest, 'main')
    scenes = [s for s in main if s['id'] in AUDITION_SCENE_IDS]
    if len(scenes) != 3 or tuple(s['id'] for s in scenes) != AUDITION_SCENE_IDS:
        raise BuildError('Audition requires exactly three ordered main-cut scenes: 001, 013, 014.')
    return scenes


def export_audition(manifest, work):
    scenes = audition_scenes(manifest)
    destination = work / 'voice-audition'
    (destination / 'audio').mkdir(parents=True, exist_ok=True)
    for scene in scenes:
        (destination / scene['text_filename']).write_text(scene['narration'] + '\n', encoding='utf-8')
    write_json(destination / 'manifest.json', {
        'schema_version': 1, 'authority': manifest['authority'],
        'narration_sha256': manifest['narration_sha256'],
        'image_base': manifest['image_base'], 'audio_base': 'audio',
        'scene_order': [s['id'] for s in scenes],
        'total_words': sum(s['narration_words'] for s in scenes),
        'target_seconds': sum(s['target_seconds'] for s in scenes),
        'scenes': scenes,
    })
    (destination / 'README.txt').write_text(
        'DLMS voice audition: 001 (opening), 013 (Study workflow), 014 (Learning Intelligence).\n'
        'Generate one WAV for each numbered text file using the SAME voice and settings.\n'
        'Use natural US English: calm, professional, conversational, without sales emphasis.\n'
        'Read only the numbered text files. Do not add introductions, music, or effects.\n'
        'Preserve normal pacing and sentence pauses; targets are not strict clip lengths.\n'
        'Read PRONUNCIATION_NOTES.md before recording. Do not change the script.\n'
        'Return lossless PCM WAV if supported. The builder requires mono/stereo PCM WAV;\n'
        'if necessary, convert a copy locally without changing the original recording.\n'
        'Place files under audio/ and use exactly these names from manifest.json:\n'
        + ''.join(f"  {s['text_filename']} -> audio/{s['audio_filename']}\n" for s in scenes)
        + 'Keep each candidate voice in its own directory; use --audio-dir to select it.\n'
        'Evaluate cadence, acronym clarity, sentence endings, and consistency across scenes.\n'
        'No audio is created by export. Production audio remains in build/demo-video/audio/.\n',
        encoding='utf-8')
    (destination / 'PRONUNCIATION_NOTES.md').write_text(
        '# Audition pronunciation notes\n\n'
        'These are recording instructions, not spoken text. The numbered exports preserve\n'
        'NARRATION.md exactly. Use provider pronunciation controls or human direction,\n'
        'where available, without rewriting the authoritative script.\n\n'
        '- **DLMS** (001): “dee el em ess,” four individual letters. Let the opening\n'
        '  acronym breathe. This is the presentation specified in NARRATION.md.\n'
        '- **Anki** (013): “AHN-kee,” stress the first syllable, as NARRATION.md directs.\n'
        '- **AI** (013): “ay eye,” two letters. Keep the written acronym unchanged.\n'
        '- **Question Tools**, **Study**, **Exam**, **Learning Intelligence** (013/014):\n'
        '  ordinary English words naming product features or modes; no extra pauses\n'
        '  merely because they are capitalized.\n'
        '- **local-first** (001): a connected phrase, not a pause at the hyphen.\n'
        '- **tagged concepts**, **accuracy**, **evidence**, **mastery** (014): use normal\n'
        '  US English, clear consonants, and a light list cadence rather than overemphasis.\n\n'
        'OCR and FFmpeg do not occur in these three scripts and should not be added.\n'
        'For later narration, the existing “O C R” spelling means “oh see ar.”\n'
        'FFmpeg is assembly tooling, not a spoken term in this audition.\n',
        encoding='utf-8')
    return destination


def prerequisites():
    paths = {name: shutil.which(name) for name in ('ffmpeg', 'ffprobe')}
    missing = [name for name, path in paths.items() if path is None]
    if missing:
        raise BuildError('Missing prerequisite: ' + ', '.join(missing) + '. Install/provide these tools explicitly; no packages were installed.')
    # Require the actual encoders/filters we use, not just executables on PATH.
    for option, needed in [('-encoders', ('libx264', 'aac', 'pcm_s16le', 'mov_text')),
                           ('-filters', ('zoompan', 'fade', 'loudnorm', 'apad', 'adelay'))]:
        listing = run([paths['ffmpeg'], '-hide_banner', option]).stdout
        absent = [name for name in needed if not re.search(r'\b' + name + r'\b', listing)]
        if absent:
            raise BuildError('FFmpeg lacks required capabilities: ' + ', '.join(absent))
    return paths


def run(command, timeout=600):
    """Argument arrays preserve spaces; bounded calls never spawn shell children."""
    try:
        result = subprocess.run([str(x) for x in command], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError(f'Media command failed: {command[0]}: {exc}') from exc
    if result.returncode:
        raise BuildError(f'Media command failed ({result.returncode}): {command[0]}\n{result.stderr[-6000:]}')
    return result


def probe(path, media):
    try:
        return json.loads(run([media['ffprobe'], '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path], timeout=30).stdout)
    except json.JSONDecodeError as exc:
        raise BuildError(f'ffprobe returned malformed JSON for {path}') from exc


def audio_inputs(scenes, audio_dir, media):
    """Only exact NNN.wav names and PCM WAV; excluded known scenes are ignored."""
    if not audio_dir.is_dir():
        raise BuildError(f'Audio directory does not exist: {audio_dir}. Supply one PCM WAV per included scene (001.wav, etc.).')
    errors, clips = [], {}
    for path in sorted(audio_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac'}:
            if not re.fullmatch(r'\d{3}\.wav', path.name) or not 1 <= int(path.stem) <= 36:
                errors.append(f'Unsupported or unmapped audio: {path.name}; use exact 001.wav–036.wav PCM WAV names.')
    for scene in scenes:
        path = audio_dir / scene['audio_filename']
        if not path.is_file():
            errors.append(f"Scene {scene['id']:03}: missing {path.name}")
            continue
        try:
            data = probe(path, media)
            streams = data.get('streams', [])
            if len(streams) != 1 or streams[0].get('codec_type') != 'audio':
                raise BuildError('expected exactly one audio stream and no other streams')
            stream = streams[0]
            if data.get('format', {}).get('format_name') != 'wav' or not stream.get('codec_name', '').startswith('pcm_'):
                raise BuildError('expected lossless PCM WAV (not a renamed compressed file)')
            duration = float(stream.get('duration') or data.get('format', {}).get('duration', 0))
            if not math.isfinite(duration) or duration <= 0 or int(stream.get('channels', 0)) not in (1, 2):
                raise BuildError('expected positive finite duration and mono or stereo audio')
            # Decode validation catches truncated/corrupt payloads that metadata alone may accept.
            run([media['ffmpeg'], '-v', 'error', '-xerror', '-i', path, '-map', '0:a:0', '-f', 'null', '-'], timeout=120)
            clips[scene['id']] = {'path': str(path.resolve()), 'seconds': duration, 'sha256': sha256(path)}
        except (BuildError, ValueError) as exc:
            errors.append(f"Scene {scene['id']:03}: malformed {path.name}: {exc}")
    if errors:
        raise BuildError('Audio validation failed:\n' + '\n'.join(errors))
    return clips


def timeline(scenes, clips=None, tail=0.6):
    """Whole-frame slots; no audio overlap. Editorial targets are viewing minimums."""
    if not math.isfinite(tail) or tail < FADE_FRAMES / FPS:
        raise BuildError(f'Visual tail must be finite and at least {FADE_FRAMES / FPS:.3f} seconds.')
    result, cursor = [], 0
    for index, scene in enumerate(scenes):
        fade_in = index > 0 and scene['transition_in'] == 'fade'
        fade_out = index == len(scenes) - 1 or scenes[index + 1]['transition_in'] == 'fade'
        lead_frames = FADE_FRAMES if fade_in else 0
        clip = clips[scene['id']] if clips is not None else None
        if clip is not None and (not math.isfinite(clip['seconds']) or clip['seconds'] <= 0):
            raise BuildError(f"Scene {scene['id']:03}: invalid audio duration.")
        seconds = scene['target_seconds']
        if clip:
            seconds = max(seconds, lead_frames / FPS + clip['seconds'] + tail)
        frames = math.ceil(seconds * FPS - 1e-9)
        row = dict(scene, start_frame=cursor, frames=frames, duration_seconds=frames / FPS,
                   fade_in_frames=FADE_FRAMES if fade_in else 0,
                   fade_out_frames=FADE_FRAMES if fade_out else 0,
                   audio=clip, audio_lead_frames=lead_frames)
        result.append(row)
        cursor += frames
    return result


def srt_timestamp(seconds):
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{sec:02},{ms:03}'


def subtitles(rows):
    entries = []
    for i, row in enumerate(rows, 1):
        if row['audio'] is None:
            raise BuildError('Subtitles require real per-scene audio; silent previews do not produce timed captions.')
        start = (row['start_frame'] + row['audio_lead_frames']) / FPS
        end = start + row['audio']['seconds']
        entries.append(f'{i}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{row["narration"]}\n')
    return '\n'.join(entries)


def export_pack(manifest, cut, work):
    """Derived files, not an independently editable production manifest."""
    directory = work / 'narration-text' / cut
    directory.mkdir(parents=True, exist_ok=True)
    index = []
    for scene in select_scenes(manifest, cut):
        (directory / scene['text_filename']).write_text(scene['narration'] + '\n', encoding='utf-8')
        index.append({key: scene[key] for key in ('id', 'image', 'text_filename', 'target_seconds', 'audio_filename')})
    write_json(directory / 'index.json', {'cut': cut, 'image_base': 'docs/demo-video',
               'audio_base': '../../audio', 'scenes': index})
    write_json(work / 'production-manifest.json', manifest)
    return directory


def video_filter(row, motion='none'):
    if motion not in {'none', 'planned'}:
        raise BuildError('Motion must be none or planned.')
    frames = row['frames']
    filters = ['setsar=1']
    if motion == 'none' or row['motion'] == 'static':
        filters.append(f'fps={FPS}')
    else:
        # Supersampling limits integer crop jitter. Fixed center; no speculative focus pan.
        travel = max(1, frames - 1 - (60 if row['motion'] == 'pull' else 0))
        progress = f'min(on/{travel},1)'
        zoom = f'1+0.02*{progress}' if row['motion'] == 'push' else f'1.02-0.02*{progress}'
        filters += ['scale=3840:2160:flags=lanczos',
                    f"zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={WIDTH}x{HEIGHT}:fps={FPS}"]
    filters += [f'trim=end_frame={frames}', f'setpts=N/({FPS}*TB)', 'format=yuv420p']
    if row['fade_in_frames']:
        filters.append(f"fade=t=in:s=0:n={row['fade_in_frames']}")
    if row['fade_out_frames']:
        count = row['fade_out_frames']
        filters.append(f'fade=t=out:s={frames-count}:n={count-1}')
    return ','.join(filters)


def ffmpeg(media):
    return [media['ffmpeg'], '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-filter_threads', '1']


def concat_file(path, names):
    # Names are generated internally and relative to the list, never user paths.
    path.write_text(''.join(f"file '{name}'\n" for name in names), encoding='utf-8')


def normalize_audio(source, destination, media, samples):
    """Two-pass scene leveling; silence padding permits measurement of short clips."""
    base = 'loudnorm=I=-18:TP=-2:LRA=11'
    # loudnorm emits measurement JSON at info level, even though rendering is quiet.
    measured = run([media['ffmpeg'], '-hide_banner', '-nostdin', '-i', source,
                    '-af', 'apad=whole_dur=3,' + base + ':print_format=json', '-f', 'null', '-'])
    match = re.search(r'\{\s*"input_i".*?\}', measured.stderr, re.S)
    if not match:
        raise BuildError('FFmpeg did not report loudness measurements.')
    values = json.loads(match[0])
    keys = {'measured_I': 'input_i', 'measured_TP': 'input_tp', 'measured_LRA': 'input_lra',
            'measured_thresh': 'input_thresh', 'offset': 'target_offset'}
    if not all(math.isfinite(float(values[key])) for key in keys.values()):
        raise BuildError('Audio loudness cannot be measured (possibly silent clips). Use real narration or --normalization none.')
    correction = base + ''.join(f':{key}={values[value]}' for key, value in keys.items()) + ':linear=true'
    correction = f'apad=whole_dur=3,{correction},aresample={SAMPLE_RATE},apad,atrim=end_sample={samples}'
    run(ffmpeg(media) + ['-i', source, '-af', correction, '-ar', str(SAMPLE_RATE), '-ac', '1',
                        '-c:a', 'pcm_s16le', destination])
    return values


def verify_output(path, rows, media, narrated=False, mux_subtitles=False):
    data = probe(path, media)
    streams = data.get('streams', [])
    videos = [s for s in streams if s['codec_type'] == 'video']
    if len(videos) != 1:
        raise BuildError('Rendered output must contain exactly one video stream.')
    video = videos[0]
    expected = sum(row['frames'] for row in rows)
    checks = (video.get('codec_name') == 'h264', video.get('pix_fmt') == 'yuv420p',
              (video.get('width'), video.get('height')) == (WIDTH, HEIGHT),
              video.get('avg_frame_rate') == '30/1', int(video.get('nb_frames', -1)) == expected,
              abs(float(video.get('duration', 0)) - expected / FPS) <= 1 / FPS)
    audio = [s for s in streams if s['codec_type'] == 'audio']
    subs = [s for s in streams if s['codec_type'] == 'subtitle']
    if not all(checks) or len(audio) != int(narrated) or len(subs) != int(mux_subtitles):
        raise BuildError(f'Rendered output stream/timing contract failed: {path}')
    if narrated and (audio[0]['codec_name'] != 'aac' or abs(float(audio[0].get('duration', 0)) - expected / FPS) > 0.1):
        raise BuildError('Rendered AAC duration does not match the scene timeline.')
    if mux_subtitles and subs[0].get('codec_name') != 'mov_text':
        raise BuildError('Expected a selectable mov_text subtitle track.')
    return data


def render(rows, output, media, project=PROJECT, normalization='ebu', mux_subtitles=False,
           overwrite=False, preset='veryfast', motion='none'):
    filters = {str(row['id']): video_filter(row, motion) for row in rows}
    narrated = all(row['audio'] is not None for row in rows)
    if not rows or (not narrated and any(row['audio'] is not None for row in rows)):
        raise BuildError('Render needs a nonempty, entirely silent or entirely narrated timeline.')
    if mux_subtitles and not narrated:
        raise BuildError('Selectable subtitles require real narration audio.')
    outputs = [output, output.with_suffix('.timeline.json')]
    if narrated:
        outputs.append(output.with_suffix('.srt'))
    if not overwrite and any(path.exists() for path in outputs):
        raise BuildError(f'Output already exists for {output}; use --overwrite explicitly.')
    output.parent.mkdir(parents=True, exist_ok=True)
    loudness = {}
    # All intermediates are bounded to one disposable directory, also on failure/Ctrl-C.
    with tempfile.TemporaryDirectory(prefix='.render-', dir=output.parent) as temporary:
        temp = Path(temporary)
        video_names, audio_names = [], []
        for number, row in enumerate(rows):
            print(f"Rendering scene {row['id']:03} ({number+1}/{len(rows)}), {row['duration_seconds']:.3f}s", flush=True)
            name = f'video-{number:03}.mp4'
            run(ffmpeg(media) + ['-loop', '1', '-framerate', str(FPS), '-i', project / row['image'],
                                '-vf', filters[str(row['id'])], '-frames:v', str(row['frames']), '-an',
                                '-c:v', 'libx264', '-preset', preset, '-crf', '18', '-threads', '2',
                                '-pix_fmt', 'yuv420p', '-video_track_timescale', '15360', temp / name])
            video_names.append(name)
            if narrated:
                audio_name = f'audio-{number:03}.wav'
                samples = row['frames'] * (SAMPLE_RATE // FPS)
                lead = row['audio_lead_frames'] * (SAMPLE_RATE // FPS)
                audio_filter = f'aresample={SAMPLE_RATE},aformat=channel_layouts=mono,adelay={lead}S:all=1,apad,atrim=end_sample={samples},asetpts=N/SR/TB'
                run(ffmpeg(media) + ['-i', row['audio']['path'], '-af', audio_filter,
                                    '-c:a', 'pcm_s16le', temp / audio_name])
                if normalization == 'ebu':
                    normalized_name = f'normalized-{number:03}.wav'
                    loudness[str(row['id'])] = normalize_audio(
                        temp / audio_name, temp / normalized_name, media, samples)
                    audio_name = normalized_name
                audio_names.append(audio_name)
        concat_file(temp / 'video.txt', video_names)
        run(ffmpeg(media) + ['-f', 'concat', '-safe', '1', '-i', temp / 'video.txt', '-map', '0:v:0',
                            '-c', 'copy', temp / 'joined.mp4'])
        command = ffmpeg(media) + ['-i', temp / 'joined.mp4']
        if narrated:
            concat_file(temp / 'audio.txt', audio_names)
            run(ffmpeg(media) + ['-f', 'concat', '-safe', '1', '-i', temp / 'audio.txt',
                                '-c:a', 'pcm_s16le', temp / 'joined.wav'])
            audio_source = temp / 'joined.wav'
            command += ['-i', audio_source]
            (temp / 'captions.srt').write_text(subtitles(rows), encoding='utf-8')
            if mux_subtitles:
                command += ['-i', temp / 'captions.srt']
        command += ['-map', '0:v:0', '-c:v', 'copy']
        if narrated:
            command += ['-map', '1:a:0', '-c:a', 'aac', '-b:a', '192k', '-ar', str(SAMPLE_RATE), '-ac', '1']
            if mux_subtitles:
                command += ['-map', '2:s:0', '-c:s', 'mov_text', '-metadata:s:s:0', 'language=eng',
                            '-metadata:s:s:0', 'title=English']
        command += ['-map_metadata', '-1', '-movflags', '+faststart', temp / 'result.mp4']
        run(command)
        checked = verify_output(temp / 'result.mp4', rows, media, narrated, mux_subtitles)
        report = {'fps': FPS, 'duration_seconds': sum(r['frames'] for r in rows) / FPS,
                  'motion_mode': motion, 'video_filters': filters,
                  'normalization': normalization if narrated else 'none', 'loudness_measurement': loudness,
                  'ffmpeg_version': run([media['ffmpeg'], '-version']).stdout.splitlines()[0],
                  'ffprobe_version': run([media['ffprobe'], '-version']).stdout.splitlines()[0],
                  'scenes': rows, 'encoded_streams': checked['streams']}
        write_json(temp / 'timeline.json', report)
        # Only publish a validated finished result; failed renders preserve old outputs.
        (temp / 'result.mp4').replace(output)
        (temp / 'timeline.json').replace(output.with_suffix('.timeline.json'))
        if narrated:
            (temp / 'captions.srt').replace(output.with_suffix('.srt'))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'export', 'preview', 'build', 'subtitles'))
    parser.add_argument('--cut', choices=('main', 'long'), default='main')
    parser.add_argument('--audition', action='store_true', help='Use scenes 001, 013, 014 and separate audition audio/output.')
    parser.add_argument('--audio-set', help='Audition candidate under voice-audition/candidates/; also names the output.')
    parser.add_argument('--work-dir', type=Path, default=ROOT / 'build/demo-video')
    parser.add_argument('--audio-dir', type=Path, help='Default: WORK_DIR/audio, or WORK_DIR/voice-audition/audio with --audition. Exact PCM WAV names: 001.wav, etc.')
    parser.add_argument('--require-audio', action='store_true', help='Also validate audio with the validate action.')
    parser.add_argument('--tail', type=float, default=0.6, help='Minimum post-audio visual tail in seconds.')
    parser.add_argument('--mux-subtitles', action='store_true')
    parser.add_argument('--normalization', choices=('ebu', 'none'), default='ebu')
    parser.add_argument('--motion', choices=('none', 'planned'), default='none',
                        help='Default none: static screenshots, retaining chapter fades. planned restores historical scene motion.')
    parser.add_argument('--overwrite', action='store_true', help='Replace existing video/SRT outputs.')
    args = parser.parse_args(argv)
    try:
        work = args.work_dir.resolve()
        if not work.is_relative_to((ROOT / 'build').resolve()) or work == (ROOT / 'build').resolve():
            raise BuildError('--work-dir must be a subdirectory of the repository build/ directory.')
        if args.audio_set and (not args.audition or args.audio_dir
                               or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.audio_set)):
            raise BuildError('--audio-set requires --audition, cannot be combined with --audio-dir, and must be a simple name.')
        manifest = production_manifest()
        if args.audition and (args.cut != 'main' or args.action == 'preview'):
            raise BuildError('--audition uses main-cut scenes and requires real audio to build; do not combine with --cut long or preview.')
        scenes = audition_scenes(manifest) if args.audition else select_scenes(manifest, args.cut)
        if args.action == 'export':
            destination = export_audition(manifest, work) if args.audition else export_pack(manifest, args.cut, work)
            print(f'Exported {len(scenes)} narration units to {destination}')
            return 0
        media = prerequisites()
        clips = None
        if args.action in {'build', 'subtitles'} or args.require_audio:
            if args.audio_set:
                audio_dir = work / 'voice-audition/candidates' / args.audio_set
            else:
                audio_dir = args.audio_dir or (work / 'voice-audition/audio' if args.audition else work / 'audio')
            if args.audition and not audio_dir.is_dir():
                raise BuildError(f'Missing audition audio directory: {audio_dir}; required WAVs: ' + ', '.join(s['audio_filename'] for s in scenes))
            clips = audio_inputs(scenes, audio_dir, media)
        rows = timeline(scenes, clips, args.tail)
        if args.action == 'validate':
            print(f"Validated {len(manifest['scenes'])} screenshots; main={len(select_scenes(manifest, 'main'))}, long={len(select_scenes(manifest, 'long'))}; {len(rows)} {'audition' if args.audition else args.cut} scenes, {sum(r['frames'] for r in rows)/FPS:.3f}s.")
            print(f"FFmpeg: {media['ffmpeg']}; ffprobe: {media['ffprobe']}; audio {'validated' if clips else 'not required (use --require-audio)' }.")
            return 0
        if args.action == 'preview' and (args.require_audio or args.mux_subtitles):
            raise BuildError('Silent preview cannot use --require-audio or --mux-subtitles.')
        if args.audition:
            export_audition(manifest, work)
        else:
            export_pack(manifest, args.cut, work)
        if args.audition:
            label = re.sub(r'^a[fm]_', '', args.audio_set) if args.audio_set else None
            base = 'DLMS-3.2-voice-audition' + (f'-{label}' if label else '')
        else:
            base = 'DLMS-3.2-demo' + ('-long' if args.cut == 'long' else '')
        if args.action == 'subtitles':
            path = work / (base + '.srt')
            if path.exists() and not args.overwrite:
                raise BuildError(f'{path} exists; use --overwrite explicitly.')
            path.write_text(subtitles(rows), encoding='utf-8')
            write_json(path.with_suffix('.subtitle-timeline.json'), {'fps': FPS, 'scenes': rows})
            print(f'Wrote scene-level subtitles to {path}')
        else:
            output = work / (base + ('-silent-preview' if args.action == 'preview' else '') + '.mp4')
            report = render(rows, output, media, normalization=args.normalization,
                            mux_subtitles=args.mux_subtitles, overwrite=args.overwrite, motion=args.motion)
            print(f"Validated output: {output} ({report['duration_seconds']:.3f}s)")
        return 0
    except (BuildError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Interrupted; disposable render intermediates removed.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
