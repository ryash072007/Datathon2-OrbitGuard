"""Candidate manoeuvre grid.

Directions are in the primary's RTN frame: +-R radial, +-T along-track (transverse), +-N cross-track (normal).

Along-track (+-T) burns are marked ``analytic_seed``: for long lead times in LEO an along-track burn is
near-optimal because a small change of semi-major axis changes the mean motion and the resulting in-track
displacement grows linearly with time (Bombardelli group, https://oa.upm.es/51461/). The grid still evaluates
all six directions so the screener can confirm (or refute) this on real data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DIRECTIONS = ("+T", "-T", "+R", "-R", "+N", "-N")
DV_MPS_GRID = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5)
LEAD_PERIODS = (0.5, 1.0, 2.0, 3.0)

# direction -> unit vector in (R, T, N)
DIRECTION_VECTORS = {
    "+R": (1.0, 0.0, 0.0), "-R": (-1.0, 0.0, 0.0),
    "+T": (0.0, 1.0, 0.0), "-T": (0.0, -1.0, 0.0),
    "+N": (0.0, 0.0, 1.0), "-N": (0.0, 0.0, -1.0),
}


@dataclass(frozen=True)
class Burn:
    burn_id: str
    direction: str  # one of DIRECTIONS, or "none" for the no-burn baseline
    dv_mps: float
    burn_time: datetime  # UTC
    lead_periods: float = 0.0

    @property
    def analytic_seed(self) -> bool:
        return self.direction in ("+T", "-T")

    def dv_rtn_kms(self) -> tuple[float, float, float]:
        if self.direction == "none" or self.dv_mps == 0.0:
            return (0.0, 0.0, 0.0)
        u = DIRECTION_VECTORS[self.direction]
        s = self.dv_mps / 1000.0
        return (u[0] * s, u[1] * s, u[2] * s)


def burn_grid(tca: datetime, period_min: float, earliest: datetime | None = None,
              dv_mps: tuple[float, ...] = DV_MPS_GRID,
              lead_periods: tuple[float, ...] = LEAD_PERIODS) -> list[Burn]:
    """6 directions x dv x lead times, plus one no-burn baseline. Burns before ``earliest`` are dropped."""
    if tca.tzinfo is None:
        tca = tca.replace(tzinfo=timezone.utc)
    burns: list[Burn] = []
    for lead in lead_periods:
        t_b = (tca - timedelta(minutes=lead * period_min)).replace(microsecond=0)
        if earliest is not None and t_b < earliest:
            continue
        for d in DIRECTIONS:
            for dv in dv_mps:
                burns.append(Burn(f"{d}_{dv:g}_{lead:g}P", d, dv, t_b, lead))
    if not burns:
        raise ValueError("no burn lead time fits between 'earliest' and the TCA")
    burns.append(Burn("none", "none", 0.0, min(b.burn_time for b in burns), 0.0))
    return burns
