#!/usr/bin/env python3
"""Open Notch's titled script library and launcher."""

import argparse
import os
import signal
import subprocess
import sys
import math
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

from notes_store import NOTES_FILE, NoteStore

HERE = Path(__file__).resolve().parent
PROMPTER_SCRIPT = HERE / "prompter.py"

BG = "#000000"
SIDEBAR = "#070707"
BROWSER = "#090909"
PANEL = "#101010"
MUTED = "#929292"
PROMPTER_LOG = NOTES_FILE.parent / "prompter.log"


def _rounded_points(x1, y1, x2, y2, radius):
    points = []
    for center_x, center_y, start in (
        (x1 + radius, y1 + radius, 180),
        (x2 - radius, y1 + radius, 270),
        (x2 - radius, y2 - radius, 0),
        (x1 + radius, y2 - radius, 90),
    ):
        for step in range(7):
            angle = math.radians(start + step * 15)
            points.extend((center_x + radius * math.cos(angle),
                           center_y + radius * math.sin(angle)))
    return points


class NotchHome:
    def __init__(self, args):
        self.args = args
        self.root = tk.Tk()
        self.root.title("Open Notch")
        self.root.geometry("1120x740")
        self.root.minsize(900, 580)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Command-q>", self.close)
        if sys.platform == "darwin":
            try:
                self.root.createcommand("tk::mac::Quit", self.close)
            except tk.TclError:
                pass
        self.root.bind("<Command-s>", lambda _e: self.save_current())
        self.root.bind("<Command-n>", lambda _e: self.new_note())
        self.root.bind("<Command-Return>", lambda _e: self.launch())

        try:
            self.store = NoteStore()
        except ValueError as exc:
            messagebox.showerror("Could not open notes", str(exc), parent=self.root)
            self.root.destroy()
            raise

        self.selected_id = None
        self.active_process = None
        self._build_ui()
        self._refresh_notes()
        if self.store.notes:
            self._select_id(self.store.notes[0]["id"])
        else:
            self._set_editor_enabled(False)
            self.status.configure(text="Create your first script to get started")

    def _build_ui(self):
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=18, pady=18)

        sidebar = tk.Frame(shell, bg=SIDEBAR, width=176)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar, text="OPEN NOTCH", bg=SIDEBAR, fg="#FFFFFF",
            font=("Helvetica Neue", 13, "bold"), anchor="w",
        ).pack(fill="x", padx=22, pady=(27, 7))
        tk.Frame(sidebar, bg="#292929", height=1).pack(
            fill="x", padx=20, pady=(8, 23),
        )
        tk.Label(
            sidebar, text="●   Scripts", bg="#202020", fg="#FFFFFF",
            font=("Helvetica Neue", 11, "bold"), anchor="w", padx=13, pady=11,
        ).pack(fill="x", padx=11)
        tk.Label(
            sidebar, text="Private · saved on this Mac", bg=SIDEBAR, fg=MUTED,
            font=("Helvetica Neue", 9), anchor="w", justify="left", wraplength=130,
        ).pack(side="bottom", fill="x", padx=20, pady=(0, 22))

        browser = tk.Frame(shell, bg=BROWSER, width=276)
        browser.pack(side="left", fill="y", padx=(1, 0))
        browser.pack_propagate(False)
        browser_header = tk.Frame(browser, bg=BROWSER)
        browser_header.pack(fill="x", padx=18, pady=(27, 17))
        tk.Label(
            browser_header, text="Scripts", bg=BROWSER, fg="#FFFFFF",
            font=("Helvetica Neue", 18, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self.note_count = tk.Label(
            browser_header, text="0", bg="#202020", fg=MUTED,
            font=("Helvetica Neue", 9), padx=8, pady=4,
        )
        self.note_count.pack(side="left", padx=(8, 0))
        self._button(browser_header, "+", self.new_note).pack(
            side="right", padx=(8, 0),
        )

        search_shell = tk.Canvas(
            browser, bg=BROWSER, height=38, highlightthickness=0,
        )
        search_shell.pack(fill="x", padx=14, pady=(0, 15))
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(
            search_shell, textvariable=self.search_var, bg="#171717", fg="#FFFFFF",
            insertbackground="#FFFFFF", relief="flat", bd=0,
            font=("Helvetica Neue", 10), highlightthickness=0,
        )
        search_window = search_shell.create_window(
            70, 19, window=search_entry, anchor="w", width=150,
        )
        search_shell.create_text(
            14, 19, text="Search", fill=MUTED,
            font=("Helvetica Neue", 10), anchor="w", tags="search-label",
        )

        def layout_search(event):
            search_shell.delete("surface")
            search_shell.create_polygon(
                _rounded_points(1, 1, event.width - 1, 37, 17), smooth=True,
                splinesteps=20, fill="#171717", outline="#303030", width=1,
                tags="surface",
            )
            search_shell.tag_lower("surface")
            search_shell.coords("search-label", 14, 19)
            search_shell.coords(search_window, 70, 19)
            search_shell.itemconfigure(search_window, width=max(40, event.width - 82))

        search_shell.bind("<Configure>", layout_search)
        self.search_var.trace_add("write", lambda *_: self._refresh_notes(self.selected_id))

        self.notes_canvas = tk.Canvas(
            browser, bg=BROWSER, bd=0, highlightthickness=0,
        )
        self.notes_canvas.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self.notes_inner = tk.Frame(self.notes_canvas, bg=BROWSER)
        self.notes_window = self.notes_canvas.create_window(
            (0, 0), window=self.notes_inner, anchor="nw",
        )
        self.notes_inner.bind(
            "<Configure>",
            lambda _event: self.notes_canvas.configure(
                scrollregion=self.notes_canvas.bbox("all"),
            ),
        )
        self.notes_canvas.bind(
            "<Configure>",
            lambda event: self.notes_canvas.itemconfigure(
                self.notes_window, width=event.width,
            ),
        )
        self.notes_canvas.bind(
            "<MouseWheel>",
            lambda event: self.notes_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"),
        )

        content = tk.Frame(shell, bg=BG)
        content.pack(side="left", fill="both", expand=True, padx=(25, 15))
        header = tk.Frame(content, bg=BG)
        header.pack(fill="x", pady=(9, 20))
        title_shell = tk.Canvas(header, bg=BG, height=52, highlightthickness=0)
        title_shell.pack(side="left", fill="x", expand=True)
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(
            title_shell, textvariable=self.title_var, bg="#111111", fg="#FFFFFF",
            insertbackground="#FFFFFF", relief="flat", bd=0,
            font=("Helvetica Neue", 16, "bold"), highlightthickness=0,
        )
        title_window = title_shell.create_window(
            17, 26, window=self.title_entry, anchor="w", width=500,
        )

        def layout_title(event):
            title_shell.delete("surface")
            title_shell.create_polygon(
                _rounded_points(1, 1, event.width - 1, 51, 14), smooth=True,
                splinesteps=20, fill="#111111", outline="#303030", width=1,
                tags="surface",
            )
            title_shell.tag_lower("surface")
            title_shell.coords(title_window, 17, 26)
            title_shell.itemconfigure(title_window, width=max(80, event.width - 34))

        title_shell.bind("<Configure>", layout_title)
        self.launch_button = self._button(
            header, "Present  →", self.launch,
        )
        self.launch_button.pack(side="right", padx=(12, 0))

        editor_surface = tk.Canvas(content, bg=BG, highlightthickness=0)
        editor_surface.pack(fill="both", expand=True)
        editor = tk.Frame(editor_surface, bg=PANEL)
        editor_window = editor_surface.create_window(
            5, 5, window=editor, anchor="nw", width=700, height=500,
        )

        def layout_editor(event):
            editor_surface.delete("surface")
            editor_surface.create_polygon(
                _rounded_points(1, 1, event.width - 1, event.height - 1, 19),
                smooth=True, splinesteps=24, fill=PANEL,
                outline="#303030", width=1, tags="surface",
            )
            editor_surface.tag_lower("surface")
            editor_surface.coords(editor_window, 5, 5)
            editor_surface.itemconfigure(
                editor_window, width=max(100, event.width - 10),
                height=max(100, event.height - 10),
            )

        editor_surface.bind("<Configure>", layout_editor)
        script_header = tk.Frame(editor, bg=PANEL)
        script_header.pack(fill="x", padx=24, pady=(19, 6))
        tk.Label(
            script_header, text="Script", bg=PANEL, fg="#F0F0F0",
            font=("Helvetica Neue", 11, "bold"), anchor="w",
        ).pack(side="left")
        self.editor_count = tk.Label(
            script_header, text="0 words", bg=PANEL, fg=MUTED,
            font=("Helvetica Neue", 9), anchor="e",
        )
        self.editor_count.pack(side="right")
        self.body = tk.Text(
            editor, wrap="word", bg=PANEL, fg="#EEEEEE",
            insertbackground="#FFFFFF", selectbackground="#555555",
            relief="flat", bd=0, highlightthickness=0,
            font=("Helvetica Neue", 14), padx=24, pady=17, spacing1=7,
        )
        self.body.pack(fill="both", expand=True)
        self.body.bind("<KeyRelease>", self._update_count)

        footer = tk.Frame(content, bg=BG)
        footer.pack(fill="x", pady=(12, 0))
        self.status = tk.Label(
            footer, text="Saved locally", bg=BG, fg=MUTED,
            font=("Avenir Next", 10),
        )
        self.status.pack(side="left", fill="x", expand=True)
        self.delete_button = self._button(footer, "Delete script", self.delete_note)
        self.delete_button.pack(side="right", padx=(8, 0))
        self.save_button = self._button(footer, "Save", self.save_current)
        self.save_button.pack(side="right")

    def _button(self, parent, label, command):
        base_bg = "#FFFFFF"
        hover_bg = "#BDBDBD"
        base_fg = "#000000"
        font = tkfont.Font(root=parent, family="Helvetica Neue", size=10, weight="bold")
        button = tk.Canvas(
            parent, width=font.measure(label) + 28, height=font.metrics("linespace") + 20,
            bg=parent.cget("bg"), highlightthickness=0, bd=0, cursor="hand2",
        )
        button.enabled = True
        button.fill_color = base_bg
        shape = button.create_polygon(
            _rounded_points(1, 1, font.measure(label) + 27, font.metrics("linespace") + 19, 9),
            smooth=True, splinesteps=20, fill=base_bg, outline="",
        )
        text = button.create_text(
            (font.measure(label) + 28) / 2, (font.metrics("linespace") + 20) / 2,
            text=label, fill=base_fg, font=font,
        )
        button.bind("<Button-1>", lambda _event: command() if button.enabled else None)
        button.bind("<Enter>", lambda _event: button.itemconfigure(shape, fill=hover_bg)
                    if button.enabled else None)
        button.bind("<Leave>", lambda _event: button.itemconfigure(shape, fill=button.fill_color))

        def set_enabled(enabled):
            button.enabled = enabled
            button.fill_color = base_bg if enabled else "#444444"
            button.itemconfigure(shape, fill=button.fill_color)
            button.itemconfigure(text, fill=base_fg if enabled else "#AAAAAA")
            button.configure(cursor="hand2" if enabled else "arrow")

        button.set_enabled = set_enabled
        return button

    def _set_editor_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.title_entry.configure(state=state)
        self.body.configure(state=state)
        self.save_button.set_enabled(enabled)
        self.delete_button.set_enabled(enabled)
        self.launch_button.set_enabled(enabled)

    def _refresh_notes(self, selected_id=None):
        self._refreshing_notes = True
        query = self.search_var.get().strip().casefold() if hasattr(self, "search_var") else ""
        self.visible_notes = [
            note for note in self.store.notes
            if not query or query in note["title"].casefold() or query in note["body"].casefold()
        ]
        for child in self.notes_inner.winfo_children():
            child.destroy()
        for note in self.visible_notes:
            selected = note["id"] == selected_id
            card_bg = "#242424" if selected else "#111111"
            card = tk.Canvas(
                self.notes_inner, height=112, bg=BROWSER,
                highlightthickness=0, bd=0, cursor="hand2",
            )
            card.pack(fill="x", padx=4, pady=(0, 9))
            preview = " ".join(note["body"].split())
            if len(preview) > 76:
                preview = preview[:73].rstrip() + "…"
            try:
                updated = datetime.fromisoformat(note["updated_at"]).strftime("%b %d")
            except (KeyError, ValueError):
                updated = ""
            count = len(note["body"].split())
            title_text = note["title"].strip() or "Untitled script"
            meta_text = f"{count} WORDS  ·  {updated}" if updated else f"{count} WORDS"

            def draw_card(event, canvas=card, fill=card_bg, active=selected,
                          title=title_text, excerpt=preview or "No script text yet",
                          meta=meta_text):
                canvas.delete("all")
                canvas.create_polygon(
                    _rounded_points(1, 1, event.width - 1, 111, 11),
                    smooth=True, splinesteps=20, fill=fill,
                    outline="#777777" if active else "#292929", width=1,
                )
                canvas.create_text(
                    14, 12, text=title, fill="#F4F4F4",
                    font=("Helvetica Neue", 11, "bold"), anchor="nw",
                    width=max(100, event.width - 28),
                )
                canvas.create_text(
                    14, 39, text=excerpt, fill="#B8B8B8",
                    font=("Helvetica Neue", 9), anchor="nw",
                    width=max(100, event.width - 28),
                )
                canvas.create_text(
                    14, 91, text=meta, fill="#858585",
                    font=("Helvetica Neue", 8), anchor="nw",
                )

            card.bind("<Configure>", draw_card)
            card.bind("<Button-1>", lambda _event, note_id=note["id"]: self._on_select(note_id))
            card.bind("<MouseWheel>", self._scroll_notes)
        if hasattr(self, "note_count"):
            self.note_count.configure(text=str(len(self.store.notes)))
        self._refreshing_notes = False

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
        self.status.configure(text="Saved locally")
        self._update_count()

    def _scroll_notes(self, event):
        self.notes_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_select(self, note_id):
        if getattr(self, "_refreshing_notes", False):
            return
        if note_id != self.selected_id:
            self._save_current(silent=True)
            self._select_id(note_id)

    def _save_current(self, silent=False):
        note = self.store.get(self.selected_id) if self.selected_id else None
        if not note:
            return False
        title = self.title_var.get().strip() or "Untitled script"
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
        self.search_var.set("")
        note = self.store.create()
        self._refresh_notes(note["id"])
        self._select_id(note["id"])
        self.title_entry.focus_set()
        self.title_entry.selection_range(0, "end")

    def delete_note(self):
        note = self.store.get(self.selected_id) if self.selected_id else None
        if not note:
            return
        if not messagebox.askyesno(
            "Delete script", f"Delete ‘{note['title']}’?", parent=self.root,
        ):
            return
        self.store.delete(note["id"])
        self.selected_id = None
        self.search_var.set("")
        if self.store.notes:
            self._select_id(self.store.notes[0]["id"])
        else:
            self.title_var.set("")
            self.body.configure(state="normal")
            self.body.delete("1.0", "end")
            self._set_editor_enabled(False)
            self._refresh_notes()
            self.status.configure(text="Create your first script to get started")
            self._update_count()

    def _update_count(self, _event=None):
        count = len(self.body.get("1.0", "end-1c").split())
        label = f"{count} word{'s' if count != 1 else ''}"
        if hasattr(self, "editor_count"):
            self.editor_count.configure(text=label)

    def launch(self):
        note = self.store.get(self.selected_id) if self.selected_id else None
        if not note:
            return
        self._save_current(silent=True)
        note = self.store.get(self.selected_id)
        if not note["body"].strip():
            self.status.configure(text="Add script text before launching")
            return
        if self.active_process and self.active_process.poll() is None:
            self.status.configure(text="Presenter is already open")
            return
        command = [
            sys.executable, str(PROMPTER_SCRIPT), "--note-id", note["id"],
            "--lang", self.args.lang,
        ]
        try:
            PROMPTER_LOG.parent.mkdir(parents=True, exist_ok=True)
            with PROMPTER_LOG.open("w", encoding="utf-8") as log_file:
                self.active_process = subprocess.Popen(
                    command, cwd=str(HERE), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=log_file,
                    start_new_session=True,
                )
            self.status.configure(text=f"Presenter launched · {note['title']}")
            self.root.after(1200, self._check_presenter)
        except OSError as exc:
            self.status.configure(text="Could not launch presenter")
            messagebox.showerror("Could not launch", str(exc), parent=self.root)

    def _check_presenter(self):
        if not self.root.winfo_exists():
            return
        if not self.active_process:
            return
        result = self.active_process.poll()
        if result is None:
            self.root.after(1200, self._check_presenter)
        else:
            self.active_process = None
            if result == 0:
                message = "Presenter closed"
            else:
                message = "Presenter failed to start"
                try:
                    details = PROMPTER_LOG.read_text(encoding="utf-8").strip()
                except OSError:
                    details = "See the presenter log in Application Support/Open Notch."
                if not details:
                    details = "The presenter exited without writing an error log."
                messagebox.showerror("Presenter failed to start", details[-2400:], parent=self.root)
            self.status.configure(text=message)

    def close(self, _event=None):
        self._save_current(silent=True)
        self._stop_presenter()
        self.root.destroy()

    def _stop_presenter(self):
        process = self.active_process
        self.active_process = None
        if not process or process.poll() is not None:
            return

        # The presenter and its Swift speech helper share the launch process group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
        try:
            process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            process.wait()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Open Notch script library")
    parser.add_argument("--lang", default="en-US",
                        help="speech locale used by the presenter, e.g. en-US")
    args = parser.parse_args()
    NotchHome(args).run()


if __name__ == "__main__":
    main()
