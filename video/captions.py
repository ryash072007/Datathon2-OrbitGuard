"""Captions: split narration text into <=2 lines of <=42 chars, time proportionally by word count, write .ass + .srt."""
from __future__ import annotations

from pathlib import Path

MAX_CHARS = 42
MAX_LINES = 2


def split_chunks(text: str) -> list[list[str]]:
    """Return chunks; each chunk is a list of 1-2 lines. Greedy fill, preferring breaks after punctuation."""
    words = text.split()
    lines: list[list[str]] = []  # each line = list of words
    cur: list[str] = []
    for w in words:
        if cur and len(" ".join(cur + [w])) > MAX_CHARS:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    chunks = []
    for i in range(0, len(lines), MAX_LINES):
        chunks.append(lines[i:i + MAX_LINES])
    return [[" ".join(l) for l in c] for c in chunks]


def cues(segments: list[dict], starts: dict[str, float], durs: dict[str, float]) -> list[tuple[float, float, str]]:
    out = []
    for s in segments:
        sid = s["id"]
        chunks = split_chunks(s["text"])
        counts = [sum(len(l.split()) for l in c) for c in chunks]
        total = sum(counts)
        t = starts[sid]
        for c, n in zip(chunks, counts):
            d = durs[sid] * n / total
            out.append((t, t + d, "\n".join(c)))
            t += d
    return out


def _ts_srt(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _ts_ass(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000:d}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_srt(path: Path, cs: list[tuple[float, float, str]]) -> None:
    path.write_text("".join(f"{i}\n{_ts_srt(a)} --> {_ts_srt(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(cs, 1)), encoding="utf-8")


def write_ass(path: Path, cs: list[tuple[float, float, str]], font: str = "Segoe UI") -> None:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},46,&H00FFFFFF,&H00FFFFFF,&H38120A05,&H38120A05,0,0,0,0,100,100,0,0,3,12,0,2,160,160,48,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = "".join(f"Dialogue: 0,{_ts_ass(a)},{_ts_ass(b)},Default,,0,0,0,,{t.replace(chr(10), chr(92) + 'N')}\n" for a, b, t in cs)
    path.write_text(head + body, encoding="utf-8")
