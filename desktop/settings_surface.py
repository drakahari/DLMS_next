"""Qt-owned Local Settings pages; no web page can call these controls."""
from __future__ import annotations

import re

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .frozen_runtime import source_import_path
from .settings_icons import sidebar_icon
from .storage_presentation import StorageComposition

source_import_path()
from dlms.themes import DEFAULT_THEME, THEME_REGISTRY  # noqa: E402


def _solid(value: str, base: str) -> str:
    """Composite captured web rgba tokens onto the opaque theme base for Qt."""
    if value.startswith("#"):
        return value
    match = re.fullmatch(r"rgba\((\d+),(\d+),(\d+),([.\d]+)\)", value.replace(" ", ""))
    if not match:
        return base
    foreground = tuple(int(match.group(i)) for i in (1, 2, 3))
    background = QColor(base)
    alpha = max(0.0, min(1.0, float(match.group(4))))
    return "#" + "".join(f"{round(a * alpha + b * (1 - alpha)):02x}" for a, b in
                         zip(foreground, (background.red(), background.green(), background.blue())))


def _mix(foreground: str, background: str, weight: float) -> str:
    front, back = QColor(foreground), QColor(background)
    return "#" + "".join(f"{round(a * weight + b * (1 - weight)):02x}" for a, b in
                         zip((front.red(), front.green(), front.blue()),
                             (back.red(), back.green(), back.blue())))


class ActionButton(QPushButton):
    """Activate Return only while this particular button owns keyboard focus."""

    def keyPressEvent(self, event):  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.hasFocus():
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class _ContinuousOutline(QWidget):
    """Paint above both scrollbars so the upper shell corners stay continuous."""

    def __init__(self, parent):
        super().__init__(parent)
        self.color = QColor("#ffffff")
        self.radius = 24
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):  # noqa: N802 - Qt API
        super().paintEvent(event)
        if not self.radius:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self.color, 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                self.radius - .5, self.radius - .5)


