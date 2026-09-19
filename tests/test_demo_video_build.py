"""Deterministic video planning plus a small real FFmpeg smoke test; no DLMS server."""
import importlib.util
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('demo_video_build', ROOT / 'tools/build_demo_video.py')
video = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(video)


@pytest.fixture(scope='module')
def manifest():
    return video.production_manifest()


@pytest.fixture
def copied_project(tmp_path):
    project = tmp_path / 'project with spaces'
    project.mkdir()
    for name in ('NARRATION.md', 'NARRATION_PLAIN.txt', 'video-manifest.json'):
        shutil.copyfile(video.PROJECT / name, project / name)
    (project / 'captures').symlink_to(video.PROJECT / 'captures', target_is_directory=True)
    return project


def test_cuts_and_editorial_durations(manifest):
    main = video.select_scenes(manifest, 'main')
    long = video.select_scenes(manifest, 'long')
    assert len(manifest['scenes']) == 36
    assert [s['id'] for s in main] == [i for i in range(1, 37) if i not in {17, 20, 35}]
    assert [s['id'] for s in long] == [i for i in range(1, 37) if i not in {17, 35}]
    assert sum(s['target_seconds'] for s in main) == 375
    assert sum(s['target_seconds'] for s in long) == 388
    assert sum(s['narration_words'] for s in main) == 797
    assert sum(s['narration_words'] for s in long) == 826
    assert manifest == video.production_manifest()  # no timestamps/unstable iteration


@pytest.mark.parametrize('filename,old,new,error', [
    ('NARRATION.md', '**Target:** 11 sec', '**Target:** soon', 'target'),
    ('NARRATION.md', 'Essential — KEEP', 'Essential — MAYBE', 'status'),
    ('NARRATION.md', 'Slow 2% push', 'Dramatic spin', 'motion'),
    ('NARRATION.md', '> DLMS is', '> Changed DLMS is', 'word count'),
    ('NARRATION_PLAIN.txt', 'DLMS is', 'Altered DLMS is', 'differs'),
])
def test_editorial_drift_is_rejected(copied_project, filename, old, new, error):
    path = copied_project / filename
    path.write_text(path.read_text().replace(old, new, 1))
    with pytest.raises(video.BuildError, match=error):
        video.production_manifest(copied_project)


def test_capture_hash_drift_rejected(copied_project):
    path = copied_project / 'video-manifest.json'
    data = json.loads(path.read_text())
    data[0]['sha256'] = '0' * 64
    video.write_json(path, data)
    with pytest.raises(video.BuildError, match='changed screenshot'):
        video.production_manifest(copied_project)


def test_exports_are_exact_and_repeatable(tmp_path, manifest):
    for cut, count in [('main', 33), ('long', 34)]:
        destination = video.export_pack(manifest, cut, tmp_path)
        index = json.loads((destination / 'index.json').read_text())
        assert len(list(destination.glob('*.txt'))) == count
        assert len(index['scenes']) == count
        before = {p.name: p.read_bytes() for p in destination.iterdir()}
        for scene in video.select_scenes(manifest, cut):
            assert (destination / scene['text_filename']).read_text() == scene['narration'] + '\n'
            assert scene['audio_filename'] == f"{scene['id']:03}.wav"
        video.export_pack(manifest, cut, tmp_path)
        assert before == {p.name: p.read_bytes() for p in destination.iterdir()}
    assert json.loads((tmp_path / 'production-manifest.json').read_text()) == manifest


def test_missing_prerequisites(monkeypatch):
    monkeypatch.setattr(video.shutil, 'which', lambda name: None)
    with pytest.raises(video.BuildError, match='ffmpeg, ffprobe'):
        video.prerequisites()


def test_missing_encoder(monkeypatch):
    monkeypatch.setattr(video.shutil, 'which', lambda name: '/bin/' + name)
    monkeypatch.setattr(video, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 0, '', ''))
    with pytest.raises(video.BuildError, match='libx264'):
        video.prerequisites()


