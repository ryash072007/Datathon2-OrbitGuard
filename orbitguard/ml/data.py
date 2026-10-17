"""Official ESA data acquisition; labels are isolated until final evaluation."""
from __future__ import annotations
import hashlib, json, os, struct, subprocess, tempfile, time, zipfile, zlib
from pathlib import Path
import numpy as np
import pandas as pd

ESA_BASE='https://kelvins.esa.int/media/public/competitions/collision-avoidance-challenge/'
ZENODO='https://zenodo.org/api/records/4463683/files/Collision%20Avoidance%20Challenge%20-%20Dataset.zip/content'
CUTOFF=2.0

def paths(root):
    base=Path(root)/'artifacts/ml'; (base/'data').mkdir(parents=True,exist_ok=True); return base,base/'data'

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def write_json(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix=path.name+'.',suffix='.partial',delete=False) as f:
        f.write(json.dumps(obj,indent=2,allow_nan=False)+'\n'); temp=f.name
    os.replace(temp,path)

def crc(path):
    c=0
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): c=zlib.crc32(b,c)
    return c&0xffffffff

def fetch(root):
    base,data=paths(root)
    sources=[]
    for name,expected_size,expected_crc in [('train_data.zip',87718091,0xaa9c3d81),('test_data.csv',35303060,0xd0184cc0)]:
        p=data/name
        if not p.exists() or p.stat().st_size!=expected_size:
            subprocess.run(['/usr/bin/curl' if Path('/usr/bin/curl').exists() else 'curl','--fail','--location','--retry','3','--continue-at','-','--connect-timeout','20','--max-time','1200','--output',str(p),ESA_BASE+name],check=True)
        if p.stat().st_size!=expected_size or crc(p)!=expected_crc: raise ValueError(f'Official archive CRC/size mismatch: {name}')
        sources.append({'file':name,'source_url':ESA_BASE+name,'bytes':p.stat().st_size,'sha256':digest(p),'official_archive_crc32':f'{expected_crc:08x}','crc_verified':True})
    with zipfile.ZipFile(data/'train_data.zip') as z:
        if z.testzip(): raise ValueError('Training ZIP CRC failed')
        if z.namelist()!=['train_data.csv']: raise ValueError('Unexpected training archive structure')
        z.extract('train_data.csv',data)
    # Keep this member compressed. Its payload is opened only by evaluate after model freeze.
    member=data/'test_labels_member.bin'
    if not member.exists() or member.stat().st_size!=1347128:
        subprocess.run(['/usr/bin/curl' if Path('/usr/bin/curl').exists() else 'curl','--fail','--location','--retry','3','--range','13659544-15006671','--max-time','180','--output',str(member),ZENODO],check=True)
    if member.stat().st_size!=1347128: raise ValueError('Label-member range response has unexpected size')
    sources.append({'file':member.name,'source_url':ZENODO,'range':'13659544-15006671','sha256':digest(member),'payload_opened':False})
    report={'source':'ESA Collision Avoidance Challenge / Zenodo record 4463683','licence':'CC BY 4.0','retrieved_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'full_archive_md5_reference':'d19dc8875229f2f6893253c38adddc87','full_archive_md5_verified':False,'verification':'Selected members checked against official ZIP central-directory CRC32; SHA256 records local provenance. Full 221 MB archive not downloaded.','files':sources}
    write_json(base/'provenance.json',report); return report

def read_labels(root):
    base,_=paths(root)
    if not (base/'model.joblib').exists() or not (base/'model_metadata.json').exists(): raise ValueError('Freeze the model before opening final test labels')
    return unseal_labels(root)

def read_labels_after_freeze(root,frozen):
    # Same sealed member, for other frozen artifacts (the decision layer): refuse until the artifact exists.
    if not Path(frozen).exists(): raise ValueError(f'Freeze {Path(frozen).name} before opening final test labels')
    return unseal_labels(root)

def unseal_labels(root):
    _,data=paths(root)
    import io
    raw=(data/'test_labels_member.bin').read_bytes()
    h=struct.unpack_from('<4s5H3I2H',raw,0)
    if h[0]!=b'PK\x03\x04' or h[3]!=8: raise ValueError('Invalid released-label ZIP member')
    start=30+h[-2]+h[-1]; payload=zlib.decompress(raw[start:start+h[7]],-15)
    if zlib.crc32(payload)&0xffffffff!=0x2b46d216: raise ValueError('Released-label CRC mismatch')
    labels=pd.read_csv(io.BytesIO(payload),usecols=['event_id','true_risk'])
    if labels.event_id.duplicated().any(): raise ValueError('Duplicate test label event')
    return labels

def load_frames(root):
    _,data=paths(root)
    return pd.read_csv(data/'train_data.csv'),pd.read_csv(data/'test_data.csv')

def prepare(root):
    base,data=paths(root); train,test=load_frames(root)
    raw_id_overlap=set(train.event_id)&set(test.event_id)
    # ESA numbers IDs independently inside each dataset; they are not global IDs.
    shared=[c for c in train.columns if c!='event_id']
    train_hash=pd.util.hash_pandas_object(train[shared],index=False)
    test_hash=pd.util.hash_pandas_object(test[shared],index=False)
    duplicate_rows=int(test_hash.isin(train_hash).sum())
    if duplicate_rows: raise ValueError('Exact CDM overlap across official splits')
    inputs=train[train.time_to_tca>=CUTOFF]
    last=train.sort_values('time_to_tca').groupby('event_id',sort=False).first()
    eligible=sorted(set(inputs.event_id)&set(last.index[last.time_to_tca<1]))
    report={'train_rows':len(train),'test_rows':len(test),'original_train_events':int(train.event_id.nunique()),'train_events':len(eligible),'excluded_train_events':int(train.event_id.nunique()-len(eligible)),'test_events':int(test.event_id.nunique()),'train_high_risk_events':int((last.loc[eligible,'risk']>=-6).sum()),'namespaced_event_overlap':0,'raw_numeric_id_overlap':len(raw_id_overlap),'id_namespace':'train:<id> and test:<id>; source files number IDs independently','exact_duplicate_cdms_across_splits':duplicate_rows,'cutoff_days':CUTOFF,'target_max_time_to_tca_days':1,'train_missing_fraction':float(train.isna().to_numpy().mean()),'test_all_inputs_meet_cutoff':bool((test.time_to_tca>=CUTOFF).all()),'train_sha256':digest(data/'train_data.csv'),'test_sha256':digest(data/'test_data.csv')}
    if not report['test_all_inputs_meet_cutoff']: raise ValueError('Unexpected future messages in official test inputs')
    write_json(base/'data_quality.json',report); return report
