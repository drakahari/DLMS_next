"""Render the captured sidebar's own SVG symbols for native Settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .isolation import FROZEN, PROJECT


@lru_cache(maxsize=1)
def _symbols() -> dict[str, ET.Element]:
    path = Path(PROJECT) / "static/icons.svg"
    root = ET.parse(path).getroot()
    return {node.get("id"): node for node in root if node.tag.endswith("symbol") and node.get("id")}


@lru_cache(maxsize=128)
def sidebar_icon(name: str, color: str, size: int = 24) -> QIcon:
    if not re.fullmatch(r"[a-z][a-z-]*", name) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or size not in (24, 34):
        return QIcon()
    symbol = _symbols().get(name)
    if symbol is None:
        return QIcon()
    viewbox = symbol.get("viewBox", "0 0 24 24")
    parts = [ET.tostring(child, encoding="unicode") for child in symbol]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" '
           f'fill="{symbol.get("fill", "none")}" stroke="{color}" '
           f'stroke-width="{symbol.get("stroke-width", "1.8")}" '
           f'stroke-linecap="{symbol.get("stroke-linecap", "round")}" '
           f'stroke-linejoin="{symbol.get("stroke-linejoin", "round")}">'
           + "".join(parts).replace("currentColor", color) + "</svg>")
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)