def test_audio_missing_and_mapping(tmp_path, manifest):
    scenes = video.select_scenes(manifest, 'main')
    (tmp_path / '001-dashboard.wav').write_bytes(b'bad')
    (tmp_path / '002.mp3').write_bytes(b'bad')
    (tmp_path / '999.wav').write_bytes(b'bad')
    with pytest.raises(video.BuildError) as exc:
        video.audio_inputs(scenes, tmp_path, {})
    message = str(exc.value)
    assert '001-dashboard.wav' in message and '002.mp3' in message and '999.wav' in message
    assert 'Scene 001: missing 001.wav' in message
    assert 'Scene 033: missing 033.wav' in message
    assert 'Scene 017:' not in message and 'Scene 020:' not in message and 'Scene 035:' not in message


def test_audio_probe_mapping_excludes_unused(tmp_path, manifest, monkeypatch):
    scenes = video.select_scenes(manifest, 'main')
    for s in manifest['scenes']:
        (tmp_path / s['audio_filename']).write_bytes(b'fixture')
    calls = []

    def fake_probe(path, media):
        calls.append(path.name)
        return {'streams': [{'codec_type': 'audio', 'codec_name': 'pcm_s16le', 'channels': 1, 'duration': '1.123'}],
                'format': {'format_name': 'wav'}}

    monkeypatch.setattr(video, 'probe', fake_probe)
    monkeypatch.setattr(video, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 0, '', ''))
    clips = video.audio_inputs(scenes, tmp_path, {'ffmpeg': 'ffmpeg'})
    assert len(clips) == 33
    assert '020.wav' not in calls
    assert clips[1]['seconds'] == 1.123
    assert Path(clips[1]['path']).name == '001.wav'


@pytest.mark.parametrize('duration', ['nan', 'inf', '0', '-1'])
def test_invalid_audio_duration(tmp_path, manifest, monkeypatch, duration):
    (tmp_path / '001.wav').write_bytes(b'bad')
    monkeypatch.setattr(video, 'probe', lambda *a: {
        'streams': [{'codec_type': 'audio', 'codec_name': 'pcm_s16le', 'channels': 1, 'duration': duration}],
        'format': {'format_name': 'wav'}})
    with pytest.raises(video.BuildError, match='malformed 001.wav'):
        video.audio_inputs(manifest['scenes'][:1], tmp_path, {})


def test_timeline_audio_never_truncated(manifest):
    scenes = [manifest['scenes'][0], manifest['scenes'][5]]
    clips = {1: {'seconds': 14.123}, 6: {'seconds': 2.0}}
    rows = video.timeline(scenes, clips)
    assert rows[0]['frames'] == math.ceil((14.123 + .6) * 30)
    assert rows[1]['frames'] == 300  # editorial viewing time preserved
    assert rows[1]['start_frame'] == rows[0]['frames']
    assert rows[1]['audio_lead_frames'] == 5
    for row in rows:
        end = row['audio_lead_frames'] / 30 + row['audio']['seconds']
        assert end + .6 <= row['duration_seconds'] + 1e-8
        assert end < row['duration_seconds'] - row['fade_out_frames'] / 30
    assert video.timeline(scenes, clips, 1.0)[0]['frames'] > rows[0]['frames']
    for value in [0, -1, math.nan, math.inf]:
        with pytest.raises(video.BuildError):
            video.timeline(scenes, clips, value)


def test_srt_uses_audio_boundaries_not_target_estimates(manifest):
    scenes = [manifest['scenes'][0], manifest['scenes'][5]]
    rows = video.timeline(scenes, {1: {'seconds': 2.25}, 6: {'seconds': 3.5}})
    srt = video.subtitles(rows)
    assert '00:00:00,000 --> 00:00:02,250' in srt
    assert '00:00:11,167 --> 00:00:14,667' in srt
    assert scenes[0]['narration'] in srt
    assert '00:00:11,000' not in srt  # no captions during the visual tail
    assert video.srt_timestamp(3661.9996) == '01:01:02,000'
    with pytest.raises(video.BuildError, match='real per-scene audio'):
        video.subtitles(video.timeline(scenes))


