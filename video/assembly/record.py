"""Scripted screen recorder for the dashboard demo video.

Run with the recorder env:  video/.venv-rec/Scripts/python video/record.py [--only replay dodge]
See video/README.md for the capture-method rationale.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
W, H = 1920, 1080
FPS = 60
SKIP = {"linuxone_terminal", "end_card"}
LEAD_S = 0.35          # ffmpeg start-up slack trimmed from the head of every capture
EXTRA_S = 0.4          # added to narration duration

# ---------------------------------------------------------------- in-page helpers (injected once per page)
HELPERS = r"""
(() => {
  if (window.__rec) return;
  const ease = t => t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
  const raf = () => new Promise(r => requestAnimationFrame(r));
  async function tween(ms, fn) {
    const t0 = performance.now();
    for (;;) { const k = Math.min(1, (performance.now() - t0) / Math.max(ms, 1)); fn(ease(k), k); if (k >= 1) break; await raf(); }
  }
  window.__rec = {
    async scrollTo(y, ms) { const y0 = scrollY; if (ms <= 0) { scrollTo(0, y); return; } await tween(ms, e => scrollTo(0, y0 + (y - y0) * e)); },
    async drag(el, dx, dy, ms) {
      const r = el.getBoundingClientRect(), x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
      const ev = (type, x, y) => el.dispatchEvent(new PointerEvent(type, {bubbles: true, cancelable: true, pointerId: 7, pointerType: 'mouse', isPrimary: true, clientX: x, clientY: y, buttons: type === 'pointerup' ? 0 : 1}));
      try { ev('pointerdown', x0, y0); } catch (e) {}
      await tween(ms, e => ev('pointermove', x0 + dx * e, y0 + dy * e));
      ev('pointerup', x0 + dx, y0 + dy);
    },
    async wheel(el, dy, steps, ms) {
      const r = el.getBoundingClientRect(); let last = 0;
      await tween(ms, (e) => { const n = Math.round(e * steps); while (last < n) { last++; el.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, deltaY: dy, clientX: r.left + r.width/2, clientY: r.top + r.height/2})); } });
    },
  };
  const st = document.createElement('style');
  st.textContent = '*{cursor:none !important} html{scrollbar-width:none} ::-webkit-scrollbar{display:none}';
  document.head.appendChild(st);
})();
"""


# ---------------------------------------------------------------- server management
def port_up(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=2).read(1)
        return True
    except Exception:
        return False


def cmdline(pid: int) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
        capture_output=True, text=True).stdout
    return out.strip()


class Server:
    def __init__(self, base: str):
        self.base, self.proc = base, None

    def __enter__(self):
        if port_up(self.base):
            print("server already up; reusing (will not kill it)")
            return self
        py = ROOT / ".venv" / "Scripts" / "python.exe"
        self.proc = subprocess.Popen([str(py), "-m", "legacy.flask_dashboard.run"], cwd=ROOT,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            if port_up(self.base):
                break
            time.sleep(0.5)
        else:
            self.__exit__()
            raise RuntimeError("dashboard did not start within 60 s")
        print(f"server started, pid {self.proc.pid}")
        return self

    def __exit__(self, *a):
        if self.proc is None:
            return
        pid = self.proc.pid
        if "legacy.flask_dashboard.run" in cmdline(pid):      # only kill what we started, after verifying identity
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            print(f"server pid {pid} stopped")
        else:
            print(f"pid {pid} cmdline does not contain legacy.flask_dashboard.run; not killing", file=sys.stderr)


# ---------------------------------------------------------------- durations
def load_durations(shots_cfg: dict, segs: list[dict], dur_file: Path | None) -> dict[str, float]:
    words: dict[str, int] = {}
    for s in segs:
        words[s["shot"]] = words.get(s["shot"], 0) + len(s["text"].split())
    out = {k: round(v / 2.5, 2) for k, v in words.items()}
    for k, v in shots_cfg["shots"].items():
        if "dur" in v:
            out[k] = float(v["dur"])
    if dur_file and dur_file.exists():
        d = json.loads(dur_file.read_text())
        seg_shot = {s["id"]: s["shot"] for s in segs}
        sums: dict[str, float] = {}
        for k, v in d.items():
            if isinstance(v, dict):
                v = v.get("duration") or v.get("dur") or v.get("seconds")
            if k in seg_shot:
                sums[seg_shot[k]] = sums.get(seg_shot[k], 0) + float(v)
            elif k in out or k in shots_cfg["shots"]:
                sums[k] = float(v)
        for k, v in sums.items():
            out[k] = round(v + EXTRA_S, 2)
        print(f"durations overridden from {dur_file} for {sorted(sums)}")
    return out


# ---------------------------------------------------------------- actions
class Runner:
    def __init__(self, page: Page, base: str):
        self.page, self.base = page, base
        self.mx, self.my = W // 2, H // 2

    def loc(self, sel: str, nth: int = 0):
        return self.page.locator(sel).nth(nth)

    def mouse_to(self, x: float, y: float, ms: int = 700):
        n = max(2, int(ms / 16))
        x0, y0 = self.mx, self.my
        for i in range(1, n + 1):
            t = i / n
            e = t * t * (3 - 2 * t)
            self.page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
            self.page.wait_for_timeout(16)
        self.mx, self.my = x, y

    def center(self, sel: str, nth: int = 0):
        el = self.loc(sel, nth)
        el.scroll_into_view_if_needed()
        b = el.bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    def do(self, a: dict):
        p, t = self.page, a["type"]
        if t == "goto":
            p.goto(self.base.rstrip("/") + a.get("url", "/"), wait_until="load")
            p.evaluate(HELPERS)
            if a.get("ready"):
                p.wait_for_selector(a["ready"], state="attached", timeout=30000)
            p.wait_for_timeout(1500)
        elif t == "wait":
            p.wait_for_timeout(int(a["s"] * 1000))
        elif t == "scroll":
            y = p.evaluate("([s,o]) => document.querySelector(s).getBoundingClientRect().top + scrollY - o",
                           [a["to"], a.get("offset", 0)])
            p.evaluate("([y,ms]) => window.__rec.scrollTo(y, ms)", [y, a.get("ms", 2000)])
        elif t == "hover":
            x, y = self.center(a["sel"], a.get("nth", 0))
            self.mouse_to(x, y, a.get("move_ms", 800))
            p.wait_for_timeout(int(a.get("s", 1) * 1000))
        elif t == "click":
            x, y = self.center(a["sel"], a.get("nth", 0))
            self.mouse_to(x, y, a.get("move_ms", 800))
            p.wait_for_timeout(200)
            p.mouse.down(); p.wait_for_timeout(60); p.mouse.up()
        elif t == "drag":
            self.loc(a["sel"]).evaluate("(el,[dx,dy,ms]) => window.__rec.drag(el,dx,dy,ms)", [a["dx"], a["dy"], a["ms"]])
        elif t == "wheel":
            self.loc(a["sel"]).evaluate("(el,[dy,n,ms]) => window.__rec.wheel(el,dy,n,ms)", [a["dy"], a["steps"], a["ms"]])
        elif t == "slider":
            sel = a["sel"]
            x, y = self.center(sel)
            self.mouse_to(x, y, 800)
            for v in a["values"]:
                p.evaluate("([s,v]) => { const r = document.querySelector(s); r.value = v; r.dispatchEvent(new Event('input', {bubbles:true})); }", [sel, v])
                p.wait_for_timeout(int(a.get("hold_s", 3) * 1000))
        elif t == "js":
            p.evaluate(a["code"])
        else:
            raise ValueError(f"unknown action {t}")


def est_s(a: dict) -> float:
    t = a["type"]
    if t == "wait": return a["s"]
    if t == "scroll": return a.get("ms", 2000) / 1000
    if t in ("drag", "wheel"): return a["ms"] / 1000
    if t == "hover": return a.get("s", 1) + a.get("move_ms", 800) / 1000
    if t == "click": return 1.1
    if t == "slider": return 0.8 + len(a["values"]) * a.get("hold_s", 3)
    return 0.0


def fit(actions: list[dict], dur: float) -> list[dict]:
    """Compress (never stretch) action timings so the sequence fits the shot duration."""
    total = sum(est_s(a) for a in actions)
    k = max(0.45, min(1.0, (dur - 0.4) / total)) if total else 1.0
    if k >= 1.0:
        return actions
    out = []
    for a in actions:
        a = dict(a)
        for key in ("s", "ms", "hold_s", "move_ms"):
            if key in a:
                a[key] = a[key] * k if key != "ms" else int(a[key] * k)
        out.append(a)
    print(f"  timings compressed x{k:.2f} (nominal {total:.1f}s -> {dur:.1f}s)")
    return out


# ---------------------------------------------------------------- capture
def start_ffmpeg(raw: Path) -> subprocess.Popen:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "gdigrab", "-framerate", str(FPS), "-draw_mouse", "0",
           "-offset_x", "0", "-offset_y", "0", "-video_size", f"{W}x{H}", "-i", "desktop",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", str(raw)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def stop_ffmpeg(proc: subprocess.Popen):
    try:
        proc.stdin.write(b"q"); proc.stdin.flush()
    except Exception:
        pass
    proc.wait(timeout=60)


def finalize(raw: Path, out: Path, dur: float):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(LEAD_S), "-i", str(raw),
           "-vf", f"fps={FPS},tpad=stop_mode=clone:stop_duration=120", "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def record_shot(pw, name: str, spec: dict, dur: float, base: str, out_dir: Path, tmp: Path):
    print(f"[{name}] target {dur:.2f}s")
    browser = pw.chromium.launch(
        channel="msedge", headless=False, ignore_default_args=["--enable-automation"],
        args=["--kiosk", "--force-device-scale-factor=1", "--window-position=0,0", "--disable-infobars",
              "--hide-scrollbars", "--ignore-gpu-blocklist", "--enable-gpu-rasterization",
              "--no-first-run", "--autoplay-policy=no-user-gesture-required"])
    ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)           # true fullscreen: no tabs, address bar or title bar
    wid = cdp.send("Browser.getWindowForTarget")["windowId"]
    cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "fullscreen"}})
    page.wait_for_timeout(1500)
    r = Runner(page, base)
    actions = spec["actions"]
    # run the leading goto (+ instant scrolls) BEFORE recording so no loading state is captured
    pre = 0
    while pre < len(actions) and actions[pre]["type"] == "goto":
        r.do(actions[pre]); pre += 1
    while pre < len(actions) and actions[pre]["type"] == "scroll" and actions[pre].get("ms", 2000) == 0:
        r.do(actions[pre]); pre += 1
    page.bring_to_front()
    page.wait_for_timeout(800)
    raw = tmp / f"{name}.raw.mkv"
    ff = start_ffmpeg(raw)
    time.sleep(0.9)  # ffmpeg warm-up; static opening frame
    t0 = time.time()
    try:
        for a in fit(actions[pre:], dur):
            if time.time() - t0 > dur + 1:
                break
            r.do(a)
        remaining = dur + 0.2 - (time.time() - t0)
        if remaining > 0:
            page.wait_for_timeout(int(remaining * 1000))
        else:
            print(f"  note: actions overran target by {-remaining:.1f}s (trimmed)")
    finally:
        stop_ffmpeg(ff)
        ctx.close(); browser.close()
    out = out_dir / f"{name}.mp4"
    finalize(raw, out, dur)
    raw.unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT / "video" / "shots.json"))
    ap.add_argument("--durations", default=None)
    ap.add_argument("--segments", default=str(ROOT / "video" / "vo_segments.json"))
    ap.add_argument("--out", default=str(ROOT / "video" / "out" / "shots"))
    ap.add_argument("--only", nargs="*", help="record just these shots")
    a = ap.parse_args()

    cfg = json.loads(Path(a.shots).read_text())
    segs = json.loads(Path(a.segments).read_text())
    durs = load_durations(cfg, segs, Path(a.durations) if a.durations else None)
    names = [n for n in cfg["shots"] if n not in SKIP and (not a.only or n in a.only)]
    out_dir = Path(a.out); out_dir.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "video" / "out" / "tmp"; tmp.mkdir(parents=True, exist_ok=True)
    base = cfg.get("base_url", "http://127.0.0.1:8080/")

    with Server(base), sync_playwright() as pw:
        for n in names:
            if n not in durs:
                print(f"[{n}] no narration segment and no dur; skipping", file=sys.stderr)
                continue
            record_shot(pw, n, cfg["shots"][n], durs[n], base, out_dir, tmp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
