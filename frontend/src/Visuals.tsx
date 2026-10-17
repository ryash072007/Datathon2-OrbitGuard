import { useEffect, useMemo, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Globe from './Globe';
import type { GlobeMarker, GlobeOrbit, Vec3 } from './Globe';
import { finite, number, probability } from './api';
import type { Json } from './api';
import { Tip, useTokens } from './ui';

const km = (p: Json): Vec3 => [p.x_m / 1000, p.y_m / 1000, p.z_m / 1000];
const distanceKm = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
export const formatDistance = (valueKm: number | null | undefined) => !finite(valueKm) ? '—' : valueKm < 1 ? `${number(valueKm * 1000, 0)} m` : valueKm < 100 ? `${number(valueKm, 1)} km` : `${number(valueKm, 0)} km`;
const clock = (seconds: number) => `T+${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;

// ---------------------------------------------------------------- manoeuvre planning: the whole neighbourhood

type OrbitalProps = {trajectories: Json[], activePolicy: string, policyLabel: string, primaryId: string, secondaryId?: string, burnTime?: number | null, primaryTca?: number, secondaryTca?: number, limitKm?: number};

export function OrbitalView({trajectories, activePolicy, policyLabel, primaryId, secondaryId, burnTime, primaryTca, secondaryTca}: OrbitalProps) {
  const t = useTokens();
  const base = trajectories.filter(tr => !tr.policy);
  const original = base.find(tr => tr.object_id === 'A');
  const policyPath = trajectories.find(tr => tr.policy === activePolicy);
  const pathA = activePolicy !== 'no_action' && policyPath ? policyPath : original;
  const times: number[] = (pathA?.points || []).map((p: Json) => p.t_seconds);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState<Vec3 | null>(null);
  useEffect(() => {
    if (!playing || !times.length) return;
    const timer = window.setInterval(() => setIndex(i => {if (i >= times.length - 1) {setPlaying(false); return i;} return i + 1;}), 70);
    return () => window.clearInterval(timer);
  }, [playing, times.length]);
  const nearestIndex = (seconds?: number | null) => finite(seconds) && times.length ? times.reduce((best, value, i) => Math.abs(value - seconds) < Math.abs(times[best] - seconds) ? i : best, 0) : 0;

  const colorFor = (id: string) => id === 'A' ? t.s1 : id === primaryId ? t.s2 : id === secondaryId ? t.s3 : t.faint;
  const orbits: GlobeOrbit[] = useMemo(() => {
    const list: GlobeOrbit[] = base.filter(tr => tr.object_id !== 'A').map(tr => {
      const main = tr.object_id === primaryId || tr.object_id === secondaryId;
      return {id: tr.object_id, color: colorFor(tr.object_id), points: tr.points.map(km), width: main ? 2 : 1, opacity: main ? 1 : 0.6};
    });
    if (pathA && pathA !== original && original) list.push({id: 'A-original', color: t.muted, points: original.points.map(km), width: 1.5, dashed: true, opacity: 0.9});
    if (pathA) list.push({id: 'A', color: t.s1, points: pathA.points.map(km), width: 2.6});
    return list;
  }, [trajectories, activePolicy, t.s1, t.s2, t.s3, t.muted, t.faint]);

  const position = (tr: Json | undefined, i: number): Vec3 | null => tr?.points?.[i] ? km(tr.points[i]) : null;
  const objectB = base.find(tr => tr.object_id === primaryId);
  const objectC = secondaryId ? base.find(tr => tr.object_id === secondaryId) : undefined;
  const markers: GlobeMarker[] = [];
  for (const tr of base) {
    const id = tr.object_id === 'A' ? 'A' : tr.object_id;
    const p = position(tr.object_id === 'A' ? pathA : tr, index);
    if (p) markers.push({id: `now-${id}`, position: p, color: colorFor(id), label: id, kind: id === 'A' || id === primaryId || id === secondaryId ? 'object' : 'minor', labelLeft: id === 'A'});
  }
  const burnIndex = finite(burnTime) ? nearestIndex(burnTime) : null;
  const primaryIndex = nearestIndex(primaryTca);
  const secondaryIndex = secondaryId ? nearestIndex(secondaryTca) : null;
  const burnPoint = burnIndex !== null ? position(pathA, burnIndex) : null;
  if (burnPoint && activePolicy !== 'no_action') markers.push({id: 'event-burn', position: burnPoint, color: t.s1, label: index === burnIndex ? '' : 'Burn', kind: 'event', labelLeft: true});
  const pPoint = position(objectB, primaryIndex);
  if (pPoint) markers.push({id: 'event-primary', position: pPoint, color: t.s2, label: index === primaryIndex ? '' : `Encounter ${primaryId}`, kind: 'event'});
  const sPoint = secondaryIndex !== null ? position(objectC, secondaryIndex) : null;
  if (sPoint) markers.push({id: 'event-secondary', position: sPoint, color: t.s3, label: index === secondaryIndex ? '' : `Encounter ${secondaryId}`, kind: 'event'});

  const separation = times.map((seconds, i) => {
    const a = position(pathA, i);
    const row: Json = {minute: seconds / 60};
    for (const tr of base) if (tr.object_id !== 'A' && a) {const p = position(tr, i); if (p) row[tr.object_id] = Math.max(distanceKm(a, p), 0.001);}
    return row;
  });
  const now = separation[index] || {};
  const nearestOther = base.filter(tr => tr.object_id !== 'A').map(tr => ({id: tr.object_id, d: now[tr.object_id] as number})).filter(x => finite(x.d)).sort((x, y) => x.d - y.d)[0];
  const jump = (i: number | null, point: Vec3 | null) => {if (i === null) return; setPlaying(false); setIndex(i); if (point) setFocus([...point] as Vec3);};

  if (!pathA || !times.length) return <div className="placeholder empty"><strong>No trajectory data for this scenario</strong></div>;
  return <div className="orbital">
    <div className="orbital-main">
      <Globe orbits={orbits} markers={markers} focus={focus} height={460} label={`Orbits of satellite A and ${base.length - 1} nearby objects over three hours, showing ${policyLabel}.`}/>
      <aside className="orbital-side">
        <div className="time-readout"><span className="figure-label">Simulation time</span><strong>{clock(times[index])}</strong><span className="small muted">of {clock(times[times.length - 1])}</span></div>
        <div className="replay">
          <button className="btn icon" aria-label={playing ? 'Pause' : 'Play the three-hour window'} onClick={() => {if (!playing && index >= times.length - 1) setIndex(0); setPlaying(p => !p);}}>{playing ? <Pause size={14}/> : <Play size={14}/>}</button>
          <input type="range" aria-label="Simulation time" min={0} max={times.length - 1} value={index} onChange={e => {setPlaying(false); setIndex(Number(e.target.value));}}/>
        </div>
        <div className="jumps">
          <span className="figure-label">Jump to</span>
          {burnIndex !== null && activePolicy !== 'no_action' && <button className="btn small" onClick={() => jump(burnIndex, burnPoint)}>Burn ({clock(times[burnIndex])})</button>}
          <button className="btn small" onClick={() => jump(primaryIndex, pPoint)}>Closest approach with {primaryId} ({clock(times[primaryIndex])})</button>
          {secondaryIndex !== null && <button className="btn small" onClick={() => jump(secondaryIndex, sPoint)}>Closest approach with {secondaryId} ({clock(times[secondaryIndex])})</button>}
        </div>
        <dl className="facts stacked">
          <div><dt>Distance from A to {primaryId}</dt><dd>{formatDistance(now[primaryId])}</dd></div>
          {secondaryId && <div><dt>Distance from A to {secondaryId}</dt><dd>{formatDistance(now[secondaryId])}</dd></div>}
          {nearestOther && <div><dt>Nearest object right now</dt><dd>{nearestOther.id}, {formatDistance(nearestOther.d)}</dd></div>}
        </dl>
        <ul className="legend">
          <li><span className="swatch" style={{background: t.s1}}/>Satellite A ({policyLabel})</li>
          {pathA !== original && <li><span className="swatch dashed-swatch"/>A without a burn</li>}
          <li><span className="swatch" style={{background: t.s2}}/>Object {primaryId} (original threat)</li>
          {secondaryId && <li><span className="swatch" style={{background: t.s3}}/>Object {secondaryId}</li>}
          <li><span className="swatch" style={{background: t.faint}}/>Other tracked objects</li>
        </ul>
      </aside>
    </div>
    <div className="separation">
      <h3 className="subhead">Distance from satellite A to each object <Tip text="Sampled every minute along the simulated paths, on a logarithmic scale. Dips are close approaches; the exact minimum distance and collision probability come from the refined calculation in the table below. Click the chart to move the time cursor."/></h3>
      <SeparationChart rows={separation} objects={base.filter(tr => tr.object_id !== 'A').map(tr => tr.object_id)} primaryId={primaryId} secondaryId={secondaryId} cursor={times[index] / 60} onPick={minute => jump(nearestIndex(minute * 60), null)}/>
    </div>
  </div>;
}

function SeparationChart({rows, objects, primaryId, secondaryId, cursor, onPick}: {rows: Json[], objects: string[], primaryId: string, secondaryId?: string, cursor: number, onPick: (minute: number) => void}) {
  const t = useTokens();
  const ticks = [0.01, 0.1, 1, 10, 100, 1000, 10000];
  const main = [primaryId, secondaryId].filter(Boolean) as string[];
  const minor = objects.filter(id => !main.includes(id));
  return <ResponsiveContainer width="100%" height={230}>
    <LineChart data={rows} margin={{top: 8, right: 16, left: 8, bottom: 20}} onClick={(state: Json) => {if (finite(state?.activeLabel)) onPick(state.activeLabel);}}>
      <CartesianGrid stroke={t.grid} vertical={false}/>
      <ReferenceArea y1={0.001} y2={1} fill={t.bad} fillOpacity={0.06} ifOverflow="hidden" label={{value: 'Under 1 km', position: 'insideTopLeft', fill: t.muted, fontSize: 11}}/>
      <XAxis dataKey="minute" type="number" domain={[0, 'dataMax']} tickFormatter={v => `${v} min`} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} label={{value: 'Minutes after scenario start', position: 'insideBottom', offset: -14, fill: t.muted, fontSize: 12}}/>
      <YAxis scale="log" domain={[0.01, 20000]} ticks={ticks} allowDataOverflow tickFormatter={v => Number(v) >= 1000 ? `${Number(v) / 1000}k km` : formatDistance(Number(v))} tick={{fill: t.muted, fontSize: 12}} stroke={t.axis} tickLine={false} width={58}/>
      <ReferenceLine x={cursor} stroke={t.text} strokeWidth={1}/>
      <Tooltip cursor={{stroke: t.axis}} content={({active, payload, label}) => active && payload?.length ? <div className="chart-tip"><div className="muted">{number(Number(label), 0)} min after start</div>{payload.filter(p => main.includes(String(p.dataKey))).map(p => <div key={String(p.dataKey)}>{String(p.dataKey)}: {formatDistance(Number(p.value))}</div>)}</div> : null}/>
      {minor.map(id => <Line key={id} dataKey={id} stroke={t.faint} strokeWidth={1} dot={false} isAnimationActive={false}/>)}
      {main.map(id => <Line key={id} dataKey={id} stroke={id === primaryId ? t.s2 : t.s3} strokeWidth={2} dot={false} isAnimationActive={false}/>)}
    </LineChart>
  </ResponsiveContainer>;
}

// ---------------------------------------------------------------- encounters: the two orbits from the CDM

function orbitPoints(aKm: number, e: number, incDeg: number, count = 240): Vec3[] {
  const inc = incDeg * Math.PI / 180;
  const points: Vec3[] = [];
  for (let k = 0; k < count; k++) {
    const nu = 2 * Math.PI * k / count;
    const r = aKm * (1 - e * e) / (1 + e * Math.cos(nu));
    const xp = r * Math.cos(nu), yp = r * Math.sin(nu);
    points.push([xp, yp * Math.cos(inc), yp * Math.sin(inc)]);
  }
  return points;
}
const TYPE_LABEL: Record<string, string> = {DEBRIS: 'Debris', PAYLOAD: 'Satellite (payload)', 'ROCKET BODY': 'Rocket body', UNKNOWN: 'Unknown object', TBA: 'Unknown object'};

export function EncounterOrbits({message}: {message: Json}) {
  const t = useTokens();
  const ok = ['t_j2k_sma', 't_j2k_ecc', 't_j2k_inc', 'c_j2k_sma', 'c_j2k_ecc', 'c_j2k_inc'].every(k => finite(message[k]));
  const target = useMemo(() => ok ? orbitPoints(message.t_j2k_sma, message.t_j2k_ecc, message.t_j2k_inc) : [], [message, ok]);
  const chaser = useMemo(() => ok ? orbitPoints(message.c_j2k_sma, message.c_j2k_ecc, message.c_j2k_inc) : [], [message, ok]);
  if (!ok) return <div className="placeholder empty"><strong>Orbital elements are missing for this encounter</strong></div>;
  const encounter: Vec3 = target[0];
  const type = TYPE_LABEL[String(message.c_object_type)] || 'Unknown object';
  const orbits: GlobeOrbit[] = [
    {id: 'target', color: t.s1, points: target, width: 2.4, closed: true},
    {id: 'chaser', color: t.s2, points: chaser, width: 2.4, closed: true},
  ];
  const markers: GlobeMarker[] = [
    {id: 'encounter', position: encounter, color: t.text, label: 'Encounter point', kind: 'event'},
    {id: 'target-label', position: target[Math.floor(target.length * 0.06)], color: t.s1, label: 'ESA satellite', kind: 'object'},
    {id: 'chaser-label', position: chaser[Math.floor(chaser.length * 0.94)], color: t.s2, label: type, kind: 'object', labelLeft: true},
  ];
  const apogee = Math.max(message.c_j2k_sma * (1 + message.c_j2k_ecc), message.t_j2k_sma * (1 + message.t_j2k_ecc));
  const crossing = Math.abs(message.t_j2k_inc - message.c_j2k_inc);
  return <div className="encounter-orbits">
    <Globe orbits={orbits} markers={markers} focus={encounter} height={380} fitRadiusKm={apogee} label={`Orbit of the ESA satellite at ${number(message.t_j2k_inc, 1)} degrees inclination and of the ${type.toLowerCase()} at ${number(message.c_j2k_inc, 1)} degrees.`}/>
    <div className="table-wrap"><table className="table compact">
      <thead><tr><th/><th>ESA satellite</th><th>{type}</th></tr></thead>
      <tbody>
        <tr><td className="muted">Altitude (perigee to apogee)</td><td>{number(message.t_h_per, 0)}–{number(message.t_h_apo, 0)} km</td><td>{number(message.c_h_per, 0)}–{number(message.c_h_apo, 0)} km</td></tr>
        <tr><td className="muted">Inclination <Tip text="Tilt of the orbit relative to the equator. Around 98° is a sun-synchronous orbit; above 90° means the object travels against Earth's rotation."/></td><td>{number(message.t_j2k_inc, 1)}°</td><td>{number(message.c_j2k_inc, 1)}°</td></tr>
      </tbody>
    </table></div>
    <dl className="facts">
      <div><dt>Relative speed</dt><dd>{number(message.relative_speed / 1000, 1)} km/s</dd></div>
      <div><dt>Predicted miss distance</dt><dd>{formatDistance(message.miss_distance / 1000)}</dd></div>
      <div><dt>Orbits cross at</dt><dd>{number(crossing, 0)}° apart</dd></div>
    </dl>
    <p className="footnote">Orbit size, shape and tilt come from the latest message. ESA anonymised the dataset, so where each orbit sits around the Earth is illustrative: both are drawn crossing at the encounter point. Latest reported Pc {probability(Math.pow(10, message.risk))}.</p>
  </div>;
}
