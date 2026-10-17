import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDownToLine, ExternalLink, Loader2, Pause, Play, RefreshCw } from 'lucide-react';
import { G, POLICIES, Empty, Loading, Notice, Status, Term, Tip, useAsync, useTokens } from './ui';
import { PolicyBars, PopulationChart, RankingCurve } from './Charts';

// The 3D views pull in three.js, so they load on first use rather than with the page.
const OrbitalView = lazy(() => import('./Visuals').then(m => ({default: m.OrbitalView})));
const EncounterOrbits = lazy(() => import('./Visuals').then(m => ({default: m.EncounterOrbits})));
const loadingGlobe = <Loading label="Loading 3D view"/>;
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { finite, fixed, logProbability, number, percent, post, powerOfTen, probability, request } from './api';
import type { Json } from './api';

type Tab = 'encounters' | 'planning' | 'validation';
const TABS: [Tab, string][] = [['encounters', 'Encounters'], ['planning', 'Manoeuvre planning'], ['validation', 'Validation']];

const METHOD_NAMES: Record<string, string> = {
  clipped_latest_baseline: 'Latest reported value (ESA baseline)',
  learned_residual_scored: 'Learned model',
  constant_minus_5: 'Constant 10⁻⁵ (reference)',
};

function Intro({title, children, action}: {title: string, children: ReactNode, action?: ReactNode}) {return <div className="intro"><div><h1>{title}</h1><p className="lead">{children}</p></div>{action}</div>;}
function OrbitMark() {return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/><ellipse cx="12" cy="12" rx="10" ry="4.6" transform="rotate(-25 12 12)"/></svg>;}

// ---------------------------------------------------------------- shell

export default function App() {
  const [tab, setTab] = useState<Tab>(() => {const hash = location.hash.slice(1); return (TABS.some(([id]) => id === hash) ? hash : 'encounters') as Tab;});
  const health = useAsync<Json>('/health');
  useEffect(() => {history.replaceState(null, '', `#${tab}`);}, [tab]);
  useEffect(() => {
    const follow = () => {const hash = location.hash.slice(1); if (TABS.some(([id]) => id === hash)) setTab(hash as Tab);};
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  }, []);
  const onLinuxONE = health.data?.architecture === 's390x';
  return <div className="app">
    <header className="topbar"><div className="topbar-inner">
      <a className="brand" href="#encounters" onClick={e => {e.preventDefault(); setTab('encounters');}}><OrbitMark/>OrbitGuard</a>
      <nav className="tabs" aria-label="Sections">{TABS.map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => {setTab(id); window.scrollTo(0, 0);}}>{label}</button>)}</nav>
      <div className="runtime">
        <span className={`dot ${health.data ? 'on' : health.error ? 'off' : ''}`}/>
        <span>{health.data ? (onLinuxONE ? 'IBM LinuxONE' : 'Local machine') : health.error ? 'Server unreachable' : 'Connecting'}</span>
        {health.data && <span className="mono muted">{health.data.architecture}</span>}
        <Tip text={health.data ? (onLinuxONE
          ? `Every forecast and screening on this page is computed on an IBM LinuxONE virtual machine (${health.data.architecture}, ${health.data.available_cpus ?? '?'} CPUs). The browser only displays the results.`
          : `Running on a ${health.data.architecture} development machine, not LinuxONE.`) : 'Checking the connection to the OrbitGuard server.'}/>
      </div>
    </div></header>
    <main className="page">
      {health.error && <Notice retry={health.retry}>Cannot reach the OrbitGuard server: {health.error}</Notice>}
      {tab === 'encounters' ? <Encounters/> : tab === 'planning' ? <Planning/> : <Validation/>}
    </main>
  </div>;
}

// ---------------------------------------------------------------- encounters

