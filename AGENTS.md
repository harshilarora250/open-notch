# Repository instructions

- Read `DESIGN.md` before changing either app's interface. Treat its window roles, visual tokens, and control behavior as requirements.
- Treat supplied visual references as mood and usability cues; do not reproduce them literally unless the user explicitly asks to follow a specific reference. Even then, adapt it to Open Notch's actual features and identity, and do not invent camera or recording capabilities.
- Keep the script library (`notch.py`) and floating presenter (`prompter.py`) as separate Python processes. The library owns note editing; the presenter owns the topmost overlay and speech following.
- Put note persistence in `notes_store.py`, shared by both entry points. Keep `listen.swift` as the on-device speech helper.
- The library keeps native macOS title chrome. The floating presenter is borderless and must not inherit the library's window style.
- Launch presenter processes with argument arrays (never shell command strings). Pass note IDs and shared configuration rather than copying source into generated scripts.
- Keep microphone and camera claims accurate. The current app uses the microphone for local speech following and does not access the camera.
- Preserve the existing manual controls and keyboard shortcuts when adjusting the presenter UI.
- Keep notes on-device. Do not add network services or telemetry.
- Update `README.md` when startup commands, dependencies, or app responsibilities change.
