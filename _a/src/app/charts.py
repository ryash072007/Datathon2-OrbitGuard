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


def _nice_ticks(lo: float, hi: float, n: int = 6) -> list[float]:
    span = max(hi - lo, 1e-9)
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 6))
        t += step
    return out


def network_svg(nodes: list[dict], edges: list[dict], n_top: int = 60, width: int = 640, height: int = 420) -> str:
    """Scatter of the top nodes: x = mean altitude (km), y = inclination (deg), circle size ~ score, colour = type."""
    sel = sorted(nodes, key=lambda n: -n["score"])[:n_top]
    if not sel:
        return "<p class='muted'>No network yet.</p>"
    alt = {n["norad"]: 0.5 * (n["perigee_km"] + n["apogee_km"]) for n in sel}
    L, R, T, B = 52, 16, 14, 44
    pw, ph = width - L - R, height - T - B
    a_vals, i_vals = list(alt.values()), [n["inclination_deg"] for n in sel]
    a_pad = max((max(a_vals) - min(a_vals)) * 0.06, 20.0)
    i_pad = max((max(i_vals) - min(i_vals)) * 0.08, 2.0)
    a0, a1 = min(a_vals) - a_pad, max(a_vals) + a_pad
    i0, i1 = max(min(i_vals) - i_pad, 0.0), min(max(i_vals) + i_pad, 180.0)

    def X(a: float) -> float:
        return L + pw * (a - a0) / (a1 - a0)

    def Y(i: float) -> float:
        return T + ph * (1 - (i - i0) / (i1 - i0))

    colours = {"PAYLOAD": "#2563eb", "DEBRIS": "#f97316", "ROCKET BODY": "#7c3aed"}
    smax = max(n["score"] for n in sel) or 1.0
    out = [f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' aria-label='super-spreader scatter'>"]
    for t in _nice_ticks(a0, a1):
        out.append(f"<line x1='{X(t):.1f}' x2='{X(t):.1f}' y1='{T}' y2='{T + ph}' stroke='#eef0f3'/>"
                   f"<text x='{X(t):.1f}' y='{T + ph + 14}' font-size='10' text-anchor='middle'>{t:g}</text>")
    for t in _nice_ticks(i0, i1, 5):
        out.append(f"<line x1='{L}' x2='{L + pw}' y1='{Y(t):.1f}' y2='{Y(t):.1f}' stroke='#eef0f3'/>"
                   f"<text x='{L - 5}' y='{Y(t) + 3:.1f}' font-size='10' text-anchor='end'>{t:g}</text>")
    out.append(f"<rect x='{L}' y='{T}' width='{pw}' height='{ph}' fill='none' stroke='#9ca3af'/>"
               f"<text x='{L + pw / 2}' y='{T + ph + 32}' font-size='11' text-anchor='middle'>mean altitude (km)</text>"
               f"<text x='12' y='{T + ph / 2}' font-size='11' text-anchor='middle' "
               f"transform='rotate(-90 12 {T + ph / 2})'>inclination (deg)</text>")
    pos = {n["norad"]: (X(alt[n["norad"]]), Y(n["inclination_deg"])) for n in sel}
    for e in edges:
        if e["a"] in pos and e["b"] in pos:
            (xa, ya), (xb, yb) = pos[e["a"]], pos[e["b"]]
            out.append(f"<line x1='{xa:.1f}' y1='{ya:.1f}' x2='{xb:.1f}' y2='{yb:.1f}' stroke='#64748b' "
                       f"stroke-opacity='0.3' stroke-width='0.7'/>")
    radii: dict[int, float] = {}
    for n in sel:  # sorted by score: big first so small circles stay visible on top
        x, y = pos[n["norad"]]
        r = radii[n["norad"]] = 3 + 10 * math.sqrt(n["score"] / smax)
        out.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{r:.1f}' fill='{colours.get(n['type'], '#64748b')}' "
                   f"fill-opacity='0.7' stroke='#fff' stroke-width='0.8'><title>{escape(n['name'])} ({escape(n['type'])}): "
                   f"degree {n['degree']}, score {n['score']:.3f}, {alt[n['norad']]:.0f} km, "
                   f"{n['inclination_deg']:.1f} deg</title></circle>")
    # labels for the top 5, greedy placement avoiding earlier labels, circles and the plot border
    placed: list[tuple[float, float, float, float]] = []
    circles = [(pos[k][0], pos[k][1], radii[k]) for k in pos]

    def cost(b) -> float:
        if b[0] < L or b[2] > L + pw or b[1] < T or b[3] > T + ph:
            return 1e6
        c = sum(1 for p in placed if not (b[2] < p[0] or b[0] > p[2] or b[3] < p[1] or b[1] > p[3])) * 100
        c += sum(1 for cx, cy, r in circles if not (b[2] < cx - r or b[0] > cx + r or b[3] < cy - r or b[1] > cy + r))
        return c

    for n in sel[:5]:
        x, y = pos[n["norad"]]
        r = radii[n["norad"]]
        name = n["name"][:18]
        w, h = 5.6 * len(name) + 4, 12
        best = None
        for k in range(1, 15):
            gap = r + 6 * k
            for ang in range(0, 360, 30):
                dx, dy = gap * math.cos(math.radians(ang)), -gap * math.sin(math.radians(ang)) * 0.8
                anchor = "start" if dx > 4 else "end" if dx < -4 else "middle"
                bx = x + dx - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
                by = y + dy + (h if dy > 0 else 0)
                b = (bx, by - h, bx + w, by)
                c = cost(b) + k
                if best is None or c < best[0]:
                    best = (c, b, x + dx, by, anchor)
            if best[0] < 8:
                break
        _, b, tx, ty, anchor = best
        placed.append(b)
        out.append(f"<line x1='{x:.1f}' y1='{y:.1f}' x2='{tx:.1f}' y2='{ty - 4:.1f}' stroke='#111827' stroke-width='0.8'/>")
        out.append(f"<text x='{tx:.1f}' y='{ty:.1f}' font-size='10' font-weight='600' text-anchor='{anchor}' "
                   f"fill='#111827' stroke='#fff' stroke-width='3' paint-order='stroke'>{escape(name)}</text>")
    # legend below the plot's top-right corner
    lx = L + pw - 275
    out.append(f"<g font-size='10'><rect x='{lx - 6}' y='{T + ph - 25}' width='268' height='20' rx='3' fill='#fff' "
               f"fill-opacity='0.9' stroke='#e5e7eb'/>")
    for lab, key in (("payload", "PAYLOAD"), ("rocket body", "ROCKET BODY"), ("debris", "DEBRIS")):
        out.append(f"<circle cx='{lx + 4}' cy='{T + ph - 15}' r='4.5' fill='{colours[key]}' fill-opacity='0.8'/>"
                   f"<text x='{lx + 12}' y='{T + ph - 11.5}'>{lab}</text>")
        lx += 12 + 6 * len(lab) + 12
    out.append(f"<text x='{lx}' y='{T + ph - 11.5}' fill='#6b7280'>size = score</text></g>")
    out.append("</svg>")
    return "".join(out)


