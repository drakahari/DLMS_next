"""Conservative layout inference for screenshot OCR observations.

The OCR engine deliberately returns only untrusted word observations.  This
module turns those observations into *review drafts*, never authoritative quiz
records.  Every OCR-derived question requires explicit correctness
confirmation before the Smart PDF workflow can save it as active content.
"""

from __future__ import annotations

from io import BytesIO
from dataclasses import dataclass
from math import atan2, hypot, pi
from statistics import median
import re
from typing import Any, Iterable

from PIL import Image, UnidentifiedImageError


OCR_QUESTION_MAX_CHOICES = 26
OCR_QUESTION_MAX_RECORDS = 50
OCR_QUESTION_MAX_TEXT_CHARS = 250_000
OCR_LABELS = tuple(chr(ord("A") + index) for index in range(26))

_QUESTION_MARKER_RE = re.compile(
    r"^\s*(?:question|q)\s*(\d+)\s*[:.)-]?\s*(.*)$", re.IGNORECASE
)
_EXPLICIT_CHOICE_RE = re.compile(
    r"^\s*(?:(?:[@©®Oo0QØ○◯◉●□☐☑()]|\|)\s*)?"
    r"([A-Z]|\d{1,2})\s*[.)\]:-]\s+(.+?)\s*$",
    re.IGNORECASE,
)
_RELAXED_CHOICE_RE = re.compile(
    r"^\s*(?P<control>(?:(?:[@©®Oo0QØ○◯◉●□☐☑()]|\|)\s*){0,2})"
    r"(?P<label>[A-Z]|8|©)(?:(?P<separator>[.)\]:-])\s*|\s+)"
    r"(?P<text>.+?)\s*$",
    re.IGNORECASE,
)
_TRAILING_RESULT_GLYPH_RE = re.compile(
    r"(?:\s+(?:\((?:x|/|v|7|✓|✔|✕|×)?\)|"
    r"(?:x|/|v|7|✓|✔|✕|×)\)|[|])\s*)+$",
    re.IGNORECASE,
)
_RESULT_US_INITIALISM_RE = re.compile(r"^US\.(?=\s|$)")
_RESULT_IOCS_CONFUSION_RE = re.compile(r"^1[0O][¢C]s$", re.IGNORECASE)
_ANSWER_KEY_RE = re.compile(
    r"\bcorrect\s+answers?\s*[:\-]\s*([^\n]+)", re.IGNORECASE
)
_FEEDBACK_KEY_RE = re.compile(
    r"\b(?:the\s+)?correct\s+answers?\s+(?:is|are)\s+([^.;\n]+)",
    re.IGNORECASE,
)
_MULTIPLE_MODE_RE = re.compile(
    r"\b(?:select|choose)\s+(?:all(?:\s+that\s+apply)?|two|three|multiple|\d+)\b|"
    r"\bmultiple\s+(?:answers?|responses?)\b",
    re.IGNORECASE,
)
_EXPLANATION_HEADING_RE = re.compile(
    r"^\s*(explanation|rationale|feedback|why\s+this\s+is\s+correct|"
    r"why\s+the\s+other\s+options\s+are\s+incorrect)\s*[:\-]?\s*(.*)$",
    re.IGNORECASE,
)
_CHOICE_FEEDBACK_RE = re.compile(
    r"^\s*([A-Z])\s*(?:feedback|explanation)\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)
_OBVIOUS_CHROME_RE = re.compile(
    r"^\s*(?:next|previous|back|submit|continue|explain\s+this\s+further|"
    r"menu|navigation|home)\s*[>»→]?\s*$",
    re.IGNORECASE,
)
_RESULT_BANNER_RE = re.compile(r"^\s*(correct|incorrect)\s*[!.]?\s*$", re.IGNORECASE)
_CONTROL_GLYPH_PREFIX_RE = re.compile(
    r"^\s*(?:[@©®Oo0QØ○◯◉●□☐☑()]|\|)\s+(.+?)\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class OCRLine:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True)
class OCRChoiceRow:
    line: OCRLine
    raw_label: str
    text: str
    strict: bool
    control_prefix: bool
    trailing_result_glyph: bool


def _explanation_heading(text: str):
    """Match a heading, tolerating one isolated OCR control-glyph token."""

    match = _EXPLANATION_HEADING_RE.match(text)
    if match:
        return match
    noisy = _CONTROL_GLYPH_PREFIX_RE.match(text)
    return _EXPLANATION_HEADING_RE.match(noisy.group(1)) if noisy else None


def _color_distance(first: tuple[int, ...], second: tuple[int, ...]) -> float:
    return hypot(
        hypot(int(first[0]) - int(second[0]), int(first[1]) - int(second[1])),
        int(first[2]) - int(second[2]),
    )


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length_squared = dx * dx + dy * dy
    if not length_squared:
        return hypot(px - sx, py - sy), 0.0
    position = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length_squared))
    nearest = (sx + position * dx, sy + position * dy)
    return hypot(px - nearest[0], py - nearest[1]), position


