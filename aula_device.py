"""Talks to the AULA H510 (SinoWealth 258a:0029) over hidraw.

Protocol notes, checked against the official AULA app running under Wine and
libratbag's SinoWealth driver:

* Everything goes through the vendor interface (interface 1), which carries
  feature report 0x05 (6-byte commands) and 0x04 (520-byte config blocks).
* Reading a block: SET_FEATURE [05 cmd 00 00 00 00], then GET_FEATURE 0x04.
  0x11 = settings (131 bytes), 0x12 = button map (88 bytes).
* Writing a block: send the block back as read, with byte 3 set to
  (block size - 8). Unknown bytes are always preserved.
* DPI values are 1-based indexes into the official DPI table (Cfg.ini DPISET;
  the app's DPIHW default is index + 1).
"""

import fcntl
import os

VID, PID = 0x258A, 0x0029
REPORT_LEN = 520
CONFIG_SIZE = 131
BUTTON_SIZE = 88

CMD_FIRMWARE = 0x01
CMD_PROFILE = 0x02
CMD_GET_CONFIG = 0x11
CMD_GET_BUTTONS = 0x12
CMD_DEBOUNCE = 0x1A
CMD_MACRO = 0x30

# Macro events are 3 bytes, as the official app writes them (OemDrv 0x414ae0):
# [command | delay >> 8, delay & 0xFF, code], delay in ms after the event (12 bits).
MACRO_BUTTON_DOWN, MACRO_BUTTON_UP = 0x10, 0x90
MACRO_KEY_DOWN, MACRO_KEY_UP = 0x50, 0xD0
MACRO_MAX_EVENTS = 166
MACRO_MAX_DELAY = 4095
MACRO_SLOTS = 10  # the official app never uses more than 10 macro slots
# Button-entry macro modes (byte 2 of a 0x70 entry); byte 3 is the repeat count for REPEAT.
MACRO_REPEAT, MACRO_UNTIL_PRESSED, MACRO_UNTIL_RELEASED = 0x1, 0x2, 0x4
MACRO_MODES = [
    (MACRO_REPEAT, "Repeat a set number of times"),
    (MACRO_UNTIL_RELEASED, "Repeat until the button is released"),
    (MACRO_UNTIL_PRESSED, "Repeat until the button is pressed again"),
]

DPI_TABLE = [
    200, 250, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500,
    1600, 1700, 1800, 1900, 2000, 2100, 2200, 2300, 2400, 2500, 2600, 2700, 2800,
    2900, 3000, 3100, 3200, 3300, 3400, 3500, 3600, 3700, 3800, 3900, 4000, 4100,
    4200, 4300, 4400, 4500, 4600, 4700, 4800, 4900, 5000, 5100, 5200, 5300, 5400,
    5500, 5600, 5700, 5800, 5900, 6000, 6100, 6200, 6500, 7000, 7500, 8000, 8500,
    9000, 10000, 10500, 11000, 11500, 12000, 12400,
]
POLLING_RATES = {1: 125, 2: 250, 3: 500, 4: 1000}
DEBOUNCE_TIMES = [4, 6, 8, 10, 12, 14, 16]
DPI_STAGES = 6

# Byte offsets inside the 131-byte settings block (report ID included).
OFF_RATE = 10
OFF_DPI_COUNT = 11
OFF_DPI_DISABLED = 12
OFF_DPIS = 13
OFF_DPI_COLORS = 29
OFF_EFFECT = 53

# Lighting effects: (id, name, mode byte offset, colour offset, colour count, has speed)
EFFECTS = [
    (0x00, "Off", None, None, 0, False),
    (0x01, "Spectrum", 54, None, 0, True),
    (0x02, "Static colour", 56, 57, 1, False),
    (0x0A, "Breathing (one colour)", 125, 126, 1, True),
    (0x03, "Breathing (seven colours)", 60, 62, 7, True),
    (0x05, "Breathing (RGB)", 84, None, 0, True),
    (0x04, "Tail", 83, None, 0, True),
    (0x07, "Rave", 116, 117, 2, True),
    (0x08, "Random", 123, None, 0, True),
    (0x09, "Wave", 124, None, 0, True),
]
EFFECT_BY_ID = {e[0]: e for e in EFFECTS}