def markdown_html(text: str) -> str:
    """Tiny safe markdown subset: # headings, - / * bullets, 1. lists, **bold**, paragraphs. HTML is escaped first."""
    import re

    def inline(s: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escape(s))

    out: list[str] = []
    para: list[str] = []
    lst: list[str] = []  # zero or one open list tag

    def flush_para() -> None:
        if para:
            out.append("<p>" + " ".join(inline(p) for p in para) + "</p>")
            para.clear()

    def close_list() -> None:
        if lst:
            out.append(f"</{lst.pop()}>")

    for raw in text.splitlines():
        line = raw.strip()
        m_h = re.match(r"^(#{1,6})\s+(.*)$", line)
        m_b = re.match(r"^[-*]\s+(.*)$", line)
        m_n = re.match(r"^\d+[.)]\s+(.*)$", line)
        if not line:
            flush_para()
            close_list()
        elif m_h:
            flush_para()
            close_list()
            lvl = min(len(m_h.group(1)) + 1, 6)
            out.append(f"<h{lvl}>{inline(m_h.group(2))}</h{lvl}>")
        elif m_b or m_n:
            flush_para()
            kind = "ul" if m_b else "ol"
            if not lst or lst[0] != kind:
                close_list()
                out.append(f"<{kind}>")
                lst.append(kind)
            out.append(f"<li>{inline((m_b or m_n).group(1))}</li>")
        else:
            close_list()
            para.append(line)
    flush_para()
    close_list()
    return "\n".join(out)


def globe_svg(g: dict, snap: int = -2, width: int = 560, height: int = 400) -> str:
    """Static orthographic projection of the globe payload, used when WebGL or the three.js CDN is unavailable."""
    import numpy as np

    view = np.array([0.8, -0.5, 0.45])
    view /= np.linalg.norm(view)
    right = np.cross([0.0, 0.0, 1.0], view)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    re = float(g.get("earth_radius_km", 6371.0))
    snaps = g.get("snapshots") or []
    extent = 1.0
    for arr in [s_["points"] for s_ in snaps] + [g.get("tracks", {}).get("primary", [])]:
        if len(arr):
            extent = max(extent, float(np.abs(np.asarray(arr)).max()))
    extent = max(extent, re) * 1.08
    sc = min(width, height) / 2 / extent
    cx, cy = width / 2, height / 2

    def proj(a):
        a = np.asarray(a, dtype=float).reshape(-1, 3)
        x, y, d = a @ right, a @ up, a @ view
        hidden = (d < 0) & (np.hypot(x, y) < re)
        return cx + x * sc, cy - y * sc, hidden

    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='100%' role='img' "
           f"aria-label='debris cloud projection' style='background:#050b18'>",
           f"<circle cx='{cx}' cy='{cy}' r='{re * sc:.1f}' fill='#0b2447' stroke='#2c5282'/>"]
    for name, col, dash in (("primary", "#4cc9f0", ""), ("threat", "#f4a261", "")):
        pts = g.get("tracks", {}).get(name) or []
        if len(pts) > 1:
            x, y, h = proj(pts)
            out.append(f"<polyline points='{' '.join(f'{a:.1f},{b:.1f}' for a, b in zip(x, y))}' fill='none' "
                       f"stroke='{col}' stroke-width='1.2' opacity='0.9'/>")
    burn = g.get("burn")
    if burn and len(burn.get("points", [])) > 1:
        x, y, h = proj(burn["points"])
        out.append(f"<polyline points='{' '.join(f'{a:.1f},{b:.1f}' for a, b in zip(x, y))}' fill='none' "
                   f"stroke='#80ed99' stroke-width='1.2' stroke-dasharray='5 4'/>")
    if snaps:
        s_ = snaps[snap]
        x, y, h = proj(s_["points"]) if len(s_["points"]) else ([], [], [])
        out.append("<g fill='#ffd166' fill-opacity='0.75'>" + "".join(
            f"<circle cx='{a:.1f}' cy='{b:.1f}' r='1.3'/>" for a, b, hd in zip(x, y, h) if not hd) + "</g>")
        out.append(f"<text x='10' y='20' fill='#e2e8f0' font-size='12'>day {s_['day']:g}, {s_['n']} of "
                   f"{g.get('fragments_true', 0):,.0f} fragments sampled (static view)</text>")
    out.append("</svg>")
    return "".join(out)