def _marker_template_score(
    points: list[tuple[float, float]],
    segments: tuple[tuple[tuple[float, float], tuple[float, float]], ...],
) -> float:
    if len(points) < 5:
        return 0.0
    distances = []
    coverage = [[False, False, False] for _segment in segments]
    for point in points:
        candidates = [_point_segment_distance(point, *segment) for segment in segments]
        segment_index, (distance, position) = min(
            enumerate(candidates), key=lambda item: item[1][0]
        )
        distances.append(distance)
        if distance <= 0.14:
            coverage[segment_index][min(2, int(position * 3))] = True
    if not all(all(segment_coverage) for segment_coverage in coverage):
        return 0.0
    return sum(max(0.0, 1.0 - distance / 0.18) for distance in distances) / len(distances)


def _classify_marker_component(
    image: Image.Image,
    component: list[tuple[int, int]],
    *,
    max_icon_size: int = 72,
) -> str | None:
    left = min(point[0] for point in component)
    top = min(point[1] for point in component)
    right = max(point[0] for point in component) + 1
    bottom = max(point[1] for point in component) + 1
    width = right - left
    height = bottom - top
    if not (
        12 <= width <= max_icon_size
        and 12 <= height <= max_icon_size
        and 0.65 <= width / height <= 1.5
    ):
        return None

    active = set(component)
    density = len(active) / (width * height)
    center_x = left + (width - 1) / 2
    center_y = top + (height - 1) / 2
    radius_x = max(1.0, width / 2)
    radius_y = max(1.0, height / 2)
    outer_sectors = set()
    outside_circle = 0
    for x, y in component:
        offset_x = (x - center_x) / radius_x
        offset_y = (y - center_y) / radius_y
        radius = hypot(offset_x, offset_y)
        if radius > 1.12:
            outside_circle += 1
        if 0.62 <= radius <= 1.08:
            angle = (atan2(offset_y, offset_x) + pi) / (2 * pi)
            outer_sectors.add(min(7, int(angle * 8)))
    if len(outer_sectors) < 6 or outside_circle / len(component) > 0.08:
        return None

    interior = []
    if density >= 0.55:
        fill_pixels = [image.getpixel(point) for point in component]
        fill = tuple(
            int(median(pixel[channel] for pixel in fill_pixels)) for channel in range(3)
        )
        for y in range(top, bottom):
            for x in range(left, right):
                normalized_radius = hypot(
                    (x - center_x) / radius_x, (y - center_y) / radius_y
                )
                if normalized_radius > 0.72:
                    continue
                pixel = image.getpixel((x, y))
                if _color_distance(pixel, fill) >= 75:
                    interior.append(((x - left) / width, (y - top) / height))
    else:
        for x, y in component:
            normalized_radius = hypot(
                (x - center_x) / radius_x, (y - center_y) / radius_y
            )
            if normalized_radius <= 0.62:
                interior.append(((x - left) / width, (y - top) / height))

    x_score = _marker_template_score(
        interior,
        (((0.23, 0.23), (0.77, 0.77)), ((0.77, 0.23), (0.23, 0.77))),
    )
    check_score = _marker_template_score(
        interior,
        (((0.18, 0.52), (0.42, 0.75)), ((0.42, 0.75), (0.82, 0.25))),
    )
    best = max(x_score, check_score)
    if best < 0.42 or abs(x_score - check_score) < 0.08:
        return None
    return "x" if x_score > check_score else "check"


