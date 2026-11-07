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
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox
from uuid import uuid4

HERE = Path(__file__).resolve().parent
SWIFT_SRC = HERE / "listen.swift"
BUILD_DIR = HERE / ".build"
LISTEN_BIN = BUILD_DIR / "listen"
NOTES_FILE = Path.home() / "Library" / "Application Support" / "Open Notch" / "notes.json"

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


def use_accessory_app_policy():
    """Hide the Python menu-bar and Dock entries while keeping app windows usable."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        app = NSApplication.sharedApplication()
        if not app.setActivationPolicy_(NSApplicationActivationPolicyAccessory):
            print("Could not switch Open Notch to accessory app mode.", file=sys.stderr)
    except ImportError:
        print(
            "For macOS menu-bar integration, install: "
            "python3 -m pip install pyobjc-framework-Cocoa",
            file=sys.stderr,
        )
    except Exception as exc:
        print("Could not hide the Python app menu:", exc, file=sys.stderr)


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

    def __init__(self, script_text, voice, events, args, parent=None, on_close=None):
        self.voice, self.events = voice, events
        self.on_close = on_close
        self.paused = False
        self.seen = 0

        self.root = tk.Tk() if parent is None else tk.Toplevel(parent)
        self.root.title("Notch")
        self.root.configure(bg=self.BG)
        use_accessory_app_policy()
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
            bd=0, highlightthickness=0, padx=24, pady=14, cursor="arrow",
            spacing1=3, spacing3=3, insertwidth=0, selectbackground=self.BG,
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("done", foreground=self.DONE)
        self.text.tag_configure("cur", foreground=self.CURRENT)

        self.footer = tk.Frame(self.root, bg=self.BG, padx=14, pady=8)
        self.footer.pack(fill="x", side="bottom")
        self.status = tk.Label(
            self.footer, text="Starting...", bg=self.BG, fg="#9A9A9A",
            font=("Helvetica Neue", 10), anchor="w",
        )
        self.status.pack(side="left", fill="x", expand=True, padx=(4, 8))

        for label, command, width in (
            ("−6", lambda: self._nudge(-6), 3),
            ("+6", lambda: self._nudge(6), 3),
            ("A−", lambda: self._resize(-2), 3),
            ("A+", lambda: self._resize(2), 3),
            ("Restart", self._restart, 7),
        ):
            button = tk.Button(
                self.footer, text=label, command=command, width=width,
                bg="#1C1C1E", fg="#E5E5E7", activebackground="#38383A",
                activeforeground="#FFFFFF", disabledforeground="#777777",
                relief="flat", bd=0, highlightthickness=0,
                font=("Helvetica Neue", 9), cursor="arrow", padx=5, pady=4,
            )
            button.pack(side="left", padx=2)
        self.pause_button = tk.Button(
            self.footer, text="Pause", command=self.toggle_pause,
            width=6, bg="#1C1C1E", fg="#E5E5E7", activebackground="#38383A",
            activeforeground="#FFFFFF", relief="flat", bd=0,
            highlightthickness=0, font=("Helvetica Neue", 9),
            cursor="arrow", padx=5, pady=4,
        )
        self.pause_button.pack(side="left", padx=(2, 4))

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
        for drag_widget in (self.root, self.text, self.status, self.footer):
            drag_widget.bind("<ButtonPress-1>", self._drag_start)
            drag_widget.bind("<B1-Motion>", self._drag_move)
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
            width, height = self.root.winfo_width(), self.root.winfo_height()
            radius = min(self.corner_radius, width / 2, height / 2)
            layer.setCornerRadius_(radius)
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
            self.pause_button.configure(text="Resume")
        else:
            self.status.configure(text="Following your voice", fg="#5AB8F7")
            self.pause_button.configure(text="Pause")

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
        if self.on_close:
            self.on_close(self)

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------------- home
class NoteStore:
    """Small local JSON store for scripts managed from the home screen."""

    def __init__(self, path=NOTES_FILE):
        self.path = Path(path)
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.notes = [
                    note for note in data
                    if isinstance(note, dict)
                    and isinstance(note.get("id"), str)
                    and isinstance(note.get("title"), str)
                    and isinstance(note.get("body"), str)
                ]
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Could not read saved notes at {self.path}: {exc}") from exc
        else:
            self.notes = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(self.notes, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def create(self):
        note = {
            "id": str(uuid4()),
            "title": "Untitled note",
            "body": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.notes.insert(0, note)
        self.save()
        return note

    def get(self, note_id):
        return next((note for note in self.notes if note["id"] == note_id), None)

    def delete(self, note_id):
        self.notes = [note for note in self.notes if note["id"] != note_id]
        self.save()


class NotchHome:
    """Home screen for creating, saving, and launching teleprompter scripts."""

    BG = "#090B0E"
    SIDEBAR = "#101318"
    PANEL = "#12161B"
    MUTED = "#929BA5"
    ACCENT = "#5AB8F7"

    def __init__(self, args):
        self.args = args
        self.store = NoteStore()
        self.selected_id = None
        self.active_prompter = None
        self.root = tk.Tk()
        self.root.title("Open Notch")
        self.root.geometry("980x650")
        self.root.minsize(820, 540)
        # Tk's override-redirect removes native title bars even when PyObjC is
        # unavailable; the launcher supplies its own close and drag affordances.
        self.root.overrideredirect(True)
        self.root.configure(bg=self.BG)
        use_accessory_app_policy()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Command-q>", self.close)
        self.root.bind("<Command-w>", self.close)

        shell = tk.Frame(self.root, bg=self.BG)
        shell.pack(fill="both", expand=True, padx=20, pady=20)
        sidebar = tk.Frame(shell, bg=self.SIDEBAR, width=260)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand_row = tk.Frame(sidebar, bg=self.SIDEBAR)
        brand_row.pack(fill="x", padx=20, pady=(20, 4))
        brand = tk.Label(
            brand_row, text="OPEN NOTCH", bg=self.SIDEBAR, fg="#F5F5F7",
            font=("Avenir Next", 12, "bold"), anchor="w",
        )
        brand.pack(side="left", fill="x", expand=True)
        close_button = tk.Button(
            brand_row, text="×", command=self.close, bg=self.SIDEBAR,
            fg="#AAB3BC", activebackground="#272C33", activeforeground="#FFFFFF",
            relief="flat", bd=0, highlightthickness=0,
            font=("Avenir Next", 17), width=2, cursor="arrow",
        )
        close_button.pack(side="right", padx=(4, 0), pady=0)
        self._bind_window_drag(brand_row)
        self._bind_window_drag(brand)
        tk.Label(
            sidebar, text="Your presentation scripts", bg=self.SIDEBAR,
            fg=self.MUTED, font=("Avenir Next", 10), anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 16))
        self._button(
            sidebar, "+  New note", self.new_note, primary=True,
        ).pack(fill="x", padx=16, pady=(0, 18))
        tk.Label(
            sidebar, text="LIBRARY", bg=self.SIDEBAR, fg="#73737B",
            font=("Helvetica Neue", 9, "bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 8))
        self.note_list = tk.Listbox(
            sidebar, bg=self.SIDEBAR, fg="#D8D8DC", selectbackground="#26394A",
            selectforeground="#FFFFFF", activestyle="none", relief="flat",
            borderwidth=0, highlightthickness=0, font=("Helvetica Neue", 12),
            exportselection=False,
        )
        self.note_list.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self.note_list.bind("<<ListboxSelect>>", self._on_select)

        content = tk.Frame(shell, bg=self.BG)
        content.pack(side="left", fill="both", expand=True, padx=(24, 4))
        header = tk.Frame(content, bg=self.BG)
        header.pack(fill="x", pady=(6, 20))
        heading = tk.Frame(header, bg=self.BG)
        heading.pack(side="left", fill="x", expand=True)
        tk.Label(
            heading, text="Home", bg=self.BG, fg="#F5F5F7",
            font=("Avenir Next", 27, "bold"), anchor="w",
        ).pack(fill="x")
        tk.Label(
            heading, text="Write it here. Keep it beside your camera when you present.",
            bg=self.BG, fg=self.MUTED, font=("Avenir Next", 11), anchor="w",
        ).pack(fill="x", pady=(4, 0))
        self._bind_window_drag(heading)
        for child in heading.winfo_children():
            self._bind_window_drag(child)
        self.launch_button = self._button(
            header, "Launch teleprompter  →", self.launch, primary=True,
        )
        self.launch_button.pack(side="right", padx=(12, 0), pady=(8, 0))

        editor = tk.Frame(content, bg=self.PANEL, highlightthickness=1,
                          highlightbackground="#28282D")
        editor.pack(fill="both", expand=True)
        tk.Label(
            editor, text="NOTE TITLE", bg=self.PANEL, fg=self.MUTED,
            font=("Helvetica Neue", 9, "bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(18, 7))
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(
            editor, textvariable=self.title_var, bg=self.PANEL, fg="#F5F5F7",
            insertbackground="#FFFFFF", relief="flat", bd=0,
            font=("Helvetica Neue", 18, "bold"),
        )
        self.title_entry.pack(fill="x", padx=20, pady=(0, 16))
        tk.Frame(editor, bg="#29292E", height=1).pack(fill="x", padx=20)
        self.body = tk.Text(
            editor, wrap="word", bg=self.PANEL, fg="#E7E7EA",
            insertbackground="#FFFFFF", selectbackground="#31526A",
            relief="flat", bd=0, highlightthickness=0,
            font=("Helvetica Neue", 14), padx=20, pady=18, spacing1=3,
        )
        self.body.pack(fill="both", expand=True)
        self.body.bind("<KeyRelease>", self._update_count)

        footer = tk.Frame(content, bg=self.BG)
        footer.pack(fill="x", pady=(14, 0))
        self.count_label = tk.Label(
            footer, text="0 words", bg=self.BG, fg=self.MUTED,
            font=("Helvetica Neue", 10), anchor="w",
        )
        self.count_label.pack(side="left", fill="x", expand=True)
        self.status = tk.Label(
            footer, text="Saved on this Mac", bg=self.BG, fg=self.MUTED,
            font=("Helvetica Neue", 10),
        )
        self.status.pack(side="left", padx=(0, 12))
        self.delete_button = self._button(footer, "Delete", self.delete_note)
        self.delete_button.pack(side="right", padx=(8, 0))
        self.save_button = self._button(footer, "Save", self.save_current)
        self.save_button.pack(side="right")

        self.root.update_idletasks()
        self._remove_native_titlebar()
        self._refresh_notes()
        if self.store.notes:
            self._select_id(self.store.notes[0]["id"])
        else:
            self._set_editor_enabled(False)
            self.status.configure(text="Create a note to get started")

    def _button(self, parent, label, command, primary=False):
        return tk.Button(
            parent, text=label, command=command,
            bg=self.ACCENT if primary else "#242428",
            fg="#07131A" if primary else "#E5E5E7",
            activebackground="#87CCFA" if primary else "#38383C",
            activeforeground="#07131A" if primary else "#FFFFFF",
            relief="flat", bd=0, highlightthickness=0,
            font=("Avenir Next", 10, "bold"), cursor="arrow",
            padx=14, pady=9,
        )

    def _remove_native_titlebar(self):
        """Use a clean borderless macOS window with the launcher content as its chrome."""
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSApp, NSColor, NSWindowStyleMaskTitled, NSWindowTitleHidden

            target = next(
                (window for window in NSApp.windows() if window.title() == "Open Notch"),
                None,
            )
            if target is None:
                return
            target.setStyleMask_(target.styleMask() & ~NSWindowStyleMaskTitled)
            target.setTitleVisibility_(NSWindowTitleHidden)
            target.setTitlebarAppearsTransparent_(True)
            target.setMovableByWindowBackground_(False)
            target.setOpaque_(False)
            target.setBackgroundColor_(NSColor.clearColor())
            target.setHasShadow_(True)
            view = target.contentView()
            view.setWantsLayer_(True)
            layer = view.layer()
            layer.setCornerRadius_(18)
            layer.setMasksToBounds_(True)
        except ImportError:
            # The Tk override-redirect above already removed the title bar.
            # PyObjC only adds the native shadow and rounded window corners.
            return
        except Exception as exc:
            print("Could not remove the native title bar:", exc, file=sys.stderr)

    def _bind_window_drag(self, widget):
        widget.bind("<ButtonPress-1>", self._drag_start, add="+")
        widget.bind("<B1-Motion>", self._drag_move, add="+")

    def _drag_start(self, event):
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(
            f"+{event.x_root - self._drag_offset_x}+{event.y_root - self._drag_offset_y}"
        )

    def _set_editor_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.title_entry.configure(state=state)
        self.body.configure(state=state)
        self.save_button.configure(state=state)
        self.delete_button.configure(state=state)
        self.launch_button.configure(state=state)

    def _refresh_notes(self, selected_id=None):
        self.note_list.delete(0, "end")
        for note in self.store.notes:
            title = note["title"].strip() or "Untitled note"
            self.note_list.insert("end", title)
            if note["id"] == selected_id:
                index = self.note_list.size() - 1
                self.note_list.selection_set(index)
                self.note_list.activate(index)

    def _select_id(self, note_id):
        note = self.store.get(note_id)
        if not note:
            return
        self.selected_id = note_id
        self.title_var.set(note["title"])
        self.body.configure(state="normal")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", note["body"])
        self._set_editor_enabled(True)
        self._refresh_notes(note_id)
        self.status.configure(text="Saved on this Mac")
        self._update_count()

    def _on_select(self, _event=None):
        selection = self.note_list.curselection()
        if not selection:
            return
        note = self.store.notes[selection[0]]
        if note["id"] == self.selected_id:
            return
        self._save_current(silent=True)
        self._select_id(note["id"])

    def _save_current(self, silent=False):
        note = self.store.get(self.selected_id) if self.selected_id else None
        if not note:
            return False
        title = self.title_var.get().strip() or "Untitled note"
        body = self.body.get("1.0", "end-1c")
        changed = title != note["title"] or body != note["body"]
        if changed:
            note["title"] = title
            note["body"] = body
            note["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.store.save()
            self._refresh_notes(self.selected_id)
        if not silent:
            self.status.configure(text="Saved" if changed else "All changes saved")
        return True

    def save_current(self):
        self._save_current()

    def new_note(self):
        self._save_current(silent=True)
        note = self.store.create()
        self._refresh_notes(note["id"])
        self._select_id(note["id"])
        self.title_entry.focus_set()
        self.title_entry.selection_range(0, "end")

    def delete_note(self):
        note = self.store.get(self.selected_id) if self.selected_id else None
        if not note:
            return
        if not messagebox.askyesno("Delete note", f"Delete ‘{note['title']}’?", parent=self.root):
            return
        self.store.delete(note["id"])
        self.selected_id = None
        if self.store.notes:
            self._select_id(self.store.notes[0]["id"])
        else:
            self.title_var.set("")
            self.body.configure(state="normal")
            self.body.delete("1.0", "end")
            self._set_editor_enabled(False)
            self._refresh_notes()
            self.status.configure(text="Create a note to get started")
            self._update_count()

    def _update_count(self, _event=None):
        body = self.body.get("1.0", "end-1c")
        count = len(body.split())
        self.count_label.configure(text=f"{count} word{'s' if count != 1 else ''}")

    def launch(self):
        note = self.store.get(self.selected_id) if self.selected_id else None
        if not note:
            return
        self._save_current(silent=True)
        note = self.store.get(self.selected_id)
        script = note["body"].strip()
        if not script:
            self.status.configure(text="Add some script text before launching")
            return
        if self.active_prompter:
            self.active_prompter.quit()
        try:
            binary = build_listener()
            events = queue.Queue()
            voice = Voice(binary, self.args.lang, events)
            self.active_prompter = NotchApp(
                script, voice, events, self.args, parent=self.root,
                on_close=self._prompter_closed,
            )
            self.status.configure(text=f"Launched {note['title']}")
        except (OSError, RuntimeError, SystemExit) as exc:
            self.status.configure(text="Could not launch teleprompter")
            messagebox.showerror("Could not launch", str(exc), parent=self.root)

    def _prompter_closed(self, prompter):
        if self.active_prompter is prompter:
            self.active_prompter = None

    def close(self, _event=None):
        self._save_current(silent=True)
        if self.active_prompter:
            self.active_prompter.quit()
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
    ap.add_argument("--corner-radius", type=float, default=36,
                    help="native macOS panel corner radius in points (default: 36)")
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
        NotchHome(args).run()
        return
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
