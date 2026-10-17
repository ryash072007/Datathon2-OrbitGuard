import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDownToLine, BookOpen, Compass, ExternalLink, Loader2, Moon, Pause, Play, RefreshCw, Sun } from 'lucide-react';
import { G, POLICIES, Empty, Loading, Notice, Status, Term, Tip, applyTheme, readTheme, useAsync, useTokens } from './ui';
import type { ThemeName } from './ui';
import { Starfield } from './Starfield';
import { Guide, TryThis, dismissGuide, guideDismissed, reopenGuide } from './Guide';
import { Glossary } from './Glossary';
import { PolicyBars, PopulationChart, RankingCurve } from './Charts';
import { AuditPanel, DecisionCard, DecisionEvidence, LiveCatalogue, OperatorActions, PlatformEvidence } from './Live';

// The 3D views pull in three.js, so they load on first use rather than with the page.
const OrbitalView = lazy(() => import('./Visuals').then(m => ({default: m.OrbitalView})));
const EncounterOrbits = lazy(() => import('./Visuals').then(m => ({default: m.EncounterOrbits})));
const loadingGlobe = <Loading label="Loading 3D view"/>;
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { finite, fixed, logProbability, number, percent, post, powerOfTen, probability, request } from './api';
import type { Json } from './api';
import { AiEvidence } from './AiEvidence';

type Tab = 'overview' | 'encounters' | 'planning' | 'live' | 'validation';
const TABS: [Tab, string][] = [['encounters', 'Encounters'], ['planning', 'Manoeuvre planning'], ['live', 'Live catalogue'], ['validation', 'Validation'], ['overview', 'How it works']];

const METHOD_NAMES: Record<string, string> = {
  clipped_latest_baseline: 'Latest reported value (ESA baseline)',
  learned_residual_scored: 'Learned model',
  constant_minus_5: 'Constant 10⁻⁵ (reference)',
};

function Intro({title, children, action}: {title: string, children: ReactNode, action?: ReactNode}) {return <div className="intro"><div><h1>{title}</h1><p className="lead">{children}</p></div>{action}</div>;}
function OrbitMark() {return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/><ellipse cx="12" cy="12" rx="10" ry="4.6" transform="rotate(-25 12 12)"/></svg>;}

// ---------------------------------------------------------------- shell

function gapText(days: number | null): string {
  if (days === null || !finite(days)) return '';
  const hours = days * 24;
  return hours >= 1 ? `${number(hours, 1)} h` : `${number(hours * 60, 0)} min`;
}

function RealTimeStrip() {
  const [lat, setLat] = useState<Json | null>(null);
  useEffect(() => {
    let alive = true;
    const poll = () => request<Json>('/latency').then(d => {if (alive) setLat(d);}).catch(() => {if (alive) setLat(null);});
    poll();
    const timer = window.setInterval(poll, 4000);
    return () => {alive = false; window.clearInterval(timer);};
  }, []);
  const f = lat?.stages?.forecast, p = lat?.platform;
  const where = p ? (p.is_linuxone ? `${p.machine} (IBM LinuxONE)` : `${p.machine} (development machine, not LinuxONE)`) : '—';
  return <div className="rt-strip" role="status" aria-label="Real-time decision latency"><div className="rt-inner">
    <span className="rt-label"><span className={`dot ${f ? 'on' : ''}`}/><Tip text="How long the server took to forecast and decide on recent warnings, measured live on this server."><span className="term">Real time</span></Tip></span>
    <span>Last decision <strong>{f ? `${number(f.last_ms, 1)} ms` : '—'}</strong></span>
    <span>median {f ? `${number(f.p50_ms, 1)} ms` : '—'}</span>
    <span>p95 <strong>{f ? `${number(f.p95_ms, 1)} ms` : '—'}</strong></span>
    <span className="muted">{f ? `over ${number(f.n, 0)} decisions` : 'no decisions yet'}</span>
    <span>on <strong>{where}</strong>{p?.nnpa ? ' · NNPA present' : ''}</span>
  </div></div>;
}

export default function App() {
  const [tab, setTab] = useState<Tab>(() => {const hash = location.hash.slice(1); return (TABS.some(([id]) => id === hash) ? hash : 'encounters') as Tab;});
  const health = useAsync<Json>('/health');
  useEffect(() => {history.replaceState(null, '', `#${tab}`); document.title = `${TABS.find(([id]) => id === tab)?.[1]} · OrbitGuard`;}, [tab]);
  useEffect(() => {
    const follow = () => {const hash = location.hash.slice(1); if (TABS.some(([id]) => id === hash)) setTab(hash as Tab);};
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  }, []);
  const onLinuxONE = health.data?.architecture === 's390x';
  const [theme, setThemeState] = useState<ThemeName>(readTheme);
  const [guideShown, setGuideShown] = useState(() => !guideDismissed());
  const [glossary, setGlossary] = useState(false);
  const switchTheme = () => {const next: ThemeName = theme === 'dark' ? 'light' : 'dark'; applyTheme(next); setThemeState(next);};
  const goTab = (next: Tab) => {setTab(next); window.scrollTo(0, 0);};
  const showGuide = () => {reopenGuide(); setGuideShown(true); window.scrollTo(0, 0);};
  return <div className="app">
    <Starfield/>
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
      <div className="header-tools">
        <button className="btn small tool" aria-label="Show the guide" onClick={showGuide}><Compass size={15}/><span className="tool-label">Guide</span></button>
        <button className="btn small tool" aria-label="Open key terms" aria-expanded={glossary} onClick={() => setGlossary(open => !open)}><BookOpen size={15}/><span className="tool-label">Key terms</span></button>
        <button className="btn small tool" aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} onClick={switchTheme}>{theme === 'dark' ? <Sun size={15}/> : <Moon size={15}/>}</button>
      </div>
    </div><RealTimeStrip/></header>
    <Glossary open={glossary} onClose={() => setGlossary(false)}/>
    <main className="page">
      {health.error && <Notice retry={health.retry}>Cannot reach the OrbitGuard server: {health.error}</Notice>}
      {guideShown && <Guide tab={tab} setTab={goTab} onGlossary={() => setGlossary(true)} onHide={() => {dismissGuide(); setGuideShown(false);}}/>}
      {tab === 'overview' ? <Overview/> : tab === 'encounters' ? <Encounters/> : tab === 'planning' ? <Planning/> : tab === 'live' ? <LiveCatalogue/> : <Validation/>}
    </main>
  </div>;
}