def _marker_components(image: Image.Image, box: tuple[int, int, int, int]):
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return []
    background_samples = [
        image.getpixel((left, top)),
        image.getpixel((left, bottom - 1)),
        image.getpixel((right - 1, top)),
        image.getpixel((right - 1, bottom - 1)),
    ]
    background = tuple(
        int(median(pixel[channel] for pixel in background_samples))
        for channel in range(3)
    )
    active = set()
    for y in range(top, bottom):
        for x in range(left, right):
            pixel = image.getpixel((x, y))
            chroma = max(pixel) - min(pixel)
            if _color_distance(pixel, background) >= 65 and (
                chroma >= 35 or max(pixel) <= 95
            ):
                active.add((x, y))

    components = []
    while active:
        pending = [active.pop()]
        component = []
        while pending:
            point = pending.pop()
            component.append(point)
            x, y = point
            for neighbour in (
                (x - 1, y - 1),
                (x, y - 1),
                (x + 1, y - 1),
                (x - 1, y),
                (x + 1, y),
                (x - 1, y + 1),
                (x, y + 1),
                (x + 1, y + 1),
            ):
                if neighbour in active:
                    active.remove(neighbour)
                    pending.append(neighbour)
        if len(component) >= 20:
            components.append(component)
    return components


def _merge_nested_marker_components(components, *, max_icon_size: int = 72):
    """Join an outlined circle and its disconnected interior glyph."""

    remaining = sorted(components, key=len, reverse=True)
    merged = []
    while remaining:
        group = list(remaining.pop(0))
        left = min(point[0] for point in group)
        top = min(point[1] for point in group)
        right = max(point[0] for point in group) + 1
        bottom = max(point[1] for point in group) + 1
        retained = []
        for component in remaining:
            component_left = min(point[0] for point in component)
            component_top = min(point[1] for point in component)
            component_right = max(point[0] for point in component) + 1
            component_bottom = max(point[1] for point in component) + 1
            combined = (
                min(left, component_left),
                min(top, component_top),
                max(right, component_right),
                max(bottom, component_bottom),
            )
            center_x = (component_left + component_right) / 2
            center_y = (component_top + component_bottom) / 2
            nested = left <= center_x <= right and top <= center_y <= bottom
            if (
                nested
                and combined[2] - combined[0] <= max_icon_size
                and combined[3] - combined[1] <= max_icon_size
            ):
                group.extend(component)
                left, top, right, bottom = combined
            else:
                retained.append(component)
        remaining = retained
        merged.append(group)
    return merged


def _row_search_bounds(
    rows: list[OCRChoiceRow], row_index: int, image_height: int
) -> tuple[int, int, float]:
    """Return a row's unique vertical territory and typical center spacing."""

    centers = [row.line.top + row.line.height / 2 for row in rows]
    center = centers[row_index]
    spacings = [
        later - earlier
        for earlier, later in zip(centers, centers[1:])
        if later > earlier
    ]
    typical_spacing = (
        median(spacings)
        if spacings
        else max(rows[row_index].line.height * 2, 32)
    )
    top = (
        (centers[row_index - 1] + center) / 2
        if row_index
        else center - typical_spacing / 2
    )
    bottom = (
        (center + centers[row_index + 1]) / 2
        if row_index + 1 < len(centers)
        else center + typical_spacing / 2
    )
    return max(0, int(top)), min(image_height, int(bottom) + 1), typical_spacing


