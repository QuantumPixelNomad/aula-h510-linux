"""Macro editor window and per-button macro picker for the AULA H510 app."""

import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QRadioButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

import aula_device as dev
import aula_store as store

BLUE = "#0aa0e9"
TEXT = "#c8c8c8"
STYLE = f"""
QDialog {{ background: #000000; border: 1px solid #1e5a7a; }}
QWidget {{ color: {TEXT}; font-size: 12px; }}
QLabel#title {{ color: {BLUE}; font-size: 14px; }}
QListWidget, QTreeWidget {{ background: #0b0b0c; border: 1px solid #1e5a7a; color: {TEXT}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: #43a7d6; color: black; }}
QPushButton {{ background: #111; border: 1px solid #1e5a7a; padding: 5px 10px; color: {TEXT}; }}
QPushButton:hover {{ border-color: {BLUE}; color: white; }}
QPushButton:disabled {{ color: #555; border-color: #333; }}
QPushButton#record {{ background: #3a0b0b; border-color: #a33; font-weight: bold; }}
QPushButton#record:checked {{ background: #c62828; color: white; }}
QComboBox {{ background: #111; border: 1px solid #1e5a7a; padding: 3px; color: {TEXT}; }}
QSpinBox {{ background: #111; color: {TEXT}; selection-background-color: #43a7d6; }}
QHeaderView::section {{ background: #111; color: {TEXT}; border: none; padding: 3px; }}
QMenu {{ background: #060607; color: {TEXT}; border: 1px solid #646464; }}
QMenu::item:selected {{ background: #43a7d6; color: black; }}
"""

# Linux evdev key code -> USB HID keyboard usage (keys a macro can record).
EVDEV_TO_HID = {
    1: 0x29, 14: 0x2A, 15: 0x2B, 28: 0x28, 57: 0x2C, 58: 0x39,
    12: 0x2D, 13: 0x2E, 26: 0x2F, 27: 0x30, 43: 0x31, 39: 0x33, 40: 0x34, 41: 0x35,
    51: 0x36, 52: 0x37, 53: 0x38,
    29: 0xE0, 42: 0xE1, 56: 0xE2, 125: 0xE3, 97: 0xE4, 54: 0xE5, 100: 0xE6, 126: 0xE7,
    87: 0x44, 88: 0x45, 99: 0x46, 70: 0x47, 119: 0x48, 110: 0x49, 102: 0x4A, 104: 0x4B,
    111: 0x4C, 107: 0x4D, 109: 0x4E, 106: 0x4F, 105: 0x50, 108: 0x51, 103: 0x52,
    69: 0x53, 98: 0x54, 55: 0x55, 74: 0x56, 78: 0x57, 96: 0x58, 79: 0x59, 80: 0x5A,
    81: 0x5B, 75: 0x5C, 76: 0x5D, 77: 0x5E, 71: 0x5F, 72: 0x60, 73: 0x61, 82: 0x62,
    83: 0x63, 127: 0x65,
}
for _i, _code in enumerate(range(2, 12)):          # 1..0
    EVDEV_TO_HID[_code] = 0x1E + _i
for _i, _code in enumerate(range(59, 69)):         # F1..F10
    EVDEV_TO_HID[_code] = 0x3A + _i
for _row, _keys in ((16, "qwertyuiop"), (30, "asdfghjkl"), (44, "zxcvbnm")):
    for _i, _c in enumerate(_keys):
        EVDEV_TO_HID[_row + _i] = 0x04 + ord(_c) - ord("a")


class EventList(QTreeWidget):
    """Two-column list (action, delay) with the few QListWidget-style helpers the editor uses."""

    def __init__(self):
        super().__init__()
        self.setColumnCount(2)
        self.setHeaderLabels(["Action", "Delay"])
        self.setRootIsDecorated(False)
        self.setColumnWidth(0, 175)

    def currentRow(self):
        item = self.currentItem()
        return self.indexOfTopLevelItem(item) if item else -1

    def setCurrentRow(self, row):
        self.setCurrentItem(self.topLevelItem(row))

    def count(self):
        return self.topLevelItemCount()


def event_label(ev):
    arrow = "↓" if ev["down"] else "↑"
    verb = "press" if ev["down"] else "release"
    return f"{arrow}  {store.macro_event_text(ev)} {verb}"


