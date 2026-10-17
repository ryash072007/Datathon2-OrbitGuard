"""Public interface: predict_risk(cdms) -> predicted final log10 Pc for one event."""
from __future__ import annotations

import pandas as pd

from src.risk.features import MIN_TTCA_DAYS, build_table

_ART: dict | None = None


def _load() -> dict:
    global _ART
    if _ART is None:
        import joblib

        from src.risk.train import MODEL_PATH
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"{MODEL_PATH} missing: run `python -m src.risk.train`")
        _ART = joblib.load(MODEL_PATH)
    return _ART


def predict_risk(cdms: pd.DataFrame) -> float:
    """CDM rows of ONE event -> predicted final log10 Pc (uses CDMs with time_to_tca >= 2)."""
    from src.risk.train import predict_table
    u = cdms[cdms["time_to_tca"] >= MIN_TTCA_DAYS]
    if u.empty:
        raise ValueError("Event has no CDMs with time_to_tca >= 2 days")
    tab = build_table(u.assign(event_id=0))
    return float(predict_table(_load(), tab)[0])
