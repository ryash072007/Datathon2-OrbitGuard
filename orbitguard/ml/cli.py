"""Reproducible data/ML commands delegated by OrbitGuard's root CLI."""
import argparse,json,os
from pathlib import Path
from .data import fetch,prepare
from .model import train_model,evaluate

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('command',choices=['fetch-data','prepare-data','train','evaluate']); p.add_argument('--root',default=os.getenv('ORBITGUARD_ROOT','.')); p.add_argument('--bootstrap-repeats',type=int,default=1000); args=p.parse_args(argv)
    if args.bootstrap_repeats<1: p.error('--bootstrap-repeats must be positive')
    root=Path(args.root).resolve()
    if args.command=='fetch-data': result=fetch(root)
    elif args.command=='prepare-data': result=prepare(root)
    elif args.command=='train': result=train_model(root)
    else: result=evaluate(root,args.bootstrap_repeats)
    if args.command=='evaluate': print(json.dumps({'status':result['status'],'metrics':result['metrics'],'validation':result['validation']},indent=2))
    elif args.command=='train': print(json.dumps({k:v for k,v in result.items() if k!='feature_names'},indent=2))
    else: print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
