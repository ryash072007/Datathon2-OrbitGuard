import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Loader2, Send } from 'lucide-react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { finite, fixed, number, percent, post, request } from './api';
import type { Json } from './api';
import { Loading, Notice, Status, Tip, useAsync, useTokens } from './ui';

/* Everything on this page is read from artefacts via /api/ai-evidence. Nothing is typed in by hand. */

type Block = {status: 'ok' | 'missing', path: string | null, platform: string | null, data: Json | null, error?: string};

const CMD: Record<string, string> = {
  decision: 'orbitguard decision-eval', workload: 'orbitguard workload-eval', snapml: 'orbitguard zai-fit && orbitguard zai-eval',
  snapml_bench: 'orbitguard zai-bench', optimise: 'orbitguard optimise-burns synthetic --count 50 --budget 37', guard_eval: 'orbitguard guard-eval', nnpa_bench: 'orbitguard nnpa-bench',
};

function interval(ci: unknown, digits = 3): string {
  return Array.isArray(ci) && finite(ci[0]) && finite(ci[1]) ? `${fixed(ci[0], digits)} to ${fixed(ci[1], digits)}` : '—';
}
/** Plain verdict from a 95% interval on (method minus naive). `better` says which sign is good. */
function verdict(lo: unknown, hi: unknown, better: 'lower' | 'higher'): {text: string, tone: 'good' | 'bad' | 'neutral'} {
  if (!finite(lo) || !finite(hi)) return {text: 'No interval available', tone: 'neutral'};
  if (lo <= 0 && hi >= 0) return {text: 'Not significant: the interval includes 0, so no difference from the naive baseline is established', tone: 'neutral'};
  const good = better === 'lower' ? hi < 0 : lo > 0;
  return good ? {text: 'Significant improvement over the naive baseline (interval excludes 0)', tone: 'good'} : {text: 'Significantly worse than the naive baseline (interval excludes 0)', tone: 'bad'};
}
/** Tone for a difference interval where the null is 0; `lowerIsBetter` says which sign is good. */
function diffTone(ci: unknown, lowerIsBetter: boolean): string {
  if (!Array.isArray(ci) || !finite(ci[0]) || !finite(ci[1]) || (ci[0] <= 0 && ci[1] >= 0)) return 'muted';
  return (ci[1] < 0) === lowerIsBetter ? 'good-text' : 'bad-text';
}
const toneClass = (tone: string) => tone === 'good' ? 'good-text' : tone === 'bad' ? 'bad-text' : 'muted';
function score(x: unknown): number | undefined {
  if (finite(x)) return x;
  if (x && typeof x === 'object' && finite((x as Json).value)) return (x as Json).value;
  return undefined;
}

function EvCard({title, block, cmd, children}: {title: ReactNode, block?: Block, cmd: string, children?: ReactNode}) {
  const ok = block?.status === 'ok' && block.data;
  return <article className="ai-card">
    <h3>{title}</h3>
    {ok ? <>
      <p className="footnote ai-where">Measured on: {block!.platform || 'platform not recorded in the artefact'} · <code>{block!.path}</code></p>
      {children}
    </> : <p className="muted small">Missing: run <code>{cmd}</code>.{block?.path && <> Expected <code>{block.path}</code>.</>}{block?.error && <> ({block.error})</>}</p>}
  </article>;
}

