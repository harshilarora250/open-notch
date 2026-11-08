#!/usr/bin/env python3
"""Borderless, voice-following presenter window for Open Notch."""

import argparse
import difflib
import json
import math
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from notes_store import NoteStore

HERE = Path(__file__).resolve().parent
SWIFT_SRC = HERE / "listen.swift"
BUILD_DIR = HERE / ".build"
LISTEN_BIN = BUILD_DIR / "listen"

BG = "#000000"
TODO = "#FFFFFF"
DONE = "#6B6B6B"
CURRENT = "#4B91D5"
STATUS = "#9A9A9A"


def set_presenter_activation_policy():
    """Make the floating presenter a utility app without a Dock or menu-bar item."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        app = NSApplication.sharedApplication()
        if not app.setActivationPolicy_(NSApplicationActivationPolicyAccessory):
            print("Could not hide the presenter Dock and menu-bar items.", file=sys.stderr)
    except ImportError:
        pass
    except Exception as exc:
        print("Could not set the presenter activation policy:", exc, file=sys.stderr)

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>net.local.notch.listen</string>
<key>CFBundleName</key><string>Open Notch Presenter</string>
<key>NSMicrophoneUsageDescription</key><string>Open Notch follows your voice to scroll your script.</string>
<key>NSSpeechRecognitionUsageDescription</key><string>Open Notch transcribes speech on this Mac to follow your script.</string>
</dict></plist>
"""


