"""Offline local narration contract tests; HTTP is always mocked."""
import io
import json
from pathlib import Path
import sys
import urllib.error
import wave
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import generate_demo_narration as tts


@pytest.fixture
def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\x01\x00' * 2400)
    return buffer.getvalue()


@pytest.fixture
def scenes():
    return tts.narration_scenes(True, None)[1]


def test_scene_sources_and_contract(scenes, tmp_path):
    manifest, main = tts.narration_scenes(False, 'main')
    _, long = tts.narration_scenes(False, 'long')
    assert len(main) == 33 and len(long) == 34
    assert [s['id'] for s in scenes] == [1, 13, 14]
    assert {s['id'] for s in long} - {s['id'] for s in main} == {20}
    export = tts.video.export_audition(manifest, tmp_path)
    for scene in scenes:
        assert (export / scene['text_filename']).read_text() == scene['narration'] + '\n'
        assert scene['audio_filename'] == f"{scene['id']:03}.wav"
    assert sum(s['narration_words'] for s in main) == 790


def test_transforms():
    assert tts.synthesis_text('DLMS AI Anki OCR API') == (
        '[DLMS](/dˈi ˈɛl ˈɛm ˈɛs/) [AI](/ˈA ˈI/) [Anki](/ˈɑnki/) '
        '[OCR](/ˈO sˈi ˈɑɹ/) [API](/ˈA pˈi ˈI/)')
    assert tts.synthesis_text('D L M S A I O C R A P I') == tts.synthesis_text('DLMS AI OCR API')
    unchanged = 'XDLMS DLMS2 RAID RAPID OCRed APIs Anking _AI_ naïAIve PDF CSV'
    assert tts.synthesis_text(unchanged) == unchanged
    assert tts.synthesis_text('(AI), Anki’s AI-ready workflow.') == (
        '([AI](/ˈA ˈI/)), [Anki](/ˈɑnki/)’s [AI](/ˈA ˈI/)-ready workflow.')
    transformed = tts.synthesis_text('DLMS and Anki use AI. A I is spelled out.')
    assert tts.synthesis_text(transformed) == transformed


