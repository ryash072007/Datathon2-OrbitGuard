// Browser regression checks. Optional fixtures exist only in this test process;
// the production app always reads the connected API.
import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const baseURL = process.env.ORBITGUARD_BASE_URL || 'http://127.0.0.1:5173';
const fixtures = process.env.ORBITGUARD_UI_FIXTURES === '1';
const executablePath = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const browser = await chromium.launch({executablePath,headless:true});
const page = await browser.newPage({viewport:{width:1500,height:1060}});
const errors=[];
let latestForecastHistory=null;
page.on('pageerror',error=>errors.push(error.message));
const points = [{t_seconds:0,x_m:-500,y_m:50,z_m:0},{t_seconds:100,x_m:0,y_m:20,z_m:0},{t_seconds:200,x_m:500,y_m:60,z_m:0}];
const trajectories = [{object_id:'A',name:'TEST controlled A',points},{object_id:'B',name:'TEST object B',points:points.map(p=>({...p,y_m:p.y_m+300}))}];
const policy={accepted:true,delta_v_mps:0.1,burn_time_seconds:300,primary_pc:1e-8,worst_secondary_pc:1e-9,worst_pc:1e-8,reason:'TEST FIXTURE ONLY — computed outcomes are not represented by this fixture.'};
if(fixtures)await page.route('**/api/**',route=>{
  const url = new URL(route.request().url()); let body;
  if(url.pathname==='/api/health')body={status:'ready',architecture:'TEST-ONLY',platform:'Browser fixture'};
  else if(url.pathname==='/api/events')body={events:[{event_id:'TEST-FIXTURE',latest_log10_pc:-7,time_to_tca_days:2,message_count:3}]};
  else if(url.pathname.startsWith('/api/events/'))body={event_id:'TEST-FIXTURE',history:[{time_to_tca:4,risk:-8},{time_to_tca:3,risk:-7.5},{time_to_tca:2,risk:-7}],forecast:{baseline_log10_pc:-7,forecast_log10_pc:-6.5,model_name:'TEST FIXTURE'},reference:{true_log10_pc:-6.2}};
  else if(url.pathname==='/api/forecast'){latestForecastHistory=route.request().postDataJSON().history;body={baseline_log10_pc:-7.5,forecast_log10_pc:-7,model_name:'TEST FIXTURE'};}
  else if(url.pathname==='/api/scenarios')body={scenarios:[{scenario_id:'test-fixture',name:'TEST FIXTURE ONLY',source:'synthetic'}]};
  else if(url.pathname.startsWith('/api/scenarios/'))body={scenario_id:'test-fixture',name:'TEST FIXTURE ONLY',description:'Browser test fixture. Not a result.',source:'synthetic',horizon_seconds:10800,trajectories,assumptions:['TEST FIXTURE ONLY']};
  else if(url.pathname==='/api/screen')body={job_id:'test-fixture-job',status:'queued'};
  else if(url.pathname.startsWith('/api/jobs/'))body={job_id:'test-fixture-job',status:'completed',result:{source:'synthetic',candidates_evaluated:37,elapsed_ms:2000,recommendation:policy,policies:{no_action:{...policy,accepted:false},pair_only:{...policy,accepted:false},orbitguard:policy},trajectories}};
  else if(url.pathname==='/api/evidence')body={ml:{status:'missing'},physics:{status:'missing'},runtime:{architecture:'TEST-ONLY'}};
  else body={};
  return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
});
try {
  await page.goto(baseURL);
  await mkdir('test-results',{recursive:true});
  const mode=fixtures?'fixture':'live';
  await page.getByRole('heading',{name:'Encounters',exact:true}).waitFor();
  await page.getByRole('heading',{name:/^Encounter #/}).waitFor({timeout:30000});
  await page.getByText('Latest reported value').first().waitFor({timeout:30000});
  if(fixtures){await page.getByRole('button',{name:'#TEST-FIXTURE'}).waitFor();const replay=page.getByRole('slider',{name:'Historical message replay position'});await replay.focus();await replay.press('Home');await replay.press('ArrowRight');await page.waitForTimeout(500);assert.equal(latestForecastHistory?.length,2,'Replay sends only the messages available at the selected point');}
  // Tooltips must open on hover and explain the term.
  await page.locator('.tip-anchor').first().hover();await page.getByRole('tooltip').waitFor();
  await page.mouse.move(0,0);
  if(!fixtures){await page.locator('.encounters-visuals .globe canvas').waitFor({timeout:30000});await page.locator('.population .recharts-scatter-symbol').first().waitFor({timeout:30000});await page.waitForTimeout(800);}
  await page.screenshot({path:`test-results/${mode}-monitor.png`,fullPage:true});
  await page.getByRole('button',{name:'Manoeuvre planning',exact:true}).click();
  await page.getByRole('heading',{name:'Manoeuvre planning',exact:true}).waitFor();
  if(fixtures||process.env.ORBITGUARD_SMOKE_SCREEN==='1'){
    await page.getByRole('button',{name:'Screen manoeuvres',exact:true}).click();
    await page.getByRole('button',{name:'Run again',exact:true}).waitFor({timeout:120000});
    await page.getByRole('link',{name:'Download screening result'}).waitFor();
    const pair=page.getByRole('button',{name:/^Avoid .* only$/});await pair.click();
    assert.equal(await pair.getAttribute('aria-pressed'),'true');
    if(!fixtures){await page.locator('[aria-label="Orbital view"] .globe canvas').waitFor({timeout:30000});await page.getByRole('button',{name:/^Closest approach with C \(T\+/}).click();await page.getByRole('button',{name:'Closest approach with C',exact:true}).click();await page.getByText('Miss distance to C').waitFor();await page.waitForTimeout(900);}
  }
  await page.screenshot({path:`test-results/${mode}-desktop.png`,fullPage:true});
  await page.getByRole('button',{name:'Validation',exact:true}).click();
  await page.getByRole('heading',{name:'Validation',exact:true}).waitFor();
  // Live mode must render real artifacts, not stop at the loading state.
  if(!fixtures){for(const name of ['Forecasting on held-out ESA data','Collision probability against NASA reference cases','Speed on this server'])await page.getByRole('heading',{name}).waitFor({timeout:30000});await page.getByRole('cell',{name:'Omitron circular'}).waitFor();await page.locator('.policy-bars .bar-segment').first().waitFor();await page.locator('.ranking-curve .recharts-line').first().waitFor();}
  else await page.getByText('Evaluation results not available').waitFor();
  await page.screenshot({path:`test-results/${mode}-evidence.png`,fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'Manoeuvre planning',exact:true}).click();
  await page.screenshot({path:`test-results/${mode}-mobile.png`,fullPage:true});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Page must not overflow viewport horizontally');
  assert.deepEqual(errors,[],'No browser runtime exceptions');
  console.log(`PASS: ${fixtures?'isolated fixture':'live API'} navigation, ${fixtures?'screening interaction, ':''}mobile layout, and browser runtime checks.`);
} finally {await browser.close();}
