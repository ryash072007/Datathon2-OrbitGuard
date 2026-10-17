import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, ChevronRight, CircleHelp, Loader2, RefreshCw, X } from 'lucide-react';
import { request } from './api';

/** Plain-language definitions shown in tooltips wherever a term appears. */
export const G = {
  pc: 'Collision probability (Pc): the estimated chance that the two objects actually collide during this pass, given how uncertain their positions are.',
  cdm: 'Conjunction data message (CDM): an alert issued when two objects are predicted to pass close to each other. Each new message refines the estimate.',
  tca: 'Time of closest approach (TCA): the moment the two objects are predicted to be nearest each other.',
  threshold: 'ESA counts an encounter as high-risk when its final Pc is at least 10⁻⁶ (one in a million).',
  latest: 'The most recent Pc available 48 hours before closest approach. This is ESA\'s standard baseline. Validation shows how it compares with the learned model.',
  learned: 'A model trained on historical ESA encounters that adjusts the latest value using the message history. Compare its point forecasts and review ranking separately in Validation.',
  final: 'The Pc that ESA reported in the last day before closest approach. The models never see it; it is shown only so you can compare.',
  dv: 'Velocity change of the burn in metres per second. It stands in for fuel: a smaller Δv uses less propellant. Positive means a prograde burn (speeding up along the direction of travel), negative means retrograde.',
  limit: 'A plan is acceptable only if every encounter with every object stays below Pc 10⁻⁴ (one in ten thousand), at all three uncertainty levels tested.',
  uncertainty: 'Object positions are uncertain, so each Pc is recomputed with the assumed position error halved, as given, and doubled. The worst of the three is reported.',
  verify: 'After choosing, the plan is re-propagated with a finer time step and tighter tolerances to confirm the result does not depend on numerical settings.',
  geometry: 'Positions near the moment of closest approach, measured relative to where satellite A would be without a burn. Horizontal is along-track (direction of travel), vertical is cross-track. Object sizes are not to scale.',
  loss: 'ESA\'s challenge score: the forecast error on high-risk encounters divided by F2. Lower is better.',
  f2: 'F2 = 5 × precision × recall / (4 × precision + recall). The recall weight is four times the precision weight. Higher is better.',
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
export function Loading({label}: {label: string}) {return <div className="placeholder" role="status"><Loader2 className="spin" size={18}/><span>{label}</span></div>;}
export function Empty({title, children}: {title: string, children?: ReactNode}) {return <div className="placeholder empty"><strong>{title}</strong>{children && <p>{children}</p>}</div>;}
export function Notice({children, retry}: {children: ReactNode, retry?: () => void}) {return <div className="notice" role="alert"><span>{children}</span>{retry && <button className="btn small" onClick={retry}><RefreshCw size={13}/> Retry</button>}</div>;}
export function Status({ok, children}: {ok: boolean, children?: ReactNode}) {return <span className={`status ${ok ? 'ok' : 'bad'}`}>{ok ? <Check size={14} aria-hidden="true"/> : <X size={14} aria-hidden="true"/>}{children ?? (ok ? 'Accepted' : 'Rejected')}</span>;}
export function useAsync<T>(path: string | null, deps: unknown[] = []) {
  const [state, setState] = useState<{path: string | null, data: T | null, loading: boolean, error: string}>({path, data: null, loading: Boolean(path), error: ''});
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!path) {setState({path, data: null, loading: false, error: ''}); return;}
    let alive = true;
    setState({path, data: null, loading: true, error: ''});
    request<T>(path).then(data => {if (alive) setState({path, data, loading: false, error: ''});}).catch(error => {if (alive) setState({path, data: null, loading: false, error: error.message});});
    return () => {alive = false;};
  }, [path, reload, ...deps]);
  const current = state.path === path;
  return {data: current ? state.data : null, loading: Boolean(path) && (!current || state.loading), error: current ? state.error : '', retry: () => setReload(v => v + 1)};
}
export type ThemeName = 'dark' | 'light';
/** The console defaults to the dark space theme; the choice is kept in localStorage. */
export function readTheme(): ThemeName {
  try {return localStorage.getItem('og-theme') === 'light' ? 'light' : 'dark';} catch {return 'dark';}
}
export function applyTheme(theme: ThemeName) {
  document.documentElement.dataset.theme = theme;
  try {localStorage.setItem('og-theme', theme);} catch {/* storage unavailable (private mode): the choice lasts for this page only */}
  window.dispatchEvent(new Event('og-theme'));
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
    window.addEventListener('og-theme', update);
    return () => {media.removeEventListener('change', update); window.removeEventListener('og-theme', update);};
  }, []);
  return tokens;
}

