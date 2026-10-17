// Records every scene of the demo video as timestamped frames, using Chrome's screencast.
// Narrative scenes are local HTML; app scenes drive the live OrbitGuard console on LinuxONE
// (through the SSH tunnel at APP_URL). Cues fire when each narration line starts.
// Usage: node video/record.mjs [sceneId ...]
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import fs from 'node:fs';

const ROOT = new URL('..', import.meta.url).pathname;
const OUT = `${ROOT}video/out/`;
const APP = process.env.APP_URL || 'http://127.0.0.1:8080';
const timing = JSON.parse(fs.readFileSync(`${OUT}audio/timing.json`, 'utf8'));
const demo = JSON.parse(fs.readFileSync(`${ROOT}artifacts/linuxone/physics/demonstration.json`, 'utf8'));
const CANDIDATES = demo.candidates.map(c => ({id: c.candidate_id, accepted: c.accepted, chosen: c.candidate_id === demo.recommendation?.candidate_id}));
const TERMINAL = JSON.parse(fs.readFileSync(`${ROOT}video/terminal.json`, 'utf8'));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const scene = file => `file://${ROOT}video/scenes/${file}`;

// ---------------------------------------------------------------- helpers for the live app

let cursor = {x: 960, y: 1150};
async function moveTo(page, target, ms = 550) {
  const box = typeof target.boundingBox === 'function' ? await target.boundingBox() : target;
  if (!box) return;
  const x = box.x + (box.width ?? 0) / 2, y = box.y + (box.height ?? 0) / 2;
  const steps = Math.max(8, Math.round(ms / 16));
  for (let i = 1; i <= steps; i++) {
    const k = i / steps, e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    await page.mouse.move(cursor.x + (x - cursor.x) * e, cursor.y + (y - cursor.y) * e);
    await sleep(16);
  }
  cursor = {x, y};
}
async function click(page, locator, ms) {await locator.scrollIntoViewIfNeeded().catch(() => {}); await moveTo(page, locator, ms); await sleep(120); await page.mouse.down(); await sleep(70); await page.mouse.up();}
const side = (page, where, content) => page.evaluate(([w, c]) => window.__vo.side(w, c), [where, content]);
const chapter = (page, n, label) => page.evaluate(([a, b]) => window.__vo.chapter(a, b), [n, label]);
async function ring(page, locator, ms = 2500, pad = 8) {const h = await locator.elementHandle(); await page.evaluate(([el, m, p]) => window.__vo.ring(el, m, p), [h, ms, pad]);}
async function scrollTo(page, locator, offset = 76, ms = 1000) {const h = locator ? await locator.elementHandle() : null; await page.evaluate(([el, o, m]) => window.__vo.scrollToEl(el, o, m), [h, offset, ms]); await sleep(60);}
const section = (page, heading) => page.locator('section.section', {has: page.getByRole('heading', {name: heading})});

// ---------------------------------------------------------------- scenes