/** Generic fallback: the evidence's own summary string plus a flat key/value table of its scalar fields. */
function flatten(obj: unknown, prefix = '', depth = 0, out: [string, string][] = []): [string, string][] {
  if (out.length >= 40 || obj == null) return out;
  if (Array.isArray(obj)) {
    if (obj.every(v => typeof v !== 'object')) out.push([prefix, obj.join(', ')]);
    return out;
  }
  if (typeof obj === 'object') {
    if (depth >= 3) return out;
    for (const [k, v] of Object.entries(obj as Json)) {
      if (k === 'per_scenario' || k === 'fingerprints' || k === 'notes' || k === 'limitations') continue;
      flatten(v, prefix ? `${prefix}.${k}` : k, depth + 1, out);
    }
    return out;
  }
  out.push([prefix, typeof obj === 'number' ? number(obj, 4) : String(obj)]);
  return out;
}
function Generic({data}: {data: Json}) {
  const summary = data.summary_text || data.one_line_summary || (typeof data.summary === 'string' ? data.summary : null);
  const rows = flatten(data);
  return <>
    {summary && <p className="finding">{summary}</p>}
    <details className="raw"><summary>All recorded fields ({rows.length})</summary>
      <div className="table-wrap"><table className="table compact"><tbody>{rows.map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{v}</td></tr>)}</tbody></table></div></details>
  </>;
}

// ---------------------------------------------------------------- (a) forecasting vs naive
function Forecasting({decision, snapml}: {decision?: Block, snapml?: Block}) {
  const L = decision?.data?.bootstrap?.metrics?.L;
  const lv = verdict(L?.ci95_lo, L?.ci95_hi, 'lower');
  const s = snapml?.data;
  const cmp = s?.paired_bootstrap_ap_difference?.vs_naive_latest_risk;
  const apV = cmp?.status === 'ready' ? verdict(cmp.ci95?.[0], cmp.ci95?.[1], 'higher') : null;
  return <EvCard title="Forecasting versus the naive baseline" block={decision} cmd={CMD.decision}>
    <p className="small muted">Naive baseline = the latest reported risk. {number(decision?.data?.test_events, 0)} held-out ESA test events. Each interval is a paired 95% bootstrap CI.</p>
    <dl className="kv">
      <div><dt>Decision layer, challenge loss L minus naive (lower is better)</dt><dd>{fixed(L?.point, 3)} <span className="muted">({interval([L?.ci95_lo, L?.ci95_hi])})</span></dd></div>
    </dl>
    <p className={`small ${toneClass(lv.tone)}`}>{lv.text}.</p>
    {snapml?.status === 'ok' && s ? <>
      <dl className="kv">
        <div><dt>Snap ML triage, average precision <Tip text="How well the method orders encounters from most to least risky. Higher is better."/></dt>
          <dd>{fixed(score(s.snapml_cpu?.average_precision), 3)} vs naive {fixed(score(s.naive_latest_risk?.average_precision), 3)}</dd></div>
        <div><dt>Difference (Snap ML minus naive)</dt><dd>{cmp?.status === 'ready' ? <>{fixed(cmp.point, 3)} <span className="muted">({interval(cmp.ci95)})</span></> : '—'}</dd></div>
      </dl>
      {apV && <p className={`small ${toneClass(apV.tone)}`}>{apV.text}.</p>}
      <p className="footnote">Snap ML measured on: {snapml.platform || 'not recorded'}</p>
    </> : <p className="muted small">Snap ML: missing, run <code>{CMD.snapml}</code>.</p>}
  </EvCard>;
}

