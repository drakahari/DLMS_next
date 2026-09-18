#!/usr/bin/env python3
"""Build labeled contact sheets and an editing manifest; never alter captures."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from capture_demo_video_screenshots import FRAMES, PROJECT


def main():
    captures = PROJECT / 'captures'
    objectives = {}
    for line in (PROJECT / 'STORYBOARD.md').read_text().splitlines():
        cells = [c.strip() for c in line.split('|')]
        if len(cells) >= 5 and cells[1].isdigit():
            objectives[cells[1]] = cells[2]
    records = {}
    for path in sorted(captures.glob('capture-*.json'), key=lambda p: p.stat().st_mtime_ns):
        metadata = json.loads(path.read_text())
        assert metadata['theme'] == 'purple-gold'
        for record in metadata['captures']:
            records[record['id']] = (record, path.name)
    font_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    font = ImageFont.truetype(str(font_path), 23) if font_path.exists() else ImageFont.load_default(size=23)
    manifest = []
    for start in range(0, len(FRAMES), 6):
        sheet = Image.new('RGB', (1968, 1824), '#160d26')
        draw = ImageDraw.Draw(sheet)
        for offset, frame in enumerate(FRAMES[start:start+6]):
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


if __name__ == '__main__':
    main()