class MacroEditor(QDialog):
    """Create, record and edit macros. They are saved on this computer."""

    def __init__(self, parent=None, select=None):
        super().__init__(parent)
        self.setWindowTitle("Macro editor")
        self.setStyleSheet(STYLE)
        self.setFixedSize(767, 418)
        self.recording = False
        self.last_time = None
        self.current = None
        self.dirty = False

        title = QLabel("Macro editor")
        title.setObjectName("title")

        # Left: macro list
        self.macros = QListWidget()
        self.macros.currentTextChanged.connect(self.open_macro)
        new = QPushButton("New")
        new.clicked.connect(self.new_macro)
        rename = QPushButton("Rename")
        rename.clicked.connect(self.rename_macro)
        delete = QPushButton("Delete")
        delete.clicked.connect(self.delete_macro)
        left = QVBoxLayout()
        left.addWidget(QLabel("Macro list"))
        left.addWidget(self.macros)
        row = QHBoxLayout()
        for b in (new, rename, delete):
            row.addWidget(b)
        left.addLayout(row)

        # Middle: event list
        self.events = EventList()
        self.events.itemDoubleClicked.connect(lambda *_: self.edit_delay())
        self.events.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.events.customContextMenuRequested.connect(self.event_menu)
        mid = QVBoxLayout()
        mid.addWidget(QLabel("Key list  (double-click a line to change its delay)"))
        mid.addWidget(self.events)

        # Right: recording and editing tools
        self.record_btn = QPushButton("●  Start recording")
        self.record_btn.setObjectName("record")
        self.record_btn.setCheckable(True)
        self.record_btn.toggled.connect(self.toggle_record)
        self.auto_delay = QCheckBox("Record real delays")
        self.auto_delay.setChecked(True)
        self.fixed_delay = QSpinBox()
        self.fixed_delay.setRange(1, dev.MACRO_MAX_DELAY)
        self.fixed_delay.setValue(10)
        self.fixed_delay.setSuffix(" ms")
        self.fixed_delay.setMinimumWidth(90)
        add_key = QPushButton("Add key…")
        add_key.clicked.connect(self.add_key)
        add_click = QPushButton("Add mouse click…")
        add_click.clicked.connect(self.add_click)
        edit_delay = QPushButton("Change delay…")
        edit_delay.clicked.connect(self.edit_delay)
        up = QPushButton("Move up")
        up.clicked.connect(lambda: self.move_event(-1))
        down = QPushButton("Move down")
        down.clicked.connect(lambda: self.move_event(1))
        remove = QPushButton("Delete line")
        remove.clicked.connect(self.remove_event)
        clear = QPushButton("Clear all")
        clear.clicked.connect(self.clear_events)
        self.save_btn = QPushButton("Save macro")
        self.save_btn.clicked.connect(self.save_macro)
        close = QPushButton("Close")
        close.clicked.connect(self.close)

        right = QVBoxLayout()
        right.addWidget(self.record_btn)
        right.addWidget(self.auto_delay)
        drow = QHBoxLayout()
        drow.addWidget(QLabel("Otherwise:"))
        drow.addWidget(self.fixed_delay)
        right.addLayout(drow)
        right.addSpacing(6)
        grid = QGridLayout()
        for n, b in enumerate((add_key, add_click, edit_delay, remove, up, down)):
            grid.addWidget(b, n // 2, n % 2)
        right.addLayout(grid)
        right.addWidget(clear)
        right.addStretch()
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9fd9f5;")
        right.addWidget(self.hint)
        brow = QHBoxLayout()
        brow.addWidget(self.save_btn)
        brow.addWidget(close)
        right.addLayout(brow)

        body = QHBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(mid, 4)
        body.addLayout(right, 3)
        outer = QVBoxLayout(self)
        outer.addWidget(title)
        outer.addLayout(body)

        self.reload_list(select)

    # ---------- list management ----------
    def reload_list(self, select=None):
        self.macros.blockSignals(True)
        self.macros.clear()
        names = store.list_macros()
        self.macros.addItems(names)
        self.macros.blockSignals(False)
        if select in names:
            self.macros.setCurrentRow(names.index(select))
        elif names:
            self.macros.setCurrentRow(0)
        else:
            self.current = None
            self.data = {"events": []}
            self.render_events()
        self.update_enabled()

    def update_enabled(self):
        has = self.current is not None
        for w in (self.events, self.record_btn, self.save_btn):
            w.setEnabled(has)
        if not has:
            self.hint.setText("Click New to create your first macro.")

    def maybe_save(self):
        if self.dirty and self.current:
            r = QMessageBox.question(self, "Macro editor", f"Save changes to “{self.current}”?")
            if r == QMessageBox.StandardButton.Yes:
                self.save_macro()
        self.dirty = False

    def open_macro(self, name):
        if self.recording:
            self.record_btn.setChecked(False)
        self.maybe_save()
        self.current = name or None
        self.data = store.load_macro(name) if name else {"events": []}
        self.render_events()
        self.update_enabled()
        self.hint.setText("")

    def new_macro(self):
        name, ok = QInputDialog.getText(self, "New macro", "Macro name:",
                                        text=store.unique_name(store.list_macros(), "Macro"))
        if ok and name.strip():
            self.maybe_save()
            name = store.unique_name(store.list_macros(), name.strip())
            store.save_macro(name, {"events": []})
            self.reload_list(name)
            self.hint.setText("Press Start recording, then type the keys.")

    def rename_macro(self):
        if not self.current:
            return
        name, ok = QInputDialog.getText(self, "Rename macro", "New name:", text=self.current)
        if ok and name.strip() and name.strip() != self.current:
            self.save_macro()
            new = store.unique_name(store.list_macros(), name.strip())
            store.rename_macro(self.current, new)
            self.reload_list(new)

    def delete_macro(self):
        if not self.current:
            return
        r = QMessageBox.question(self, "Delete macro", f"Delete “{self.current}”?")
        if r == QMessageBox.StandardButton.Yes:
            store.delete_macro(self.current)
            self.dirty = False
            self.reload_list()

    def save_macro(self):
        if self.current:
            store.save_macro(self.current, self.data)
            self.dirty = False
            self.hint.setText(f"Saved “{self.current}”.")

    # ---------- events ----------
    def render_events(self, select=None):
        self.events.clear()
        for ev in self.data["events"]:
            item = QTreeWidgetItem([event_label(ev), f"{ev['delay']} ms"])
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.events.addTopLevelItem(item)
        if select is not None and 0 <= select < self.events.count():
            self.events.setCurrentRow(select)
        else:
            self.events.scrollToBottom()
        count = len(self.data["events"])
        if count > dev.MACRO_MAX_EVENTS:
            self.hint.setText(f"The mouse keeps only the first {dev.MACRO_MAX_EVENTS} lines.")

    def changed(self, select=None):
        self.dirty = True
        self.render_events(select)

    def append(self, kind, code, down):
        now = time.monotonic()
        evs = self.data["events"]
        if evs:
            if self.auto_delay.isChecked() and self.last_time is not None:
                evs[-1]["delay"] = max(1, min(dev.MACRO_MAX_DELAY, round((now - self.last_time) * 1000)))
            else:
                evs[-1]["delay"] = self.fixed_delay.value()
        self.last_time = now
        evs.append({"kind": kind, "code": code, "down": down, "delay": self.fixed_delay.value()})
        self.changed()

    def toggle_record(self, on):
        self.recording = on
        self.last_time = None
        self.record_btn.setText("■  Stop recording" if on else "●  Start recording")
        if on:
            self.hint.setText("Recording keys… Press Stop when you are done.")
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
            self.hint.setText("Recording stopped. Click Save macro to keep it.")

    def keyPressEvent(self, e):
        if self.recording:
            if not e.isAutoRepeat():
                code = EVDEV_TO_HID.get(e.nativeScanCode() - 8)
                if code:
                    self.append("key", code, True)
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if self.recording:
            if not e.isAutoRepeat():
                code = EVDEV_TO_HID.get(e.nativeScanCode() - 8)
                if code:
                    self.append("key", code, False)
            return
        super().keyReleaseEvent(e)

    def insert_pair(self, kind, code):
        row = self.events.currentRow()
        pos = row + 1 if row >= 0 else len(self.data["events"])
        d = self.fixed_delay.value()
        self.data["events"][pos:pos] = [
            {"kind": kind, "code": code, "down": True, "delay": d},
            {"kind": kind, "code": code, "down": False, "delay": d},
        ]
        self.changed(pos + 1)

    def add_key(self):
        names = [n for _, n in sorted(dev.MACRO_KEYS.items())]
        codes = [c for c, _ in sorted(dev.MACRO_KEYS.items())]
        name, ok = QInputDialog.getItem(self, "Add key", "Key (adds a press and a release):", names, 0, False)
        if ok:
            self.insert_pair("key", codes[names.index(name)])

    def add_click(self):
        menu = QMenu(self)
        for code, name in dev.MACRO_BUTTONS.items():
            act = QAction(name, menu)
            act.triggered.connect(lambda _=False, c=code: self.insert_pair("button", c))
            menu.addAction(act)
        menu.exec(self.cursor().pos())

    def edit_delay(self):
        row = self.events.currentRow()
        if row < 0:
            return
        ev = self.data["events"][row]
        val, ok = QInputDialog.getInt(self, "Delay", "Delay after this line (ms):",
                                      ev["delay"], 1, dev.MACRO_MAX_DELAY)
        if ok:
            ev["delay"] = val
            self.changed(row)

    def move_event(self, step):
        row = self.events.currentRow()
        new = row + step
        evs = self.data["events"]
        if 0 <= row < len(evs) and 0 <= new < len(evs):
            evs[row], evs[new] = evs[new], evs[row]
            self.changed(new)

    def remove_event(self):
        row = self.events.currentRow()
        if row >= 0:
            del self.data["events"][row]
            self.changed(min(row, len(self.data["events"]) - 1))

    def clear_events(self):
        if self.data["events"]:
            self.data["events"] = []
            self.changed()

    def event_menu(self, pos):
        menu = QMenu(self)
        for text, fn in (("Change delay…", self.edit_delay), ("Delete line", self.remove_event),
                         ("Add key after…", self.add_key)):
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.exec(self.events.mapToGlobal(pos))

    def closeEvent(self, e):
        if self.recording:
            self.record_btn.setChecked(False)
        self.maybe_save()
        super().closeEvent(e)


class MacroPicker(QDialog):
    """Choose which saved macro a button plays, and how it repeats."""

    def __init__(self, parent, label, current=None):
        super().__init__(parent)
        self.setWindowTitle(f"Macro for button {label}")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(380)
        current = current or {}

        self.list = QListWidget()
        manage = QPushButton("Open macro editor…")
        manage.clicked.connect(self.open_editor)

        self.mode_buttons = []
        modes = QVBoxLayout()
        for mode, text in dev.MACRO_MODES:
            rb = QRadioButton(text)
            rb.setChecked(current.get("mode", dev.MACRO_REPEAT) == mode)
            modes.addWidget(rb)
            self.mode_buttons.append((mode, rb))
        self.count = QSpinBox()
        self.count.setRange(1, 255)
        self.count.setValue(current.get("count", 1))
        crow = QHBoxLayout()
        crow.addWidget(QLabel("Times:"))
        crow.addWidget(self.count)
        crow.addStretch()

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.ok = box.button(QDialogButtonBox.StandardButton.Ok)

        lay = QVBoxLayout(self)
        title = QLabel(f"Macro for button {label}")
        title.setObjectName("title")
        lay.addWidget(title)
        lay.addWidget(QLabel("Saved macros"))
        lay.addWidget(self.list)
        lay.addWidget(manage)
        lay.addWidget(QLabel("Playback"))
        lay.addLayout(modes)
        lay.addLayout(crow)
        lay.addWidget(box)
        self.reload(current.get("name"))

    def reload(self, select=None):
        self.list.clear()
        names = store.list_macros()
        self.list.addItems(names)
        if select in names:
            self.list.setCurrentRow(names.index(select))
        elif names:
            self.list.setCurrentRow(0)
        self.ok.setEnabled(bool(names))

    def open_editor(self):
        sel = self.list.currentItem().text() if self.list.currentItem() else None
        MacroEditor(self, sel).exec()
        self.reload(sel)

    def result_assignment(self):
        mode = next(m for m, rb in self.mode_buttons if rb.isChecked())
        name = self.list.currentItem().text()
        return {"name": name, "mode": mode, "count": self.count.value() if mode == dev.MACRO_REPEAT else 1,
                "events": store.load_macro(name).get("events", [])}