function Encounters() {
  const list = useAsync<Json>('/events?limit=100');
  const events: Json[] = list.data?.events || [];
  const [selected, setSelected] = useState('');
  const [filter, setFilter] = useState('');
  const [replayCount, setReplayCount] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [forecast, setForecast] = useState<Json | null>(null);
  const [forecastBusy, setForecastBusy] = useState(false);
  useEffect(() => {if (!selected && events.length) setSelected(String(events[0].event_id));}, [events, selected]);
  const detail = useAsync<Json>(selected ? `/events/${encodeURIComponent(selected)}` : null);
  const event = detail.data && String(detail.data.event_id) === selected ? detail.data : null;
  const history: Json[] = event?.history || event?.messages || [];
  useEffect(() => {setReplayCount(null); setPlaying(false); setForecast(event?.forecast || null);}, [event]);
  useEffect(() => {
    if (!playing || !history.length) return;
    const timer = window.setInterval(() => setReplayCount(current => {const next = (current ?? 0) + 1; if (next >= history.length) {setPlaying(false); return history.length;} return next;}), 1000);
    return () => window.clearInterval(timer);
  }, [playing, history.length]);
  useEffect(() => {
    if (replayCount === null || !event) return;
    let alive = true;
    setForecastBusy(true);
    const timer = window.setTimeout(() => {
      post('/forecast', {history: history.slice(0, replayCount)})
        .then(f => {if (alive) setForecast(f);})
        .catch(e => {if (alive) setForecast({error: e.message});})
        .finally(() => {if (alive) setForecastBusy(false);});
    }, 150);
    return () => {alive = false; window.clearTimeout(timer);};
  }, [event, replayCount]);

  const toPoint = (row: Json, i: number) => ({day: finite(row.time_to_tca) ? row.time_to_tca : i, risk: row.risk ?? row.log10_pc});
  const full = history.map(toPoint).filter(p => finite(p.risk)).sort((a, b) => b.day - a.day);
  const shown = history.slice(0, replayCount ?? history.length).map(toPoint).filter(p => finite(p.risk)).sort((a, b) => b.day - a.day);
  const reference = event?.reference?.true_log10_pc;
  const visible = events.filter(e => String(e.event_id).includes(filter.trim().replace(/^#/, '')));
  const lastDay = full.length ? full[full.length - 1].day : null;
  const population = useAsync<Json>('/population');
  const latestMessage = history.length ? history[history.length - 1] : null;

  return <>
    <Intro title="Encounters">
      Historical close approaches from the held-out test set of ESA's Collision Avoidance Challenge. Each encounter is a series of <Term k="cdm">conjunction data messages</Term> issued in the days before two objects pass closest. Select one to replay its messages and compare forecasts of the <Term k="final">final reported collision probability</Term>.
    </Intro>
    {list.error && <Notice retry={list.retry}>{list.error}</Notice>}
    <div className="encounters-layout">
      <section className="card list-card" aria-label="Encounter list">
        <div className="card-head">
          <h2>Highest-risk encounters</h2>
          <span className="muted small">Top {events.length || '—'} of 2,167, by latest <Term k="pc">Pc</Term></span>
        </div>
        <input className="search" type="search" aria-label="Search by encounter number" placeholder="Search by encounter number" value={filter} onChange={e => setFilter(e.target.value)}/>
        <div className="list-scroll">
          {list.loading ? <Loading label="Loading encounters"/> : visible.length ? <table className="table event-table">
            <thead><tr><th>Encounter</th><th className="num">Messages</th><th className="num">Days to <Term k="tca">TCA</Term></th><th className="num">Latest <Term k="pc">Pc</Term></th></tr></thead>
            <tbody>{visible.map(e => {const id = String(e.event_id); return <tr key={id} className={selected === id ? 'selected' : ''} onClick={() => setSelected(id)}>
              <td><button className="row-button" aria-pressed={selected === id} onClick={ev => {ev.stopPropagation(); setSelected(id);}}>#{id}</button></td>
              <td className="num">{number(e.message_count, 0)}</td>
              <td className="num">{number(e.time_to_tca_days, 1)}</td>
              <td className="num">{logProbability(e.latest_log10_pc)}</td>
            </tr>;})}</tbody>
          </table> : <Empty title={filter ? 'No encounter matches that number' : 'No encounters available'}>{!filter && 'Prepare the ESA dataset on the server to populate this list.'}</Empty>}
        </div>
      </section>

      <section className="card detail-card" aria-label="Encounter detail">
        {detail.error ? <Notice retry={detail.retry}>{detail.error}</Notice> : !event ? <Loading label="Loading encounter"/> : full.length ? <>
          <div className="card-head">
            <div><h2>Encounter #{selected}</h2><p className="muted small">{history.length} messages; the last one was issued {number(lastDay, 2)} days before closest approach.</p></div>
          </div>
          <h3 className="subhead">Reported collision probability over time <Tip text={`${G.pc} ${G.threshold}`}/></h3>
          <RiskChart data={shown} full={full}/>
          <div className="replay">
            <button className="btn icon" aria-label={playing ? 'Pause replay' : 'Replay messages one by one'} onClick={() => {if (playing) {setPlaying(false); return;} if (replayCount === null || replayCount >= history.length) setReplayCount(1); setPlaying(true);}}>{playing ? <Pause size={14}/> : <Play size={14}/>}</button>
            <input aria-label="Historical message replay position" type="range" min="1" max={history.length} value={replayCount ?? history.length} onChange={e => {setPlaying(false); setReplayCount(Number(e.target.value));}}/>
            <span className="small muted replay-count">Message {replayCount ?? history.length} of {history.length}{forecastBusy && <Loader2 size={12} className="spin"/>}</span>
          </div>
          <div className="figures">
            <div className="figure"><span className="figure-label">Latest reported value <Tip text={G.latest}/></span><strong>{logProbability(forecast?.baseline_log10_pc)}</strong><span className="tag">Default forecast</span></div>
            <div className="figure"><span className="figure-label">Learned model <Tip text={G.learned}/></span><strong>{logProbability(forecast?.learned_forecast_log10_pc)}</strong></div>
            <div className="figure muted-figure"><span className="figure-label">Final reported value <Tip text={G.final}/></span><strong>{logProbability(reference)}</strong><span className="small muted">Revealed for comparison</span></div>
          </div>
          {forecast?.error && <Notice>{forecast.error}</Notice>}
          <p className="footnote">Forecasts use only messages issued at least 48 hours before closest approach. They estimate the final reported risk; they do not predict whether a collision happens.</p>
        </> : <Empty title="No message history for this encounter"/>}
      </section>
    </div>
    <div className="encounters-visuals">
      <section className="card" aria-label="Orbits of the two objects">
        <div className="card-head"><div><h2>Orbits of the two objects</h2><p className="muted small">Encounter #{selected}: the ESA satellite and the object that came close to it.</p></div></div>
        {latestMessage ? <Suspense fallback={loadingGlobe}><EncounterOrbits message={latestMessage}/></Suspense> : <Loading label="Loading encounter"/>}
      </section>
      <section className="card" aria-label="All encounters by orbit">
        <div className="card-head"><div><h2>Where all {number(population.data?.count, 0)} encounters happen</h2><p className="muted small">Each dot is one encounter, placed by the orbit of the object that approached an ESA satellite. Clusters are orbits shared by many objects, often debris from earlier break-ups. Click a dot to open that encounter.</p></div></div>
        {population.error ? <Notice retry={population.retry}>{population.error}</Notice> : population.data ? <PopulationChart population={population.data} selected={selected} onSelect={setSelected}/> : <Loading label="Loading all encounters"/>}
      </section>
    </div>
  </>;
}

function RiskChart({data, full}: {data: {day: number, risk: number}[], full: {day: number, risk: number}[]}) {
  const t = useTokens();
  const risks = full.map(d => d.risk);
  const low = Math.floor(Math.min(...risks, -6));
  const high = Math.max(Math.ceil(Math.max(...risks)), low + 1);
  const ticks = Array.from({length: high - low + 1}, (_, i) => low + i);
  const days = full.map(d => d.day);
  return <div className="chart" role="img" aria-label={`Reported collision probability for ${full.length} messages, from ${logProbability(full[0]?.risk)} to ${logProbability(full[full.length - 1]?.risk)}`}>
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{top: 10, right: 16, left: 4, bottom: 22}}>
        <CartesianGrid stroke={t.grid} vertical={false}/>
        <XAxis dataKey="day" type="number" domain={[Math.min(...days), Math.max(...days)]} reversed tickFormatter={v => number(Number(v), 1)} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} label={{value: 'Days before closest approach', position: 'insideBottom', offset: -14, fill: t.muted, fontSize: 12}}/>
        <YAxis domain={[low - 0.7, high]} ticks={ticks} tickFormatter={v => powerOfTen(Number(v))} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} width={48}/>
        <ReferenceLine y={-6} stroke={t.muted} strokeDasharray="4 4" label={{value: 'High-risk threshold (10⁻⁶)', position: 'insideBottomLeft', fill: t.muted, fontSize: 11}}/>
        <Tooltip cursor={{stroke: t.axis}} content={({active, payload}) => active && payload?.length ? <div className="chart-tip"><div className="muted">{number(payload[0].payload.day, 2)} days before closest approach</div><div>Pc {logProbability(payload[0].payload.risk)}</div></div> : null}/>
        <Line type="linear" dataKey="risk" stroke={t.s1} strokeWidth={2} dot={{r: 4, fill: t.surface, stroke: t.s1, strokeWidth: 2}} activeDot={{r: 5}} isAnimationActive={false}/>
      </LineChart>
    </ResponsiveContainer>
  </div>;
}

