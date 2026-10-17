"""Server-side inline SVG charts (no JS or CDN needed, works offline on the VM)."""
from __future__ import annotations

import math
from html import escape


def bar_chart(items: dict[str, float], width: int = 420, bar_h: int = 20, max_items: int = 8) -> str:
    rows = sorted(items.items(), key=lambda kv: -kv[1])[:max_items]
    if not rows:
        return "<p class='muted'>No data.</p>"
    vmax = max(v for _, v in rows) or 1.0
    label_w = 130
    h = bar_h * len(rows) + 6
    out = [f"<svg viewBox='0 0 {width} {h}' width='100%' role='img' aria-label='affected constellations'>"]
    for i, (k, v) in enumerate(rows):
        y = 3 + i * bar_h
        w = (width - label_w - 50) * v / vmax
        out.append(f"<text x='{label_w - 6}' y='{y + 14}' text-anchor='end' font-size='12'>{escape(str(k))[:18]}</text>"
                   f"<rect x='{label_w}' y='{y + 2}' width='{w:.1f}' height='{bar_h - 6}' fill='#3b82f6'/>"
                   f"<text x='{label_w + w + 4:.1f}' y='{y + 14}' font-size='12'>{v:g}</text>")
    out.append("</svg>")
    return "".join(out)


def slope_chart(rows: list[dict], selected: int | None = None, width: int = 420) -> str:
    """rows: dicts with primary, norad, rank_pc, rank_harm. Left axis = Pc rank, right axis = harm rank."""
    if not rows:
        return "<p class='muted'>No survey yet.</p>"
    n = max(max(r["rank_pc"], r["rank_harm"]) for r in rows)
    top, step = 28, 15
    h = top + step * n + 10
    xl, xr = 110, width - 110
    out = [f"<svg viewBox='0 0 {width} {h}' width='100%' role='img' aria-label='Pc rank versus harm rank'>",
           f"<text x='{xl}' y='14' text-anchor='end' font-size='12' font-weight='bold'>Rank by Pc</text>",
           f"<text x='{xr}' y='14' font-size='12' font-weight='bold'>Rank by harm</text>"]
    for r in sorted(rows, key=lambda r: r["rank_pc"]):
        y1, y2 = top + step * (r["rank_pc"] - 1), top + step * (r["rank_harm"] - 1)
        shift = r["rank_pc"] - r["rank_harm"]
        sel = selected is not None and r["norad"] == selected
        colour = "#111827" if sel else ("#dc2626" if shift >= 3 else "#16a34a" if shift <= -3 else "#9ca3af")
        sw = 2.5 if sel else 1.2
        name = escape(str(r["primary"]))[:16]
        out.append(f"<line x1='{xl + 4}' y1='{y1}' x2='{xr - 4}' y2='{y2}' stroke='{colour}' stroke-width='{sw}'/>"
                   f"<text x='{xl}' y='{y1 + 4}' text-anchor='end' font-size='10'>{r['rank_pc']} {name}</text>"
                   f"<text x='{xr}' y='{y2 + 4}' font-size='10'>{r['rank_harm']} {name}</text>")
    out.append("</svg>")
    return "".join(out)


def network_svg(nodes: list[dict], edges: list[dict], n_top: int = 50, width: int = 560, height: int = 340) -> str:
    """Top nodes placed by inclination (x) and mean altitude (y); radius ~ sqrt(score)."""
    sel = nodes[:n_top]
    if not sel:
        return "<p class='muted'>No network yet.</p>"
    pos: dict[int, tuple[float, float]] = {}
    inc = [n["inclination_deg"] for n in sel]
    alt = [0.5 * (n["perigee_km"] + n["apogee_km"]) for n in sel]
    i0, i1 = min(inc), max(inc)
    a0, a1 = min(alt), max(alt)
    pad = 36
    for n, i, a in zip(sel, inc, alt):
        x = pad + (width - 2 * pad) * ((i - i0) / (i1 - i0) if i1 > i0 else 0.5)
        y = height - pad - (height - 2 * pad) * ((a - a0) / (a1 - a0) if a1 > a0 else 0.5)
        pos[n["norad"]] = (x, y)
    colours = {"PAYLOAD": "#2563eb", "DEBRIS": "#f97316", "ROCKET BODY": "#7c3aed"}
    smax = max(n["score"] for n in sel) or 1.0
    out = [f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' aria-label='super-spreader network'>",
           f"<text x='{width / 2}' y='{height - 6}' text-anchor='middle' font-size='11'>inclination "
           f"{i0:.0f} to {i1:.0f} deg</text>",
           f"<text x='10' y='{height / 2}' font-size='11' transform='rotate(-90 10 {height / 2})' "
           f"text-anchor='middle'>mean altitude {a0:.0f} to {a1:.0f} km</text>"]
    for e in edges:
        if e["a"] in pos and e["b"] in pos:
            (xa, ya), (xb, yb) = pos[e["a"]], pos[e["b"]]
            out.append(f"<line x1='{xa:.1f}' y1='{ya:.1f}' x2='{xb:.1f}' y2='{yb:.1f}' stroke='#94a3b8' "
                       f"stroke-width='{min(0.6 + 0.4 * math.log1p(e['steps']), 3):.1f}'/>")
    for k, n in enumerate(sel):
        x, y = pos[n["norad"]]
        r = 3 + 9 * math.sqrt(n["score"] / smax)
        out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='{colours.get(n['type'], '#64748b')}' "
                   f"fill-opacity='0.75'><title>{escape(n['name'])}: degree {n['degree']}, score {n['score']:.3f}"
                   f"</title></circle>")
        if k < 6:
            out.append(f"<text x='{x + r + 2:.1f}' y='{y + 3:.1f}' font-size='9'>{escape(n['name'])[:16]}</text>")
    out.append("</svg>")
    return "".join(out)
