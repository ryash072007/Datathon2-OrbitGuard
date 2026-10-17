"""Validate the SBM fragment count against real break-ups: python -m src.consequence.validate

Compares our predicted number of >=10 cm fragments with the number of catalogued debris objects in CelesTrak
SATCAT (matched by international-designator launch prefix, OBJECT_TYPE == DEB, decayed objects included).
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

from .breakup import ejected_mass_kg, is_catastrophic, n_fragments

SATCAT_URL = "https://celestrak.org/pub/satcat.csv"
CACHE = Path("data/raw/celestrak/satcat.csv")
OUT_JSON = Path("data/out/validation.json")
OUT_MD = Path("docs/validation.md")

# All masses approximate (public reporting; see docs/validation.md).
EVENTS = [
    {"event": "Iridium 33 / Cosmos 2251 (2009-02-10)", "prefixes": ["1997-051", "1993-036"],
     "norad": {"1997-051C": 24946, "1993-036A": 22675}, "m1": 560.0, "m2": 900.0, "v_rel_kms": 11.7,
     "mass_note": "Iridium 33 ~560 kg (689 kg quoted by some sources; 560 used) + Cosmos 2251 ~900 kg, ~11.7 km/s"},
    {"event": "Fengyun-1C ASAT (2007-01-11)", "prefixes": ["1999-025"], "norad": {"1999-025A": 25730},
     "m1": 880.0, "m2": 600.0, "v_rel_kms": 9.0,
     "mass_note": "target ~880 kg + kill vehicle ~600 kg (uncertain), ~9 km/s"},
    {"event": "Cosmos 1408 ASAT (2021-11-15)", "prefixes": ["1982-092"], "norad": {"1982-092A": 13552},
     "m1": 1750.0, "m2": None, "v_rel_kms": None,
     "mass_note": "target ~1750 kg; interceptor mass unknown, treated as catastrophic with M = target mass"},
]


def load_satcat(max_age_s: float = 86400.0) -> pd.DataFrame:
    if not CACHE.exists() or time.time() - CACHE.stat().st_mtime > max_age_s:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(SATCAT_URL, headers={"User-Agent": "datathon-validate"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if not data.startswith(b"OBJECT_NAME"):
                raise ValueError("download did not look like the expected CSV")
            CACHE.write_bytes(data)
        except Exception as exc:  # noqa: BLE001
            if CACHE.exists():
                print(f"[warn] SATCAT refresh failed ({exc}); using stale cache")
            else:
                raise SystemExit(f"Cannot download SATCAT from {SATCAT_URL}: {exc}") from exc
    df = pd.read_csv(CACHE, dtype=str, keep_default_na=False)
    need = {"OBJECT_ID", "NORAD_CAT_ID", "OBJECT_TYPE", "DECAY_DATE"}
    if not need <= set(df.columns):
        raise SystemExit(f"SATCAT columns changed: missing {need - set(df.columns)}")
    return df


def predicted_ge10cm(ev: dict) -> tuple[float, float]:
    if ev["m2"] is None:
        mass = ev["m1"]
    else:
        if not is_catastrophic(ev["m1"], ev["m2"], ev["v_rel_kms"]):
            raise ValueError("expected a catastrophic collision")
        mass = ejected_mass_kg(ev["m1"], ev["m2"], ev["v_rel_kms"])
    return n_fragments(mass), mass


def run() -> list[dict]:
    df = load_satcat()
    rows = []
    for ev in EVENTS:
        for iid, norad in ev["norad"].items():  # verify parent identities against SATCAT
            m = df[df.OBJECT_ID == iid]
            if m.empty or int(m.NORAD_CAT_ID.iloc[0]) != norad:
                raise SystemExit(f"SATCAT does not confirm {iid} = NORAD {norad}")
        deb = df[df.OBJECT_TYPE.eq("DEB") & df.OBJECT_ID.str.startswith(tuple(ev["prefixes"]))]
        total = len(deb)
        on_orbit = int((deb.DECAY_DATE == "").sum())
        pred, mass = predicted_ge10cm(ev)
        rows.append({"event": ev["event"], "predicted_ge10cm": round(pred), "ejected_mass_kg": mass,
                     "catalogued_total": total, "on_orbit_now": on_orbit,
                     "ratio_pred_over_catalogued": round(pred / total, 2) if total else None,
                     "mass_note": ev["mass_note"], "prefixes": ev["prefixes"]})
    return rows


def write_outputs(rows: list[dict]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({"satcat_source": SATCAT_URL, "events": rows}, indent=2), encoding="utf-8")
    lines = ["| Event | Predicted >=10 cm | Catalogued debris (all-time) | Still on orbit | Ratio pred/cat |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['event']} | {r['predicted_ge10cm']} | {r['catalogued_total']} | {r['on_orbit_now']} "
                     f"| {r['ratio_pred_over_catalogued']} |")
    table = "\n".join(lines)
    notes = "\n".join(f"- **{r['event']}**: {r['mass_note']}; SBM ejected mass M = {r['ejected_mass_kg']:.0f} kg."
                      for r in rows)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(f"""# Validation of the break-up model against real events

We run our simplified NASA Standard Breakup Model (`src/consequence/breakup.py`, N = 0.1 M^0.75 Lc^-1.71 for
Lc >= 10 cm) on three historical break-ups and compare the predicted fragment count with the number of debris
objects in the CelesTrak SATCAT for the same launch (international designator prefix, OBJECT_TYPE = DEB,
including objects that have since decayed). Reproduce with `python -m src.consequence.validate`.

{table}

Inputs (all masses approximate, from public reporting, not authoritative):

{notes}

## How to read this

- Order of magnitude is what matters. The public catalogue tracks only roughly >= 10 cm objects (less reliably
  at high altitude), detection is incomplete, and small or short-lived fragments may never be catalogued. The
  catalogued count is therefore a lower bound on true >= 10 cm fragments, not a precise target.
- The designator prefix can also include debris from other pieces of the same launch, and for Iridium/Cosmos
  both parents are pooled, so counts are approximate in both directions.
- Interceptor masses and the Cosmos 1408 treatment are assumptions. We do not claim accurate per-event
  prediction, only that the model is not off by orders of magnitude.
- Source data: CelesTrak SATCAT, fetched {today}.
""", encoding="utf-8")


def main() -> int:
    rows = run()
    write_outputs(rows)
    print(f"{'event':42s} {'pred>=10cm':>10s} {'catalogued':>10s} {'on orbit':>8s} {'ratio':>6s}")
    for r in rows:
        print(f"{r['event']:42s} {r['predicted_ge10cm']:>10d} {r['catalogued_total']:>10d} "
              f"{r['on_orbit_now']:>8d} {r['ratio_pred_over_catalogued']!s:>6s}")
    print(f"wrote {OUT_JSON} and {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
