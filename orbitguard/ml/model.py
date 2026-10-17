"""Event-level features and frozen model selection with no final-label access."""
from __future__ import annotations
import hashlib, itertools, json, os, platform, time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.model_selection import StratifiedKFold
from threadpoolctl import threadpool_limits
from .data import CUTOFF, digest, load_frames, paths, prepare, read_labels, write_json

SEED=42
HISTORY_FIELDS=['risk','miss_distance','relative_speed','t_sigma_r','t_sigma_t','t_sigma_n','c_sigma_r','c_sigma_t','c_sigma_n']
EXCLUDED={'event_id','mission_id','true_risk','target','label'}

def feature_frame(rows,history=True):
    if rows.empty: raise ValueError('No encounter messages supplied')
    if not {'event_id','time_to_tca','risk'}.issubset(rows.columns): raise ValueError('History needs event_id, time_to_tca and risk')
    times=pd.to_numeric(rows.time_to_tca,errors='coerce'); risks=pd.to_numeric(rows.risk,errors='coerce')
    if not np.isfinite(times).all() or not np.isfinite(risks).all(): raise ValueError('Risk and time_to_tca must be finite numeric values')
    if (times<CUTOFF).any(): raise ValueError('Forecast inputs must be at least 2 days before closest approach')
    if (risks>0).any(): raise ValueError('risk must be log10 probability, at most zero')
    rows=rows.copy(); rows['risk']=risks; rows['time_to_tca']=times
    rows=rows.sort_values(['event_id','time_to_tca'],ascending=[True,False],kind='stable')
    g=rows.groupby('event_id',sort=True)
    latest=g.tail(1).set_index('event_id').sort_index()
    # groupby.last skips missing values, which would accidentally mix messages; tail(1) does not.
    records=[]
    for _,r in latest.iterrows():
        out={}
        for k,v in r.items():
            if k in EXCLUDED or pd.isna(v): continue
            if k=='c_object_type': out[k]=str(v)
            elif isinstance(v,(int,float,np.number)) and np.isfinite(v): out['latest_'+k]=float(np.clip(v,-12,0)) if k=='risk' else float(v)
        records.append(out)
    if history:
        first=g.head(1).set_index('event_id').sort_index()
        counts=g.size(); spans=g.time_to_tca.max()-g.time_to_tca.min()
        for i,eid in enumerate(latest.index):
            records[i]['history_message_count']=int(counts.loc[eid]); records[i]['history_span_days']=float(spans.loc[eid])
        for field in HISTORY_FIELDS:
            if field not in rows: continue
            stats=g[field].agg(['min','max']).reindex(latest.index)
            for i,eid in enumerate(latest.index):
                delta=latest.at[eid,field]-first.at[eid,field]
                vals={'first':first.at[eid,field],'min':stats.at[eid,'min'],'max':stats.at[eid,'max'],'change':delta}
                if field=='risk': vals['trend_per_day']=delta/max(float(spans.loc[eid]),1e-9)
                for name,v in vals.items():
                    if pd.notna(v) and np.isfinite(v): records[i][f'history_{field}_{name}']=float(v)
    return latest.index.to_numpy(),records,latest['risk'].to_numpy(dtype=float)

def clipped(pred):
    p=np.asarray(pred,dtype=float).copy(); p[p<-6]=-6.001; return p

def metrics(y,pred,name='model'):
    y=np.asarray(y,dtype=float); pred=np.asarray(pred,dtype=float)
    if len(y)!=len(pred) or not len(y) or not np.isfinite(y).all() or not np.isfinite(pred).all(): raise ValueError('Metric inputs must be matching finite vectors')
    actual=y>=-6; estimated=pred>=-6
    tp=int((actual&estimated).sum()); fp=int((~actual&estimated).sum()); fn=int((actual&~estimated).sum()); tn=int((~actual&~estimated).sum())
    precision=tp/(tp+fp) if tp+fp else 0.; recall=tp/(tp+fn) if tp+fn else 0.; f2=5*tp/(5*tp+4*fn+fp) if 5*tp+4*fn+fp else 0.
    high_mse=float(np.mean((y[actual]-pred[actual])**2)) if actual.any() else None
    order=np.argsort(-pred,kind='stable')[:max(1,int(np.ceil(len(y)*.1)))]; top_recall=float(actual[order].sum()/actual.sum()) if actual.any() else 0.
    return {'name':name,'challenge_loss':high_mse/f2 if f2 and high_mse is not None else None,'f2':f2,'precision':precision,'recall':recall,'average_precision':float(average_precision_score(actual,pred)) if actual.any() else None,'high_risk_log_rmse':float(np.sqrt(high_mse)) if high_mse is not None else None,'top_10_percent_recall':top_recall,'tp':tp,'fp':fp,'fn':fn,'tn':tn,'event_count':len(y),'high_risk_event_count':int(actual.sum()),'undefined_loss_reason':None if f2 else 'F2 is zero'}

