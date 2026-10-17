import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, Clock, Loader2, Play, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { Empty, G, Loading, Notice, Status, Term, Tip, useAsync } from './ui';
import { finite, fixed, logProbability, number, percent, post, probability, request } from './api';
import type { Json } from './api';
import { AskOrbitGuard, SecondOpinion } from './AiEvidence';

const ISS = 25544;
const DIRECTIONS: Record<string, string> = {'+T': 'Prograde', '-T': 'Retrograde', '+R': 'Radial out', '-R': 'Radial in', '+N': 'Cross-track +', '-N': 'Cross-track −'};
const ACTION_TEXT: Record<string, string> = {
  ACT: 'Prepare an avoidance manoeuvre: the evidence points to a high final risk.',
  WAIT: 'Borderline: wait for the next message before committing fuel.',
  MONITOR: 'Keep monitoring. This is not a safety clearance.',
};

function Section({title, sub, action, children, label}: {title: ReactNode, sub?: ReactNode, action?: ReactNode, children: ReactNode, label?: string}) {
  return <section className="card section" aria-label={label}><div className="card-head"><div><h2>{title}</h2>{sub && <p className="muted small">{sub}</p>}</div>{action}</div>{children}</section>;
}

/** Poll the background-job registry while any job runs; call onDone when a watched key finishes. */
function useJobs(onDone: (key: string) => void) {
  const [jobs, setJobs] = useState<Json>({});
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    request<Json>('/live/status').then(s => {
      if (!alive) return;
      setJobs(prev => {
        for (const [k, j] of Object.entries<Json>(s.jobs || {})) if (prev[k]?.state === 'running' && j.state !== 'running') onDone(k);
        return s.jobs || {};
      });
    }).catch(() => undefined);
    const running = Object.values<Json>(jobs).some(j => j.state === 'running');
    const timer = window.setTimeout(() => setTick(t => t + 1), running ? 2000 : 8000);
    return () => {alive = false; window.clearTimeout(timer);};
  }, [tick]);
  return {jobs, kick: () => setTick(t => t + 1)};
}

function JobLine({job}: {job?: Json}) {
  if (!job) return null;
  if (job.state === 'running') return <span className="small muted job-line"><Loader2 size={12} className="spin"/> {job.label}: {number(job.elapsed_s, 0)} s</span>;
  if (job.state === 'error') return <span className="small job-line bad-text"><X size={12}/> {job.error}</span>;
  return <span className="small muted job-line"><Check size={12}/> finished in {number(job.elapsed_s, 0)} s</span>;
}

export function OperatorActions({context, reference, recommendation}: {context: 'live' | 'encounter' | 'planning', reference: string, recommendation?: Json}) {
  const [record, setRecord] = useState<Json | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {setRecord(null); setError('');}, [reference]);
  async function choose(choice: string) {
    setBusy(true); setError('');
    try {setRecord({...(await post('/audit/operator', {context, reference, choice, recommendation})), choice});}
    catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }
  return <div className="operator" aria-label="Operator decision">
    <span className="small muted">Operator decision <Tip text="The tool recommends; a person decides. Your choice is appended to a hash-chained audit log (each record includes the hash of the previous one), so the trail of recommendations and decisions cannot be silently edited."/></span>
    <div className="actions">
      <button className="btn small" disabled={busy} onClick={() => choose('accept')}><Check size={13}/> Accept</button>
      <button className="btn small" disabled={busy} onClick={() => choose('defer')}><Clock size={13}/> Defer</button>
      <button className="btn small" disabled={busy} onClick={() => choose('reject')}><X size={13}/> Reject</button>
    </div>
    {record && <span className="small"><ShieldCheck size={13} className="good-text"/> Logged “{record.choice}” as record #{record.seq} · <span className="mono">{String(record.record_hash).slice(0, 12)}…</span></span>}
    {error && <span className="small bad-text">{error}</span>}
  </div>;
}

