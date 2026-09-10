"""Generate redistribution-safe reviewed-result screenshot OCR fixtures."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SIZE = (900, 690)
ROW_TOPS = (210, 285, 360, 435)


def font(size, *, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/share/fonts/dejavu") / name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def legacy_font(size, *, bold=False):
    """Keep the original fixture rendering stable when system fonts are absent."""

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/share/fonts/dejavu") / name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


BODY = legacy_font(24)
BODY_BOLD = legacy_font(24, bold=True)
HEADING = legacy_font(30, bold=True)
SMALL = legacy_font(20)


def marker(draw, center, kind):
    x, y = center
    fill = "#16864b" if kind == "check" else "#c53030"
    draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill=fill)
    if kind == "check":
        draw.line((x - 10, y, x - 3, y + 8, x + 12, y - 10), fill="white", width=5, joint="curve")
    else:
        draw.line((x - 9, y - 9, x + 9, y + 9), fill="white", width=5)
        draw.line((x + 9, y - 9, x - 9, y + 9), fill="white", width=5)


def render(filename, *, banner, question, choices, selected, checks, wrongs, explanation):
    image = Image.new("RGB", SIZE, "#f4f7fb")
    draw = ImageDraw.Draw(image)
    banner_fill = "#e8f7ee" if banner == "Correct" else "#fff0f0"
    banner_text = "#17663a" if banner == "Correct" else "#9b2525"
    draw.rounded_rectangle((42, 30, 858, 90), radius=14, fill=banner_fill, outline=banner_text, width=2)
    draw.text((68, 44), banner, fill=banner_text, font=BODY_BOLD)
    draw.multiline_text((55, 118), question, fill="#182433", font=HEADING, spacing=5)

    for index, (top, text) in enumerate(zip(ROW_TOPS, choices)):
        is_selected = index in selected
        row_fill = "#eef4ff" if is_selected else "white"
        draw.rounded_rectangle((52, top, 848, top + 58), radius=12, fill=row_fill, outline="#9aa9bd", width=2)
        draw.ellipse((72, top + 18, 92, top + 38), fill="white", outline="#53657c", width=2)
        if is_selected:
            draw.ellipse((77, top + 23, 87, top + 33), fill="#315fa8")
        draw.text((112, top + 14), f"{chr(65 + index)}. {text}", fill="#182433", font=BODY)
        if index in checks:
            marker(draw, (816, top + 29), "check")
        if index in wrongs:
            marker(draw, (816, top + 29), "x")

    draw.text((55, 520), "Explanation", fill="#182433", font=BODY_BOLD)
    draw.multiline_text((55, 558), explanation, fill="#36475b", font=SMALL, spacing=5)
    image.save(ROOT / filename, format="PNG", optimize=True)


render(
    "screenshot-result-a-wrong-b-correct.png",
    banner="Incorrect",
    question="Which quality is most useful for this synthetic example?",
    choices=("Timeliness", "Detail", "Accuracy", "Relevance"),
    selected={0},
    checks={1},
    wrongs={0},
    explanation="Detail is the answer identified by the result feedback.\nThe selected first row is intentionally wrong.",
)
render(
    "screenshot-result-d-correct.png",
    banner="Correct",
    question="Which option best represents the synthetic group?",
    choices=("Alpha unit", "Beta unit", "Gamma unit", "Delta collective"),
    selected={3},
    checks={3},
    wrongs=set(),
    explanation="Delta collective is explicitly marked correct by the row result icon.",
)
render(
    "screenshot-result-a-correct-c-wrong.png",
    banner="Incorrect",
    question="Which assessment best identifies the synthetic condition?",
    choices=("Behavioral", "Instinctual", "Habitual", "Indicators"),
    selected={2},
    checks={0},
    wrongs={2},
    explanation="Behavioral is marked correct; the selected Habitual row is marked wrong.",
)


def render_scaled_result(
    filename, *, banner, question, choices, selected, checks, wrongs, explanation
):
    """Render a larger, antialiased result layout matching ordinary browser scaling."""

    logical_size = (1120, 840)
    scale = 2
    image = Image.new("RGB", tuple(value * scale for value in logical_size), "#f5f7fa")
    draw = ImageDraw.Draw(image)

    def box(values):
        return tuple(value * scale for value in values)

    def point(values):
        return tuple(value * scale for value in values)

    banner_fill = "#e7f7ec" if banner == "Correct" else "#fff0f1"
    banner_text = "#17663a" if banner == "Correct" else "#9b2525"
    draw.rounded_rectangle(
        box((44, 28, 1076, 96)),
        radius=15 * scale,
        fill=banner_fill,
        outline=banner_text,
        width=2 * scale,
    )
    draw.text(point((72, 47)), banner, fill=banner_text, font=font(25 * scale, bold=True))
    draw.text(point((58, 132)), question, fill="#172333", font=font(27 * scale, bold=True))

    row_tops = (235, 317, 399, 481)
    for index, (top, answer_text) in enumerate(zip(row_tops, choices)):
        row_fill = "#edf4ff" if index in selected else "#ffffff"
        draw.rounded_rectangle(
            box((52, top, 1068, top + 70)),
            radius=12 * scale,
            fill=row_fill,
            outline="#9aa9bd",
            width=2 * scale,
        )
        draw.ellipse(
            box((73, top + 23, 97, top + 47)),
            fill="white",
            outline="#53657c",
            width=2 * scale,
        )
        if index in selected:
            draw.ellipse(box((79, top + 29, 91, top + 41)), fill="#315fa8")
        draw.text(
            point((118, top + 20)),
            f"{chr(65 + index)}. {answer_text}",
            fill="#172333",
            font=font(25 * scale),
        )
        kind = "check" if index in checks else "x" if index in wrongs else None
        if kind:
            center_x, center_y = 1028 * scale, (top + 48) * scale
            radius = 25 * scale
            fill = "#16864b" if kind == "check" else "#c53030"
            draw.ellipse(
                (
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                ),
                fill=fill,
            )
            if kind == "check":
                draw.line(
                    (
                        center_x - 14 * scale,
                        center_y,
                        center_x - 4 * scale,
                        center_y + 11 * scale,
                        center_x + 17 * scale,
                        center_y - 14 * scale,
                    ),
                    fill="white",
                    width=6 * scale,
                    joint="curve",
                )
            else:
                draw.line(
                    (
                        center_x - 12 * scale,
                        center_y - 12 * scale,
                        center_x + 12 * scale,
                        center_y + 12 * scale,
                    ),
                    fill="white",
                    width=6 * scale,
                )
                draw.line(
                    (
                        center_x + 12 * scale,
                        center_y - 12 * scale,
                        center_x - 12 * scale,
                        center_y + 12 * scale,
                    ),
                    fill="white",
                    width=6 * scale,
                )

    draw.text(
        point((58, 590)),
        "Explanation",
        fill="#172333",
        font=font(25 * scale, bold=True),
    )
    draw.multiline_text(
        point((58, 632)),
        explanation,
        fill="#36475b",
        font=font(20 * scale),
        spacing=5 * scale,
    )
    image = image.resize(logical_size, Image.Resampling.LANCZOS)
    image.save(ROOT / filename, format="PNG", optimize=True)


render_scaled_result(
    "screenshot-result-sequence-recovery-d-correct.png",
    banner="Correct",
    question="Which synthetic group best demonstrates civic advocacy?",
    choices=("Alpha service", "Beta office", "Gamma circle", "Delta advocates"),
    selected={3},
    checks={3},
    wrongs=set(),
    explanation="The dedicated result marker identifies Delta advocates.",
)
render_scaled_result(
    "screenshot-result-artifact-cleanup-a-correct-c-wrong.png",
    banner="Incorrect",
    question="Which assessment best identifies an internal risk?",
    choices=("Behavioral", "Instinctual", "Habitual", "Indicators"),
    selected={2},
    checks={0},
    wrongs={2},
    explanation="Behavioral evidence is the intended answer in this synthetic example.",
)
