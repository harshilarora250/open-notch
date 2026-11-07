#!/usr/bin/env python3
"""
notch.py - a voice-following teleprompter for macOS, modelled on Notch (trynotch.net).

* A small borderless window floats at the top-centre of your screen, right by the
  camera, above Zoom / Meet / Teams.
* Your microphone is transcribed ON-DEVICE by listen.swift (Apple Speech framework),
  and the script scrolls and darkens words as you say them.
* The window is hidden from screen sharing / screen recording (needs pyobjc, see below).

Setup (once):
    xcode-select --install                       # gives you swiftc
    python3 -m pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz

Run:
    python3 notch.py                  # built-in sample script
    python3 notch.py my_script.txt    # your own script
    python3 notch.py -c               # script from the clipboard
    python3 notch.py my_script.txt --lang de-DE

Keys (click the window once so it has focus):
    Space   pause / resume voice following
    Up/Down jump back / forward a few words (manual control)
    R       restart from the top
    + / -   bigger / smaller text
    Q/Esc   quit
"""

import argparse
import difflib
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

HERE = Path(__file__).resolve().parent
SWIFT_SRC = HERE / "listen.swift"
BUILD_DIR = HERE / ".build"
LISTEN_BIN = BUILD_DIR / "listen"

SAMPLE_SCRIPT = (
    "Let's start with our Q2 results. Revenue is up fourteen percent, and activation "
    "held at sixty-eight. Churn is down to three point one.\n"
    "Here's what changed this quarter. Onboarding is now one call, not three. "
    "We're still two points below our activation target, so this quarter we're "
    "focusing on onboarding, so new teams see value sooner.\n"
    "Next, the pilot plan for July. Thank you, and let's open it up for questions."
)

