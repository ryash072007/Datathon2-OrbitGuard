// Synthesises each narration line with macOS `say`, converts it to 48 kHz WAV and records durations.
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { SCENES, VOICE, RATE } from './narration.mjs';

const out = new URL('./out/audio/', import.meta.url).pathname;
mkdirSync(out, {recursive: true});
const timing = {};
let total = 0;
for (const scene of SCENES) {
  const lines = [];
  for (const [i, text] of scene.lines.entries()) {
    const aiff = `${out}${scene.id}-${i}.aiff`, wav = `${out}${scene.id}-${i}.wav`;
    execFileSync('say', ['-v', VOICE, '-r', String(RATE), '-o', aiff, text]);
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', aiff, '-ar', '48000', '-ac', '2', wav]);
    const seconds = Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', wav]).toString());
    lines.push({file: wav, seconds});
  }
  // Lines start back to back with a short breath between them.
  let t = scene.lead;
  const starts = lines.map(line => {const s = t; t += line.seconds + 0.35; return s;});
  const duration = t - 0.35 + scene.tail;
  timing[scene.id] = {lines: lines.map((l, i) => ({...l, start: starts[i]})), duration};
  total += duration;
  console.log(`${scene.id.padEnd(11)} ${duration.toFixed(1)} s`);
}
console.log(`total       ${total.toFixed(1)} s`);
writeFileSync(`${out}timing.json`, JSON.stringify(timing, null, 2));