// ---------------------------------------------------------------- encounters

function EvidenceDownload({data}: {data: Json | null}) {
  function download() {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'orbitguard-evidence.json'; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <button className="btn small" disabled={!data} onClick={download}><ArrowDownToLine size={14}/> Download evidence JSON</button>;
}

function Overview() {
  const {data, loading, error, retry} = useAsync<Json>('/evidence');
  const ml = data?.ml || {}, physics = data?.physics || {};
  const rows: Json[] = Array.isArray(ml.metrics) ? ml.metrics : [];
  const baseline = rows.find(row => row.name === 'clipped_latest_baseline');
  const ranking = ml.ranking_comparison;
  const validation = ml.validation || {};
  const cases: Json[] = physics.validation?.cases || [];
  const planner = physics.benchmark;
  return <>
    <Intro title="Understand the risk. Check the whole orbit." action={<EvidenceDownload data={data}/>}>OrbitGuard helps an operator decide what to do about a close approach: how likely it is, whether an avoidance burn creates a second hazard, and what a collision would cost everyone else in orbit. Start with the evidence below, then explore historical forecasts, a synthetic stress test or the live catalogue.</Intro>
    <p className="page-note">The method behind each page, and what the evidence does and does not support.</p>
    <div className="overview-tracks three">
      <section className="card track"><span className="tag">Historical ESA data</span><h2>Forecast a later risk estimate</h2><p>Use only messages available at least 48 hours before closest approach to estimate ESA's final reported collision probability. Replay a held-out encounter and compare the baseline with the learned forecast.</p><a className="btn" href="#encounters">Explore encounters</a></section>
      <section className="card track"><span className="tag">Synthetic simulation</span><h2>Test a manoeuvre against every object</h2><p>Compare no burn, avoiding one object, and OrbitGuard's screening of every nearby object. Check fuel cost, uncertainty sensitivity and a finer numerical re-check before accepting a plan.</p><a className="btn" href="#planning">Open manoeuvre planning</a></section>
      <section className="card track"><span className="tag">Real CelesTrak catalogue</span><h2>Screen a real satellite, see the cost</h2><p>Find a satellite's next close approach among about 18,000 tracked objects, screen 145 burns with the same validated Pc rule, model the debris a collision would create, and read a Granite-written brief whose numbers are checked against the computation.</p><a className="btn primary" href="#live">Open the live catalogue</a></section>
    </div>
    <section className="card section" aria-label="Evidence at a glance">
      <div className="card-head"><div><h2>What the evidence supports</h2><p className="muted small">Read directly from the server's evaluation artifacts. Missing results stay explicitly unavailable.</p></div><button className="btn small" disabled={loading} onClick={retry}><RefreshCw size={13} className={loading ? 'spin' : ''}/> Reload</button></div>
      {error ? <Notice retry={retry}>{error}</Notice> : loading ? <Loading label="Loading evidence summary"/> : <>
        <div className="evidence-grid">
          <article><h3>Forecast detection</h3>{baseline ? <><strong>{percent(baseline.recall)} recall</strong><p>{number(baseline.fn, 0)} missed high-risk encounters out of {number(baseline.high_risk_event_count, 0)} in {number(baseline.event_count, 0)} held-out encounters, using the ESA baseline.</p><p className="small muted">Challenge loss {fixed(baseline.challenge_loss, 3)}. Baseline reproduction: {validation.published_baseline_reproduced === true ? 'passed' : validation.published_baseline_reproduced === false ? 'failed' : 'unavailable'}.</p></> : <p>Forecast evaluation unavailable.</p>}</article>
          <article><h3>Review ranking</h3>{ranking ? <><strong>{fixed(ranking.learned_average_precision, 3)} average precision</strong><p>Learned ranking; latest-value ranking scores {fixed(ranking.latest_average_precision, 3)}. Ranking quality and threshold detection measure different tasks.</p><p className="small muted">{ranking.interpretation || 'Inspect the paired confidence interval in Validation before claiming an improvement.'}</p></> : <p>Ranking evaluation unavailable.</p>}</article>
          <article><h3>Physics checks</h3>{cases.length ? <><strong>{cases.filter(item => item.passed).length} / {cases.length} reference cases passed</strong><p>Collision probability compared with independently published NASA cases.</p></> : <p>NASA reference checks unavailable.</p>}{planner?.policies?.orbitguard && <p className="small muted">Synthetic planner: {number(planner.policies.orbitguard.unsafe_selected_count, 0)} unsafe choices in {number(planner.scenario_count, 0)} stress scenarios.</p>}</article>
        </div>
        <a className="link" href="#validation">Inspect metrics, confidence intervals and provenance</a>
      </>}
    </section>
    <p className="scope-note">These forecasts estimate a later reported risk, not an observed collision. Historical ESA encounters do not supply the simulated manoeuvre geometry. Synthetic planning uses assumed uncertainty and simplified dynamics; recommendations support human review.</p>
  </>;
}

function Encounters() {
  const list = useAsync<Json>('/events?limit=100');
  const events: Json[] = list.data?.events || [];
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get('event') || '');
  const [filter, setFilter] = useState('');
  const [replayCount, setReplayCount] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [forecast, setForecast] = useState<Json | null>(null);
  const [forecastBusy, setForecastBusy] = useState(false);
  const [updates, setUpdates] = useState<Json[]>([]);
  const [replayAttempt, setReplayAttempt] = useState(0);
  useEffect(() => {if (!selected && events.length) setSelected(String(events[0].event_id));}, [events, selected]);
  const detail = useAsync<Json>(selected ? `/events/${encodeURIComponent(selected)}` : null);
  const event = detail.data && String(detail.data.event_id) === selected ? detail.data : null;
  const history: Json[] = event?.history || event?.messages || [];
  useEffect(() => {setReplayCount(null); setPlaying(false); setForecastBusy(false); setForecast(event?.forecast || null); setUpdates([]);}, [event]);
  useEffect(() => {
    if (!playing || forecastBusy || !history.length || replayCount === null || !updates.some(update => update.message_count === replayCount)) return;
    if (replayCount >= history.length) {setPlaying(false); return;}
    const timer = window.setTimeout(() => setReplayCount(replayCount + 1), 1000);
    return () => window.clearInterval(timer);
  }, [playing, history.length, replayCount, updates, forecastBusy]);
  useEffect(() => {
    if (replayCount === null || !event) return;
    let alive = true;
    setForecastBusy(true); setForecast(null);
    setUpdates(current => current.filter(update => update.message_count !== replayCount));
    const timer = window.setTimeout(() => {
      const started = performance.now();
      post('/replay/update', {event_id: String(event.event_id), message_count: replayCount})
        .then(update => {if (alive) {setForecast(update.forecast); setUpdates(current => [...current.filter(item => item.message_count !== update.message_count), {...update, roundtrip_ms: performance.now() - started}].sort((first, second) => first.message_count - second.message_count));}})
        .catch(e => {if (alive) {setForecast({error: e.message}); setPlaying(false);}})
        .finally(() => {if (alive) setForecastBusy(false);});
    }, 150);
    return () => {alive = false; window.clearTimeout(timer);};
  }, [event, replayCount, replayAttempt]);

  const toPoint = (row: Json, i: number) => ({day: finite(row.time_to_tca) ? row.time_to_tca : i, risk: row.risk ?? row.log10_pc});
  const full = history.map(toPoint).filter(p => finite(p.risk)).sort((a, b) => b.day - a.day);
  const shown = history.slice(0, replayCount ?? history.length).map(toPoint).filter(p => finite(p.risk)).sort((a, b) => b.day - a.day);
  const reference = event?.reference?.true_log10_pc;
  const visible = events.filter(e => String(e.event_id).includes(filter.trim().replace(/^#/, '')));
  const lastDay = full.length ? full[full.length - 1].day : null;
  const population = useAsync<Json>('/population');
  const latestMessage = history.length ? history[(replayCount ?? history.length) - 1] : null;

  return <>
    <Intro title="Encounters">
      Historical close approaches from the held-out test set of ESA's Collision Avoidance Challenge. Each encounter is a series of <Term k="cdm">conjunction data messages</Term> issued in the days before two objects pass closest. Select one to replay its messages and compare forecasts of the <Term k="final">final reported collision probability</Term>.
    </Intro>
    <TryThis tab="encounters" steps={['Pick an encounter from the list; the highest risk is at the top.', 'Press Play stream to replay its messages in order.', 'Read the decision card: Act, Wait or Monitor, and the reasons behind it.']}/>
    {list.error && <Notice retry={list.retry}>{list.error}</Notice>}
    <div className="encounters-layout">
      <section className="card list-card" aria-label="Encounter list">
        <div className="card-head">
          <h2>Highest-risk encounters</h2>
          <span className="muted small">Showing {events.length || '—'}, ordered by latest <Term k="pc">Pc</Term></span>
        </div>
        <div className="search-control"><input className="search" type="search" aria-label="Search by encounter number" placeholder="Search by encounter number" value={filter} onChange={e => setFilter(e.target.value)}/>{filter && <button className="btn small" onClick={e => {setFilter(''); e.currentTarget.parentElement?.querySelector('input')?.focus();}}>Clear search</button>}</div>
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
        {detail.error ? <Notice retry={detail.retry}>{detail.error}</Notice> : !selected && !list.loading ? <Empty title="Select an encounter">{list.error ? 'Retry loading the encounter list.' : 'An available encounter will appear here once selected.'}</Empty> : !event ? <Loading label="Loading encounter"/> : full.length ? <>
          <div className="card-head">
            <div><h2>Encounter #{selected}</h2><p className="muted small">{history.length} messages; the last one was issued {number(lastDay, 2)} days before closest approach.</p></div>
          </div>
          <h3 className="subhead">Reported collision probability over time <Tip text={`${G.pc} ${G.threshold}`}/></h3>
          <RiskChart data={shown} full={full}/>
          <div className="replay">
            <button className="btn icon" aria-label={playing ? 'Pause replay' : 'Replay messages one by one'} onClick={() => {if (playing) {setPlaying(false); return;} if (replayCount === null || replayCount >= history.length) {setUpdates([]); setReplayCount(1);} setPlaying(true);}}>{playing ? <Pause size={14}/> : <Play size={14}/>}<span>{playing ? 'Pause' : 'Play stream'}</span></button>
            <input aria-label="Historical message replay position" type="range" min="1" max={history.length} value={replayCount ?? history.length} onChange={e => {setPlaying(false); setReplayCount(Number(e.target.value));}}/>
            <span className="small muted replay-count">Message {replayCount ?? history.length} of {history.length}{forecastBusy && <Loader2 size={12} className="spin"/>}</span>
          </div>
          <div className="figures">
            <div className="figure"><span className="figure-label">Latest reported value <Tip text={G.latest}/></span><strong>{logProbability(forecast?.baseline_log10_pc)}</strong><span className="tag">Default forecast</span></div>
            <div className="figure"><span className="figure-label">Learned model <Tip text={G.learned}/></span><strong>{logProbability(forecast?.learned_forecast_log10_pc)}</strong></div>
            <div className="figure muted-figure"><span className="figure-label">Final reported value <Tip text={G.final}/></span><strong>{logProbability(reference)}</strong><span className="small muted">Revealed for comparison</span></div>
          </div>
          {forecast?.error && <Notice retry={() => setReplayAttempt(current => current + 1)}>{forecast.error}</Notice>}
          <DecisionCard decision={forecast?.decision} eventId={selected}/>
          {updates.length > 0 && <section className="replay-timeline" aria-label="Update processing timeline">
            <h3 className="subhead">Update → forecast → alert</h3>
            <p className="small muted">Historical replay, not a live feed: messages arrive hours apart, and every new one gets a fresh decision in milliseconds. Each step waits for the server before continuing. Alert changes compare consecutive message prefixes, even when you scrub.</p>
            <ol aria-live="polite" className="ticker">{updates.slice(-8).map(update => {
              const next = history[update.message_count];
              const gapDays = next && finite(next.time_to_tca) && finite(update.message_time_to_tca_days) ? update.message_time_to_tca_days - next.time_to_tca : null;
              return <li key={update.message_count}>
                <strong>Message {update.message_count}</strong>
                <span className="badge-ms" title="Server time to run the forecast and decision layer for this message">{number(update.forecast?.elapsed_ms, 1)} ms</span>
                <span>{update.alert.state === 'high_risk' ? 'High-risk alert' : update.alert.state === 'additional_review' ? 'Additional review (experimental)' : 'Monitor'}{update.alert.changed ? ' — changed' : ''}</span>
                <span className="small muted">Issued {number(update.message_time_to_tca_days, 2)} days before closest approach. {gapDays !== null ? `The next message in this encounter arrived ${gapText(gapDays)} later; the decision took ${number(update.forecast?.elapsed_ms, 0)} ms.` : `This is the last message in the encounter; the decision took ${number(update.forecast?.elapsed_ms, 0)} ms.`} ({number(update.roundtrip_ms, 0)} ms including the network round trip.)</span>
              </li>;
            })}</ol>
            {updates.find(update => update.message_count === replayCount) && <p className="small">{updates.find(update => update.message_count === replayCount)?.action}</p>}
            <p className="small muted">Synthetic manoeuvre screening remains separate: ESA histories do not provide the planning geometry.</p>
          </section>}
          <p className="footnote">Forecasts use only messages issued at least 48 hours before closest approach. They estimate the final reported risk; they do not predict whether a collision happens.</p>
          {forecast?.supplemental_review?.additional_review && <p className="finding" role="status"><strong>Additional review advised (experimental).</strong> The learned escalation rule flags this encounter even though the baseline is below the high-risk threshold. The displayed default forecast is unchanged. <a href="#validation">See the missed-alert and false-alarm comparison.</a></p>}
        </> : <Empty title="No message history for this encounter"/>}
      </section>
    </div>
    <div className="encounters-visuals">
      <section className="card" aria-label="Orbits of the two objects">
        <div className="card-head"><div><h2>Orbits of the two objects</h2><p className="muted small">Encounter #{selected}: the ESA satellite and the object that came close to it.</p></div></div>
        {latestMessage ? <Suspense fallback={loadingGlobe}><EncounterOrbits message={latestMessage}/></Suspense> : list.loading || detail.loading ? <Loading label="Loading encounter"/> : <Empty title="No orbital data available"/>}
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
  const runVersion = useRef(0);
  useEffect(() => () => {runVersion.current += 1;}, []);
  useEffect(() => {setResult(null); setJob(null); setError(''); setFocus('primary'); setActivePolicy('orbitguard');}, [selected]);

  async function run() {
    const version = ++runVersion.current;
    const isCurrent = () => version === runVersion.current;
    setBusy(true); setError(''); setResult(null);
    try {
      const start = await post('/screen', {scenario_id: selected});
      if (!isCurrent()) return;
      setJob(start);
      for (let attempt = 0; attempt < 600 && isCurrent(); attempt++) {
        await new Promise(resolve => setTimeout(resolve, 600));
        if (!isCurrent()) return;
        const update = await request(`/jobs/${start.job_id}`);
        if (!isCurrent()) return;
        setJob(update);
        if (update.status === 'completed') {setResult(update.result); return;}
        if (update.status === 'failed') throw new Error(update.error?.message || 'Screening failed on the server.');
      }
      if (isCurrent()) throw new Error('Stopped waiting after six minutes. The server job may still be running; check its status before starting another screening.');
    } catch (e) {if (isCurrent()) setError((e as Error).message);} finally {if (isCurrent()) setBusy(false);}
  }

  const views = result?.encounter_views || scenario?.encounter_views;
  const primaryId: string = views?.primary?.object_id || 'B';
  const secondaryId: string | undefined = views?.secondary?.object_id;
  const policies: Json = result?.policies || {};
  const activeAbstained = Boolean(result && policies[activePolicy]?.abstained);
  const noPolicyPath = <Empty title="No accepted manoeuvre for this policy">Select No manoeuvre to inspect the original trajectory. A declined plan is not an avoidance trajectory.</Empty>;
  const assumptions: string[] = Array.isArray(result?.assumptions || scenario?.assumptions) ? (result?.assumptions || scenario?.assumptions) : [];

  return <>
    <Intro title="Manoeuvre planning">
      Synthetic simulation, separate from the historical ESA forecast. OrbitGuard tries 37 candidate burns for satellite A, checks each one against every nearby object, and recommends the smallest acceptable burn below the <Term k="limit">risk limit</Term>. A burn that avoids one object can steer into another; the first scenario demonstrates this failure mode.
    </Intro>
    <TryThis tab="planning" steps={['Choose a scenario; the first one shows the trap.', 'Press Screen manoeuvres.', 'Select a policy row, then jump to each closest approach in the orbital view.']}/>
    <section className="card toolbar">
      <label className="field"><span>Scenario</span>
        <select aria-label="Scenario" value={selected} disabled={busy || !scenarios.length} onChange={e => setSelected(e.target.value)}>
          {!scenarios.length && <option>{list.loading ? 'Loading' : 'No scenarios available'}</option>}
          {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.name || s.scenario_id}</option>)}
        </select>
      </label>
      <p className="toolbar-text">{scenario?.description || ' '}</p>
      <button className="btn primary" disabled={!scenario || busy} onClick={run}>{busy ? <Loader2 className="spin" size={15}/> : <Play size={15}/>}{busy ? 'Screening' : result ? 'Run again' : 'Screen manoeuvres'}</button>
    </section>
    {(error || list.error || scenarioReq.error) && <Notice retry={error ? undefined : scenarioReq.error ? scenarioReq.retry : list.retry}>{error || list.error || scenarioReq.error}</Notice>}
    {error && job?.job_id && <a className="link" href={`/api/jobs/${encodeURIComponent(job.job_id)}`} target="_blank" rel="noreferrer">Check server job status <ExternalLink size={12}/></a>}

    <Recommendation result={result} busy={busy} job={job} primaryId={primaryId}/>

    <section className="card" aria-label="Orbital view">
      <div className="card-head">
        <div><h2>Orbital view <Tip text="Paths over the three-hour planning window in an Earth-centred inertial frame, so the Earth is drawn without its rotation. Altitudes are to scale; at this scale a near miss of a few metres looks like a collision, so use the distance chart and the encounter geometry for close-range detail."/></h2><p className="muted small">Satellite A and every tracked object nearby, for the policy selected in the table below. {result ? '' : 'Showing the paths before any burn; run the screening to compare policies.'}</p></div>
      </div>
      {activeAbstained ? noPolicyPath : (result?.trajectories || scenario?.trajectories)?.length ? <Suspense fallback={loadingGlobe}><OrbitalView trajectories={result?.trajectories || scenario?.trajectories} activePolicy={result ? activePolicy : 'no_action'} policyLabel={activePolicy === 'pair_only' && result ? `Avoid ${primaryId} only` : result ? POLICIES.find(p => p.id === activePolicy)?.label || '' : 'No manoeuvre'} primaryId={primaryId} secondaryId={secondaryId} burnTime={policies[activePolicy]?.burn_time_seconds} primaryTca={scenario?.primary_tca_seconds} secondaryTca={scenario?.secondary_tca_seconds}/></Suspense> : list.loading || scenarioReq.loading ? <Loading label="Loading scenario"/> : <Empty title="Scenario geometry unavailable">Choose an available scenario or retry the failed request above.</Empty>}
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
        {activeAbstained ? noPolicyPath : <OrbitPlot view={views?.[focus]} activePolicy={result ? activePolicy : 'no_action'} policyLabel={!result ? 'No manoeuvre' : activePolicy === 'pair_only' ? `Avoid ${primaryId} only` : POLICIES.find(p => p.id === activePolicy)?.label || ''} hasResult={Boolean(result)}/>}
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
      <div><dt>Numerical re-check <Tip text={G.verify}/></dt><dd>{verification ? <Status ok={verification.status === 'passed'}>{verification.status === 'passed' ? 'Passed' : verification.status === 'rejected' ? 'Rejected: risk limit exceeded' : 'Failed'}</Status> : '—'}</dd></div>
    </dl>
    {job?.job_id && <a className="btn small" href={`/api/runs/${job.job_id}`} download><ArrowDownToLine size={14}/> Download screening result</a>}
    <OperatorActions context="planning" reference={`${result.scenario_id}:${rec?.candidate_id || 'abstained'}`} recommendation={{status: result.status, candidate: rec?.candidate_id, delta_v_mps: rec?.delta_v_mps, worst_pc: chosen.worst_pc}}/>
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
        ? `Under this policy satellite A passes within ${formatM(miss)} of object ${objectId}. Distance alone does not establish a collision: Pc also depends on object size and position uncertainty.`
        : `Under this policy satellite A passes ${formatM(miss)} from object ${objectId}.`}{ghost ? ' The grey marker shows where A would have been without the burn.' : ''}</p>
      <ul className="legend">{series.map(s => <li key={s.key}><span className="swatch" style={{background: s.color}}/>{s.label}</li>)}{ghost && <li><span className="swatch ghost"/>A without burn</li>}</ul>
      <button className="btn small" onClick={() => setZoomed(v => !v)}>{zoomed ? 'Show wider window' : 'Zoom to closest approach'}</button>
    </aside>
  </div>;
}

