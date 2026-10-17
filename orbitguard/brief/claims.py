"""Deterministic categorical claim checker: the second guard layer, for what the numeric guard cannot see.

The numeric guard proves every number is traceable. This checks CATEGORICAL claims against the facts dict with
regular expressions and no model: the direction words used for a named burn, whether the text recommends a burn,
no action, or escalation (versus the Pc-gated recommendation), NORAD ids and the name written before them, whether
the pair-only burn is described as safe, and overconfident phrases. It is deliberately conservative: it only fires
on a sentence it can attribute (one burn id per sentence, a NORAD id with a known owner), so a good brief should
never be flagged. It cannot catch a wrong claim that has no such anchor; that is stated in the evidence report.

``check_claims(text, facts)`` returns a list of human-readable issues (empty = nothing contradicted).
"""
from __future__ import annotations

import re

from .grounding import fact_numbers

BURN_ID = r"[+-][RTN]_[\d.]+_[\d.]+P"
BURN_RE = re.compile(BURN_ID)
SPECIFIC = (  # (regex, directions it asserts), most specific first
    (re.compile(r"retrograde", re.I), {"-T"}), (re.compile(r"prograde", re.I), {"+T"}),
    (re.compile(r"radial[- ]out", re.I), {"+R"}), (re.compile(r"radial[- ]in", re.I), {"-R"}),
    (re.compile(r"anti-normal", re.I), {"-N"}), (re.compile(r"(?<!anti-)\bnormal\b", re.I), {"+N"}))
GENERIC = (
    (re.compile(r"along[- ]track", re.I), {"+T", "-T"}), (re.compile(r"cross[- ]track", re.I), {"+N", "-N"}),
    (re.compile(r"\bradial\b", re.I), {"+R", "-R"}))
NO_ACTION_RE = re.compile(r"no burn is needed|no manoeuvre is recommended|no maneuver is recommended|"
                          r"no (?:avoidance )?action is (?:needed|required|necessary)|no screened burn passes|"
                          r"can be left to pass|no manoeuvre is needed|no maneuver is needed", re.I)
RECOMMENDS_RE = re.compile(rf"\b(?:consider|execute|fire|perform|recommend(?:ed)?(?: burn)?)\s+({BURN_ID})", re.I)
SAFE_RE = re.compile(r"\b(?:is|are|remains?|looks?|appears?)\s+(?:completely |entirely |totally |perfectly |also )?safe\b|"
                     r"\bno (?:secondary|new|additional|other) (?:hazard|risk|conflict|danger)|"
                     r"\bintroduc\w+ no\b|\b(?:does|do) not (?:introduce|create|push|cause)\b|\bharmless\b|\bwithout (?:any )?hazard", re.I)
HAZARD_RE = re.compile(r"pushes another object|introduces? a secondary hazard|creates? a secondary hazard", re.I)
OVERCONFIDENT_RE = re.compile(
    r"\bguarantee[sd]?\b|\bno risk\b|\bzero risk\b|\brisk[- ]free\b|\b(?:completely|entirely|totally|absolutely|perfectly) safe\b|"
    r"\bwill (?:certainly |definitely |inevitably )?(?:collide|destroy|be destroyed)\b|"
    r"\b(?:certain|certainly|definitely) (?:to )?(?:collide|destroy|be destroyed)\b|\b100 ?% (?:safe|certain|sure)\b|"
    r"\beliminat\w+ (?:the |all )?(?:collision )?(?:risk|danger)\b|\bno (?:remaining )?uncertaint", re.I)
NORAD_RE = re.compile(r"NORAD\s+(\d+)", re.I)


def _sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.split("\n"):
        parts += re.split(r"(?<=[.;!?])\s+(?=[A-Z0-9\-+*])", line)
    return [p.strip() for p in parts if p.strip()]


