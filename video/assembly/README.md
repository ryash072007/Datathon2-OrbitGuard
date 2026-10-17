# Screen-recording pipeline

Records one MP4 per dashboard shot, at exactly the narration duration, into `video/out/shots/<shot>.mp4`
(1920x1080, 60 fps, H.264 yuv420p, crf 16). `linuxone_terminal` and `end_card` are produced separately.

## Setup (once)

```
py -3.12 -m venv video/.venv-rec
video/.venv-rec/Scripts/pip install playwright      # uses the installed Edge, no browser download
```

Needs ffmpeg on PATH and Edge installed. The dashboard needs cached results (`scripts/demo.py`).

## Run

```
video/.venv-rec/Scripts/python video/record.py                       # all shots
video/.venv-rec/Scripts/python video/record.py --only dodge replay   # some shots
video/.venv-rec/Scripts/python video/record.py --durations video/out/vo/durations.json
```

`record.py` starts `.venv/Scripts/python -m legacy.flask_dashboard.run` itself (or reuses a server already on :8080) and,
if it started it, stops it afterwards, killing only that PID after checking its command line contains `legacy.flask_dashboard.run`.

**Do not touch the mouse, move windows or let notifications appear while it records**: it captures the real screen.
Leave the screen on and unlocked.

Durations: default is narration words / 2.5; with `--durations`, each shot gets the summed narration
duration of its segments + 0.4 s. The file may map segment id (`s01`) or shot name to seconds. If a shot's
actions are longer than its duration they are compressed (never below x0.45) and anything left is cut; if
shorter, the last frame is held.

## Editing shots (`shots.json`)

Per shot: `actions` run in order, optionally `dur`. Types: `goto` (`url`, `ready` selector; loaded and
settled *before* recording starts), `scroll` (`to`, `ms`, `offset`; eased JS animation, `ms: 0` = instant and
done pre-roll), `wait`, `hover`, `click` (smooth mouse path, `sel`, `nth`), `drag` / `wheel` (synthetic
pointer/wheel events on a canvas, eased, to rotate/zoom the globes), `slider` (sets the debris-time range
input through its steps), `js`.

## Capture method and why

Chosen: **ffmpeg `gdigrab` of the desktop region 0,0 1920x1080 at 60 fps while Playwright drives a headed Edge in real
fullscreen.**

- Headed Edge (`channel="msedge"`) uses the RTX GPU, so the WebGL globes are smooth. Fullscreen (via CDP
  `Browser.setWindowBounds`) removes tabs, address bar and title bar; `--force-device-scale-factor=1` plus a
  1920x1080 emulated viewport gives exactly 1920x1080 CSS px at 1:1 in the top-left of the 2560x1440 screen,
  so cropping that region is exact. The Windows 125% scaling does not matter because of the forced factor.
- Cursor: gdigrab `-draw_mouse 0`, plus `cursor:none` and hidden scrollbars injected into the page. Playwright's
  mouse is synthetic anyway, so only hover/click effects show.
- Capture is encoded fast (crf 12, veryfast) to a temp MKV, then trimmed (head slack) and re-encoded
  `crf 16 -preset slow`, padded with the last frame to the exact duration.
- Why not the alternatives: Playwright `record_video` is VP8 at a fixed low bitrate and 25 fps, which blurs the
  text and globe. Per-frame `page.screenshot` is not deterministic here because the globes and counters animate in
  real time, and each screenshot takes ~100 ms, so it would stutter. gdigrab works because the 2560x1440 monitor is
  bigger than 1080p.
- If the monitor were smaller than 1080p, fall back to `record_video` with `record_video_size=1920x1080`.