def build_listener():
    if sys.platform != "darwin":
        raise RuntimeError("The voice-following presenter currently requires macOS.")
    if not SWIFT_SRC.exists():
        raise RuntimeError(f"Missing speech helper: {SWIFT_SRC}")
    if LISTEN_BIN.exists() and LISTEN_BIN.stat().st_mtime >= SWIFT_SRC.stat().st_mtime:
        return LISTEN_BIN
    if not shutil.which("swiftc"):
        raise RuntimeError("swiftc not found. Install the Xcode command line tools.")
    BUILD_DIR.mkdir(exist_ok=True)
    plist = BUILD_DIR / "Info.plist"
    plist.write_text(INFO_PLIST, encoding="utf-8")
    command = [
        "swiftc", "-O", str(SWIFT_SRC), "-o", str(LISTEN_BIN),
        "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT",
        "-Xlinker", "__info_plist", "-Xlinker", str(plist),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Swift compile failed:\n" + result.stderr)
    return LISTEN_BIN


class Voice:
    def __init__(self, binary, lang, out):
        self.out = out
        self.proc = subprocess.Popen(
            [str(binary), lang], stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                message = json.loads(line.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            self.out.put(message)
        self.out.put({"event": "ended"})

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()


def norm(word):
    return re.sub(r"[^\w]", "", word.lower())


def similar(a, b):
    if a == b:
        return True
    if len(a) > 3 and len(b) > 3:
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
    return False


class Follower:
    LOOKAHEAD = 8

    def __init__(self, words):
        self.keys = [norm(word) for word in words]
        self.n = len(words)
        self.pos = 0
        self.recent = []
        self.misses = 0
        self._skip_empty()

    def _skip_empty(self):
        while self.pos < self.n and not self.keys[self.pos]:
            self.pos += 1

    def feed(self, spoken_words):
        for raw in spoken_words:
            word = norm(raw)
            if not word:
                continue
            self.recent = (self.recent + [word])[-3:]
            matched = False
            for index in range(self.pos, min(self.n, self.pos + self.LOOKAHEAD)):
                if not self.keys[index]:
                    continue
                if index - self.pos > 2 and len(word) < 4:
                    continue
                if similar(word, self.keys[index]):
                    self.pos = index + 1
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
        if len(self.recent) < 3:
            return
        lo, hi = max(0, self.pos - 15), min(self.n - 2, self.pos + 80)
        for index in range(lo, hi):
            if all(similar(self.recent[k], self.keys[index + k])
                   for k in range(3) if index + k < self.n):
                self.pos = min(self.n, index + 3)
                self.misses = 0
                return

    def move(self, delta):
        self.pos = max(0, min(self.n, self.pos + delta))
        self._skip_empty()
        self.recent, self.misses = [], 0

    def reset(self):
        self.pos, self.recent, self.misses = 0, [], 0
        self._skip_empty()


class Prompter:
    def __init__(self, script, voice, events, args):
        self.voice, self.events, self.args = voice, events, args
        self.paused = False
        self.seen = 0
        self.root = tk.Tk()
        self.root.title("Open Notch Presenter")
        self.root.overrideredirect(True)
        set_presenter_activation_policy()
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self._build_ui(script)
        screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.width, self.height = self._fit_geometry(script)
        self.x = (screen_width - self.width) // 2
        if args.animate:
            self.root.geometry(f"260x60+{(screen_width - 260) // 2}+8")
        else:
            self.root.geometry(f"{self.width}x{self.height}+{self.x}+8")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        for key, handler in {
            "<space>": self.toggle_following,
            "<Up>": lambda _e: self._nudge(-6),
            "<Down>": lambda _e: self._nudge(6),
            "<r>": self._restart,
            "<plus>": lambda _e: self._resize_text(2),
            "<equal>": lambda _e: self._resize_text(2),
            "<minus>": lambda _e: self._resize_text(-2),
            "<bracketleft>": lambda _e: self._resize_panel(-30),
            "<bracketright>": lambda _e: self._resize_panel(30),
            "<q>": self.close,
            "<Escape>": self.close,
        }.items():
            self.root.bind(key, handler)

        self.root.update()
        self._style_native_surface()
        if args.animate:
            self.root.after(24, self._animate_expand)
        self.root.after(40, self._poll)

    def _build_ui(self, script):
        self.font = tkfont.Font(
            family="Avenir Next", size=self.args.size, weight="normal",
        )
        self.text = tk.Text(
            self.root, wrap="word", bg=BG, fg=TODO, font=self.font,
            bd=0, highlightthickness=0, padx=44, pady=22, cursor="arrow",
            spacing1=6, spacing3=6, insertwidth=0, selectbackground=BG,
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("spoken", foreground=DONE)
        self.text.tag_configure("current", foreground=CURRENT)
        self.words, self.spans = [], []
        self._load_script(script)
        self.follower = Follower(self.words)
        self._render()

        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=42, pady=(0, 15))
        self.activity = tk.Canvas(footer, width=42, height=14, bg=BG,
                                 highlightthickness=0)
        self.activity.pack(side="left", padx=(0, 9))
        self._draw_activity(CURRENT)
        self.status = tk.Label(
            footer, text="Following · Space pauses", bg=BG, fg=STATUS,
            font=("Helvetica Neue", 9), anchor="w",
        )
        self.status.pack(side="left", fill="x", expand=True)

        for widget in (self.root, self.text, footer, self.status, self.activity):
            widget.bind("<ButtonPress-1>", self._drag_start, add="+")
            widget.bind("<B1-Motion>", self._drag_move, add="+")

    def _fit_geometry(self, script):
        screen_width = self.root.winfo_screenwidth()
        width_limit = max(320, min(self.args.width, screen_width - 40))
        min_width = min(520, width_limit)
        natural_text_width = max(
            (self.font.measure(line) for line in script.splitlines()), default=0,
        )
        width = min(width_limit, max(min_width, natural_text_width + 96))

        screen_height = self.root.winfo_screenheight()
        height_limit = max(160, int(screen_height * 0.52))
        if self.args.height is not None:
            return width, min(height_limit, max(140, self.args.height))

        text_width = max(120, width - 88)
        visual_lines = sum(
            max(1, math.ceil(self.font.measure(line) / text_width))
            for line in script.splitlines()
        )
        visual_lines = max(1, visual_lines)
        line_height = self.font.metrics("linespace") + 12
        desired_height = visual_lines * line_height + 68
        return width, min(height_limit, max(140, desired_height))

    def _load_script(self, script):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in script.strip().splitlines():
            for word in line.split():
                start = self.text.index("end-1c")
                self.text.insert("end", word)
                self.spans.append((start, self.text.index("end-1c")))
                self.words.append(word)
                self.text.insert("end", " ")
            self.text.insert("end", "\n")
        self.text.configure(state="disabled")

    def _render(self):
        position = self.follower.pos
        self.text.tag_remove("spoken", "1.0", "end")
        self.text.tag_remove("current", "1.0", "end")
        if position:
            self.text.tag_add("spoken", "1.0", self.spans[position - 1][1])
        if position < len(self.spans):
            if getattr(self, "_finish_after_id", None):
                self.root.after_cancel(self._finish_after_id)
                self._finish_after_id = None
            self.text.tag_add("current", *self.spans[position])
            self.text.yview(f"{self.spans[position][0]} -1 displaylines")
        elif self.spans and hasattr(self, "status"):
            self.status.configure(text="Script complete · closing…")
            if not getattr(self, "_finish_after_id", None):
                self._finish_after_id = self.root.after(1100, self.close)

    def _draw_activity(self, color):
        self.activity.delete("all")
        heights = (4, 7, 11, 6, 14, 8, 4)
        for index, height in enumerate(heights):
            x = 3 + index * 6
            self.activity.create_line(x, 9 - height // 2, x, 9 + height // 2,
                                      fill=color, width=2, capstyle="round")

    def _poll(self):
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(40, self._poll)

    def _handle(self, message):
        if "error" in message:
            self.status.configure(text=message["error"][:90], fg="#B44848")
            self._draw_activity("#C96969")
            return
        if message.get("event") == "ready":
            self._set_status()
        elif message.get("event") == "reset":
            self.seen = 0
        elif message.get("event") == "ended":
            self.status.configure(text="Voice engine stopped", fg="#B44848")
        elif "text" in message:
            words = message["text"].split()
            if len(words) < self.seen:
                self.seen = len(words)
            new_words, self.seen = words[self.seen:], len(words)
            if new_words and not self.paused:
                self.follower.feed(new_words)
                self._render()

    def _set_status(self):
        if self.paused:
            self.status.configure(text="Paused · Space to resume", fg=STATUS)
            self._draw_activity(STATUS)
        else:
            self.status.configure(text="Following · Space pauses", fg=STATUS)
            self._draw_activity(CURRENT)
        self._style_native_surface()

    def toggle_following(self, _event=None):
        self.paused = not self.paused
        self._set_status()

    def _nudge(self, delta):
        self.follower.move(delta)
        self._render()

    def _restart(self, _event=None):
        self.follower.reset()
        self._render()
        self._set_status()

    def _resize_text(self, delta):
        self.font.configure(size=max(16, self.font.cget("size") + delta))
        self._render()

    def _resize_panel(self, delta):
        self.height = max(140, min(int(self.screen_height * 0.72), self.height + delta))
        self.root.geometry(f"{self.width}x{self.height}+{self.x}+8")
        self._style_native_surface()

    def _style_native_surface(self):
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSApp, NSColor
            from Quartz import kCGWindowLevelStatusBar

            target = next(
                (window for window in NSApp.windows()
                 if window.title() == "Open Notch Presenter"),
                None,
            )
            if not target:
                return
            target.setOpaque_(False)
            target.setBackgroundColor_(NSColor.clearColor())
            target.setHasShadow_(True)
            target.setLevel_(kCGWindowLevelStatusBar + 1)
            target.setCollectionBehavior_((1 << 0) | (1 << 8))
            target.setSharingType_(0)
            view = target.contentView()
            view.setWantsLayer_(True)
            layer = view.layer()
            visible_height = self.root.winfo_height() or self.height
            layer.setCornerRadius_(visible_height / 2)
            layer.setMasksToBounds_(True)
            layer.setBorderWidth_(1.2)
            layer.setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
                int(CURRENT[1:3], 16) / 255,
                int(CURRENT[3:5], 16) / 255,
                int(CURRENT[5:7], 16) / 255,
                0.24,
            ).CGColor())
            layer.setShadowColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.22, 0.55, 0.78, 0.34,
            ).CGColor())
            layer.setShadowOffset_((0, -3))
            layer.setShadowRadius_(18)
            layer.setShadowOpacity_(0.42)
        except ImportError:
            # Tk still supplies the separate, borderless presenter window.
            pass
        except Exception as exc:
            print("Could not style the native presenter surface:", exc, file=sys.stderr)

    def _animate_expand(self):
        steps = 28
        self._animation_step = getattr(self, "_animation_step", 0) + 1
        t = min(1.0, self._animation_step / steps)
        eased = 1.0 - (1.0 - t) ** 3
        width = round(260 + (self.width - 260) * eased)
        height = round(60 + (self.height - 60) * eased)
        screen_width = self.root.winfo_screenwidth()
        x = (screen_width - width) // 2
        self.root.geometry(f"{width}x{height}+{x}+8")
        self._style_native_surface()
        if t < 1:
            self.root.after(16, self._animate_expand)
        else:
            self.root.geometry(f"{self.width}x{self.height}+{self.x}+8")
            self._style_native_surface()

    def _drag_start(self, event):
        self.drag_x = event.x_root - self.root.winfo_x()
        self.drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(f"+{event.x_root - self.drag_x}+{event.y_root - self.drag_y}")

    def close(self, _event=None):
        self.voice.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Open Notch floating presenter")
    parser.add_argument("script", nargs="?", help="text file to present")
    parser.add_argument("--note-id", help="load a saved note from the Open Notch library")
    parser.add_argument("-c", "--clipboard", action="store_true")
    parser.add_argument("--lang", default="en-US")
    parser.add_argument("--size", type=int, default=27)
    parser.add_argument("--width", type=int, default=900,
                        help="maximum presenter width; actual width adapts to the script")
    parser.add_argument("--height", type=int, default=None,
                        help="fixed presenter height; defaults to a script-fitted height")
    parser.add_argument("--no-animate", dest="animate", action="store_false")
    parser.set_defaults(animate=True)
    args = parser.parse_args()

    if args.note_id:
        note = NoteStore().get(args.note_id)
        if not note:
            parser.error(f"saved note not found: {args.note_id}")
        script = note["body"]
    elif args.clipboard:
        script = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    elif args.script:
        script = Path(args.script).expanduser().read_text(encoding="utf-8")
    else:
        parser.error("provide a script file, --clipboard, or --note-id")
    if not script.strip():
        parser.error("the script is empty")

    voice = Voice(build_listener(), args.lang, queue.Queue())
    try:
        Prompter(script, voice, voice.out, args).run()
    finally:
        voice.stop()


if __name__ == "__main__":
    main()