def test_pronunciation_dry_run_has_no_network_or_scene_export(monkeypatch, capsys):
    monkeypatch.setattr(tts.KokoroClient, 'request', Mock(side_effect=AssertionError('network')))
    monkeypatch.setattr(tts, 'narration_scenes', Mock(side_effect=AssertionError('scene export')))
    assert tts.main(['--pronunciation-test', '--dry-run', '--voice', 'af_heart']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {'text': tts.synthesis_text(tts.PRONUNCIATION_TEST), 'voice': 'af_heart', 'speed': 1.0}
    assert tts.main(['--cut', 'main', '--dry-run']) == 2
    assert '--dry-run requires --pronunciation-test' in capsys.readouterr().err


def test_pronunciation_clip_is_isolated(monkeypatch, tmp_path, wav_bytes):
    monkeypatch.setattr(tts.video, 'ROOT', tmp_path)
    monkeypatch.setattr(tts, 'narration_scenes', Mock(side_effect=AssertionError('production selection')))
    monkeypatch.setattr(tts.KokoroClient, 'voices', Mock(return_value=['af_heart']))
    generate = Mock(return_value=wav_bytes)
    monkeypatch.setattr(tts.KokoroClient, 'generate', generate)
    assert tts.main(['--pronunciation-test', '--voice', 'af_heart']) == 0
    assert list(tmp_path.rglob('*.wav')) == [tmp_path / 'build/demo-video/pronunciation-test/pronunciation.wav']
    generate.assert_called_once_with(tts.synthesis_text(tts.PRONUNCIATION_TEST), 'af_heart', 1.0)
    assert tts.main(['--pronunciation-test', '--voice', 'af_heart']) == 2
    assert generate.call_count == 1  # overwrite protection remains in force


def test_request_contract(wav_bytes):
    client = tts.KokoroClient('http://127.0.0.1:9876/prefix/')
    response = Mock(status=200)
    response.read.return_value = wav_bytes
    client.opener.open = Mock()
    client.opener.open.return_value.__enter__ = Mock(return_value=response)
    client.opener.open.return_value.__exit__ = Mock(return_value=False)
    assert client.generate('Exact text', 'af_nicole', 0.95) == wav_bytes
    request = client.opener.open.call_args.args[0]
    assert request.full_url == 'http://127.0.0.1:9876/prefix/tts/generate'
    assert json.loads(request.data) == {'text': 'Exact text', 'voice': 'af_nicole', 'speed': 0.95}


@pytest.mark.parametrize('error,match', [
    (urllib.error.URLError('connection refused'), 'Start the local Kokoro container'),
    (urllib.error.HTTPError('url', 400, 'Bad request', {}, io.BytesIO(b'Invalid voice')), 'HTTP 400'),
    (TimeoutError('timed out'), 'not reachable'),
])
def test_http_errors(error, match):
    client = tts.KokoroClient(tts.DEFAULT_BASE_URL)
    client.opener.open = Mock(side_effect=error)
    with pytest.raises(tts.video.BuildError, match=match):
        client.voices()


def test_discovery(monkeypatch):
    client = tts.KokoroClient(tts.DEFAULT_BASE_URL)
    request = Mock(return_value={'speakers': {'Sarah': 'af_sarah', 'Nicole': 'af_nicole'}})
    monkeypatch.setattr(client, 'json_request', request)
    assert client.voices() == ['af_nicole', 'af_sarah']
    request.assert_called_once_with('/tts/speakers?language=a')
    request.return_value = {'error': 'unavailable'}
    with pytest.raises(tts.video.BuildError, match='Unexpected'):
        client.voices()


def test_generate_force_and_metadata(tmp_path, scenes, wav_bytes):
    client = Mock(base_url=tts.DEFAULT_BASE_URL)
    client.voices.return_value = ['af_sarah', 'af_nicole']
    client.generate.return_value = wav_bytes
    tts.generate_scenes(client, scenes, tmp_path, 'af_nicole', 1.0)
    assert sorted(p.name for p in tmp_path.glob('*.wav')) == ['001.wav', '013.wav', '014.wav']
    assert len(client.generate.call_args_list) == 3
    assert client.generate.call_args_list[0].args == (tts.synthesis_text(scenes[0]['narration']), 'af_nicole', 1.0)
    record = json.loads((tmp_path / '001.generation.json').read_text())
    assert record['duration_seconds'] == 0.1
    assert record['source_text'] == scenes[0]['narration']
    with pytest.raises(tts.video.BuildError, match='--force'):
        tts.generate_scenes(client, scenes, tmp_path, 'af_sarah', 1.0)
    client.generate.return_value = b'<html>error</html>'
    with pytest.raises(tts.video.BuildError, match='Invalid PCM WAV'):
        tts.generate_scenes(client, scenes, tmp_path, 'af_sarah', 1.0, True)
    assert (tmp_path / '001.wav').read_bytes() == wav_bytes
    client.generate.return_value = wav_bytes
    tts.generate_scenes(client, scenes, tmp_path, 'af_sarah', 1.0, True)
    assert json.loads((tmp_path / '001.generation.json').read_text())['voice'] == 'af_sarah'
    assert not list(tmp_path.glob('.tts-*'))


@pytest.mark.parametrize('payload', [b'', b'{}', b'<html>error</html>', b'RIFF0000WAVE'])
def test_invalid_audio(tmp_path, payload):
    path = tmp_path / 'bad.wav'
    path.write_bytes(payload)
    with pytest.raises(tts.video.BuildError):
        tts.validate_wav(path)


def test_truncation_and_no_ffprobe(tmp_path, wav_bytes, monkeypatch):
    path = tmp_path / 'test.wav'
    monkeypatch.setattr(tts.shutil, 'which', lambda _: None)
    path.write_bytes(wav_bytes)
    assert tts.validate_wav(path) == 0.1
    path.write_bytes(wav_bytes[:-10])
    with pytest.raises(tts.video.BuildError, match='Truncated'):
        tts.validate_wav(path)


def test_unknown_voice_no_generation(tmp_path, scenes):
    client = Mock()
    client.voices.return_value = ['af_heart']
    with pytest.raises(tts.video.BuildError, match='not advertised'):
        tts.generate_scenes(client, scenes, tmp_path, 'af_sarah', 1)
    client.generate.assert_not_called()


@pytest.mark.parametrize('args,suffix,count', [
    (['--audition'], 'voice-audition/audio', 3),
    (['--audition', '--output-set', 'sarah'], 'voice-audition/candidates/sarah', 3),
    (['--cut', 'main'], 'audio', 33), (['--cut', 'long'], 'audio', 34),
])
def test_cli_destinations(tmp_path, monkeypatch, args, suffix, count):
    monkeypatch.setattr(tts.video, 'ROOT', tmp_path)
    generation = Mock()
    monkeypatch.setattr(tts, 'generate_scenes', generation)
    assert tts.main(args) == 0
    call = generation.call_args.args
    assert len(call[1]) == count
    assert call[2] == tmp_path / 'build/demo-video' / suffix
    assert call[3:5] == ('af_sarah', 1.0)


def test_cli_failure_is_concise(monkeypatch, capsys):
    monkeypatch.setattr(tts.KokoroClient, 'voices', Mock(side_effect=tts.video.BuildError('Start the local Kokoro container first.')))
    assert tts.main(['--list-voices']) == 2
    assert 'Traceback' not in capsys.readouterr().err


@pytest.mark.parametrize('args', [
    ['--audition', '--speed', 'nan'], ['--audition', '--speed', '2'],
    ['--audition', '--output-set', '../bad'], ['--cut', 'main', '--output-set', 'bad'],
    ['--list-voices', '--base-url', 'https://example.com'],
])
def test_invalid_cli_options(args):
    assert tts.main(args) == 2


@pytest.mark.parametrize('response', [
    {'language': 'a', 'language_name': 'American English',
     'speakers': ['af_sarah', 'af_heart', 'am_adam', 'af_sarah']},
    {'voices': [
        {'id': 'af_sarah', 'name': 'Sarah', 'language': 'a', 'language_name': 'American English'},
        {'id': 'af_heart', 'name': 'Heart', 'language': 'a'},
        {'id': 'am_adam', 'name': 'Adam', 'language': 'a'},
        {'id': 'bf_emma', 'name': 'Emma', 'language': 'b'},
    ]},
    {'speakers': {'Sarah': 'af_sarah', 'Heart': 'af_heart', 'Adam': 'am_adam'}},
])
def test_live_discovery_shapes(response, monkeypatch, tmp_path, scenes, wav_bytes, capsys):
    monkeypatch.setattr(tts.KokoroClient, 'json_request', lambda self, route: response)
    client = tts.KokoroClient(tts.DEFAULT_BASE_URL)
    assert client.voices() == ['af_heart', 'af_sarah', 'am_adam']
    assert tts.main(['--list-voices']) == 0
    assert 'af_sarah (American female)' in capsys.readouterr().out
    client.generate = Mock(return_value=wav_bytes)
    tts.generate_scenes(client, scenes, tmp_path / 'accepted', 'af_sarah', 1.0)
    assert client.generate.call_count == 3
    with pytest.raises(tts.video.BuildError, match="Voice 'af_unknown' is not advertised"):
        tts.generate_scenes(client, scenes, tmp_path / 'rejected', 'af_unknown', 1.0)
    assert client.generate.call_count == 3


@pytest.mark.parametrize('response', [
    None, {}, {'speakers': []}, {'speakers': 'af_sarah'},
    {'speakers': ['af_sarah', 42]}, {'speakers': ['bf_emma']},
    {'voices': ['af_sarah']}, {'voices': [{'id': 'af_sarah'}]},
    {'voices': [{'id': None, 'language': 'a'}]},
    {'voices': [{'id': 'bf_emma', 'language': 'b'}]},
])
def test_malformed_discovery_shapes(response):
    with pytest.raises(tts.video.BuildError, match='Unexpected Kokoro voices response'):
        tts.american_voice_ids(response)