/** A probability in everyday words, e.g. "about 1 in 780". Empty when the value is not a usable probability. */
export function plainOdds(p: number | null | undefined): string {
  if (typeof p !== 'number' || !Number.isFinite(p) || p <= 0) return '';
  if (p >= 0.5) return 'about 1 in 2 or higher';
  const n = Number((1 / p).toPrecision(2));
  const trim = (value: number) => String(Number(value.toPrecision(2)));
  if (n >= 1e12) return 'less than 1 in a trillion';
  if (n >= 1e9) return `about 1 in ${trim(n / 1e9)} billion`;
  if (n >= 1e6) return `about 1 in ${trim(n / 1e6)} million`;
  return `about 1 in ${n.toLocaleString('en-US')}`;
}
/** Muted plain-words line under a probability figure. Renders nothing when the probability is unusable. */
export function Odds({p}: {p: number | null | undefined}) {
  const text = plainOdds(p);
  return text ? <span className="odds">{text}</span> : null;
}

function readFlag(key: string): boolean {
  try {return localStorage.getItem(key) === '1';} catch {return false;}
}
function writeFlag(key: string, on: boolean) {
  try {localStorage.setItem(key, on ? '1' : '0');} catch {/* storage unavailable: the choice lasts for this page only */}
}
/** Ask a Disclosure with this storage key to open (used by the section bar). */
export function openDisclosure(storageKey: string) {window.dispatchEvent(new CustomEvent('og-open-details', {detail: storageKey}));}
/** A native details disclosure, closed by default, that remembers whether it was opened. */
export function Disclosure({storageKey, summary, children, className = '', id}: {storageKey: string, summary: ReactNode, children: ReactNode, className?: string, id?: string}) {
  const [open, setOpen] = useState(() => readFlag(storageKey));
  useEffect(() => {
    const handler = (event: Event) => {if ((event as CustomEvent).detail === storageKey) {setOpen(true); writeFlag(storageKey, true);}};
    window.addEventListener('og-open-details', handler);
    return () => window.removeEventListener('og-open-details', handler);
  }, [storageKey]);
  return <details id={id} className={`disclosure ${className}`} open={open} onToggle={e => {const now = e.currentTarget.open; if (now !== open) {setOpen(now); writeFlag(storageKey, now);}}}>
    <summary><ChevronRight size={15} aria-hidden="true"/>{summary}</summary>
    <div className="disclosure-body">{children}</div>
  </details>;
}

export type NavItem = {id: string, label: string, opens?: string};
/** Sticky in-page section bar: highlights the section in view and scrolls to the others. */
export function SectionNav({items, label = 'On this page'}: {items: NavItem[], label?: string}) {
  const [picked, setActive] = useState('');
  const key = items.map(i => i.id).join('|');
  const active = items.some(i => i.id === picked) ? picked : items[0]?.id;
  useEffect(() => {
    const ids = key.split('|');
    const inBand = new Set<string>();
    const header = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h')) || 96;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {if (entry.isIntersecting) inBand.add(entry.target.id); else inBand.delete(entry.target.id);}
      const current = [...ids].reverse().find(id => inBand.has(id));
      if (current) setActive(current);
    }, {rootMargin: `-${Math.round(header + 56)}px 0px -55% 0px`});
    ids.forEach(id => {const el = document.getElementById(id); if (el) observer.observe(el);});
    return () => observer.disconnect();
  }, [key]);
  function jump(item: NavItem) {
    if (item.opens) openDisclosure(item.opens);
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.setTimeout(() => document.getElementById(item.id)?.scrollIntoView({behavior: reduce ? 'auto' : 'smooth', block: 'start'}), item.opens ? 30 : 0);
    setActive(item.id);
  }
  return <nav className="sectionnav" aria-label={label}>
    <ul>{items.map(item => <li key={item.id}><button className={active === item.id ? 'active' : ''} aria-current={active === item.id ? 'location' : undefined} onClick={() => jump(item)}>{item.label}</button></li>)}</ul>
  </nav>;
}
