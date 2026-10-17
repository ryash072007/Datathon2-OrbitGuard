"""Feature construction for the CDM risk model (one row per event)."""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_TTCA_DAYS = 2.0
CAT_COLS = ["c_object_type", "mission_id"]
TREND_COLS = [
    "n_cdms", "risk_first", "risk_min", "risk_max", "risk_mean", "risk_std",
    "risk_slope", "risk_delta_last2", "miss_distance_delta_last2", "time_span_days",
]


def _usable(df: pd.DataFrame) -> pd.DataFrame:
    u = df[df["time_to_tca"] >= MIN_TTCA_DAYS]
    return u.sort_values(["event_id", "time_to_tca"], ascending=[True, False], kind="stable")


def build_table(df: pd.DataFrame, labels: pd.Series | None = None) -> pd.DataFrame:
    """One row per event_id from CDMs with time_to_tca >= 2. Index = event_id.

    labels: optional Series indexed by event_id; added as column 'target'
    (events missing from labels are dropped).
    """
    u = _usable(df)
    if u.empty:
        raise ValueError("No CDMs with time_to_tca >= 2 days")
    g = u.groupby("event_id", sort=True)
    last = g.tail(1).set_index("event_id").sort_index()
    out = last.copy()

    r = g["risk"]
    out["n_cdms"] = g.size().astype(float)
    out["risk_first"] = r.first()
    out["risk_min"] = r.min()
    out["risk_max"] = r.max()
    out["risk_mean"] = r.mean()
    out["risk_std"] = r.std(ddof=0)
    # slope of risk vs time_to_tca (least squares), 0 if 1 CDM or constant time
    u2 = pd.DataFrame({"event_id": u["event_id"], "time_to_tca": u["time_to_tca"], "risk": u["risk"],
                       "_tr": u["time_to_tca"] * u["risk"], "_tt": u["time_to_tca"] ** 2})
    g2 = u2.groupby("event_id", sort=True)
    n = g2.size()
    st, sr = g2["time_to_tca"].sum(), g2["risk"].sum()
    str_, stt = g2["_tr"].sum(), g2["_tt"].sum()
    den = n * stt - st ** 2
    num = n * str_ - st * sr
    slope = (num / den.where(den.abs() > 1e-12)).fillna(0.0)
    out["risk_slope"] = slope
    out["risk_delta_last2"] = _delta_last2(u, "risk")
    out["miss_distance_delta_last2"] = _delta_last2(u, "miss_distance")
    out["time_span_days"] = g["time_to_tca"].max() - g["time_to_tca"].min()
    out["naive_risk"] = out["risk"]
    out["c_object_type"] = out["c_object_type"].astype(str)
    if labels is not None:
        out["target"] = labels.reindex(out.index)
        out = out[out["target"].notna()]
    return out


def _delta_last2(u: pd.DataFrame, col: str) -> pd.Series:
    """last - second-to-last value per event (0 if only one CDM). u must be sorted."""
    d = u[col] - u.groupby("event_id", sort=True)[col].shift(1)
    d = pd.Series(d.to_numpy(), index=u["event_id"].to_numpy())
    # sorted by descending time_to_tca, so the last row of each event is the latest CDM
    return d.groupby(level=0, sort=True).last().fillna(0.0)


def event_features(cdms: pd.DataFrame) -> dict:
    """Features for ONE event's CDMs (rows with time_to_tca >= 2 only)."""
    u = cdms[cdms["time_to_tca"] >= MIN_TTCA_DAYS]
    if u.empty:
        raise ValueError("Event has no CDMs with time_to_tca >= 2 days")
    u = u.assign(event_id=0)
    row = build_table(u).iloc[0].to_dict()
    row.pop("event_id", None)
    return row
