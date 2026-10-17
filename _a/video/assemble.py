"""Assemble the demo video: title + 10 narrated segments, crossfades, callouts, captions, music bed, loudness.

Run (needs Playwright for the cards, so use the recorder venv):
    video/.venv-rec/Scripts/python.exe video/assemble.py [--force-cards] [--no-music]
Output: video/out/final/datathon2_demo.mp4 (+ .srt/.ass). Missing narration/shots are replaced by labelled placeholders.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import build_cards as bc
import captions

ROOT = bc.ROOT
OUT = bc.OUT
WORK = OUT / "work"
FINAL = OUT / "final"
SHOTS = OUT / "shots"
MUSIC = ROOT / "music" / "calm_ambient_2.mp3"

FPS = 30
XF = 0.4          # crossfade
LEAD = 0.3        # narration starts this long after its segment starts (inside the crossfade-in)
TAIL = 0.4        # padding after narration
TITLE_S = 4.0
MAX_TOTAL_S = 178.0  # 2:58
VOICE_LUFS, MUSIC_LUFS, FINAL_LUFS, FINAL_TP = -16, -28, -14, -1
PRE_AAC_TP = -2.5  # headroom: AAC encoding overshoots true peak by ~1-2 dB


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd[:6])} ...\n{r.stderr[-3000:]}")
    return r


def probe_dur(p: Path) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).stdout.strip())


def esc_path(p: Path) -> str:
    return str(p).replace("\\", "/")


def main() -> None:
    force_cards = "--force-cards" in sys.argv
    use_music = "--no-music" not in sys.argv and MUSIC.exists()
    WORK.mkdir(parents=True, exist_ok=True)
    FINAL.mkdir(parents=True, exist_ok=True)

    segs = bc.load_segments()
    vo = bc.resolve_vo(segs)
    cards = bc.build(force=force_cards)

    # ---- timeline
    clips = [{"id": "title", "path": cards["title"], "L": TITLE_S, "start": 0.0}]
    t = TITLE_S - XF
    placeholders = []
    for i, s in enumerate(segs):
        sid, shot = s["id"], s["shot"]
        dur = vo[sid]["dur"]
        L = dur + LEAD + TAIL + XF
        if sid == "s10":
            L = max(L, probe_dur(cards["end_card"]))
        path = cards.get(shot) or (SHOTS / f"{shot}.mp4")
        if not path.exists():
            placeholders.append(shot)
            path = None
        clips.append({"id": sid, "shot": shot, "path": path, "L": L, "start": t, "astart": t + LEAD, "adur": dur,
                      "wav": vo[sid]["wav"], "src": vo[sid]["source"]})
        t += L - XF
    total = clips[-1]["start"] + clips[-1]["L"]
    print(f"[assemble] total {total:.2f}s ({int(total // 60)}:{total % 60:04.1f})")
    if total > MAX_TOTAL_S:
        raise SystemExit(f"TOTAL {total:.1f}s exceeds {MAX_TOTAL_S:.0f}s (2:58) -- tighten narration/padding")
    print("[assemble] narration: " + ", ".join(f"{c['id']}={c['src']}" for c in clips[1:]))
    if placeholders:
        print(f"[assemble] PLACEHOLDER slates for shots: {placeholders}")

    # ---- callouts
    spec = json.loads((ROOT / "callouts.json").read_text(encoding="utf-8"))["callouts"]
    by_shot = {c["shot"]: c for c in clips[1:]}
    texts = {s["shot"]: s["text"] for s in segs}
    co = []
    for k, c in enumerate(spec):
        seg = by_shot.get(c["shot"])
        if seg is None:
            raise SystemExit(f"callout for unknown shot {c['shot']}")
        if "at" in c:
            at = seg["astart"] + c["at"]
        else:
            txt = texts[c["shot"]]
            m = re.search(re.escape(c["cue"]), txt, re.I)
            if not m:
                raise SystemExit(f"callout cue {c['cue']!r} not found in narration of {c['shot']}")
            frac = len(txt[:m.start()].split()) / len(txt.split())
            at = seg["astart"] + frac * seg["adur"] - 0.25
        co.append({**c, "at": max(at, seg["start"] + XF), "png": str(WORK / f"callout_{k}.png"), "tone": c.get("tone", "cyan")})
    for a, b in zip(co, co[1:]):  # avoid overlapping pills within a shot
        if a["shot"] == b["shot"] and a["at"] + a["dur"] > b["at"] - 0.15:
            a["dur"] = max(1.5, b["at"] - 0.15 - a["at"])
    for c in co:
        seg = by_shot[c["shot"]]
        c["dur"] = min(c["dur"], seg["start"] + seg["L"] - XF - c["at"])
    bc.render_pngs(co, placeholders)

    # ---- captions
    starts = {c["id"]: c["astart"] for c in clips[1:]}
    durs = {c["id"]: c["adur"] for c in clips[1:]}
    cs = captions.cues(segs, starts, durs)
    captions.write_srt(FINAL / "datathon2_demo.srt", cs)
    captions.write_ass(WORK / "captions.ass", cs)

    # ---- audio: voice (+ music) -> loudness-normalised wav
    ain, vparts = [], []
    for c in clips[1:]:
        if c["wav"]:
            ain += ["-i", c["wav"]]
            vparts.append((len(vparts), c["start"] + LEAD))
    fc = []
    for n, (idx, st) in enumerate(vparts):
        fc.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={int(st * 1000)}:all=1[v{n}]")
    if vparts:
        fc.append("".join(f"[v{n}]" for n in range(len(vparts))) + f"amix=inputs={len(vparts)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},atrim=0:{total:.3f}[vmix]")
    else:
        fc.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[vmix]")
    fc.append(f"[vmix]loudnorm=I={VOICE_LUFS}:TP=-2:LRA=11[voice]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *ain]
    if use_music:
        mi = len(vparts)
        cmd += ["-i", MUSIC]
        fc.append("[voice]asplit=2[vo1][vo2]")
        fc.append(f"[{mi}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total + 1:.3f},asetpts=PTS-STARTPTS,"
                  f"loudnorm=I={MUSIC_LUFS}:TP=-6:LRA=7,afade=t=in:st=0:d=2.5,afade=t=out:st={total - 4:.3f}:d=4[mus]")
        fc.append("[mus][vo1]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=500:makeup=1[duck]")
        fc.append(f"[vo2][duck]amix=inputs=2:normalize=0:duration=first,atrim=0:{total:.3f}[mix]")
    else:
        fc.append("[voice]anull[mix]")
    pre = WORK / "mix_pre.wav"
    run([*cmd, "-filter_complex", ";".join(fc), "-map", "[mix]", "-ar", "48000", "-c:a", "pcm_s16le", pre])
    # two-pass loudnorm to -14 LUFS / -1 dBTP
    meas = run(["ffmpeg", "-hide_banner", "-i", pre, "-af", f"loudnorm=I={FINAL_LUFS}:TP={PRE_AAC_TP}:LRA=11:print_format=json", "-f", "null", "-"]).stderr
    m = json.loads(meas[meas.rindex("{"):meas.rindex("}") + 1])
    af = (f"loudnorm=I={FINAL_LUFS}:TP={PRE_AAC_TP}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,alimiter=limit=0.73:level=false")
    audio = WORK / "mix_final.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", pre, "-af", af, "-ar", "48000", "-c:a", "pcm_s16le", audio])

    # ---- video graph
    inputs, f = [], []
    for k, c in enumerate(clips):
        if c["path"] is None:
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{c['L']:.3f}", "-i", bc.CARD_OUT / f"slate_{c['shot']}.png"]
        else:
            inputs += ["-i", c["path"]]
        f.append(f"[{k}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x050912,"
                 f"fps={FPS},setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration=60,trim=duration={c['L']:.3f},setpts=PTS-STARTPTS[c{k}]")
    prev = "c0"
    for k in range(1, len(clips)):
        off = clips[k]["start"]
        f.append(f"[{prev}][c{k}]xfade=transition=fade:duration={XF}:offset={off:.3f}[x{k}]")
        prev = f"x{k}"
    n0 = len(clips)
    for j, c in enumerate(co):
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{c['dur']:.3f}", "-i", c["png"]]
        idx, D, S = n0 + j, c["dur"], c["at"]
        f.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,fade=t=out:st={D - 0.35:.3f}:d=0.35:alpha=1,setpts=PTS-STARTPTS+{S:.3f}/TB[p{j}]")
        xx, yy = ("W-w-40", "150") if c.get("pos") == "top-right" else ("60", "H-h-270")
        f.append(f"[{prev}][p{j}]overlay=x={xx}:y='{yy}+if(lt(t-{S:.3f},0.5),44*pow(1-(t-{S:.3f})/0.5,3),0)':"
                 f"enable='between(t,{S:.3f},{S + D:.3f})':eof_action=pass[o{j}]")
        prev = f"o{j}"
    f.append(f"[{prev}]ass=captions.ass[vout]")
    script = WORK / "graph.txt"
    script.write_text(";\n".join(f), encoding="utf-8")
    ai = n0 + len(co)
    final = FINAL / "datathon2_demo.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-i", audio, "-filter_complex_script", "graph.txt",
         "-map", "[vout]", "-map", f"{ai}:a", "-c:v", "libx264", "-profile:v", "high", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", final],
        cwd=WORK)
    shutil.copy(WORK / "captions.ass", FINAL / "datathon2_demo.ass")
    d = probe_dur(final)
    print(f"[assemble] wrote {final}\n[assemble] DURATION {d:.2f}s = {int(d // 60)}:{d % 60:05.2f}")
    if d > MAX_TOTAL_S:
        raise SystemExit(f"final {d:.1f}s exceeds 2:58")


if __name__ == "__main__":
    main()