class RoundedSettingsShell(QFrame):
    """Clip children, then draw one outline above the scrollbars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.radius = 24
        self.outline = _ContinuousOutline(self)

    def set_outline(self, color: str, radius: int):
        self.radius = radius
        self.outline.color = QColor(color)
        self.outline.radius = radius
        self._sync_outline()

    def _sync_outline(self):
        self.outline.setGeometry(self.rect())
        self.outline.raise_()
        self.outline.update()
        if not self.radius:
            self.clearMask()
            self.outline.hide()
            return
        self.outline.show()
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._sync_outline()


class LocalSettingsSurface(QFrame):
    def __init__(self, profile: str, root: str, activate, navigate, parent=None):
        super().__init__(parent)
        self.setObjectName("managedSettingsPanel")
        self.setAccessibleName(f"Local Settings for profile {profile}")
        self.buttons: dict[str, ActionButton] = {}
        self.action_status: dict[str, QLabel] = {}
        self.theme_notices: list[QLabel] = []
        self.stack = QStackedWidget(self)
        self.navigate = navigate
        self._nav_open = False
        self._theme = DEFAULT_THEME
        self._outline_color = "#ffffff"
        self._shell_radius = -1
        outer = QVBoxLayout(self)
        self.outer_layout = outer
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)
        self.shell = RoundedSettingsShell(self)
        self.shell.setObjectName("settingsOuterShell")
        outer.addWidget(self.shell, 1)
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(1, 1, 1, 1)
        shell_layout.setSpacing(0)
        self.nav_toggle = ActionButton("☰  Navigation", self.shell)
        self.nav_toggle.setObjectName("settingsNavToggle")
        self.nav_toggle.setAccessibleName("Show or hide DLMS navigation")
        self.nav_toggle.clicked.connect(self._toggle_navigation)
        shell_layout.addWidget(self.nav_toggle)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        shell_layout.addLayout(layout, 1)
        self.sidebar = QScrollArea(self)
        self.sidebar.setObjectName("settingsSidebar")
        self.sidebar.setWidgetResizable(True)
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setFixedWidth(292)
        sidebar_body = QWidget(self.sidebar)
        sidebar_body.setObjectName("settingsSidebarBody")
        self.sidebar_layout = QVBoxLayout(sidebar_body)
        self.sidebar_layout.setContentsMargins(18, 26, 18, 18)
        self.sidebar_layout.setSpacing(4)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(10, 0, 10, 22)
        brand_row.setSpacing(14)
        self.brand_mark = QLabel(sidebar_body)
        self.brand_mark.setObjectName("settingsBrandMark")
        self.brand_mark.setFixedSize(48, 54)
        self.brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_row.addWidget(self.brand_mark)
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(5)
        self.brand_title = QLabel("DLMS", sidebar_body)
        self.brand_title.setObjectName("settingsBrandTitle")
        self.brand_subtitle = QLabel("Training Center", sidebar_body)
        self.brand_subtitle.setObjectName("settingsBrandSubtitle")
        brand_copy.addWidget(self.brand_title)
        brand_copy.addWidget(self.brand_subtitle)
        brand_row.addLayout(brand_copy, 1)
        self.sidebar_layout.addLayout(brand_row)
        self.nav_items = QVBoxLayout()
        self.nav_items.setSpacing(3)
        self.sidebar_layout.addLayout(self.nav_items)
        self.sidebar_layout.addStretch()
        profile_label = QLabel(f"LOCAL · {profile}", sidebar_body)
        profile_label.setObjectName("settingsNavProfile")
        profile_label.setWordWrap(True)
        self.sidebar_layout.addWidget(profile_label)
        self.sidebar.setWidget(sidebar_body)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.backup_page = self._page("Backup & Restore", profile, root, navigate)
        self.reset_page = self._page("Reset & Remove", profile, root, navigate)
        self.stack.addWidget(self.backup_page[0])
        self.stack.addWidget(self.reset_page[0])
        self._build_backup(self.backup_page[1], profile, activate)
        self._build_reset(self.reset_page[1], profile, activate)
        self.backup_page[1].addStretch()
        self.reset_page[1].addStretch()
        self.set_theme(DEFAULT_THEME)
        self._sync_navigation_layout()

    def _page(self, title, profile, root, navigate):
        scroll = QScrollArea(self)
        scroll.setObjectName("localSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(scroll)
        body.setObjectName("localSettingsBody")
        column = QVBoxLayout(body)
        column.setContentsMargins(30, 27, 30, 36)
        column.setSpacing(18)
        eyebrow = QLabel("SETTINGS / " + title.upper(), body)
        eyebrow.setObjectName("settingsEyebrow")
        column.addWidget(eyebrow)
        heading = QLabel(title, body)
        heading.setObjectName("settingsTitle")
        heading.setAccessibleName(title + " Local Settings")
        column.addWidget(heading)
        identity = QLabel(f"LOCAL · disposable profile: {profile}", body)
        identity.setObjectName("profileIdentity")
        identity.setWordWrap(True)
        identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByKeyboard |
                                         Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(identity)
        theme_notice = QLabel("", body)
        theme_notice.setObjectName("settingsWarning")
        theme_notice.setWordWrap(True)
        theme_notice.hide()
        column.addWidget(theme_notice)
        self.theme_notices.append(theme_notice)
        details = ActionButton("Show profile location details", body)
        details.setObjectName("settingsDetailsToggle")
        details.setAccessibleName("Show or hide local profile location details")
        details.setCheckable(True)
        column.addWidget(details)
        path_label = QLabel(f"Data folder: {root}", body)
        path_label.setObjectName("settingsDetails")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByKeyboard |
                                           Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.hide()
        column.addWidget(path_label)
        details.toggled.connect(path_label.setVisible)
        details.toggled.connect(lambda open_, button=details: button.setText(
            "Hide profile location details" if open_ else "Show profile location details"))
        scroll.setWidget(body)
        return scroll, column

    def _section(self, column, title, description, warnings, action, label, profile, activate):
        card = QFrame(self)
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 19, 22, 21)
        layout.setSpacing(11)
        heading = QLabel(title, card)
        heading.setObjectName("cardHeading")
        layout.addWidget(heading)
        paragraph = QLabel(description, card)
        paragraph.setWordWrap(True)
        layout.addWidget(paragraph)
        destructive = action in {"exam", "learning", "study", "quiz", "source", "settings", "fresh", "remove"}
        for index, warning in enumerate(warnings):
            note = QLabel(warning, card)
            note.setObjectName("settingsWarning" if destructive and (index == 0 or action == "remove")
                               else "settingsNote")
            note.setWordWrap(True)
            layout.addWidget(note)
        if action:
            button = ActionButton(label.replace("&", "&&"), card)
            button.setAccessibleName(f"{label} for disposable profile {profile}")
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setMinimumHeight(42)
            button.setObjectName("destructiveAction" if action in {"exam", "learning", "study", "quiz", "source", "settings", "fresh", "remove"} else "managedAction")
            button.clicked.connect(lambda checked=False, key=action: activate(key))
            layout.addWidget(button)
            self.buttons[action] = button
            status = QLabel("", card)
            if action in {"create_backup", "backup"}:
                status.setObjectName("operationFeedback")
            status.setTextFormat(Qt.TextFormat.PlainText)
            status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            status.setWordWrap(True)
            status.setAccessibleName(f"{label} status")
            if action in {"create_backup", "backup"}:
                status.hide()
            layout.addWidget(status)
            self.action_status[action] = status
        column.addWidget(card)
        return layout

    def _build_backup(self, column, profile, activate):
        storage = self._section(column, "Storage health",
            "Check DLMS data size and available disk space. This check changes no data.",
            ["Sizes are approximate; inaccessible files and symbolic links are skipped. "
             "Downloads outside this profile are not counted. Backups and imports need working space."],
            "refresh_storage", "Check / refresh storage", profile, activate)
        self.storage_label = QLabel("Storage has not been checked yet.", self)
        self.storage_label.setWordWrap(True)
        self.storage_label.setAccessibleName("Local profile storage health")
        storage.addWidget(self.storage_label)
        self.storage_details_button = ActionButton("Show storage breakdown", self)
        self.storage_details_button.setObjectName("settingsDetailsToggle")
        self.storage_details_button.setAccessibleName("Show or hide storage breakdown")
        self.storage_details_button.setCheckable(True)
        storage.insertWidget(storage.count() - 1, self.storage_details_button)
        self.storage_label.hide()
        self.storage_details_button.toggled.connect(self.storage_label.setVisible)
        self.storage_details_button.toggled.connect(lambda open_: self.storage_details_button.setText(
            "Hide storage breakdown" if open_ else "Show storage breakdown"))
        self.storage_composition = StorageComposition(self)
        storage.insertWidget(storage.indexOf(self.storage_details_button), self.storage_composition)
        self.storage_space_label = QLabel("Available disk space is checked separately from DLMS data size.", self)
        self.storage_space_label.setObjectName("settingsStorageSpace")
        self.storage_space_label.setWordWrap(True)
        storage.insertWidget(storage.indexOf(self.storage_details_button), self.storage_space_label)
        portable = self._section(column, "Portable Backup",
            "Create and download one ZIP snapshot containing persistent DLMS data.",
            ["Included: quizzes, history, settings, Study and Content Packs, quiz assets, "
             "import source banks, drafts, Law Study content, backgrounds and persistent logos.",
             "Excluded: temporary uploads, staging files, temporary previews and older backup archives. "
             "Accepted pending Desktop work must settle first."],
            "create_backup", "Save Backup As…", profile, activate)
        inventory_heading = QLabel("Recent safety backups kept on this device", self)
        inventory_heading.setObjectName("cardHeading")
        portable.addWidget(inventory_heading)
        self.inventory_label = QLabel("Checking recent backups…", self)
        self.inventory_label.setWordWrap(True)
        self.inventory_label.setAccessibleName("Recent local safety backups")
        portable.addWidget(self.inventory_label)
        self._section(column, "Restore from Backup",
            "Select a DLMS portable-backup ZIP. Desktop validates a retained copy before changing this profile.",
            ["Desktop checks archive safety and compatibility, makes a private safety copy, "
             "reconciles interruption and isolates old browser recovery evidence. "
             "Choose an owned ZIP from Documents, Downloads or another ordinary local folder. "
             "Symbolic links and special files are not supported. Continue using synthetic backups "
             "for this development pilot; no copying into hidden application folders is needed."],
            "backup", "Import a DLMS backup…", profile, activate)

    def clear_backup_feedback(self):
        for action in ("create_backup", "backup"):
            self.action_status[action].clear()
            self.action_status[action].hide()
            self.buttons[action].setAccessibleDescription("")

    def set_backup_feedback(self, action, message, severity, *, reveal=False):
        label = self.action_status[action]
        label.setProperty("severity", severity)
        label.setText(message)
        label.setAccessibleDescription(message)
        self.buttons[action].setAccessibleDescription(message)
        label.style().unpolish(label)
        label.style().polish(label)
        label.show()
        if reveal:
            self.backup_page[0].ensureWidgetVisible(label, 12, 12)

    def _build_reset(self, column, profile, activate):
        from .maintenance import SCOPES
        sections = (
            ("exam", "Persistent Exam Result Storage",
             "Clear completed Exam attempts and missed-question results without deleting quizzes.",
             "Study history remains. This cannot be undone without a retained backup."),
            ("learning", "Reset Learning Intelligence",
             "Clear mastery, recommendation, diagnostic and review-schedule estimates.",
             "Quizzes, saved Study and Exam factual history, source content and settings remain."),
            ("study", "Delete Study History",
             "Delete Study sessions, responses, completions and Study learning evidence.",
             "Exam attempts and evidence, quizzes and settings remain. A typed confirmation is required."),
            ("quiz", "Reset Quiz Library & Results",
             "Remove generated quizzes, quiz records, results, pages, assets and logos.",
             "Source packs, import banks, certifications, settings and backup archives remain."),
            ("source", "Clear Imported / Source Content",
             "Remove reusable source material without deleting published quizzes.",
             "Protected packs and published dependencies are preserved; removable packs, banks, drafts and staging are cleared."),
            ("settings", "Reset Application Settings",
             "Restore appearance, parsing, AI Integration, navigation and folder preferences to defaults.",
             "Quizzes, populated folder assignments, history and learning evidence remain. Empty folders and hidden state reset."),
            ("fresh", "Reset DLMS to Fresh State",
             "Return active runtime data to an empty first-run state.",
             "Quizzes, history, packs, banks, drafts and settings are removed. Existing backup ZIPs remain."),
        )
        for action, title, description, warning in sections:
            self._section(column, title, description,
                          [warning, "Desktop retains a private recovery copy and a safety backup where applicable."],
                          action, SCOPES[action], profile, activate)
        self._section(column, "Remove DLMS Data from This Computer",
            "Permanently remove this exact disposable Desktop profile and shut down its local application.",
            ["This includes backups inside the target. An external intentional-removal record and synthetic "
             "recovery copy are retained for this development phase; the application files remain.",
             "Type REMOVE DLMS DATA in the confirmation. This profile name will not be recreated automatically."],
            "remove", "Remove selected disposable profile…", profile, activate)

    def show_kind(self, kind: str):
        self.stack.setCurrentWidget(self.backup_page[0] if kind == "backup" else self.reset_page[0])
        self._current_kind = kind
        for button in getattr(self, "nav_buttons", []):
            path = button.property("navPath")
            button.setProperty("selected", path == f"/settings/{kind}")
            button.style().unpolish(button)
            button.style().polish(button)
        if self.width() < 780:
            self._nav_open = False
            self._sync_navigation_layout()

    def set_navigation(self, entries: list[dict]):
        """Render read-only canonical sidebar entries from the verified page."""
        while self.nav_items.count():
            item = self.nav_items.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.nav_buttons = []
        for entry in entries:
            if entry["type"] == "section":
                section = QWidget(self)
                section.setObjectName("settingsNavSectionRow")
                row = QHBoxLayout(section)
                row.setContentsMargins(8, 13, 8, 5)
                row.setSpacing(10)
                label = QLabel(entry["label"].upper(), section)
                label.setObjectName("settingsNavSection")
                row.addWidget(label)
                divider = QFrame(section)
                divider.setObjectName("settingsNavDivider")
                divider.setFixedHeight(1)
                row.addWidget(divider, 1)
                self.nav_items.addWidget(section)
                continue
            path = entry["path"]
            label = entry["label"]
            button = ActionButton(label.replace("&", "&&"), self)
            button.setObjectName("settingsNavItem")
            button.setProperty("navIcon", entry.get("icon"))
            button.setProperty("navIconColor", entry.get("icon_color"))
            button.setProperty("navPath", path)
            button.setProperty("selected", bool(entry.get("active")))
            button.setAccessibleName(f"Navigate to {label}")
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if entry.get("icon"):
                button.setIcon(sidebar_icon(entry["icon"], entry.get("icon_color") or THEME_REGISTRY[self._theme]["colors"]["accent_text"]))
                button.setIconSize(QSize(24, 24))
            button.clicked.connect(lambda checked=False, destination=path: self.navigate(destination))
            self.nav_items.addWidget(button)
            self.nav_buttons.append(button)
            if path == "/settings":
                for title, subpath in (("Backup & Restore", "/settings/backup"),
                                       ("Reset & Remove", "/settings/reset-remove"),
                                       ("Appearance & themes", "/settings/appearance")):
                    sub = ActionButton(title.replace("&", "&&"), self)
                    sub.setObjectName("settingsNavSubitem")
                    sub.setProperty("navPath", subpath)
                    sub.setProperty("selected", subpath == f"/settings/{getattr(self, '_current_kind', '')}")
                    sub.setAccessibleName(f"Navigate to {title}")
                    sub.clicked.connect(lambda checked=False, destination=subpath: self.navigate(destination))
                    self.nav_items.addWidget(sub)
                    self.nav_buttons.append(sub)

    def _toggle_navigation(self):
        self._nav_open = not self._nav_open
        self._sync_navigation_layout()

    def _sync_navigation_layout(self):
        compact = self.width() < 780
        self.nav_toggle.setVisible(compact)
        self.sidebar.setFixedWidth(max(292, self.width()) if compact and self._nav_open else 292)
        self.sidebar.setVisible(not compact or self._nav_open)
        self.stack.setVisible(not compact or not self._nav_open)

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # The captured web shell meets the viewport edge in narrow layouts.
        compact = self.width() < 780
        self.outer_layout.setContentsMargins(*( (0, 0, 0, 0) if compact else (12, 12, 12, 12) ))
        radius = 0 if compact else 24
        if radius != self._shell_radius:
            self._shell_radius = radius
            self.shell.setStyleSheet(f"QFrame#settingsOuterShell {{ border-radius: {radius}px; }}")
        self.shell.set_outline(self._outline_color, radius)
        self._sync_navigation_layout()

    def set_theme(self, theme: str):
        unknown = theme not in THEME_REGISTRY
        if unknown:
            theme = DEFAULT_THEME
        for notice in self.theme_notices:
            notice.setText("The selected theme is unavailable; showing the Purple & Gold fallback. Review Appearance settings." if unknown else "")
            notice.setVisible(unknown)
        self._theme = theme
        entry = THEME_REGISTRY[theme]
        p, extra = entry["colors"], entry["extra_tokens"]
        base = p["body_base"]
        surface, card, sidebar = (_solid(p[key], base) for key in ("main1", "panel1", "sidebar1"))
        text, muted, edge = p["page"], p["muted"], _solid(p["border"], base)
        self._outline_color = _solid(p["border"], _solid(p["shell"], base))
        self.shell.set_outline(self._outline_color, 0 if self.width() < 780 else 24)
        accent = p["accent"]
        focus = extra.get("--theme-focus-ring", p["accent_text"])
        warning = extra.get("--theme-semantic-warning-text", "#765511" if entry["scheme"] == "light" else "#f4cf72")
        destructive = extra.get("--theme-semantic-error-text", "#8f2435" if entry["scheme"] == "light" else "#ff9eaa")
        hover = _solid(p["surface2"], base)
        nav_hover = _mix(accent, sidebar, .17)
        nav_active = _mix(accent, sidebar, .32)
        nav_border = _mix(accent, sidebar, .58)
        # The captured web CSS uses Arial for ordinary themes. Ethereal alone
        # selects system-ui for body text and ui-monospace for display text.
        # These are the corresponding Fedora fontconfig families, rather than
        # the unrelated default Qt application font.
        body_font = "Noto Sans" if theme == "ethereal" else "Liberation Sans"
        display_font = "DejaVu Sans Mono" if theme == "ethereal" else body_font
        self.setFont(QFont(body_font))
        brand_size = (40, 44) if theme == "ethereal" else (48, 54)
        self.brand_mark.setFixedSize(*brand_size)
        self.brand_title.setFixedHeight(31 if theme == "ethereal" else 35)
        self.brand_subtitle.setFixedHeight(18)
        self.sidebar_layout.setContentsMargins(
            *((14, 18, 14, 14) if theme == "ethereal" else (18, 26, 18, 18))
        )
        divider = p["border_soft"]
        self.setStyleSheet(f"""
            QFrame#managedSettingsPanel {{ background: {base}; color: {text}; }}
            QFrame#settingsOuterShell {{ background: {p['shell']}; border: 0; border-radius: 24px; }}
            QWidget#localSettingsBody, QScrollArea#localSettingsScroll {{ background: {surface}; color: {text}; }}
            QScrollArea#settingsSidebar, QWidget#settingsSidebarBody {{ background: {sidebar}; color: {p['nav_text']}; }}
            QScrollArea#settingsSidebar {{ border: 0; border-right: 1px solid {divider}; }}
            QScrollArea#settingsSidebar QScrollBar:vertical {{ background: {sidebar}; border: 0; width: 8px; margin: 0; }}
            QScrollArea#settingsSidebar QScrollBar::handle:vertical {{ background: {divider}; border-radius: 4px; min-height: 28px; }}
            QScrollArea#settingsSidebar QScrollBar::add-line:vertical, QScrollArea#settingsSidebar QScrollBar::sub-line:vertical {{ height: 0; border: 0; }}
            QScrollArea#localSettingsScroll QScrollBar:vertical {{ background: {surface}; border: 0; width: 8px; margin: 0; }}
            QScrollArea#localSettingsScroll QScrollBar::handle:vertical {{ background: {divider}; border-radius: 4px; min-height: 28px; }}
            QScrollArea#localSettingsScroll QScrollBar::add-line:vertical, QScrollArea#localSettingsScroll QScrollBar::sub-line:vertical {{ height: 0; border: 0; }}
            QFrame#settingsCard {{ background: {card}; border: 1px solid {edge}; border-radius: 10px; }}
            QLabel {{ color: {text}; font-family: "{body_font}"; font-size: 14px; }}
            QLabel#settingsBrandTitle {{ color: {p['heading']}; font-family: "{display_font}"; font-size: {27 if theme == 'ethereal' else 31}px; font-weight: 800; letter-spacing: 0.4px; }}
            QLabel#settingsBrandSubtitle {{ color: {p['nav_muted']}; font-size: {12 if theme == 'ethereal' else 14}px; }}
            QLabel#settingsBrandMark {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(25,77,132,140),stop:1 rgba(11,40,80,115)); border: 1px solid rgba(108,181,255,107); border-radius: 15px; }}
            QLabel#settingsNavProfile {{ color: {p['nav_muted']}; font-size: 12px; font-weight: 600; }}
            QLabel#settingsNavSection {{ color: {p['accent_text']}; font-family: "{display_font}"; font-size: 10px; font-weight: 800; letter-spacing: 1px; }}
            QFrame#settingsNavDivider {{ background: {nav_border}; border: 0; }}
            QLabel#settingsEyebrow {{ color: {p['accent_text']}; font-family: "{display_font}"; font-size: 12px; font-weight: 800; }}
            QLabel#settingsTitle {{ color: {p['heading']}; font-family: "{display_font}"; font-size: 30px; font-weight: 700; }}
            QLabel#cardHeading {{ color: {p['heading']}; font-family: "{display_font}"; font-size: 20px; font-weight: 700; }}
            QLabel#profileIdentity {{ color: {muted}; font-weight: 600; }}
            QLabel#settingsWarning {{ color: {warning}; font-weight: 650; }}
            QLabel#operationFeedback {{ background: {surface}; border: 1px solid {edge}; border-radius: 8px; padding: 12px; }}
            QLabel#operationFeedback[severity="error"] {{ color: {destructive}; border: 2px solid {destructive}; font-weight: 600; }}
            QLabel#operationFeedback[severity="warning"] {{ color: {warning}; border: 2px solid {warning}; font-weight: 600; }}
            QLabel#settingsNote, QLabel#settingsStorageNote, QLabel#settingsStorageSpace {{ color: {muted}; font-weight: 400; }}
            QFrame#settingsStorageComposition {{ background: {surface}; border: 1px solid {edge}; border-radius: 10px; }}
            QPushButton {{ font-family: "{body_font}"; background: {hover}; color: {text}; border: 1px solid {edge}; border-radius: 8px;
                           padding: 9px 13px; text-align: left; font-size: 14px; min-height: 24px; }}
            QPushButton:hover {{ background: {card}; border-color: {accent}; }}
            QPushButton:focus {{ border: 2px dashed {focus}; padding: 8px 12px; }}
            QPushButton:disabled {{ color: {muted}; background: {surface}; }}
            QPushButton#settingsNavItem, QPushButton#settingsNavSubitem {{ background: {sidebar}; color: {p['nav_text']}; border: 1px solid {sidebar}; font-weight: 600; }}
            QPushButton#settingsNavItem {{ min-height: {42 if theme == 'ethereal' else 46}px; padding: 0 14px; font-size: {15 if theme == 'ethereal' else 16}px; border-radius: 10px; }}
            QPushButton#settingsNavSubitem {{ margin-left: 38px; min-height: 30px; padding: 4px 9px; font-size: 13px; }}
            QPushButton#settingsNavItem:hover, QPushButton#settingsNavSubitem:hover {{ background: {nav_hover}; border-color: {nav_border}; }}
            QPushButton#settingsNavItem[selected="true"], QPushButton#settingsNavSubitem[selected="true"] {{ background: {nav_active}; border-color: {accent}; color: {p['heading']}; font-weight: 700; }}
            QPushButton#settingsNavItem:focus, QPushButton#settingsNavSubitem:focus {{ border: 2px dashed {focus}; }}
            QPushButton#destructiveAction {{ color: {destructive}; border-color: {destructive}; font-weight: 700; }}
            QPushButton#managedAction {{ border-color: {accent}; font-weight: 700; }}
            QPushButton#settingsNavToggle {{ background: {sidebar}; color: {p['nav_text']}; border-radius: 0; }}
            QPushButton#settingsDetailsToggle {{ background: {surface}; color: {p['accent_text']}; border-color: {edge}; font-size: 13px; }}
        """)
        self.brand_mark.setPixmap(sidebar_icon("settings", "#8ecbff", 34).pixmap(QSize(34, 34)))
        self.storage_composition.set_palette(entry)
        for button in getattr(self, "nav_buttons", []):
            icon = button.property("navIcon")
            if icon:
                button.setIcon(sidebar_icon(icon, button.property("navIconColor") or p["accent_text"]))