export function DecisionCard({decision, eventId}: {decision?: Json, eventId: string}) {
  if (!decision) return null;
  if (decision.status !== 'ready') return <p className="footnote">Decision layer: {decision.message}</p>;
  const lo = decision.interval_log10_pc?.[0], hi = decision.interval_log10_pc?.[1];
  return <section className={`decision decision-${String(decision.action).toLowerCase()}`} aria-label="Recommended action">
    <div className="decision-head">
      <span className={`action-badge ${String(decision.action).toLowerCase()}`}>{decision.action}</span>
      <p>{ACTION_TEXT[decision.action] || ''}</p>
    </div>
    <div className="figures">
      <div className="figure"><span className="figure-label">P(final risk ≥ 10⁻⁶) <Tip text="Probability that the final reported Pc ends at or above the ESA high-risk threshold, from a calibrated logistic model (isotonic calibration, 5-fold) on the message history. ACT and WAIT thresholds were chosen on training data only."/></span><strong>{percent(decision.p_high)}</strong><span className="small muted">ACT ≥ {percent(decision.thresholds?.act, 0)}, WAIT ≥ {percent(decision.thresholds?.wait, 0)}</span></div>
      <div className="figure"><span className="figure-label">Decision-layer forecast <Tip text="The latest reported value adjusted by rules chosen with cross-validation on training encounters (for example, a borderline value just below 10⁻⁶ is promoted, a payload or very distant object is forced low)."/></span><strong>{logProbability(decision.predicted_log10_pc)}</strong></div>
      <div className="figure"><span className="figure-label">80% interval <Tip text="Quantile gradient-boosting models (10th and 90th percentile of the final log Pc). Honest but wide; see Validation for its measured coverage."/></span><strong className="interval">{logProbability(lo)} – {logProbability(hi)}</strong></div>
    </div>
    <SecondOpinion decision={decision}/>
    <details className="raw"><summary>Why ({(decision.reasons || []).length} reasons)</summary><ul className="limits">{(decision.reasons || []).map((r: string) => <li key={r}>{r}</li>)}</ul></details>
    <OperatorActions context="encounter" reference={eventId} recommendation={{action: decision.action, p_high: decision.p_high}}/>
  </section>;
}

function BriefText({text}: {text: string}) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {if (list.length) {blocks.push(<ul key={`l${blocks.length}`}>{list.map((l, i) => <li key={i}>{l}</li>)}</ul>); list = [];}};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) {flush(); continue;}
    if (line.startsWith('## ')) {flush(); blocks.push(<h3 key={`h${blocks.length}`}>{line.slice(3)}</h3>);}
    else if (/^([-*]|\d+[.)])\s+/.test(line)) list.push(line.replace(/^([-*]|\d+[.)])\s+/, ''));
    else {flush(); blocks.push(<p key={`p${blocks.length}`}>{line.replace(/\*\*/g, '')}</p>);}
  }
  flush();
  return <div className="brief">{blocks}</div>;
}

function Recommendation({facts}: {facts: Json}) {
  const burns = facts.burns || {};
  const pol = burns.policies || {};
  const og = pol.orbitguard, pair = pol.pair_only;
  const ok = pol.status === 'recommended' || pol.status === 'no_action';
  const headline = pol.status === 'recommended' && og ? `${DIRECTIONS[og.direction] || og.direction} burn of ${fixed(og.dv_mps, 2)} m/s, ${number(og.lead_periods, 1)} orbits before closest approach`
    : pol.status === 'no_action' ? 'No manoeuvre needed' : pol.status === 'abstained' ? 'No acceptable manoeuvre found' : 'Recommendation unavailable';
  return <section className={`card recommendation ${ok ? 'has-rec' : 'no-rec'}`} aria-live="polite">
    <div className="rec-main">
      <span className="label">Recommendation</span>
      <h2>{headline}</h2>
      <p>{pol.reason}</p>
      {pair?.introduced_secondary_hazard && <p className="finding"><strong>Pair-only check would be unsafe:</strong> the cheapest burn that clears the threat alone ({pair.burn_id}) raises the Pc with NORAD {pair.worst_other_norad} to {probability(pair.worst_other_pc)}.</p>}
      {pair && og && !pair.introduced_secondary_hazard && pair.burn_id === og.burn_id && <p className="small muted">Here the pair-only check picks the same burn: no other object in the {number(burns.n_objects_screened, 0)} screened comes close enough to matter.</p>}
    </div>
    <dl className="facts">
      <div><dt>Worst encounter Pc <Tip text={G.uncertainty}/></dt><dd>{probability(og?.worst_pc)} <span className="muted small">limit {probability(pol.pc_threshold, 0)}</span></dd></div>
      <div><dt>Miss with this plan</dt><dd>{number(og?.miss_km_threat, 2)} km <span className="muted small">target {number(burns.target_km, 0)} km</span></dd></div>
      <div><dt>Candidates accepted</dt><dd>{number(burns.n_accepted, 0)} of {number(burns.n_screened, 0)}</dd></div>
    </dl>
    <OperatorActions context="live" reference={og?.burn_id || pol.status || 'none'} recommendation={{status: pol.status, burn: og?.burn_id, dv_mps: og?.dv_mps, worst_pc: og?.worst_pc}}/>
  </section>;
}

