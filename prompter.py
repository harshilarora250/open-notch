#!/usr/bin/env python3
"""Borderless, voice-following presenter window for Open Notch."""

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

from notes_store import NoteStore

HERE = Path(__file__).resolve().parent
SWIFT_SRC = HERE / "listen.swift"
BUILD_DIR = HERE / ".build"
LISTEN_BIN = BUILD_DIR / "listen"

PEARL = "#F4F5F2"
INK = "#171B1D"
SPOKEN = "#A1A8AA"
MUTED = "#68757A"
BLUE = "#4B91D5"
GREEN = "#59A975"

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


def draw_icon(canvas, name, color):
    canvas.delete("all")
    canvas.configure(cursor="arrow")
    if name == "close":
        canvas.create_line(9, 9, 21, 21, fill=color, width=1.8, capstyle="round")
        canvas.create_line(21, 9, 9, 21, fill=color, width=1.8, capstyle="round")
    elif name == "camera":
        canvas.create_rectangle(5, 8, 20, 21, outline=color, width=1.6)
        canvas.create_polygon(20, 12, 25, 9, 25, 20, 20, 17,
                             outline=color, fill="", width=1.6)
        canvas.create_oval(10, 11, 16, 17, outline=color, width=1.4)
    elif name == "mic":
        canvas.create_oval(11, 4, 19, 18, outline=color, width=1.7)
        canvas.create_arc(7, 8, 23, 23, start=180, extent=180,
                          style="arc", outline=color, width=1.7)
        canvas.create_line(15, 22, 15, 26, fill=color, width=1.7)
        canvas.create_line(11, 26, 19, 26, fill=color, width=1.7)
    elif name == "settings":
        points = [15, 3, 21, 6, 25, 13, 22, 21, 15, 25, 8, 21, 5, 13, 9, 6]
        canvas.create_polygon(points, outline=color, fill="", width=1.6)
        canvas.create_oval(12, 10, 18, 16, outline=color, width=1.5)