// ---------------------------------------------------------------- (b) workload
const POLICY_LABEL: Record<string, string> = {
  'naive_latest_risk>=-6': 'Naive rule', 'decision_action==ACT': 'Decision layer: ACT', 'decision_action in (ACT,WAIT)': 'Decision layer: ACT or WAIT',
  'matched:triage_classifier': 'Triage, matched recall', 'matched:decision_p_high': 'P(high), matched recall',
  'budget:triage_classifier': 'Triage, same alert budget', 'budget:decision_p_high': 'P(high), same alert budget', 'matched:snapml': 'Snap ML, matched recall', 'budget:snapml': 'Snap ML, same alert budget',
};
function Workload({block}: {block?: Block}) {
  const t = useTokens();
  const d = block?.data || {};
  const pol: Json = d.policies || {}, boot: Json = d.paired_bootstrap_vs_naive || {};
  const keys = Object.keys(pol);
  const curves: Json = d.ranking_caught_at_budget || {};
  const names = Object.keys(curves);
  const ks = Array.from(new Set(names.flatMap(n => Object.keys(curves[n] || {})))).map(Number).sort((a, b) => a - b);
  const rows = ks.map(k => Object.fromEntries([['k', k], ...names.map(n => [n, curves[n]?.[k]])]));
  const colours = [t.s1, t.s2, t.s3, t.s4];
  return <EvCard title="Operator workload at an equal alert budget" block={block} cmd={CMD.workload}>
    {d.summary && <p className="finding">{d.summary}</p>}
    {keys.length > 0 && <div className="table-wrap"><table className="table compact">
      <thead><tr><th>Policy</th><th className="num">Alerts</th><th className="num">Caught (95% CI vs naive)</th><th className="num">False alerts (95% CI vs naive)</th></tr></thead>
      <tbody>{keys.map(k => {const b = boot[k]; return <tr key={k}><td>{POLICY_LABEL[k] || k}</td><td className="num">{number(pol[k].alerts, 0)}</td>
        <td className="num">{number(pol[k].caught, 0)}{b && <div className={`small ${diffTone(b.caught_difference?.ci95, false)}`}>{finite(b.caught_difference?.point) ? `${b.caught_difference.point > 0 ? '+' : ''}${number(b.caught_difference.point, 0)}, ` : ''}{interval(b.caught_difference?.ci95, 0)}</div>}</td>
        <td className="num">{number(pol[k].false_alerts, 0)}{b && <div className={`small ${diffTone(b.false_alerts_difference?.ci95, true)}`}>{finite(b.false_alerts_difference?.point) ? `${b.false_alerts_difference.point > 0 ? '+' : ''}${number(b.false_alerts_difference.point, 0)}, ` : ''}{interval(b.false_alerts_difference?.ci95, 0)}</div>}</td></tr>;})}</tbody>
    </table></div>}
    {rows.length > 1 && <div>
      <p className="small muted">High-risk events caught when reviewing only the top K alerts by each score ({number(d.n_high_risk_test_for_ranking, 0)} high-risk in total).</p>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={rows} margin={{top: 6, right: 12, bottom: 0, left: 0}}>
          <CartesianGrid stroke={t.grid} strokeDasharray="3 3"/>
          <XAxis dataKey="k" type="number" domain={['dataMin', 'dataMax']} stroke={t.axis} tick={{fill: t.muted, fontSize: 11}} label={{value: 'alerts reviewed (K)', position: 'insideBottom', offset: -2, fill: t.muted, fontSize: 11}}/>
          <YAxis stroke={t.axis} tick={{fill: t.muted, fontSize: 11}} width={36}/>
          <Tooltip contentStyle={{background: t.surface, border: `1px solid ${t.grid}`, fontSize: 12}}/>
          <Legend wrapperStyle={{fontSize: 11}}/>
          {names.map((n, i) => <Line key={n} type="monotone" dataKey={n} name={n.replace(/_/g, ' ')} stroke={colours[i % colours.length]} strokeWidth={2} dot={{r: 2}} isAnimationActive={false}/>)}
        </LineChart>
      </ResponsiveContainer>
    </div>}
    <p className="footnote">Green or red differences have an interval that excludes 0, so they are real; grey ones include 0, so no difference is established.</p>
    <p className="footnote">ESA test events over-represent high-risk cases, so these counts do not estimate operational volumes.</p>
  </EvCard>;
}

