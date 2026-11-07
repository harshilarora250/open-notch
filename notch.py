#!/usr/bin/env python3
"""Open Notch's titled script library and launcher."""

import argparse
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
        self.root.geometry("980x650")
        self.root.minsize(820, 540)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
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
        shell.pack(fill="both", expand=True, padx=22, pady=22)

        sidebar = tk.Frame(shell, bg=SIDEBAR, width=258)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar, text="OPEN NOTCH", bg=SIDEBAR, fg="#F2F6F6",
            font=("Avenir Next", 12, "bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(22, 4))
        tk.Label(
            sidebar, text="Presentation scripts", bg=SIDEBAR, fg=MUTED,
            font=("Avenir Next", 10), anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 18))
        self._button(sidebar, "+  New script", self.new_note, primary=True).pack(
            fill="x", padx=16, pady=(0, 22),
        )
        tk.Label(
            sidebar, text="LIBRARY", bg=SIDEBAR, fg="#737D87",
            font=("Avenir Next", 9, "bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 9))
        self.note_list = tk.Listbox(
            sidebar, bg=SIDEBAR, fg="#D8DDE1", selectbackground="#263B4D",
            selectforeground="#FFFFFF", activestyle="none", relief="flat",
            borderwidth=0, highlightthickness=0, font=("Avenir Next", 12),
            exportselection=False,
        )
        self.note_list.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self.note_list.bind("<<ListboxSelect>>", self._on_select)

        content = tk.Frame(shell, bg=BG)
        content.pack(side="left", fill="both", expand=True, padx=(26, 2))
        header = tk.Frame(content, bg=BG)
        header.pack(fill="x", pady=(4, 20))
        title_group = tk.Frame(header, bg=BG)
        title_group.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_group, text="Your scripts", bg=BG, fg="#F2F6F6",
            font=("Avenir Next", 26, "bold"), anchor="w",
        ).pack(fill="x")
        tk.Label(
            title_group, text="Prepare a script, then keep it close while you present.",
            bg=BG, fg=MUTED, font=("Avenir Next", 11), anchor="w",
        ).pack(fill="x", pady=(3, 0))
        self.launch_button = self._button(
            header, "Launch presenter  →", self.launch, primary=True,
        )
        self.launch_button.pack(side="right", padx=(12, 0), pady=(8, 0))

        editor = tk.Frame(
            content, bg=PANEL, highlightthickness=1,
            highlightbackground="#282E34",
        )
        editor.pack(fill="both", expand=True)
        tk.Label(
            editor, text="SCRIPT TITLE", bg=PANEL, fg=MUTED,
            font=("Avenir Next", 9, "bold"), anchor="w",
        ).pack(fill="x", padx=22, pady=(19, 7))
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(
            editor, textvariable=self.title_var, bg=PANEL, fg="#F2F6F6",
            insertbackground="#FFFFFF", relief="flat", bd=0,
            font=("Avenir Next", 18, "bold"),
        )
        self.title_entry.pack(fill="x", padx=22, pady=(0, 16))
        tk.Frame(editor, bg="#292F35", height=1).pack(fill="x", padx=22)
        self.body = tk.Text(
            editor, wrap="word", bg=PANEL, fg="#E7EAED",
            insertbackground="#FFFFFF", selectbackground="#31526A",
            relief="flat", bd=0, highlightthickness=0,
            font=("Avenir Next", 13), padx=22, pady=18, spacing1=3,
        )
        self.body.pack(fill="both", expand=True)
        self.body.bind("<KeyRelease>", self._update_count)

        footer = tk.Frame(content, bg=BG)
        footer.pack(fill="x", pady=(14, 0))
        self.count_label = tk.Label(
            footer, text="0 words", bg=BG, fg=MUTED,
            font=("Avenir Next", 10), anchor="w",
        )
        self.count_label.pack(side="left", fill="x", expand=True)
        self.status = tk.Label(
            footer, text="Saved locally", bg=BG, fg=MUTED,
            font=("Avenir Next", 10),
        )
        self.status.pack(side="left", padx=(0, 12))
        self.delete_button = self._button(footer, "Delete", self.delete_note)
        self.delete_button.pack(side="right", padx=(8, 0))
        self.save_button = self._button(footer, "Save", self.save_current)
        self.save_button.pack(side="right")

    def _button(self, parent, label, command, primary=False):
        return tk.Button(
            parent, text=label, command=command,
            bg=ACCENT if primary else "#24292E",
            fg="#07131A" if primary else "#E5E8EB",
            activebackground="#87CCFA" if primary else "#383E44",
            activeforeground="#07131A" if primary else "#FFFFFF",
            relief="flat", bd=0, highlightthickness=0,
            font=("Avenir Next", 10, "bold"), cursor="arrow",
            padx=14, pady=9,
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
            self.note_list.insert("end", note["title"].strip() or "Untitled script")
            if note["id"] == selected_id:
                row = self.note_list.size() - 1
                self.note_list.selection_set(row)
                self.note_list.activate(row)

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

    def _on_select(self, _event=None):
        selected = self.note_list.curselection()
        if not selected:
            return
        note = self.store.notes[selected[0]]
        if note["id"] != self.selected_id:
            self._save_current(silent=True)
            self._select_id(note["id"])

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
        self.count_label.configure(text=f"{count} word{'s' if count != 1 else ''}")

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

    def close(self):
        self._save_current(silent=True)
        # The presenter is a separate app process and is intentionally left open.
        self.root.destroy()

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