def _burns(facts: dict) -> dict[str, dict]:
    b = facts.get("burns", {}) or {}
    pol = b.get("policies") or {}
    out: dict[str, dict] = {}
    for r in list(b.get("top", [])) + list(b.get("table") or []) + list(facts.get("burn_table") or []) + [
            pol.get("orbitguard"), pol.get("pair_only")]:
        if r and r.get("burn_id"):
            out[r["burn_id"]] = r
    return out


def _direction_issue(sentence: str, burns: dict[str, dict]) -> str | None:
    ids = set(BURN_RE.findall(sentence))
    if len(ids) != 1:
        return None  # ambiguous: stay silent
    bid = next(iter(ids))
    row = burns.get(bid)
    if not row or not row.get("direction"):
        return None
    d = row["direction"]
    for rx, dirs in SPECIFIC:
        if rx.search(sentence):
            return None if d in dirs else f"burn {bid} is {d} but the text calls it {rx.pattern}"
    for rx, dirs in GENERIC:
        if rx.search(sentence) and d not in dirs:
            return f"burn {bid} is {d} but the text places it {rx.pattern}"
    return None


def check_claims(text: str, facts: dict, *, action: bool = True) -> list[str]:
    """Contradictions between categorical claims in ``text`` and ``facts``. ``action=False`` skips the
    recommendation-versus-policy rule (for free-form answers about hypothetical burns)."""
    issues: list[str] = []
    burns = _burns(facts)
    sents = _sentences(text)
    pol = (facts.get("burns") or {}).get("policies") or {}
    status = pol.get("status")
    rec_id = (pol.get("orbitguard") or {}).get("burn_id")
    pair = pol.get("pair_only") or {}

    for s in sents:
        i = _direction_issue(s, burns)
        if i:
            issues.append("direction: " + i)

    if action and status:
        for s in sents:
            if status == "recommended" and NO_ACTION_RE.search(s):
                issues.append(f"action: text says no burn/escalate but the recommendation is {rec_id}")
            if re.search(r"pair[- ]only", s, re.I):
                continue  # describes what the naive check would pick, not the recommendation
            for m in RECOMMENDS_RE.finditer(s):
                if status == "recommended" and m.group(1) != rec_id:
                    issues.append(f"action: text recommends {m.group(1)} but the recommendation is {rec_id}")
                if status in ("abstained", "no_action"):
                    issues.append(f"action: text recommends {m.group(1)} but the status is {status}")
        if status == "no_action" and not any(re.search(r"no burn is needed|no (?:action|manoeuvre|maneuver)|monitor", s, re.I)
                                             for s in sents):
            issues.append("action: status is no_action but the text does not say so")
        if status == "abstained" and not any(re.search(r"escalate|no screened burn|no acceptable|no manoeuvre|no maneuver", s, re.I)
                                             for s in sents):
            issues.append("action: status is abstained but the text does not say to escalate")

    for s in sents:
        if re.search(r"pair[- ]only", s, re.I):
            if pair.get("introduced_secondary_hazard") and SAFE_RE.search(s):
                issues.append("pair-only: described as safe but the facts show it introduces a secondary hazard")
            elif pair and not pair.get("introduced_secondary_hazard") and HAZARD_RE.search(s):
                issues.append("pair-only: described as hazardous but the facts show no secondary hazard")

    ev = facts.get("event", {}) or {}
    owners = {o.get("norad"): o.get("name") for o in (ev.get("primary"), ev.get("threat")) if o}
    known = {int(x) for x in fact_numbers(facts) if x == int(x)}
    for m in NORAD_RE.finditer(text):
        n = int(m.group(1))
        if n not in known:
            issues.append(f"object: NORAD {n} is not in the facts")
        elif n in owners and owners[n] and owners[n] not in text[max(0, m.start() - len(owners[n]) - 6):m.start()]:
            issues.append(f"object: NORAD {n} belongs to {owners[n]}, which is not the name written before it")

    for m in OVERCONFIDENT_RE.finditer(text):
        issues.append(f"overconfident: '{m.group(0)}'")
    return list(dict.fromkeys(issues))
