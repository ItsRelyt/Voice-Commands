#!/usr/bin/env python3
"""
Continuous Voice App Launcher
Listens for spoken commands and launches matching applications.

• Known apps (Discord, Zen Browser, Modrinth, …) use smart path discovery.
• Any other app can be opened by name (searches Start Menu, PATH, install folders).
• Say "open <name>" / "launch <name>" for unknown apps to avoid false positives.
"""

from __future__ import annotations

import os
import re
import sys
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional

try:
    import speech_recognition as sr
except ImportError:
    print("Missing dependency: speech_recognition")
    print("Install with:  pip install SpeechRecognition pyaudio")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Terminal styling
# ─────────────────────────────────────────────────────────────────────────────

class Style:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[92m"
    CYAN    = "\033[96m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"
    BLUE    = "\033[94m"


# Enable ANSI colours on modern Windows terminals
if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def c(text: str, *styles: str) -> str:
    return "".join(styles) + text + Style.RESET


def banner() -> None:
    width = 64
    line = "═" * width
    print()
    print(c(line, Style.CYAN, Style.BOLD))
    print(c("  🎙️  CONTINUOUS VOICE APP LAUNCHER", Style.CYAN, Style.BOLD))
    print(c("  Say any app name → it opens automatically", Style.DIM))
    print(c(line, Style.CYAN, Style.BOLD))
    print()


def status(msg: str, kind: str = "info") -> None:
    icons = {
        "info":   (Style.CYAN,    "ℹ️ "),
        "ok":     (Style.GREEN,   "✅"),
        "warn":   (Style.YELLOW,  "⚠️ "),
        "error":  (Style.RED,     "❌"),
        "listen": (Style.MAGENTA, "🎙️ "),
        "launch": (Style.GREEN,   "🚀"),
        "search": (Style.BLUE,    "🔍"),
        "found":  (Style.GREEN,   "📁"),
        "miss":   (Style.YELLOW,  "❓"),
        "exit":   (Style.CYAN,    "👋"),
    }
    color, icon = icons.get(kind, (Style.WHITE, "•"))
    print(c(f"  {icon}  {msg}", color))


def divider() -> None:
    print(c("  " + "─" * 58, Style.DIM))


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────────────

def _user_home() -> Path:
    return Path.home()


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(_user_home() / "AppData" / "Local"))


def _roaming_appdata() -> Path:
    return Path(os.environ.get("APPDATA") or str(_user_home() / "AppData" / "Roaming"))


def _program_files() -> Path:
    return Path(os.environ.get("ProgramFiles") or r"C:\Program Files")


def _program_files_x86() -> Path:
    return Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")


def which(cmd: str) -> Optional[str]:
    """Return full path of an executable if it is on PATH."""
    return shutil.which(cmd) or shutil.which(f"{cmd}.exe")


# ─────────────────────────────────────────────────────────────────────────────
# Known-app finders
# ─────────────────────────────────────────────────────────────────────────────

def find_discord() -> Optional[str]:
    base = _local_appdata() / "Discord"
    update = base / "Update.exe"
    if update.is_file():
        # Official launcher – survives version folder changes
        return f'"{update}" --processStart Discord.exe'
    if base.is_dir():
        for child in sorted(base.iterdir(), reverse=True):
            if child.is_dir() and child.name.startswith("app-"):
                exe = child / "Discord.exe"
                if exe.is_file():
                    return str(exe)
    return None


