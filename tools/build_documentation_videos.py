#!/usr/bin/env python3
"""DLMS instructional series: validate, capture, narrate and render selected videos.

Uses the overview's renderer and local Kokoro adapter without editing its plan.
Definitions are offline JSON; all derived media stays beneath build/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import tempfile

import build_demo_video as video
import generate_demo_narration as tts

ROOT = video.ROOT
SERIES = ROOT / 'docs/demo-video/series'
OUTPUT = ROOT / 'build/demo-video/series'
VOICE = 'af_heart'
SPEED = 1.0


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise video.BuildError(f'{path}: cannot read JSON: {exc}') from exc


def require(condition, message):
    if not condition:
        raise video.BuildError(message)


def text_field(row, key):
    value = row.get(key)
    require(isinstance(value, str) and bool(value.strip()), f'Missing/nonempty text required: {key}')
    require(value == value.strip() and '\n' not in value and '\r' not in value,
            f'{key}: use one trimmed paragraph')
    return value


def resource(base, name):
    require(isinstance(name, str) and bool(name), 'Resource path must be text')
    path = (base / name).resolve()
    require(not Path(name).is_absolute() and path.is_relative_to(base.resolve()),
            f'Resource escapes its root: {name}')
    require(path.is_file(), f'Missing resource: {path}')
    return path


def manual_reference(reference):
    name, _, anchor = reference.partition('#')
    require(name.startswith('docs/user-manual/') and name.endswith('.md'),
            f'Expected a canonical manual reference: {reference}')
    path = resource(ROOT, name)
    if anchor:
        headings = re.findall(r'^#{1,6} (.+)$', path.read_text(encoding='utf-8'), re.M)
        slugs = {re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headings}
        require(anchor in slugs, f'Missing manual anchor: {reference}')


def capture_catalog(series=SERIES):
    result = {}
    for filename in ('video-manifest.json', 'v3-additions-manifest.json', 'exam-additions-manifest.json'):
        data = read_json(video.PROJECT / filename)
        for row in data if isinstance(data, list) else data['scenes']:
            key = 'overview:' + video.scene_label(row['id'])
            result[key] = dict(row, image='docs/demo-video/' + row['image'], recipe=key)
    additions = read_json(series / 'captures.json')
    require(isinstance(additions, list), 'captures.json must be an array')
    for row in additions:
        require(isinstance(row, dict), 'Capture must be an object')
        key = text_field(row, 'key')
        require(re.fullmatch(r'series:\d{3}', key) and key not in result, f'Duplicate/invalid capture key: {key}')
        require(row.get('recipe') == key, f'Capture recipe must match {key}')
        result[key] = row
    for key, row in result.items():
        path = resource(ROOT, row['image'])
        require(path.is_relative_to(video.PROJECT.resolve()), f'{key}: capture must be in demo-video')
        png = path.read_bytes()
        require(png[:8] == b'\x89PNG\r\n\x1a\n' and len(png) >= 24
                and struct.unpack('>II', png[16:24]) == (video.WIDTH, video.HEIGHT),
                f'{key}: expected a 1920x1080 PNG')
        require(video.sha256(path) == row['sha256'], f'{key}: screenshot hash changed; review before accepting it')
    return result


def load_series(series=SERIES):
    index = read_json(series / 'index.json')
    require(isinstance(index, dict) and index.get('schema_version') == 1, 'Unsupported series schema')
    require(index.get('voice') == VOICE and index.get('speed') == SPEED, 'Series production voice must be af_heart at 1.0')
    text_field(index, 'playlist')
    definitions = index.get('videos')
    require(isinstance(definitions, list) and bool(definitions), 'Series needs video definitions')
    captures, videos, identifiers = capture_catalog(series), [], set()
    for filename in definitions:
        path = resource(series, filename)
        definition = read_json(path)
        require(isinstance(definition, dict), f'{filename}: expected an object')
        identifier = text_field(definition, 'id')
        require(re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', identifier)
                and identifier not in identifiers, f'Duplicate/invalid video identifier: {identifier}')
        identifiers.add(identifier)
        for key in ('title', 'purpose', 'youtube_title', 'description', 'thumbnail_text'):
            text_field(definition, key)
        require(len(definition['youtube_title']) < 100, f'{identifier}: YouTube title must be under 100 characters')
        require(len(definition['thumbnail_text'].split()) <= 6, f'{identifier}: thumbnail text too long')
        refs = definition.get('manual_refs')
        require(isinstance(refs, list) and bool(refs) and all(isinstance(r, str) for r in refs), f'{identifier}: missing manual references')
        for ref in refs:
            manual_reference(ref)
        sources = definition.get('implementation_refs')
        require(isinstance(sources, list) and bool(sources), f'{identifier}: missing implementation references')
        for ref in sources:
            resource(ROOT, ref)
        limits = definition.get('target_seconds')
        require(isinstance(limits, list) and len(limits) == 2
                and all(type(n) is int and n > 0 for n in limits) and limits[0] <= limits[1],
                f'{identifier}: invalid duration range')
        original = definition.get('scenes')
        require(isinstance(original, list) and bool(original), f'{identifier}: empty scenes')
        scenes, seen = [], set()
        for raw in original:
            require(isinstance(raw, dict), f'{identifier}: scene must be an object')
            label = video.scene_label(raw.get('id'))
            require(label not in seen, f'{identifier}: duplicate scene {label}')
            seen.add(label)
            for key in ('title', 'narration', 'visual_focus'):
                text_field(raw, key)
            require('chapter' not in raw or isinstance(raw['chapter'], str) and bool(raw['chapter'].strip()),
                    f'{identifier}/{label}: invalid chapter')
            capture = captures.get(raw.get('capture'))
            require(capture is not None, f'{identifier}/{label}: unknown capture')
            minimum = raw.get('minimum_seconds', 6)
            require(type(minimum) in (float, int) and math.isfinite(minimum) and minimum >= 1,
                    f'{identifier}/{label}: invalid visual minimum')
            scenes.append(dict(raw, id=label, image=capture['image'], image_sha256=capture['sha256'],
                               audio_filename=label + '.wav', text_filename=label + '.txt',
                               narration_words=len(raw['narration'].split()), target_seconds=minimum,
                               motion='static', transition_in='cut'))
        require(scenes[0].get('chapter'), f'{identifier}: first scene must start a chapter')
        require(definition.get('thumbnail_capture') in {s['capture'] for s in scenes},
                f'{identifier}: thumbnail must use a scene capture')
        videos.append(dict(definition, scenes=scenes,
                           definition_path='docs/demo-video/series/' + str(path.relative_to(series))))
    return index, videos, captures


def select(videos, requested=None, all_videos=False):
    require(bool(requested) != all_videos, 'Select --all or --videos id[,id], exclusively')
    if all_videos:
        return videos
    wanted = requested.split(',')
    require(all(wanted) and len(set(wanted)) == len(wanted), 'Selection contains empty or duplicate IDs')
    unknown = set(wanted) - {v['id'] for v in videos}
    require(not unknown, 'Unknown videos: ' + ', '.join(sorted(unknown)))
    return [v for v in videos if v['id'] in wanted]  # playlist order, not CLI order


def output_directory(root, identifier):
    path = (root / identifier).resolve()
    require(path.is_relative_to((ROOT / 'build').resolve()) and path.is_relative_to(root.resolve()),
            'Series outputs must stay below build/, separate from overview outputs')
    return path


def audio_status(definition, directory):
    current, stale = [], []
    for scene in definition['scenes']:
        path = directory / 'audio' / scene['audio_filename']
        try:
            tts.validate_recorded_audio(scene, path, VOICE, SPEED)
            tts.validate_wav(path)
        except (video.BuildError, OSError) as exc:
            stale.append((scene, str(exc)))
        else:
            current.append(scene['id'])
    return current, stale


def chapters(rows):
    entries = [(r['start_frame'] / video.FPS, r['chapter']) for r in rows if r.get('chapter')]
    end = sum(r['frames'] for r in rows) / video.FPS
    starts = [math.floor(t + 0.5) for t, _ in entries]
    require(starts and starts[0] == 0 and len(starts) >= 3, 'Publishing needs at least three chapters starting at zero')
    require(all(b - a >= 10 for a, b in zip(starts, starts[1:] + [end])), 'Every chapter must last at least ten seconds')
    return '\n'.join(f'{start // 60:02}:{start % 60:02} {title}'
                     for start, (_, title) in zip(starts, entries)) + '\n'


def export_definition(definition, directory):
    directory.mkdir(parents=True, exist_ok=True)
    video.write_json(directory / 'plan.json', definition)
    (directory / 'NARRATION.txt').write_text('\n\n'.join(
        f"=== {s['id']} — {s['title']} ===\n{s['narration']}" for s in definition['scenes']) + '\n', encoding='utf-8')


def publishing(definition, directory, rows):
    chapter_text = chapters(rows)
    (directory / 'CHAPTERS.txt').write_text(chapter_text, encoding='utf-8')
    manual = '\n'.join('- ' + ref for ref in definition['manual_refs'])
    body = (definition['description'] + '\n\n' + chapter_text
            + '\nWritten guide (replace repository-relative paths with the public repository URLs before upload):\n'
            + manual + '\n\nDLMS is local-first, single-user software. Demonstrations use original synthetic content. '
            'Narration is synthesized locally with Kokoro.\n')
    (directory / 'DESCRIPTION.txt').write_text(body, encoding='utf-8')
    video.write_json(directory / 'publishing.json', {
        'status': 'candidate — not published', 'title': definition['youtube_title'],
        'captions': 'master.srt', 'delivery': 'delivery.mp4', 'thumbnail_text': definition['thumbnail_text'],
        'thumbnail_capture': definition['thumbnail_capture'], 'manual_refs': definition['manual_refs'],
    })
    review = ['# Candidate listening and visual review', '', definition['title'], '',
              'Listen to the complete video before publication. Check pronunciation, sentence endings,',
              'natural pacing, caption alignment and the visual state named below. No review is',
              'automatically approved by a successful render.', '']
    for row in rows:
        stamp = video.srt_timestamp(row['start_frame'] / video.FPS).split(',')[0]
        review.append(f"- [ ] {stamp} — {row['id']} {row['title']}: {row['visual_focus']}")
    review += ['', '- [ ] DLMS, AI, OCR, API and Anki pronunciation where present.',
               '- [ ] Small text and borders remain readable in the delivery encode.',
               '- [ ] Chapter names, manual links and thumbnail are accurate.',
               '- [ ] Candidate approved for publication by the repository owner.', '']
    (directory / 'LISTENING_REVIEW.md').write_text('\n'.join(review), encoding='utf-8')


def fingerprint(definition, clips):
    # Includes shared pipeline code so a renderer/TTS change invalidates the cache.
    state = {'definition': definition, 'audio': clips, 'voice': VOICE, 'speed': SPEED,
             'tools': {p.name: video.sha256(p) for p in
                       (Path(__file__), Path(video.__file__), Path(tts.__file__))}}
    return hashlib.sha256(json.dumps(state, sort_keys=True, allow_nan=False).encode()).hexdigest()


def cache_valid(directory, signature):
    record = directory / 'build-record.json'
    if not record.is_file():
        return False
    try:
        data = read_json(record)
        names = ('master.mp4', 'master.srt', 'master.timeline.json')
        return (data.get('fingerprint') == signature
                and set(data.get('outputs', {})) == set(names)
                and all((directory / name).is_file() and video.sha256(directory / name) == data['outputs'][name]
                        for name in names))
    except (video.BuildError, OSError):
        return False


def build_one(definition, directory, media, force=False):
    current, stale = audio_status(definition, directory)
    require(not stale, 'Stale/missing narration; run narrate first:\n' + '\n'.join(reason for _, reason in stale))
    scenes = definition['scenes']
    clips = video.audio_inputs(scenes, directory / 'audio', media,
                               known_scene_labels={s['id'] for s in scenes})
    rows = video.timeline(scenes, clips)
    signature = fingerprint(definition, clips)
    publishing(definition, directory, rows)  # validates chapter timing before expensive rendering
    if not force and cache_valid(directory, signature):
        print(f"{definition['id']}: current master reused", flush=True)
    else:
        video.render(rows, directory / 'master.mp4', media, project=ROOT,
                     mux_subtitles=True, overwrite=True, motion='none')
        video.run([media['ffmpeg'], '-v', 'error', '-xerror', '-i', directory / 'master.mp4', '-f', 'null', '-'])
        video.write_json(directory / 'build-record.json', {
            'fingerprint': signature, 'outputs': {name: video.sha256(directory / name)
                for name in ('master.mp4', 'master.srt', 'master.timeline.json')}})
    return {'reused_audio': current, 'duration_seconds': sum(r['frames'] for r in rows) / video.FPS,
            'spoken_seconds': sum(c['seconds'] for c in clips.values()), 'status': 'built'}


def delivery_one(definition, directory, media):
    # Always verify current source/audio mappings; never deliver an old content cut.
    scenes = definition['scenes']
    _, stale = audio_status(definition, directory)
    require(not stale, 'Delivery requires current narration')
    clips = video.audio_inputs(scenes, directory / 'audio', media,
                               known_scene_labels={s['id'] for s in scenes})
    require(cache_valid(directory, fingerprint(definition, clips)), 'Delivery requires a current validated master; run build first')
    rows = video.timeline(scenes, clips)
    source = directory / 'master.mp4'
    before = video.sha256(source)
    keyframes = ','.join(str(r['start_frame'] / video.FPS) for r in rows)
    with tempfile.TemporaryDirectory(prefix='.delivery-', dir=directory) as temp:
        output = Path(temp) / 'delivery.mp4'
        video.run(video.ffmpeg(media) + ['-i', source, '-map', '0:v:0', '-map', '0:a:0', '-map', '0:s:0',
            '-vf', 'colorspace=ispace=smpte170m:iprimaries=bt709:itrc=bt709:irange=tv:all=bt709:range=tv:format=yuv420p:fast=1',
            '-c:v', 'libx264', '-preset', 'slow', '-tune', 'stillimage', '-crf', '18',
            '-profile:v', 'high', '-level:v', '4.0', '-pix_fmt', 'yuv420p', '-threads', '2',
            '-g', '60', '-bf', '2', '-flags', '+cgop', '-force_key_frames', keyframes,
            '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
            '-c:a', 'copy', '-c:s', 'copy', '-movflags', '+faststart', output])
        video.verify_output(output, rows, media, narrated=True, mux_subtitles=True)
        video.run([media['ffmpeg'], '-v', 'error', '-xerror', '-i', output, '-f', 'null', '-'])
        require(video.sha256(source) == before, 'Master changed during delivery encoding')
        output.replace(directory / 'delivery.mp4')
    return {'status': 'delivery encoded', 'master_sha256': before}


def verify_one(definition, directory, media, preview=False):
    """Decode every frame and compare each entire hold to its source YUV pixels."""
    name = 'silent-preview' if preview else 'master'
    output = directory / (name + '.mp4')
    report = read_json(directory / (name + '.timeline.json'))
    rows = report['scenes']
    require(len(rows) == len(definition['scenes']), 'Rendered scene count is stale')
    for row, scene in zip(rows, definition['scenes']):
        for key in ('id', 'image', 'image_sha256', 'narration'):
            require(row[key] == scene[key], f'Rendered scene has stale {key}')
    video.verify_output(output, rows, media, narrated=not preview, mux_subtitles=not preview)
    video.run([media['ffmpeg'], '-v', 'error', '-xerror', '-i', output, '-f', 'null', '-'])

    def hashes(command):
        return [line.rsplit(',', 1)[1].strip() for line in video.run(command).stdout.splitlines()
                if line and not line.startswith('#')]

    decoded = hashes(video.ffmpeg(media) + ['-i', output, '-map', '0:v:0', '-f', 'framemd5', '-'])
    require(len(decoded) == sum(r['frames'] for r in rows), 'Decoded frame count disagrees with timeline')
    expected = {}
    for row in rows:
        image = row['image']
        if image not in expected:
            expected[image] = hashes(video.ffmpeg(media) + ['-i', ROOT / image, '-vf', 'format=yuv420p',
                                                           '-frames:v', '1', '-f', 'framemd5', '-'])[0]
        hold = decoded[row['start_frame']:row['start_frame'] + row['frames']]
        require(hold and set(hold) == {expected[image]}, f"Scene {row['id']}: blank, altered or unstable frames")
    if not preview:
        _, stale = audio_status(definition, directory)
        require(not stale, 'Narration provenance is stale')
        clips = video.audio_inputs(definition['scenes'], directory / 'audio', media,
                                   known_scene_labels={s['id'] for s in definition['scenes']})
        require(cache_valid(directory, fingerprint(definition, clips)), 'Master provenance is stale')
        require((directory / 'master.srt').read_text(encoding='utf-8') == video.subtitles(rows),
                'Separate captions disagree with actual timeline')
        muxed = video.run(video.ffmpeg(media) + ['-i', output, '-map', '0:s:0', '-f', 'srt', '-']).stdout
        require(muxed.strip() == video.subtitles(rows).strip(), 'Muxed captions differ from authoritative SRT')
    return {'status': 'verified silent preview' if preview else 'verified narrated master',
            'frames': len(decoded), 'scenes': len(rows), 'source_pixel_equality': True,
            'duration_seconds': len(decoded) / video.FPS}


def capture_selected(definitions, captures, work):
    # Existing capture engine owns the server/browser/data-root lifecycle.
    import capture_demo_video_screenshots as capture
    wanted = {s['capture'] for d in definitions for s in d['scenes']}
    for namespace, available in (('overview', capture.FRAMES), ('series', capture.DOCUMENTATION_FRAMES)):
        items = [f for f in available if namespace + ':' + f.id in wanted]
        if not items:
            continue
        destination = work / 'capture-review' / namespace
        records = capture.capture(items, destination, 'purple-gold', replay_prefix=namespace == 'overview')
        video.write_json(destination / 'capture-report.json', records)
        video.write_json(destination / 'proposed-hashes.json', {
            namespace + ':' + f.id: {'image': str((destination / f.filename).relative_to(ROOT)),
                                    'sha256': video.sha256(destination / f.filename)} for f in items})
    return {'status': 'captured for review; canonical screenshots unchanged'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('list', 'validate', 'export', 'capture', 'narrate', 'preview', 'build', 'verify', 'delivery'))
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--videos', help='Comma-separated IDs; playlist order is preserved')
    parser.add_argument('--work-dir', type=Path, default=OUTPUT)
    parser.add_argument('--base-url', default=tts.DEFAULT_BASE_URL)
    parser.add_argument('--force', action='store_true', help='Rebuild current masters; does not regenerate current audio')
    parser.add_argument('--require-audio', action='store_true')
    parser.add_argument('--preview', action='store_true', help='With verify, inspect silent previews instead of narrated masters')
    args = parser.parse_args(argv)
    try:
        index, definitions, captures = load_series()
        require(not args.preview or args.action == 'verify', '--preview applies only to verify')
        if args.action == 'list':
            for d in definitions:
                print(f"{d['id']}: {d['title']} ({len(d['scenes'])} scenes)")
            return 0
        selected = select(definitions, args.videos, args.all)
        work = args.work_dir.resolve()
        require(work.is_relative_to((ROOT / 'build').resolve()), 'Work directory must be below build/')
        if args.action == 'capture':
            print(json.dumps(capture_selected(selected, captures, work), indent=2))
            return 0
        media = video.prerequisites() if args.action in ('preview', 'build', 'verify', 'delivery') or args.require_audio else None
        results, failed = {}, False
        for definition in selected:
            identifier = definition['id']
            try:
                directory = output_directory(work, identifier)
                if args.action == 'validate':
                    if args.require_audio:
                        _, stale = audio_status(definition, directory)
                        require(not stale, '\n'.join(reason for _, reason in stale))
                        video.audio_inputs(definition['scenes'], directory / 'audio', media,
                                           known_scene_labels={s['id'] for s in definition['scenes']})
                    results[identifier] = {'status': 'valid'}
                    continue
                export_definition(definition, directory)
                if args.action == 'export':
                    results[identifier] = {'status': 'exported; chapter times await real audio'}
                elif args.action == 'narrate':
                    current, stale = audio_status(definition, directory)
                    if stale:
                        tts.generate_scenes(tts.KokoroClient(args.base_url), [s for s, _ in stale],
                                            directory / 'audio', VOICE, SPEED, force=True)
                    results[identifier] = {'status': 'narration ready', 'reused': current,
                                           'generated': [s['id'] for s, _ in stale]}
                elif args.action == 'preview':
                    # Clearly separate silent editorial previews from narrated masters.
                    scenes = [dict(s, target_seconds=max(s['target_seconds'], s['narration_words'] / 135 * 60 + .6))
                              for s in definition['scenes']]
                    rows = video.timeline(scenes)
                    video.render(rows, directory / 'silent-preview.mp4', media, project=ROOT,
                                 overwrite=True, motion='none')
                    results[identifier] = {'status': 'silent preview', 'duration_seconds': sum(r['frames'] for r in rows) / video.FPS}
                elif args.action == 'build':
                    results[identifier] = build_one(definition, directory, media, args.force)
                elif args.action == 'verify':
                    results[identifier] = verify_one(definition, directory, media, args.preview)
                elif args.action == 'delivery':
                    results[identifier] = delivery_one(definition, directory, media)
            except (video.BuildError, OSError) as exc:
                failed = True
                results[identifier] = {'status': 'failed', 'error': str(exc)}
                print(f'{identifier}: {exc}', file=sys.stderr, flush=True)
        if args.action != 'validate':
            work.mkdir(parents=True, exist_ok=True)
            video.write_json(work / (args.action + '-report.json'), results)
        print(json.dumps(results, indent=2))
        return int(failed)
    except (video.BuildError, OSError, KeyError, TypeError) as exc:
        print(f'Series error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
