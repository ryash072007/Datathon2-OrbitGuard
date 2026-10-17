"""Object type and mass assumptions. ALL masses are rough approximations, collected in ASSUMPTIONS."""
from __future__ import annotations

import re

from orbitguard.catalog.catalog import DEBRIS_GROUPS, CatalogRecord

DEBRIS, ROCKET_BODY, PAYLOAD = "DEBRIS", "ROCKET BODY", "PAYLOAD"
ISS_NORAD = 25544

ASSUMPTIONS: dict[str, object] = {
    "note": "APPROXIMATE masses (kg); public catalogues carry no mass data",
    "mass_kg_by_type": {DEBRIS: 10.0, ROCKET_BODY: 1500.0, PAYLOAD: 500.0},
    "mass_kg_by_name_prefix": {"STARLINK": 800.0, "ONEWEB": 150.0},
    "mass_kg_by_norad": {ISS_NORAD: 420000.0},
}

_DEB_RE = re.compile(r"\bDEB\b")


def object_type(rec: CatalogRecord) -> str:
    name = rec.name.upper()
    if rec.group in DEBRIS_GROUPS or _DEB_RE.search(name):
        return DEBRIS
    if " R/B" in name:
        return ROCKET_BODY
    return PAYLOAD


def object_mass_kg(rec: CatalogRecord) -> float:
    by_id = ASSUMPTIONS["mass_kg_by_norad"]
    if rec.norad in by_id:
        return float(by_id[rec.norad])
    name = rec.name.upper()
    for prefix, m in ASSUMPTIONS["mass_kg_by_name_prefix"].items():
        if name.startswith(prefix):
            return float(m)
    return float(ASSUMPTIONS["mass_kg_by_type"][object_type(rec)])