class Prompter:
    def __init__(self, script, voice, events, args):
        self.voice, self.events, self.args = voice, events, args
        self.paused = False
        self.seen = 0
        self.root = tk.Tk()
        self.root.title("Open Notch Presenter")
        self.root.overrideredirect(True)
        self.root.configure(bg=PEARL)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)
        self.width, self.height = args.width, args.height
        screen_width = self.root.winfo_screenwidth()
        self.x = (screen_width - self.width) // 2
        if args.animate:
            self.root.geometry(f"280x76+{(screen_width - 280) // 2}+8")
        else:
            self.root.geometry(f"{self.width}x{self.height}+{self.x}+8")

        self._build_ui(script)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        for key, handler in {
            "<space>": self.toggle_following,
            "<Up>": lambda _e: self._nudge(-6),
            "<Down>": lambda _e: self._nudge(6),
            "<r>": self._restart,
            "<plus>": lambda _e: self._resize_text(2),
            "<equal>": lambda _e: self._resize_text(2),
            "<minus>": lambda _e: self._resize_text(-2),
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
        top = tk.Frame(self.root, bg=PEARL)
        top.pack(fill="x", padx=24, pady=(17, 3))
        self.close_icon = tk.Canvas(top, width=30, height=30, bg=PEARL,
                                    highlightthickness=0)
        draw_icon(self.close_icon, "close", MUTED)
        self.close_icon.pack(side="left")
        self.close_icon.bind("<Button-1>", lambda _e: self.close())
        self._tooltip(self.close_icon, "Close presenter")

        actions = tk.Frame(top, bg=PEARL)
        actions.pack(side="right")
        camera = tk.Canvas(actions, width=30, height=30, bg=PEARL,
                           highlightthickness=0)
        draw_icon(camera, "camera", MUTED)
        camera.pack(side="left", padx=(0, 8))
        self._tooltip(camera, "Camera is not in use")
        self.mic_icon = tk.Canvas(actions, width=30, height=30, bg=PEARL,
                                  highlightthickness=0)
        draw_icon(self.mic_icon, "mic", BLUE)
        self.mic_icon.pack(side="left", padx=8)
        self.mic_icon.bind("<Button-1>", lambda _e: self.toggle_following())
        self._tooltip(self.mic_icon, "Pause voice following")
        settings = tk.Canvas(actions, width=30, height=30, bg=PEARL,
                             highlightthickness=0)
        draw_icon(settings, "settings", INK)
        settings.pack(side="left", padx=(8, 0))
        settings.bind("<Button-1>", self._show_settings)
        self._tooltip(settings, "Presenter settings")

        self.font = tkfont.Font(family="Avenir Next", size=self.args.size, weight="medium")
        self.text = tk.Text(
            self.root, wrap="word", bg=PEARL, fg=INK, font=self.font,
            bd=0, highlightthickness=0, padx=28, pady=10, cursor="arrow",
            spacing1=4, spacing3=4, insertwidth=0, selectbackground=PEARL,
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("spoken", foreground=SPOKEN)
        self.text.tag_configure("current", foreground=BLUE)
        self.words, self.spans = [], []
        self._load_script(script)
        self.follower = Follower(self.words)
        self._render()

        footer = tk.Frame(self.root, bg=PEARL)
        footer.pack(fill="x", padx=24, pady=(0, 16))
        self.activity = tk.Canvas(footer, width=48, height=18, bg=PEARL,
                                 highlightthickness=0)
        self.activity.pack(side="left", padx=(0, 10))
        self._draw_activity(BLUE)
        self.status = tk.Label(
            footer, text="Following your voice", bg=PEARL, fg=MUTED,
            font=("Avenir Next", 10), anchor="w",
        )
        self.status.pack(side="left", fill="x", expand=True)

        for widget in (self.root, top, self.text, footer, self.status):
            widget.bind("<ButtonPress-1>", self._drag_start, add="+")
            widget.bind("<B1-Motion>", self._drag_move, add="+")

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
            self.text.tag_add("current", *self.spans[position])
            self.text.yview(f"{self.spans[position][0]} -1 displaylines")
        elif self.spans and hasattr(self, "status"):
            self.status.configure(text="End of script")

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
            self.status.configure(text="Paused · press Space to resume", fg=MUTED)
            draw_icon(self.mic_icon, "mic", MUTED)
            self._tooltip(self.mic_icon, "Resume voice following")
            self._draw_activity("#C7CECF")
        else:
            self.status.configure(text="Following your voice", fg=MUTED)
            draw_icon(self.mic_icon, "mic", BLUE)
            self._tooltip(self.mic_icon, "Pause voice following")
            self._draw_activity(GREEN)
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
        self.height = max(150, min(360, self.height + delta))
        self.root.geometry(f"{self.width}x{self.height}+{self.x}+8")
        self._style_native_surface()

    def _show_settings(self, event):
        menu = tk.Menu(self.root, tearoff=False, bg=PEARL, fg=INK,
                       activebackground="#DDECF5", activeforeground=INK,
                       relief="flat", bd=0, font=("Avenir Next", 11))
        menu.add_command(label="Text smaller  (−)", command=lambda: self._resize_text(-2))
        menu.add_command(label="Text larger  (+)", command=lambda: self._resize_text(2))
        menu.add_separator()
        menu.add_command(label="Show more script", command=lambda: self._resize_panel(40))
        menu.add_command(label="Show less script", command=lambda: self._resize_panel(-40))
        menu.add_separator()
        menu.add_command(label="Move back  (↑)", command=lambda: self._nudge(-6))
        menu.add_command(label="Move forward  (↓)", command=lambda: self._nudge(6))
        menu.add_command(label="Restart script  (R)", command=self._restart)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _tooltip(self, widget, text):
        widget._tooltip_text = text
        if getattr(widget, "_tooltip_bound", False):
            return
        widget._tooltip_bound = True
        widget._tooltip_window = None
        widget._tooltip_after = None

        def show():
            if not widget.winfo_exists():
                return
            popup = tk.Toplevel(self.root)
            popup.overrideredirect(True)
            popup.configure(bg="#263139")
            tk.Label(popup, text=widget._tooltip_text, bg="#263139", fg="#F4F5F2",
                     font=("Avenir Next", 9), padx=8, pady=4).pack()
            popup.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + 30}")
            widget._tooltip_window = popup
            widget._tooltip_after = None

        def hide(_event=None):
            if widget._tooltip_after:
                self.root.after_cancel(widget._tooltip_after)
                widget._tooltip_after = None
            if widget._tooltip_window:
                widget._tooltip_window.destroy()
                widget._tooltip_window = None

        def schedule(_event=None):
            hide()
            widget._tooltip_after = self.root.after(550, show)

        widget.bind("<Enter>", schedule, add="+")
        widget.bind("<Leave>", hide, add="+")

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
            layer.setCornerRadius_(min(44, self.height / 2))
            layer.setMasksToBounds_(True)
            glow = GREEN if not self.paused else BLUE
            layer.setBorderWidth_(1.2)
            layer.setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
                int(glow[1:3], 16) / 255,
                int(glow[3:5], 16) / 255,
                int(glow[5:7], 16) / 255,
                0.55,
            ).CGColor())
            layer.setShadowColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.38, 0.72, 0.96, 0.55,
            ).CGColor())
            layer.setShadowOffset_((0, -3))
            layer.setShadowRadius_(22)
            layer.setShadowOpacity_(0.6)
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
        width = round(280 + (self.width - 280) * eased)
        height = round(76 + (self.height - 76) * eased)
        screen_width = self.root.winfo_screenwidth()
        x = (screen_width - width) // 2
        self.root.geometry(f"{width}x{height}+{x}+8")
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
    parser.add_argument("--size", type=int, default=25)
    parser.add_argument("--width", type=int, default=680)
    parser.add_argument("--height", type=int, default=250)
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