const SCENES = [
  {id: 'title', url: scene('title.html'), extras: [[5.6, 2]]},
  {id: 'problem', url: scene('problem.html')},
  {id: 'solution', url: scene('solution.html'), init: [c => {window.CANDIDATES = c;}, CANDIDATES]},
  {id: 'linuxone', url: scene('linuxone.html'), init: [t => {window.TERMINAL = t;}, TERMINAL]},
  {id: 'encounters', app: true, url: `${APP}/#encounters`,
    async prepare(page) {
      await page.getByRole('heading', {name: /^Encounter #891/}).waitFor({timeout: 60000});
      await page.locator('.encounters-visuals .globe canvas').waitFor({timeout: 60000});
      await page.locator('.population .recharts-scatter-symbol').first().waitFor({timeout: 60000});
      await page.evaluate(() => window.scrollTo(0, 0));
    },
    cues: [
      async page => {
        await chapter(page, '01', 'Encounter monitor');
        await side(page, 'left', {kicker: 'Real data', title: 'ESA Collision Avoidance Challenge', body: '2,167 held-out encounters, never used for training. The list shows the 100 with the highest latest risk.', top: 330});
        await ring(page, page.locator('.list-card'), 2600);
        await moveTo(page, page.getByRole('button', {name: '#891'}), 900);
      },
      async page => {
        await side(page, 'right', {kicker: 'The 48-hour rule', title: 'Forecast from what was known two days ahead', body: 'Replay steps through the alert messages one at a time. The forecast updates as each one arrives.', top: 330});
        await click(page, page.getByRole('button', {name: /Replay messages|Pause replay/}), 700);
        await sleep(2600);
        await ring(page, page.locator('.figures'), 3600);
        await moveTo(page, page.locator('.figures .figure').nth(0), 700);
        await sleep(900);
        await moveTo(page, page.locator('.figures .figure').nth(2), 700);
      },
      async page => {
        await side(page, 'left', {kicker: 'Built for operators', title: 'Every term explains itself', body: 'Hover any underlined word or question mark for a plain-language definition.', top: 330});
        await moveTo(page, page.locator('.lead .term').first(), 650);
        await sleep(1900);
      },
      async page => {
        await page.mouse.move(1700, 900); cursor = {x: 1700, y: 900};
        await scrollTo(page, page.locator('.encounters-visuals'), 76, 850);
        await side(page, 'right', {kicker: 'From the alert data', title: 'The two orbits that meet', body: 'ESA satellite at 98.3°, debris at 73.9°. They cross at 14.9 km/s.', top: 300});
        const globe = await page.locator('.encounters-visuals .globe').boundingBox();
        await moveTo(page, {x: globe.x + globe.width * 0.62, y: globe.y + globe.height * 0.45, width: 0, height: 0}, 300);
        await page.mouse.down();
        // Release the drag without blocking the next line; the globe keeps easing on its own.
        moveTo(page, {x: globe.x + globe.width * 0.38, y: globe.y + globe.height * 0.5, width: 0, height: 0}, 900).then(() => page.mouse.up());
        await sleep(150);
      },
      async page => {
        await side(page, 'left', {kicker: 'All 2,167 encounters', title: 'Where encounters happen', body: 'Each dot is one encounter, placed by the orbit of the approaching object. The vertical bands are orbits crowded with debris.', top: 300});
        await ring(page, page.locator('.population'), 3800);
        const symbols = page.locator('.population .recharts-scatter-symbol');
        const count = await symbols.count();
        await sleep(800);
        for (const k of [0.62, 0.78]) {await moveTo(page, symbols.nth(Math.floor(count * k)), 750); await sleep(1100);}
      },
    ]},
  {id: 'planning', app: true, url: `${APP}/#planning`,
    async prepare(page) {
      await page.getByRole('button', {name: 'Screen manoeuvres', exact: true}).waitFor({timeout: 60000});
      await page.locator('[aria-label="Orbital view"] .globe canvas').waitFor({timeout: 60000});
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(800);
    },
    cues: [
      async page => {
        await chapter(page, '02', 'Manoeuvre planning');
        await side(page, 'left', {kicker: 'Synthetic scenario', title: 'Eight objects, three hours', body: 'Satellite A is heading for object B. Without a burn, A passes 21 m from B.', top: 330});
        await scrollTo(page, page.getByLabel('Orbital view'), 70, 1200);
        await click(page, page.getByRole('button', {name: /^Closest approach with B \(T\+/}), 700);
      },
      async page => {
        await scrollTo(page, null, 0, 900);
        await side(page, 'right', {kicker: 'Computed on IBM LinuxONE', title: '37 burns × every object × 3 uncertainty levels', body: 'Each candidate is propagated, checked against all seven neighbours, then re-verified with a finer time step.', top: 330, accent: '#22a87a'});
        await click(page, page.getByRole('button', {name: 'Screen manoeuvres', exact: true}), 700);
        await page.getByRole('button', {name: 'Run again', exact: true}).waitFor({timeout: 30000});
        await sleep(300);
        await ring(page, page.locator('.recommendation'), 3200);
        await moveTo(page, page.locator('.recommendation .facts > div').nth(1), 700);
      },
      async page => {
        await scrollTo(page, page.getByLabel('Policy comparison'), 70, 900);
        await side(page, 'left', {kicker: 'The tempting option', title: 'Avoid B only: −0.05 m/s', body: 'The cheapest burn that clears B. It ignores every other object.', top: 330, accent: '#e2672f'});
        await click(page, page.getByRole('button', {name: 'Avoid B only'}), 650);
        await sleep(200);
        await ring(page, page.locator('.policy-table tr.selected'), 2400, 4);
      },
      async page => {
        await scrollTo(page, page.getByLabel('Orbital view'), 70, 900);
        await click(page, page.getByRole('button', {name: /^Closest approach with C \(T\+/}), 500);
      },
      async page => {
        await side(page, 'right', {kicker: 'The hidden cost', title: '15 m from object C', body: 'Collision probability 0.0215, more than 200 times the one-in-ten-thousand limit.', top: 560, accent: '#e5534b'});
        await ring(page, page.locator('.separation'), 4200, 6);
        const chart = await page.locator('.separation .recharts-wrapper').boundingBox();
        await moveTo(page, {x: chart.x + 66 + (chart.width - 82) * 100 / 180, y: chart.y + chart.height * 0.55, width: 0, height: 0}, 900);
      },
      async page => {
        await scrollTo(page, page.getByLabel('Policy comparison'), 70, 900);
        await side(page, 'left', {kicker: 'OrbitGuard', title: '+0.05 m/s instead', body: 'Same fuel. Accepted against every object at every uncertainty level.', top: 330, accent: '#3fae5a'});
        await click(page, page.getByRole('button', {name: 'OrbitGuard', exact: true}), 650);
        await sleep(200);
        await ring(page, page.locator('.policy-table tr.selected'), 2600, 4);
      },
      async page => {
        await scrollTo(page, page.getByLabel('Orbital view'), 70, 900);
        await side(page, 'right', {kicker: 'Result', title: 'Worst encounter 4.8 × 10⁻⁵', body: 'Below the limit for every object, and confirmed by the finer re-check. The dip to C is gone.', top: 560, accent: '#3fae5a'});
        await ring(page, page.locator('.separation'), 3400, 6);
      },
    ]},
  {id: 'validation', app: true, url: `${APP}/#validation`,
    async prepare(page) {
      await page.locator('.policy-bars .bar-segment').first().waitFor({timeout: 60000});
      await page.locator('.ranking-curve .recharts-line').first().waitFor({timeout: 60000});
      await page.evaluate(() => window.scrollTo(0, 0));
      await sleep(600);
    },
    cues: [
      async page => {
        await chapter(page, '03', 'Validation');
        await side(page, 'left', {kicker: 'Evidence', title: 'Three independent checks', body: 'Every number on this page is read from evaluation files produced on LinuxONE.', top: 330});
      },
      async page => {
        const forecasting = section(page, 'Forecasting on held-out ESA data');
        await side(page, 'right', {kicker: 'Check 1 · ESA held-out data', title: 'Published baseline reproduced: 0.694', body: 'Our scoring matches ESA\'s published result, so the evaluation itself is sound.', top: 330});
        await ring(page, forecasting.locator('.section-head p'), 3000, 6);
        await sleep(3400);
        await scrollTo(page, page.locator('.subsection'), 90, 1000);
        await side(page, 'right', {kicker: 'Ranking alerts for review', title: 'Average precision 0.665 → 0.701', body: '95% confidence interval +0.004 to +0.064. It excludes zero.', top: 330});
        await ring(page, page.locator('.compare'), 3000, 6);
        await sleep(3300);
        await scrollTo(page, page.locator('.ranking-curve'), 140, 900);
        await side(page, 'left', {kicker: 'Honest result', title: 'Baseline stays the default forecast', body: 'As a point forecast the learned model is not better, so we do not use it for that.', top: 330, accent: '#e2672f'});
      },
      async page => {
        const nasa = section(page, 'Collision probability against NASA reference cases');
        await scrollTo(page, nasa, 76, 1000);
        await side(page, 'right', {kicker: 'Check 2 · NASA reference cases', title: '3 of 3 matched', body: 'Largest relative error 2.9 × 10⁻⁶, against a tolerance of 10⁻³.', top: 330, accent: '#3fae5a'});
        await ring(page, nasa.locator('table'), 3600, 6);
      },
      async page => {
        await scrollTo(page, page.locator('.policy-bars'), 260, 1000);
        await side(page, 'left', {kicker: 'Check 3 · 50 stress-test scenarios', title: '20 new hazards → 0', body: 'Same mean Δv of 0.0375 m/s. All 10 impossible cases correctly declined.', top: 330, accent: '#3fae5a'});
        await ring(page, page.locator('.policy-bars'), 4000, 8);
        await sleep(4400);
        await scrollTo(page, section(page, 'Speed on this server'), 76, 1000);
        await side(page, 'right', {kicker: 'Speed on LinuxONE', title: '1.7 s per full screening', body: '8.5 ms per forecast. 2.77× faster across three cores.', top: 330});
      },
    ]},
  {id: 'outro', url: scene('outro.html')},
];

// ---------------------------------------------------------------- recorder

async function record(browser, s) {
  const page = await browser.newPage({viewport: {width: 1920, height: 1080}, deviceScaleFactor: 1, colorScheme: 'dark'});
  page.on('pageerror', e => console.warn(`  [${s.id}] page error: ${e.message}`));
  if (s.app) await page.addInitScript({path: `${ROOT}video/overlay.js`});
  if (s.init) await page.addInitScript(s.init[0], s.init[1]);
  cursor = {x: 1700, y: 1150};
  await page.goto(s.url);
  await page.evaluate(() => document.fonts.ready);
  if (s.prepare) await s.prepare(page);
  await sleep(700);
  const dir = `${OUT}frames/${s.id}/`;
  fs.rmSync(dir, {recursive: true, force: true}); fs.mkdirSync(dir, {recursive: true});
  const client = await page.context().newCDPSession(page);
  const frames = [], writes = [];
  let t0 = null;
  client.on('Page.screencastFrame', ({data, metadata, sessionId}) => {
    const arrival = Date.now() / 1000;
    const file = `${dir}${String(frames.length).padStart(5, '0')}.jpg`;
    writes.push(fs.promises.writeFile(file, Buffer.from(data, 'base64')));
    const stamp = Math.abs(metadata.timestamp - arrival) < 1 ? metadata.timestamp : arrival;
    frames.push({file, t: stamp});
    client.send('Page.screencastFrameAck', {sessionId}).catch(() => {});
  });
  await client.send('Page.startScreencast', {format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1});
  t0 = Date.now() / 1000;
  const T = timing[s.id];
  const elapsed = () => Date.now() / 1000 - t0;
  const until = async seconds => {const wait = (seconds - elapsed()) * 1000; if (wait > 0) await sleep(wait);};
  await page.evaluate(() => window.start && window.start());
  const events = T.lines.map((line, i) => ({t: line.start, run: () => s.app ? s.cues?.[i]?.(page) : page.evaluate(k => window.cue && window.cue(k), i)}));
  for (const [t, k] of s.extras || []) events.push({t, run: () => page.evaluate(n => window.cue && window.cue(n), k)});
  events.sort((a, b) => a.t - b.t);
  let chain = Promise.resolve();
  for (const event of events) {
    await until(event.t);
    if (s.app) {await chain; if (elapsed() > event.t + 0.3) console.warn(`  [${s.id}] cue at ${event.t.toFixed(1)} s started ${(elapsed() - event.t).toFixed(1)} s late`);}
    chain = Promise.resolve().then(event.run).catch(e => console.warn(`  [${s.id}] cue failed: ${e.message}`));
  }
  await chain;
  if (elapsed() > T.duration) console.warn(`  [${s.id}] actions overran the scene by ${(elapsed() - T.duration).toFixed(1)} s`);
  await until(T.duration);
  await client.send('Page.stopScreencast');
  await Promise.all(writes);
  fs.writeFileSync(`${dir}frames.json`, JSON.stringify({t0, duration: T.duration, frames: frames.map(f => ({file: f.file, t: f.t - t0}))}));
  console.log(`${s.id.padEnd(11)} ${frames.length} frames, ${T.duration.toFixed(1)} s`);
  await page.close();
}

const only = process.argv.slice(2);
const browser = await chromium.launch({executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, args: ['--use-angle=metal', '--enable-gpu-rasterization', '--force-color-profile=srgb', '--hide-scrollbars']});
try {for (const s of SCENES) if (!only.length || only.includes(s.id)) await record(browser, s);} finally {await browser.close();}
