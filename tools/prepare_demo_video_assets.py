#!/usr/bin/env python3
"""Build labeled contact sheets and editing manifests; never alter captures."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from capture_demo_video_screenshots import PROJECT, V2_FRAMES, V3_ADDITIONS


V3_PLACEMENT = {
    '013A': ('013', 'Show a complete matching interaction with placed answers and immediate correctness feedback.'),
    '013B': ('013A', 'Show that hotspot questions are answered by selecting a region on an image.'),
    '028A': ('028', 'Distinguish Content Packs as the validation and package-management workspace.'),
    '028B': ('028A', 'Show Study Packs turning installed matching, image, and prepared-question datasets into practice.'),
}


def _capture_records(captures):
    records = {}
    for path in sorted(captures.glob('capture-*.json'), key=lambda p: p.stat().st_mtime_ns):
        metadata = json.loads(path.read_text())
        assert metadata['theme'] == 'purple-gold'
        for record in metadata['captures']:
            records[record['id']] = (record, path.name)
    return records


def _font(size):
    font_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    return ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default(size=size)


def prepare_v3_additions():
    captures = PROJECT / 'captures'
    records = _capture_records(captures)
    sheet = Image.new('RGB', (1968, 1224), '#160d26')
    draw = ImageDraw.Draw(sheet)
    font = _font(23)
    manifest = []
    for offset, frame in enumerate(V3_ADDITIONS):
        path = captures / frame.filename
        record, sidecar = records[frame.id]
        with Image.open(path) as source:
            assert source.size == (1920, 1080), frame.filename
            thumbnail = source.convert('RGB').resize((960, 540), Image.Resampling.LANCZOS)
        x, y = 16 + (offset % 2) * 976, 16 + (offset // 2) * 600
        draw.text((x, y), frame.filename, fill='#f3d468', font=font)
        sheet.paste(thumbnail, (x, y + 42))
        after, narration_objective = V3_PLACEMENT[frame.id]
        manifest.append({
            'id': frame.id, 'image': 'captures/' + frame.filename,
            'purpose': frame.title, 'proposed_after': after,
            'duration_estimate': float(frame.seconds), 'essential': frame.essential,
            'narration_objective': narration_objective, 'state': frame.state,
            'fixture': frame.fixture, 'theme': 'purple-gold',
            'width': 1920, 'height': 1080, 'device_scale': 1,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'capture_metadata': 'captures/' + sidecar,
            'evidence_anchor': record['evidence_anchor'],
            'fixture_version': record['fixture_version'],
        })
    sheet.save(PROJECT / 'v3-additions-contact-sheet.png')
    payload = {
        'status': 'approved-v3-sequencing; narration integrated; audio, subtitles, and video not regenerated',
        'v2_runtime_seconds': 403.6,
        'v2_editorial_target_seconds': 390,
        'v3_editorial_target_seconds': 425,
        'new_scene_target_seconds': sum(item.seconds for item in V3_ADDITIONS),
        'redistributed_existing_target_seconds': -9,
        'net_editorial_target_change_seconds': 35,
        'estimated_v3_runtime_seconds': 438.6,
        'scenes': manifest,
    }
    (PROJECT / 'v3-additions-manifest.json').write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
    print('Validated 4 V3 additions; wrote v3-additions-contact-sheet.png and v3-additions-manifest.json')


def prepare_v2():
    captures = PROJECT / 'captures'
    objectives = {}
    for line in (PROJECT / 'STORYBOARD.md').read_text().splitlines():
        cells = [c.strip() for c in line.split('|')]
        if len(cells) >= 5 and cells[1].isdigit():
            objectives[cells[1]] = cells[2]
    records = _capture_records(captures)
    font = _font(23)
    manifest = []
    for start in range(0, len(V2_FRAMES), 6):
        sheet = Image.new('RGB', (1968, 1824), '#160d26')
        draw = ImageDraw.Draw(sheet)
        for offset, frame in enumerate(V2_FRAMES[start:start+6]):
            path = captures / frame.filename
            record, sidecar = records[frame.id]
            with Image.open(path) as image:
                assert image.size == (1920, 1080), frame.filename
                thumbnail = image.convert('RGB').resize((960,540), Image.Resampling.LANCZOS)
            x, y = 16+(offset % 2)*976, 16+(offset//2)*600
            draw.text((x,y), frame.filename, fill='#f3d468', font=font)
            sheet.paste(thumbnail, (x,y+42))
            manifest.append(dict(
                id=int(frame.id), image='captures/'+frame.filename,
                purpose=frame.title, duration_estimate=float(frame.seconds),
                optional=not frame.essential,
                focus=frame.title, capture_focus_selector=frame.focus or None,
                motion_suggestion='Static hold; optional gentle zoom toward the focus. Keep labels and controls visible.',
                narration_objective=objectives[frame.id], state=frame.state,
                theme='purple-gold', width=1920, height=1080, device_scale=1,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                capture_metadata='captures/'+sidecar,
                evidence_anchor=record['evidence_anchor'], fixture_version=record['fixture_version'],
                editorial_note={17:'Optional: overlaps the intelligence overview.',20:'Optional: retain if question-versus-topic timing needs explanation.',33:'Optional: extends the Question Tools AI discussion into content creation.',35:'Optional: broad settings tour overlaps backup/local-first closing.'}.get(int(frame.id), ''),
            ))
        sheet.save(PROJECT / f'contact-sheet-{start//6+1:02}.png')
    (PROJECT/'video-manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    print(f'Validated {len(manifest)} frames; wrote six contact sheets and video-manifest.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v3-additions', action='store_true', help='Build only the V3 additions handoff; preserve V2 assets and manifest')
    args = parser.parse_args(argv)
    if args.v3_additions:
        prepare_v3_additions()
    else:
        prepare_v2()


if __name__ == '__main__':
    main()
