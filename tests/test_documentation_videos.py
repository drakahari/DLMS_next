"""Series metadata, incremental provenance and shared-renderer regression gates."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import wave

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    spec = importlib.util.spec_from_file_location('documentation_videos_test', ROOT / 'tools/build_documentation_videos.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def copied_series(tmp_path):
    target = tmp_path / 'series'
    shutil.copytree(ROOT / 'docs/demo-video/series', target, ignore=shutil.ignore_patterns('captures'))
    return target


def edit_json(path, mutate):
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data))


def test_canonical_series_is_valid_and_ordered(tool):
    index, videos, captures = tool.load_series()
    assert index['voice'] == 'af_heart'
    assert len(videos) == 6
    assert len({d['id'] for d in videos}) == 6
    assert len(captures) == 47
    assert sum(len(d['scenes']) for d in videos) == 39
    assert all(s['motion'] == 'static' and s['transition_in'] == 'cut' for d in videos for s in d['scenes'])
    assert tool.load_series() == (index, videos, captures)


def test_capture_recipes_are_opt_in_and_resolvable(tool, monkeypatch, capsys):
    import capture_demo_video_screenshots as capture
    monkeypatch.setattr(capture, 'capture', lambda *a, **kw: pytest.fail('browser should not start'))
    assert capture.main(['--documentation', '--list', '--only', '101,104']) == 0
    assert [r['id'] for r in json.loads(capsys.readouterr().out)] == ['101', '104']
    assert len(capture.FRAMES) == 43
    _, _, catalog = tool.load_series()
    available = {'overview:' + f.id for f in capture.FRAMES} | {'series:' + f.id for f in capture.DOCUMENTATION_FRAMES}
    assert set(catalog) <= available
    with pytest.raises(SystemExit):
        capture.main(['--documentation', '--replay-prefix', '--list'])


@pytest.mark.parametrize('mutation,message', [
    (lambda d: d.update(id='../overview'), 'identifier'),
    (lambda d: d.update(manual_refs=['docs/user-manual/missing.md']), 'Missing resource'),
    (lambda d: d.update(manual_refs=['docs/user-manual/06-taking-quizzes.md#missing-heading']), 'anchor'),
    (lambda d: d.update(target_seconds=[float('nan'), 180]), 'duration range'),
    (lambda d: d['scenes'][0].update(capture='overview:999'), 'unknown capture'),
    (lambda d: d['scenes'][0].update(narration=''), 'narration'),
    (lambda d: d['scenes'][0].update(narration='two\nparagraphs'), 'paragraph'),
    (lambda d: d['scenes'][0].update(minimum_seconds=True), 'visual minimum'),
    (lambda d: d['scenes'][0].update(minimum_seconds=float('inf')), 'visual minimum'),
    (lambda d: d['scenes'][0].pop('chapter'), 'first scene'),
    (lambda d: d['scenes'][1].update(id='001'), 'duplicate scene'),
    (lambda d: d.update(thumbnail_capture='overview:036'), 'thumbnail'),
    (lambda d: d.update(youtube_title='x' * 100), '100 characters'),
])
def test_bad_definition_fails_closed(tool, copied_series, mutation, message):
    edit_json(copied_series / 'imports-and-repair/video.json', mutation)
    with pytest.raises(tool.video.BuildError, match=message):
        tool.load_series(copied_series)


def test_duplicate_video_and_escaping_definition(tool, copied_series):
    path = copied_series / 'index.json'
    original = path.read_text()
    edit_json(path, lambda d: d['videos'].append(d['videos'][0]))
    with pytest.raises(tool.video.BuildError, match='Duplicate'):
        tool.load_series(copied_series)
    path.write_text(original)
    edit_json(path, lambda d: d.update(videos=['../outside.json']))
    with pytest.raises(tool.video.BuildError, match='escapes'):
        tool.load_series(copied_series)


def test_capture_hash_and_duplicate_key(tool, copied_series):
    path = copied_series / 'captures.json'
    original = path.read_text()
    edit_json(path, lambda d: d[0].update(sha256='0' * 64))
    with pytest.raises(tool.video.BuildError, match='hash changed'):
        tool.load_series(copied_series)
    path.write_text(original)
    edit_json(path, lambda d: d.append(d[0]))
    with pytest.raises(tool.video.BuildError, match='Duplicate'):
        tool.load_series(copied_series)


def test_selection_and_deterministic_paths(tool):
    _, definitions, _ = tool.load_series()
    first, second = definitions[:2]
    assert tool.select(definitions, all_videos=True) == definitions
    assert tool.select(definitions, second['id']) == [second]
    assert tool.select(definitions, second['id'] + ',' + first['id']) == [first, second]
    for requested, all_videos in [(None, False), ('missing', False), ('study-and-exam,', False),
                                  ('study-and-exam,study-and-exam', False), ('study-and-exam', True)]:
        with pytest.raises(tool.video.BuildError):
            tool.select(definitions, requested, all_videos)
    assert tool.output_directory(tool.OUTPUT, first['id']) == tool.OUTPUT / first['id']
    with pytest.raises(tool.video.BuildError):
        tool.output_directory(ROOT / 'docs/demo-video', first['id'])
    with pytest.raises(tool.video.BuildError):
        tool.output_directory(tool.OUTPUT, '../overview')


def test_list_validate_have_no_network_or_render_side_effects(tool, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('side effect')
    monkeypatch.setattr(tool.tts, 'KokoroClient', forbidden)
    monkeypatch.setattr(tool.video, 'render', forbidden)
    monkeypatch.setattr(tool.video, 'prerequisites', forbidden)
    monkeypatch.setattr(tool.video, 'write_json', forbidden)
    assert tool.main(['list']) == 0
    assert tool.main(['validate', '--all']) == 0
    assert tool.main(['validate', '--videos', 'study-and-exam']) == 0
    assert tool.main(['validate', '--videos', 'typo']) == 1


def test_alpha_ids_subtitles_and_chapters(tool):
    _, definitions, _ = tool.load_series()
    scenes = copy.deepcopy(definitions[0]['scenes'][:3])
    for scene, label in zip(scenes, ('001', '001A', '101')):
        scene.update(id=label, chapter=scene['title'], target_seconds=12)
    clips = {s['id']: {'seconds': 11.25} for s in scenes}
    rows = tool.video.timeline(scenes, clips)
    assert [r['id'] for r in rows] == ['001', '001A', '101']
    assert [r['start_frame'] for r in rows] == [0, 360, 720]
    assert tool.chapters(rows).splitlines()[1].startswith('00:12 ')
    assert tool.video.subtitles(rows).count(' --> ') == 3
    assert all('scale=' not in tool.video.video_filter(r) and 'fade=' not in tool.video.video_filter(r) for r in rows)
    rows[1]['start_frame'] = 100
    with pytest.raises(tool.video.BuildError, match='ten seconds'):
        tool.chapters(rows)


def test_incremental_audio_rejects_changed_text_and_payload(tool, tmp_path, monkeypatch):
    _, definitions, _ = tool.load_series()
    definition = copy.deepcopy(definitions[0])
    definition['scenes'] = definition['scenes'][:2]
    destination = tmp_path / 'audio'
    destination.mkdir()
    # Provenance is exercised with test PCM, never presented as production speech.
    monkeypatch.setattr(tool.tts, 'validate_wav', lambda path: 1.0)
    for scene in definition['scenes']:
        path = destination / scene['audio_filename']
        path.write_bytes(b'test-only-pcm')
        tool.video.write_json(path.with_suffix('.generation.json'), {
            'source_text': scene['narration'], 'synthesis_text': tool.tts.synthesis_text(scene['narration']),
            'voice': tool.VOICE, 'speed': tool.SPEED, 'audio_filename': path.name, 'sha256': tool.video.sha256(path)})
    assert tool.audio_status(definition, tmp_path) == (['001', '002'], [])
    definition['scenes'][0]['narration'] += ' Changed.'
    current, stale = tool.audio_status(definition, tmp_path)
    assert current == ['002'] and [s['id'] for s, _ in stale] == ['001']
    (destination / '002.wav').write_bytes(b'changed')
    assert len(tool.audio_status(definition, tmp_path)[1]) == 2


def test_build_cache_checks_every_artifact(tool, tmp_path):
    names = ('master.mp4', 'master.srt', 'master.timeline.json')
    for name in names:
        (tmp_path / name).write_text(name)
    tool.video.write_json(tmp_path / 'build-record.json', {
        'fingerprint': 'current', 'outputs': {n: tool.video.sha256(tmp_path / n) for n in names}})
    assert tool.cache_valid(tmp_path, 'current')
    assert not tool.cache_valid(tmp_path, 'old')
    (tmp_path / 'master.srt').write_text('changed')
    assert not tool.cache_valid(tmp_path, 'current')


def test_batch_reports_failure_and_continues(tool, monkeypatch, tmp_path):
    _, definitions, captures = tool.load_series()
    monkeypatch.setattr(tool, 'load_series', lambda: ({}, definitions[:2], captures))
    monkeypatch.setattr(tool, 'output_directory', lambda root, name: tmp_path / name)
    monkeypatch.setattr(tool.video, 'prerequisites', lambda: {})
    calls = []
    def build(definition, *args):
        calls.append(definition['id'])
        if len(calls) == 1:
            raise tool.video.BuildError('intentional test failure')
        return {'status': 'built'}
    monkeypatch.setattr(tool, 'build_one', build)
    reports = []
    monkeypatch.setattr(tool.video, 'write_json', lambda p, data: reports.append((p, data)))
    # No production media path is touched: export is redirected to pytest temp.
    assert tool.main(['build', '--all']) == 1
    assert calls == [d['id'] for d in definitions[:2]]
    assert reports[-1][1][calls[0]]['status'] == 'failed'
    assert reports[-1][1][calls[1]]['status'] == 'built'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg not installed')
def test_shared_audio_supports_scoped_series_ids(tool, tmp_path):
    with wave.open(str(tmp_path / '101.wav'), 'wb') as wav:
        wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        wav.writeframes(struct.pack('<h', 200) * 48000)
    scenes = [{'id': '101', 'audio_filename': '101.wav'}]
    media = tool.video.prerequisites()
    assert tool.video.audio_inputs(scenes, tmp_path, media, known_scene_labels={'101'})['101']['seconds'] == 1
    with pytest.raises(tool.video.BuildError, match='unmapped'):
        tool.video.audio_inputs(scenes, tmp_path, media)


def test_overview_contract_unchanged(tool):
    manifest = tool.video.production_manifest()
    assert len(tool.video.select_scenes(manifest, 'main')) == 40
    assert len(tool.video.select_scenes(manifest, 'long')) == 41
    assert sum(s['narration_words'] for s in tool.video.select_scenes(manifest, 'main')) == 911
    assert [s['id'] for s in tool.video.audition_scenes(manifest)] == [1, 13, 14]


def test_narrate_only_passes_stale_scenes(tool, monkeypatch, tmp_path):
    _, definitions, captures = tool.load_series()
    definition = definitions[0]
    monkeypatch.setattr(tool, 'load_series', lambda: ({}, [definition], captures))
    monkeypatch.setattr(tool, 'output_directory', lambda *args: tmp_path)
    monkeypatch.setattr(tool, 'audio_status', lambda *args: (['001'], [(definition['scenes'][1], 'text changed')]))
    monkeypatch.setattr(tool.video, 'write_json', lambda *args: None)
    monkeypatch.setattr(tool.tts, 'KokoroClient', lambda *args: 'local-test-client')
    calls = []
    monkeypatch.setattr(tool.tts, 'generate_scenes', lambda *args, **kwargs: calls.append((args, kwargs)))
    assert tool.main(['narrate', '--all']) == 0
    assert [s['id'] for s in calls[0][0][1]] == ['002']
    assert calls[0][0][3:5] == ('af_heart', 1.0)
    assert calls[0][1] == {'force': True}
    monkeypatch.setattr(tool, 'audio_status', lambda *args: (['001', '002'], []))
    calls.clear()
    assert tool.main(['narrate', '--all']) == 0
    assert calls == []


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg not installed')
def test_real_series_verification_checks_source_pixels(tool, tmp_path):
    _, definitions, _ = tool.load_series()
    definition = copy.deepcopy(definitions[0])
    definition['scenes'] = [dict(s, target_seconds=1) for s in definition['scenes'][:2]]
    media = tool.video.prerequisites()
    rows = tool.video.timeline(definition['scenes'])
    tool.video.render(rows, tmp_path / 'silent-preview.mp4', media, project=ROOT)
    result = tool.verify_one(definition, tmp_path, media, preview=True)
    assert result['source_pixel_equality'] and result['frames'] == 60
    definition['scenes'][0]['narration'] += ' Changed.'
    with pytest.raises(tool.video.BuildError, match='stale narration'):
        tool.verify_one(definition, tmp_path, media, preview=True)