// ---------------------------------------------------------------- planning

function worstOther(policy: Json | undefined, primary: string): {id: string, pc: number} | null {
  const others = (policy?.encounters || []).filter((e: Json) => e.object_id !== primary && finite(e.sensitivity_worst_pc));
  if (!others.length) return null;
  const worst = others.reduce((a: Json, b: Json) => b.sensitivity_worst_pc > a.sensitivity_worst_pc ? b : a);
  return {id: worst.object_id, pc: worst.sensitivity_worst_pc};
}
function burnText(dv: number | null | undefined, time: number | null | undefined) {
  if (!finite(dv) || dv === 0) return 'None';
  return `${dv > 0 ? '+' : '−'}${fixed(Math.abs(dv), 2)} m/s at T+${number(time, 0)} s`;
}

function Planning() {
  const list = useAsync<Json>('/scenarios');
  const scenarios: Json[] = list.data?.scenarios || [];
  const [selected, setSelected] = useState('');
  useEffect(() => {if (!selected && scenarios.length) setSelected(scenarios[0].scenario_id);}, [scenarios, selected]);
  const scenarioReq = useAsync<Json>(selected ? `/scenarios/${encodeURIComponent(selected)}` : null);
  const scenario = scenarioReq.data;
  const [result, setResult] = useState<Json | null>(null);
  const [job, setJob] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [activePolicy, setActivePolicy] = useState('orbitguard');
  const [focus, setFocus] = useState<'primary' | 'secondary'>('primary');
  const cancelled = useRef(false);
  useEffect(() => () => {cancelled.current = true;}, []);
  useEffect(() => {setResult(null); setJob(null); setError(''); setFocus('primary'); setActivePolicy('orbitguard');}, [selected]);

  async function run() {
    setBusy(true); setError(''); setResult(null); cancelled.current = false;
    try {
      const start = await post('/screen', {scenario_id: selected});
      setJob(start);
      for (let i = 0; i < 600 && !cancelled.current; i++) {
        await new Promise(resolve => setTimeout(resolve, 600));
        const update = await request(`/jobs/${start.job_id}`);
        setJob(update);
        if (update.status === 'completed') {setResult(update.result); break;}
        if (update.status === 'failed') throw new Error(update.error?.message || 'Screening failed on the server.');
      }
    } catch (e) {if (!cancelled.current) setError((e as Error).message);} finally {if (!cancelled.current) setBusy(false);}
  }

  const views = result?.encounter_views || scenario?.encounter_views;
  const primaryId: string = views?.primary?.object_id || 'B';
  const secondaryId: string | undefined = views?.secondary?.object_id;
  const policies: Json = result?.policies || {};
  const assumptions: string[] = Array.isArray(result?.assumptions || scenario?.assumptions) ? (result?.assumptions || scenario?.assumptions) : [];

  return <>
    <Intro title="Manoeuvre planning">
      In each scenario a simulated satellite, A, is heading for a close approach. OrbitGuard tries 37 candidate burns, checks each one against every nearby object, and recommends the smallest burn that keeps all encounters below the <Term k="limit">risk limit</Term>. A burn that avoids one object can steer into another; the first scenario shows exactly that.
    </Intro>
    <section className="card toolbar">
      <label className="field"><span>Scenario</span>
        <select value={selected} disabled={busy || !scenarios.length} onChange={e => setSelected(e.target.value)}>
          {!scenarios.length && <option>{list.loading ? 'Loading' : 'No scenarios available'}</option>}
          {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.name || s.scenario_id}</option>)}
        </select>
      </label>
      <p className="toolbar-text">{scenario?.description || ' '}</p>
      <button className="btn primary" disabled={!scenario || busy} onClick={run}>{busy ? <Loader2 className="spin" size={15}/> : <Play size={15}/>}{busy ? 'Screening' : result ? 'Run again' : 'Screen manoeuvres'}</button>
    </section>
    {(error || list.error || scenarioReq.error) && <Notice retry={error ? undefined : list.retry}>{error || list.error || scenarioReq.error}</Notice>}

    <Recommendation result={result} busy={busy} job={job} primaryId={primaryId}/>

    <section className="card" aria-label="Orbital view">
      <div className="card-head">
        <div><h2>Orbital view <Tip text="Paths over the three-hour planning window in an Earth-centred inertial frame, so the Earth is drawn without its rotation. Altitudes are to scale; at this scale a near miss of a few metres looks like a collision, so use the distance chart and the encounter geometry for close-range detail."/></h2><p className="muted small">Satellite A and every tracked object nearby, for the policy selected in the table below. {result ? '' : 'Showing the paths before any burn; run the screening to compare policies.'}</p></div>
      </div>
      {(result?.trajectories || scenario?.trajectories)?.length ? <Suspense fallback={loadingGlobe}><OrbitalView trajectories={result?.trajectories || scenario?.trajectories} activePolicy={result ? activePolicy : 'no_action'} policyLabel={activePolicy === 'pair_only' && result ? `Avoid ${primaryId} only` : result ? POLICIES.find(p => p.id === activePolicy)?.label || '' : 'No manoeuvre'} primaryId={primaryId} secondaryId={secondaryId} burnTime={policies[activePolicy]?.burn_time_seconds} primaryTca={scenario?.primary_tca_seconds} secondaryTca={scenario?.secondary_tca_seconds}/></Suspense> : <Loading label="Loading scenario"/>}
    </section>

    <div className="planning-layout">
      <section className="card" aria-label="Policy comparison">
        <div className="card-head"><div><h2>Compare policies</h2><p className="muted small">All three use the same scenario and the same 37 candidates. Select a row to show it in the geometry view below.</p></div></div>
        <div className="table-wrap"><table className="table policy-table">
          <thead><tr><th>Policy</th><th>Burn <Tip text={G.dv}/></th><th className="num">Pc with {primaryId} <Tip text={G.uncertainty}/></th><th className="num">Worst Pc, other objects</th><th>Result <Tip text={G.limit}/></th></tr></thead>
          <tbody>{POLICIES.map(p => {const row = policies[p.id]; const other = worstOther(row, primaryId); return <tr key={p.id} className={activePolicy === p.id ? 'selected' : ''} onClick={() => setActivePolicy(p.id)}>
            <td><button className="row-button" aria-pressed={activePolicy === p.id} onClick={ev => {ev.stopPropagation(); setActivePolicy(p.id);}}>{p.id === 'pair_only' ? `Avoid ${primaryId} only` : p.label}</button><div className="small muted">{p.id === 'pair_only' ? `Cheapest burn that clears ${primaryId}, ignoring others` : p.short}</div></td>
            <td className="nowrap">{row ? (row.abstained ? 'None found' : burnText(row.delta_v_mps, row.burn_time_seconds)) : '—'}</td>
            <td className={`num ${row?.primary_pc >= 1e-4 ? 'over' : ''}`}>{probability(row?.primary_pc)}</td>
            <td className={`num ${row?.worst_secondary_pc >= 1e-4 ? 'over' : ''}`}>{probability(row?.worst_secondary_pc)}{other && row?.worst_secondary_pc >= 1e-6 && <span className="small muted"> ({other.id})</span>}</td>
            <td>{row ? <><Status ok={row.accepted}>{row.abstained ? 'Declined' : row.accepted ? 'Accepted' : 'Rejected'}</Status>{!row.accepted && row.reason && <div className="small muted reason">{row.reason}</div>}</> : <span className="muted">Not run</span>}</td>
          </tr>;})}</tbody>
        </table></div>
        {result?.candidates && <CandidateTable candidates={result.candidates} policies={policies} primaryId={primaryId}/>}
      </section>

      <section className="card" aria-label="Encounter geometry">
        <div className="card-head">
          <div><h2>Encounter geometry <Tip text={G.geometry}/></h2><p className="muted small">Close-up of the moment of closest approach, for the policy selected in the table above.</p></div>
          {secondaryId && <div className="segmented" role="group" aria-label="Encounter shown">
            <button aria-pressed={focus === 'primary'} onClick={() => setFocus('primary')}>Closest approach with {primaryId}</button>
            <button aria-pressed={focus === 'secondary'} onClick={() => setFocus('secondary')}>Closest approach with {secondaryId}</button>
          </div>}
        </div>
        <OrbitPlot view={views?.[focus]} activePolicy={activePolicy} policyLabel={activePolicy === 'pair_only' ? `Avoid ${primaryId} only` : POLICIES.find(p => p.id === activePolicy)?.label || ''} hasResult={Boolean(result)}/>
      </section>
    </div>

    {assumptions.length > 0 && <details className="card assumptions">
      <summary>Simulation assumptions ({assumptions.length})</summary>
      <ul>{assumptions.map(a => <li key={a}>{a}</li>)}</ul>
    </details>}
  </>;
}

