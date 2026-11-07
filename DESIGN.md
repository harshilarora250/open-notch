# Open Notch interface design

## Product shape

Open Notch is two desktop windows with separate jobs:

- `notch.py` is the script library and editor. It is a normal macOS window with the native title bar, resizing, and familiar window behavior.
- `prompter.py` is a separate process launched by the library. It is a compact, frameless floating surface that stays near the camera while the user presents.

The library should feel like a quiet writing studio. The prompter should feel like a soft, luminous glass island. Keep the editor calm so the floating surface remains the memorable part of the product.

## Visual references

Use the three supplied references as the source for the prompter's shape and hierarchy:

- A large, deeply rounded capsule with a pale pearl surface and a cool blue edge glow.
- Large, high-contrast script text with the spoken portion receding to soft gray.
- A compact top control row: close on the left; camera status, microphone status, and settings on the right.
- A small audio activity/status cue below the script. Use a faint green accent only for an active or ready state.
- The compact state is a short pill. Expansion grows smoothly into the reading surface without changing its visual language.

Do not copy decorative browser chrome from the references. Keep the prompter free of a native title bar, Dock presence, and unnecessary labels.

## Tokens

| Purpose | Value |
| --- | --- |
| Library background | `#090B0E` |
| Library sidebar | `#101318` |
| Library editor surface | `#12161B` |
| Primary text | `#F5F5F7` |
| Muted text | `#929BA5` |
| Open Notch accent | `#5AB8F7` |
| Prompter pearl | `#F4F5F2` |
| Prompter script | `#171B1D` |
| Spoken text | `#A1A8AA` |
| Prompter blue edge | `#83BFFF` |
| Active audio green | `#82DCA0` |

Use Avenir Next for the library's display and interface text. Use a system sans face for dense utility labels and the prompter body. The script should stay visually dominant.

## Layout and behavior

- Keep the library's native title bar. Use a clear two-column library/editor layout, one strong primary action, and restrained secondary actions.
- Keep the floating prompter borderless and topmost. Drag from its surface, close from the left control, and keep voice-following/manual controls reachable without obscuring the script.
- Controls must represent working behavior. The microphone control toggles voice following. Settings exposes existing text-size and panel-size preferences. The camera symbol is a status indicator only; Open Notch does not access a camera.
- Preserve keyboard shortcuts and the existing script-following behavior.
- Save notes locally and launch a selected note as a separate `prompter.py` process. Closing the library must not implicitly close an already launched prompter.
- Keep spacing generous, corners strongly rounded on the prompter, and borders/shadows soft. Avoid hard black panels, heavy dividers, gradients with saturated color, and control rows that compete with the script.

## Motion and states

- Use the existing short ease-out expansion from a compact pill to the reading panel.
- Use a restrained blue glow while idle and a quiet green accent while the microphone is active.
- Keep pause, following, error, and end-of-script states legible without moving the script unexpectedly.

## Accessibility and resilience

- Give icon controls tooltips and accessible text labels where Tk supports them.
- Preserve keyboard equivalents for close, pause/resume, restart, nudge, and text sizing.
- The main launcher must remain usable when optional AppKit styling is unavailable. The prompter must still be frameless; optional native masking may enhance its corners and shadow.
- Do not make camera access, recording, cloud services, or unrelated product features appear available when they are not implemented.