// ---------------------------------------------------------------- validation

function interval(values: unknown, asPercent = false) {
  if (!Array.isArray(values) || values.length !== 2 || !values.every(finite)) return 'Unavailable';
  const format = asPercent ? percent : (value: number) => fixed(value, 3);
  return `${format(values[0])} to ${format(values[1])}`;
}

function TriageEvidence({evaluation}: {evaluation: Json | undefined}) {
  if (!evaluation?.metrics || !evaluation.baseline) return null;
  const bounds = evaluation.paired_bootstrap?.ci95;
  const supported = Array.isArray(bounds) && bounds.length === 2 && bounds.every(finite);
  const interpretation = !supported ? 'Ranking uncertainty unavailable.' : bounds[0] > 0 ? 'The interval favours triage ranking.' : bounds[1] < 0 ? 'The interval favours latest-value ranking.' : 'The interval crosses zero; a ranking improvement is not established.';
  return <div className="subsection" aria-label="Experimental triage evaluation"><h3>Experimental alert triage</h3><p className="muted">A separate classifier estimates whether the final reported risk meets Pc ≥ 10⁻⁶. Its score is a high-risk label score, not collision probability. It does not replace the deployed forecast or drive manoeuvre screening.</p><div className="table-wrap"><table className="table compact"><thead><tr><th>Review method</th><th className="num">Average precision</th><th className="num">Top 10% recall</th><th className="num">Recall</th><th className="num">Precision</th><th className="num">Missed alerts</th><th className="num">False alarms</th></tr></thead><tbody>{[['Latest-value ranking', evaluation.baseline], ['Experimental triage', evaluation.metrics]].map(([name, raw]) => {const row = raw as Json; return <tr key={name as string}><td>{name as string}</td><td className="num">{fixed(row.average_precision, 3)}</td><td className="num">{percent(row.top_10_percent_recall)}</td><td className="num">{percent(row.recall)}</td><td className="num">{percent(row.precision)}</td><td className="num">{number(row.fn, 0)}</td><td className="num">{number(row.fp, 0)}</td></tr>;})}</tbody></table></div><p className="footnote">Triage minus raw latest average precision, paired 95% CI: {interval(bounds)}. {interpretation} Compare missed alerts and false alarms separately from ranking; higher recall can require more false alarms.</p><p className="footnote">Classifier alert threshold: {fixed(evaluation.model?.threshold, 3)}. {evaluation.validation?.threshold_selected_on_training_only === true ? 'Selected using training validation only.' : 'Training-only threshold selection is not confirmed by this artifact.'} This is a retrospective public-test evaluation.</p></div>;
}

