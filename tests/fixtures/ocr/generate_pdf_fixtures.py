"""Generate redistribution-safe synthetic PDFs used by selective OCR tests.

The content is authored for DLMS and contains no third-party quiz material.
Run from the repository root with the project virtual environment.
"""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


ROOT = Path(__file__).resolve().parent / "pdf"


def digital_pdf(lines):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    commands = ["BT /F1 14 Tf 72 730 Td"]
    for index, line in enumerate(lines):
        escaped = str(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index:
            commands.append("0 -24 Td")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def scanned_pdf(pages):
    images = []
    for lines in pages:
        image = Image.new("RGB", (850, 1100), "white")
        ImageDraw.Draw(image).multiline_text(
            (70, 70), "\n".join(lines), fill="black", spacing=12
        )
        images.append(image)
    output = BytesIO()
    images[0].save(
        output,
        "PDF",
        resolution=144,
        save_all=True,
        append_images=images[1:],
    )
    return output.getvalue()


def merge(*documents):
    writer = PdfWriter()
    for payload in documents:
        for page in PdfReader(BytesIO(payload)).pages:
            writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    digital = digital_pdf(
        [
            "Question 1",
            "Which protocol protects remote shell traffic?",
            "A. FTP",
            "B. SFTP",
            "C. HTTP",
            "Correct Answer: B",
            "Explanation: SFTP uses an encrypted SSH transport.",
        ]
    )
    scanned = scanned_pdf(
        [["Question 2", "Which port is HTTPS?", "A. 22", "B. 80", "C. 443", "Correct answer: C"]]
    )
    fixtures = {
        "selectable-text.pdf": digital,
        "fully-scanned.pdf": scanned,
        "mixed-text-and-scan.pdf": merge(digital, scanned),
        "low-text-ambiguous.pdf": digital_pdf(
            ["Question image placeholder text", "Choices may be incomplete below"]
        ),
        "multiple-scanned-pages.pdf": scanned_pdf(
            [
                ["Question 1", "Choose alpha", "A. Alpha", "B. Beta", "Correct answer: A"],
                ["Question 2", "Choose delta", "A. Gamma", "B. Delta", "Correct answer: B"],
                ["Question 3", "Choose zeta", "A. Epsilon", "B. Zeta", "Correct answer: B"],
            ]
        ),
        "scanned-multiple-correct.pdf": scanned_pdf(
            [["Select all that apply", "A. One", "B. Two", "C. Three", "Correct answers: A and C"]]
        ),
        "scanned-unlabeled-six.pdf": scanned_pdf(
            [["Which values are examples?", "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]]
        ),
    }
    for name, payload in fixtures.items():
        (ROOT / name).write_bytes(payload)


if __name__ == "__main__":
    main()