function Recommendation({result, busy, job, primaryId}: {result: Json | null, busy: boolean, job: Json | null, primaryId: string}) {
  if (busy) return <section className="card recommendation"><Loading label={`Screening candidate burns on the server (${job?.status || 'queued'})`}/></section>;
  if (!result) return <section className="card recommendation"><p className="muted">Press <strong>Screen manoeuvres</strong> to evaluate every candidate burn for this scenario. It takes about two seconds.</p></section>;
  const policies = result.policies || {};
  const chosen = policies.orbitguard || result.recommendation || {};
  const pair = policies.pair_only;
  const rec = result.recommendation;
  const pairHazard = worstOther(pair, primaryId);
  let headline: string, explanation: string;
  if (!rec) {
    headline = 'No acceptable manoeuvre found';
    explanation = chosen.reason || 'None of the evaluated candidates keeps every encounter below the risk limit. Escalate to the operations team.';
  } else if (!rec.delta_v_mps) {
    headline = 'No manoeuvre needed';
    explanation = 'Every encounter in the planning window is already below the risk limit, so no fuel needs to be spent.';
  } else {
    headline = `${rec.delta_v_mps > 0 ? 'Prograde' : 'Retrograde'} burn of ${fixed(Math.abs(rec.delta_v_mps), 2)} m/s at T+${number(rec.burn_time_seconds, 0)} s`;
    explanation = pair?.introduced_secondary_hazard && pairHazard
      ? `The cheapest burn that clears ${primaryId} (${burnText(pair.delta_v_mps, pair.burn_time_seconds)}) would raise the collision probability with ${pairHazard.id} to ${probability(pairHazard.pc)}. This burn clears both, ${Math.abs(Math.abs(pair.delta_v_mps) - Math.abs(rec.delta_v_mps)) < 1e-9 ? 'for the same fuel' : `for ${fixed(Math.abs(rec.delta_v_mps) - Math.abs(pair.delta_v_mps), 2)} m/s more Δv`}.`
      : 'This is the smallest burn that keeps every encounter with every nearby object below the risk limit at all three uncertainty levels.';
  }
  const verification = chosen.verification;
  return <section className={`card recommendation ${rec ? 'has-rec' : 'no-rec'}`} aria-live="polite">
    <div className="rec-main">
      <span className="label">Recommendation</span>
      <h2>{headline}</h2>
      <p>{explanation}</p>
    </div>
    <dl className="facts">
      <div><dt>Worst encounter Pc <Tip text={G.uncertainty}/></dt><dd>{probability(chosen.worst_pc)} <span className="muted small">limit {powerOfTen(Math.round(Math.log10(result.risk_threshold ?? 1e-4)))}</span></dd></div>
      <div><dt>Candidates screened</dt><dd>{number(result.candidates_evaluated, 0)} in {number((result.elapsed_ms ?? 0) / 1000, 2)} s</dd></div>
      <div><dt>Numerical re-check <Tip text={G.verify}/></dt><dd>{verification ? <Status ok={verification.status === 'passed'}>{verification.status === 'passed' ? 'Passed' : 'Failed'}</Status> : '—'}</dd></div>
    </dl>
    {job?.job_id && <a className="btn small" href={`/api/runs/${job.job_id}`} download><ArrowDownToLine size={14}/> Download screening result</a>}
  </section>;
}