def detect_visual_result_markers(
    image_bytes: bytes,
    observations: Iterable[Any],
) -> tuple[dict[str, Any], ...]:
    """Find dedicated row-level check/X icons in a reviewed-result screenshot.

    Color is used only to locate a compact candidate. A check/X stroke template,
    far-right placement, unambiguous row geometry, and either an OCR-recognized
    result banner or a bounded question/answer/explanation result layout are
    required before a marker is returned.
    """

    observations = tuple(observations)
    lines = observations_to_lines(observations)
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            source.load()
            image = source.convert("RGB")
    except (OSError, ValueError, UnidentifiedImageError):
        return ()

    source_width = int(_field(observations[0], "source_width", image.width))
    source_height = int(_field(observations[0], "source_height", image.height))
    if image.size != (source_width, source_height):
        return ()

    markers = []
    for segment in _segment_lines(lines):
        first_question_top = min(
            (line.top for line in segment if _looks_like_question(line.text)),
            default=float("inf"),
        )
        result_banner = any(
            line.top < first_question_top and _RESULT_BANNER_RE.match(line.text)
            for line in segment
        )
        answer_rows = _choice_row_sequence(
            segment, source_width=source_width, result_context=True
        )
        if not answer_rows:
            continue
        if not result_banner:
            question_before = any(
                _looks_like_question(line.text)
                and line.top < answer_rows[0].line.top
                for line in segment
            )
            explanation_after = any(
                _explanation_heading(line.text)
                and line.top > answer_rows[-1].line.top
                for line in segment
            )
            if not (question_before and explanation_after):
                continue
        answer_centers = [row.line.top + row.line.height / 2 for row in answer_rows]
        for row_index, row in enumerate(answer_rows):
            row_center = answer_centers[row_index]
            search_top, search_bottom, typical_spacing = _row_search_bounds(
                answer_rows, row_index, image.height
            )
            search_left = int(image.width * 0.67)
            search_box = (
                min(image.width - 1, search_left),
                search_top,
                image.width,
                search_bottom,
            )
            candidates = []
            max_icon_size = min(112, max(72, int(typical_spacing * 0.9)))
            components = _merge_nested_marker_components(
                _marker_components(image, search_box), max_icon_size=max_icon_size
            )
            for component in components:
                kind = _classify_marker_component(
                    image, component, max_icon_size=max_icon_size
                )
                if kind is None:
                    continue
                left = min(point[0] for point in component)
                top = min(point[1] for point in component)
                right = max(point[0] for point in component) + 1
                bottom = max(point[1] for point in component) + 1
                marker_center = top + (bottom - top) / 2
                center_distances = [
                    abs(marker_center - answer_center)
                    for answer_center in answer_centers
                ]
                nearest_distance = min(center_distances)
                if (
                    center_distances[row_index] != nearest_distance
                    or center_distances.count(nearest_distance) != 1
                ):
                    continue
                if abs(marker_center - row_center) > typical_spacing * 0.45:
                    continue
                candidates.append((kind, left, top, right - left, bottom - top))
            if len(candidates) != 1:
                continue
            kind, left, top, width, height = candidates[0]
            markers.append(
                {
                    "kind": kind,
                    "row_left": row.line.left,
                    "row_top": row.line.top,
                    "bounding_box": {
                        "left": left,
                        "top": top,
                        "width": width,
                        "height": height,
                    },
                }
            )
    marker_counts = {}
    for marker in markers:
        box = marker["bounding_box"]
        key = (box["left"], box["top"], box["width"], box["height"])
        marker_counts[key] = marker_counts.get(key, 0) + 1
    return tuple(
        marker
        for marker in markers
        if marker_counts[
            (
                marker["bounding_box"]["left"],
                marker["bounding_box"]["top"],
                marker["bounding_box"]["width"],
                marker["bounding_box"]["height"],
            )
        ]
        == 1
    )


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _box_field(observation: Any, name: str) -> int:
    box = _field(observation, "bounding_box")
    if isinstance(box, dict):
        return int(box.get(name, 0))
    return int(getattr(box, name, 0))


def observations_to_lines(observations: Iterable[Any]) -> list[OCRLine]:
    """Combine bounded word observations into stable visual lines."""

    groups: dict[tuple[int, int, int, int], list[Any]] = {}
    for observation in observations:
        text = str(_field(observation, "text", "") or "").strip()
        if not text:
            continue
        key = (
            int(_field(observation, "page_index", 0)),
            int(_field(observation, "block_id", 0)),
            int(_field(observation, "paragraph_id", 0)),
            int(_field(observation, "line_id", 0)),
        )
        groups.setdefault(key, []).append(observation)

    lines: list[OCRLine] = []
    for words in groups.values():
        words.sort(key=lambda item: (_box_field(item, "left"), _box_field(item, "top")))
        left = min(_box_field(item, "left") for item in words)
        top = min(_box_field(item, "top") for item in words)
        right = max(_box_field(item, "left") + _box_field(item, "width") for item in words)
        bottom = max(_box_field(item, "top") + _box_field(item, "height") for item in words)
        confidences = [float(_field(item, "confidence", 0.0)) for item in words]
        text = " ".join(str(_field(item, "text", "") or "").strip() for item in words)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text).strip()
        lines.append(
            OCRLine(
                text=text,
                left=left,
                top=top,
                width=max(1, right - left),
                height=max(1, bottom - top),
                confidence=sum(confidences) / len(confidences),
            )
        )
    return sorted(lines, key=lambda line: (line.top, line.left))


def _confidence_label(value: float) -> str:
    if value >= 85:
        return "high"
    if value >= 65:
        return "medium"
    return "low"


def _segment_lines(lines: list[OCRLine]) -> list[list[OCRLine]]:
    marker_indexes = [
        index for index, line in enumerate(lines) if _QUESTION_MARKER_RE.match(line.text)
    ]
    if len(marker_indexes) < 2:
        return [lines]
    segments = []
    for position, start in enumerate(marker_indexes):
        end = marker_indexes[position + 1] if position + 1 < len(marker_indexes) else len(lines)
        segments.append(lines[start:end])
    return segments


