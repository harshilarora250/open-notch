# Open Notch interface design

## Product shape

Open Notch has two separate Python apps:

- `notch.py` is the script library and editor. It keeps a normal macOS title bar and familiar window behavior.
- `prompter.py` is a separate, frameless presenter process. It stays near the camera and gives the script the entire visual focus.

The library is a quiet monochrome workspace. The presenter is a black capsule: long, spare, and readable at a glance. Use a deliberate grayscale range for hierarchy and keep the controls clear against the black surfaces.

## Reference for this pass

The user explicitly selected the scripts-and-editor reference as the library UI target. Follow its three-part hierarchy: a slim navigation rail, a searchable script list with title, excerpt, and word/date metadata cards, and a focused editor with the launch action near the title. Adapt the colors and controls to Open Notch; do not add recording, profile, copy, camera, or other features that do not exist. This is an explicit exception to the default originality rule in `AGENTS.md`.

The floating presenter remains its own minimal, text-first surface and should not inherit the library's navigation or toolbar.

## Palette

Use a monochrome black-and-white identity, following the supplied black canvas and rounded white-button references:

| Purpose | Value |
| --- | --- |
| Library background | `#000000` |
| Library sidebar | `#070707` |
| Library browser | `#090909` |
| Library editor surface | `#101010` |
| Primary text | `#FFFFFF` |
| Body text | `#EEEEEE` |
| Muted text | `#929292` |
| Primary button | `#FFFFFF` with black text |
| Button hover | `#BDBDBD` with black text |
| Field and card surfaces | `#111111`–`#242424` |
| Presenter surface | `#000000` |
| Presenter script | `#D6D6D6` |
| Current word and close control | `#FFFFFF` |
| Spoken script and status | `#777777`–`#A0A0A0` |
| Presenter edge and shadow | subtle neutral gray |

Keep all UI color within black, white, and neutral grays. Enabled actions are white with black labels and turn medium gray on hover. Disabled actions use darker gray and remain visually distinct. Preserve strong contrast for script text and status labels.

## Typography and shape

- Use Avenir Next for library headings, editor content, and the presenter script. Use only Tk-supported `normal` and `bold` weights.
- Use Helvetica Neue for small status text.
- Set the presenter script large and regular, with generous line spacing. The script is the only large element in the capsule.
- Keep the presenter strongly rounded, with a corner radius equal to half its height. The silhouette should read as a single horizontal pill, not a card. Show a small circular close affordance only while the pointer is over the presenter.
- Use rounded script cards, pill-like actions, and softened editor/search surfaces throughout the library. Avoid default square Tk button chrome.
- Use a fine neutral edge and soft gray native shadow when AppKit is available. The presenter remains borderless without optional native styling.

## Layout and behavior

- Keep the library's native title bar. Use the three-part navigation, searchable script list, and editor hierarchy described above, with deliberate spacing and a clear launch action.
- Keep the presenter topmost, draggable, and separate from the library process. Quitting the library closes its launched presenter and speech helper.
- The presenter contains script text, a compact status/audio cue, and a close control that appears on hover. Do not show camera, microphone, or settings controls.
- Preserve keyboard controls: Space pauses/resumes, Up/Down nudges, R restarts, plus/minus changes text size, bracket keys change panel height, and Q/Esc closes.
- Close the presenter shortly after voice-following advances through the final script word. Resetting or moving back before the close delay expires cancels the close.
- Preserve local speech following and script persistence. Open Notch uses the microphone for voice following and never accesses the camera.
- Fit the presenter's width and height to the script's rendered text, within screen-aware minimum and maximum bounds. Short scripts use a compact capsule; long scripts expand until the cap and remain scrollable.
- Retain the short ease-out expansion from a compact pill into the reading capsule.

## Resilience

- Keep notes on-device and launch a saved note as a separate `prompter.py` process by note ID.
- Show useful startup errors from the presenter process in the launcher instead of silently swallowing them.
- Keep the launcher usable when AppKit styling is unavailable. Do not suggest that recording, camera access, or cloud features exist.