def _xy(train,history=True):
    eligible=train[train.time_to_tca>=CUTOFF]
    ids,features,latest=feature_frame(eligible,history)
    final=train.sort_values('time_to_tca',kind='stable').groupby('event_id').head(1).set_index('event_id')
    keep=np.array([final.at[eid,'time_to_tca']<1 for eid in ids]); ids=ids[keep]; latest=latest[keep]; features=[r for r,k in zip(features,keep) if k]
    y=final.loc[ids,'risk'].to_numpy(dtype=float)
    return ids,features,latest,y

def _estimator(config):
    return HistGradientBoostingRegressor(max_iter=200,learning_rate=.05,early_stopping=False,random_state=SEED,**{k:config[k] for k in ('max_leaf_nodes','min_samples_leaf','l2_regularization')})

def cv_predict(records,latest,y,config):
    out=np.empty(len(y)); target=np.clip(y,-12,0)-np.clip(latest,-12,0)
    folds=StratifiedKFold(n_splits=3,shuffle=True,random_state=SEED)
    for tr,va in folds.split(np.zeros(len(y)),y>=-6):
        vec=DictVectorizer(sparse=False); xtr=vec.fit_transform([records[i] for i in tr]); xva=vec.transform([records[i] for i in va])
        model=_estimator(config)
        model.fit(xtr,target[tr],sample_weight=np.where(y[tr]>=-6,config['high_risk_weight'],1))
        out[va]=model.predict(xva)
    return out