def _answer_labels(text: str) -> list[str]:
    answers = []
    for token in re.findall(r"\b([A-Z])\b", str(text or "").upper()):
        if token in OCR_LABELS and token not in answers:
            answers.append(token)
    return answers


def _looks_like_question(text: str) -> bool:
    normalized = text.strip().lower()
    return (
        normalized.endswith("?")
        or normalized.startswith(("which ", "what ", "who ", "when ", "where ", "why ", "how "))
        or bool(_MULTIPLE_MODE_RE.search(normalized))
    )


def _choice_row_candidate(line: OCRLine, *, result_context: bool) -> OCRChoiceRow | None:
    strict_match = _EXPLICIT_CHOICE_RE.match(line.text)
    if strict_match:
        text = strict_match.group(2).strip()
        trailing_result_glyph = bool(
            result_context and _TRAILING_RESULT_GLYPH_RE.search(text)
        )
        if trailing_result_glyph:
            text = _TRAILING_RESULT_GLYPH_RE.sub("", text).strip()
        if result_context:
            text = _normalize_result_choice_text(text)
        return OCRChoiceRow(
            line=line,
            raw_label=strict_match.group(1),
            text=text,
            strict=True,
            control_prefix=line.text.lstrip()[:1] in "@©®Oo0QØ○◯◉●□☐☑()|",
            trailing_result_glyph=trailing_result_glyph,
        )

    if not result_context:
        return None
    relaxed_match = _RELAXED_CHOICE_RE.match(line.text)
    if not relaxed_match:
        return None
    text = relaxed_match.group("text").strip()
    trailing_result_glyph = bool(
        result_context and _TRAILING_RESULT_GLYPH_RE.search(text)
    )
    if trailing_result_glyph:
        text = _TRAILING_RESULT_GLYPH_RE.sub("", text).strip()
    text = _normalize_result_choice_text(text)
    return OCRChoiceRow(
        line=line,
        raw_label=relaxed_match.group("label"),
        text=text,
        strict=False,
        control_prefix=bool(relaxed_match.group("control").strip()),
        trailing_result_glyph=trailing_result_glyph,
    )


def _labels_are_contiguous(rows: list[OCRChoiceRow]) -> bool:
    for index, row in enumerate(rows):
        expected = OCR_LABELS[index]
        observed = row.raw_label.upper()
        if observed == "8" and expected == "B":
            continue
        if observed == "©" and expected == "C":
            continue
        if observed != expected:
            return False
    return True


def _row_has_expected_label(row: OCRChoiceRow, index: int) -> bool:
    if index >= len(OCR_LABELS):
        return False
    observed = row.raw_label.upper()
    expected = OCR_LABELS[index]
    return (
        observed == expected
        or (observed == "8" and expected == "B")
        or (observed == "©" and expected == "C")
    )


def _choice_row_sequence(
    lines: list[OCRLine], *, source_width: int, result_context: bool
) -> list[OCRChoiceRow]:
    """Recover one bounded A–Z row sequence without promoting unrelated lists."""

    candidates = {
        index: candidate
        for index, line in enumerate(lines)
        if (candidate := _choice_row_candidate(line, result_context=result_context))
    }
    strict_rows = [candidate for candidate in candidates.values() if candidate.strict]
    if len(strict_rows) >= 2 and len(strict_rows) == len(candidates):
        return strict_rows
    runs: list[list[tuple[int, OCRChoiceRow]]] = []
    current: list[tuple[int, OCRChoiceRow]] = []
    for index in range(len(lines)):
        candidate = candidates.get(index)
        if candidate is None:
            if current:
                runs.append(current)
                current = []
            continue
        if current and not _row_has_expected_label(candidate, len(current)):
            runs.append(current)
            current = []
        if not current and not _row_has_expected_label(candidate, 0):
            continue
        current.append((index, candidate))
    if current:
        runs.append(current)

    plausible = []
    for run in runs:
        rows = [item[1] for item in run]
        if not 2 <= len(rows) <= OCR_QUESTION_MAX_CHOICES:
            continue
        if not _labels_are_contiguous(rows):
            continue
        if not _aligned_choice_block([row.line for row in rows], source_width):
            continue
        start = run[0][0]
        preceding = lines[:start]
        question_before = any(_looks_like_question(line.text) for line in preceding)
        strict_count = sum(row.strict for row in rows)
        control_count = sum(row.control_prefix for row in rows)
        relaxed_supported = (
            len(rows) >= 3
            and question_before
            and (strict_count >= 2 or control_count >= 2)
        )
        if all(row.strict for row in rows) or relaxed_supported:
            plausible.append((start, rows))

    if plausible:
        plausible.sort(key=lambda item: (-len(item[1]), item[0]))
        return plausible[0][1]

    return strict_rows if len(strict_rows) >= 2 else []