# Button slots in the order the official app lists them.
BUTTON_LABELS = ["1", "2", "3", "4", "5", "6", "7", "8", "S1", "S2", "S3", "S4", "S5", "S6"]

T_BUTTON, T_WHEEL, T_KEY, T_MEDIA, T_REPEAT = 0x11, 0x12, 0x21, 0x22, 0x31
T_DPI, T_DPI_LOCK, T_SPECIAL, T_MACRO = 0x41, 0x42, 0x50, 0x70

# Simple actions offered in the button menu: name -> 4 raw bytes.
SIMPLE_ACTIONS = [
    ("Left click", bytes([T_BUTTON, 0x01, 0, 0])),
    ("Right click", bytes([T_BUTTON, 0x02, 0, 0])),
    ("Middle click", bytes([T_BUTTON, 0x04, 0, 0])),
    ("Back", bytes([T_BUTTON, 0x08, 0, 0])),
    ("Forward", bytes([T_BUTTON, 0x10, 0, 0])),
    ("Scroll up", bytes([T_WHEEL, 0x01, 0, 0])),
    ("Scroll down", bytes([T_WHEEL, 0xFF, 0, 0])),
    ("DPI+", bytes([T_DPI, 0x01, 0, 0])),
    ("DPI-", bytes([T_DPI, 0x02, 0, 0])),
    ("DPI cycle", bytes([T_DPI, 0x00, 0, 0])),
    ("Disabled", bytes([T_SPECIAL, 0x01, 0, 0])),
]
MEDIA_ACTIONS = [
    ("Play / Pause", bytes([T_MEDIA, 0x08, 0, 0])),
    ("Next track", bytes([T_MEDIA, 0x01, 0, 0])),
    ("Previous track", bytes([T_MEDIA, 0x02, 0, 0])),
    ("Stop", bytes([T_MEDIA, 0x04, 0, 0])),
    ("Mute", bytes([T_MEDIA, 0x10, 0, 0])),
    ("Volume up", bytes([T_MEDIA, 0x40, 0, 0])),
    ("Volume down", bytes([T_MEDIA, 0x80, 0, 0])),
    ("Calculator", bytes([T_MEDIA, 0, 0x20, 0])),
    ("Mail", bytes([T_MEDIA, 0, 0x10, 0])),
    ("Home page", bytes([T_MEDIA, 0, 0, 0x02])),
]
MOD_NAMES = [(0x01, "Ctrl"), (0x02, "Shift"), (0x04, "Alt"), (0x08, "Win")]

# HID keyboard usage -> name (enough for display and the key picker).
HID_KEYS = {}
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    HID_KEYS[0x04 + i] = c
for i, c in enumerate("1234567890"):
    HID_KEYS[0x1E + i] = c
HID_KEYS.update({
    0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab", 0x2C: "Space",
    0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\", 0x33: ";", 0x34: "'",
    0x35: "`", 0x36: ",", 0x37: ".", 0x38: "/", 0x39: "Caps Lock",
    0x46: "Print Screen", 0x47: "Scroll Lock", 0x48: "Pause", 0x49: "Insert",
    0x4A: "Home", 0x4B: "Page Up", 0x4C: "Delete", 0x4D: "End", 0x4E: "Page Down",
    0x4F: "Right", 0x50: "Left", 0x51: "Down", 0x52: "Up",
})
for i in range(12):
    HID_KEYS[0x3A + i] = f"F{i + 1}"
for i, c in enumerate("/*-+"):
    HID_KEYS[0x54 + i] = "Num " + c
HID_KEYS[0x58] = "Num Enter"
for i, c in enumerate("1234567890"):
    HID_KEYS[0x59 + i] = "Num " + c
HID_KEYS[0x63] = "Num ."
HID_KEYS[0x65] = "Menu"
# Modifiers only appear inside macros; button shortcuts use the modifier bits instead.
MACRO_KEYS = dict(HID_KEYS)
MACRO_KEYS.update({0xE0: "Left Ctrl", 0xE1: "Left Shift", 0xE2: "Left Alt", 0xE3: "Left Win",
                   0xE4: "Right Ctrl", 0xE5: "Right Shift", 0xE6: "Right Alt", 0xE7: "Right Win"})
MACRO_BUTTONS = {0x01: "Left button", 0x02: "Right button", 0x04: "Middle button",
                 0x08: "Back button", 0x10: "Forward button"}


