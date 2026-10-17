import { useEffect, useState } from 'react';
import { BookOpen, X } from 'lucide-react';

export type GuideTab = 'overview' | 'encounters' | 'planning' | 'live' | 'validation';
const GUIDE_KEY = 'og-guide-dismissed';
const TIPS_PREFIX = 'og-tips-';
const TABS_WITH_TIPS: GuideTab[] = ['encounters', 'planning', 'live'];

function read(key: string): boolean {
  try {return localStorage.getItem(key) !== null;} catch {return false;}
}
function write(key: string, on: boolean) {
  try {if (on) localStorage.setItem(key, '1'); else localStorage.removeItem(key);} catch {/* storage unavailable: the choice lasts for this page only */}
}

export const guideDismissed = () => read(GUIDE_KEY);
export function dismissGuide() {write(GUIDE_KEY, true);}
/** Show the guide and every per-page tip strip again. */
export function reopenGuide() {
  write(GUIDE_KEY, false);
  TABS_WITH_TIPS.forEach(tab => write(TIPS_PREFIX + tab, false));
  window.dispatchEvent(new Event('og-guide-open'));
}

const STEPS: {tab: GuideTab, title: string, text: string, button: string}[] = [
  {tab: 'encounters', title: 'Watch a warning develop', text: 'Replay a real ESA encounter message by message and watch the Act, Wait or Monitor call update.', button: 'Open Encounters'},
  {tab: 'planning', title: 'Plan a burn that stays safe', text: 'Screen candidate burns against every nearby object, and see how dodging one object can steer into another.', button: 'Open planning'},
  {tab: 'live', title: 'Check a real satellite', text: 'Screen a real satellite against the tracked catalogue, see what debris a collision would create, and read a checked AI brief.', button: 'Open Live catalogue'},
];

export function Guide({tab, setTab, onGlossary, onHide}: {tab: GuideTab, setTab: (tab: GuideTab) => void, onGlossary: () => void, onHide: () => void}) {
  return <section className="guide" aria-labelledby="guide-heading">
    <h2 id="guide-heading">When two objects in orbit might collide, OrbitGuard helps an operator decide what to do.</h2>
    <p className="guide-lead">It forecasts how the risk will develop, plans a burn that is checked against every nearby object, and explains the result in plain language. A person always makes the final call.</p>
    <ol className="guide-steps">{STEPS.map((step, i) => <li key={step.tab}>
      <span className="guide-num" aria-hidden="true">{i + 1}</span>
      <div className="guide-step-body">
        <h3>{step.title}</h3>
        <p>{step.text}</p>
        {tab === step.tab ? <span className="guide-here">You are here</span> : <button className="btn small" onClick={() => {setTab(step.tab); window.scrollTo(0, 0);}}>{step.button}</button>}
      </div>
    </li>)}</ol>
    <div className="guide-foot">
      <p className="small">Validation shows where every number was measured. How it works explains the method.</p>
      <div className="actions">
        <button className="btn small" onClick={onGlossary}><BookOpen size={13}/> Key terms</button>
        <button className="btn small" onClick={onHide}>Hide guide</button>
      </div>
    </div>
  </section>;
}

/** A compact "Try this" strip under a page intro, dismissible per page. */
export function TryThis({tab, steps}: {tab: GuideTab, steps: string[]}) {
  const key = TIPS_PREFIX + tab;
  const [hidden, setHidden] = useState(() => read(key));
  useEffect(() => {
    setHidden(read(key));
    const show = () => setHidden(false);
    window.addEventListener('og-guide-open', show);
    return () => window.removeEventListener('og-guide-open', show);
  }, [key]);
  if (hidden) return null;
  return <section className="tryit" aria-label="Try this">
    <strong className="tryit-title">Try this</strong>
    <ol>{steps.map((text, i) => <li key={i}><span className="tryit-num" aria-hidden="true">{i + 1}</span><span>{text}</span></li>)}</ol>
    <button className="tryit-close" aria-label="Hide tips for this page" onClick={() => {write(key, true); setHidden(true);}}><X size={14}/></button>
  </section>;
}