def _aligned_choice_block(lines: list[OCRLine], source_width: int) -> bool:
    if not 2 <= len(lines) <= OCR_QUESTION_MAX_CHOICES:
        return False
    lefts = [line.left for line in lines]
    if max(lefts) - min(lefts) > max(60, int(source_width * 0.08)):
        return False
    if len(lines) >= 3:
        gaps = [max(0, lines[index + 1].top - lines[index].bottom) for index in range(len(lines) - 1)]
        typical = median(gaps)
        tolerance = max(20, typical * 1.8)
        if any(abs(gap - typical) > tolerance for gap in gaps):
            return False
    return True


def _source_label(raw_label: str, expected: str) -> tuple[str, str | None]:
    label = raw_label.upper()
    if label == expected:
        return label, None
    if label == "8" and expected == "B":
        return expected, "OCR may have read source label B as 8."
    if label == "©" and expected == "C":
        return expected, "OCR may have read source label C as ©."
    if label.isdigit():
        return expected, f"Numeric or ambiguous source label {label} was normalized by position."
    return expected, f"Source label {label} was normalized to positional label {expected}."


def _normalize_result_choice_text(text: str) -> str:
    """Repair narrowly measured OCR confusions in reviewed-result answer rows."""

    text = _RESULT_US_INITIALISM_RE.sub("U.S.", text)
    if _RESULT_IOCS_CONFUSION_RE.fullmatch(text):
        return "IOCs"
    return text