# An Info.plist embedded in the helper binary. macOS requires these usage strings
# or the Speech / Microphone permission prompts will crash the process.
INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>net.local.notch.listen</string>
<key>CFBundleName</key><string>listen</string>
<key>NSMicrophoneUsageDescription</key><string>Notch follows your voice to scroll your script.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Notch transcribes your speech on this Mac to follow your script.</string>
</dict></plist>
"""


# --------------------------------------------------------------------------- build
def build_listener() -> Path:
    if sys.platform != "darwin":
        sys.exit("This script is built for macOS only.")
    if not SWIFT_SRC.exists():
        sys.exit(f"Missing {SWIFT_SRC}. Keep listen.swift in the same folder as notch.py.")
    if LISTEN_BIN.exists() and LISTEN_BIN.stat().st_mtime >= SWIFT_SRC.stat().st_mtime:
        return LISTEN_BIN
    if not shutil.which("swiftc"):
        sys.exit("swiftc not found. Install the Xcode command line tools: xcode-select --install")

    print("Compiling listen.swift (first run only)...")
    BUILD_DIR.mkdir(exist_ok=True)
    plist = BUILD_DIR / "Info.plist"
    plist.write_text(INFO_PLIST)
    cmd = [
        "swiftc", "-O", str(SWIFT_SRC), "-o", str(LISTEN_BIN),
        "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT",
        "-Xlinker", "__info_plist", "-Xlinker", str(plist),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("Swift compile failed:\n" + result.stderr)
    return LISTEN_BIN


# --------------------------------------------------------------------------- voice
class Voice:
    """Runs the Swift helper and forwards its JSON lines to a queue."""

    def __init__(self, binary: Path, lang: str, out: "queue.Queue[dict]"):
        self.out = out
        self.proc = subprocess.Popen(
            [str(binary), lang], stdout=subprocess.PIPE, text=True, bufsize=1
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.out.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        self.out.put({"event": "ended"})

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()


# --------------------------------------------------------------------------- matching
def norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def similar(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) > 3 and len(b) > 3:
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
    return False


class Follower:
    """Tracks where the speaker is in the script."""

    LOOKAHEAD = 8

    def __init__(self, words):
        self.keys = [norm(w) for w in words]
        self.n = len(words)
        self.pos = 0            # index of the next word to be spoken
        self.recent = []        # last few spoken words (normalised)
        self.misses = 0
        self._skip_empty()

    def _skip_empty(self):
        while self.pos < self.n and not self.keys[self.pos]:
            self.pos += 1

    def feed(self, spoken_words):
        for raw in spoken_words:
            s = norm(raw)
            if not s:
                continue
            self.recent = (self.recent + [s])[-3:]
            matched = False
            for j in range(self.pos, min(self.n, self.pos + self.LOOKAHEAD)):
                if not self.keys[j]:
                    continue
                # Skipping ahead is only trusted for longer, more distinctive words.
                if j - self.pos > 2 and len(s) < 4:
                    continue
                if similar(s, self.keys[j]):
                    self.pos = j + 1
                    matched = True
                    break
            if matched:
                self.misses = 0
            else:
                self.misses += 1
                if self.misses >= 4:
                    self._resync()
            self._skip_empty()
        return self.pos

    def _resync(self):
        """Lost track: look for the last three spoken words nearby and jump there."""
        r = self.recent
        if len(r) < 3:
            return
        lo, hi = max(0, self.pos - 15), min(self.n - 2, self.pos + 80)
        for j in range(lo, hi):
            if all(similar(r[k], self.keys[j + k]) for k in range(3) if j + k < self.n):
                self.pos = min(self.n, j + 3)
                self.misses = 0
                return

    def move(self, delta):
        self.pos = max(0, min(self.n, self.pos + delta))
        self._skip_empty()
        self.recent, self.misses = [], 0

    def reset(self):
        self.pos, self.recent, self.misses = 0, [], 0
        self._skip_empty()


# --------------------------------------------------------------------------- UI
class NotchApp:
    BG = "#000000"
    TODO = "#FFFFFF"
    DONE = "#6B6B6B"
    CURRENT = "#5AB8F7"   # Notch's accent blue

    def __init__(self, script_text, voice, events, args):
        self.voice, self.events = voice, events
        self.paused = False
        self.seen = 0

        self.root = tk.Tk()
        self.root.title("Notch")
        self.root.configure(bg=self.BG)
        try:  # borderless window on macOS Tk
            self.root.tk.call("::tk::unsupported::MacWindowStyle", "style",
                              self.root._w, "plain", "none")
        except tk.TclError:
            self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 1.0)

        # The window starts at the top-centre, directly beneath the MacBook
        # camera notch. A pure-black window makes its centre visually merge
        # with the physical black notch; the rounded lower corners make the
        # expanded panel feel like one continuous Dynamic-Island-style surface.
        self.target_width, self.target_height = args.width, args.height
        self.corner_radius = args.corner_radius
        self._screen_width = self.root.winfo_screenwidth()
        self._target_x = (self._screen_width - self.target_width) // 2
        if args.animate:
            self.root.geometry(f"220x42+{(self._screen_width - 220) // 2}+0")
        else:
            self.root.geometry(
                f"{self.target_width}x{self.target_height}+{self._target_x}+0"
            )

        self.font = tkfont.Font(family="Helvetica Neue", size=args.size, weight="bold")
        self.text = tk.Text(
            self.root, wrap="word", bg=self.BG, fg=self.TODO, font=self.font,
            bd=0, highlightthickness=0, padx=18, pady=8, cursor="arrow",
            spacing1=2, spacing3=2, insertwidth=0, selectbackground=self.BG,
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("done", foreground=self.DONE)
        self.text.tag_configure("cur", foreground=self.CURRENT)

        self.status = tk.Label(self.root, text="Starting...", bg=self.BG, fg="#9A9A9A",
                               font=("Helvetica Neue", 11), anchor="w", padx=18)
        self.status.pack(fill="x", side="bottom")

        self._load_script(script_text)
        self.follower = Follower(self.words)
        self._render()

        for key, fn in {
            "<space>": self.toggle_pause, "<Up>": lambda e: self._nudge(-6),
            "<Down>": lambda e: self._nudge(6), "<r>": self._restart,
            "<plus>": lambda e: self._resize(2), "<equal>": lambda e: self._resize(2),
            "<minus>": lambda e: self._resize(-2),
            "<q>": self.quit, "<Escape>": self.quit,
        }.items():
            self.root.bind(key, fn)
        self.status.bind("<ButtonPress-1>", self._drag_start)
        self.status.bind("<B1-Motion>", self._drag_move)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.root.update()
        self._apply_native_notch_style()
        if not args.no_hide:
            self._harden()
            self.root.after(400, self._harden)  # re-apply once macOS has the window

        if args.animate:
            self.root.after(30, self._animate_expand)
        self.root.after(40, self._poll)

    # ---- native macOS notch integration
    def _apply_native_notch_style(self):
        """Style the Tk window's underlying NSWindow as a clean black panel."""
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSApp, NSColor
            from Quartz import kCGWindowLevelStatusBar

            self.root.update_idletasks()
            target = None
            for window in NSApp.windows():
                # Tk creates a native NSWindow for this toplevel.
                if window.title() == "Notch" or window.isKeyWindow():
                    target = window
                    if window.title() == "Notch":
                        break

            if target is None:
                return

            target.setOpaque_(False)
            target.setBackgroundColor_(NSColor.clearColor())
            target.setHasShadow_(False)
            target.setLevel_(kCGWindowLevelStatusBar + 1)
            target.setCollectionBehavior_((1 << 0) | (1 << 8))  # all Spaces + full-screen auxiliary

            view = target.contentView()
            view.setWantsLayer_(True)
            layer = view.layer()
            layer.setBackgroundColor_(NSColor.blackColor().CGColor())
            layer.setCornerRadius_(self.corner_radius)
            layer.setMasksToBounds_(True)

            # Keep the actual Tk widgets black too, so there is no visible
            # seam between the native window surface and its contents.
            self.root.configure(bg="#000000")
        except ImportError:
            print(
                "For native notch styling, install: "
                "python3 -m pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz",
                file=sys.stderr,
            )
        except Exception as exc:
            print("Could not apply native notch styling:", exc, file=sys.stderr)

    def _animate_expand(self):
        """Ease the small notch-sized panel into the full teleprompter."""
        duration_ms = 460
        start_width, start_height = 220, 42
        steps = 28
        self._animation_step = getattr(self, "_animation_step", 0) + 1
        t = min(1.0, self._animation_step / steps)
        eased = 1.0 - (1.0 - t) ** 3  # ease-out cubic

        width = round(start_width + (self.target_width - start_width) * eased)
        height = round(start_height + (self.target_height - start_height) * eased)
        x = (self._screen_width - width) // 2
        self.root.geometry(f"{width}x{height}+{x}+0")

        if t < 1.0:
            self.root.after(max(1, duration_ms // steps), self._animate_expand)
        else:
            self.root.geometry(
                f"{self.target_width}x{self.target_height}+{self._target_x}+0"
            )
            self._apply_native_notch_style()

    # ---- script display
    def _load_script(self, script_text):
        self.words, self.spans = [], []
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in script_text.strip().splitlines():
            for word in line.split():
                start = self.text.index("end-1c")
                self.text.insert("end", word)
                self.spans.append((start, self.text.index("end-1c")))
                self.words.append(word)
                self.text.insert("end", " ")
            self.text.insert("end", "\n")
        self.text.configure(state="disabled")

    def _render(self):
        pos = self.follower.pos
        self.text.tag_remove("done", "1.0", "end")
        self.text.tag_remove("cur", "1.0", "end")
        if pos > 0:
            self.text.tag_add("done", "1.0", self.spans[pos - 1][1])
        if pos < len(self.spans):
            self.text.tag_add("cur", *self.spans[pos])
            self.text.yview(f"{self.spans[pos][0]} -1 displaylines")
        else:
            self.status.configure(text="End of script")

    # ---- events from the Swift helper
    def _poll(self):
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def _handle(self, msg):
        if "error" in msg:
            self.status.configure(text=msg["error"][:90], fg="#FF6B6B")
            print("listen:", msg["error"], file=sys.stderr)
        elif msg.get("event") == "ready":
            self._set_status()
        elif msg.get("event") == "reset":
            self.seen = 0
        elif msg.get("event") == "ended":
            self.status.configure(text="Voice engine stopped", fg="#FF6B6B")
        elif "text" in msg:
            words = msg["text"].split()
            if len(words) < self.seen:
                self.seen = len(words)
            new, self.seen = words[self.seen:], len(words)
            if new and not self.paused:
                self.follower.feed(new)
                self._render()

    def _set_status(self):
        if self.paused:
            self.status.configure(text="Paused  (space to resume)", fg="#E0B341")
        else:
            self.status.configure(text="Following your voice", fg="#5AB8F7")

    # ---- controls
    def toggle_pause(self, _e=None):
        self.paused = not self.paused
        self._set_status()

    def _nudge(self, delta):
        self.follower.move(delta)
        self._render()

    def _restart(self, _e=None):
        self.follower.reset()
        self._render()
        self._set_status()

    def _resize(self, delta):
        self.font.configure(size=max(10, self.font.cget("size") + delta))
        self._render()

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    # ---- macOS window tweaks via pyobjc (optional)
    def _harden(self):
        try:
            from AppKit import NSApp
            for win in NSApp.windows():
                if win.title() == "Notch" or win.isKeyWindow():
                    win.setSharingType_(0)  # NSWindowSharingNone: hidden from capture
                    win.setHasShadow_(False)
                    break
        except ImportError:
            if not getattr(self, "_warned", False):
                self._warned = True
                print("Tip: pip install pyobjc-framework-Cocoa to hide Notch from screen sharing.")
        except Exception as exc:  # pragma: no cover
            print("Could not apply window tweaks:", exc)

    def quit(self, _e=None):
        self.voice.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Voice-following teleprompter for macOS")
    ap.add_argument("script", nargs="?", help="path to a .txt script")
    ap.add_argument("-c", "--clipboard", action="store_true", help="read the script from the clipboard")
    ap.add_argument("--lang", default="en-US", help="speech locale, e.g. en-US, de-DE, es-ES, fr-FR")
    ap.add_argument("--size", type=int, default=24, help="font size")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=170,
                    help="expanded panel height in points (default: 170)")
    ap.add_argument("--corner-radius", type=float, default=28,
                    help="native macOS panel corner radius in points (default: 28)")
    ap.add_argument("--no-animate", dest="animate", action="store_false",
                    help="show the expanded panel immediately")
    ap.set_defaults(animate=True)
    ap.add_argument("--no-hide", action="store_true", help="do not hide from screen sharing")
    args = ap.parse_args()

    if args.clipboard:
        script = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    elif args.script:
        script = Path(args.script).expanduser().read_text(encoding="utf-8")
    else:
        script = SAMPLE_SCRIPT
    if not script.strip():
        sys.exit("The script is empty.")

    binary = build_listener()
    events: "queue.Queue[dict]" = queue.Queue()
    voice = Voice(binary, args.lang, events)
    try:
        NotchApp(script, voice, events, args).run()
    finally:
        voice.stop()


if __name__ == "__main__":
    main()