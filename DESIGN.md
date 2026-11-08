# Open Notch interface design

## Product shape

Open Notch has two separate Python apps:

- `notch.py` is the script library and editor. It keeps a normal macOS title bar and familiar window behavior.
- `prompter.py` is a separate, frameless presenter process. It stays near the camera and gives the script the entire visual focus.

The library is a quiet dark workspace. The presenter is a black, blue-lit capsule: long, spare, and readable at a glance. It should feel native to Open Notch instead of looking like a reskinned reference mockup.

## Reference for this pass

The user explicitly selected the scripts-and-editor reference as the library UI target. Follow its three-part hierarchy: a slim navigation rail, a searchable script list with title, excerpt, and word/date metadata cards, and a focused editor with the launch action near the title. Adapt the colors and controls to Open Notch; do not add recording, profile, copy, camera, or other features that do not exist. This is an explicit exception to the default originality rule in `AGENTS.md`.

The floating presenter remains its own minimal, text-first surface and should not inherit the library's navigation or toolbar.

## Palette

Return to Open Notch's original ink-and-blue identity:

| Purpose | Value |
| --- | --- |
| Library background | `#090B0E` |
| Library sidebar | `#101318` |
| Library editor surface | `#12161B` |
| Primary text | `#F5F5F7` |
| Muted text | `#929BA5` |
| Open Notch blue | `#4B91D5` |
| Presenter surface | `#000000` |
| Presenter script | `#FFFFFF` |
| Spoken script | `#6B6B6B` |
| Current word and edge | `#4B91D5` |

Keep the blue restrained: it marks the active word, voice-following state, and a faint capsule edge. Do not introduce the reference's pearl surface or green state color.

## Typography and shape

- Use Avenir Next for library headings, editor content, and the presenter script. Use only Tk-supported `normal` and `bold` weights.
- Use Helvetica Neue for small status text.
- Set the presenter script large and regular, with generous line spacing. The script is the only large element in the capsule.
- Keep the presenter strongly rounded, with a corner radius equal to half its height. The silhouette should read as a single horizontal pill, not a card.
- Use a fine blue edge and soft native shadow when AppKit is available. The presenter remains borderless without optional native styling.

## Layout and behavior

- Keep the library's native title bar. Use the three-part navigation, searchable script list, and editor hierarchy described above, with deliberate spacing and a clear launch action.
- Keep the presenter topmost, draggable, and separate from the library process. Quitting the library closes its launched presenter and speech helper.
- The presenter contains only script text and a compact status/audio cue. Show no camera, microphone, close, or settings buttons.
- Preserve keyboard controls: Space pauses/resumes, Up/Down nudges, R restarts, plus/minus changes text size, bracket keys change panel height, and Q/Esc closes.
- Close the presenter shortly after voice-following advances through the final script word. Resetting or moving back before the close delay expires cancels the close.
- Preserve local speech following and script persistence. Open Notch uses the microphone for voice following and never accesses the camera.
- Fit the presenter's width and height to the script's rendered text, within screen-aware minimum and maximum bounds. Short scripts use a compact capsule; long scripts expand until the cap and remain scrollable.
- Retain the short ease-out expansion from a compact pill into the reading capsule.

## Resilience

- Keep notes on-device and launch a saved note as a separate `prompter.py` process by note ID.
- Show useful startup errors from the presenter process in the launcher instead of silently swallowing them.
- Keep the launcher usable when AppKit styling is unavailable. Do not suggest that recording, camera access, or cloud features exist.
