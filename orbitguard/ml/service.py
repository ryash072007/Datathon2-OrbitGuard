"""Read-only forecasting service; never reads private labels or trains models."""
from __future__ import annotations
import json, time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from .model import feature_frame,predict

class MLService:
    def __init__(self,root):
        self.root=Path(root); self.base=self.root/'artifacts/ml'; self._model=None; self._metadata=None; self._events=None; self._predictions=None

    def _load_model(self):
        if self._model is None:
            if not (self.base/'model.joblib').exists(): raise FileNotFoundError('Model not trained; run train first')
            self._model=joblib.load(self.base/'model.joblib'); self._metadata=json.loads((self.base/'model_metadata.json').read_text())
        return self._model

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
        return {'event_id':str(ids[0]),'baseline_log10_pc':float(latest[0]),'forecast_log10_pc':float(pred[0]),'reported_log10_pc':float(latest[0]),'learned_forecast_log10_pc':float(challenger[0]),'learned_model_name':'gradient_boosted_residual','model_name':model['metadata']['selected_method'],'model_version':self._metadata['version'],'cutoff_days':2,'elapsed_ms':(time.perf_counter()-start)*1000,'warnings':warnings,'source':'ESA historical dataset','score_clipping_applied':False}

    def evidence(self):
        p=self.base/'evidence.json'
        if not p.exists(): return {'status':'missing','message':'No held-out evaluation artifact. Run fetch-data, prepare-data, train, evaluate.','model_ready':(self.base/'model.joblib').exists()}
        result=json.loads(p.read_text())
        curves=self.ranking_curves()
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
