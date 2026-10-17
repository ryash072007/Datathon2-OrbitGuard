// Assembles recorded frames, narration and a synthesised ambient bed into the final demo video.
// Outputs (in video/out/): OrbitGuard_demo.mp4, OrbitGuard_demo_music_only.mp4, OrbitGuard_demo.srt, poster.png
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import { SCENES } from './narration.mjs';

const OUT = new URL('./out/', import.meta.url).pathname;
const timing = JSON.parse(fs.readFileSync(`${OUT}audio/timing.json`, 'utf8'));
const ff = args => execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], {stdio: ['ignore', 'inherit', 'inherit']});
const work = `${OUT}build/`;
fs.mkdirSync(work, {recursive: true});

const parts = [];
let offset = 0;
const subtitles = [];
for (const scene of SCENES) {
  const meta = JSON.parse(fs.readFileSync(`${OUT}frames/${scene.id}/frames.json`, 'utf8'));
  const D = timing[scene.id].duration;
  const frames = meta.frames.filter(f => f.t < D).sort((a, b) => a.t - b.t);
  // Variable frame timing from the screencast, held until the next frame arrives.
  const lines = ['ffconcat version 1.0'];
  frames.forEach((f, i) => {
    const start = i === 0 ? 0 : f.t;
    const end = i + 1 < frames.length ? frames[i + 1].t : D;
    lines.push(`file '${f.file}'`, `duration ${Math.max(end - start, 0.001).toFixed(4)}`);
  });
  lines.push(`file '${frames[frames.length - 1].file}'`);
  fs.writeFileSync(`${work}${scene.id}.ffconcat`, lines.join('\n'));
  const fadeIn = scene.id === 'title' ? 1.0 : 0.35, fadeOut = scene.id === 'outro' ? 1.2 : 0.35;
  ff(['-f', 'concat', '-safe', '0', '-i', `${work}${scene.id}.ffconcat`,
    '-vf', `fps=30,tpad=stop_mode=clone:stop_duration=2,format=yuv420p,fade=t=in:st=0:d=${fadeIn},fade=t=out:st=${(D - fadeOut).toFixed(3)}:d=${fadeOut}`,
    '-t', D.toFixed(3), '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', '30', '-an', `${work}${scene.id}.mp4`]);

  // Narration lines at their cue times.
  const audio = timing[scene.id].lines;
  const inputs = audio.flatMap(l => ['-i', l.file]);
  const delays = audio.map((l, i) => `[${i}]adelay=${Math.round(l.start * 1000)}|${Math.round(l.start * 1000)}[a${i}]`).join(';');
  const mix = `${audio.map((_, i) => `[a${i}]`).join('')}amix=inputs=${audio.length}:normalize=0,apad=whole_dur=${D.toFixed(3)}[out]`;
  ff([...inputs, '-filter_complex', `${delays};${mix}`, '-map', '[out]', '-t', D.toFixed(3), '-ar', '48000', '-ac', '2', `${work}${scene.id}.wav`]);

  // Subtitles: one cue per sentence, timed in proportion to its length within the line.
  scene.lines.forEach((text, i) => {
    const sentences = text.match(/[^.?!]+[.?!]?/g).map(s => s.trim()).filter(Boolean);
    const total = sentences.reduce((n, s) => n + s.length, 0);
    let t = offset + audio[i].start;
    for (const s of sentences) {const d = audio[i].seconds * s.length / total; subtitles.push({start: t, end: t + d, text: s}); t += d;}
  });
  parts.push(scene.id);
  offset += D;
  console.log(`${scene.id.padEnd(11)} encoded (${D.toFixed(1)} s)`);
}

fs.writeFileSync(`${work}video.txt`, parts.map(p => `file '${work}${p}.mp4'`).join('\n'));
fs.writeFileSync(`${work}audio.txt`, parts.map(p => `file '${work}${p}.wav'`).join('\n'));
ff(['-f', 'concat', '-safe', '0', '-i', `${work}video.txt`, '-c', 'copy', `${work}video.mp4`]);
ff(['-f', 'concat', '-safe', '0', '-i', `${work}audio.txt`, '-c', 'pcm_s16le', `${work}narration.wav`]);

// Ambient pad: slowly swelling A-major add9 voicing, detuned between channels, softened and spaced.
const T = offset.toFixed(3);
const notes = [[110, 0.18, 0.031, 0], [164.81, 0.12, 0.047, 1.3], [246.94, 0.09, 0.039, 2.1], [277.18, 0.07, 0.053, 0.4], [329.63, 0.05, 0.027, 2.9]];
const voice = detune => notes.map(([f, a, lfo, ph]) => `${a}*sin(2*PI*${(f + detune).toFixed(2)}*t)*(0.5+0.5*sin(2*PI*${lfo}*t+${ph}))`).join('+');
ff(['-f', 'lavfi', '-i', `aevalsrc=exprs='${voice(0)}|${voice(0.35)}':s=48000:d=${T}`,
  '-af', `lowpass=f=1500,aecho=0.8:0.6:180|360:0.22|0.14,afade=t=in:d=3,afade=t=out:st=${(offset - 4).toFixed(2)}:d=4`, `${work}music.wav`]);

const final = `${OUT}OrbitGuard_demo.mp4`;
ff(['-i', `${work}video.mp4`, '-i', `${work}narration.wav`, '-i', `${work}music.wav`, '-filter_complex',
  '[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,asplit[v1][v2];[2:a]loudnorm=I=-31:TP=-6[m0];[m0][v1]sidechaincompress=threshold=0.04:ratio=5:attack=30:release=500[m];[v2][m]amix=inputs=2:normalize=0[a]',
  '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-shortest', final]);
ff(['-i', `${work}video.mp4`, '-i', `${work}music.wav`, '-filter_complex', '[1:a]loudnorm=I=-20:TP=-2[a]',
  '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-shortest', `${OUT}OrbitGuard_demo_music_only.mp4`]);

const stamp = s => {const ms = Math.round(s * 1000); const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, sec = Math.floor(ms / 1000) % 60; return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')},${String(ms % 1000).padStart(3, '0')}`;};
fs.writeFileSync(`${OUT}OrbitGuard_demo.srt`, subtitles.map((s, i) => `${i + 1}\n${stamp(s.start)} --> ${stamp(s.end)}\n${s.text}\n`).join('\n'));
const planningStart = SCENES.slice(0, SCENES.findIndex(s => s.id === 'planning')).reduce((n, s) => n + timing[s.id].duration, 0);
ff(['-ss', (planningStart + 25.5).toFixed(2), '-i', final, '-frames:v', '1', `${OUT}poster.png`]);
const duration = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', final]).toString().trim();
console.log(`\n${final}\nduration ${Number(duration).toFixed(2)} s`);