def describe_button(raw):
    """Human-readable name for one 4-byte button entry."""
    for name, code in SIMPLE_ACTIONS + MEDIA_ACTIONS:
        if raw == code:
            return name
    t = raw[0]
    if t == T_KEY:
        parts = [n for bit, n in MOD_NAMES if raw[1] & bit]
        if raw[2]:
            parts.append(HID_KEYS.get(raw[2], f"Key 0x{raw[2]:02X}"))
        return " + ".join(parts) or "Key (none)"
    if t == T_MACRO:
        return f"Macro {raw[1]}"
    if t == T_DPI_LOCK:
        dpi = DPI_TABLE[raw[1] - 1] if 1 <= raw[1] <= len(DPI_TABLE) else raw[1]
        return f"DPI lock - {dpi}"
    if t == T_REPEAT:
        return "Fire key (rapid click)"
    if t == T_BUTTON:
        return f"Mouse buttons 0x{raw[1]:02X}"
    return "Unknown (" + raw.hex(" ") + ")"


def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("H") << 8) | nr


def find_hidraw():
    """Return the /dev/hidraw node of the H510's vendor interface, or None."""
    base = "/sys/class/hidraw"
    if not os.path.isdir(base):
        return None
    for name in sorted(os.listdir(base)):
        try:
            with open(os.path.join(base, name, "device", "uevent")) as f:
                uevent = f.read()
            with open(os.path.join(base, name, "device", "report_descriptor"), "rb") as f:
                desc = f.read()
        except OSError:
            continue
        if f"{VID:08X}:{PID:08X}" not in uevent.upper():
            continue
        # The vendor interface declares feature report 4 under usage page 0xFF00.
        if b"\x06\x00\xff" in desc and b"\x85\x04" in desc:
            return "/dev/" + name
    return None


class MouseError(Exception):
    pass


