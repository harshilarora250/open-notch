# Open Notch

Open Notch has two separate Python apps:

- `notch.py` opens the titled script library. Create and edit scripts, then launch one in the floating presenter.
- `prompter.py` runs as a separate, frameless presenter process. Closing the library does not close an already launched presenter.

Notes are stored locally at `~/Library/Application Support/Open Notch/notes.json`.

## Start the library

```sh
python3 notch.py
```

## Start the presenter directly

```sh
python3 prompter.py my_script.txt
python3 prompter.py --clipboard
```

The library launches a saved note by ID, so scripts are not copied into temporary files or shell commands.

## Requirements

The first presenter launch compiles the on-device speech helper. Install the Xcode command line tools and PyObjC for native window masking, rounded corners, and screen-share hiding:

```sh
xcode-select --install
python3 -m pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz
```

The presenter still opens borderlessly without PyObjC; native corner masking and capture protection are optional enhancements when those packages are available.

## Presenter controls

- Click the microphone icon or press **Space** to pause/resume script following.
- Use the settings icon to change text size, panel height, or script position.
- **R** restarts the script; **Up/Down** nudge the position; **+/−** change text size; **Q/Esc** closes the presenter.
