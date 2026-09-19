#!/usr/bin/env python3
"""Optional local Kokoro adapter; no DLMS runtime or model dependencies."""
import argparse
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import wave

import build_demo_video as video

DEFAULT_BASE_URL = 'http://127.0.0.1:7860'
DEFAULT_VOICE = 'af_sarah'


def american_voice_ids(data):
    """Normalize speaker IDs/maps or the richer /tts/voices inventory."""
    error = 'Unexpected Kokoro voices response; expected American English speaker IDs or voice objects.'
    if not isinstance(data, dict):
        raise video.BuildError(error)
    if 'speakers' in data:
        speakers = data['speakers']
        ids = list(speakers.values()) if isinstance(speakers, dict) else speakers
    else:
        voices = data.get('voices')
        if not isinstance(voices, list) or not all(
                isinstance(v, dict) and isinstance(v.get('id'), str)
                and isinstance(v.get('language'), str) for v in voices):
            raise video.BuildError(error)
        ids = [v['id'] for v in voices if v['language'] == 'a']
    if not isinstance(ids, list) or not ids or not all(
            isinstance(v, str) and re.fullmatch(r'a[fm]_[a-z0-9_]+', v) for v in ids):
        raise video.BuildError(error)
    return sorted(set(ids))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_base_url(value):
    parsed = urllib.parse.urlsplit(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
        local = address.is_loopback or address.is_private
    except ValueError:
        local = parsed.hostname == 'localhost'
    if (parsed.scheme not in {'http', 'https'} or not local or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise video.BuildError('Use a local HTTP(S) base URL: localhost, loopback, or a private IP address, without credentials/query/fragment.')
    return value.rstrip('/')


class KokoroClient:
    """Only this adapter knows Kokoro's wire protocol. No proxies or redirects."""
    def __init__(self, base_url, timeout=300):
        self.base_url = local_base_url(base_url)
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, route, payload=None):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(self.base_url + route, data=body,
                                         headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.timeout if body else min(10, self.timeout)) as response:
                if not 200 <= response.status < 300:
                    raise video.BuildError(f'Kokoro HTTP {response.status} at {route}.')
                data = response.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    raise video.BuildError('Kokoro response exceeds the 64 MiB per-scene limit.')
                return data
        except urllib.error.HTTPError as exc:
            detail = exc.read(512).decode('utf-8', errors='replace')
            raise video.BuildError(f'Kokoro HTTP {exc.code} at {route}: {detail}. Check the voice ID and server logs.') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise video.BuildError(f'Kokoro TTS is not reachable at {self.base_url}. Start the local Kokoro container first. ({exc})') from exc

    def json_request(self, route):
        data = self.request(route)
        try:
            return json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise video.BuildError(f'Kokoro returned invalid JSON at {route}.') from exc

    def voices(self):
        # Current servers return a list; retain compatibility with older maps.
        return american_voice_ids(self.json_request('/tts/speakers?language=a'))

    def generate(self, text, voice, speed):
        # Omitted output_format requests the documented default lossless WAV.
        return self.request('/tts/generate', {'text': text, 'voice': voice, 'speed': speed})


def synthesis_text(text):
    """Minimal pronunciation-only substitutions; Anki remains unchanged for audition."""
    for term, spoken in [('DLMS', 'D L M S'), ('AI', 'A I'), ('OCR', 'O C R'), ('API', 'A P I')]:
        text = re.sub(r'\b' + term + r'\b', spoken, text)
    return text


def narration_scenes(audition, cut):
    manifest = video.production_manifest()
    return manifest, video.audition_scenes(manifest) if audition else video.select_scenes(manifest, cut)


def validate_wav(path):
    """Validate actual PCM data, with ffprobe metadata verification when available."""
    try:
        with wave.open(str(path), 'rb') as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            if wav.getnchannels() not in (1, 2) or frames <= 0 or rate <= 0 or wav.getcomptype() != 'NONE':
                raise video.BuildError('Expected nonempty mono/stereo PCM WAV.')
            expected = frames * wav.getnchannels() * wav.getsampwidth()
            if len(wav.readframes(frames)) != expected:
                raise video.BuildError('Truncated WAV audio payload.')
            duration = frames / rate
    except (wave.Error, EOFError) as exc:
        raise video.BuildError('Invalid PCM WAV response; possible HTML/JSON error or unsupported audio format.') from exc
    if shutil.which('ffprobe'):
        data = video.probe(path, {'ffprobe': shutil.which('ffprobe')})
        streams = data.get('streams', [])
        if len(streams) != 1 or not streams[0].get('codec_name', '').startswith('pcm_'):
            raise video.BuildError('ffprobe rejected generated PCM WAV.')
        measured = float(streams[0].get('duration') or data.get('format', {}).get('duration', 0))
        if not math.isfinite(measured) or abs(measured - duration) > 0.05:
            raise video.BuildError('ffprobe duration disagrees with WAV data.')
    return duration


def generate_scenes(client, scenes, destination, voice, speed, force=False):
    paths = [destination / s['audio_filename'] for s in scenes]
    existing = [p.name for p in paths if p.exists() or p.is_symlink()]
    if existing and not force:
        raise video.BuildError('Existing WAVs: ' + ', '.join(existing) + '. Use --force explicitly, or a new --output-set.')
    voices = client.voices()  # Reachability and voice validation before any synthesis.
    if voice not in voices:
        raise video.BuildError(f'Voice {voice!r} is not advertised by this server. Use --list-voices.')
    destination.mkdir(parents=True, exist_ok=True)
    for scene, path in zip(scenes, paths):
        spoken = synthesis_text(scene['narration'])
        print(f"Generating {scene['id']:03} with {voice}...", flush=True)
        audio = client.generate(spoken, voice, speed)
        # Validate before publication; failed requests never replace a good take.
        with tempfile.TemporaryDirectory(prefix='.tts-', dir=destination) as temporary:
            staged = Path(temporary) / path.name
            staged.write_bytes(audio)
            duration = validate_wav(staged)
            if force:
                staged.replace(path)
            else:
                os.link(staged, path)  # Atomic refusal if a concurrent writer created it.
            record = {'scene': scene['id'], 'image': scene['image'], 'voice': voice,
                      'speed': speed, 'base_url': client.base_url,
                      'source_text': scene['narration'], 'synthesis_text': spoken,
                      'duration_seconds': duration, 'audio_filename': path.name,
                      'sha256': video.sha256(path)}
            video.write_json(path.with_suffix('.generation.json'), record)
        print(f'Wrote {path} ({duration:.3f}s)')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--audition', action='store_true')
    mode.add_argument('--cut', choices=('main', 'long'))
    mode.add_argument('--list-voices', action='store_true')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL)
    parser.add_argument('--voice', default=DEFAULT_VOICE)
    parser.add_argument('--speed', type=float, default=1.0, help='Synthesis speed, 0.8–1.2; no post-synthesis stretching.')
    parser.add_argument('--timeout', type=float, default=300, help='Per synthesis request timeout in seconds.')
    parser.add_argument('--output-set', help='Audition candidate directory name, e.g. af_sarah.')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.speed) or not 0.8 <= args.speed <= 1.2:
            raise video.BuildError('--speed must be between 0.8 and 1.2.')
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise video.BuildError('--timeout must be positive and finite.')
        if args.output_set and (not args.audition or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.output_set)):
            raise video.BuildError('--output-set requires --audition and a simple name containing letters, digits, underscores or hyphens.')
        client = KokoroClient(args.base_url, args.timeout)
        if args.list_voices:
            for voice in client.voices():
                print(voice + (' (American female)' if voice.startswith('af_') else ' (American male)'))
            return 0
        manifest, scenes = narration_scenes(args.audition, args.cut)
        work = video.ROOT / 'build/demo-video'
        if args.audition:
            export = video.export_audition(manifest, work)
            # Reuse the exact canonical export, verify before any synthesis transforms.
            for scene in scenes:
                if (export / scene['text_filename']).read_text(encoding='utf-8') != scene['narration'] + '\n':
                    raise video.BuildError('Audition narration export differs from its source.')
            destination = export / 'candidates' / args.output_set if args.output_set else export / 'audio'
        else:
            destination = work / 'audio'
        generate_scenes(client, scenes, destination, args.voice, args.speed, args.force)
        return 0
    except (video.BuildError, OSError, ValueError) as exc:
        if args.verbose:
            raise
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Interrupted; completed clips retained. Use a new set or --force to retry.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
