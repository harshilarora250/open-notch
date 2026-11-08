#!/usr/bin/env python3
"""Open Notch's titled script library and launcher."""

import argparse
import os
import signal
import subprocess
import sys
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

from notes_store import NOTES_FILE, NoteStore

HERE = Path(__file__).resolve().parent
PROMPTER_SCRIPT = HERE / "prompter.py"

BG = "#090B0E"
SIDEBAR = "#101318"
PANEL = "#12161B"
MUTED = "#929BA5"
ACCENT = "#4B91D5"
PROMPTER_LOG = NOTES_FILE.parent / "prompter.log"


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
            sidebar, text="OPEN NOTCH", bg=SIDEBAR, fg="#F2F6F6",
            font=("Helvetica Neue", 13, "bold"), anchor="w",
        ).pack(fill="x", padx=22, pady=(27, 7))
        tk.Label(
            sidebar, text="SPEAK WITH CLARITY", bg=SIDEBAR, fg=MUTED,
            font=("Helvetica Neue", 9), anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 31))
        tk.Label(
            sidebar, text="●   Scripts", bg="#1A2633", fg="#DCEBFA",
            font=("Helvetica Neue", 11, "bold"), anchor="w", padx=13, pady=11,
        ).pack(fill="x", padx=11)
        tk.Label(
            sidebar, text="LOCAL LIBRARY", bg=SIDEBAR, fg="#737D87",
            font=("Avenir Next", 8, "bold"), anchor="w",
        ).pack(side="bottom", fill="x", padx=22, pady=(0, 7))
        tk.Label(
            sidebar, text="Saved on this Mac", bg=SIDEBAR, fg=MUTED,
            font=("Avenir Next", 9), anchor="w",
        ).pack(side="bottom", fill="x", padx=22, pady=(0, 23))

        browser = tk.Frame(shell, bg="#0E1116", width=276)
        browser.pack(side="left", fill="y", padx=(1, 0))
        browser.pack_propagate(False)
        browser_header = tk.Frame(browser, bg="#0E1116")
        browser_header.pack(fill="x", padx=18, pady=(27, 17))
        tk.Label(
            browser_header, text="Scripts", bg="#0E1116", fg="#F2F6F6",
            font=("Avenir Next", 18, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self.note_count = tk.Label(
            browser_header, text="0", bg="#18212B", fg=MUTED,
            font=("Helvetica Neue", 9), padx=8, pady=4,
        )
        self.note_count.pack(side="left", padx=(8, 0))
        self._button(browser_header, "+", self.new_note, primary=True).pack(
            side="right", padx=(8, 0),
        )

        search_shell = tk.Frame(
            browser, bg="#171C23", highlightthickness=1,
            highlightbackground="#242B34",
        )
        search_shell.pack(fill="x", padx=14, pady=(0, 15))
        tk.Label(
            search_shell, text="Search", bg="#171C23", fg=MUTED,
            font=("Helvetica Neue", 10),
        ).pack(side="left", padx=(11, 5), pady=9)
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(
            search_shell, textvariable=self.search_var, bg="#171C23", fg="#E5E8EB",
            insertbackground="#FFFFFF", relief="flat", bd=0,
            font=("Avenir Next", 10),
        )
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=9)
        self.search_var.trace_add("write", lambda *_: self._refresh_notes(self.selected_id))

        self.notes_canvas = tk.Canvas(
            browser, bg="#0E1116", bd=0, highlightthickness=0,
        )
        self.notes_canvas.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self.notes_inner = tk.Frame(self.notes_canvas, bg="#0E1116")
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
        title_shell = tk.Frame(
            header, bg="#11151A", highlightthickness=1,
            highlightbackground="#252B33",
        )
        title_shell.pack(side="left", fill="x", expand=True)
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(
            title_shell, textvariable=self.title_var, bg="#11151A", fg="#F2F6F6",
            insertbackground="#FFFFFF", relief="flat", bd=0,
            font=("Helvetica Neue", 16, "bold"), highlightthickness=0,
        )
        self.title_entry.pack(fill="x", padx=16, pady=12)
        self.launch_button = self._button(
            header, "Present  →", self.launch, primary=True,
        )
        self.launch_button.pack(side="right", padx=(12, 0))

        editor = tk.Frame(
            content, bg=PANEL, highlightthickness=1,
            highlightbackground="#252B33",
        )
        editor.pack(fill="both", expand=True)
        script_header = tk.Frame(editor, bg=PANEL)
        script_header.pack(fill="x", padx=24, pady=(19, 6))
        tk.Label(
            script_header, text="SCRIPT CONTENT", bg=PANEL, fg="#E4E8ED",
            font=("Helvetica Neue", 11, "bold"), anchor="w",
        ).pack(side="left")
        self.editor_count = tk.Label(
            script_header, text="0 words", bg=PANEL, fg=MUTED,
            font=("Helvetica Neue", 9), anchor="e",
        )
        self.editor_count.pack(side="right")
        self.body = tk.Text(
            editor, wrap="word", bg=PANEL, fg="#E7EAED",
            insertbackground="#FFFFFF", selectbackground="#31526A",
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

    def _button(self, parent, label, command, primary=False):
        base_bg = ACCENT if primary else "#24292E"
        hover_bg = "#68A8E8" if primary else "#343B44"
        base_fg = "#07131A" if primary else "#E5E8EB"
        button = tk.Label(
            parent, text=label, bg=base_bg, fg=base_fg,
            relief="flat", bd=0, highlightthickness=0,
            font=("Helvetica Neue", 10, "bold"), cursor="hand2",
            padx=14, pady=9,
        )
        button.bind("<Button-1>", lambda _event: command() if button.cget("state") != "disabled" else None)
        button.bind("<Enter>", lambda _event: button.configure(bg=hover_bg)
                    if button.cget("state") != "disabled" else None)
        button.bind("<Leave>", lambda _event: button.configure(bg=base_bg))
        return button

    def _set_editor_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.title_entry.configure(state=state)
        self.body.configure(state=state)
        self.save_button.configure(state=state)
        self.delete_button.configure(state=state)
        self.launch_button.configure(state=state)

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
            card_bg = "#1B2A39" if selected else "#141A21"
            card = tk.Frame(
                self.notes_inner, bg=card_bg, highlightthickness=1,
                highlightbackground="#35516C" if selected else "#222A34",
                cursor="hand2",
            )
            card.pack(fill="x", padx=4, pady=(0, 9))
            title = tk.Label(
                card, text=note["title"].strip() or "Untitled script",
                bg=card_bg, fg="#F2F6F8", font=("Helvetica Neue", 11, "bold"),
                anchor="w", justify="left", wraplength=220,
            )
            title.pack(fill="x", padx=12, pady=(11, 4))
            preview = " ".join(note["body"].split())
            if len(preview) > 76:
                preview = preview[:73].rstrip() + "…"
            excerpt = tk.Label(
                card, text=preview or "No script text yet",
                bg=card_bg, fg="#AEB8C4", font=("Helvetica Neue", 9),
                anchor="w", justify="left", wraplength=220,
            )
            excerpt.pack(fill="x", padx=12, pady=(0, 8))
            try:
                updated = datetime.fromisoformat(note["updated_at"]).strftime("%b %d")
            except (KeyError, ValueError):
                updated = ""
            count = len(note["body"].split())
            meta = tk.Label(
                card, text=f"{count} words  ·  {updated}" if updated else f"{count} words",
                bg=card_bg, fg="#778493", font=("Helvetica Neue", 8), anchor="w",
            )
            meta.pack(fill="x", padx=12, pady=(0, 11))
            for widget in (card, title, excerpt, meta):
                widget.bind("<Button-1>", lambda _event, note_id=note["id"]: self._on_select(note_id))
                widget.bind("<MouseWheel>", self._scroll_notes)
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
