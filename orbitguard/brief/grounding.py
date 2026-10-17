"""Grounding guard: every number in an LLM brief must be traceable to the facts dict.

Matching is tolerant to rounding (a written number is accepted if it equals a fact rounded to the written
precision), to scientific notation, to percentages (fact x 100) and to common unit changes (x 1e3, x 1e-3,
x 1e6, x 1e-6). Signs are ignored. Small integers 0-3 are always allowed (list numbering, "top 3").
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

NUM_RE = re.compile(r"(?<![\w.])[-+−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?|\d{1,2}:\d{2}(:\d{2})?")
LIST_MARK_RE = re.compile(r"^\s*(?:[-*]\s+)?\d+[.)]\s+", re.M)
UNIT_SCALES = (1.0, 100.0, 1e3, 1e-3, 1e6, 1e-6, 60.0, 1.0 / 60.0)
FREE_INTS = {0, 1, 2, 3}
# The Pc sensitivity sweep multipliers ("0.5x to 2x the assumed error") are method constants, not event facts.
SWEEP_RE = re.compile(r"(?<![\w.])(?:0\.5|1|2)\s?x(?![a-zA-Z])")


def _walk(obj, out: list[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if obj == obj and abs(obj) != float("inf"):
            out.append(abs(float(obj)))
    elif isinstance(obj, str):
        out.extend(abs(v) for v in _parse_all(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk(k, out)
            _walk(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            _walk(v, out)


def _parse_all(text: str) -> list[float]:
    vals = []
    for tok in NUM_RE.findall(text):
        try:
            vals.append(float(tok.replace(",", "").replace("−", "-")))
        except ValueError:
            continue
    # digits inside dates/times also count as facts (e.g. 2026, 10, 18, 04, 48)
    for m in DATE_RE.finditer(text):
        for tok in re.findall(r"\d+(?:\.\d+)?", m.group(0)):
            vals.append(float(tok))
    return vals


def fact_numbers(facts: dict) -> list[float]:
    """All numbers (absolute values) reachable in the facts, including digits inside strings."""
    out: list[float] = []
    _walk(facts, out)
    return out


def _tolerance(token: str) -> tuple[float, float]:
    """(value, half-unit of the last written digit)."""
    tok = token.replace(",", "").replace("−", "-").lstrip("+-")
    d = Decimal(tok)
    exp = d.as_tuple().exponent
    if exp == 0 and abs(d) >= 1000:  # "11,300" written as a rounded number: last non-zero digit is the unit
        exp = d.normalize().as_tuple().exponent
    return abs(float(d)), 0.5 * 10.0 ** exp


def _grounded(token: str, facts_abs: list[float]) -> bool:
    try:
        val, tol = _tolerance(token)
    except InvalidOperation:
        return True  # not a parseable number: nothing to check
    if val in FREE_INTS and re.fullmatch(r"\d", token):
        return True
    for f in facts_abs:
        for s in UNIT_SCALES:
            g = f * s
            # A unit-scaled match only means something if the written precision resolves the value (within 5%):
            # otherwise "0.1" or "0.0" would be "grounded" by a scaled copy of almost any fact.
            if s != 1.0 and tol > 0.05 * abs(g):
                continue
            if abs(g - val) <= tol * (1 + 1e-9) + 1e-12 * max(abs(g), 1.0):
                return True
    return False


def check_grounding(text: str, facts: dict) -> list[str]:
    """Return the numbers in ``text`` that cannot be traced to ``facts`` (empty list = grounded)."""
    facts_abs = fact_numbers(facts)
    body = SWEEP_RE.sub(" ", DATE_RE.sub(" ", LIST_MARK_RE.sub("", text.replace("−", "-"))))
    bad: list[str] = []
    for m in NUM_RE.finditer(body):
        tok = m.group(0)
        if tok not in bad and not _grounded(tok, facts_abs):
            bad.append(tok)
    return bad