// ---------------------------------------------------------------- (c) Snap ML on Telum
function Telum({bench, snapml, nnpa}: {bench?: Block, snapml?: Block, nnpa?: Block}) {
  const d = bench?.data || {};
  const table: Json[] = Array.isArray(d.table) ? d.table : [];
  const diffs = table.map(r => r.max_abs_diff).filter(finite);
  const zEv = snapml?.data?.snapml_zdnn;
  const maxDiff = diffs.length ? Math.max(...diffs) : zEv?.max_abs_diff_vs_cpu;
  const engaged = d.nnpa_available;
  return <EvCard title="IBM Snap ML on Telum" block={bench} cmd={CMD.snapml_bench}>
    {d.status && d.status !== 'ready' && <p className="small bad-text">Not measured on this machine{d.reason ? `: ${d.reason}` : ''}. No Telum speedup is claimed.</p>}
    <p className="small">zDNN engaged: {engaged === true ? <Status ok>Yes</Status> : engaged === false ? <Status ok={false}>No{d.nnpa_unavailable_reason ? `: ${d.nnpa_unavailable_reason}` : ''}</Status> : <span className="muted">not measured</span>}
      {d.status && d.status !== 'ready' && <span className="muted"> · benchmark status: {d.status}</span>}</p>
    {table.length > 0 && <div className="table-wrap"><table className="table compact">
      <thead><tr><th className="num">Rows</th><th className="num">CPU rows/s</th><th className="num">zDNN rows/s</th><th className="num">Speedup</th></tr></thead>
      <tbody>{table.map(r => <tr key={r.rows}><td className="num">{number(r.rows, 0)}</td><td className="num">{number(r.cpu_rows_per_s, 0)}</td><td className="num">{finite(r.nnpa_rows_per_s) ? number(r.nnpa_rows_per_s, 0) : r.nnpa_status || '—'}</td><td className="num">{finite(r.speedup) ? `${fixed(r.speedup, 2)}×` : '—'}</td></tr>)}</tbody>
    </table></div>}
    <p className="small muted">Largest probability difference, CPU versus zDNN: {finite(maxDiff) ? maxDiff.toExponential(2) : '—'}. A speedup below 1× means the accelerator was slower for that size; it is reported as measured.</p>
    {nnpa?.status === 'ok' && Array.isArray(nnpa.data?.table) && nnpa.data.table.length > 0 && <details className="raw"><summary>TensorFlow MLP on NNPA ({nnpa.platform || 'platform not recorded'}; engaged: {String(nnpa.data.nnpa_available)})</summary>
      <div className="table-wrap"><table className="table compact"><thead><tr><th className="num">Rows</th><th className="num">CPU rows/s</th><th className="num">NNPA rows/s</th><th className="num">Speedup</th></tr></thead>
        <tbody>{nnpa.data.table.map((r: Json) => <tr key={r.rows}><td className="num">{number(r.rows, 0)}</td><td className="num">{number(r.cpu_rows_per_s, 0)}</td><td className="num">{number(r.nnpa_rows_per_s, 0)}</td><td className="num">{fixed(r.speedup, 2)}×</td></tr>)}</tbody></table></div></details>}
  </EvCard>;
}

