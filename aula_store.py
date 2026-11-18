"""Profiles, the macro library and KDE pointer settings for the AULA H510 app.

Profiles and macros live on this computer, like in the official app: the mouse
holds only the settings that were last applied, and it cannot report macros back.
"""

import json
import os
import re
import subprocess

import aula_device as dev

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "aula-h510")
PROFILE_DIR = os.path.join(CONFIG_DIR, "profiles")
MACRO_DIR = os.path.join(CONFIG_DIR, "macros")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")


def _safe(name):
    return re.sub(r"[^\w .()-]", "_", name).strip() or "Untitled"


def _read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _names(folder):
    if not os.path.isdir(folder):
        return []
    return sorted((f[:-5] for f in os.listdir(folder) if f.endswith(".json")), key=str.lower)


def unique_name(existing, base):
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


# ---------- macros ----------
# A macro is {"events": [{"kind": "key"|"button", "code": int, "down": bool, "delay": ms}]}.

def list_macros():
    return _names(MACRO_DIR)


def load_macro(name):
    return _read_json(os.path.join(MACRO_DIR, _safe(name) + ".json"), {"events": []})


def save_macro(name, macro):
    _write_json(os.path.join(MACRO_DIR, _safe(name) + ".json"), macro)


def delete_macro(name):
    try:
        os.remove(os.path.join(MACRO_DIR, _safe(name) + ".json"))
    except OSError:
        pass


def rename_macro(old, new):
    os.replace(os.path.join(MACRO_DIR, _safe(old) + ".json"), os.path.join(MACRO_DIR, _safe(new) + ".json"))


def macro_event_text(ev):
    if ev["kind"] == "button":
        name = dev.MACRO_BUTTONS.get(ev["code"], f"Button 0x{ev['code']:02X}")
    else:
        name = dev.MACRO_KEYS.get(ev["code"], f"Key 0x{ev['code']:02X}")
    return name


def macro_to_device_events(macro):
    """Convert to (command, code, delay) triples the mouse understands."""
    out = []
    for ev in macro.get("events", []):
        if ev["kind"] == "button":
            cmd = dev.MACRO_BUTTON_DOWN if ev["down"] else dev.MACRO_BUTTON_UP
        else:
            cmd = dev.MACRO_KEY_DOWN if ev["down"] else dev.MACRO_KEY_UP
        out.append((cmd, ev["code"], int(ev.get("delay", 10))))
    return out


# ---------- profiles ----------
# A profile is {"config": hex, "buttons": hex, "macros": {slot: {"name", "mode", "count"}},
#               "pointer": float, "scroll": float}.

def list_profiles():
    return _names(PROFILE_DIR)


def load_profile(name):
    return _read_json(os.path.join(PROFILE_DIR, _safe(name) + ".json"), None)


def save_profile(name, profile):
    _write_json(os.path.join(PROFILE_DIR, _safe(name) + ".json"), profile)


def delete_profile(name):
    try:
        os.remove(os.path.join(PROFILE_DIR, _safe(name) + ".json"))
    except OSError:
        pass


def rename_profile(old, new):
    os.replace(os.path.join(PROFILE_DIR, _safe(old) + ".json"), os.path.join(PROFILE_DIR, _safe(new) + ".json"))


def profile_from_settings(settings, macros, pointer, scroll):
    return {
        "config": bytes(settings.config[:dev.CONFIG_SIZE]).hex(),
        "buttons": bytes(settings.buttons[:dev.BUTTON_SIZE]).hex(),
        "macros": {str(k): v for k, v in macros.items()},
        "pointer": pointer,
        "scroll": scroll,
    }


def settings_from_profile(profile, base):
    """Apply a stored profile on top of what the mouse reported (keeps unknown bytes sane)."""
    s = base.copy()
    cfg = bytes.fromhex(profile["config"])
    btn = bytes.fromhex(profile["buttons"])
    s.config[:len(cfg)] = cfg
    s.buttons[:len(btn)] = btn
    s.config[3] = s.buttons[3] = 0
    macros = {int(k): v for k, v in profile.get("macros", {}).items()}
    return s, macros


def current_profile():
    return _read_json(STATE_FILE, {}).get("profile")


def set_current_profile(name):
    state = _read_json(STATE_FILE, {})
    state["profile"] = name
    _write_json(STATE_FILE, state)


# ---------- KDE pointer speed and scroll speed ----------

KWIN = "org.kde.KWin"
KCM_GROUP = ["Libinput", str(dev.VID), str(dev.PID)]


def _busctl(*args):
    return subprocess.run(["busctl", "--user", *args], capture_output=True, text=True, timeout=5)


def _kwin_device():
    """D-Bus path and name of the H510's pointer device in KWin, or (None, None)."""
    try:
        tree = _busctl("tree", "--list", KWIN).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None, None
    for path in tree:
        if not path.startswith("/org/kde/KWin/InputDevice/event"):
            continue
        props = {}
        for prop in ("vendor", "product", "supportsPointerAcceleration", "name"):
            r = _busctl("get-property", KWIN, path, "org.kde.KWin.InputDevice", prop)
            props[prop] = r.stdout.strip().split(" ", 1)[-1] if r.returncode == 0 else ""
        if props["vendor"] == str(dev.VID) and props["product"] == str(dev.PID) \
                and props["supportsPointerAcceleration"] == "true":
            return path, props["name"].strip('"')
    return None, None


class PointerSettings:
    """Cursor speed (-1..1) and scroll factor for this mouse, applied live through KWin
    and saved to kcminputrc so they survive a restart."""

    def __init__(self):
        self.path, self.name = _kwin_device()

    @property
    def available(self):
        return self.path is not None

    def _get(self, prop, default):
        if not self.path:
            return default
        r = _busctl("get-property", KWIN, self.path, "org.kde.KWin.InputDevice", prop)
        try:
            return float(r.stdout.split()[1])
        except (IndexError, ValueError):
            return default

    def _set(self, prop, value, key):
        if not self.path:
            return False
        r = _busctl("set-property", KWIN, self.path, "org.kde.KWin.InputDevice", prop, "d", f"{value:.3f}")
        group = []
        for g in KCM_GROUP + [self.name]:
            group += ["--group", g]
        subprocess.run(["kwriteconfig6", "--file", "kcminputrc", *group, "--key", key, f"{value:.3f}"],
                       capture_output=True, timeout=5)
        return r.returncode == 0

    def pointer(self):
        return self._get("pointerAcceleration", 0.0)

    def set_pointer(self, value):
        return self._set("pointerAcceleration", max(-1.0, min(1.0, value)), "PointerAcceleration")

    def scroll(self):
        return self._get("scrollFactor", 1.0)

    def set_scroll(self, value):
        return self._set("scrollFactor", max(0.1, min(20.0, value)), "ScrollFactor")
