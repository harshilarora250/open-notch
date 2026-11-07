# Open Notch

A small macOS voice-following teleprompter.

## Start

```sh
python3 notch.py
```

This opens the home screen. Create a note, write or paste a script, save it, then choose **Launch teleprompter**. Notes are stored locally at `~/Library/Application Support/Open Notch/notes.json`.

You can still open a text file directly:

```sh
python3 notch.py my_script.txt
python3 notch.py --clipboard
```

The first launch compiles the on-device speech helper. Install the Xcode command line tools and PyObjC if needed:

```sh
xcode-select --install
python3 -m pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz
```

## Teleprompter controls

- **Pause** pauses voice following; **Resume** starts it again.
- **−6 / +6** move the script position manually.
- **A− / A+** change the script text size.
- **Restart** returns to the start of the note.
- Keyboard shortcuts: Space, Up/Down, R, +/−, Q/Esc.