def find_zen_browser() -> Optional[str]:
    candidates = [
        _program_files() / "Zen Browser" / "zen.exe",
        _program_files_x86() / "Zen Browser" / "zen.exe",
        _program_files() / "Zen" / "Zen" / "Zen.exe",
        _local_appdata() / "Zen Browser" / "zen.exe",
        _local_appdata() / "Programs" / "Zen Browser" / "zen.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return which("zen") or which("zen.exe")


def find_any_browser() -> tuple[Optional[str], str]:
    """
    Prefer Zen Browser. Fall back to other browsers.
    Returns (path, display_name).
    """
    zen = find_zen_browser()
    if zen:
        return zen, "Zen Browser"

    fallbacks: list[tuple[Path, str]] = [
        (_program_files() / "Google" / "Chrome" / "Application" / "chrome.exe", "Google Chrome"),
        (_program_files_x86() / "Google" / "Chrome" / "Application" / "chrome.exe", "Google Chrome"),
        (_local_appdata() / "Google" / "Chrome" / "Application" / "chrome.exe", "Google Chrome"),
        (_program_files() / "Microsoft" / "Edge" / "Application" / "msedge.exe", "Microsoft Edge"),
        (_program_files_x86() / "Microsoft" / "Edge" / "Application" / "msedge.exe", "Microsoft Edge"),
        (_program_files() / "Mozilla Firefox" / "firefox.exe", "Firefox"),
        (_program_files_x86() / "Mozilla Firefox" / "firefox.exe", "Firefox"),
        (_program_files() / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe", "Brave"),
        (_local_appdata() / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe", "Brave"),
    ]
    for path, name in fallbacks:
        if path.is_file():
            return str(path), name

    for exe_name, label in (
        ("chrome", "Google Chrome"),
        ("msedge", "Microsoft Edge"),
        ("firefox", "Firefox"),
        ("brave", "Brave"),
        ("opera", "Opera"),
    ):
        found = which(exe_name)
        if found:
            return found, label
    return None, "Browser"


def find_modrinth() -> Optional[str]:
    candidates = [
        _roaming_appdata() / "Modrinth App" / "Modrinth App.exe",
        _local_appdata() / "Modrinth App" / "Modrinth App.exe",
        _roaming_appdata() / "ModrinthApp" / "Modrinth App.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


# Registry: (display_name, keywords as whole words, finder)
# Finder may return str | None  OR  (str|None, display_name) for browsers
APP_REGISTRY = [
    (
        "Discord",
        ("discord",),
        find_discord,
    ),
    (
        "Zen Browser",
        ("browser", "zen", "internet"),
        find_any_browser,
    ),
    (
        "Modrinth",
        ("modrinth", "minecraft"),
        find_modrinth,
    ),
    (
        "Notepad",
        ("notepad",),
        lambda: which("notepad"),
    ),
    (
        "Calculator",
        ("calculator", "calc"),
        lambda: which("calc"),
    ),
]

# Voice exit phrases
EXIT_PHRASES = ("exit", "quit", "stop listening", "goodbye", "shut down")


def resolve_known_apps() -> dict[str, dict]:
    results: dict[str, dict] = {}
    for name, keywords, finder in APP_REGISTRY:
        path = None
        display = name
        try:
            result = finder()
            if isinstance(result, tuple):
                path, display = result
            else:
                path = result
        except Exception:
            pass
        results[name] = {
            "keywords": keywords,
            "path": path,
            "found": bool(path),
            "display": display if path else name,
        }
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Word-boundary matching (fixes substring false positives)
# ─────────────────────────────────────────────────────────────────────────────

def words_in(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def keyword_match(text: str, keywords: tuple[str, ...]) -> bool:
    """True only when a full keyword appears as a whole word (or multi-word phrase)."""
    text_l = text.lower()
    text_words = words_in(text_l)
    for kw in keywords:
        if " " in kw:
            if kw in text_l:
                return True
        else:
            if kw in text_words:
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Generic "open any app by name" engine
# ─────────────────────────────────────────────────────────────────────────────

COMMAND_WORDS = {
    "open", "launch", "start", "run", "execute", "please", "the", "app",
    "application", "program", "for", "me", "can", "you", "could", "would",
    "i", "want", "to", "a", "an",
}

# Require one of these verbs before trying a generic (unknown) app.
# Known apps still work with just the name.
OPEN_VERBS = {"open", "launch", "start", "run", "execute"}

SEARCH_ROOTS = [
    _program_files(),
    _program_files_x86(),
    _local_appdata() / "Programs",
    _user_home() / "AppData" / "Local" / "Programs",
]

MAX_SEARCH_DEPTH = 3

# Cache Start Menu shortcuts so we only scan once
_start_menu_cache: list[Path] | None = None


def extract_app_name(transcript: str) -> str:
    words = re.findall(r"[a-z0-9]+", transcript.lower())
    filtered = [w for w in words if w not in COMMAND_WORDS]
    return " ".join(filtered).strip()


def has_open_verb(transcript: str) -> bool:
    return bool(words_in(transcript) & OPEN_VERBS)


def find_in_path(name: str) -> Optional[str]:
    for candidate in (name, name.replace(" ", ""), name.replace(" ", "") + ".exe"):
        found = which(candidate)
        if found:
            return found
    return None


def _load_start_menu_shortcuts() -> list[Path]:
    global _start_menu_cache
    if _start_menu_cache is not None:
        return _start_menu_cache

    roots = [
        _roaming_appdata() / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("ProgramData") or r"C:\ProgramData")
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    links: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            links.extend(root.rglob("*.lnk"))
        except (PermissionError, OSError):
            continue
    _start_menu_cache = links
    return links


def find_in_start_menu(name: str) -> Optional[str]:
    name_lower = name.lower()
    name_compact = name_lower.replace(" ", "")
    best: Optional[Path] = None
    best_score = 0

    for lnk in _load_start_menu_shortcuts():
        stem = lnk.stem.lower()
        stem_compact = stem.replace(" ", "")

        if stem == name_lower or stem_compact == name_compact:
            return str(lnk)
        score = 0
        if name_lower in stem or stem in name_lower:
            score = 70
        elif name_compact in stem_compact or stem_compact in name_compact:
            score = 50
        if score > best_score:
            best_score = score
            best = lnk

    return str(best) if best and best_score >= 50 else None


def find_exe_by_walking(name: str) -> Optional[str]:
    name_lower = name.lower().replace(" ", "")
    if len(name_lower) < 3:
        return None  # too short – avoid random matches

    candidates: list[tuple[int, Path]] = []

    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                try:
                    rel = Path(dirpath).relative_to(root)
                except ValueError:
                    dirnames.clear()
                    continue
                if len(rel.parts) > MAX_SEARCH_DEPTH:
                    dirnames.clear()
                    continue

                for fname in filenames:
                    low = fname.lower()
                    if not low.endswith(".exe"):
                        continue
                    # Skip obvious helpers / uninstallers
                    if any(skip in low for skip in (
                        "uninstall", "update", "setup", "installer",
                        "helper", "crash", "report", "cef", "chrome_elf",
                    )):
                        continue

                    stem = Path(fname).stem.lower().replace(" ", "")
                    full = Path(dirpath) / fname

                    score = 0
                    if stem == name_lower:
                        score = 100
                    elif name_lower in stem and len(name_lower) >= 4:
                        score = 60
                    elif stem in name_lower and len(stem) >= 4:
                        score = 50

                    if score > 0:
                        candidates.append((score, full))
        except (PermissionError, OSError):
            continue

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], len(str(x[1]))))
    return str(candidates[0][1])


def launch_via_windows_start(name: str) -> bool:
    """
    Hand the name to Windows `start`. Returns True only if the process
    appears to have been accepted (best-effort – start is asynchronous).
    """
    try:
        # Use CREATE_NO_WINDOW so a console doesn't flash
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.run(
            f'start "" "{name}"',
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=creationflags,
        )
        # `start` usually returns 0 even on failure, so treat non-zero as hard fail
        # and zero as "accepted" (best effort).
        return proc.returncode == 0
    except Exception:
        return False


def launch_path(path: str) -> bool:
    """Launch a concrete path or command string. Returns True on success."""
    try:
        # Discord-style command with arguments
        if " --" in path:
            subprocess.Popen(path, shell=True)
            return True

        p = Path(path)
        if not p.exists() and not path.lower().endswith((".exe", ".lnk", ".bat", ".cmd")):
            # Might be a bare name that shell can resolve
            subprocess.Popen(path, shell=True)
            return True

        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
            return True

        subprocess.Popen([str(p)])
        return True
    except Exception as exc:
        status(f"Launch error: {exc}", "error")
        return False


def open_any_app(spoken_name: str) -> bool:
    clean = extract_app_name(spoken_name)
    if not clean:
        status("Could not extract an app name from what you said.", "miss")
        return False

    if len(clean) < 2:
        status(f'Name too short: "{clean}"', "miss")
        return False

    status(f'Searching for "{clean}"…', "search")

    # 1. PATH
    path = find_in_path(clean)
    if path:
        status(f"Found on PATH → {path}", "found")
        return launch_path(path)

    # 2. Start Menu shortcuts
    path = find_in_start_menu(clean)
    if path:
        status(f"Found Start Menu shortcut → {Path(path).name}", "found")
        return launch_path(path)

    # 3. Walk common install folders
    path = find_exe_by_walking(clean)
    if path:
        status(f"Found executable → {path}", "found")
        return launch_path(path)

    # 4. Windows start (last resort)
    status(f'Trying Windows start "{clean}"…', "search")
    if launch_via_windows_start(clean):
        # Give a honest message – start is fire-and-forget
        status(f'Handed "{clean}" to Windows. Check if it opened.', "ok")
        return True

    status(f'Could not find or launch "{clean}".', "error")
    status("Try the exact name as it appears in the Start Menu.", "warn")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Debounce – prevent double-launches from repeated recognition
# ─────────────────────────────────────────────────────────────────────────────

_last_launch: dict[str, float] = {}
DEBOUNCE_SECONDS = 4.0


def recently_launched(key: str) -> bool:
    now = time.time()
    prev = _last_launch.get(key, 0)
    if now - prev < DEBOUNCE_SECONDS:
        return True
    _last_launch[key] = now
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Command processing
# ─────────────────────────────────────────────────────────────────────────────

def process_command(transcript: str, known_apps: dict[str, dict]) -> bool:
    """
    Process one transcript. Returns False if the user asked to exit.
    """
    text = transcript.lower().strip()
    if not text:
        return True

    # Voice exit
    for phrase in EXIT_PHRASES:
        if phrase in text:
            status("Exit command received.", "exit")
            return False

    # 1. Known apps (whole-word match, no verb required)
    for name, info in known_apps.items():
        if keyword_match(text, info["keywords"]):
            display = info.get("display", name)
            if not info["path"]:
                status(f'"{display}" is known but its path could not be resolved.', "error")
                return True
            if recently_launched(display):
                status(f"{display} was just launched – ignoring repeat.", "warn")
                return True
            status(f"Launching {display}…", "launch")
            if launch_path(info["path"]):
                status(f"{display} started.", "ok")
            else:
                status(f"Failed to start {display}.", "error")
            return True

    # 2. Generic apps – require an open verb to reduce false positives
    #    from ambient conversation ("I was talking about steam…" etc.)
    if not has_open_verb(text):
        status(
            'Heard something, but no known app matched. '
            'Say "open <app name>" for other programs.',
            "miss",
        )
        return True

    clean = extract_app_name(text)
    if recently_launched(clean):
        status(f'"{clean}" was just launched – ignoring repeat.', "warn")
        return True

    open_any_app(text)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Listening loop
# ─────────────────────────────────────────────────────────────────────────────

def listen_continuously(known_apps: dict[str, dict]) -> None:
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.energy_threshold = 300          # starting point; adjust_for_ambient overwrites
    recognizer.pause_threshold = 0.8
    recognizer.non_speaking_duration = 0.4
    recognizer.phrase_threshold = 0.3

    mic = sr.Microphone()

    with mic as source:
        status("Calibrating microphone… stay quiet for ~2 seconds", "listen")
        recognizer.adjust_for_ambient_noise(source, duration=2)
        # Floor so very quiet rooms don't become hypersensitive
        if recognizer.energy_threshold < 150:
            recognizer.energy_threshold = 150
        status(f"Energy threshold = {recognizer.energy_threshold:.0f}", "ok")
        print()
        status("Listening. Speak a command any time.", "listen")
        status('Say "exit" or press Ctrl+C to quit.', "info")
        divider()

        while True:
            try:
                audio = recognizer.listen(
                    source,
                    timeout=None,
                    phrase_time_limit=7,
                )
            except Exception as exc:
                status(f"Microphone error: {exc}", "error")
                time.sleep(1)
                continue

            try:
                transcript = recognizer.recognize_google(audio).lower()
            except sr.UnknownValueError:
                continue
            except sr.RequestError as exc:
                status(f"Speech service error: {exc}", "error")
                status("Check your internet connection.", "warn")
                time.sleep(2)
                continue
            except Exception as exc:
                status(f"Recognition error: {exc}", "error")
                continue

            print()
            print(c(f"  📝  \"{transcript}\"", Style.WHITE, Style.BOLD))
            keep_going = process_command(transcript, known_apps)
            divider()
            if not keep_going:
                break


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    if os.name != "nt":
        status("This launcher is designed for Windows.", "warn")
        print()

    banner()

    status("Resolving known applications…", "search")
    known = resolve_known_apps()

    print()
    found = 0
    for name, info in known.items():
        display = info.get("display", name)
        if info["found"]:
            found += 1
            path_str = info["path"] or ""
            if len(path_str) > 50:
                path_str = "…" + path_str[-47:]
            # Show real browser name when fallback was used
            label = display if display != name else name
            status(f"{label:<18} → {path_str}", "found")
        else:
            status(f"{name:<18} → not found (generic search still works)", "miss")

    print()
    status(f"{found}/{len(known)} known apps resolved with direct paths", "ok")
    print()

    print(c("  How to use:", Style.DIM))
    print(c("    • Known apps (just the name):", Style.DIM))
    print(c("        \"discord\"  \"browser\" / \"zen\"  \"modrinth\"  \"calculator\"", Style.DIM))
    print(c("    • Any other app (say open/launch):", Style.DIM))
    print(c("        \"open spotify\"  \"launch steam\"  \"start visual studio code\"", Style.DIM))
    print(c("    • Exit:  \"exit\"  \"quit\"  \"stop listening\"", Style.DIM))
    print()

    # Warm the Start Menu cache in the background so first generic open is fast
    try:
        _load_start_menu_shortcuts()
        status(f"Cached {len(_start_menu_cache or [])} Start Menu shortcuts", "ok")
    except Exception:
        pass
    print()

    try:
        listen_continuously(known)
    except KeyboardInterrupt:
        pass

    print()
    status("Exiting Voice Launcher. Goodbye!", "exit")
    print()


if __name__ == "__main__":
    main()