def test_motion_and_frame_fades(manifest):
    rows = video.timeline([manifest['scenes'][0], manifest['scenes'][5]])
    assert 'zoompan' in video.video_filter(rows[0])
    assert '0.02' in video.video_filter(rows[0])
    assert 'zoompan' not in video.video_filter(rows[1])
    assert 'fade=t=in:s=0:n=5' in video.video_filter(rows[1])
    closing = video.timeline([manifest['scenes'][-1]])[0]
    assert '1.02-0.02' in video.video_filter(closing)


def test_chapter_boundaries_match_editorial_notes(manifest):
    documented = {s['id'] for s in manifest['scenes'] if '0.3-second' in s['production_note']}
    assert documented == video.CHAPTER_STARTS


def test_subprocess_paths_with_spaces(monkeypatch):
    seen = []

    def fake_run(args, **kwargs):
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, '', '')

    monkeypatch.setattr(video.subprocess, 'run', fake_run)
    video.run(['ffprobe', Path('/tmp/narrator takes/001.wav')])
    assert seen[0][0][-1] == '/tmp/narrator takes/001.wav'
    assert 'shell' not in seen[0][1]
    assert seen[0][1]['timeout'] == 600


def test_cleanup_and_previous_output_preserved_on_failure(tmp_path, manifest, monkeypatch):
    output = tmp_path / 'existing.mp4'
    output.write_bytes(b'prior output')
    monkeypatch.setattr(video, 'run', lambda *a, **kw: (_ for _ in ()).throw(video.BuildError('encoder failed')))
    with pytest.raises(video.BuildError, match='encoder failed'):
        video.render(video.timeline(manifest['scenes'][:1]), output, {'ffmpeg': 'ffmpeg'}, overwrite=True)
    assert output.read_bytes() == b'prior output'
    assert not list(tmp_path.glob('.render-*'))


def test_output_guard_before_render(tmp_path, manifest):
    output = tmp_path / 'existing.mp4'
    output.write_bytes(b'prior')
    with pytest.raises(video.BuildError, match='already exists'):
        video.render(video.timeline(manifest['scenes'][:1]), output, {})


def test_work_directory_guard(capsys):
    assert video.main(['export', '--work-dir', str(video.PROJECT)]) == 2
    assert 'build/' in capsys.readouterr().err


def write_test_tone(path, seconds, amplitude=3000):
    """Test signal only, never narration; lives in pytest's disposable directory."""
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b''.join(struct.pack('<h', int(amplitude * math.sin(2 * math.pi * 440 * n / 48000)))
                                for n in range(round(seconds * 48000))))


@pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='FFmpeg media smoke prerequisites unavailable')
def test_real_media_smoke(tmp_path, manifest):
    media = video.prerequisites()
    audio = tmp_path / 'audio with spaces'
    audio.mkdir()
    scenes = [dict(manifest['scenes'][0], target_seconds=1), dict(manifest['scenes'][5], target_seconds=1)]
    write_test_tone(audio / '001.wav', 2.2)
    write_test_tone(audio / '006.wav', 2.4, amplitude=900)
    clips = video.audio_inputs(scenes, audio, media)
    rows = video.timeline(scenes, clips)
    output = tmp_path / 'output with spaces' / 'test-signal.mp4'
    report = video.render(rows, output, media, mux_subtitles=True)
    assert all(value['input_i'] != '-inf' for value in report['loudness_measurement'].values())
    data = video.verify_output(output, rows, media, narrated=True, mux_subtitles=True)
    assert len(data['streams']) == 3
    assert output.with_suffix('.srt').read_text() == video.subtitles(rows)
    assert not list(output.parent.glob('.render-*'))
    assert all(video.sha256(Path(clip['path'])) == clip['sha256'] for clip in clips.values())
    decoded = tmp_path / 'decoded.wav'
    video.run(video.ffmpeg(media) + ['-i', output, '-map', '0:a:0', '-c:a', 'pcm_s16le', decoded])
    with wave.open(str(decoded), 'rb') as wav:
        samples = struct.unpack('<' + 'h' * wav.getnframes(), wav.readframes(wav.getnframes()))

    def rms(start, stop):
        segment = samples[round(start * 48000):round(stop * 48000)]
        return math.sqrt(sum(n*n for n in segment) / len(segment))

    # Differently recorded levels become comparable; padding remains silent.
    second_start = (rows[1]['start_frame'] + rows[1]['audio_lead_frames']) / 30
    assert abs(20 * math.log10(rms(.4, 1.4) / rms(second_start+.4, second_start+1.4))) < 1
    assert rms(2.35, 2.6) < 10
    # A truly malformed input must fail ffprobe/decode validation.
    (audio / '001.wav').write_bytes(b'not a WAV file')
    with pytest.raises(video.BuildError, match='malformed 001.wav'):
        video.audio_inputs(scenes, audio, media)


def test_audition_export_exact_repeatable(tmp_path, manifest):
    before_manifest = json.dumps(manifest, sort_keys=True)
    destination = video.export_audition(manifest, tmp_path / 'work with spaces')
    index = json.loads((destination / 'manifest.json').read_text())
    assert index['scene_order'] == [1, 13, 14]
    assert index['total_words'] == 77
    assert index['target_seconds'] == 36
    assert sorted(p.name for p in destination.glob('[0-9]*.txt')) == ['001.txt', '013.txt', '014.txt']
    for scene in index['scenes']:
        authoritative = manifest['scenes'][scene['id'] - 1]
        assert scene == authoritative
        assert (destination / scene['text_filename']).read_text() == authoritative['narration'] + '\n'
        assert scene['audio_filename'] == f"{scene['id']:03}.wav"
    before = {p.name: p.read_bytes() for p in destination.iterdir() if p.is_file()}
    video.export_audition(manifest, tmp_path / 'work with spaces')
    assert before == {p.name: p.read_bytes() for p in destination.iterdir() if p.is_file()}
    assert not list((destination / 'audio').iterdir())
    assert json.dumps(manifest, sort_keys=True) == before_manifest


@pytest.mark.parametrize('ids', [(1, 13), (1, 13, 13), (1, 17, 14), (1, 20, 14), (14, 13, 1)])
def test_invalid_audition_selection_rejected(monkeypatch, manifest, ids):
    monkeypatch.setattr(video, 'AUDITION_SCENE_IDS', ids)
    with pytest.raises(video.BuildError, match='exactly three ordered main-cut'):
        video.audition_scenes(manifest)


@pytest.mark.parametrize('directory_exists', [False, True])
def test_audition_missing_audio(monkeypatch, tmp_path, manifest, capsys, directory_exists):
    monkeypatch.setattr(video, 'ROOT', tmp_path)
    monkeypatch.setattr(video, 'production_manifest', lambda: manifest)
    monkeypatch.setattr(video, 'prerequisites', lambda: {})
    monkeypatch.setattr(video, 'render', lambda *a, **kw: pytest.fail('Must not render without real audio'))
    work = tmp_path / 'build/work with spaces'
    if directory_exists:
        (work / 'voice-audition/audio').mkdir(parents=True)
    assert video.main(['build', '--audition', '--work-dir', str(work)]) == 2
    message = capsys.readouterr().err
    for name in ('001.wav', '013.wav', '014.wav'):
        assert name in message
    assert '002.wav' not in message
    assert not list(work.glob('*.mp4'))