// ---------------------------------------------------------------- (d) learned burn search
function ratioTone(lo: unknown, hi: unknown): string {
  if (!finite(lo) || !finite(hi) || (lo <= 1 && hi >= 1)) return 'muted';
  return hi < 1 ? 'good-text' : 'bad-text';
}
function ratioWord(lo: unknown, hi: unknown): string {
  if (!finite(lo) || !finite(hi)) return '';
  return lo <= 1 && hi >= 1 ? ' · same as grid' : hi < 1 ? ' · cheaper' : ' · costlier';
}
const METHOD: Record<string, string> = {grid: 'Grid (reference)', bo: 'Learned search (Bayesian)', bo_warm: 'Learned search, seeded with grid', random: 'Random', random_log: 'Random (log-spaced)', random_warm: 'Random, seeded with grid', fine_grid: 'Finer grid'};
function Burn({block}: {block?: Block}) {
  const d = block?.data || {};
  const s: Json = d.summary && typeof d.summary === 'object' ? d.summary : {};
  const methods = Object.keys(s).filter(k => s[k] && typeof s[k] === 'object');
  const specific = methods.length > 0 && s[methods[0]].dv_ratio_vs_grid;
  const missed = methods.reduce((n, m) => n + (Array.isArray(s[m].grid_finds_method_abstains) ? s[m].grid_finds_method_abstains.length : 0), 0);
  const extra = methods.reduce((n, m) => n + (Array.isArray(s[m].grid_abstains_method_finds) ? s[m].grid_abstains_method_finds.length : 0), 0);
  return <EvCard title="Learned burn search" block={block} cmd={CMD.optimise}>
    {specific ? <>
      <p className="small muted">{number(d.scenarios, 0)} scenarios, {number(d.budget_evaluations, 0)} evaluations per method. Δv ratio is the method's Δv divided by the grid's, so below 1 means a cheaper burn (median, 95% CI). The null is 1: an interval that includes 1 means no difference from the grid.</p>
      <div className="table-wrap"><table className="table compact">
        <thead><tr><th>Method</th><th className="num">Δv ratio vs grid</th><th className="num">Better / tied / worse</th><th className="num">Found</th></tr></thead>
        <tbody>{methods.map(m => {const r = s[m].dv_ratio_vs_grid?.median_ci95 || {}; return <tr key={m}><td>{METHOD[m] || m}</td>
          <td className="num">{fixed(r.median ?? s[m].dv_ratio_vs_grid?.mean, 3)}<div className={`small ${ratioTone(r.lo, r.hi)}`}>{interval([r.lo, r.hi])}{ratioWord(r.lo, r.hi)}</div></td>
          <td className="num">{s[m].wins_vs_grid} / {s[m].ties_vs_grid} / {s[m].losses_vs_grid}</td><td className="num">{s[m].feasible_found}{finite(d.scenarios) ? ` / ${number(d.scenarios, 0)}` : ''}</td></tr>;})}</tbody>
      </table></div>
      <p className="small">Abstention: {d.designed_impossible_all_abstain === true ? <Status ok>Every method declined all designed-impossible scenarios</Status> : d.designed_impossible_all_abstain === false ? <Status ok={false}>Some method proposed a burn where none exists</Status> : '—'}
        <span className="muted"> · grid and learned search disagree on whether a burn exists in {number(missed + extra, 0)} case(s).</span></p>
      {d.one_line_summary && <p className="footnote">{d.one_line_summary}</p>}
    </> : <Generic data={d}/>}
  </EvCard>;
}

