"""Shared local storage for the Open Notch launcher and presenter."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

NOTES_FILE = Path.home() / "Library" / "Application Support" / "Open Notch" / "notes.json"


class NoteStore:
    """Small JSON-backed library of presentation scripts."""

    def __init__(self, path=NOTES_FILE):
        self.path = Path(path)
        if not self.path.exists():
            self.notes = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read saved notes at {self.path}: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError(f"Saved notes at {self.path} must contain a JSON list.")
        self.notes = [
            note for note in data
            if isinstance(note, dict)
            and isinstance(note.get("id"), str)
            and isinstance(note.get("title"), str)
            and isinstance(note.get("body"), str)
        ]

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