@pytest.mark.parametrize('audition,cut,count', [(True, 'main', 3), (False, 'main', 33), (False, 'long', 34)])
def test_build_dispatch_preserves_audio_contract(monkeypatch, tmp_path, manifest, audition, cut, count):
    monkeypatch.setattr(video, 'ROOT', tmp_path)
    monkeypatch.setattr(video, 'production_manifest', lambda: manifest)
    monkeypatch.setattr(video, 'prerequisites', lambda: {})
    work = tmp_path / 'build/work with spaces'
    expected_audio = work / ('voice-audition/audio' if audition else 'audio')
    expected_audio.mkdir(parents=True)

    def inputs(scenes, directory, media):
        assert directory == expected_audio
        assert len(scenes) == count
        if audition:
            assert [s['id'] for s in scenes] == [1, 13, 14]
        assert all(s['audio_filename'] == f"{s['id']:03}.wav" for s in scenes)
        return {s['id']: {'path': str(directory / s['audio_filename']), 'seconds': 12.5} for s in scenes}

    def render(rows, output, media, **kwargs):
        assert len(rows) == count
        assert kwargs['normalization'] == 'ebu'
        assert all(r['duration_seconds'] >= 13.1 for r in rows)
        assert all(r['audio'] is not None for r in rows)
        if audition:
            assert output == work / 'DLMS-3.2-voice-audition.mp4'
            assert [r['motion'] for r in rows] == ['push', 'static', 'static']
            assert rows[2]['fade_in_frames'] == video.FADE_FRAMES
        return {'duration_seconds': sum(r['duration_seconds'] for r in rows)}

    monkeypatch.setattr(video, 'audio_inputs', inputs)
    monkeypatch.setattr(video, 'render', render)
    args = ['build', '--cut', cut, '--work-dir', str(work)]
    assert video.main(args + (['--audition'] if audition else [])) == 0


@pytest.mark.parametrize('args', [['preview', '--audition'], ['export', '--audition', '--cut', 'long']])
def test_incompatible_audition_options(manifest, monkeypatch, capsys, args):
    monkeypatch.setattr(video, 'production_manifest', lambda: manifest)
    assert video.main(args) == 2
    assert '--audition uses main-cut scenes' in capsys.readouterr().err


@pytest.mark.parametrize('audio_set,output_name', [
    ('af_nicole', 'DLMS-3.2-voice-audition-nicole.mp4'),
    ('af_heart', 'DLMS-3.2-voice-audition-heart.mp4'),
    ('candidate_a', 'DLMS-3.2-voice-audition-candidate_a.mp4'),
])
def test_audition_audio_set_dispatch(monkeypatch, tmp_path, manifest, audio_set, output_name):
    monkeypatch.setattr(video, 'ROOT', tmp_path)
    monkeypatch.setattr(video, 'production_manifest', lambda: manifest)
    monkeypatch.setattr(video, 'prerequisites', lambda: {})
    work = tmp_path / 'build/demo-video'
    expected_audio = work / 'voice-audition/candidates' / audio_set
    expected_audio.mkdir(parents=True)

    def inputs(scenes, directory, media):
        assert directory == expected_audio
        return {s['id']: {'path': str(directory / s['audio_filename']), 'seconds': 10.0}
                for s in scenes}

    def render(rows, output, media, **kwargs):
        assert output == work / output_name
        assert [r['id'] for r in rows] == [1, 13, 14]
        return {'duration_seconds': sum(r['duration_seconds'] for r in rows)}

    monkeypatch.setattr(video, 'audio_inputs', inputs)
    monkeypatch.setattr(video, 'render', render)
    assert video.main(['build', '--audition', '--audio-set', audio_set,
                       '--work-dir', str(work)]) == 0


@pytest.mark.parametrize('args', [
    ['build', '--audio-set', 'af_nicole'],
    ['build', '--audition', '--audio-set', '../nicole'],
    ['build', '--audition', '--audio-set', 'af_nicole', '--audio-dir', 'clips'],
])
def test_invalid_audio_set_options(args, capsys):
    assert video.main(args) == 2
    assert '--audio-set requires --audition' in capsys.readouterr().err
