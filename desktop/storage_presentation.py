"""Read-only Qt view of the existing bounded DLMS storage snapshot."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


# Matches the captured web chart's light-dark() fallbacks in storage-health.css.
_LIGHT_CHART = ("#215faf", "#7542aa", "#967000", "#14766c", "#af4c24",
                "#a43d75", "#4e772b", "#336d89", "#95464d", "#616975")
_DARK_CHART = ("#75adf3", "#b391dc", "#e3bf50", "#61cbbd", "#f39a72",
               "#df8bb9", "#a3c87b", "#85c4df", "#df989e", "#adb6c4")


class StorageDonut(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsStorageDonut")
        self.setFixedSize(190, 190)
        self.setAccessibleName("DLMS data composition chart")
        self.total = 0
        self.size = "Not checked"
        self.partial = False
        self.segments: list[tuple[int, QColor]] = []
        self.track = QColor("#66758c")
        self.text = QColor("#ffffff")
        self.muted = QColor("#b8c2cc")

    def paintEvent(self, event):  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = QRectF(20, 20, 150, 150)
        pen = QPen(self.track, 18)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.drawEllipse(ring)
        if self.total > 0:
            start = 90 * 16
            consumed = 0
            positive = [(amount, color) for amount, color in self.segments if amount > 0]
            for index, (amount, color) in enumerate(positive):
                span = (360 * 16 - consumed if index == len(positive) - 1
                        else round(360 * 16 * amount / self.total))
                if span <= 0:
                    continue  # Exact tiny categories remain in the readable legend.
                painter.setPen(QPen(color, 18, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                painter.drawArc(ring, start, -span)
                start -= span
                consumed += span
        painter.setPen(self.text)
        font = QFont(self.font())
        font.setPointSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(38, 68, 114, 29), Qt.AlignmentFlag.AlignCenter, self.size)
        painter.setPen(self.muted)
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)
        label = "Measured data" if self.partial else "DLMS data"
        painter.drawText(QRectF(35, 99, 120, 25), Qt.AlignmentFlag.AlignCenter, label)


class StorageComposition(QFrame):
    """The donut and its exact text legend consume one server-owned snapshot."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsStorageComposition")
        self.setAccessibleName("Measured DLMS data by category")
        self.layout_box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.layout_box.setContentsMargins(8, 10, 8, 10)
        self.layout_box.setSpacing(18)
        self.donut = StorageDonut(self)
        self.layout_box.addWidget(self.donut, 0, Qt.AlignmentFlag.AlignCenter)
        self.legend = QWidget(self)
        self.legend_layout = QVBoxLayout(self.legend)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(5)
        self.layout_box.addWidget(self.legend, 1)
        self.note = QLabel("Run the storage check to measure this profile.", self.legend)
        self.note.setObjectName("settingsStorageNote")
        self.note.setWordWrap(True)
        self.legend_layout.addWidget(self.note)
        self.colors = [QColor("#75adf3") for _ in range(10)]
        self._labels: list[QLabel] = []
        self._swatches: list[QFrame] = []

    def set_palette(self, entry):
        palette = entry["colors"]
        extra = entry["extra_tokens"]
        fallbacks = _LIGHT_CHART if entry["scheme"] == "light" else _DARK_CHART
        self.colors = [QColor(extra.get(f"--theme-chart-{index}", fallbacks[index]))
                       for index in range(10)]
        self.donut.track = QColor(palette["border_soft"] if palette["border_soft"].startswith("#")
                                  else palette["muted"])
        self.donut.text = QColor(palette["heading"])
        self.donut.muted = QColor(palette["muted"])
        self.donut.segments = [(amount, self.colors[index])
                               for index, (amount, _) in enumerate(self.donut.segments)]
        for index, swatch in enumerate(self._swatches):
            swatch.setStyleSheet(f"background: {self.colors[index].name()}; border-radius: 3px;")
        self.donut.update()

    def set_snapshot(self, storage: dict) -> bool:
        """Reject incoherent measurements instead of drawing a false proportion."""
        groups = storage.get("groups")
        total = storage.get("bytes")
        valid = (isinstance(total, int) and not isinstance(total, bool) and total >= 0
                 and isinstance(groups, list) and len(groups) <= 10)
        if valid:
            valid = all(isinstance(group, dict) and isinstance(group.get("label"), str)
                        and isinstance(group.get("size"), str)
                        and isinstance(group.get("bytes"), int)
                        and not isinstance(group["bytes"], bool) and group["bytes"] >= 0
                        for group in groups)
        if valid:
            valid = sum(group["bytes"] for group in groups) == total
        self.clear()
        if not valid:
            self.note.setText("Storage composition is unavailable; the measurement was incomplete or inconsistent.")
            return False
        self.donut.total = total
        self.donut.size = storage.get("size") if isinstance(storage.get("size"), str) else f"{total} B"
        self.donut.partial = storage.get("partial") is True
        self.donut.segments = [(group["bytes"], self.colors[index]) for index, group in enumerate(groups)]
        self.note.setText("Measured portion only; scan incomplete." if self.donut.partial else
                          "No measured file data." if total == 0 else
                          "Approximate composition of this DLMS profile. Small slices may be too thin to see.")
        for index, group in enumerate(groups):
            row = QWidget(self.legend)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            swatch = QFrame(row)
            swatch.setFixedSize(13, 13)
            swatch.setAccessibleName(f"Color for {group['label']}")
            swatch.setStyleSheet(f"background: {self.colors[index].name()}; border-radius: 3px;")
            line.addWidget(swatch)
            label = QLabel(f"{group['label']}: {group['size']}", row)
            label.setObjectName("settingsStorageLegend")
            label.setWordWrap(True)
            line.addWidget(label, 1)
            self.legend_layout.addWidget(row)
            self._labels.append(label)
            self._swatches.append(swatch)
        self.donut.update()
        return True

    def clear(self):
        for label in self._labels:
            row = label.parentWidget()
            self.legend_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._labels.clear()
        self._swatches.clear()
        self.donut.total = 0
        self.donut.size = "Unavailable"
        self.donut.partial = False
        self.donut.segments = []
        self.donut.update()

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        direction = (QBoxLayout.Direction.TopToBottom if self.width() < 600
                     else QBoxLayout.Direction.LeftToRight)
        if self.layout_box.direction() != direction:
            self.layout_box.setDirection(direction)