// ---------------------------------------------------------------- (e) guard evaluation
type Rate = {k?: number, n?: number, rate?: number, wilson95?: unknown};
const isRate = (v: unknown): v is Rate => !!v && typeof v === 'object' && finite((v as Json).rate);
const GUARD_METHOD: Record<string, string> = {numeric_guard: 'Numeric check', guardian: 'Granite Guardian', combined: 'Both together'};
const label = (k: string) => k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
const pct = (x: unknown) => finite(x) ? `${(x * 100).toFixed(0)}%` : '—';
function RateCell({r}: {r?: Rate}) {
  if (!isRate(r)) return <td className="num muted">—</td>;
  return <td className="num">{pct(r.rate)}<div className="small muted">{finite(r.k) && finite(r.n) ? `${r.k} of ${r.n}` : ''}{Array.isArray(r.wilson95) ? ` (${pct(r.wilson95[0])} to ${pct(r.wilson95[1])})` : ''}</div></td>;
}
/** Renders whatever rows exist: results is {check: {category: {k, n, rate, wilson95}}}; columns come from the data. */
function GuardEval({block}: {block?: Block}) {
  const d = block?.data || {};
  const res: Json = d.results && typeof d.results === 'object' && !Array.isArray(d.results) ? d.results : {};
  const methods = Object.keys(res).filter(m => res[m] && typeof res[m] === 'object');
  const cats = Array.from(new Set(methods.flatMap(m => Object.keys(res[m]).filter(c => isRate(res[m][c])))));
  const types = Array.from(new Set(methods.flatMap(m => Object.keys(res[m]?.by_type || {}))));
  const lat = d.guardian?.latency_ms;
  return <EvCard title="Guard evaluation" block={block} cmd={CMD.guard_eval}>
    <p className="small muted">How often the checks on the written brief catch a deliberately corrupted brief, and how often they wrongly flag a correct one. Caught: higher is better. False flags: lower is better. Corruptions are synthetic edits of template briefs, so rates describe this test set only; intervals are 95% Wilson.</p>
    {d.summary && <p className="finding">{d.summary}</p>}
    {methods.length > 0 && cats.length > 0 ? <>
      <div className="table-wrap"><table className="table compact">
        <thead><tr><th>Check</th>{cats.map(c => <th key={c} className="num">{c.startsWith('false') ? `${label(c)} (lower is better)` : `Caught: ${label(c)}`}</th>)}</tr></thead>
        <tbody>{methods.map(m => <tr key={m}><td>{GUARD_METHOD[m] || label(m)}</td>{cats.map(c => <RateCell key={c} r={res[m][c]}/>)}</tr>)}</tbody>
      </table></div>
      {types.length > 0 && <details className="raw"><summary>Detection by corruption type</summary>
        <div className="table-wrap"><table className="table compact">
          <thead><tr><th>Check</th>{types.map(t => <th key={t} className="num">{label(t)}</th>)}</tr></thead>
          <tbody>{methods.map(m => <tr key={m}><td>{GUARD_METHOD[m] || label(m)}</td>{types.map(t => <RateCell key={t} r={res[m]?.by_type?.[t]}/>)}</tr>)}</tbody>
        </table></div></details>}
      {finite(lat?.p50) && finite(lat?.p95) && <p className="footnote">Guardian latency per brief: median {number(lat.p50 / 1000, 1)} s, 95th percentile {number(lat.p95 / 1000, 1)} s ({d.guardian?.model_file || 'model not recorded'}).</p>}
      {Array.isArray(d.notes) && d.notes.length > 0 && <details className="raw"><summary>Notes</summary><ul className="small muted">{d.notes.map((n: unknown, i: number) => <li key={i}>{String(n)}</li>)}</ul></details>}
    </> : block?.data && <Generic data={d}/>}
  </EvCard>;
}

export function AiEvidence() {
  const { data, loading, error, retry } = useAsync<Json>('/ai-evidence');
  const b = (k: string) => data?.[k] as Block | undefined;
  return <section className="card section" aria-label="Where the AI helps, and where it doesn't">
    <div className="section-head"><h2>Where the AI helps, and where it doesn't</h2>
      <p className="muted">Each card reads a measured artefact and names the machine it was measured on. Where an interval includes zero, the result is reported as not significant.</p></div>
    {error && <Notice retry={retry}>{error}</Notice>}
    {loading ? <Loading label="Loading AI evidence"/> : data && <div className="ai-grid">
      <Forecasting decision={b('decision')} snapml={b('snapml')}/>
      <Workload block={b('workload')}/>
      <Telum bench={b('snapml_bench')} snapml={b('snapml')} nnpa={b('nnpa_bench')}/>
      <Burn block={b('optimise')}/>
      <GuardEval block={b('guard_eval')}/>
    </div>}
  </section>;
}

// ---------------------------------------------------------------- Ask OrbitGuard
const SUGGESTIONS = ['What if I burn one orbit later?', 'Why not the pair-only burn?', 'How many satellites would the debris threaten?'];