def _infer_one_question(
    lines: list[OCRLine],
    *,
    source_id: str,
    source_index: int,
    source_width: int,
    visual_markers: Iterable[Any] = (),
) -> dict[str, Any] | None:
    if not lines:
        return None
    visual_markers = tuple(visual_markers)
    issues: list[str] = []
    unassigned: list[str] = []
    content_lines: list[OCRLine] = []
    for line in lines:
        if _OBVIOUS_CHROME_RE.match(line.text):
            unassigned.append(line.text)
        else:
            content_lines.append(line)
    if not content_lines:
        return None

    first_explicit_top = min(
        (
            line.top
            for line in content_lines
            if _EXPLICIT_CHOICE_RE.match(line.text)
        ),
        default=float("inf"),
    )
    first_question_top = min(
        (line.top for line in content_lines if _looks_like_question(line.text)),
        default=first_explicit_top,
    )
    result_banner = None
    without_banner = []
    for line in content_lines:
        banner_match = _RESULT_BANNER_RE.match(line.text)
        if (
            result_banner is None
            and banner_match
            and line.top < min(first_question_top, first_explicit_top)
        ):
            result_banner = banner_match.group(1).lower()
            continue
        without_banner.append(line)
    content_lines = without_banner
    if not content_lines:
        return None

    marker = _QUESTION_MARKER_RE.match(content_lines[0].text)
    if marker:
        remainder = marker.group(2).strip()
        if remainder:
            content_lines[0] = OCRLine(
                remainder,
                content_lines[0].left,
                content_lines[0].top,
                content_lines[0].width,
                content_lines[0].height,
                content_lines[0].confidence,
            )
        else:
            unassigned.append(content_lines.pop(0).text)

    result_context = bool(result_banner or visual_markers)
    key_texts: list[str] = []
    explanation_lines: list[str] = []
    choice_feedback: dict[str, str] = {}
    body_lines: list[OCRLine] = []
    in_explanation = False
    question_seen = False
    post_question_unlabelled_lines = 0
    explicit_rows_seen = 0
    for line in content_lines:
        feedback_match = _CHOICE_FEEDBACK_RE.match(line.text)
        heading_match = _explanation_heading(line.text)
        if feedback_match:
            choice_feedback[feedback_match.group(1).upper()] = feedback_match.group(2).strip()
            continue
        explanation_context = (
            explicit_rows_seen >= 2
            or (question_seen and post_question_unlabelled_lines >= 2)
        )
        if heading_match and explanation_context:
            in_explanation = True
            remainder = heading_match.group(2).strip()
            if remainder:
                explanation_lines.append(remainder)
            continue
        if _ANSWER_KEY_RE.search(line.text):
            key_texts.append(line.text)
            continue
        if in_explanation:
            explanation_lines.append(line.text)
        else:
            body_lines.append(line)
            if _choice_row_candidate(line, result_context=result_context):
                explicit_rows_seen += 1
            elif question_seen:
                post_question_unlabelled_lines += 1
            if _looks_like_question(line.text):
                question_seen = True

    choice_rows = _choice_row_sequence(
        body_lines,
        source_width=source_width,
        result_context=result_context,
    )
    explicit = [(row.line, row.raw_label, row.text) for row in choice_rows]

    question_lines: list[OCRLine] = []
    choice_texts: list[str] = []
    label_origin = "unknown"
    structure_confidence = "low"
    if len(explicit) >= 2:
        first_choice = body_lines.index(explicit[0][0])
        explicit_lines = {id(item[0]) for item in explicit}
        question_lines = body_lines[:first_choice]
        for index, (_line, raw_label, text) in enumerate(explicit):
            if index < OCR_QUESTION_MAX_CHOICES:
                expected = OCR_LABELS[index]
                _label, warning = _source_label(raw_label, expected)
                if warning:
                    issues.append(warning)
            choice_texts.append(text)
        for line in body_lines[first_choice:]:
            if id(line) not in explicit_lines:
                unassigned.append(line.text)
        label_origin = "source"
        structure_confidence = "high" if not issues else "medium"
    else:
        question_end = next(
            (index for index, line in enumerate(body_lines) if _looks_like_question(line.text)),
            0,
        )
        question_end += 1
        question_lines = body_lines[:question_end]
        candidates = body_lines[question_end:]
        if _looks_like_question(" ".join(line.text for line in question_lines)) and _aligned_choice_block(
            candidates, source_width
        ):
            choice_texts = [line.text.lstrip("•◦○◉□☐☑- ").strip() for line in candidates]
            label_origin = "inferred"
            structure_confidence = "medium"
            issues.append("Answer labels were inferred from aligned answer rows and require review.")
        else:
            unassigned.extend(line.text for line in candidates)
            issues.append("DLMS could not confidently identify separate answer rows.")

    if len(choice_texts) > OCR_QUESTION_MAX_CHOICES:
        unassigned.extend(choice_texts)
        choice_texts = []
        label_origin = "unknown"
        structure_confidence = "low"
        issues.append(
            "More than 26 likely answer rows were detected; none were truncated. "
            "Reconstruct this question with no more than 26 choices."
        )

    question_text = " ".join(line.text for line in question_lines).strip()
    if not question_text and body_lines:
        question_text = body_lines[0].text
        if body_lines[0].text in unassigned:
            unassigned.remove(body_lines[0].text)

    all_text = "\n".join(line.text for line in content_lines)
    explicit_answers: list[str] = []
    correctness_evidence = "unknown"
    for value in key_texts:
        match = _ANSWER_KEY_RE.search(value)
        if match:
            explicit_answers.extend(_answer_labels(match.group(1)))
    if explicit_answers:
        correctness_evidence = "explicit_source"
    else:
        feedback_match = _FEEDBACK_KEY_RE.search("\n".join(explanation_lines))
        if feedback_match:
            explicit_answers = _answer_labels(feedback_match.group(1))
            if explicit_answers:
                correctness_evidence = "explicit_feedback"
    explicit_answers = list(dict.fromkeys(explicit_answers))
    valid_labels = set(OCR_LABELS[: len(choice_texts)])
    correct_answers = [answer for answer in explicit_answers if answer in valid_labels]
    if len(correct_answers) != len(explicit_answers):
        issues.append("The detected answer key referenced a label outside the detected choices.")

    detected_markers = []
    if result_context and explicit:
        for index, (line, _raw_label, _text) in enumerate(explicit):
            row_markers = [
                marker
                for marker in visual_markers
                if abs(int(_field(marker, "row_top", -10_000)) - line.top) <= 2
                and abs(int(_field(marker, "row_left", -10_000)) - line.left) <= 2
                and str(_field(marker, "kind", "")) in {"check", "x"}
            ]
            if len(row_markers) == 1:
                detected_markers.append(
                    {
                        "label": OCR_LABELS[index],
                        "kind": str(_field(row_markers[0], "kind")),
                    }
                )
    visual_answers = [
        marker["label"] for marker in detected_markers if marker["kind"] == "check"
    ]
    if not correct_answers and visual_answers:
        correct_answers = list(dict.fromkeys(visual_answers))
        correctness_evidence = "visual_result_marker"

    multiple_wording = bool(_MULTIPLE_MODE_RE.search(all_text))
    answer_mode = "multiple" if multiple_wording or len(correct_answers) > 1 else "single"
    if multiple_wording:
        answer_mode_evidence = "explicit_instruction"
    elif correctness_evidence == "explicit_source":
        answer_mode_evidence = "explicit_answer_key"
    elif correctness_evidence in {"explicit_feedback", "visual_result_marker"}:
        answer_mode_evidence = correctness_evidence
    else:
        answer_mode_evidence = "unknown"
    if answer_mode_evidence == "unknown":
        issues.append("Answer mode was not explicit; verify single-answer or multiple-answer mode.")

    text_confidence = _confidence_label(
        sum(line.confidence for line in content_lines) / len(content_lines)
    )
    if text_confidence == "low":
        issues.append("OCR text confidence is low; compare every field with the source image.")

    complete_structure = bool(question_text and 2 <= len(choice_texts) <= 26)
    status = "review" if complete_structure else "incomplete"
    if not complete_structure:
        structure_confidence = "low"

    return {
        "number": source_index,
        "question": question_text,
        "choices": [
            {
                "label": OCR_LABELS[index],
                "text": text,
                "label_origin": label_origin,
            }
            for index, text in enumerate(choice_texts)
        ],
        "correct_answers": correct_answers,
        "answer_mode": answer_mode,
        "answer_mode_evidence": answer_mode_evidence,
        "correctness_confirmation_required": True,
        "correctness_confirmed": False,
        "correctness_evidence": correctness_evidence,
        "declared_answer_text": "\n".join(key_texts),
        "explanation": "\n".join(explanation_lines).strip(),
        "choice_feedback": choice_feedback,
        "pages": [source_index],
        "status": status,
        "issues": list(dict.fromkeys(issues)),
        "ocr_metadata": {
            "source_id": source_id,
            "source_index": source_index,
            "label_origin": label_origin,
            "text_confidence": text_confidence,
            "structure_confidence": structure_confidence,
            "correctness_evidence": correctness_evidence,
            "unassigned_text": "\n".join(dict.fromkeys(unassigned)).strip(),
            "result_banner": result_banner,
            "visual_result_markers": detected_markers,
        },
    }


