"""Preserve validated playable hotspots during derived-page maintenance.

The database grading surrogate cannot reconstruct spatial content. This module
does not repair old quizzes or use a source pack as a substitute for a quiz.
"""
import json
import os
from pathlib import Path
import stat


class HotspotArtifactUnavailable(ValueError):
    """The existing authoritative assessment cannot safely be preserved."""


def preserved_hotspot_bytes(conn, quiz_id, path, *, validate_shape, resolve_image, validate_image):
    """Return exact validated bytes, or None for an ordinary DB-derived quiz.

    A hotspot marker with absent/non-hotspot content is refused, including
    previously degraded artifacts. No database or source-pack writes occur.
    """
    from .review_marks import _context_rows

    rows = conn.execute(
        'SELECT question_text FROM questions WHERE quiz_id=? ORDER BY question_number,id',
        (quiz_id,),
    ).fetchall()
    surrogates = [str(row[0]).endswith(' [Image hotspot]') for row in rows]
    try:
        source = Path(path)
        if not stat.S_ISREG(source.lstat().st_mode):
            raise ValueError('Playable content is not a regular file')
        raw = source.read_bytes()
        payload = json.loads(raw)
    except (OSError, ValueError) as exc:
        if any(surrogates):
            raise HotspotArtifactUnavailable() from exc
        return None
    has_hotspot = isinstance(payload, list) and any(
        isinstance(item, dict) and item.get('type') == 'hotspot' for item in payload
    )
    if not any(surrogates) and not has_hotspot:
        return None
    try:
        if not isinstance(payload, list) or len(payload) != len(rows):
            raise ValueError('Question count differs')
        # Verify all question positions, saved answers, text, explanation and
        # media against the same projection used by server-owned marks.
        _context_rows(conn.cursor(), quiz_id, payload)
        checked_images = set()
        for surrogate, item in zip(surrogates, payload):
            if surrogate and item.get('type') != 'hotspot':
                raise ValueError('Spatial content is unavailable')
            if item.get('type') != 'hotspot':
                continue
            target = item.get('target')
            validate_shape(target)  # validation only: never normalize saved geometry
            if target.get('type') not in {'circle', 'polygon'}:
                raise ValueError('Unsupported playable geometry')
            coordinates = ([target.get(key) for key in ('x', 'y', 'radius')]
                           if target['type'] == 'circle'
                           else [value for point in target['points'] for value in point])
            if any(type(value) not in (int, float) for value in coordinates):
                raise ValueError('Playable coordinates must be numeric')
            if not isinstance(item.get('target_label'), str) or not item['target_label'].strip():
                raise ValueError('Target label is unavailable')
            image = resolve_image(item.get('image_url'))
            if not image or not Path(image).is_file():
                raise ValueError('Required image is unavailable')
            if image not in checked_images:
                validate_image(image)
                checked_images.add(image)
        return raw
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise HotspotArtifactUnavailable() from exc


def write_preserved_hotspot_json(path, raw):
    """Write the bytes already validated under the caller's maintenance lock."""
    with open(path, 'wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
