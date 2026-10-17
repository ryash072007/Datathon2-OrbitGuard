"""Deterministic markdown brief. Every number comes from the facts dict (so it always passes the guard)."""
from __future__ import annotations

DIRECTION_WORDS = {"+T": "prograde along-track", "-T": "retrograde along-track", "+R": "radial-out",
                   "-R": "radial-in", "+N": "cross-track (normal)", "-N": "cross-track (anti-normal)"}


def _burn_line(b: dict, rank: int) -> str:
    where = DIRECTION_WORDS.get(b.get("direction", ""), b.get("direction", "?"))
    lead = f", {b['lead_periods']:g} orbits before closest approach" if b.get("lead_periods") else ""
    conj = ("creates no new close approach" if not b.get("new_conjunctions")
            else f"creates {b['new_conjunctions']} new close approach(es)")
    ok = "meets the miss target" if b.get("feasible") else "does not meet the miss target"
    pc = f"; worst-case Pc {b['worst_pc']:.1e}" if b.get("worst_pc") is not None else ""
    return (f"{rank}. {b['burn_id']}: {where} burn, {b['dv_mps']:g} m/s{lead}. Miss {b['miss_km_threat']:.1f} km; "
            f"{conj}; {ok}{pc}.")


def render_template(facts: dict) -> str:
    ev = facts.get("event", {})
    p, t = ev.get("primary", {}), ev.get("threat", {})
    risk = facts.get("risk", {})
    burns = facts.get("burns", {})
    cons = facts.get("consequence")
    net = facts.get("network")
    lines: list[str] = []

    lines += ["## Situation",
              f"{p.get('name', '?')} (NORAD {p.get('norad', '?')}) has a predicted close approach with "
              f"{t.get('name', '?')} (NORAD {t.get('norad', '?')}) at {ev.get('tca_utc', '?')} UTC, "
              f"miss distance {ev.get('miss_km', 0):.2f} km.", ""]

    lines.append("## Risk")
    if risk.get("live_pc") is not None:
        worst = (f" (worst case over 0.5x to 2x the assumed error: {risk['live_pc_worst']:.1e})"
                 if risk.get("live_pc_worst") is not None else "")
        lines.append(f"Estimated collision probability from public orbit data: {risk['live_pc']:.1e}{worst}. "
                     f"Public orbit data has no covariance, so the position error is assumed; treat it as a "
                     f"screening indicator.")
    dec = risk.get("decision")
    if dec and "action" in dec:
        lines.append(f"Decision-layer demo ({dec['label']}, ESA event {dec['cdm_event_id']}, not this "
                     f"conjunction): {dec['action']}, predicted risk {dec['predicted_risk_log10_pc']:.2f} "
                     f"(log10 Pc), probability of high final risk {dec['p_high']:.2f}.")
    lines.append("")

    lines.append("## Options")
    top = burns.get("top", [])[:3]
    if top:
        lines.append(f"Baseline miss without a burn is {burns.get('baseline_miss_km', 0):.2f} km; "
                     f"{burns.get('n_feasible', 0)} of {burns.get('n_screened', 0)} candidate burns reach the "
                     f"{burns.get('target_km', 0):g} km target. Top options:")
        lines += [_burn_line(b, i + 1) for i, b in enumerate(top)]
        lines.append("Trade-off: a larger delta-v buys more miss distance, and earlier burns need less "
                     "delta-v but give more time for new conflicts to appear.")
    else:
        lines.append("No burn options were screened.")
    lines.append("")

    lines.append("## Consequence if no action")
    if cons:
        kind = "catastrophic" if cons.get("catastrophic") else "non-catastrophic"
        cs = cons.get("exposed_by_constellation") or {}
        top_c = max(cs, key=cs.get) if cs else None
        asm = cons.get("assumptions", {})
        txt = (f"A collision would be {kind} and release about {cons['fragments_true']:,.0f} fragments of "
               f"{asm.get('min_fragment_cm', 10)} cm or more. Over {asm.get('horizon_days', 30)} days "
               f"{cons['n_sats_ge1_encounter']:,} of {cons['n_sats_considered']:,} active LEO satellites would "
               f"expect at least one pass within {asm.get('encounter_radius_km', 1):g} km. "
               f"Expected harm (Pc times encounters): {cons['expected_harm']:.1e}.")
        if top_c:
            txt += f" Most exposed group: {top_c} ({cs[top_c]})."
        lines.append(txt)
    else:
        lines.append("Consequence analysis not available.")
    if net:
        def one(label: str, d: dict) -> str:
            if d.get("listed"):
                return f"{label} ranks {d['rank']} of {net['n_nodes_listed']} listed super-spreaders (score {d['score']:.2f})"
            return f"{label} is not among the {net['n_nodes_listed']} listed super-spreaders"
        lines.append("Network context: " + "; ".join([one(p.get("name", "primary"), net["primary"]),
                                                       one(t.get("name", "threat"), net["threat"])]) + ".")
    lines.append("")

    lines.append("## Recommendation")
    pol = burns.get("policies")
    if pol and pol.get("status"):
        og, pair, thr = pol.get("orbitguard"), pol.get("pair_only"), pol.get("pc_threshold")
        if pol["status"] == "recommended" and og:
            lines.append(f"Consider {og['burn_id']}: the lowest delta-v option ({og['dv_mps']:g} m/s) that meets the "
                         f"miss target with every screened encounter at or below Pc {thr:.0e}, even at twice the "
                         f"assumed position error. The operator decides whether to execute.")
        elif pol["status"] == "no_action":
            lines.append("No burn is needed: the current trajectory meets the miss target and every Pc check. "
                         "Continue monitoring and refresh with the next orbit update.")
        else:
            lines.append("No screened burn passes every check, so no manoeuvre is recommended. Escalate to the "
                         "flight dynamics team before committing fuel.")
        if pair and pair.get("introduced_secondary_hazard"):
            lines.append(f"A pair-only check would choose {pair['burn_id']}, which pushes another object "
                         f"(NORAD {pair['worst_other_norad']}) to Pc {pair['worst_other_pc']:.1e}.")
    elif not top:
        lines.append("Escalate to the flight dynamics team for manual analysis.")
    elif burns.get("baseline_miss_km", 0) >= burns.get("target_km", 0):
        lines.append("The predicted miss already exceeds the target, so continue monitoring and refresh with "
                     "the next orbit update.")
    else:
        clean = [b for b in top if b.get("feasible") and not b.get("new_conjunctions")]
        if clean:
            lines.append(f"Consider {clean[0]['burn_id']} as the first candidate. It meets the target without "
                         f"creating a new close approach. The operator decides whether to execute.")
        else:
            lines.append("No screened burn is both sufficient and conflict-free; escalate to the operator "
                         "before committing fuel.")
    lines.append("")

    lines += ["## Uncertainties",
              "Public orbit data carries no covariance, so the probability is approximate. Object masses are "
              "assumed by type. Burn effects use a simplified perturbation model. Consequence figures are for "
              "relative ranking, not absolute prediction. This is decision support, not an autonomous command."]
    return "\n".join(lines)
