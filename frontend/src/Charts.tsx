import { CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';
import { fixed, logProbability, number } from './api';
import type { Json } from './api';
import { useTokens } from './ui';

// ---------------------------------------------------------------- population of all held-out encounters

const TYPES: {key: string, label: string, token: 's1' | 's2' | 's3' | 'faint'}[] = [
  {key: 'DEBRIS', label: 'Debris', token: 's1'},
  {key: 'PAYLOAD', label: 'Satellite (payload)', token: 's2'},
  {key: 'ROCKET BODY', label: 'Rocket body', token: 's3'},
  {key: 'UNKNOWN', label: 'Unknown', token: 'faint'},
];
const typeOf = (value: string) => TYPES.some(t => t.key === value) ? value : 'UNKNOWN';

export function PopulationChart({population, selected, onSelect}: {population: Json, selected: string, onSelect: (id: string) => void}) {
  const t = useTokens();
  const c = population.columns || {};
  const rows: Json[] = (c.event_id || []).map((id: string, i: number) => ({
    id, inc: c.c_j2k_inc?.[i], alt: c.c_h_per?.[i], risk: c.risk?.[i], type: typeOf(c.c_object_type?.[i]),
  })).filter((r: Json) => typeof r.inc === 'number' && typeof r.alt === 'number');
  const counts = Object.fromEntries(TYPES.map(type => [type.key, rows.filter(r => r.type === type.key).length]));
  const highRisk = rows.filter(r => r.risk >= -6).length;
  const current = rows.find(r => r.id === selected);
  const dot = (color: string) => (props: Json) => {
    const high = props.payload.risk >= -6;
    return <circle cx={props.cx} cy={props.cy} r={high ? 3.6 : 2} fill={color} fillOpacity={high ? 0.95 : 0.35} stroke={high ? t.surface : 'none'} strokeWidth={high ? 1 : 0} style={{cursor: 'pointer'}}/>;
  };
  return <div className="population">
    <ResponsiveContainer width="100%" height={340}>
      <ScatterChart margin={{top: 10, right: 16, left: 4, bottom: 22}}>
        <CartesianGrid stroke={t.grid}/>
        <XAxis type="number" dataKey="inc" name="Inclination" domain={[0, 130]} ticks={[0, 30, 60, 90, 120]} tickFormatter={v => `${v}°`} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} label={{value: 'Orbit inclination of the approaching object', position: 'insideBottom', offset: -14, fill: t.muted, fontSize: 12}}/>
        <YAxis type="number" dataKey="alt" name="Perigee altitude" domain={[150, 900]} ticks={[200, 400, 600, 800]} allowDataOverflow tickFormatter={v => `${v} km`} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} width={58}/>
        <ZAxis range={[20, 20]}/>
        <Tooltip cursor={false} content={({active, payload}) => {
          const r = active && payload?.[0]?.payload;
          return r ? <div className="chart-tip"><div><strong>Encounter #{r.id}</strong></div><div className="muted">{TYPES.find(x => x.key === r.type)?.label} · {number(r.inc, 1)}° · perigee {number(r.alt, 0)} km</div><div>Latest Pc {logProbability(r.risk)}</div><div className="muted small">Click to open</div></div> : null;
        }}/>
        {TYPES.map(type => <Scatter key={type.key} name={type.label} data={rows.filter(r => r.type === type.key)} shape={dot(t[type.token])} isAnimationActive={false} onClick={(point: Json) => onSelect(String(point.payload?.id ?? point.id))}/>)}
        {current && <Scatter data={[current]} isAnimationActive={false} shape={(props: Json) => <g><circle cx={props.cx} cy={props.cy} r={9} fill="none" stroke={t.text} strokeWidth={2}/><text x={props.cx + 13} y={props.cy + 4} fill={t.text} fontSize={12} fontWeight={500}>#{current.id}</text></g>}/>}
      </ScatterChart>
    </ResponsiveContainer>
    <ul className="legend horizontal">
      {TYPES.map(type => <li key={type.key}><span className="swatch dot" style={{background: t[type.token]}}/>{type.label} ({number(counts[type.key], 0)})</li>)}
      <li><span className="swatch dot big" style={{background: t.muted}}/>Larger dots: latest Pc at least 10⁻⁶ ({number(highRisk, 0)})</li>
    </ul>
  </div>;
}

// ---------------------------------------------------------------- precision-recall for both rankings

export function RankingCurve({curves}: {curves: Json}) {
  const t = useTokens();
  const series = [
    {key: 'latest', label: 'Latest reported value', color: t.muted, data: curves.latest || []},
    {key: 'learned', label: 'Learned model', color: t.s1, data: curves.learned || []},
  ];
  return <div className="ranking-curve">
    <ResponsiveContainer width="100%" height={260}>
      <LineChart margin={{top: 10, right: 20, left: 4, bottom: 22}}>
        <CartesianGrid stroke={t.grid}/>
        <XAxis type="number" dataKey="recall" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} label={{value: 'Share of high-risk encounters found (recall)', position: 'insideBottom', offset: -14, fill: t.muted, fontSize: 12}}/>
        <YAxis type="number" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} width={48} label={{value: 'Precision', angle: -90, position: 'insideLeft', offset: 10, fill: t.muted, fontSize: 12}}/>
        <Tooltip cursor={{stroke: t.axis}} content={({active, payload}) => active && payload?.length ? <div className="chart-tip">{payload.map(p => <div key={String(p.name)}>{p.name}: recall {fixed(p.payload.recall * 100, 0)}%, precision {fixed(p.payload.precision * 100, 0)}%</div>)}</div> : null}/>
        {series.map(s => <Line key={s.key} name={s.label} data={s.data} dataKey="precision" stroke={s.color} strokeWidth={2} dot={false} isAnimationActive={false} type="stepAfter"/>)}
      </LineChart>
    </ResponsiveContainer>
    <ul className="legend horizontal">{series.map(s => <li key={s.key}><span className="swatch" style={{background: s.color}}/>{s.label}</li>)}</ul>
  </div>;
}

// ---------------------------------------------------------------- outcomes of each policy across the scenario suite

const OUTCOMES = [
  {key: 'acceptable_plan_count', label: 'Safe plan', token: 'good' as const},
  {key: 'correct_abstentions', label: 'Correctly declined', token: 'neutral' as const},
  {key: 'unsafe_selected_count', label: 'Unsafe choice', token: 'bad' as const},
];

export function PolicyBars({policies, total, names}: {policies: Json, total: number, names: {id: string, label: string}[]}) {
  const t = useTokens();
  return <div className="policy-bars">
    {names.map(p => {
      const row = policies[p.id];
      if (!row) return null;
      return <div className="bar-row" key={p.id}>
        <span className="bar-label">{p.label}</span>
        <div className="bar" role="img" aria-label={`${p.label}: ${OUTCOMES.map(o => `${row[o.key]} ${o.label.toLowerCase()}`).join(', ')} out of ${total}`}>
          {OUTCOMES.map(o => row[o.key] > 0 && <div key={o.key} className="bar-segment" style={{width: `${row[o.key] / total * 100}%`, background: t[o.token]}} title={`${row[o.key]} ${o.label.toLowerCase()}`}>{row[o.key] / total >= 0.08 ? row[o.key] : ''}</div>)}
        </div>
      </div>;
    })}
    <ul className="legend horizontal">{OUTCOMES.map(o => <li key={o.key}><span className="swatch block" style={{background: t[o.token]}}/>{o.label}</li>)}</ul>
  </div>;
}