class AulaH510:
    def __init__(self, path=None):
        self.path = path or find_hidraw()
        if not self.path:
            raise MouseError("AULA H510 not found. Is it plugged in?")
        try:
            self.fd = os.open(self.path, os.O_RDWR)
        except PermissionError:
            raise MouseError(f"No permission to open {self.path}. Is the udev rule installed?")

    def close(self):
        os.close(self.fd)

    def _set(self, data):
        fcntl.ioctl(self.fd, _ioc(3, 0x06, len(data)), bytes(data))

    def _get(self, report_id, size):
        buf = bytearray(size)
        buf[0] = report_id
        fcntl.ioctl(self.fd, _ioc(3, 0x07, size), buf, True)
        return buf

    def _query(self, cmd, arg=0):
        self._set([0x05, cmd, arg, 0, 0, 0])
        return self._get(0x05, 6)

    def firmware(self):
        return bytes(self._query(CMD_FIRMWARE)[2:6]).decode("ascii", "replace")

    def read_block(self, cmd, size):
        self._set([0x05, cmd, 0, 0, 0, 0])
        buf = self._get(0x04, REPORT_LEN)
        if buf[1] != cmd:
            raise MouseError(f"Unexpected reply 0x{buf[1]:02X} to block 0x{cmd:02X}")
        return buf

    def write_block(self, block, size):
        out = bytearray(block)
        out[0] = 0x04
        out[3] = size - 8
        self._set(out)

    def write_macro(self, index, events):
        """events: list of (command, code, delay_ms). Delay is the pause after the event."""
        out = bytearray(REPORT_LEN)
        out[0], out[1], out[2] = 0x04, CMD_MACRO, 0x02
        out[8] = index
        events = events[:MACRO_MAX_EVENTS]
        out[9], out[10] = len(events) >> 8, len(events) & 0xFF
        for n, (command, code, delay) in enumerate(events):
            delay = max(1, min(MACRO_MAX_DELAY, delay))
            o = 11 + 3 * n
            out[o:o + 3] = bytes([(command & 0xF0) | (delay >> 8), delay & 0xFF, code])
        self._set(out)

    def debounce(self):
        return self._query(CMD_DEBOUNCE)[2] * 2

    def set_debounce(self, ms):
        self._set([0x05, CMD_DEBOUNCE, ms // 2, 0, 0, 0])


class Settings:
    """Editable view of the settings + button blocks. Unknown bytes are kept."""

    def __init__(self, config, buttons, debounce):
        self.config = bytearray(config)
        self.buttons = bytearray(buttons)
        self.debounce = debounce

    @classmethod
    def load(cls, dev):
        return cls(dev.read_block(CMD_GET_CONFIG, CONFIG_SIZE),
                   dev.read_block(CMD_GET_BUTTONS, BUTTON_SIZE),
                   dev.debounce())

    def save(self, dev, original):
        if self.config[:CONFIG_SIZE] != original.config[:CONFIG_SIZE]:
            dev.write_block(self.config, CONFIG_SIZE)
        if self.buttons[:BUTTON_SIZE] != original.buttons[:BUTTON_SIZE]:
            dev.write_block(self.buttons, BUTTON_SIZE)
        if self.debounce != original.debounce:
            dev.set_debounce(self.debounce)

    def copy(self):
        return Settings(self.config, self.buttons, self.debounce)

    # Polling rate
    @property
    def polling_rate(self):
        return POLLING_RATES.get(self.config[OFF_RATE] & 0x0F, 1000)

    @polling_rate.setter
    def polling_rate(self, hz):
        code = {v: k for k, v in POLLING_RATES.items()}[hz]
        self.config[OFF_RATE] = (self.config[OFF_RATE] & 0xF0) | code

    # DPI stages
    def stage_enabled(self, i):
        return not (self.config[OFF_DPI_DISABLED] >> i) & 1

    def stage_dpi(self, i):
        raw = self.config[OFF_DPIS + i]
        return DPI_TABLE[min(max(raw, 1), len(DPI_TABLE)) - 1]

    def set_stage_dpi(self, i, dpi):
        idx = min(range(len(DPI_TABLE)), key=lambda k: abs(DPI_TABLE[k] - dpi))
        self.config[OFF_DPIS + i] = idx + 1

    def stage_color(self, i):
        o = OFF_DPI_COLORS + 3 * i
        return tuple(self.config[o:o + 3])

    def set_stage_color(self, i, rgb):
        o = OFF_DPI_COLORS + 3 * i
        self.config[o:o + 3] = bytes(rgb)

    def active_stage(self):
        """Index (0-based slot) of the active DPI stage."""
        nth = self.config[OFF_DPI_COUNT] >> 4
        enabled = [i for i in range(8) if self.stage_enabled(i)]
        return enabled[nth - 1] if 1 <= nth <= len(enabled) else (enabled[0] if enabled else 0)

    def set_stages_enabled(self, flags, active_slot):
        """flags: list of DPI_STAGES bools. At least one must be on."""
        active = self.active_stage() if active_slot is None else active_slot
        mask = 0xFF
        for i, on in enumerate(flags):
            if on:
                mask &= ~(1 << i)
        enabled = [i for i in range(8) if not (mask >> i) & 1]
        if active not in enabled:
            active = enabled[0]
        self.config[OFF_DPI_DISABLED] = mask
        self.config[OFF_DPI_COUNT] = ((enabled.index(active) + 1) << 4) | len(enabled)

    # Lighting
    @property
    def effect(self):
        return self.config[OFF_EFFECT]

    @effect.setter
    def effect(self, value):
        self.config[OFF_EFFECT] = value

    def _effect_info(self):
        return EFFECT_BY_ID.get(self.effect)

    def effect_brightness(self):
        info = self._effect_info()
        return (self.config[info[2]] >> 4) if info and info[2] else 0

    def effect_speed(self):
        info = self._effect_info()
        return (self.config[info[2]] & 0x0F) if info and info[2] else 0

    def set_effect_mode(self, brightness, speed):
        info = self._effect_info()
        if info and info[2]:
            self.config[info[2]] = ((brightness & 0x0F) << 4) | (speed & 0x0F)

    def effect_color(self):
        info = self._effect_info()
        if not info or info[3] is None:
            return None
        return tuple(self.config[info[3]:info[3] + 3])

    def set_effect_color(self, rgb):
        info = self._effect_info()
        if info and info[3] is not None:
            self.config[info[3]:info[3] + 3] = bytes(rgb)
            if self.effect == 0x03:  # seven-colour breathing: use just this colour
                self.config[61] = 1

    # Buttons
    def button(self, slot):
        o = 8 + 4 * slot
        return bytes(self.buttons[o:o + 4])

    def set_button(self, slot, raw):
        o = 8 + 4 * slot
        self.buttons[o:o + 4] = raw