def infer_screenshot_questions(
    observations: Iterable[Any], *, source_id: str, source_index: int
) -> dict[str, Any]:
    """Return bounded Smart PDF review records for one screenshot."""

    visual_markers: Iterable[Any] = ()
    if isinstance(observations, dict):
        visual_markers = observations.get("visual_markers") or ()
        observations = observations.get("observations") or ()
    observations = tuple(observations)
    if not observations:
        return {"questions": [], "raw_text": "", "warnings": ["No readable OCR text was detected."]}
    source_width = int(_field(observations[0], "source_width", 0))
    lines = observations_to_lines(observations)
    raw_text = "\n".join(line.text for line in lines)
    if len(raw_text) > OCR_QUESTION_MAX_TEXT_CHARS:
        raise ValueError("OCR text exceeds the screenshot review limit.")

    questions = []
    segments = _segment_lines(lines)
    for segment in segments[:OCR_QUESTION_MAX_RECORDS]:
        question = _infer_one_question(
            segment,
            source_id=source_id,
            source_index=source_index,
            source_width=source_width,
            visual_markers=visual_markers,
        )
        if question:
            question["number"] = len(questions) + 1
            questions.append(question)
    warnings = []
    if len(segments) > OCR_QUESTION_MAX_RECORDS:
        overflow = "\n".join(
            line.text
            for segment in segments[OCR_QUESTION_MAX_RECORDS:]
            for line in segment
        )
        warning = (
            f"More than {OCR_QUESTION_MAX_RECORDS} clear question regions were detected. "
            "The remaining OCR text was preserved for manual review rather than truncated."
        )
        warnings.append(warning)
        if questions:
            questions[-1].setdefault("issues", []).append(warning)
            metadata = questions[-1].setdefault("ocr_metadata", {})
            existing = str(metadata.get("unassigned_text") or "").strip()
            metadata["unassigned_text"] = "\n".join(
                part for part in (existing, overflow) if part
            )
    return {"questions": questions, "raw_text": raw_text, "warnings": warnings}