function CandidateTable({candidates, policies, primaryId}: {candidates: Json[], policies: Json, primaryId: string}) {
  const picks: Record<string, string[]> = {};
  for (const p of POLICIES) {const id = policies[p.id]?.candidate_id; if (id) (picks[id] ||= []).push(p.id === 'pair_only' ? `Avoid ${primaryId} only` : p.label);}
  const accepted = candidates.filter(c => c.accepted).length;
  return <details className="candidates">
    <summary>All {candidates.length} candidates ({accepted} acceptable)</summary>
    <div className="table-wrap"><table className="table compact">
      <thead><tr><th>Burn</th><th className="num">Pc with {primaryId}</th><th className="num">Worst Pc, other objects</th><th>Result</th></tr></thead>
      <tbody>{candidates.map(c => <tr key={c.candidate_id}>
        <td className="nowrap">{burnText(c.delta_v_mps, c.burn_time_seconds)}{picks[c.candidate_id]?.map(name => <span key={name} className="tag">{name}</span>)}</td>
        <td className={`num ${c.primary_pc >= 1e-4 ? 'over' : ''}`}>{probability(c.primary_pc)}</td>
        <td className={`num ${c.worst_secondary_pc >= 1e-4 ? 'over' : ''}`}>{probability(c.worst_secondary_pc)}</td>
        <td><Status ok={Boolean(c.accepted)}/>{!c.accepted && c.rejection_reasons?.length > 0 && <span className="small muted"> {c.rejection_reasons.join('; ')}</span>}</td>
      </tr>)}</tbody>
    </table></div>
  </details>;
}