function BurnTable({top}: {top: Json[]}) {
  return <div className="table-wrap"><table className="table compact">
    <thead><tr><th>Candidate</th><th>Direction</th><th className="num"><Term k="dv">Δv</Term> (m/s)</th><th className="num">Lead (orbits)</th><th className="num">Miss (km)</th><th className="num">New close approaches</th><th className="num">Worst Pc <Tip text={G.uncertainty}/></th><th>Result</th></tr></thead>
    <tbody>{top.map(b => <tr key={b.burn_id}><td className="mono">{b.burn_id}</td><td>{DIRECTIONS[b.direction] || b.direction}</td><td className="num">{fixed(b.dv_mps, 2)}</td><td className="num">{number(b.lead_periods, 1)}</td><td className="num">{fixed(b.miss_km_threat, 2)}</td><td className="num">{number(b.new_conjunctions, 0)}</td><td className="num">{probability(b.worst_pc)}</td><td><Status ok={Boolean(b.accepted)}>{b.accepted ? 'Accepted' : b.feasible ? 'Pc too high' : 'Misses target'}</Status></td></tr>)}</tbody>
  </table></div>;
}

function Consequence({cons}: {cons?: Json}) {
  if (!cons) return <Empty title="Consequence not computed"/>;
  const groups = Object.entries<number>(cons.exposed_by_constellation || {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const max = groups.length ? groups[0][1] : 1;
  return <>
    <div className="figures">
      <div className="figure"><span className="figure-label">Fragments ≥ 10 cm <Tip text="NASA Standard Breakup Model power law with masses assumed by object type. Validated against three real break-ups (predicted/catalogued 0.35–0.77), so use it for ranking, not absolute counts."/></span><strong>{number(cons.fragments_true, 0)}</strong><span className="small muted">{cons.catastrophic ? 'Catastrophic' : 'Non-catastrophic'} break-up</span></div>
      <div className="figure"><span className="figure-label">Satellites put at risk <Tip text="Active LEO satellites expecting at least one pass within 1 km of a fragment over 30 days (kinetic-gas density model, J2 spreading, no drag)."/></span><strong>{number(cons.n_sats_ge1_encounter, 0)}</strong><span className="small muted">of {number(cons.n_sats_considered, 0)} active in LEO</span></div>
      <div className="figure"><span className="figure-label">Expected harm <Tip text="Pc × total expected encounters. Two events with similar Pc can carry very different consequences; this ranks them by expected damage."/></span><strong>{probability(cons.expected_harm)}</strong><span className="small muted">{number(cons.total_expected_encounters, 0)} expected encounters</span></div>
    </div>
    {groups.length > 0 && <div className="bars" aria-label="Most exposed constellations">{groups.map(([name, n]) => <div className="bar-row" key={name}><span>{name}</span><span className="bar"><span style={{width: `${(100 * n) / max}%`}}/></span><span className="num">{number(n, 0)}</span></div>)}</div>}
  </>;
}

function Network({onRun, job}: {onRun: () => void, job?: Json}) {
  const net = useAsync<Json>('/live/network', [job?.state]);
  const action = <div className="job-actions"><JobLine job={job}/><button className="btn small" disabled={job?.state === 'running'} onClick={onRun}><Play size={13}/> {net.data ? 'Re-run sweep' : 'Run sweep'}</button></div>;
  return <Section title="Super-spreaders: objects that could seed a cascade" label="Super-spreader network" action={action}
    sub={net.data ? <>All {number(net.data.summary.n_objects, 0)} catalogue objects compared pairwise every {number(net.data.params.step_s, 0)} s for {number(net.data.params.hours, 0)} h; {number(net.data.summary.n_edges, 0)} close approaches under {number(net.data.params.r_km, 0)} km{net.data.timings?.sweep_wall_s ? ` found in ${number(net.data.timings.sweep_wall_s, 0)} s on ${net.data.timings.workers} workers` : ''}.</> : 'Catalogue-wide close-approach graph. Score = distinct neighbours × log mass × shell density.'}>
    {net.data ? <div className="table-wrap list-scroll short"><table className="table compact">
      <thead><tr><th className="num">Rank</th><th>Object</th><th>Type</th><th className="num">Neighbours</th><th className="num">Score</th><th className="num">Altitude (km)</th></tr></thead>
      <tbody>{net.data.nodes.slice(0, 15).map((n: Json) => <tr key={n.norad}><td className="num">{n.rank}</td><td>{n.name} <span className="muted small">{n.norad}</span></td><td>{n.type}</td><td className="num">{number(n.degree, 0)}</td><td className="num">{fixed(n.score, 2)}</td><td className="num">{number(n.perigee_km, 0)}–{number(n.apogee_km, 0)}</td></tr>)}</tbody>
    </table></div> : net.loading ? <Loading label="Loading network"/> : <Empty title="Network sweep not run yet">It takes about 100 s on the 3-core LinuxONE VM.</Empty>}
  </Section>;
}

function Survey({onRun, job}: {onRun: () => void, job?: Json}) {
  const s = useAsync<Json>('/live/survey', [job?.state]);
  const rows: Json[] = (s.data?.rows || []).slice().sort((a: Json, b: Json) => a.rank_harm - b.rank_harm);
  const action = <div className="job-actions"><JobLine job={job}/><button className="btn small" disabled={job?.state === 'running'} onClick={onRun}><Play size={13}/> {rows.length ? 'Re-run survey' : 'Run survey'}</button></div>;
  return <Section title="Probability is not priority" label="Pc versus expected harm" action={action}
    sub="20 random real conjunctions ranked two ways: by collision probability and by expected harm (Pc × the satellites a collision would endanger). Events that move up deserve attention their Pc alone hides.">
    {rows.length ? <div className="table-wrap list-scroll short"><table className="table compact">
      <thead><tr><th>Primary</th><th>Threat</th><th className="num">Rank by Pc</th><th className="num">Rank by harm</th><th className="num">Shift</th></tr></thead>
      <tbody>{rows.map(r => {const shift = r.rank_pc - r.rank_harm; return <tr key={`${r.norad}-${r.threat}`}><td>{r.primary}</td><td>{r.threat}</td><td className="num">{r.rank_pc}</td><td className="num">{r.rank_harm}</td><td className={`num ${shift >= 3 ? 'good-text' : shift <= -3 ? 'bad-text' : ''}`}>{shift > 0 ? `▲${shift}` : shift < 0 ? `▼${-shift}` : '–'}</td></tr>;})}</tbody>
    </table></div> : s.loading ? <Loading label="Loading survey"/> : <Empty title="Survey not run yet">It screens 20 random active satellites; about 4 minutes on LinuxONE.</Empty>}
  </Section>;
}

export function AuditPanel({refresh}: {refresh?: unknown}) {
  const a = useAsync<Json>('/audit?n=8', [refresh]);
  return <Section title={<>Audit trail <Tip text="Append-only JSON lines. Each record stores the SHA-256 of its payload and of the previous record, so editing or deleting any earlier line breaks the chain. Verify on the server with orbitguard audit-verify."/></>} label="Audit trail"
    action={<button className="btn small" onClick={a.retry}><RefreshCw size={13}/> Reload</button>}
    sub={a.data ? <>Chain {a.data.intact ? 'intact' : `broken at record ${a.data.first_bad_seq}`}{a.data.head ? <> · head #{a.data.head.seq} <span className="mono">{String(a.data.head.record_hash).slice(0, 16)}…</span></> : ' · empty'}</> : undefined}>
    {a.data?.recent?.length ? <ul className="audit">{a.data.recent.map((r: Json) => <li key={r.seq}><span className="mono small">#{r.seq}</span><span className={`kind ${r.kind}`}>{r.kind}</span><span className="small">{summarise(r)}</span><span className="small muted">{new Date(r.utc).toLocaleTimeString()}</span></li>)}</ul>
      : a.loading ? <Loading label="Loading audit trail"/> : <Empty title="No records yet">Replays, screenings, briefs and operator decisions are recorded here.</Empty>}
  </Section>;
}

function summarise(r: Json): string {
  const p = r.payload || {};
  if (r.kind === 'operator') return `${p.choice} · ${p.context} ${p.reference}`;
  if (r.kind === 'forecast') return `event ${p.event_id} message ${p.message_count}: ${p.alert?.state}${p.decision_action ? ` / ${p.decision_action}` : ''}`;
  if (r.kind === 'screen') return p.source === 'synthetic' ? `synthetic ${p.scenario_id}: ${p.status}` : `NORAD ${p.primary_norad} vs ${p.threat_norad}: ${p.status}${p.recommended ? ` (${p.recommended})` : ''}`;
  if (r.kind === 'brief') return `${p.backend} brief, ${p.grounded ? 'grounded' : 'ungrounded'}`;
  return r.kind;
}

export function LiveCatalogue() {
  const events = useAsync<Json>('/live/events');
  const [norad, setNorad] = useState(ISS);
  const [input, setInput] = useState(String(ISS));
  const [target, setTarget] = useState('10');
  const [version, setVersion] = useState(0);
  const [error, setError] = useState('');
  const {jobs, kick} = useJobs(key => {if (key === `analyse:${norad}` || key.startsWith('brief:')) setVersion(v => v + 1); if (key === 'survey') events.retry();});
  const facts = useAsync<Json>(`/live/facts/${norad}`, [version]);
  const brief = useAsync<Json>(facts.data ? `/live/brief/${norad}` : null, [version]);
  const f = facts.data;
  const analyse = jobs[`analyse:${norad}`];

  async function start(path: string, body: unknown) {
    setError('');
    try {await post(path, body); kick();} catch (e) {setError((e as Error).message);}
  }
  function run() {
    const n = Number(input), t = Number(target);
    if (!Number.isInteger(n) || n <= 0) {setError('Enter a NORAD catalogue number, for example 25544 for the ISS.'); return;}
    setNorad(n);
    start('/live/analyse', {norad: n, target_km: t});
  }
  const ev = f?.event, risk = f?.risk || {};
  return <>
    <div className="intro"><div><h1>Live catalogue</h1><p className="lead">
      Real orbits for every tracked object from CelesTrak, screened on LinuxONE. Find a satellite's closest approach in the next three days, test 145 candidate burns against the whole catalogue with the same <Term k="pc">Pc</Term> maths validated on NASA's reference cases, and see what a collision would cost. The operator makes the call.
    </p></div></div>
    <section className="card controls" aria-label="Run an analysis">
      <label>Satellite (NORAD) <input className="search" list="live-sats" value={input} onChange={e => setInput(e.target.value)} inputMode="numeric"/></label>
      <datalist id="live-sats">{(events.data?.events || []).map((e: Json) => <option key={e.norad} value={e.norad}>{e.name}</option>)}</datalist>
      <label>Miss target (km) <Tip text="The miss distance a burn must reach. TLE positions carry about 1 km of error, so targets below 2 km are not trustworthy."/><input className="search narrow" type="number" min="1" max="100" value={target} onChange={e => setTarget(e.target.value)}/></label>
      <button className="btn primary" disabled={analyse?.state === 'running'} onClick={run}>{analyse?.state === 'running' ? <Loader2 size={14} className="spin"/> : <Play size={14}/>} Find and screen</button>
      <JobLine job={analyse}/>
      {(events.data?.events || []).length > 1 && <div className="chips">{(events.data?.events || []).map((e: Json) => <button key={e.norad} className={`btn small ${e.norad === norad ? 'primary' : ''}`} onClick={() => {setNorad(e.norad); setInput(String(e.norad));}}>{e.name}</button>)}</div>}
    </section>
    {error && <Notice>{error}</Notice>}

    {facts.loading ? <Loading label="Loading analysis"/> : !f ? <section className="card"><Empty title={`No analysis for NORAD ${norad} yet`}>Press <strong>Find and screen</strong>. On the 3-core LinuxONE VM the full pipeline (catalogue download, closest-approach search, 145 burns, consequence) takes one to two minutes.</Empty></section> : <>
      <section className="card section" aria-label="Situation">
        <div className="card-head"><div><h2>{ev.primary.name} and {ev.threat.name}</h2><p className="muted small">NORAD {ev.primary.norad} ({ev.primary.type}) and {ev.threat.norad} ({ev.threat.type}) · analysed {new Date(f.generated_utc).toLocaleString()}</p></div></div>
        <div className="figures four">
          <div className="figure"><span className="figure-label">Closest approach <Tip text={G.tca}/></span><strong className="small-figure">{new Date(ev.tca_utc).toUTCString().replace(' GMT', ' UTC')}</strong></div>
          <div className="figure"><span className="figure-label">Miss distance <Tip text="SGP4 sampled every second, then refined to the straight-line closest approach. Sampling alone overstates a LEO miss by up to several kilometres."/></span><strong>{fixed(ev.miss_km, 2)} km</strong></div>
          <div className="figure"><span className="figure-label">Collision probability <Tip text="Encounter-plane Gaussian integral (the implementation checked against NASA CARA reference cases) with assumed TLE position errors of 0.5 / 1 / 0.5 km (radial / along-track / cross-track) per object."/></span><strong>{probability(risk.live_pc)}</strong><span className="small muted">worst case {probability(risk.live_pc_worst)}</span></div>
          <div className="figure"><span className="figure-label">Objects screened</span><strong>{number(f.burns?.n_objects_screened, 0)}</strong><span className="small muted">{number(f.timings_s?.screen_s, 1)} s for {number(f.burns?.n_screened, 0)} burns</span></div>
        </div>
      </section>
      <Recommendation facts={f}/>
      <Section title="Candidate burns" label="Candidate burns" sub={`Six directions × six sizes × four lead times. Accepted means the miss target is met and every close approach within 5 km, old or new, stays at or below Pc ${probability(f.burns?.policies?.pc_threshold, 0)} even at twice the assumed error.`}>
        <BurnTable top={f.burns?.top || []}/>
      </Section>
      <Section title="If they collide" label="Consequence" sub="What a collision at this closest approach would do to everyone else in orbit over 30 days.">
        <Consequence cons={f.consequence}/>
      </Section>
      <Section title={<>Operator brief <Tip text="Written by IBM Granite 3.3 2B running on the LinuxONE box (big-endian GGUF through llama.cpp) when LLM_BACKEND=llamacpp. A grounding guard extracts every number and checks it against the computed facts; any invented number switches to a deterministic template."/></>} label="Operator brief"
        action={<div className="job-actions"><JobLine job={jobs[`brief:${norad}`]}/>{brief.data && <span className="badges"><span className="tag">{brief.data.backend_used}</span><Status ok={Boolean(brief.data.grounded)}>{brief.data.grounded ? 'Grounded' : 'Ungrounded'}</Status></span>}<button className="btn small" onClick={() => start(`/live/brief/${norad}`, {})}><RefreshCw size={13}/> Regenerate</button></div>}>
        {brief.data?.text ? <><BriefText text={brief.data.text}/>{brief.data.issues?.length > 0 && <p className="footnote">Guard: {brief.data.issues.join('; ')}</p>}</> : brief.data?.status === 'computing' ? <Loading label="The on-box language model is writing the brief"/> : brief.loading ? <Loading label="Loading brief"/> : <Empty title="No brief yet"/>}
      </Section>
      <AskOrbitGuard norad={norad}/>
    </>}
    <div className="two-col">
      <Network job={jobs.network} onRun={() => start('/live/network', {})}/>
      <Survey job={jobs.survey} onRun={() => start('/live/survey', {})}/>
    </div>
    <AuditPanel refresh={version}/>
    <p className="scope-note">Public TLEs have about 1 km of error and no covariance, so position uncertainty is assumed and every Pc is a screening indicator. Burns use a J2 delta model on top of SGP4 and ignore drag. Masses are assumed by object type. OrbitGuard supports a human operator; it does not command spacecraft.</p>
  </>;
}

export function DecisionEvidence({evaluation}: {evaluation?: Json}) {
  if (!evaluation) return null;
  if (evaluation.status !== 'ready') return <section className="card section"><h2>Act / Wait / Monitor decision layer</h2><p className="muted">{evaluation.message}</p></section>;
  const m = evaluation.metrics || {}, chosen = evaluation.chosen;
  const rows: [string, Json][] = [['Latest reported value (ESA baseline)', m.naive], [`Decision layer (candidate ${chosen})`, m[chosen]]];
  return <section className="card section">
    <div className="section-head"><div><h2>Act / Wait / Monitor decision layer</h2>
      <p className="muted">Rules and a calibrated classifier chosen by 5-fold cross-validation on training encounters only; the sealed test labels were opened after the artefact was frozen (fingerprint below). {number(evaluation.test_events, 0)} test encounters, {number(evaluation.high_risk_test_events, 0)} high-risk.</p></div></div>
    <div className="table-wrap"><table className="table">
      <thead><tr><th>Method</th><th className="num">Challenge loss <Tip text={G.loss}/></th><th className="num">F2 <Tip text={G.f2}/></th><th className="num">Recall</th><th className="num">Precision</th></tr></thead>
      <tbody>{rows.map(([name, r]) => r ? <tr key={name}><td>{name}</td><td className="num">{fixed(r.L, 3)}</td><td className="num">{fixed(r.f2, 3)}</td><td className="num">{percent(r.recall)}</td><td className="num">{percent(r.precision)}</td></tr> : null)}</tbody>
    </table></div>
    <div className="compare">
      {(['ACT', 'WAIT', 'MONITOR'] as const).map(a => <div key={a}><span className="figure-label"><span className={`action-badge ${a.toLowerCase()}`}>{a}</span></span><strong>{number(evaluation.actions?.[a]?.events, 0)} encounters</strong><span className="small muted">{number(evaluation.actions?.[a]?.high_risk_events, 0)} of {number(evaluation.high_risk_test_events, 0)} high-risk encounters land here</span></div>)}
    </div>
    <p className="finding"><strong>Calibration and uncertainty:</strong> P(high) average precision {fixed(evaluation.p_high?.average_precision, 3)}, Brier score {fixed(evaluation.p_high?.brier, 4)}. The nominal 80% interval covers {percent(evaluation.interval?.empirical_coverage)} of final values with a mean width of {fixed(evaluation.interval?.mean_width_log10, 1)} log units: honest, but wide.</p>
    <p className="small muted">Decision artefact SHA-256 before labels: <span className="mono">{String(evaluation.fingerprints?.decision_sha256_before_labels || '—').slice(0, 16)}…</span> · evaluated on {evaluation.platform?.architecture}</p>
  </section>;
}

export function PlatformEvidence() {
  const {data, loading, error, retry} = useAsync<Json>('/evidence/platform');
  if (loading) return <Loading label="Loading platform evidence"/>;
  if (error) return <Notice retry={retry}>{error}</Notice>;
  const p = data?.platform || {}, speed = data?.catalogue_speedup || {}, nnpa = data?.nnpa || {}, net = data?.network || {}, breakup = data?.breakup_validation || {};
  return <section className="card section">
    <div className="section-head"><div><h2>IBM LinuxONE platform use</h2><p className="muted">Read from the connected server and from artefacts written by the benchmark commands. Anything not yet run on this server is shown as missing.</p></div></div>
    <dl className="provenance">
      <div><dt>Architecture</dt><dd>{p.machine} · {p.byteorder}-endian · {p.cpu_count} CPUs{p.machine_type ? ` · machine type ${p.machine_type}` : ''}</dd></div>
      <div><dt>On-chip AI accelerator (NNPA)</dt><dd>{p.nnpa_in_cpuinfo ? 'Present in /proc/cpuinfo' : 'Not reported by this CPU'}</dd></div>
      <div><dt>SGP4 C extension</dt><dd>{p.sgp4_accelerated === true ? 'Built and active' : p.sgp4_accelerated === false ? 'Pure-Python fallback (about 70× slower)' : 'Unknown'}</dd></div>
      <div><dt>Container</dt><dd>{p.container ? 'Running inside a container' : 'Not containerised (systemd service or development run)'}</dd></div>
      <div><dt>Language model</dt><dd>{p.llm_backend}{p.llm_model ? ` · ${p.llm_model}` : ''}</dd></div>
    </dl>
    <div className="subsection"><h3>Parallel catalogue screening</h3>
      {Array.isArray(speed.results) ? <><div className="table-wrap"><table className="table compact"><thead><tr><th className="num">Workers</th><th className="num">Wall time (s)</th><th className="num">Speed-up</th></tr></thead><tbody>{speed.results.map((r: Json) => <tr key={r.workers}><td className="num">{r.workers}</td><td className="num">{fixed(r.wall_s, 1)}</td><td className="num">{fixed(r.speedup, 2)}×</td></tr>)}</tbody></table></div><p className="small muted">{number(speed.n_burns, 0)} burns against {number(speed.n_objects, 0)} objects on {speed.machine} ({speed.byteorder}-endian, {speed.cpu_count} CPUs).</p></> : <Empty title="Not measured on this server">Run orbitguard screen-live --benchmark.</Empty>}</div>
    <div className="subsection"><h3>Telum NNPA inference (TensorFlow + IBM zDNN plugin)</h3>
      {Array.isArray(nnpa.table) ? <><div className="table-wrap"><table className="table compact"><thead><tr><th className="num">Rows scored</th><th className="num">CPU rows/s</th><th className="num">NNPA rows/s</th><th className="num">Speed-up</th></tr></thead><tbody>{nnpa.table.map((r: Json) => <tr key={r.rows}><td className="num">{number(r.rows, 0)}</td><td className="num">{number(r.cpu_rows_per_s, 0)}</td><td className="num">{number(r.nnpa_rows_per_s, 0)}</td><td className="num">{fixed(r.speedup, 2)}×</td></tr>)}</tbody></table></div><p className="small muted">Keras MLP P(high) scorer on decision features · machine type {nnpa.sysinfo_type} · ibm-zdnn-plugin {nnpa.ibm_zdnn_plugin_version} · NNPA kernels confirmed: {nnpa.nnpa_available ? 'yes' : 'no'} · max |CPU − NNPA| {finite(nnpa.max_abs_diff_prob) ? nnpa.max_abs_diff_prob.toFixed(4) : '—'}</p></> : <Empty title="Not measured on this server">Run orbitguard nnpa-bench inside the LinuxONE TensorFlow image.</Empty>}</div>
    <div className="figures">
      <div className="figure"><span className="figure-label">Network sweep</span><strong>{net.summary ? `${number(net.summary.n_edges, 0)} encounters` : '—'}</strong><span className="small muted">{net.summary ? `${number(net.summary.n_objects, 0)} objects, ${number(net.timings?.sweep_wall_s, 0)} s` : 'not run'}</span></div>
      <div className="figure"><span className="figure-label">Break-up model vs real events</span><strong>{Array.isArray(breakup.events) ? breakup.events.map((e: Json) => fixed(e.ratio_pred_over_catalogued, 2)).join(' · ') : '—'}</strong><span className="small muted">{Array.isArray(breakup.events) ? breakup.events.map((e: Json) => e.event).join(' · ') : 'run orbitguard validate-breakup'}</span></div>
    </div>
  </section>;
}
