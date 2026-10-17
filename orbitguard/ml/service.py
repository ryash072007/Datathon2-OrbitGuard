"""Read-only forecasting service; never reads private labels or trains models."""
from __future__ import annotations
import json, time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from .model import feature_frame,predict
from .data import digest

class MLService:
    def __init__(self,root):
        self.root=Path(root); self.base=self.root/'artifacts/ml'; self._model=None; self._metadata=None; self._events=None; self._predictions=None; self._decision=None; self._snap=None

    def _decision_layer(self, rows):
        # Act / Wait / Monitor from the decision layer (rules + calibrated P(high) + quantile interval).
        # Shown beside the validated forecast; it does not replace it or drive manoeuvre screening.
        path=self.base/'decision.joblib'
        if not path.exists(): return {'status':'missing','message':'Decision layer not trained; run orbitguard decision-fit.'}
        if self._decision is None: self._decision=joblib.load(path)
        from orbitguard.decision.decision import decide
        try:
            d=decide(rows,self._decision)
        except (KeyError,ValueError,TypeError) as exc:
            return {'status':'unavailable','message':f'The decision layer needs the full ESA CDM schema ({type(exc).__name__}: {exc}).'}
        return {'status':'ready','action':d.action,'p_high':d.p_high,'predicted_log10_pc':d.predicted_risk,
                'interval_log10_pc':list(d.interval),'interval_nominal':0.8,'reasons':list(d.reasons),
                'thresholds':{'act':self._decision['t_act'],'wait':self._decision['t_wait']},'chosen':self._decision['chosen']}

    def _attach_second_opinion(self, decision, rows):
        # Snap ML tree ensemble (zDNN on Telum when present) as a second P(high). Never changes the action.
        meta_path=self.root/'artifacts/zai/snapml_metadata.json'; model_path=self.root/'artifacts/zai/snapml_bmc.pmml'
        if not (meta_path.exists() and model_path.exists()): return decision
        from orbitguard.zai import snap
        if self._snap is None:
            try: self._snap=(snap.load_best_scorer(model_path),json.loads(meta_path.read_text()))
            except RuntimeError as exc: self._snap=exc
        if isinstance(self._snap,Exception):
            decision['second_opinion']={'status':'unavailable','message':str(self._snap)}; return decision
        scorer,meta=self._snap
        try:
            from orbitguard.decision.decision import build_table
            u=rows[rows['time_to_tca']>=2]; tab=build_table(u.assign(event_id=0))
            t0=time.perf_counter(); p=float(scorer.predict_proba(snap.featurize(tab,meta['train_medians']))[0]); ms=(time.perf_counter()-t0)*1000
        except (KeyError,ValueError,TypeError) as exc:
            decision['second_opinion']={'status':'unavailable','message':f'Needs the full ESA CDM schema ({type(exc).__name__}: {exc})'}; return decision
        so={'p_high':p,'backend':scorer.backend,'latency_ms':ms,'agrees':None}
        main_p=decision.get('p_high')
        if main_p is not None:
            so['agrees']=bool((p>=0.5)==(main_p>=0.5) or abs(p-main_p)<0.25)
            if not so['agrees'] and isinstance(decision.get('reasons'),list):
                decision['reasons'].append(f'Snap ML second opinion disagrees (p={p:.2f}); review manually')
        decision['second_opinion']=so
        return decision

    def _load_model(self):
        if self._model is None:
            if not (self.base/'model.joblib').exists(): raise FileNotFoundError('Model not trained; run train first')
            self._model=joblib.load(self.base/'model.joblib'); self._metadata=json.loads((self.base/'model_metadata.json').read_text())
        return self._model

    def _supplemental_review(self, latest, learned):
        from . import guard
        policy_path=self.base/'guard_policy.json'
        if not policy_path.exists(): return None
        policy=json.loads(policy_path.read_text())
        model_path=self.base/'model.joblib'
        if (not model_path.exists() or digest(model_path)!=policy.get('baseline_model_sha256')
                or digest(Path(guard.__file__))!=policy.get('guard_source_sha256')
                or digest(Path(__file__).with_name('model.py'))!=policy.get('prediction_source_sha256')):
            return {'status':'stale','message':'Retrain the supplemental review policy for the current model.'}
        candidate=float(guard.guard_predictions([latest],[learned],policy)[0])
        return {'status':'experimental','additional_review':bool(latest < -6 and candidate >= -6),
                'candidate_log10_pc':candidate,'threshold':policy['threshold'],
                'message':'Experimental review alert only; the default forecast and manoeuvre planner are unchanged.'}

    def _load_events(self):
        if self._events is None:
            p=self.base/'data/test_data.csv'
            if not p.exists(): raise FileNotFoundError('Historical ESA inputs missing; run fetch-data first')
            self._events=pd.read_csv(p); self._events['event_id']=self._events.event_id.astype(str)
        return self._events

    def _load_predictions(self):
        if self._predictions is None:
            p=self.base/'test_predictions.csv'
            self._predictions=pd.read_csv(p,dtype={'event_id':str}).set_index('event_id') if p.exists() else pd.DataFrame()
        return self._predictions

    def list_events(self,limit=100):
        if not isinstance(limit,int) or not 1<=limit<=500: raise ValueError('limit must be an integer from 1 to 500')
        rows=self._load_events(); preds=self._load_predictions()
        latest=rows.sort_values('time_to_tca').groupby('event_id',sort=False).head(1).copy(); counts=rows.groupby('event_id').size()
        # Fixed ranking uses only available latest risk, not final labels.
        latest=latest.sort_values('risk',ascending=False).head(limit); out=[]
        for _,r in latest.iterrows():
            d={'event_id':str(r.event_id),'latest_log10_pc':float(r.risk),'time_to_tca_days':float(r.time_to_tca),'message_count':int(counts.loc[r.event_id]),'source':'ESA historical dataset'}
            if not preds.empty and r.event_id in preds.index: d['forecast_log10_pc']=float(preds.loc[r.event_id,'forecast_log10_pc']); d['learned_forecast_log10_pc']=float(preds.loc[r.event_id,'learned_log10_pc'])
            out.append(d)
        return out

    def get_event(self,event_id):
        event_id=str(event_id); rows=self._load_events(); selected=rows[rows.event_id==event_id].sort_values('time_to_tca',ascending=False)
        if selected.empty: raise KeyError(event_id)
        history=json.loads(selected.to_json(orient='records')); preds=self._load_predictions()
        result={'event_id':event_id,'source':'ESA historical dataset','cutoff_days':2,'history':history,'messages':history,'forecast':self.forecast(history),'reference':None}
        if not preds.empty and event_id in preds.index:
            result['reference']={'true_log10_pc':float(preds.loc[event_id,'true_log10_pc']),'evaluation_only':True,'label':'Later ESA reported risk estimate; reference available retrospectively'}
        return result

    def replay_update(self, event_id, message_count):
        started = time.perf_counter()
        received_at = datetime.now(timezone.utc).isoformat()
        rows = self._load_events()
        selected = rows[rows.event_id == str(event_id)].sort_values('time_to_tca', ascending=False, kind='stable')
        if selected.empty:
            raise KeyError(event_id)
        if type(message_count) is not int or not 1 <= message_count <= min(len(selected), 1000):
            raise ValueError('message_count must be an integer within the available history (maximum 1000)')
        history = json.loads(selected.head(message_count).to_json(orient='records'))
        forecast = self.forecast(history)

        def alert_state(result):
            if result['forecast_log10_pc'] >= -6:
                return 'high_risk'
            if (result.get('supplemental_review') or {}).get('additional_review'):
                return 'additional_review'
            return 'monitor'

        state = alert_state(forecast)
        previous = alert_state(self.forecast(history[:-1])) if message_count > 1 else None
        identity = json.dumps({'history': history, 'forecast': {
            key: value for key, value in forecast.items() if key not in ('elapsed_ms', 'stage_ms')
        }}, sort_keys=True, allow_nan=False)
        return {
            'update_id': hashlib.sha256(identity.encode()).hexdigest(),
            'event_id': str(event_id), 'source': 'historical_replay',
            'message_count': message_count, 'total_messages': len(selected),
            'message_time_to_tca_days': history[-1]['time_to_tca'],
            'received_at': received_at, 'completed_at': datetime.now(timezone.utc).isoformat(),
            'processing_ms': (time.perf_counter() - started) * 1000,
            'forecast': forecast,
            'alert': {'state': state, 'previous_state': previous, 'changed': previous is not None and state != previous},
            'action': ('Continue monitoring; this is not a safety clearance.' if state == 'monitor'
                       else 'Operator review required; no automatic manoeuvre.'),
            'scope': 'Replayed ESA messages, not a live feed. Synthetic planning is a separate demonstration.',
        }

    def forecast(self,history):
        start=time.perf_counter()
        if not isinstance(history,list) or not history or any(not isinstance(r,dict) for r in history): raise ValueError('history must be a nonempty array of CDM objects')
        if len(history)>1000: raise ValueError('At most 1000 CDM messages per forecast')
        # Prohibit target columns rather than silently accepting evaluation payloads.
        if any({'true_risk','true_log10_pc','label','target'}&set(r) for r in history): raise ValueError('Evaluation labels must not be supplied as forecast inputs')
        rows=pd.DataFrame(history)
        if 'event_id' not in rows or rows.event_id.nunique(dropna=False)!=1 or rows.event_id.isna().any(): raise ValueError('History must contain exactly one event_id')
        for field in ('time_to_tca','risk'):
            if field not in rows or any(isinstance(v,bool) for v in rows[field]): raise ValueError(f'{field} must be numeric')
        ids,records,latest=feature_frame(rows); model=self._load_model(); pred=predict(model,records,latest); challenger=predict(model,records,latest,learned=True)
        warnings=['Forecast estimates a later reported collision probability, not whether an actual collision occurs.']
        numeric_count=sum(k.startswith('latest_') for k in records[0])
        if numeric_count<20: warnings.append('Sparse input features: supply the full ESA CDM schema for benchmark-comparable predictions.')
        if model['metadata']['selected_method']=='latest_baseline': warnings.append('Cross-validation selected the latest-risk baseline; learned challenger is shown in Evidence.')
        supplemental=self._supplemental_review(float(latest[0]),float(challenger[0]))
        t_dec=time.perf_counter(); decision=self._decision_layer(rows); decision_ms=(time.perf_counter()-t_dec)*1000
        decision=self._attach_second_opinion(decision,rows)
        return {'decision':decision,'event_id':str(ids[0]),'baseline_log10_pc':float(latest[0]),'forecast_log10_pc':float(pred[0]),'reported_log10_pc':float(latest[0]),'learned_forecast_log10_pc':float(challenger[0]),'learned_model_name':'gradient_boosted_residual','model_name':model['metadata']['selected_method'],'model_version':self._metadata['version'],'cutoff_days':2,'elapsed_ms':(time.perf_counter()-start)*1000,'stage_ms':{'decision':decision_ms,'second_opinion':(decision.get('second_opinion') or {}).get('latency_ms')},'warnings':warnings,'source':'ESA historical dataset','score_clipping_applied':False,'supplemental_review':supplemental}

    def evidence(self):
        p=self.base/'evidence.json'
        if not p.exists(): return {'status':'missing','message':'No held-out evaluation artifact. Run fetch-data, prepare-data, train, evaluate.','model_ready':(self.base/'model.joblib').exists()}
        result=json.loads(p.read_text())
        current_model=self.base/'model.joblib'
        recorded_hash=result.get('validation',{}).get('model_sha256_after_evaluation')
        prediction_path=Path(__file__).with_name('model.py')
        recorded_source=result.get('prediction_source_sha256')
        if ((recorded_hash and (not current_model.exists() or recorded_hash!=digest(current_model)))
                or (recorded_source and recorded_source!=digest(prediction_path))):
            return {'status':'stale','message':'The model or prediction code changed. Run evaluate again before quoting its metrics.','model_ready':current_model.exists()}
        audit_path=self.base/'accuracy_audit.json'
        if audit_path.exists():
            audit=json.loads(audit_path.read_text())
            current_hash=digest(self.base/'model.joblib') if (self.base/'model.joblib').exists() else None
            prediction_hash=digest(Path(__file__).with_name('model.py'))
            if (audit.get('fingerprints',{}).get('model_after')==current_hash
                    and audit.get('fingerprints',{}).get('prediction_source_sha256')==prediction_hash):
                result['accuracy_audit']=audit
            else:
                result['accuracy_audit']={'status':'stale','message':'Run audit-accuracy for the current frozen model.'}
        triage_path=self.base/'triage_evidence.json'
        if triage_path.exists():
            triage=json.loads(triage_path.read_text())
            triage_model=self.base/'triage.joblib'
            if (triage_model.exists()
                    and triage.get('validation',{}).get('model_sha256_after_evaluation')==digest(triage_model)):
                result['triage_evaluation']=triage
            else:
                result['triage_evaluation']={'status':'stale','message':'Run train-triage and evaluate-triage for the current artifact.'}
        decision_path=self.base/'decision_evidence.json'
        if decision_path.exists():
            dec=json.loads(decision_path.read_text())
            art=self.base/'decision.joblib'
            if art.exists() and dec.get('fingerprints',{}).get('decision_sha256_after_evaluation')==digest(art):
                result['decision_evaluation']=dec
            else:
                result['decision_evaluation']={'status':'stale','message':'Run decision-eval for the current decision artefact.'}
        curves=self.ranking_curves()
        guard_path=self.base/'guard_evidence.json'
        policy_path=self.base/'guard_policy.json'
        if guard_path.exists() and policy_path.exists():
            guard=json.loads(guard_path.read_text())
            fingerprints=guard.get('fingerprints',{})
            if (fingerprints.get('policy_after')==digest(policy_path)
                    and current_model.exists() and fingerprints.get('base_model')==digest(current_model)
                    and guard.get('policy',{}).get('guard_source_sha256')==digest(Path(__file__).with_name('guard.py'))):
                result['guard_evaluation']=guard
        if curves: result['ranking_curves']=curves
        return result

    def ranking_curves(self,points=120):
        # Precision-recall curves for both rankings, from the frozen per-event predictions written by evaluate.
        from sklearn.metrics import precision_recall_curve
        preds=self._load_predictions()
        if preds.empty or 'true_log10_pc' not in preds: return None
        actual=(preds.true_log10_pc>=-6).to_numpy()
        if not actual.any(): return None
        out={}
        for name,column in (('latest','latest_log10_pc'),('learned','learned_log10_pc')):
            precision,recall,_=precision_recall_curve(actual,preds[column].to_numpy())
            keep=np.unique(np.linspace(0,len(recall)-1,min(points,len(recall))).round().astype(int))
            out[name]=[{'recall':float(recall[i]),'precision':float(precision[i])} for i in keep]
        return out

    def overview(self):
        # Latest message of every held-out encounter, as compact columns for the population chart.
        rows=self._load_events()
        latest=rows.sort_values('time_to_tca').groupby('event_id',sort=False).head(1)
        fields=['event_id','risk','t_h_per','t_h_apo','t_j2k_inc','c_h_per','c_h_apo','c_j2k_inc','c_object_type','miss_distance','relative_speed']
        latest=latest[[f for f in fields if f in latest]]
        columns={}
        for f in latest.columns:
            values=latest[f]
            if f in ('event_id','c_object_type'): columns[f]=[str(v) for v in values.fillna('UNKNOWN')]
            else: columns[f]=[None if pd.isna(v) else round(float(v),3) for v in values]
        return {'source':'ESA historical dataset (test inputs, latest message per encounter)','count':len(latest),'columns':columns}