function AccuracyAudit({audit}: {audit: Json | undefined}) {
  const names: Record<string, string> = {latest_baseline: 'Latest reported value', learned_residual: 'Learned model', high_risk_shrinkage: 'Experimental shrinkage'};
  if (!audit || audit.status !== 'ready') return <section className="card section"><h2 className="subhead">Deeper accuracy audit</h2><Empty title="Accuracy audit pending">Recall uncertainty, raw forecast errors and the experimental shrinkage comparison will appear after a matching model audit is generated.</Empty></section>;
  const baseline = audit.methods?.latest_baseline;
  const shrinkage = audit.shrinkage;
  return <section className="card section" aria-label="Accuracy audit">
    <div className="section-head"><div><h2>How accurate are the forecasts?</h2><p className="muted">A retrospective recheck of the public ESA test set, which earlier project versions have already evaluated. This is not a new blind test.</p></div></div>
    {baseline && <p className="finding">Always calling every encounter low-risk would score {percent(baseline.always_low_risk_accuracy)} overall accuracy while detecting no high-risk encounters. Read recall, missed alerts and uncertainty alongside loss.</p>}
    <div className="table-wrap"><table className="table"><thead><tr><th>Method</th><th className="num">Recall (95% interval)</th><th className="num">Precision (95% interval)</th><th className="num">Missed alerts</th><th className="num">Raw log₁₀ MAE</th><th className="num">Raw log₁₀ RMSE</th></tr></thead><tbody>{Object.entries(audit.methods || {}).map(([name, value]) => {const method = value as Json; return <tr key={name}><td>{names[name] || name}</td><td className="num">{percent(method.recall)}<div className="small muted">{interval(method.recall_ci95, true)}</div></td><td className="num">{percent(method.precision)}<div className="small muted">{interval(method.precision_ci95, true)}</div></td><td className="num">{number(method.fn, 0)}</td><td className="num">{fixed(method.log10_mae, 3)}</td><td className="num">{fixed(method.log10_rmse, 3)}</td></tr>;})}</tbody></table></div>
    <p className="footnote">Wilson 95% intervals quantify sampling uncertainty, not deployment guarantees. MAE and RMSE use raw log₁₀ forecasts before challenge clipping; a difference of 1 log₁₀ unit is a tenfold probability ratio.</p>
    {shrinkage && <div className="subsection"><h3>Experimental shrinkage: a small forecast adjustment</h3><p className="muted">Fits one coefficient using training events, moving high-risk latest values toward the alert threshold while preserving alert decisions. {shrinkage.default_changed ? 'The artifact records a default-method change; verify deployment metadata.' : 'The deployed default remains unchanged.'}</p><dl className="facts audit-facts"><div><dt>Training cross-validation loss</dt><dd>{fixed(shrinkage.cv_baseline?.challenge_loss, 4)} → {fixed(shrinkage.cv_challenger?.challenge_loss, 4)}</dd></div><div><dt>Training loss difference (95% CI)</dt><dd>{interval(shrinkage.cv_loss_difference?.ci95)}</dd></div><div><dt>Retrospective test loss difference (95% CI)</dt><dd>{interval(audit.shrinkage_loss_difference?.ci95)}</dd></div></dl><p className="footnote">Negative differences favour shrinkage. Preserving classifications means this adjustment cannot reduce missed alerts. Training-fold intervals do not account for every model-development choice.</p></div>}
    {Array.isArray(audit.baseline_missed_event_ids) && <details className="raw"><summary>Inspect {audit.baseline_missed_event_ids.length} baseline missed alerts</summary><p className="small muted">Each link opens the historical encounter with its final risk label shown separately.</p><div className="event-links">{audit.baseline_missed_event_ids.map((id: string) => <a key={id} href={`?event=${encodeURIComponent(id)}#encounters`}>Encounter #{id}</a>)}</div></details>}
    {Array.isArray(audit.largest_baseline_errors) && <details className="raw"><summary>Largest baseline forecast errors</summary><div className="table-wrap"><table className="table compact"><thead><tr><th>Encounter</th><th className="num">Latest Pc</th><th className="num">Final reported Pc</th><th className="num">Absolute log₁₀ error</th></tr></thead><tbody>{audit.largest_baseline_errors.map((row: Json) => <tr key={row.event_id}><td><a href={`?event=${encodeURIComponent(row.event_id)}#encounters`}>#{row.event_id}</a></td><td className="num">{logProbability(row.latest_log10_pc)}</td><td className="num">{logProbability(row.final_log10_pc)}</td><td className="num">{fixed(row.absolute_log10_error, 3)}</td></tr>)}</tbody></table></div></details>}
  </section>;
}

function GuardEvidence({evaluation}: {evaluation: Json | undefined}) {
  if (!evaluation?.methods?.residual_guard) return null;
  const names: Record<string, string> = {latest_baseline: 'Latest-risk baseline', residual_guard: 'Baseline plus learned review', simple_threshold: 'Lower threshold only'};
  const nested = evaluation.policy?.nested_validation;
  return <section className="card section" aria-label="Additional review evaluation">
    <div className="section-head"><h2>Catching additional missed alerts</h2><p className="muted">An experimental learned rule retains every baseline alert and adds encounters for operator review. Its threshold is frozen using training validation, with a training false-alarm budget. It does not replace the default risk forecast or command a manoeuvre.</p></div>
    <div className="table-wrap"><table className="table"><thead><tr><th>Policy</th><th className="num">Recall</th><th className="num">Precision</th><th className="num">Missed alerts</th><th className="num">False alarms</th><th className="num">ESA loss</th></tr></thead><tbody>{Object.entries(evaluation.methods as Record<string, Json>).map(([name, row]) => <tr key={name}><td>{names[name] || name}</td><td className="num">{percent(row.recall)}</td><td className="num">{percent(row.precision)}</td><td className="num">{number(row.fn, 0)}</td><td className="num">{number(row.fp, 0)}</td><td className="num">{fixed(row.challenge_loss, 4)}</td></tr>)}</tbody></table></div>
    <p className="finding">The learned review rule catches {number(evaluation.additional_high_risk_events_detected, 0)} additional high-risk encounters in this retrospective test. Recall difference, paired 95% CI: {interval(evaluation.paired_bootstrap?.recall_difference_ci95, true)}. Loss difference, paired 95% CI: {interval(evaluation.paired_bootstrap?.loss_difference_ci95)}. An interval crossing zero does not establish a reliable loss improvement.</p>
    {nested && <p className="footnote">Nested development validation: baseline loss {fixed(nested.baseline?.challenge_loss, 4)}, learned review {fixed(nested.guard?.challenge_loss, 4)}, lower-threshold alternative {fixed(nested.simple_threshold?.challenge_loss, 4)}. Threshold selection is isolated inside outer event folds, but base-model hyperparameters come from earlier development. The training false-alarm budget is not a guarantee on future traffic. This public test set has been evaluated before.</p>}
    {Array.isArray(evaluation.additional_alert_event_ids) && <details className="raw"><summary>Inspect all {evaluation.additional_alert_event_ids.length} additional review alerts</summary><p className="small muted">Includes both correct escalations and false alarms. Final labels are shown separately in each historical encounter.</p><div className="event-links">{evaluation.additional_alert_event_ids.map((id: string) => <a key={id} href={`?event=${encodeURIComponent(id)}#encounters`}>Encounter #{id}</a>)}</div></details>}
  </section>;
}

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
    <Intro title="Validation" action={<div className="actions"><EvidenceDownload data={data}/><button className="btn small" disabled={loading} onClick={retry}><RefreshCw size={13} className={loading ? 'spin' : ''}/> Reload</button></div>}>
      Checks of the forecasting model, collision-probability maths and manoeuvre planner, plus measured speed. Every result is read from evaluation artifacts; the runtime section identifies the machine where timing was recorded. The header identifies the currently connected server.
    </Intro>
    <p className="page-note">Use this page to check a claim: each figure names where it was measured, and missing results are shown as unavailable.</p>
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
      {Array.isArray(boot) && <p className="finding"><strong>Point forecasts:</strong> learned loss minus baseline loss has a <Term k="ci">95% CI</Term> of {fixed(boot[0], 3)} to {fixed(boot[1], 3)}. {boot[0] > 0 ? 'This interval favours the baseline.' : boot[1] < 0 ? 'This interval favours the learned forecast.' : 'This interval crosses zero; an improvement is not established.'} The deployed method is {ml.model?.selected_method || 'not recorded'}; selection must use training validation rather than these test labels.</p>}
      {baselineRow && <div className="confusion"><h3>Baseline decisions at the high-risk threshold</h3><dl><div><dt>True positives</dt><dd>{number(baselineRow.tp, 0)}</dd></div><div><dt>False negatives (missed)</dt><dd>{number(baselineRow.fn, 0)}</dd></div><div><dt>False positives (false alarms)</dt><dd>{number(baselineRow.fp, 0)}</dd></div><div><dt>True negatives</dt><dd>{number(baselineRow.tn, 0)}</dd></div></dl><p className="small muted">Positive means final reported Pc ≥ 10⁻⁶. These are risk-label decisions, not observed collision outcomes.</p></div>}

      {rank && <div className="subsection">
        <h3>Ranking encounters for review</h3>
        <p className="muted">Analysts cannot inspect every alert at once, so the order matters. These raw, unclipped predictions assess review order separately from the challenge's clipped forecasts.</p>
        <div className="compare">
          <div><span className="figure-label">Latest reported value</span><strong>{fixed(rank.latest_average_precision, 3)}</strong><span className="small muted"><Term k="ap">Average precision</Term> · top 10% finds {percent(byName.latest_known_raw?.top_10_percent_recall)}</span></div>
          <div><span className="figure-label">Learned model</span><strong>{fixed(rank.learned_average_precision, 3)}</strong><span className="small muted"><Term k="ap">Average precision</Term> · top 10% finds {percent(byName.learned_residual_raw?.top_10_percent_recall)} <Tip text={G.top10}/></span></div>
          <div><span className="figure-label"><span>Learned minus latest (<Term k="ci">95% CI</Term>)</span></span><strong>{Array.isArray(rank.paired_bootstrap_ap_difference_ci95) ? `${fixed(rank.paired_bootstrap_ap_difference_ci95[0], 3)} to ${fixed(rank.paired_bootstrap_ap_difference_ci95[1], 3)}` : '—'}</strong><span className="small muted">{Array.isArray(rank.paired_bootstrap_ap_difference_ci95) ? rank.paired_bootstrap_ap_difference_ci95[0] > 0 ? 'Interval favours learned ranking' : rank.paired_bootstrap_ap_difference_ci95[1] < 0 ? 'Interval favours latest ranking' : 'Crosses zero: improvement not established' : 'Confidence interval unavailable'}</span></div>
        </div>
      </div>}
      {ml.ranking_curves && <div className="subsection-chart"><h3 className="subhead">Precision at every review depth <Tip text="Each point shows, if analysts reviewed encounters in the order a method ranks them until they had found a given share of high-risk encounters, what fraction of what they reviewed was truly high-risk. A curve that sits higher is a better ordering."/></h3><RankingCurve curves={ml.ranking_curves}/></div>}
      <TriageEvidence evaluation={ml.triage_evaluation}/>
    </section>

    <DecisionEvidence evaluation={ml.decision_evaluation}/>
    <AiEvidence/>
    <AccuracyAudit audit={ml.accuracy_audit}/>
    <GuardEvidence evaluation={ml.guard_evaluation}/>
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
      {bench?.policies && <p className="finding"><strong>Result:</strong> avoiding only the primary object created {number(bench.policies.pair_only?.secondary_hazards_introduced, 0)} new hazards; OrbitGuard created {number(bench.policies.orbitguard?.secondary_hazards_introduced, 0)}. Mean Δv was {fixed(bench.policies.pair_only?.mean_delta_v_mps, 4)} and {fixed(bench.policies.orbitguard?.mean_delta_v_mps, 4)} m/s respectively. {finite(bench.failed_scenarios) ? `${bench.failed_scenarios} scenarios failed to compute.` : 'Failed-scenario count unavailable.'}</p>}
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

    <PlatformEvidence/>
    <AuditPanel/>

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
