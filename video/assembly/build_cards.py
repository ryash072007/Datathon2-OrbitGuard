"""Render the HTML cards (title, end card, LinuxONE terminal, callout pills, slates) with Playwright.

Deterministic capture: each card page exposes window.render(t); we step t = frame/FPS and screenshot every
frame into ffmpeg, so animation is exactly smooth regardless of machine speed.

Run with the recorder venv:  video/.venv-rec/Scripts/python.exe video/build_cards.py [--force]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import wave
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
CARDS = ROOT / "cards"
OUT = ROOT / "out"
CARD_OUT = OUT / "cards"
VO_DIR = OUT / "vo"
VO_SAMPLE_DIR = OUT / "vo_sample_ljspeech"
CAPTURE = ROOT / "vm_capture"
FPS = 30
WORDS_PER_S = 2.6  # only used to estimate placeholder narration length


# ----------------------------------------------------------------------------- narration helpers
def load_segments() -> list[dict]:
    return json.loads((ROOT / "vo_segments.json").read_text(encoding="utf-8"))


def wav_seconds(p: Path) -> float:
    with wave.open(str(p), "rb") as w:
        return w.getnframes() / w.getframerate()


def resolve_vo(segments: list[dict]) -> dict[str, dict]:
    """id -> {dur, wav (Path|None), source: real|sample|placeholder}."""
    res = {}
    for s in segments:
        sid = s["id"]
        for d, src in ((VO_DIR, "real"), (VO_SAMPLE_DIR, "sample")):
            p = d / f"{sid}.wav"
            if p.exists():
                res[sid] = {"dur": wav_seconds(p), "wav": p, "source": src}
                break
        else:
            n = len(s["text"].split())
            res[sid] = {"dur": round(n / WORDS_PER_S, 3), "wav": None, "source": "placeholder"}
    return res


# ----------------------------------------------------------------------------- capture parsing
def parse_capture(path: Path) -> list[dict]:
    """Split a capture file into blocks: {'cmd': str|None, 'lines': [...]}. Lines starting '$ ' open a block."""
    blocks: list[dict] = []
    cur = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("$ "):
            cur = {"cmd": raw[2:], "lines": []}
            blocks.append(cur)
        else:
            if cur is None:
                cur = {"cmd": None, "lines": []}
                blocks.append(cur)
            if raw.strip():
                cur["lines"].append(raw.rstrip())
    return blocks


def pick(lines: list[str], patterns: list[str]) -> list[str]:
    """Select real lines matching the patterns, in file order, inserting an elide marker for gaps."""
    out: list[str] = []
    last = -1
    for i, ln in enumerate(lines):
        if any(re.search(p, ln) for p in patterns):
            if last >= 0 and i - last > 1 or (last < 0 and i > 0):
                out.append("\0elide")
            out.append(ln)
            last = i
    if last >= 0 and last < len(lines) - 1:
        out.append("\0elide")
    return out


def items_from(block: dict, patterns: list[str] | None = None, max_lines: int = 12) -> list[dict]:
    items = []
    if block["cmd"]:
        items.append({"kind": "cmd", "text": block["cmd"]})
    lines = pick(block["lines"], patterns) if patterns else block["lines"][:max_lines]
    for ln in lines:
        items.append({"kind": "elide"} if ln == "\0elide" else {"kind": "out", "text": ln})
    return items


def terminal_scenes(dur: float = 26.0, text: str = "") -> list[dict]:
    """3 scenes from genuine captured lines only, each timed to a cue phrase in the s09 narration.
    (a) platform  (b) NNPA report table (nnpa.txt)  (c) Granite line (granite.txt).
    Missing nnpa/granite files -> that scene is skipped. platform.txt/pipeline.txt remain available for extra scenes."""
    lead = 0.3

    def at(cue: str) -> float:
        m = re.search(re.escape(cue), text, re.I)
        if not m or not text:
            return 0.0
        return max(0.0, lead + len(text[:m.start()].split()) / len(text.split()) * dur - 0.5)

    plat = parse_capture(CAPTURE / "platform.txt")
    by_cmd = {b["cmd"]: b for b in plat if b["cmd"]}

    def find(frag: str) -> dict:
        for c, b in by_cmd.items():
            if frag in c:
                return b
        raise SystemExit(f"platform.txt has no block for command containing {frag!r}")

    scenes = [{"at": 0.0, "items": items_from(find("/proc/sysinfo"), [r"^s390x", r"^Type:"])
               + items_from(find("lscpu"), [r"Byte Order"]) + items_from(find("cpuinfo"))}]
    f = CAPTURE / "nnpa.txt"
    if f.exists():
        blocks = parse_capture(f)
        rep = [b for b in blocks if b["cmd"] and "report" in b["cmd"]]
        if rep:
            scenes.append({"at": at("accelerator"), "items": items_from(rep[0], max_lines=12)})
    f = CAPTURE / "granite.txt"
    if f.exists():
        items: list[dict] = []
        for b in parse_capture(f):
            items += items_from(b, max_lines=4)
        if items:
            scenes.append({"at": at("Granite runs"), "items": items})
    return scenes


# ----------------------------------------------------------------------------- rendering
def encode_frames(pg, dur: float, out: Path, fps: int = FPS) -> None:
    n = round(dur * fps)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(fps), str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        pg.evaluate("t => window.render(t)", i / fps)
        ff.stdin.write(pg.screenshot(type="png"))
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit(f"ffmpeg failed encoding {out}")


def build(force: bool = False) -> dict[str, Path]:
    from playwright.sync_api import sync_playwright

    segs = load_segments()
    vo = resolve_vo(segs)
    jobs = {
        "title": {"dur": 4.0},
        "end_card": {"dur": round(vo["s10"]["dur"] + 2.0, 3), "query": {"dur": round(vo["s10"]["dur"] + 2.0, 3)}},
        "linuxone_terminal": {"dur": round(vo["s09"]["dur"], 3)},
    }
    scenes = terminal_scenes(vo["s09"]["dur"], next(s["text"] for s in segs if s["id"] == "s09"))
    jobs["linuxone_terminal"]["scenes"] = scenes
    result: dict[str, Path] = {}
    todo = []
    for name, j in jobs.items():
        out = CARD_OUT / f"{name}.mp4"
        stamp = CARD_OUT / f"{name}.json"
        sig = json.dumps({"dur": j["dur"], "scenes": j.get("scenes"), "fps": FPS,
                          "src": [(CARDS / f).stat().st_mtime_ns for f in (f"{name}.html", "common.js", "base.css")]}, sort_keys=True)
        result[name] = out
        if not force and out.exists() and stamp.exists() and stamp.read_text() == sig:
            continue
        todo.append((name, j, out, stamp, sig))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        for name, j, out, stamp, sig in todo:
            pg = ctx.new_page()
            if "scenes" in j:
                pg.add_init_script(f"window.SCENES={json.dumps(j['scenes'])};window.DUR={j['dur']};")
            q = ("?" + urlencode(j["query"])) if j.get("query") else ""
            pg.goto((CARDS / f"{name}.html").as_uri() + q)
            pg.wait_for_function("window.__ready===true")
            pg.evaluate("document.fonts.ready")
            print(f"[cards] rendering {name} ({j['dur']:.2f}s, {round(j['dur'] * FPS)} frames)")
            encode_frames(pg, j["dur"], out)
            stamp.write_text(sig)
            pg.close()
        browser.close()
    return result


def png_from_page(name: str, query: dict, out: Path, element: str | None = None, transparent: bool = False) -> Path:
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((CARDS / f"{name}.html").as_uri() + "?" + urlencode(query))
        pg.evaluate("document.fonts.ready")
        if element:
            pg.locator(element).screenshot(path=str(out), omit_background=transparent)
        else:
            pg.screenshot(path=str(out))
        browser.close()
    return out


def render_pngs(callouts: list[dict], slates: list[str]) -> None:
    """Render all callout pills + slates in ONE browser session (cached by content)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        for c in callouts:
            out = Path(c["png"])
            if out.exists() and out.stat().st_mtime > (CARDS / "callout.html").stat().st_mtime:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            pg.goto((CARDS / "callout.html").as_uri() + "?" + urlencode({"big": c["big"], "label": c["label"], "tone": c["tone"]}))
            pg.evaluate("document.fonts.ready")
            pg.locator("#pill").screenshot(path=str(out), omit_background=True)
        for name in slates:
            out = CARD_OUT / f"slate_{name}.png"
            pg.goto((CARDS / "slate.html").as_uri() + "?" + urlencode({"text": f"SHOT PENDING: {name}"}))
            pg.screenshot(path=str(out))
        browser.close()


if __name__ == "__main__":
    build(force="--force" in sys.argv)