function OrbitPlot({view, activePolicy, policyLabel, hasResult}: {view: Json | undefined, activePolicy: string, policyLabel: string, hasResult: boolean}) {
  const t = useTokens();
  const [zoomed, setZoomed] = useState(true);
  const raw: Json[] = view?.trajectories || [];
  if (!raw.length) return <Empty title={hasResult ? 'No geometry for this encounter' : 'Run the screening to see the encounter geometry'}/>;
  const objectId = view?.object_id;
  const policyPath = raw.find(tr => tr.policy === activePolicy);
  const original = raw.find(tr => tr.object_id === 'A');
  const other = raw.find(tr => tr.object_id === objectId);
  const pathA = activePolicy === 'no_action' || !policyPath ? original : policyPath;
  const toXY = (p: Json) => ({x: p.x_m ?? p[0], y: p.y_m ?? p[1], z: p.z_m ?? p[2] ?? 0});
  const window_ = (points: Json[]) => {const xy = points.map(toXY).filter(p => finite(p.x) && finite(p.y)); if (!zoomed || xy.length < 13) return xy; const mid = Math.floor(xy.length / 2); return xy.slice(mid - 6, mid + 7);};
  const series = [
    pathA && {key: 'A', label: activePolicy === 'no_action' ? 'Satellite A (no burn)' : 'Satellite A (after burn)', color: t.s1, points: window_(pathA.points)},
    other && {key: objectId, label: `Object ${objectId}`, color: objectId === 'B' ? t.s2 : t.s3, points: window_(other.points)},
  ].filter(Boolean) as {key: string, label: string, color: string, points: {x: number, y: number, z: number}[]}[];
  const ghost = activePolicy !== 'no_action' && policyPath && original ? window_(original.points) : null;
  const all = [...series.flatMap(s => s.points), ...(ghost || [])];
  const xs = all.map(p => p.x), ys = all.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const extent = Math.max(maxX - minX, maxY - minY, 1) * 1.15;
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const W = 640, H = 380, S = Math.min(W, H) - 40;
  const project = (p: {x: number, y: number}) => ({x: W / 2 + (p.x - cx) / extent * S, y: H / 2 - (p.y - cy) / extent * S});
  const mid = (pts: {x: number, y: number, z: number}[]) => pts[Math.floor(pts.length / 2)];
  const aMid = series[0] && mid(series[0].points), bMid = series[1] && mid(series[1].points);
  const miss = aMid && bMid ? Math.hypot(aMid.x - bMid.x, aMid.y - bMid.y, aMid.z - bMid.z) : null;
  const niceScale = (() => {const target = extent / 4; const pow = Math.pow(10, Math.floor(Math.log10(target))); const step = [1, 2, 5, 10].find(m => m * pow >= target)! * pow; return step;})();
  const scalePx = niceScale / extent * S;
  const formatM = (m: number) => m >= 1000 ? `${number(m / 1000, 1)} km` : `${number(m, 0)} m`;
  return <div className="plot">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Paths near closest approach. Miss distance ${miss !== null ? formatM(miss) : 'unknown'}.`}>
      <line x1={W / 2} y1={10} x2={W / 2} y2={H - 10} stroke={t.grid}/>
      <line x1={10} y1={H / 2} x2={W - 10} y2={H / 2} stroke={t.grid}/>
      <text x={W - 14} y={H / 2 - 6} textAnchor="end" fill={t.muted} fontSize="11">along-track</text>
      <text x={W / 2 + 6} y={20} fill={t.muted} fontSize="11">cross-track</text>
      {ghost && <g><polyline points={ghost.map(p => {const q = project(p); return `${q.x},${q.y}`;}).join(' ')} fill="none" stroke={t.muted} strokeDasharray="3 4" strokeWidth={1.5}/>{(() => {const q = project(mid(ghost)); return <><circle cx={q.x} cy={q.y} r={4} fill={t.surface} stroke={t.muted} strokeWidth={1.5}/><text x={q.x + 8} y={q.y + 16} fill={t.muted} fontSize="11">A without burn</text></>;})()}</g>}
      {aMid && bMid && (() => {const a = project(aMid), b = project(bMid); return <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={t.text} strokeDasharray="2 3" strokeWidth={1}/>;})()}
      {/* A is drawn last so its marker stays visible when it sits on top of the other object. */}
      {[...series].reverse().map(s => {const i = s.key === 'A' ? 0 : 1; const m = project(mid(s.points)); return <g key={s.key}>
        <polyline points={s.points.map(p => {const q = project(p); return `${q.x},${q.y}`;}).join(' ')} fill="none" stroke={s.color} strokeWidth={2}/>
        {i === 0 ? <circle cx={m.x} cy={m.y} r={6} fill={t.surface} stroke={s.color} strokeWidth={3}/> : <circle cx={m.x} cy={m.y} r={5} fill={s.color} stroke={t.surface} strokeWidth={2}/>}
        <text x={i === 0 ? m.x - 10 : m.x + 10} y={i === 0 ? m.y - 8 : m.y + 16} textAnchor={i === 0 ? 'end' : 'start'} fill={t.text} fontSize="13" fontWeight="500">{s.key}</text>
      </g>;})}
      <g transform={`translate(20 ${H - 22})`}><line x1={0} y1={0} x2={scalePx} y2={0} stroke={t.text} strokeWidth={1.5}/><line x1={0} y1={-4} x2={0} y2={4} stroke={t.text}/><line x1={scalePx} y1={-4} x2={scalePx} y2={4} stroke={t.text}/><text x={scalePx / 2} y={-8} textAnchor="middle" fill={t.text} fontSize="11">{formatM(niceScale)}</text></g>
    </svg>
    <aside className="plot-side">
      <dl className="facts stacked">
        <div><dt>Policy shown</dt><dd>{policyLabel}</dd></div>
        <div><dt>Miss distance to {objectId}</dt><dd>{miss !== null ? formatM(miss) : '—'}</dd></div>
      </dl>
      <p className="small">{miss === null ? '' : miss < 100
        ? `Under this policy satellite A passes within ${formatM(miss)} of object ${objectId}: effectively on a collision course.`
        : `Under this policy satellite A passes ${formatM(miss)} from object ${objectId}.`}{ghost ? ' The grey marker shows where A would have been without the burn.' : ''}</p>
      <ul className="legend">{series.map(s => <li key={s.key}><span className="swatch" style={{background: s.color}}/>{s.label}</li>)}{ghost && <li><span className="swatch ghost"/>A without burn</li>}</ul>
      <button className="btn small" onClick={() => setZoomed(v => !v)}>{zoomed ? 'Show wider window' : 'Zoom to closest approach'}</button>
    </aside>
  </div>;
}

// ---------------------------------------------------------------- validation

function Validation() {
  const {data, loading, error, retry} = useAsync<Json>('/evidence');
  const ml = data?.ml || {}, physics = data?.physics || {}, runtime = data?.runtime || {};
  const rows: Json[] = Array.isArray(ml.metrics) ? ml.metrics : [];
  const byName = Object.fromEntries(rows.map(r => [r.name, r]));
  const scored = ['clipped_latest_baseline', 'learned_residual_scored', 'constant_minus_5'].map(n => byName[n]).filter(Boolean);
  const v = ml.validation || {};
  const rank = ml.ranking_comparison;
  const cases: Json[] = physics.validation?.cases || [];
  const checks: Json[] = physics.validation?.numerical_checks || [];
  const bench = physics.benchmark;
  const env = runtime.environment || {};
  const boot = v.paired_bootstrap?.ci95;
  const baselineRow = byName.clipped_latest_baseline;

  return <>
    <Intro title="Validation" action={<button className="btn small" disabled={loading} onClick={retry}><RefreshCw size={13} className={loading ? 'spin' : ''}/> Reload</button>}>
      Independent checks of the forecasting model, the collision-probability maths and the manoeuvre planner, plus measured speed. Everything ran on the server shown in the header, and every number on this page is read from the evaluation output files rather than typed in.
    </Intro>
    {error && <Notice retry={retry}>{error}</Notice>}
    {loading ? <Loading label="Loading evaluation results"/> : <>

    <section className="card section">
      <div className="section-head"><div><h2>Forecasting on held-out ESA data</h2>
        <p className="muted">{baselineRow ? <>{number(baselineRow.event_count, 0)} test encounters ({number(baselineRow.high_risk_event_count, 0)} high-risk) that were never used for training or model selection. </> : null}
        {v.published_baseline_reproduced ? <>Our scoring reproduces ESA's published baseline loss of {v.published_clipped_latest_loss_rounded} (we get {fixed(v.reproduced_clipped_latest_loss, 4)}), which confirms the evaluation is set up correctly.</> : null}</p></div></div>
      {scored.length ? <div className="table-wrap"><table className="table">
        <thead><tr><th>Method</th><th className="num">Challenge loss <Tip text={G.loss}/></th><th className="num">F2 <Tip text={G.f2}/></th><th className="num">Recall <Tip text={G.recall}/></th><th className="num">Precision <Tip text={G.precision}/></th><th className="num">Missed <Tip text={G.fn}/></th><th className="num">False alarms <Tip text={G.fp}/></th></tr></thead>
        <tbody>{scored.map(r => <tr key={r.name}><td>{METHOD_NAMES[r.name] || r.name}{r.name === 'clipped_latest_baseline' && ml.model?.selected_method === 'latest_baseline' && <span className="tag">Default</span>}</td>
          <td className="num">{fixed(r.challenge_loss, 3)}</td><td className="num">{fixed(r.f2, 3)}</td><td className="num">{percent(r.recall)}</td><td className="num">{percent(r.precision)}</td><td className="num">{number(r.fn, 0)}</td><td className="num">{number(r.fp, 0)}</td></tr>)}</tbody>
      </table></div> : <Empty title="Evaluation results not available">Run the held-out evaluation on the server to fill this table.</Empty>}
      {Array.isArray(boot) && <p className="finding"><strong>Point forecasts:</strong> the learned model's loss is higher than the baseline's (difference {fixed(boot[0], 2)} to {fixed(boot[1], 2)}, <Term k="ci">95% CI</Term>). The latest reported value is therefore the default forecast. Cross-validation on training data had already chosen it before the test labels were read.</p>}

      {rank && <div className="subsection">
        <h3>Ranking encounters for review</h3>
        <p className="muted">Analysts cannot inspect every alert at once, so the order matters. Here the learned model does help.</p>
        <div className="compare">
          <div><span className="figure-label">Latest reported value</span><strong>{fixed(rank.latest_average_precision, 3)}</strong><span className="small muted"><Term k="ap">Average precision</Term> · top 10% finds {percent(byName.latest_known_raw?.top_10_percent_recall)}</span></div>
          <div><span className="figure-label">Learned model</span><strong>{fixed(rank.learned_average_precision, 3)}</strong><span className="small muted"><Term k="ap">Average precision</Term> · top 10% finds {percent(byName.learned_residual_raw?.top_10_percent_recall)} <Tip text={G.top10}/></span></div>
          <div><span className="figure-label"><span>Improvement (<Term k="ci">95% CI</Term>)</span></span><strong>{Array.isArray(rank.paired_bootstrap_ap_difference_ci95) ? `+${fixed(rank.paired_bootstrap_ap_difference_ci95[0], 3)} to +${fixed(rank.paired_bootstrap_ap_difference_ci95[1], 3)}` : '—'}</strong><span className="small muted">{Array.isArray(rank.paired_bootstrap_ap_difference_ci95) && rank.paired_bootstrap_ap_difference_ci95[0] > 0 ? 'Excludes zero: unlikely to be chance' : 'Includes zero: not established'}</span></div>
        </div>
      </div>}
      {ml.ranking_curves && <div className="subsection-chart"><h3 className="subhead">Precision at every review depth <Tip text="Each point shows, if analysts reviewed encounters in the order a method ranks them until they had found a given share of high-risk encounters, what fraction of what they reviewed was truly high-risk. A curve that sits higher is a better ordering."/></h3><RankingCurve curves={ml.ranking_curves}/></div>}
    </section>

    <section className="card section">
      <div className="section-head"><div><h2>Collision probability against NASA reference cases</h2>
        <p className="muted">NASA's Conjunction Assessment Risk Analysis team publishes test cases with known answers. Our independent implementation must match each within 0.1%.</p></div></div>
      {cases.length ? <div className="table-wrap"><table className="table">
        <thead><tr><th>Reference case</th><th className="num">Expected Pc</th><th className="num">OrbitGuard Pc</th><th className="num">Relative error</th><th>Result</th></tr></thead>
        <tbody>{cases.map(c => <tr key={c.name}><td>{c.name}</td><td className="num">{probability(c.expected, 4)}</td><td className="num">{probability(c.actual, 4)}</td><td className="num">{finite(c.relative_error) ? c.relative_error.toExponential(1) : '—'}</td><td><Status ok={c.passed}>{c.passed ? 'Pass' : 'Fail'}</Status></td></tr>)}</tbody>
      </table></div> : <Empty title="Reference checks not available">Run the physics validation on the server.</Empty>}
      {checks.length > 0 && <p className="small muted checks">Also checked: {checks.map((c, i) => <span key={c.name}>{i > 0 && ', '}{c.name.charAt(0).toLowerCase() + c.name.slice(1)} ({c.passed ? 'pass' : 'fail'})</span>)}.</p>}
      <a className="link" href="https://github.com/nasa/CARA_Analysis_Tools" target="_blank" rel="noreferrer">NASA CARA Analysis Tools <ExternalLink size={12}/></a>
    </section>

    <section className="card section">
      <div className="section-head"><div><h2>Manoeuvre policies on {bench?.scenario_count ?? 50} test scenarios</h2>
        <p className="muted">A fixed set of simulated scenarios, designed in advance to stress each policy: {bench?.suite_distribution ? Object.entries(bench.suite_distribution as Record<string, number>).map(([k, n]) => `${n} ${({clear: 'with nothing to avoid', primary: 'with one hazard', secondary: 'where avoiding one object endangers another', blocked: 'with no safe option'} as Record<string, string>)[k] || k}`).join(', ') : 'see the evaluation file'}. The mix is a stress test, not a sample of real-world traffic.</p></div></div>
      {bench?.policies && <PolicyBars policies={bench.policies} total={bench.scenario_count} names={POLICIES.map(p => ({id: p.id, label: p.id === 'pair_only' ? 'Avoid primary object only' : p.label}))}/>}
      {bench?.policies ? <div className="table-wrap"><table className="table">
        <thead><tr><th>Policy</th><th className="num">Acceptable plans</th><th className="num">New hazards created</th><th className="num">Unsafe choices</th><th className="num">Correctly declined</th><th className="num">Mean <Term k="dv">Δv</Term> (m/s)</th></tr></thead>
        <tbody>{POLICIES.map(p => {const r = bench.policies[p.id]; return r ? <tr key={p.id}><td>{p.label}</td><td className="num">{r.acceptable_plan_count} / {bench.scenario_count}</td><td className="num">{r.secondary_hazards_introduced}</td><td className="num">{r.unsafe_selected_count}</td><td className="num">{r.correct_abstentions}</td><td className="num">{fixed(r.mean_delta_v_mps, 4)}</td></tr> : null;})}</tbody>
      </table></div> : <Empty title="Scenario results not available">Run the planner benchmark on the server.</Empty>}
      {bench?.policies && <p className="finding"><strong>Result:</strong> avoiding only the primary object created {bench.policies.pair_only?.secondary_hazards_introduced} new hazards; OrbitGuard created {bench.policies.orbitguard?.secondary_hazards_introduced}, with the same average Δv. {bench.failed_scenarios === 0 ? 'No scenario failed to compute.' : `${bench.failed_scenarios} scenarios failed to compute.`}</p>}
    </section>

    <section className="card section">
      <div className="section-head"><div><h2>Speed on this server</h2>
        <p className="muted">{env.architecture ? `Measured on ${env.is_linuxone ? 'IBM LinuxONE' : 'a development machine'} (${env.architecture}, ${env.available_cpus} CPUs, Python ${env.python_version}). ` : ''}Times cover the server-side computation only, not network transfer to your browser.</p></div></div>
      {runtime.forecast ? <div className="table-wrap"><table className="table">
        <thead><tr><th>Task</th><th className="num">Runs</th><th className="num">Median</th><th className="num">p95 <Tip text={G.p95}/></th></tr></thead>
        <tbody>
          <tr><td>Forecast one encounter</td><td className="num">{runtime.forecast.count}</td><td className="num">{number(runtime.forecast.p50_ms, 1)} ms</td><td className="num">{number(runtime.forecast.p95_ms, 1)} ms</td></tr>
          <tr><td>Screen 37 candidate burns, including re-check</td><td className="num">{runtime.screening?.count}</td><td className="num">{number((runtime.screening?.p50_ms ?? 0) / 1000, 2)} s</td><td className="num">{number((runtime.screening?.p95_ms ?? 0) / 1000, 2)} s</td></tr>
        </tbody>
      </table></div> : <Empty title="Timing results not available">Run the runtime benchmark on the server.</Empty>}
      {runtime.parallel_comparison && <p className="finding"><strong>Parallel screening:</strong> {runtime.parallel_comparison.workloads} scenarios took {number(runtime.parallel_comparison.serial_seconds, 1)} s one at a time and {number(runtime.parallel_comparison.parallel_seconds, 1)} s across {runtime.parallel_comparison.workers} CPU cores, {number(runtime.parallel_comparison.speedup, 2)}× faster.</p>}
    </section>

    <section className="card section">
      <div className="section-head"><div><h2>Data, provenance and limits</h2></div></div>
      <dl className="provenance">
        <div><dt>Dataset</dt><dd><a className="link" href="https://zenodo.org/records/4463683" target="_blank" rel="noreferrer">ESA Collision Avoidance Challenge <ExternalLink size={12}/></a> · CC BY 4.0</dd></div>
        <div><dt>Training encounters</dt><dd>{number(ml.model?.data?.train_events, 0)} ({number(ml.model?.data?.train_high_risk_events, 0)} high-risk)</dd></div>
        <div><dt>Model fingerprint (SHA-256, before labels were read)</dt><dd className="mono">{v.frozen_model_sha256_before_labels ? `${v.frozen_model_sha256_before_labels.slice(0, 16)}…` : '—'}</dd></div>
        <div><dt>Scenario suite fingerprint</dt><dd className="mono">{bench?.suite_sha256 ? `${bench.suite_sha256.slice(0, 16)}…` : '—'}</dd></div>
        <div><dt>NASA reference version</dt><dd className="mono">{physics.validation?.reference_commit ? physics.validation.reference_commit.slice(0, 12) : '—'}</dd></div>
        <div><dt>Timings recorded</dt><dd>{runtime.generated_at ? new Date(runtime.generated_at).toLocaleString() : '—'}</dd></div>
      </dl>
      {Array.isArray(ml.limitations) && <><h3>Limitations</h3><ul className="limits">{ml.limitations.map((l: string) => <li key={l}>{l}</li>)}<li>The manoeuvre simulator uses two-body gravity, instantaneous burns and assumed (not tracked) position uncertainty. OrbitGuard supports a human operator; it does not command spacecraft.</li></ul></>}
      <details className="raw"><summary>Raw evaluation data (JSON)</summary><pre>{JSON.stringify(data, null, 2)}</pre></details>
    </section>
    </>}
  </>;
}
