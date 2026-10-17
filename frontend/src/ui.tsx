import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, CircleHelp, Loader2, RefreshCw, X } from 'lucide-react';
import { request } from './api';

/** Plain-language definitions shown in tooltips wherever a term appears. */
export const G = {
  pc: 'Collision probability (Pc): the estimated chance that the two objects actually collide during this pass, given how uncertain their positions are.',
  cdm: 'Conjunction data message (CDM): an alert issued when two objects are predicted to pass close to each other. Each new message refines the estimate.',
  tca: 'Time of closest approach (TCA): the moment the two objects are predicted to be nearest each other.',
  threshold: 'ESA counts an encounter as high-risk when its final Pc is at least 10⁻⁶ (one in a million).',
  latest: 'The most recent Pc available 48 hours before closest approach. This is ESA\'s standard baseline, and our default forecast because it scored best in cross-validation.',
  learned: 'A gradient-boosted model trained on 8,293 past encounters that adjusts the latest value using the message history. It is less accurate as a point estimate but better at ranking which encounters to review first (see Validation).',
  final: 'The Pc that ESA reported in the last day before closest approach. The models never see it; it is shown only so you can compare.',
  dv: 'Velocity change of the burn in metres per second. It stands in for fuel: a smaller Δv uses less propellant. Positive means a prograde burn (speeding up along the direction of travel), negative means retrograde.',
  limit: 'A plan is acceptable only if every encounter with every object stays below Pc 10⁻⁴ (one in ten thousand), at all three uncertainty levels tested.',
  uncertainty: 'Object positions are uncertain, so each Pc is recomputed with the assumed position error halved, as given, and doubled. The worst of the three is reported.',
  verify: 'After choosing, the plan is re-propagated with a finer time step and tighter tolerances to confirm the result does not depend on numerical settings.',
  geometry: 'Positions near the moment of closest approach, measured relative to where satellite A would be without a burn. Horizontal is along-track (direction of travel), vertical is cross-track. Object sizes are not to scale.',
  loss: 'ESA\'s challenge score: the forecast error on high-risk encounters divided by F2. Lower is better.',
  f2: 'Combines precision and recall but weights recall twice as heavily, because missing a dangerous encounter is worse than a false alarm. Higher is better.',
  recall: 'Share of the truly high-risk encounters that the method flagged.',
  precision: 'Share of the flagged encounters that were truly high-risk.',
  fn: 'High-risk encounters the method failed to flag.',
  fp: 'Encounters flagged as high-risk that were not.',
  ap: 'Average precision: how well a method orders encounters from most to least risky, so analysts see the dangerous ones first. 1.0 is a perfect ordering.',
  top10: 'Share of all high-risk encounters found by reviewing only the top 10% of the ranked list.',
  ci: '95% confidence interval from 1,000 bootstrap resamples of the test encounters. If it does not include zero, the difference is unlikely to be due to chance.',
  p95: '95th-percentile time: 95% of runs finished at least this fast.',
};

export const POLICIES: {id: string, label: string, short: string}[] = [
  {id: 'no_action', label: 'No manoeuvre', short: 'Keep the current orbit'},
  {id: 'pair_only', label: 'Avoid primary object only', short: 'Cheapest burn that clears the original encounter'},
  {id: 'orbitguard', label: 'OrbitGuard', short: 'Cheapest burn that clears every nearby object'},
];

export function Tip({text, children}: {text: ReactNode, children?: ReactNode}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{x: number, y: number, below: boolean} | null>(null);
  function show() {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const below = r.top < 140;
    setPos({x: Math.min(Math.max(r.left + r.width / 2, 150), window.innerWidth - 150), y: below ? r.bottom + 8 : r.top - 8, below});
  }
  useEffect(() => {
    if (!pos) return;
    const hide = () => setPos(null);
    window.addEventListener('scroll', hide, true);
    return () => window.removeEventListener('scroll', hide, true);
  }, [pos]);
  return <span ref={ref} className="tip-anchor" tabIndex={0} onMouseEnter={show} onMouseLeave={() => setPos(null)} onFocus={show} onBlur={() => setPos(null)} aria-label={typeof text === 'string' ? text : undefined}>
    {children ?? <CircleHelp size={13} aria-hidden="true"/>}
    {pos && <span role="tooltip" className={`tip ${pos.below ? 'below' : ''}`} style={{left: pos.x, top: pos.y}}>{text}</span>}
  </span>;
}
/** An inline term with a dotted underline that explains itself on hover or focus. */
export function Term({k, children}: {k: keyof typeof G, children: ReactNode}) {return <Tip text={G[k]}><span className="term">{children}</span></Tip>;}
export function Loading({label}: {label: string}) {return <div className="placeholder"><Loader2 className="spin" size={18}/><span>{label}</span></div>;}
export function Empty({title, children}: {title: string, children?: ReactNode}) {return <div className="placeholder empty"><strong>{title}</strong>{children && <p>{children}</p>}</div>;}
export function Notice({children, retry}: {children: ReactNode, retry?: () => void}) {return <div className="notice" role="alert"><span>{children}</span>{retry && <button className="btn small" onClick={retry}><RefreshCw size={13}/> Retry</button>}</div>;}
export function Status({ok, children}: {ok: boolean, children?: ReactNode}) {return <span className={`status ${ok ? 'ok' : 'bad'}`}>{ok ? <Check size={14} aria-hidden="true"/> : <X size={14} aria-hidden="true"/>}{children ?? (ok ? 'Accepted' : 'Rejected')}</span>;}
export function useAsync<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true); setError('');
    request<T>(path).then(v => {if (alive) setData(v);}).catch(e => {if (alive) setError(e.message);}).finally(() => {if (alive) setLoading(false);});
    return () => {alive = false;};
  }, [path, reload, ...deps]);
  return {data, loading, error, retry: () => setReload(v => v + 1)};
}
/** Chart colours come from CSS tokens so light and dark themes stay in one place. */
export function useTokens() {
  const read = () => {
    const style = getComputedStyle(document.documentElement);
    const get = (name: string) => style.getPropertyValue(name).trim();
    return {s1: get('--series-1'), s2: get('--series-2'), s3: get('--series-3'), s4: get('--series-4'), text: get('--text'), muted: get('--text-muted'), faint: get('--text-faint'), grid: get('--grid'), axis: get('--axis'), surface: get('--surface'), good: get('--st-good'), bad: get('--st-bad'), neutral: get('--st-neutral')};
  };
  const [tokens, setTokens] = useState(read);
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const update = () => setTokens(read());
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return tokens;
}

