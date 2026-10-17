"""CelesTrak catalogue download, TLE parsing and a shell-density criticality proxy.

Stdlib-only download, cached under ``<DATA_DIR>/raw/celestrak/<group>.tle`` and refreshed only when the
cached file is older than ``MAX_AGE_H`` hours (CelesTrak rate-limits repeat downloads).
"""
from __future__ import annotations

import math
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MU_KM3_S2 = 398600.4418  # WGS-72 value is close enough for altitude bands
RE_KM = 6378.137
BASE_URL = "https://celestrak.org/NORAD/elements/gp.php"
DEBRIS_GROUPS = ("cosmos-1408-debris", "fengyun-1c-debris", "iridium-33-debris", "cosmos-2251-debris")
GROUPS = ("active",) + DEBRIS_GROUPS
# TLE_MAX_AGE_H=1e9 freezes the cached snapshot (reproducible demo across machines).
MAX_AGE_H = float(os.environ.get("TLE_MAX_AGE_H", "6.0"))
USER_AGENT = "IBM-Z-Datathon-2026-collision-screener/0.1 (educational hackathon project)"
SHELL_MARGIN_KM = 25.0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else repo_root() / "data"


@dataclass
class CatalogRecord:
    name: str
    norad: int
    line1: str
    line2: str
    group: str
    perigee_km: float
    apogee_km: float
    crit: float = 0.0

    @property
    def tle(self) -> tuple[str, str]:
        return (self.line1, self.line2)


def altitudes_from_tle(line1: str, line2: str) -> tuple[float, float]:
    """Perigee and apogee altitude (km above equatorial radius) from mean motion and eccentricity."""
    ecc = float("0." + line2[26:33].strip())
    n_rev_day = float(line2[52:63])
    if n_rev_day <= 0:
        raise ValueError("non-positive mean motion")
    n_rad_s = n_rev_day * 2.0 * math.pi / 86400.0
    a_km = (MU_KM3_S2 / n_rad_s**2) ** (1.0 / 3.0)
    return a_km * (1.0 - ecc) - RE_KM, a_km * (1.0 + ecc) - RE_KM


def period_min_from_tle(line2: str) -> float:
    return 1440.0 / float(line2[52:63])


def record_from_tle(name: str, line1: str, line2: str, group: str = "") -> CatalogRecord:
    perigee, apogee = altitudes_from_tle(line1, line2)
    return CatalogRecord(name.strip(), int(line1[2:7]), line1.rstrip(), line2.rstrip(), group, perigee, apogee)


def parse_tle_text(text: str, group: str = "") -> list[CatalogRecord]:
    """Parse 3-line (name + 2 lines) or bare 2-line TLE text. Malformed entries are skipped."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out: list[CatalogRecord] = []
    i = 0
    while i < len(lines) - 1:
        if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
            name = lines[i - 1] if i > 0 and not lines[i - 1].startswith(("1 ", "2 ")) else f"NORAD {lines[i][2:7]}"
            try:
                out.append(record_from_tle(name, lines[i], lines[i + 1], group))
            except (ValueError, IndexError):
                pass  # malformed/decayed entry: skip, the rest of the catalogue is still valid
            i += 2
        else:
            i += 1
    return out


def compute_criticality(records: list[CatalogRecord], margin_km: float = SHELL_MARGIN_KM) -> None:
    """Fill ``record.crit`` in place with a shell-density criticality proxy in [0, 1].

    PROXY ONLY (we have no mass or cross-section data): for each object, count catalogue objects whose
    perigee-apogee band overlaps this object's band widened by +-margin_km, then divide by the maximum count.
    The intuition is that a new conjunction in a crowded shell is more likely to feed a debris cascade.
    """
    if not records:
        return
    peri = np.array([r.perigee_km for r in records])
    apo = np.array([r.apogee_km for r in records])
    sp, sa = np.sort(peri), np.sort(apo)
    n = len(records)
    # overlap <=> peri_j <= apo_i + m  and  apo_j >= peri_i - m ; the two excluded sets are disjoint
    no_above = n - np.searchsorted(sp, apo + margin_km, side="right")
    no_below = np.searchsorted(sa, peri - margin_km, side="left")
    count = n - no_above - no_below
    crit = count / max(count.max(), 1)
    for r, c in zip(records, crit):
        r.crit = float(c)


def _cache_path(group: str, cache_dir: Path) -> Path:
    return cache_dir / f"{group}.tle"


def fetch_group(group: str, cache_dir: Path | None = None, max_age_h: float = MAX_AGE_H,
                force: bool = False) -> Path:
    cache_dir = cache_dir or data_dir() / "raw" / "celestrak"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(group, cache_dir)
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_h * 3600
    if fresh and not force:
        return path
    url = f"{BASE_URL}?GROUP={group}&FORMAT=tle"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
        if "1 " not in body or len(body) < 100:
            raise ValueError(f"unexpected CelesTrak response for {group}: {body[:80]!r}")
        path.write_text(body, encoding="utf-8", newline="\n")
    except (urllib.error.URLError, ValueError, OSError) as exc:
        if path.exists():
            print(f"WARNING: download of {group} failed ({exc}); using stale cache", file=sys.stderr)
        else:
            raise RuntimeError(f"cannot download {group} and no cache exists: {exc}") from exc
    return path


def load_catalog(groups: tuple[str, ...] = GROUPS, cache_dir: Path | None = None,
                 force: bool = False) -> list[CatalogRecord]:
    """Download (or read cache of) all groups, de-duplicate by NORAD id, attach criticality."""
    seen: dict[int, CatalogRecord] = {}
    for g in groups:
        path = fetch_group(g, cache_dir, force=force)
        for rec in parse_tle_text(path.read_text(encoding="utf-8"), g):
            seen.setdefault(rec.norad, rec)
    records = list(seen.values())
    compute_criticality(records)
    return records


def co_orbiting(a: CatalogRecord, b: CatalogRecord) -> bool:
    """True for objects sharing essentially the same orbit (docked/attached modules, e.g. ISS elements).

    Such pairs sit permanently within metres-to-km of each other, which is not a conjunction.
    """
    def el(r: CatalogRecord) -> tuple[float, float, float]:
        return float(r.line2[8:16]), float(r.line2[17:25]), float(r.line2[52:63])
    ia, ra, na = el(a)
    ib, rb, nb = el(b)
    d_raan = abs((ra - rb + 180.0) % 360.0 - 180.0)
    return abs(ia - ib) < 0.05 and d_raan < 0.05 and abs(na - nb) < 0.005
