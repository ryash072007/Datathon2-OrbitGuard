# Demo video

The 2:55 demo video is generated from code. Narrative scenes are HTML/SVG/canvas animations in `scenes/`. App scenes are the live OrbitGuard console on LinuxONE, driven by Playwright. Frames come from Chrome's screencast and are assembled with ffmpeg.

## Rebuild

Requires macOS (`say`), ffmpeg, Google Chrome, `frontend/node_modules`, and the SSH tunnel to the VM (`python3 scripts/linuxone.py tunnel ...`, app at http://127.0.0.1:8080).

```bash
NODE_PATH=$PWD/frontend/node_modules frontend/node_modules/.bin/esbuild video/scenes/lib.js \
  --bundle --format=iife --minify --outfile=video/out/lib.js --loader:.json=json
node video/tts.mjs                 # narration lines -> video/out/audio, with timings
node video/record.mjs              # all scenes; or name scenes: node video/record.mjs planning
node video/build.mjs               # -> video/out/OrbitGuard_demo.mp4
```

## Outputs (`video/out/`, not committed)

- `OrbitGuard_demo.mp4`: 1920×1080, 30 fps, with synthesised narration (macOS voice "Samantha") over a quiet ambient pad.
- `OrbitGuard_demo_music_only.mp4`: the same picture with music only. Use it to record a teammate's voice over the top, following `narration.mjs` or the subtitles.
- `OrbitGuard_demo.srt`: subtitles. Upload them alongside the video.
- `poster.png`: thumbnail.

## Editing

- Words: `narration.mjs`. Every number must match `docs/RESULTS.md`.
- Timing: on-screen actions are cued to the start of each narration line (`record.mjs`, `cues`). Re-run all three steps after a text change.
- The terminal scene replays real VM output captured on 17 Oct 2026 (`terminal.json`). The 37-candidate grid in the solution scene uses the real LinuxONE screening result. The alert ticker in the problem scene is illustrative.