def train_model(root):
    started=time.perf_counter(); base,_=paths(root)
    quality=prepare(root); train,_=load_frames(root); ids,records,latest,y=_xy(train)
    baseline=metrics(y,clipped(latest),'clipped_latest_baseline_cv')
    configs=[dict(zip(['max_leaf_nodes','min_samples_leaf','l2_regularization','high_risk_weight'],x)) for x in itertools.product([7,15],[10,30],[1,10],[1,10])]
    trials=[]; best={'method':'latest_baseline','alpha':0,'config':None,'metrics':baseline}; best_loss=baseline['challenge_loss'] if baseline['challenge_loss'] is not None else float('inf')
    best_correction=None
    with threadpool_limits(limits=1):
        for i,config in enumerate(configs):
            correction=cv_predict(records,latest,y,config)
            for alpha in [.25,.5,1.]:
                score=metrics(y,clipped(np.minimum(latest+alpha*correction,0)))
                row={'config':config,'alpha':alpha,'metrics':score}; trials.append(row)
                loss=score['challenge_loss'] if score['challenge_loss'] is not None else float('inf')
                if score['f2']>=baseline['f2']-.02 and loss<best_loss:
                    best_loss=loss; best={'method':'gradient_boosted_residual','alpha':alpha,'config':config,'metrics':score}; best_correction=correction.copy()
            print(f'CV configuration {i+1}/{len(configs)}; selected loss={best_loss:.6f}',flush=True)
        # Always freeze a learned candidate as well as the selected default, even if baseline wins.
        learned_trials=sorted(trials,key=lambda t:t['metrics']['challenge_loss'] if t['metrics']['challenge_loss'] is not None else float('inf'))
        learned=next((r for r in learned_trials if r['metrics']['f2']>=baseline['f2']-.02),learned_trials[0])
        vec=DictVectorizer(sparse=False); x=vec.fit_transform(records); estimator=_estimator(learned['config'])
        estimator.fit(x,np.clip(y,-12,0)-np.clip(latest,-12,0),sample_weight=np.where(y>=-6,learned['config']['high_risk_weight'],1))
        # History ablation uses the same hyperparameters, only training-fold labels.
        _,latest_records,latest2,y2=_xy(train,history=False)
        ablation_correction=cv_predict(latest_records,latest2,y2,learned['config'])
        ablation=metrics(y2,clipped(np.minimum(latest2+learned['alpha']*ablation_correction,0)),'latest_message_features_only_cv')
    metadata={'name':'ESA residual gradient boosting','selected_method':best['method'],'selected_alpha':best['alpha'],'learned_alpha':learned['alpha'],'hyperparameters':learned['config'],'seed':SEED,'cutoff_days':CUTOFF,'target_max_time_to_tca_days':1,'feature_count':len(vec.feature_names_),'feature_names':vec.feature_names_,'feature_history':True,'risk_floor_for_fitting':-12,'training_event_sha256':hashlib.sha256(','.join(map(str,ids)).encode()).hexdigest(),'data':quality,'sklearn_version':sklearn.__version__,'numpy_version':np.__version__,'platform':platform.platform(),'architecture':platform.machine(),'frozen_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'fit_elapsed_seconds':time.perf_counter()-started,'selection_rule':'Minimum training-event three-fold CV ESA loss with F2 no more than .02 below clipped latest baseline; baseline candidate included.','cv':{'baseline':baseline,'selected':best,'learned':learned,'history_ablation':ablation},'final_test_labels_accessed':False}
    model={'vectorizer':vec,'estimator':estimator,'metadata':metadata}
    temporary_model=base/'model.joblib.partial'
    joblib.dump(model,temporary_model,compress=3)
    os.replace(temporary_model,base/'model.joblib')
    metadata['version']=digest(base/'model.joblib')[:12]; write_json(base/'model_metadata.json',metadata); write_json(base/'cv_trials.json',trials)
    return metadata

def predict(model,records,latest,learned=False):
    meta=model['metadata']
    if not learned and meta['selected_method']=='latest_baseline': return np.asarray(latest)
    with threadpool_limits(limits=1):
        correction=model['estimator'].predict(model['vectorizer'].transform(records))
    alpha=meta['learned_alpha'] if learned else meta['selected_alpha']
    return np.minimum(np.asarray(latest,dtype=float)+alpha*correction,0)

def evaluate(root,bootstrap_repeats=1000):
    base,_=paths(root); model=joblib.load(base/'model.joblib'); metadata=json.loads((base/'model_metadata.json').read_text())
    model_hash=digest(base/'model.joblib'); _,test=load_frames(root); ids,records,latest=feature_frame(test)
    forecasts=predict(model,records,latest); learned_forecasts=predict(model,records,latest,learned=True)
    # This is deliberately the first final-label access, after model artifact is frozen.
    labels=read_labels(root).set_index('event_id')
    if set(ids)!=set(labels.index): raise ValueError('Public input / released label event mismatch')
    y=labels.loc[ids,'true_risk'].to_numpy(dtype=float)
    methods={'latest_known_raw':latest,'clipped_latest_baseline':clipped(latest),'constant_minus_5':np.full(len(y),-5.),'learned_residual_raw':learned_forecasts,'learned_residual_scored':clipped(learned_forecasts),'selected_default_scored':clipped(forecasts)}
    scores=[metrics(y,p,name) for name,p in methods.items()]
    reference=next(s for s in scores if s['name']=='clipped_latest_baseline'); published=.694
    reproduced=reference['challenge_loss'] is not None and abs(reference['challenge_loss']-published)<.005
    rng=np.random.default_rng(SEED); deltas=[]; ap_deltas=[]
    for _ in range(bootstrap_repeats):
        ix=rng.integers(0,len(y),len(y)); a=metrics(y[ix],clipped(latest[ix])); b=metrics(y[ix],clipped(learned_forecasts[ix]))
        if a['challenge_loss'] is not None and b['challenge_loss'] is not None: deltas.append(b['challenge_loss']-a['challenge_loss'])
        if (y[ix]>=-6).any(): ap_deltas.append(float(average_precision_score(y[ix]>=-6,learned_forecasts[ix])-average_precision_score(y[ix]>=-6,latest[ix])))
    actual=y>=-6; prec,rec,thresholds=precision_recall_curve(actual,learned_forecasts)
    # Compact curve, preserving endpoints; the full predictions remain downloadable.
    curve_ids=np.unique(np.linspace(0,len(prec)-1,min(120,len(prec)),dtype=int))
    curve=[{'recall':float(rec[i]),'precision':float(prec[i])} for i in curve_ids]
    frame=pd.DataFrame({'event_id':ids.astype(str),'true_log10_pc':y,'latest_log10_pc':latest,'forecast_log10_pc':forecasts,'learned_log10_pc':learned_forecasts}); frame.to_csv(base/'test_predictions.csv',index=False)
    lat=[]
    one=records[:1]; one_latest=latest[:1]
    for _ in range(20): predict(model,one,one_latest,learned=True)
    for _ in range(100):
        t=time.perf_counter(); predict(model,one,one_latest,learned=True); lat.append((time.perf_counter()-t)*1000)
    evidence={'status':'ready','source':'ESA historical dataset; final released labels','model':metadata,'dataset':{**metadata['data'],'test_events':len(ids),'high_risk_test_events':int(actual.sum()),'labels_column':'true_risk','label_use':'Final evaluation only; frozen model SHA256 recorded before label access.'},'metrics':scores,'validation':{'published_clipped_latest_loss_rounded':published,'reproduced_clipped_latest_loss':reference['challenge_loss'],'published_baseline_reproduced':reproduced,'absolute_reproduction_tolerance':.005,'namespaced_event_overlap':0,'raw_numeric_event_id_overlap':metadata['data'].get('raw_numeric_id_overlap'),'event_id_scope':'Source files independently number events; train:<id>/test:<id> namespaces preserve official split. Exact duplicate CDMs checked separately.','all_forecast_inputs_at_least_2_days':True,'frozen_model_sha256_before_labels':model_hash,'model_sha256_after_evaluation':digest(base/'model.joblib'),'paired_bootstrap':{'repeats':bootstrap_repeats,'valid_repeats':len(deltas),'quantity':'learned scored loss minus clipped latest loss; negative favours learned','ci95':np.quantile(deltas,[.025,.975]).tolist() if deltas else None}},'ranking_comparison':{'quantity':'Average precision on raw un-clipped predictions; benchmark clipping must not be used for ranking comparisons.','latest_average_precision':float(average_precision_score(actual,latest)),'learned_average_precision':float(average_precision_score(actual,learned_forecasts)),'paired_bootstrap_ap_difference_ci95':np.quantile(ap_deltas,[.025,.975]).tolist() if ap_deltas else None,'interpretation':'Positive AP difference favours learned ranking; a confidence interval crossing zero does not establish a reliable improvement.'},'precision_recall_curve':curve,'runtime':{'platform':platform.platform(),'architecture':platform.machine(),'inference_warmup':20,'inference_measured_requests':100,'learned_core_predict_p50_ms':float(np.percentile(lat,50)),'learned_core_predict_p95_ms':float(np.percentile(lat,95)),'note':'Core model prediction only; API end-to-end latency measured separately.'},'limitations':['Forecasts a later ESA risk estimate, not an observed collision.','Historical anonymised ESA encounters are distinct from synthetic manoeuvre scenarios.','Final labels are public retrospective labels; no operational live validation.','Risk values are log10 probabilities; score clipping is benchmark-only.','High-risk events are scarce in the eligible training split.','ESA hand-picked the challenge splits to over-represent high-risk encounters; metrics do not estimate real-world encounter prevalence.']}
    if evidence['validation']['model_sha256_after_evaluation']!=model_hash:
        raise ValueError('Frozen model changed during evaluation; no evidence published')
    evidence['prediction_source_sha256']=digest(Path(__file__))
    write_json(base/'evidence.json',evidence)
    if not reproduced: print('WARNING: published baseline not reproduced within declared tolerance; investigate before comparison claims.',flush=True)
    return evidence