export function AskOrbitGuard({norad}: {norad: number}) {
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [answer, setAnswer] = useState<Json | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [notice, setNotice] = useState('');
  const alive = useRef(true);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  async function ask(q: string, refresh = false) {
    if (!q.trim() || busy) return;
    setBusy(true); setError(''); setNotice(''); setElapsed(0);
    const t0 = Date.now();
    const tick = window.setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try {
      let r = await post('/live/ask', {question: q.trim(), norad, refresh});
      const poll = `/live/ask?norad=${norad}&question=${encodeURIComponent(q.trim())}`;
      while (alive.current && r.status === 'running') {
        await new Promise(res => window.setTimeout(res, 2000));
        r = await request(poll);
      }
      if (!alive.current) return;
      if (r.status === 'busy') setNotice(r.message || 'Granite is busy with another job. Try again shortly.');
      else if (r.status === 'error') setError(r.error || 'The question failed.');
      else if (r.status === 'done') setAnswer(r);
      else setError(r.message || 'No answer was produced.');
    } catch (e) {setError((e as Error).message);} finally {window.clearInterval(tick); setBusy(false);}
  }
  const g = answer?.guardian || {};
  return <section className="card section" aria-label="Ask OrbitGuard">
    <div className="card-head"><div><h2>Ask OrbitGuard</h2>
      <p className="muted small">Questions about the analysis for NORAD {norad}. Granite picks read-only tools, and the answer only narrates what those tools computed. It cannot change the recommendation.</p></div></div>
    <form className="ask-form" onSubmit={e => {e.preventDefault(); ask(question);}}>
      <input className="search" value={question} maxLength={500} onChange={e => setQuestion(e.target.value)} placeholder="Ask about this encounter" aria-label="Question"/>
      <button className="btn primary" disabled={busy || !question.trim()}>{busy ? <Loader2 size={14} className="spin"/> : <Send size={14}/>} Ask</button>
    </form>
    <div className="chips">{SUGGESTIONS.map(s => <button key={s} className="btn small" disabled={busy} onClick={() => {setQuestion(s); ask(s);}}>{s}</button>)}</div>
    {busy && <p className="small muted" aria-live="polite"><Loader2 size={12} className="spin"/> Granite is thinking on LinuxONE… {elapsed}s</p>}
    {notice && <Notice>{notice}</Notice>}
    {error && <Notice>{error}</Notice>}
    {answer && <div className="ask-answer" aria-live="polite">
      <p>{answer.answer}</p>
      <div className="badges">
        <span className="tag">{answer.backend}</span>
        <Status ok={Boolean(answer.grounded)}>{answer.grounded ? 'Numbers grounded' : 'Not grounded'}</Status>
        <span className="tag" title={g.model || ''}>Guardian: {g.status === 'ok' ? (g.flagged ? 'flagged' : 'passed') : g.status || 'n/a'}</span>
        {answer.cached && <span className="tag">cached · generated {answer.generated_utc ? String(answer.generated_utc).replace('T', ' ').replace('Z', ' UTC') : 'earlier'}</span>}
        {finite(answer.latency_ms) && <span className="small muted">{number(answer.latency_ms / 1000, 1)} s</span>}
        {answer.cached && <button className="btn small" disabled={busy} onClick={() => ask(String(answer.question || question), true)}>Recompute</button>}
      </div>
      {answer.fallback_reason && <p className="footnote">Fell back to the template answer: {answer.fallback_reason}</p>}
      {Array.isArray(answer.tool_calls) && answer.tool_calls.length > 0 && <div className="chips" aria-label="Tools used">
        {answer.tool_calls.map((c: Json, i: number) => <span key={i} className="tag" title={c.result_summary ? String(c.result_summary) : undefined}>{c.tool}{c.args && Object.keys(c.args).length ? `(${Object.entries(c.args).map(([k, v]) => `${k}=${v}`).join(', ')})` : ''}</span>)}
      </div>}
    </div>}
  </section>;
}

export function SecondOpinion({decision}: {decision?: Json}) {
  const so = decision?.second_opinion;
  if (!so) return null;
  if (so.status === 'unavailable') return <p className="footnote">Snap ML second opinion unavailable: {so.message}</p>;
  return <p className="small second-opinion">Snap ML second opinion: P(high) {percent(so.p_high)} · {so.backend} · {number(so.latency_ms, 1)} ms · {so.agrees === true ? 'agrees with the decision layer' : so.agrees === false ? 'disagrees with the decision layer, review manually' : 'agreement not assessed'}. It never changes the action.</p>;
}
