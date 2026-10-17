import { useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';

const TERMS: [string, string][] = [
  ['Conjunction', 'A predicted close approach between two objects in orbit.'],
  ['CDM (conjunction data message)', 'A warning issued for a conjunction. Updated messages arrive as tracking improves, so the risk estimate changes over time.'],
  ['TCA (time of closest approach)', 'The moment the two objects are predicted to be nearest each other.'],
  ['Pc (collision probability)', 'The chance the two objects actually collide, given the uncertainty in where each one is.'],
  ['High-risk', 'In the ESA data, an encounter whose final reported collision probability is at least 1 in a million (10⁻⁶).'],
  ['Act / Wait / Monitor', 'OrbitGuard\'s call on a warning. Act: prepare an avoidance manoeuvre. Wait: risk is elevated but a later message should settle it. Monitor: no action needed now.'],
  ['Burn', 'A short firing of the satellite\'s thrusters that slightly changes its orbit.'],
  ['Δv (delta-v)', 'The change in speed a burn gives the satellite, in metres per second. Smaller means less fuel.'],
  ['Position uncertainty (σ)', 'How far an object\'s true position might be from its tracked position. OrbitGuard checks each burn at several uncertainty levels.'],
  ['Pair-only avoidance', 'Choosing a burn that only considers the one object in the warning. It can steer into a different object.'],
  ['All-object screening', 'OrbitGuard\'s rule: a burn is accepted only if it keeps the risk below the limit for every nearby object.'],
  ['Decline (abstain)', 'When no candidate burn meets the limits, OrbitGuard says so instead of recommending an unsafe one.'],
  ['Debris exposure', 'An estimate of how much debris a collision would create, and which other satellites it would put at risk.'],
  ['Granite brief', 'A plain-language summary written by IBM Granite running on the server. Its numbers and claims are checked against the computed facts, and a fixed template is used if a check fails.'],
  ['Audit log', 'A hash-chained record of forecasts, screenings, briefs and operator decisions. Changing any past entry breaks the chain.'],
  ['IBM LinuxONE', 'The IBM Z server this console runs on (s390x). Forecasts, screening and the AI brief all run there.'],
  ['NNPA / Telum', 'The AI accelerator built into the IBM Z processor, used through IBM\'s zDNN library for batch risk scoring.'],
];

/** Right-hand side sheet with searchable key terms. Not modal: the page behind stays usable. */
export function Glossary({open, onClose}: {open: boolean, onClose: () => void}) {
  const [filter, setFilter] = useState('');
  const sheet = useRef<HTMLElement>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    input.current?.focus();
    const onKey = (e: KeyboardEvent) => {if (e.key === 'Escape') onClose();};
    document.addEventListener('keydown', onKey);
    return () => {document.removeEventListener('keydown', onKey); if (opener && document.contains(opener)) opener.focus();};
  }, [open]);
  if (!open) return null;
  const query = filter.trim().toLowerCase();
  const shown = TERMS.filter(([term, text]) => !query || term.toLowerCase().includes(query) || text.toLowerCase().includes(query));
  return <aside ref={sheet} className="glossary" role="dialog" aria-modal="false" aria-labelledby="glossary-title">
    <div className="glossary-head">
      <h2 id="glossary-title">Key terms</h2>
      <button className="btn icon" aria-label="Close key terms" onClick={onClose}><X size={16}/></button>
    </div>
    <label className="glossary-search"><Search size={14} aria-hidden="true"/><input type="search" ref={input} aria-label="Filter key terms" placeholder="Filter terms" value={filter} onChange={e => setFilter(e.target.value)}/></label>
    {shown.length ? <dl className="glossary-list">{shown.map(([term, text]) => <div key={term}><dt>{term}</dt><dd>{text}</dd></div>)}</dl> : <p className="muted small glossary-none">No term matches “{filter}”.</p>}
  </aside>;
}
