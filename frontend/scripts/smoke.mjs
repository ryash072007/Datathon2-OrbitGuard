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
const replayRequests=[];
page.on('pageerror',error=>errors.push(error.message));
const points = [{t_seconds:0,x_m:-500,y_m:50,z_m:0},{t_seconds:100,x_m:0,y_m:20,z_m:0},{t_seconds:200,x_m:500,y_m:60,z_m:0}];
const trajectories = [{object_id:'A',name:'TEST controlled A',points},{object_id:'B',name:'TEST object B',points:points.map(p=>({...p,y_m:p.y_m+300}))}];
const policy={accepted:true,delta_v_mps:0.1,burn_time_seconds:300,primary_pc:1e-8,worst_secondary_pc:1e-9,worst_pc:1e-8,reason:'TEST FIXTURE ONLY — computed outcomes are not represented by this fixture.'};
if(fixtures)await page.route('**/api/**',route=>{
  const url = new URL(route.request().url()); let body;
  if(url.pathname==='/api/health')body={status:'ready',architecture:'TEST-ONLY',platform:'Browser fixture'};
  else if(url.pathname==='/api/events')body={events:[{event_id:'TEST-FIXTURE',latest_log10_pc:-7,time_to_tca_days:2,message_count:3}]};
  else if(url.pathname.startsWith('/api/events/'))body={event_id:'TEST-FIXTURE',history:[{time_to_tca:4,risk:-8},{time_to_tca:3,risk:-7.5},{time_to_tca:2,risk:-7}],forecast:{baseline_log10_pc:-7,forecast_log10_pc:-6.5,model_name:'TEST FIXTURE'},reference:{true_log10_pc:-6.2}};
  else if(url.pathname==='/api/forecast')body={baseline_log10_pc:-7.5,forecast_log10_pc:-7,model_name:'TEST FIXTURE'};
  else if(url.pathname==='/api/replay/update'){const payload=route.request().postDataJSON();replayRequests.push(payload.message_count);body={update_id:`fixture-${payload.message_count}`,message_count:payload.message_count,source:'historical_replay',processing_ms:12,received_at:'2026-10-17T00:00:00Z',alert:{state:payload.message_count===3?'high_risk':'monitor',previous_state:'monitor',changed:payload.message_count===3},action:'Operator review required; no automatic manoeuvre.',forecast:{baseline_log10_pc:-7.5,forecast_log10_pc:-7,model_name:'TEST FIXTURE'}};}
  else if(url.pathname==='/api/scenarios')body={scenarios:[{scenario_id:'test-fixture',name:'TEST FIXTURE ONLY',source:'synthetic'},{scenario_id:'test-slow',name:'TEST slow scenario',source:'synthetic'}]};
  else if(url.pathname.startsWith('/api/scenarios/'))body={scenario_id:'test-fixture',name:'TEST FIXTURE ONLY',description:'Browser test fixture. Not a result.',source:'synthetic',horizon_seconds:10800,trajectories,encounter_views:{primary:{object_id:'B',trajectories}},assumptions:['TEST FIXTURE ONLY']};
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
  await page.getByRole('button',{name:'How it works',exact:true}).click();
  await page.getByRole('heading',{name:'Understand the risk. Check the whole orbit.',exact:true}).waitFor();
  await page.getByText('Forecast a later risk estimate',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Download evidence JSON',exact:true}).waitFor();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button',{name:'Download evidence JSON',exact:true}).click();
  assert.equal((await downloadPromise).suggestedFilename(),'orbitguard-evidence.json');
  await page.screenshot({path:`test-results/${mode}-overview.png`,fullPage:true});
  await page.getByRole('link',{name:'Explore encounters',exact:true}).click();
  await page.getByRole('heading',{name:'Encounters',exact:true}).waitFor();
  await page.getByRole('heading',{name:/^Encounter #/}).waitFor({timeout:30000});
  await page.getByText('Latest reported value').first().waitFor({timeout:30000});
  if(fixtures){
    await page.getByRole('button',{name:'#TEST-FIXTURE'}).waitFor();
    const replay=page.getByRole('slider',{name:'Historical message replay position'});
    await replay.focus();await replay.press('Home');
    await page.getByText('Message 1 of 3',{exact:true}).waitFor();
    await replay.press('ArrowRight');
    await page.getByText('Message 2 of 3',{exact:true}).waitFor();
    await page.getByRole('region',{name:'Update processing timeline'}).getByText('Message 2',{exact:true}).waitFor();
    assert.equal(replayRequests.at(-1),2,'Replay asks the server to process only the selected prefix');
    await page.getByText('12 ms server processing',{exact:false}).first().waitFor();
    await replay.press('End');await page.getByText(/^High-risk alert/).waitFor();
    replayRequests.length=0;
    await page.getByRole('button',{name:'Replay messages one by one'}).click();
    await page.getByRole('button',{name:'Pause replay'}).waitFor();
    await page.getByRole('button',{name:'Replay messages one by one'}).waitFor();
    assert.deepEqual(replayRequests,[1,2,3],'Playback processes every update in order');
    await page.route('**/api/replay/update',async route=>{
      if(route.request().postDataJSON().message_count!==2)return route.fallback();
      await new Promise(resolve=>setTimeout(resolve,800));
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({message_count:2,processing_ms:1,alert:{state:'high_risk'},action:'STALE replay marker',forecast:{forecast_log10_pc:-1}})});
    });
    const delayed=page.waitForRequest(request=>request.url().endsWith('/api/replay/update')&&request.postDataJSON().message_count===2);
    await replay.focus();await replay.press('Home');await replay.press('ArrowRight');await delayed;
    await replay.press('Home');await page.waitForTimeout(1100);
    assert.equal(await page.getByText('STALE replay marker',{exact:true}).count(),0,'Superseded replay results must not overwrite the selected prefix');
    await page.unroute('**/api/replay/update');
    await page.route('**/api/replay/update',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'TEST replay unavailable'}})}));
    await page.getByRole('button',{name:'Replay messages one by one'}).click();
    await page.getByText('TEST replay unavailable',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Replay messages one by one'}).waitFor();
    await page.unroute('**/api/replay/update');
    await page.getByRole('button',{name:'Retry',exact:true}).click();
    await page.getByRole('region',{name:'Update processing timeline'}).getByText('Message 1',{exact:true}).waitFor();
  } else {
    await page.getByRole('slider',{name:'Historical message replay position'}).press('Home');
    await page.getByRole('region',{name:'Update processing timeline'}).waitFor({timeout:30000});
  }
  // Tooltips must open on hover and explain the term.
  await page.locator('.tip-anchor').first().hover();await page.getByRole('tooltip').waitFor();
  await page.mouse.move(0,0);
  if(!fixtures){await page.locator('.encounters-visuals .globe canvas').waitFor({timeout:30000});await page.locator('.population .recharts-scatter-symbol').first().waitFor({timeout:30000});await page.waitForTimeout(800);}
  await page.screenshot({path:`test-results/${mode}-monitor.png`,fullPage:true});
  await page.getByRole('button',{name:'Manoeuvre planning',exact:true}).click();
  await page.getByRole('heading',{name:'Manoeuvre planning',exact:true}).waitFor();
  if(fixtures){
    const geometry=page.getByRole('region',{name:'Encounter geometry',exact:true});
    await geometry.getByText('No manoeuvre',{exact:true}).waitFor();
    await geometry.getByText('Satellite A (no burn)',{exact:true}).waitFor();
    assert.equal(await geometry.getByText('Satellite A (after burn)',{exact:true}).count(),0,'Pre-screen geometry must not claim a burn');
  }
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
  if(fixtures){
    await page.route('**/api/events?*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({events:[]})}));
    await page.getByRole('button',{name:'Encounters',exact:true}).click();
    await page.getByText('No encounters available',{exact:true}).waitFor();
    await page.getByText('Select an encounter',{exact:true}).waitFor();
    assert.equal(await page.getByText('Loading encounter',{exact:true}).count(),0,'Empty list does not leave a detail spinner');
    await page.route('**/api/evidence',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'TEST evidence unavailable'}})}));
    await page.getByRole('button',{name:'How it works',exact:true}).click();
    await page.getByRole('alert').getByText('TEST evidence unavailable').waitFor();
    assert.equal(await page.getByRole('button',{name:'Download evidence JSON'}).isDisabled(),true);
    await page.route('**/api/evidence',async route=>{await new Promise(resolve=>setTimeout(resolve,350));return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ml:{status:'missing'},physics:{},runtime:{}})});});
    await page.getByRole('button',{name:'Retry',exact:true}).click();
    await page.getByRole('status').getByText('Loading evidence summary').waitFor();
    await page.getByText('Forecast evaluation unavailable.').waitFor();
    await page.getByRole('link',{name:'Open manoeuvre planning',exact:true}).click();
    await page.route('**/api/jobs/*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job_id:'test-fixture-job',status:'failed',error:{message:'TEST screening failure'}})}));
    await page.getByRole('button',{name:'Screen manoeuvres',exact:true}).click();
    await page.getByRole('alert').getByText('TEST screening failure').waitFor();
    await page.getByRole('link',{name:'Check server job status'}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Screen manoeuvres',exact:true}).isEnabled(),true);
    await page.route('**/api/jobs/*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({job_id:'test-fixture-job',status:'completed',result:{recommendation:null,policies:{orbitguard:{accepted:false,abstained:true,reason:'TEST no acceptable burn'}},trajectories,encounter_views:{primary:{object_id:'B',trajectories}}}})}));
    await page.getByRole('button',{name:'Screen manoeuvres',exact:true}).click();
    await page.getByRole('button',{name:'Run again',exact:true}).waitFor();
    assert.equal(await page.getByText('No accepted manoeuvre for this policy',{exact:true}).count(),2,'Abstention must not display original trajectories as a recommended burn');
    await page.getByRole('button',{name:'No manoeuvre',exact:true}).click();
    await page.getByRole('region',{name:'Encounter geometry',exact:true}).getByText('Satellite A (no burn)',{exact:true}).waitFor();
    await page.route('**/api/scenarios/test-slow',async route=>{await new Promise(resolve=>setTimeout(resolve,900));return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({scenario_id:'test-slow',description:'TEST slow response',source:'synthetic'})});});
    const scenarioSelect=page.getByRole('combobox');
    await scenarioSelect.selectOption('test-slow');
    assert.equal(await page.getByRole('button',{name:'Screen manoeuvres',exact:true}).isDisabled(),true,'Prior scenario cannot be screened while new detail loads');
    assert.equal(await page.getByText('Browser test fixture. Not a result.',{exact:true}).count(),0,'Prior scenario detail clears immediately');
    await scenarioSelect.selectOption('test-fixture');
    await page.getByText('Browser test fixture. Not a result.',{exact:true}).waitFor();
    await page.waitForTimeout(1000);
    assert.equal(await page.getByText('TEST slow response',{exact:true}).count(),0,'Late superseded scenario response is ignored');
    const auditMethod={recall:.5,precision:.5,fn:1,log10_mae:2,log10_rmse:3,recall_ci95:[.1,.9],precision_ci95:[.1,.9],always_low_risk_accuracy:.9};
    await page.route('**/api/evidence',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ml:{accuracy_audit:{status:'ready',methods:{latest_baseline:auditMethod,high_risk_shrinkage:auditMethod},shrinkage:{default_changed:false,cv_baseline:{challenge_loss:.8},cv_challenger:{challenge_loss:.79},cv_loss_difference:{ci95:[-.1,.1]}},shrinkage_loss_difference:{ci95:[-.05,.03]},baseline_missed_event_ids:['TEST-FIXTURE']}},physics:{},runtime:{}})}));
    await page.getByRole('button',{name:'Validation',exact:true}).click();
    await page.getByRole('heading',{name:'How accurate are the forecasts?',exact:true}).waitFor();
    await page.getByText(/This is not a new blind test/).waitFor();
    await page.getByText(/The deployed default remains unchanged/).waitFor();
    await page.getByText('Inspect 1 baseline missed alerts',{exact:true}).click();
    const missed=page.getByRole('link',{name:'Encounter #TEST-FIXTURE',exact:true});
    assert.equal(await missed.getAttribute('href'),'?event=TEST-FIXTURE#encounters');
    const triage={metrics:{average_precision:.4,top_10_percent_recall:.5,recall:.8,precision:.3,fn:2,fp:20},baseline:{average_precision:.6,top_10_percent_recall:.6,recall:.5,precision:.5,fn:5,fp:5},model:{threshold:.2},validation:{threshold_selected_on_training_only:true},paired_bootstrap:{ci95:[-.3,-.1]}};
    const setTriage=()=>page.route('**/api/evidence',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ml:{triage_evaluation:triage},physics:{},runtime:{}})}));
    await setTriage();
    await page.getByRole('button',{name:'Reload',exact:true}).click();
    await page.getByRole('heading',{name:'Experimental alert triage',exact:true}).waitFor();
    await page.getByText(/The interval favours latest-value ranking/).waitFor();
    await page.getByText(/not collision probability/).waitFor();
    triage.paired_bootstrap.ci95=[-.1,.2];
    await setTriage();await page.getByRole('button',{name:'Reload',exact:true}).click();
    await page.getByText(/The interval crosses zero; a ranking improvement is not established/).waitFor();
    triage.paired_bootstrap.ci95=[.1,.2];
    await setTriage();await page.getByRole('button',{name:'Reload',exact:true}).click();
    await page.getByText(/The interval favours triage ranking/).waitFor();
    await page.route('**/api/evidence',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ml:{triage_evaluation:{status:'stale',message:'TEST stale artifact'}},physics:{},runtime:{}})}));
    await page.getByRole('button',{name:'Reload',exact:true}).click();
    await page.getByText('Accuracy audit pending',{exact:true}).waitFor();
    assert.equal(await page.getByRole('heading',{name:'Experimental alert triage',exact:true}).count(),0,'Stale triage artifacts without metrics must not render or throw');
    const guardMethod={recall:.8,precision:.5,fn:2,fp:3,challenge_loss:.7};
    await page.route('**/api/evidence',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ml:{guard_evaluation:{methods:{latest_baseline:guardMethod,residual_guard:guardMethod,simple_threshold:guardMethod},additional_high_risk_events_detected:2,additional_alert_event_ids:['TEST-GUARD'],paired_bootstrap:{recall_difference_ci95:[0,.1],loss_difference_ci95:[-.1,.1]}}},physics:{},runtime:{}})}));
    await page.getByRole('button',{name:'Reload',exact:true}).click();
    await page.getByRole('heading',{name:'Catching additional missed alerts',exact:true}).waitFor();
    await page.getByText(/does not replace the default risk forecast or command a manoeuvre/).waitFor();
    await page.getByText('Inspect all 1 additional review alerts',{exact:true}).click();
    assert.equal(await page.getByRole('link',{name:'Encounter #TEST-GUARD',exact:true}).getAttribute('href'),'?event=TEST-GUARD#encounters');
    await page.route('**/api/events/*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({event_id:'TEST-FIXTURE',history:[{time_to_tca:2,risk:-7}],forecast:{baseline_log10_pc:-7,learned_forecast_log10_pc:-5,supplemental_review:{status:'experimental',additional_review:true}}})}));
    await page.getByRole('button',{name:'Encounters',exact:true}).click();
    await page.goto(`${baseURL}/?event=TEST-FIXTURE#encounters`);
    await page.getByText('Additional review advised (experimental).',{exact:true}).waitFor();
    await page.getByText('Default forecast',{exact:true}).waitFor();
  }
  if(!fixtures){
    const evidence=await (await page.request.get(`${baseURL}/api/evidence`)).json();
    const added=evidence.ml?.guard_evaluation?.additional_alert_event_ids;
    if(Array.isArray(added)&&added.length){
      await page.goto(`${baseURL}/#validation`);
      await page.getByRole('heading',{name:'Catching additional missed alerts',exact:true}).waitFor();
      for(const eventId of added){
        await page.goto(`${baseURL}/?event=${encodeURIComponent(eventId)}#encounters`);
        await page.getByText('Additional review advised (experimental).',{exact:true}).waitFor();
        await page.getByText('Default forecast',{exact:true}).waitFor();
      }
      await page.screenshot({path:'test-results/live-review-alert.png',fullPage:true});
    }
  }
  assert.deepEqual(errors,[],'No browser runtime exceptions');
  console.log(`PASS: ${fixtures?'isolated fixture':'live API'} navigation, evidence download, server replay, ${fixtures?'ordered playback, replay failure/retry and stale-response checks, screening success/failure, empty list, evidence retry/loading, ':''}mobile layout, and browser runtime checks.`);
} finally {await browser.close();}
