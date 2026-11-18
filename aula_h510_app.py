#!/usr/bin/env python3
"""AULA H510 control panel for Linux, laid out like the official Windows app."""

import json
import os
import sys

from PyQt6.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QGridLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton,
    QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aula_device as dev  # noqa: E402
import aula_store as store  # noqa: E402
from aula_macro_ui import MacroEditor, MacroPicker  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCROLL_STEPS = [0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
ASSETS = os.path.join(HERE, "assets")
BLUE = "#0aa0e9"
TEXT = "#c8c8c8"


def pix(name):
    return QPixmap(os.path.join(ASSETS, name))


MENU_STYLE = f"""
QMenu {{ background: #060607; color: {TEXT}; border: 1px solid #646464; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 16px; }}
QMenu::item:selected {{ background: #43a7d6; color: black; }}
QMenu::separator {{ height: 1px; background: #333; margin: 4px 8px; }}
"""
PANEL_STYLE = f"""
QWidget {{ color: {TEXT}; font-size: 12px; }}
QLabel {{ background: transparent; }}
QComboBox {{ background: #111; border: 1px solid #1e5a7a; padding: 3px 6px; color: {TEXT}; }}
QComboBox QAbstractItemView {{ background: #060607; color: {TEXT}; selection-background-color: #43a7d6; }}
QSlider::groove:horizontal {{ height: 4px; background: #333; }}
QSlider::sub-page:horizontal {{ background: {BLUE}; }}
QSlider::handle:horizontal {{ background: #ddd; width: 10px; margin: -6px 0; border-radius: 3px; }}
QPushButton {{ background: #111; border: 1px solid #1e5a7a; padding: 4px 10px; color: {TEXT}; }}
QPushButton:hover {{ border-color: {BLUE}; color: white; }}
QCheckBox::indicator {{ width: 11px; height: 11px; }}
QCheckBox::indicator:unchecked {{ image: url({ASSETS}/check_nr.png); }}
QCheckBox::indicator:checked {{ image: url({ASSETS}/check_dn.png); }}
"""


class ImageButton(QPushButton):
    """A button drawn with the original skin images (normal / hover) plus text."""

    def __init__(self, parent, normal, hover, text="", font_size=11):
        super().__init__(parent)
        self.normal, self.hover = pix(normal), pix(hover)
        self.setFixedSize(self.normal.size())
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.selected = False
        self._font = QFont()
        self._font.setPixelSize(font_size)
        self.setStyleSheet("border: none; background: transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        hot = self.selected or self.underMouse() or self.isDown()
        p.drawPixmap(self.rect(), self.hover if hot else self.normal)
        p.setFont(self._font)
        p.setPen(QColor("white" if hot else TEXT))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class SectionHeader(QPushButton):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title = title
        self.open = False
        self.setFixedSize(245, 25)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("border: none; background: transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(self.rect(), pix("header_ov.png" if self.open or self.underMouse() else "header_nr.png"))
        f = QFont()
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(BLUE if self.open else TEXT))
        p.drawText(self.rect().adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.title)
        p.setPen(QPen(QColor("#888"), 1))
        p.drawLine(222, 12, 232, 12)


class ColorSwatch(QPushButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color = (0, 0, 0)

    def set_color(self, rgb):
        self.color = tuple(rgb)
        self.setStyleSheet(f"background: rgb{self.color}; border: 1px solid #444;")


class DpiCell(QWidget):
    clicked = pyqtSignal(int)

    def __init__(self, parent, index):
        super().__init__(parent)
        self.index = index
        self.value = 0
        self.selected = False
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, _):
        self.clicked.emit(self.index)

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(0, 0, pix("mouse/dpigrid_dn.png" if self.selected else "mouse/dpigrid_nr.png"))
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        p.drawText(QRect(0, 2, 42, 18), Qt.AlignmentFlag.AlignCenter, f"DPI {self.index + 1}")
        p.fillRect(QRect(3, 22, 36, 17), QColor("#f0f0f0"))
        p.setPen(QColor("#c00000" if self.selected else "#222"))
        p.drawText(QRect(3, 22, 36, 17), Qt.AlignmentFlag.AlignCenter, str(self.value))


class KeyDialog(QDialog):
    """Pick a keyboard key with optional Ctrl/Shift/Alt/Win."""

    def __init__(self, parent, raw):
        super().__init__(parent)
        self.setWindowTitle("Keyboard key")
        self.setStyleSheet(PANEL_STYLE + "QDialog { background: #0b0b0c; }")
        lay = QGridLayout(self)
        self.mods = []
        for col, (bit, name) in enumerate(dev.MOD_NAMES):
            cb = QCheckBox(name)
            cb.setChecked(raw[0] == dev.T_KEY and bool(raw[1] & bit))
            lay.addWidget(cb, 0, col)
            self.mods.append((bit, cb))
        self.key = QComboBox()
        for code, name in sorted(dev.HID_KEYS.items()):
            self.key.addItem(name, code)
        if raw[0] == dev.T_KEY and raw[2] in dev.HID_KEYS:
            self.key.setCurrentIndex(self.key.findData(raw[2]))
        lay.addWidget(QLabel("Key:"), 1, 0)
        lay.addWidget(self.key, 1, 1, 1, 3)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box, 2, 0, 1, 4)

    def raw(self):
        mods = sum(bit for bit, cb in self.mods if cb.isChecked())
        return bytes([dev.T_KEY, mods, self.key.currentData(), 0])


class MouseArt(QWidget):
    """The H510 artwork with numbered markers; the selected button glows."""

    # Marker centres measured from the official app's window.
    MARKERS = [
        [(377, 179)], [(488, 179)], [(434, 201)], [(434, 250)], [(434, 282)],
        [(341, 255), (626, 264)], [(346, 290), (656, 290)], [(346, 328), (665, 327)],
        [(603, 273)], [(609, 313)], [(613, 354)], [(640, 341)], [(634, 302)], [(648, 251)],
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.setGeometry(0, 0, 1030, 662)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.mouse = pix("mouse/mouse_nr.png")
        self.highlight = -1

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(300, 70, self.mouse)
        f = QFont()
        f.setPixelSize(10)
        f.setBold(True)
        p.setFont(f)
        for i, points in enumerate(self.MARKERS):
            label = dev.BUTTON_LABELS[i]
            if i < 8:
                label = label
            for x, y in points:
                hot = i == self.highlight
                p.setPen(QPen(QColor("#ffffff" if hot else "#000000"), 1.5))
                p.setBrush(QColor(BLUE if hot else "#e8d21d"))
                p.drawEllipse(QPoint(x, y), 9, 9)
                p.setPen(QColor("white" if hot else "black"))
                p.drawText(QRect(x - 10, y - 9, 20, 18), Qt.AlignmentFlag.AlignCenter, label)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AULA H510")
        self.setWindowIcon(QIcon(os.path.join(ASSETS, "aula-h510.png")))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(1030, 662)
        self.setStyleSheet(PANEL_STYLE)
        self._drag = None
        self.device = None
        self.original = None
        self.settings = None
        self.selected_stage = 0
        self.selected_button = -1
        self._loading = False
        self.macros = {}            # slot -> {"name", "mode", "count", "events", "index"}
        self.original_macros = {}
        self.pointer = store.PointerSettings()
        self.speed = self.original_speed = (self.pointer.pointer(), self.pointer.scroll())
        self.profile_name = None

        self.background = pix("main_nr.png")
        self.art = MouseArt(self)
        self._build_chrome()
        self._build_buttons()
        self._build_panels()
        self.connect_and_load()

    # ---------- layout ----------
    def _build_chrome(self):
        close = ImageButton(self, "exit_nr.png", "exit_ov.png")
        close.move(982, 12)
        close.clicked.connect(self.close)
        minimize = ImageButton(self, "min_nr.png", "min_ov.png")
        minimize.move(961, 12)
        minimize.clicked.connect(self.showMinimized)

        self.restore_btn = ImageButton(self, "btn_nr.png", "btn_ov.png", "Reload")
        self.restore_btn.move(55, 449)
        self.restore_btn.clicked.connect(self.connect_and_load)
        self.macro_btn = ImageButton(self, "btn_nr.png", "btn_ov.png", "Macro editor")
        self.macro_btn.move(165, 449)
        self.macro_btn.clicked.connect(self.open_macro_editor)

        lbl = QLabel("Profile", self)
        lbl.move(42, 528)
        self.profile = QComboBox(self)
        self.profile.setGeometry(42, 550, 189, 25)
        self.profile.activated.connect(self.on_profile_chosen)
        add = ImageButton(self, "add_nr.png", "add_ov.png")
        add.move(42, 586)
        add.setToolTip("New profile")
        add.clicked.connect(self.new_profile)
        delete = ImageButton(self, "del_nr.png", "del_ov.png")
        delete.move(113, 586)
        delete.setToolTip("Delete profile")
        delete.clicked.connect(self.delete_profile)
        more = ImageButton(self, "dot_nr.png", "dot_ov.png")
        more.move(185, 586)
        more.setToolTip("Rename, import or export")
        more.clicked.connect(lambda: self.profile_menu(more))

        QLabel("www.aulacn.com", self).move(42, 618)
        self.firmware = QLabel("Linux 1.1", self)
        self.firmware.setGeometry(46, 638, 300, 18)

        self.status = QLabel("", self)
        self.status.setGeometry(560, 640, 430, 18)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.reset_btn = ImageButton(self, "button3_nr.png", "button3_ov.png", "Undo")
        self.reset_btn.move(795, 600)
        self.reset_btn.clicked.connect(self.undo_changes)
        self.apply_btn = ImageButton(self, "button3_nr.png", "button3_ov.png", "Apply")
        self.apply_btn.move(895, 600)
        self.apply_btn.clicked.connect(self.apply)

    def _build_buttons(self):
        self.button_widgets = []
        for i, label in enumerate(dev.BUTTON_LABELS):
            y = 62 + 27 * i
            badge = QLabel(label, self)
            badge.setGeometry(42, y - 12, 25, 25)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"border: 2px solid {BLUE}; border-radius: 12px; color: white;"
                                "font-weight: bold; font-size: 11px; background: #050505;")
            b = ImageButton(self, "button2_nr.png", "button2_ov.png", "", 12)
            b.move(75, y - 12)
            b.clicked.connect(lambda _=False, slot=i: self.open_button_menu(slot))
            b.installEventFilter(self)
            self.button_widgets.append(b)

    def _build_panels(self):
        frame = QWidget(self)
        frame.setGeometry(743, 41, 245, 397)
        frame.setStyleSheet("background: rgba(0,0,0,110); border: 1px solid #1e5a7a;")
        frame.lower()
        self.background_frame = frame

        self.section_titles = ["DPI settings", "Lighting", "Polling rate", "Mouse speed"]
        self.stack = QStackedWidget(self)
        self.stack.setGeometry(744, 67, 243, 370)
        self.stack.setStyleSheet("background: transparent;")
        # The top header names the open section; the three below open the others.
        self.headers = []
        for y in (41, 443, 473, 503):
            h = SectionHeader(self, "")
            h.move(743, y)
            h.clicked.connect(lambda _=False, hdr=h: self.show_section(hdr.section))
            self.headers.append(h)
        self.stack.addWidget(self._dpi_page())
        self.stack.addWidget(self._lighting_page())
        self.stack.addWidget(self._rate_page())
        self.stack.addWidget(self._speed_page())
        self.show_section(0)

    def show_section(self, n):
        self.stack.setCurrentIndex(n)
        order = [n] + [i for i in range(len(self.section_titles)) if i != n]
        for h, section in zip(self.headers, order):
            h.section = section
            h.title = self.section_titles[section]
            h.open = section == n
            h.update()

    def _dpi_page(self):
        page = QWidget()
        for x, text in ((21, "ON"), (53, "DPI"), (86, "Colour")):
            lbl = QLabel(text, page)
            lbl.move(x, 16)
        self.stage_checks, self.stage_cells, self.stage_colors = [], [], []
        for i in range(dev.DPI_STAGES):
            y = 44 + 47 * i
            cb = QCheckBox(page)
            cb.move(21, y + 14)
            cb.toggled.connect(self.on_stages_toggled)
            cell = DpiCell(page, i)
            cell.move(39, y)
            cell.clicked.connect(self.select_stage)
            sw = ColorSwatch(page)
            sw.move(88, y + 11)
            sw.clicked.connect(lambda _=False, n=i: self.pick_stage_color(n))
            self.stage_checks.append(cb)
            self.stage_cells.append(cell)
            self.stage_colors.append(sw)

        top = QLabel("200", page)
        top.setGeometry(176, 20, 40, 16)
        top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dpi_slider = QSlider(Qt.Orientation.Vertical, page)
        self.dpi_slider.setGeometry(181, 40, 30, 290)
        self.dpi_slider.setRange(0, len(dev.DPI_TABLE) - 1)
        self.dpi_slider.setInvertedAppearance(True)
        self.dpi_slider.setStyleSheet(
            f"QSlider::groove:vertical {{ width: 4px; background: {BLUE}; }}"
            f"QSlider::handle:vertical {{ image: url({ASSETS}/mouse/slider.png); height: 30px; margin: 0 -13px; }}")
        self.dpi_slider.valueChanged.connect(self.on_slider)
        bottom = QLabel("12400", page)
        bottom.setGeometry(176, 334, 40, 16)
        bottom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_dpi = QLabel("", page)
        self.current_dpi.setGeometry(21, 346, 200, 18)
        return page

    def _lighting_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(QLabel("Effect"))
        self.effect = QComboBox()
        for eid, name, *_ in dev.EFFECTS:
            self.effect.addItem(name, eid)
        self.effect.currentIndexChanged.connect(self.on_effect_changed)
        lay.addWidget(self.effect)
        self.brightness_label = QLabel("Brightness")
        lay.addWidget(self.brightness_label)
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(1, 4)
        self.brightness.valueChanged.connect(self.on_effect_mode)
        lay.addWidget(self.brightness)
        self.speed_label = QLabel("Speed")
        lay.addWidget(self.speed_label)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 3)
        self.speed_slider.valueChanged.connect(self.on_effect_mode)
        lay.addWidget(self.speed_slider)
        self.effect_color_btn = QPushButton("Colour")
        self.effect_color_btn.clicked.connect(self.pick_effect_color)
        lay.addWidget(self.effect_color_btn)
        lay.addStretch()
        return page

    def _rate_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(QLabel("USB polling rate"))
        self.rate = QComboBox()
        for hz in (125, 250, 500, 1000):
            self.rate.addItem(f"{hz} Hz", hz)
        self.rate.currentIndexChanged.connect(self.on_rate)
        lay.addWidget(self.rate)
        lay.addStretch()
        return page

    def _speed_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(QLabel("Cursor speed"))
        self.cursor_speed = QSlider(Qt.Orientation.Horizontal)
        self.cursor_speed.setRange(-10, 10)
        self.cursor_speed.valueChanged.connect(self.on_speed)
        lay.addWidget(self.cursor_speed)
        self.cursor_speed_label = QLabel("")
        self.cursor_speed_label.setStyleSheet("color: #888;")
        lay.addWidget(self.cursor_speed_label)
        lay.addSpacing(10)
        lay.addWidget(QLabel("Scroll speed"))
        self.scroll_speed = QSlider(Qt.Orientation.Horizontal)
        self.scroll_speed.setRange(0, len(SCROLL_STEPS) - 1)
        self.scroll_speed.valueChanged.connect(self.on_speed)
        lay.addWidget(self.scroll_speed)
        self.scroll_speed_label = QLabel("")
        self.scroll_speed_label.setStyleSheet("color: #888;")
        lay.addWidget(self.scroll_speed_label)
        lay.addSpacing(10)
        note = QLabel("These take effect straight away and\nare saved with the profile.")
        note.setStyleSheet("color: #888;")
        lay.addWidget(note)
        if not self.pointer.available:
            for w in (self.cursor_speed, self.scroll_speed):
                w.setEnabled(False)
            note.setText("Couldn't reach KDE's input settings,\nso speed can't be changed here.")
        lay.addStretch()
        return page

    # ---------- painting / window dragging ----------
    def paintEvent(self, _):
        QPainter(self).drawPixmap(0, 0, self.background)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle and handle.startSystemMove():
                return
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _):
        self._drag = None

    def eventFilter(self, obj, event):
        if obj in self.button_widgets:
            if event.type() == event.Type.Enter:
                self.art.highlight = self.button_widgets.index(obj)
                self.art.update()
            elif event.type() == event.Type.Leave:
                self.art.highlight = self.selected_button
                self.art.update()
        return False

    # ---------- device and profiles ----------
    def connect_and_load(self):
        try:
            if self.device is None:
                self.device = dev.AulaH510()
            self.original = dev.Settings.load(self.device)
            self.settings = self.original.copy()
            self.firmware.setText(f"Linux 1.1  ·  firmware {self.device.firmware()}")
        except (dev.MouseError, OSError) as exc:
            self.device = None
            self.set_status(str(exc), error=True)
            return
        self._load_profile_state()
        self.set_status("Settings loaded from the mouse.")
        self.refresh()

    def _load_profile_state(self):
        """Pick the current profile; the mouse's own settings are what we show."""
        names = store.list_profiles()
        if not names:
            name = "Profile 1"
            store.save_profile(name, store.profile_from_settings(self.original, {}, *self.speed))
            names = [name]
        name = store.current_profile()
        if name not in names:
            name = names[0]
        self.profile_name = name
        store.set_current_profile(name)
        profile = store.load_profile(name) or {}
        # Macros can't be read back from the mouse, so take them from the profile,
        # but only for buttons that still point at that macro slot.
        self.macros = {}
        for slot, m in {int(k): v for k, v in profile.get("macros", {}).items()}.items():
            raw = self.original.button(slot)
            if raw[0] == dev.T_MACRO and raw[1] == m.get("index"):
                self.macros[slot] = m
        self.original_macros = {k: dict(v) for k, v in self.macros.items()}
        self._fill_profile_combo()

    def _fill_profile_combo(self):
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItems(store.list_profiles())
        self.profile.setCurrentText(self.profile_name)
        self.profile.blockSignals(False)

    def _current_profile_data(self):
        return store.profile_from_settings(self.settings, self.macros, *self.speed)

    def on_profile_chosen(self, _index):
        name = self.profile.currentText()
        if not name or name == self.profile_name or self.device is None:
            return
        if self.is_dirty():
            r = QMessageBox.question(self, "AULA H510",
                                     f"Save your unapplied changes to “{self.profile_name}” first?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                     | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                self._fill_profile_combo()
                return
            if r == QMessageBox.StandardButton.Save:
                store.save_profile(self.profile_name, self._current_profile_data())
        profile = store.load_profile(name)
        if not profile:
            self._fill_profile_combo()
            return
        self.settings, self.macros = store.settings_from_profile(profile, self.original)
        self.speed = (profile.get("pointer", self.speed[0]), profile.get("scroll", self.speed[1]))
        self._apply_speed()
        self.profile_name = name
        store.set_current_profile(name)
        # Like the original app, switching a profile applies it to the mouse.
        self.apply(force_macros=True)

    def new_profile(self):
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:",
                                        text=store.unique_name(store.list_profiles(), "Profile"))
        if not ok or not name.strip():
            return
        name = store.unique_name(store.list_profiles(), name.strip())
        store.save_profile(name, self._current_profile_data())
        self.profile_name = name
        store.set_current_profile(name)
        self._fill_profile_combo()
        self.set_status(f"Created “{name}” from the current settings.")

    def delete_profile(self):
        names = store.list_profiles()
        if len(names) <= 1:
            QMessageBox.information(self, "AULA H510", "You need at least one profile.")
            return
        r = QMessageBox.question(self, "Delete profile", f"Delete “{self.profile_name}”?")
        if r != QMessageBox.StandardButton.Yes:
            return
        store.delete_profile(self.profile_name)
        names.remove(self.profile_name)
        self.profile_name = None
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItems(names)
        self.profile.blockSignals(False)
        self.profile.setCurrentText(names[0])
        self.on_profile_chosen(0)

    def profile_menu(self, anchor):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        for text, fn in (("Rename profile…", self.rename_profile), ("Import profile…", self.import_profile),
                         ("Export profile…", self.export_profile)):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def rename_profile(self):
        name, ok = QInputDialog.getText(self, "Rename profile", "New name:", text=self.profile_name)
        if ok and name.strip() and name.strip() != self.profile_name:
            new = store.unique_name(store.list_profiles(), name.strip())
            store.rename_profile(self.profile_name, new)
            self.profile_name = new
            store.set_current_profile(new)
            self._fill_profile_combo()

    def export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export profile",
                                              os.path.expanduser(f"~/{self.profile_name}.json"), "Profile (*.json)")
        if path:
            data = self._current_profile_data()
            for m in data["macros"].values():
                m["events"] = m.get("events", [])
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            self.set_status(f"Exported to {path}")

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", os.path.expanduser("~"), "Profile (*.json)")
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
            bytes.fromhex(data["config"]), bytes.fromhex(data["buttons"])
        except (OSError, ValueError, KeyError):
            QMessageBox.warning(self, "AULA H510", "That file isn't an AULA H510 profile.")
            return
        name = store.unique_name(store.list_profiles(), os.path.splitext(os.path.basename(path))[0])
        store.save_profile(name, data)
        for m in data.get("macros", {}).values():
            if m.get("name") and m["name"] not in store.list_macros():
                store.save_macro(m["name"], {"events": m.get("events", [])})
        self._fill_profile_combo()
        self.profile.setCurrentText(name)
        self.on_profile_chosen(0)

    # ---------- status ----------
    def set_status(self, text, error=False):
        self.status.setStyleSheet(f"color: {'#ff6060' if error else '#9fd9f5'};")
        self.status.setText(text)

    def is_dirty(self):
        return (self.settings is not None and
                (self.settings.config != self.original.config or
                 self.settings.buttons != self.original.buttons or
                 self.macros != self.original_macros or
                 self.speed != self.original_speed))

    def mark_dirty(self):
        self.set_status("Unsaved changes. Click Apply to write them to the mouse." if self.is_dirty() else "")

    def refresh(self):
        s = self.settings
        if s is None:
            return
        self._loading = True
        for i, b in enumerate(self.button_widgets):
            raw = s.button(i)
            if raw[0] == dev.T_MACRO and i in self.macros:
                b.setText(f"Macro: {self.macros[i]['name']}")
            else:
                b.setText(dev.describe_button(raw))
            b.selected = i == self.selected_button
            b.update()
        active = s.active_stage()
        for i in range(dev.DPI_STAGES):
            self.stage_checks[i].setChecked(s.stage_enabled(i))
            self.stage_cells[i].value = s.stage_dpi(i)
            self.stage_cells[i].selected = i == self.selected_stage
            self.stage_cells[i].update()
            self.stage_colors[i].set_color(s.stage_color(i))
        self.dpi_slider.setValue(dev.DPI_TABLE.index(s.stage_dpi(self.selected_stage)))
        self.current_dpi.setText(f"Current DPI: {s.stage_dpi(active)}  (stage {active + 1})")
        self.effect.setCurrentIndex(max(0, self.effect.findData(s.effect)))
        self._refresh_effect_controls()
        self.rate.setCurrentIndex(self.rate.findData(s.polling_rate))
        self._refresh_speed()
        self.art.highlight = self.selected_button
        self.art.update()
        self._loading = False

    def _refresh_effect_controls(self):
        s = self.settings
        info = dev.EFFECT_BY_ID.get(s.effect)
        has_mode = bool(info and info[2])
        for w in (self.brightness, self.brightness_label):
            w.setVisible(has_mode)
        for w in (self.speed_slider, self.speed_label):
            w.setVisible(has_mode and info[5])
        self.brightness.setValue(max(1, s.effect_brightness()))
        self.speed_slider.setValue(max(1, s.effect_speed()))
        color = s.effect_color()
        self.effect_color_btn.setVisible(color is not None)
        if color is not None:
            self.effect_color_btn.setStyleSheet(
                f"background: rgb{tuple(color)}; color: {'black' if sum(color) > 380 else 'white'};")

    def _refresh_speed(self):
        pointer, scroll = self.speed
        self.cursor_speed.setValue(round(pointer * 10))
        self.scroll_speed.setValue(min(range(len(SCROLL_STEPS)), key=lambda i: abs(SCROLL_STEPS[i] - scroll)))
        self.cursor_speed_label.setText(f"{'+' if pointer > 0 else ''}{pointer:.1f}  (0 is the default)")
        self.scroll_speed_label.setText(f"{scroll:g}×  (1× is the default)")

    def _apply_speed(self):
        if self.pointer.available:
            self.pointer.set_pointer(self.speed[0])
            self.pointer.set_scroll(self.speed[1])

    def on_speed(self):
        if self._loading:
            return
        self.speed = (self.cursor_speed.value() / 10, SCROLL_STEPS[self.scroll_speed.value()])
        self._apply_speed()
        self._loading = True
        self._refresh_speed()
        self._loading = False
        self.mark_dirty()

    # ---------- edits ----------
    def open_button_menu(self, slot):
        if self.settings is None:
            return
        self.selected_button = slot
        self.refresh()
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        current = self.settings.button(slot)

        def add(target, name, raw):
            act = QAction(name, target)
            act.setCheckable(True)
            act.setChecked(raw == current)
            act.triggered.connect(lambda _=False, r=raw: self.set_button(slot, r))
            target.addAction(act)

        for name, raw in dev.SIMPLE_ACTIONS:
            add(menu, name, raw)
        media = menu.addMenu("Multimedia")
        media.setStyleSheet(MENU_STYLE)
        for name, raw in dev.MEDIA_ACTIONS:
            add(media, name, raw)
        menu.addSeparator()
        key = QAction("Keyboard key / shortcut…", menu)
        key.triggered.connect(lambda: self.pick_key(slot))
        menu.addAction(key)
        macro = QAction("Macro…", menu)
        macro.setCheckable(True)
        macro.setChecked(current[0] == dev.T_MACRO)
        macro.triggered.connect(lambda: self.pick_macro(slot))
        menu.addAction(macro)
        if current[0] in (dev.T_DPI_LOCK, dev.T_REPEAT) or (current[0] == dev.T_MACRO and slot not in self.macros):
            keep = QAction(f"Keep: {dev.describe_button(current)}", menu)
            keep.setCheckable(True)
            keep.setChecked(True)
            menu.addAction(keep)
        menu.exec(self.button_widgets[slot].mapToGlobal(QPoint(self.button_widgets[slot].width(), 0)))

    def set_button(self, slot, raw):
        self.settings.set_button(slot, raw)
        if raw[0] != dev.T_MACRO:
            self.macros.pop(slot, None)
        self.refresh()
        self.mark_dirty()

    def pick_key(self, slot):
        dlg = KeyDialog(self, self.settings.button(slot))
        if dlg.exec():
            self.set_button(slot, dlg.raw())

    def _free_macro_index(self, slot):
        """Macro memory slot for this button: keep its own, else the lowest one no other button uses."""
        raw = self.settings.button(slot)
        if raw[0] == dev.T_MACRO and raw[1]:
            used_elsewhere = any(self.settings.button(i)[0] == dev.T_MACRO and self.settings.button(i)[1] == raw[1]
                                 for i in range(len(dev.BUTTON_LABELS)) if i != slot)
            if not used_elsewhere:
                return raw[1]
        used = {self.settings.button(i)[1] for i in range(len(dev.BUTTON_LABELS))
                if i != slot and self.settings.button(i)[0] == dev.T_MACRO}
        return next((n for n in range(1, dev.MACRO_SLOTS + 1) if n not in used), None)

    def pick_macro(self, slot):
        dlg = MacroPicker(self, dev.BUTTON_LABELS[slot], self.macros.get(slot))
        if not dlg.exec():
            return
        assignment = dlg.result_assignment()
        if not assignment["events"]:
            QMessageBox.information(self, "AULA H510", f"“{assignment['name']}” has no keys yet. "
                                    "Record it in the macro editor first.")
            return
        assignment["index"] = self._free_macro_index(slot)
        if assignment["index"] is None:
            QMessageBox.information(self, "AULA H510", f"The mouse holds at most {dev.MACRO_SLOTS} macros. "
                                    "Remove one from another button first.")
            return
        self.settings.set_button(slot, bytes([dev.T_MACRO, assignment["index"], assignment["mode"], assignment["count"]]))
        self.macros[slot] = assignment
        self.refresh()
        self.mark_dirty()

    def open_macro_editor(self):
        MacroEditor(self).exec()
        # Buttons using an edited macro pick up its new keys on the next Apply.
        changed = False
        for m in self.macros.values():
            events = store.load_macro(m["name"]).get("events", m.get("events", []))
            if events and events != m.get("events"):
                m["events"] = events
                changed = True
        if changed:
            self.refresh()
            self.mark_dirty()

    def select_stage(self, n):
        self.selected_stage = n
        self.refresh()

    def on_slider(self, value):
        if self._loading or self.settings is None:
            return
        self.settings.set_stage_dpi(self.selected_stage, dev.DPI_TABLE[value])
        self.stage_cells[self.selected_stage].value = dev.DPI_TABLE[value]
        self.stage_cells[self.selected_stage].update()
        active = self.settings.active_stage()
        self.current_dpi.setText(f"Current DPI: {self.settings.stage_dpi(active)}  (stage {active + 1})")
        self.mark_dirty()

    def on_stages_toggled(self):
        if self._loading or self.settings is None:
            return
        flags = [cb.isChecked() for cb in self.stage_checks]
        if not any(flags):
            self._loading = True
            self.sender().setChecked(True)
            self._loading = False
            return
        self.settings.set_stages_enabled(flags, None)
        self.refresh()
        self.mark_dirty()

    def pick_stage_color(self, n):
        c = QColorDialog.getColor(QColor(*self.settings.stage_color(n)), self, f"DPI {n + 1} colour")
        if c.isValid():
            self.settings.set_stage_color(n, (c.red(), c.green(), c.blue()))
            self.refresh()
            self.mark_dirty()

    def on_effect_changed(self):
        if self._loading or self.settings is None:
            return
        self.settings.effect = self.effect.currentData()
        self._loading = True
        self._refresh_effect_controls()
        self._loading = False
        self.mark_dirty()

    def on_effect_mode(self):
        if self._loading or self.settings is None:
            return
        self.settings.set_effect_mode(self.brightness.value(), self.speed_slider.value())
        self.mark_dirty()

    def pick_effect_color(self):
        c = QColorDialog.getColor(QColor(*self.settings.effect_color()), self, "Lighting colour")
        if c.isValid():
            self.settings.set_effect_color((c.red(), c.green(), c.blue()))
            self._refresh_effect_controls()
            self.mark_dirty()

    def on_rate(self):
        if not self._loading and self.settings is not None:
            self.settings.polling_rate = self.rate.currentData()
            self.mark_dirty()

    def undo_changes(self):
        if self.original is not None:
            self.settings = self.original.copy()
            self.macros = {k: dict(v) for k, v in self.original_macros.items()}
            if self.speed != self.original_speed:
                self.speed = self.original_speed
                self._apply_speed()
            self.refresh()
            self.set_status("Changes discarded.")

    def apply(self, force_macros=False):
        if self.device is None or self.settings is None:
            self.connect_and_load()
            return
        try:
            # Macros first, so a button never points at a macro that isn't there yet.
            for slot, m in self.macros.items():
                if force_macros or self.original_macros.get(slot) != m:
                    self.device.write_macro(m["index"], store.macro_to_device_events({"events": m["events"]}))
            self.settings.save(self.device, self.original)
            readback = dev.Settings.load(self.device)
        except (dev.MouseError, OSError) as exc:
            QMessageBox.critical(self, "AULA H510", f"Writing to the mouse failed:\n{exc}")
            return
        ok = (readback.config[4:dev.CONFIG_SIZE] == self.settings.config[4:dev.CONFIG_SIZE] and
              readback.buttons[4:dev.BUTTON_SIZE] == self.settings.buttons[4:dev.BUTTON_SIZE])
        self.original = readback
        self.settings = readback.copy()
        self.original_macros = {k: dict(v) for k, v in self.macros.items()}
        self.original_speed = self.speed
        if self.profile_name:
            store.save_profile(self.profile_name, self._current_profile_data())
        self.refresh()
        if ok:
            self.set_status(f"Saved to the mouse and to “{self.profile_name}”.")
        else:
            self.set_status("The mouse did not keep every change; showing what it saved.", error=True)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AULA H510")
    app.setDesktopFileName("aula-h510")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
