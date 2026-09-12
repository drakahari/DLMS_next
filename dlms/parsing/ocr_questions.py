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

from dlms.parsing.question_wording import question_wording_selects_multiple


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
_EXPLANATION_HEADING_RE = re.compile(
    r"^\s*(overall\s+explanation|explanation|rationale|feedback|why\s+this\s+is\s+correct|"
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
_COMBINED_RESULT_HEADER_RE = re.compile(
    r"^\s*(?:[@©®Oo0QØ○◯◉●□☐☑()]|\|)*\s*question(?:\s+\d+)?\s+"
    r"(correct|incorrect)\b.*$",
    re.IGNORECASE,
)
_DOMAIN_HEADING_RE = re.compile(
    r"^\s*(?:(?:[@©®Oo0QØ○◯◉●□☐☑()]|\|)\s*)?domain\s*$", re.IGNORECASE
)
_CARD_FEEDBACK_RE = re.compile(
    r"^\s*(?:your\s+(?:answer|selection)\s+is\s+(correct|incorrect)|"
    r"(correct)\s+(?:answer|selection))\s*[!.]?\s*$",
    re.IGNORECASE,
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


def detect_answer_row_regions(
    image_bytes: bytes, observations: Iterable[Any]
) -> tuple[dict[str, int], ...]:
    """Locate a bounded set of bordered answer rows for an optional OCR retry."""

    observations = tuple(observations)
    if not observations:
        return ()
    lines = observations_to_lines(observations)
    if len(_segment_lines(lines)) != 1:
        return ()
    explanation_tops = [line.top for line in lines if _explanation_heading(line.text)]
    if not explanation_tops:
        return ()
    explanation_top = min(explanation_tops)
    question_lines = [
        line for line in lines if line.top < explanation_top and "?" in line.text
    ]
    if not question_lines:
        return ()
    question_bottom = max(line.bottom for line in question_lines)
    if explanation_top - question_bottom < 90:
        return ()

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

    pixels = image.load()
    sample_left = min(10, max(0, image.width - 1))
    sample_right = max(sample_left + 1, image.width - 10)
    sample_count = len(range(sample_left, sample_right, 2))
    horizontal = []
    for y in range(max(0, question_bottom + 4), min(image.height, explanation_top - 4)):
        strong = 0
        for x in range(sample_left, sample_right, 2):
            pixel = pixels[x, y]
            if max(pixel) < 225 or max(pixel) - min(pixel) > 70:
                strong += 1
        if strong >= sample_count * 0.62:
            horizontal.append(y)

    runs: list[list[int]] = []
    for y in horizontal:
        if not runs or y > runs[-1][-1] + 1:
            runs.append([y])
        else:
            runs[-1].append(y)
    edges = [int(round((run[0] + run[-1]) / 2)) for run in runs if len(run) <= 8]

    regions = []
    index = 0
    while index + 1 < len(edges):
        height = edges[index + 1] - edges[index]
        if 42 <= height <= 135:
            regions.append(
                {
                    "left": 0,
                    "top": edges[index],
                    "right": image.width,
                    "bottom": edges[index + 1],
                    "ocr_left": 0,
                    "ocr_right": min(
                        image.width,
                        max(700, min(900, int(image.width * 0.48))),
                    ),
                }
            )
            index += 2
        else:
            index += 1
    if not 2 <= len(regions) <= OCR_QUESTION_MAX_CHOICES:
        return ()

    current_rows = _choice_row_sequence(
        lines, source_width=source_width, result_context=True
    )
    current_complete = (
        len(current_rows) == len(regions)
        and _labels_are_contiguous(current_rows)
        and all(
            region["top"]
            <= row.line.top + row.line.height / 2
            <= region["bottom"]
            for row, region in zip(current_rows, regions)
        )
    )
    return () if current_complete else tuple(regions)


def merge_answer_row_observations(
    observations: Iterable[Any],
    recovered: Iterable[Any],
    regions: Iterable[dict[str, int]],
) -> tuple[Any, ...]:
    """Replace only row regions that produced usable bounded retry observations."""

    observations = tuple(observations)
    recovered = tuple(recovered)
    regions = tuple(regions)
    recovered_indexes = set()
    for observation in recovered:
        center = _box_field(observation, "top") + _box_field(observation, "height") / 2
        for index, region in enumerate(regions):
            if region["top"] <= center <= region["bottom"]:
                recovered_indexes.add(index)
                break
    if not recovered_indexes:
        return observations

    retained = []
    for observation in observations:
        center = _box_field(observation, "top") + _box_field(observation, "height") / 2
        if any(
            index in recovered_indexes and region["top"] <= center <= region["bottom"]
            for index, region in enumerate(regions)
        ):
            continue
        retained.append(observation)
    return tuple(retained) + recovered


def detect_visual_result_markers(
    image_bytes: bytes,
    observations: Iterable[Any],
    *,
    answer_regions: Iterable[dict[str, int]] = (),
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

    answer_regions = tuple(answer_regions)
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
        use_regions = bool(answer_regions)
        if not answer_rows and not use_regions:
            continue
        if not result_banner:
            question_before = any(
                _looks_like_question(line.text)
                and line.top
                < (answer_regions[0]["top"] if use_regions else answer_rows[0].line.top)
                for line in segment
            )
            explanation_after = any(
                _explanation_heading(line.text)
                and line.top
                > (answer_regions[-1]["bottom"] if use_regions else answer_rows[-1].line.top)
                for line in segment
            )
            if not (question_before and explanation_after):
                continue
        answer_centers = (
            [(region["top"] + region["bottom"]) / 2 for region in answer_regions]
            if use_regions
            else [row.line.top + row.line.height / 2 for row in answer_rows]
        )
        spacings = [
            later - earlier
            for earlier, later in zip(answer_centers, answer_centers[1:])
        ]
        region_spacing = median(spacings) if spacings else 64
        for row_index in range(len(answer_centers)):
            row_center = answer_centers[row_index]
            if use_regions:
                search_top = max(0, answer_regions[row_index]["top"])
                search_bottom = min(image.height, answer_regions[row_index]["bottom"] + 1)
                typical_spacing = region_spacing
                row_left = answer_regions[row_index]["left"]
                row_top = answer_regions[row_index]["top"]
            else:
                row = answer_rows[row_index]
                search_top, search_bottom, typical_spacing = _row_search_bounds(
                    answer_rows, row_index, image.height
                )
                row_left = row.line.left
                row_top = row.line.top
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
                    "row_left": row_left,
                    "row_top": row_top,
                    **({"row_index": row_index} if use_regions else {}),
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
        or question_wording_selects_multiple(normalized)
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
    if len(rows) > len(OCR_LABELS):
        return False
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


def _card_feedback_state(text: str) -> str | None:
    match = _CARD_FEEDBACK_RE.match(text)
    if not match:
        return None
    return "incorrect" if (match.group(1) or "").lower() == "incorrect" else "correct"


def _clean_unlabelled_choice_text(text: str) -> str:
    text = _TRAILING_RESULT_GLYPH_RE.sub("", str(text or "")).strip()
    text = re.sub(r"^\s*\|\s*", "", text)
    text = re.sub(r"^\s*(?:[&@]%?|%&?)\s+", "", text)
    text = re.sub(r"^\s*(?:[_|]+|C[EO0]|[O0Q]C)\s+", "", text)
    text = re.sub(r"^\s*\([C0OQ1_]+\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\(\s*", "", text)
    text = re.sub(
        r"^\s*(?:[@©®Oo0QØ○◯◉●□☐☑])(?:[.):_-]?\s+|(?=[^A-Za-z]))",
        "",
        text,
        count=1,
    )
    text = text.strip(" |")
    return _normalize_result_choice_text(text)


def _card_choice_group_text(group: list[OCRLine]) -> str:
    parts = []
    for index, line in enumerate(sorted(group, key=lambda item: (item.top, item.left))):
        if index == 0:
            parts.append(_clean_unlabelled_choice_text(line.text))
        else:
            parts.append(line.text.lstrip(" _|\"“”").strip())
    return " ".join(part for part in parts if part).strip()


def _joined_line(lines: list[OCRLine]) -> OCRLine:
    left = min(line.left for line in lines)
    top = min(line.top for line in lines)
    right = max(line.left + line.width for line in lines)
    bottom = max(line.bottom for line in lines)
    return OCRLine(
        text=" ".join(line.text for line in lines).strip(),
        left=left,
        top=top,
        width=right - left,
        height=bottom - top,
        confidence=sum(line.confidence for line in lines) / len(lines),
    )


def _trailing_card_choice(lines: list[OCRLine]) -> tuple[int, list[OCRLine]] | None:
    usable = [
        (index, line)
        for index, line in enumerate(lines)
        if not _card_feedback_state(line.text)
    ]
    if not usable:
        return None
    selected = [usable[-1]]
    for item in reversed(usable[:-1]):
        later = selected[0][1]
        if later.top - item[1].bottom > 36:
            break
        selected.insert(0, item)
    return selected[0][0], [item[1] for item in selected]


def _expected_multiple_count(text: str) -> int | None:
    match = re.search(r"\b(?:select|choose)\s+(two|three|\d+)\b", text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).lower()
    if value == "two":
        return 2
    if value == "three":
        return 3
    return int(value)


def _explicit_feedback_choice_indexes(
    explanation: str, choice_texts: list[str]
) -> list[int]:
    match = re.search(r"\b(?:is|are)\s+correct\b", explanation, re.IGNORECASE)
    if not match:
        return []
    identifying_text = explanation[: match.start()].casefold()
    indexes = []
    for index, choice in enumerate(choice_texts):
        normalized = re.sub(r"\s+", " ", choice).strip().casefold()
        if normalized and normalized in identifying_text:
            indexes.append(index)
    return indexes


def _infer_unlabelled_card_question(
    content_lines: list[OCRLine],
    *,
    source_id: str,
    source_index: int,
    result_banner: str | None,
    initial_unassigned: list[str],
) -> dict[str, Any] | None:
    """Recover reviewed answer cards without treating their controls as labels."""

    if not result_banner:
        return None
    question_start = next(
        (index for index, line in enumerate(content_lines) if _looks_like_question(line.text)),
        None,
    )
    if question_start is None:
        return None
    question_end = next(
        (
            index
            for index in range(question_start, len(content_lines))
            if content_lines[index].text.rstrip().endswith("?")
        ),
        question_start,
    )
    body = content_lines[question_end + 1 :]
    footer_index = next(
        (index for index, line in enumerate(body) if _DOMAIN_HEADING_RE.match(line.text)),
        len(body),
    )
    footer = body[footer_index:]
    body = body[:footer_index]
    heading_indexes = [
        index for index, line in enumerate(body) if _explanation_heading(line.text)
    ]
    overall_index = next(
        (
            index
            for index in heading_indexes
            if (_explanation_heading(body[index].text).group(1) or "").lower().startswith("overall")
        ),
        None,
    )
    repeated_indexes = [
        index
        for index in heading_indexes
        if not (_explanation_heading(body[index].text).group(1) or "").lower().startswith("overall")
    ]
    if overall_index is None and len(repeated_indexes) < 2:
        return None

    choice_groups: list[list[OCRLine]] = []
    choice_states: list[str | None] = []
    feedback_groups: list[list[OCRLine]] = []
    overall_explanation: list[OCRLine] = []
    if overall_index is not None:
        answer_lines = body[:overall_index]
        current: list[OCRLine] = []
        current_state: str | None = None
        pending_state: str | None = None

        def finish_group():
            nonlocal current, current_state
            if current:
                choice_groups.append(current)
                choice_states.append(current_state)
            current = []
            current_state = None

        for line in answer_lines:
            state = _card_feedback_state(line.text)
            if state:
                finish_group()
                pending_state = state
                continue
            if current and line.top - current[-1].bottom > 36:
                finish_group()
            if not current:
                current_state = pending_state
                pending_state = None
            current.append(line)
        finish_group()
        heading = _explanation_heading(body[overall_index].text)
        if heading and heading.group(2).strip():
            line = body[overall_index]
            overall_explanation.append(
                OCRLine(
                    heading.group(2).strip(),
                    line.left,
                    line.top,
                    line.width,
                    line.height,
                    line.confidence,
                )
            )
        overall_explanation.extend(body[overall_index + 1 :])
        feedback_groups = [[] for _choice in choice_groups]
    else:
        previous_heading = -1
        for heading_index in repeated_indexes:
            interval = body[previous_heading + 1 : heading_index]
            trailing = _trailing_card_choice(interval)
            if trailing is None:
                return None
            choice_start, choice_group = trailing
            prefix = interval[:choice_start]
            if choice_groups:
                feedback_groups[-1].extend(
                    line for line in prefix if not _card_feedback_state(line.text)
                )
            state = next(
                (
                    value
                    for line in reversed(prefix)
                    if (value := _card_feedback_state(line.text))
                ),
                None,
            )
            choice_groups.append(choice_group)
            choice_states.append(state)
            feedback_groups.append([])
            previous_heading = heading_index
        feedback_groups[-1].extend(
            line
            for line in body[repeated_indexes[-1] + 1 :]
            if not _card_feedback_state(line.text)
        )

    choice_texts = [_card_choice_group_text(group) for group in choice_groups]
    if not 2 <= len(choice_texts) <= OCR_QUESTION_MAX_CHOICES or any(
        not text for text in choice_texts
    ):
        return None

    question_text = " ".join(
        line.text for line in content_lines[question_start : question_end + 1]
    ).strip()
    all_text = "\n".join(line.text for line in content_lines)
    explanation = "\n".join(line.text for line in overall_explanation).strip()
    multiple_wording = question_wording_selects_multiple(all_text)
    expected_multiple = _expected_multiple_count(all_text)
    positive_indexes = [
        index for index, state in enumerate(choice_states) if state == "correct"
    ]
    if not positive_indexes and explanation:
        positive_indexes = _explicit_feedback_choice_indexes(explanation, choice_texts)
    complete_feedback = (
        len(positive_indexes) == expected_multiple
        if multiple_wording and expected_multiple is not None
        else (not multiple_wording and len(positive_indexes) == 1)
    )
    correct_answers = (
        [OCR_LABELS[index] for index in positive_indexes] if complete_feedback else []
    )
    correctness_evidence = "explicit_feedback" if correct_answers else "unknown"
    issues = ["Answer labels were inferred from unlabeled answer cards and require review."]
    if positive_indexes and not complete_feedback:
        issues.append(
            "Textual result feedback did not establish the complete correct-answer set."
        )
    if not correct_answers and not multiple_wording:
        issues.append(
            "Answer mode was not explicit; verify single-answer or multiple-answer mode."
        )

    choice_feedback = {
        OCR_LABELS[index]: " ".join(line.text for line in group).strip()
        for index, group in enumerate(feedback_groups)
        if group
    }
    confidence_lines = content_lines[question_start:]
    text_confidence = _confidence_label(
        sum(line.confidence for line in confidence_lines) / len(confidence_lines)
    )
    if text_confidence == "low":
        issues.append("OCR text confidence is low; compare every field with the source image.")
    unassigned = list(initial_unassigned)
    unassigned.extend(line.text for line in content_lines[:question_start])
    unassigned.extend(line.text for line in footer)
    return {
        "number": source_index,
        "question": question_text,
        "choices": [
            {"label": OCR_LABELS[index], "text": text, "label_origin": "inferred"}
            for index, text in enumerate(choice_texts)
        ],
        "correct_answers": correct_answers,
        "answer_mode": "multiple" if multiple_wording else "single",
        "answer_mode_evidence": (
            "explicit_instruction"
            if multiple_wording
            else correctness_evidence if correct_answers else "unknown"
        ),
        "correctness_confirmation_required": True,
        "correctness_confirmed": False,
        "correctness_evidence": correctness_evidence,
        "declared_answer_text": "",
        "explanation": explanation,
        "choice_feedback": choice_feedback,
        "pages": [source_index],
        "status": "review",
        "issues": list(dict.fromkeys(issues)),
        "ocr_metadata": {
            "source_id": source_id,
            "source_index": source_index,
            "label_origin": "inferred",
            "text_confidence": text_confidence,
            "structure_confidence": "medium",
            "correctness_evidence": correctness_evidence,
            "unassigned_text": "\n".join(dict.fromkeys(unassigned)).strip(),
            "result_banner": result_banner,
            "visual_result_markers": [],
        },
    }


def _geometry_choice_text(line: OCRLine, index: int) -> tuple[str, bool]:
    expected = OCR_LABELS[index]
    candidate = _choice_row_candidate(line, result_context=True)
    allow_fused_label = candidate is None or not candidate.strict
    if candidate:
        if _row_has_expected_label(candidate, index):
            return candidate.text, True
        text = candidate.text
    else:
        text = _TRAILING_RESULT_GLYPH_RE.sub("", line.text).strip(" |").strip()

    direct_confusion = "©" if expected == "C" else "8" if expected == "B" else None
    fused_lookahead = r"|(?=[a-z])" if allow_fused_label else ""
    label_pattern = re.compile(
        rf"^(?:{re.escape(expected)}|{re.escape(direct_confusion) if direct_confusion else '(?!)'})"
        rf"(?:[.)\]:-]\s*|\s+|(?=\d)|(?=[$€£]){fused_lookahead})",
        re.IGNORECASE,
    )
    match = label_pattern.match(text)
    if match:
        remainder = text[match.end() :].strip()
        if remainder.startswith(expected.lower() + "."):
            remainder = remainder[2:].strip()
        return _normalize_result_choice_text(remainder), True

    control = re.match(r"^(?:[|]\s*)?(?:[@©®Oo0QØ○◯◉●□☐☑()]\s*)", text)
    if control:
        text = text[control.end() :].strip()
    match = label_pattern.match(text)
    if match:
        remainder = text[match.end() :].strip()
        if remainder.startswith(expected.lower() + "."):
            remainder = remainder[2:].strip()
        return _normalize_result_choice_text(remainder), True

    unexpected = re.match(r"^[A-Za-z©8](?:[.)\]:-]\s*|\s+)", text)
    if unexpected:
        text = text[unexpected.end() :].strip()
    return _clean_unlabelled_choice_text(text), False


def _region_choice_rows(
    body_lines: list[OCRLine], answer_regions: Iterable[dict[str, int]]
) -> list[tuple[OCRLine, str, bool]]:
    rows = []
    for index, region in enumerate(answer_regions):
        region_lines = [
            line
            for line in body_lines
            if region["top"] <= line.top + line.height / 2 <= region["bottom"]
        ]
        if not region_lines:
            return []
        line = _joined_line(sorted(region_lines, key=lambda item: (item.top, item.left)))
        text, source_label = _geometry_choice_text(line, index)
        if not text:
            return []
        rows.append((line, text, source_label))
    return rows


def _infer_one_question(
    lines: list[OCRLine],
    *,
    source_id: str,
    source_index: int,
    source_width: int,
    visual_markers: Iterable[Any] = (),
    answer_regions: Iterable[dict[str, int]] = (),
) -> dict[str, Any] | None:
    if not lines:
        return None
    visual_markers = tuple(visual_markers)
    answer_regions = tuple(answer_regions)
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
        combined_match = _COMBINED_RESULT_HEADER_RE.match(line.text)
        if (
            result_banner is None
            and (banner_match or combined_match)
            and line.top < min(first_question_top, first_explicit_top)
        ):
            result_banner = (banner_match or combined_match).group(1).lower()
            unassigned.append(line.text)
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

    domain_index = next(
        (
            index
            for index, line in enumerate(content_lines)
            if result_banner
            and _DOMAIN_HEADING_RE.match(line.text)
            and any(_explanation_heading(previous.text) for previous in content_lines[:index])
        ),
        None,
    )
    if domain_index is not None:
        unassigned.extend(line.text for line in content_lines[domain_index:])
        content_lines = content_lines[:domain_index]
    if not content_lines:
        return None

    card_question = _infer_unlabelled_card_question(
        content_lines,
        source_id=source_id,
        source_index=source_index,
        result_banner=result_banner,
        initial_unassigned=unassigned,
    )
    if card_question:
        return card_question

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
    geometry_rows = (
        _region_choice_rows(body_lines, answer_regions) if answer_regions else []
    )

    question_lines: list[OCRLine] = []
    choice_texts: list[str] = []
    label_origin = "unknown"
    structure_confidence = "low"
    source_sequence_integrity = False
    if len(geometry_rows) == len(answer_regions) and geometry_rows:
        first_region_top = answer_regions[0]["top"]
        question_lines = [line for line in body_lines if line.bottom < first_region_top]
        geometry_line_ids = {id(item[0]) for item in geometry_rows}
        choice_texts = [item[1] for item in geometry_rows]
        source_sequence_integrity = all(item[2] for item in geometry_rows)
        label_origin = "source" if source_sequence_integrity else "inferred"
        structure_confidence = "high" if source_sequence_integrity else "medium"
        if not source_sequence_integrity:
            issues.append(
                "Answer labels were inferred from complete bordered answer rows and require review."
            )
        for line in body_lines:
            if line.bottom < first_region_top or id(line) in geometry_line_ids:
                continue
            if not any(
                region["top"] <= line.top + line.height / 2 <= region["bottom"]
                for region in answer_regions
            ):
                unassigned.append(line.text)
    elif len(explicit) >= 2:
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
        source_sequence_integrity = _labels_are_contiguous(
            choice_rows
        ) and _aligned_choice_block(
            [row.line for row in choice_rows], source_width
        )
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
    if result_context and source_sequence_integrity:
        if geometry_rows:
            for index in range(len(geometry_rows)):
                row_markers = [
                    marker
                    for marker in visual_markers
                    if int(_field(marker, "row_index", -1)) == index
                    and str(_field(marker, "kind", "")) in {"check", "x"}
                ]
                if len(row_markers) == 1:
                    detected_markers.append(
                        {
                            "label": OCR_LABELS[index],
                            "kind": str(_field(row_markers[0], "kind")),
                        }
                    )
        elif explicit:
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
    elif any(str(_field(marker, "kind", "")) == "check" for marker in visual_markers):
        issues.append(
            "A result check was detected but ignored because the source-label sequence was incomplete."
        )
    visual_answers = [
        marker["label"] for marker in detected_markers if marker["kind"] == "check"
    ]
    if not correct_answers and visual_answers:
        correct_answers = list(dict.fromkeys(visual_answers))
        correctness_evidence = "visual_result_marker"

    multiple_wording = question_wording_selects_multiple(all_text)
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
    answer_regions: Iterable[dict[str, int]] = ()
    if isinstance(observations, dict):
        visual_markers = observations.get("visual_markers") or ()
        answer_regions = observations.get("answer_regions") or ()
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
            answer_regions=answer_regions,
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
