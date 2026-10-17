"""Make a neutral selectable-text PDF for Desktop terminology acceptance."""
from __future__ import annotations

from pathlib import Path
import sys

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


LINES = (
    "Access Control A process used to restrict access to authorized subjects.",
    "Audit Trail A chronological record of system activities and events.",
    "Business Continuity A capability that enables essential operations to continue after disruption.",
    "Data Classification A process for organizing information according to sensitivity and handling requirements.",
    "Encryption A method used to transform readable information into protected ciphertext.",
)


def create(destination: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    commands = ["BT", "/F1 11 Tf", "45 740 Td"]
    for index, line in enumerate(LINES):
        if index:
            commands.append("0 -28 Td")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    content = DecodedStreamObject()
    content.set_data(("\n".join(commands) + "\n").encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        writer.write(handle)


if __name__ == "__main__":
    create(Path(sys.argv[1]))
