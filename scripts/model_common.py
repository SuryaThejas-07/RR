from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.runtime/python'))
import numpy as np
import pandas as pd
CFG=json.loads((ROOT/'config.yaml').read_text(encoding='utf-8-sig'))
PRO=ROOT/'data/processed'
OUT=ROOT/CFG['paths'].get('model_outputs','outputs')
OUT.mkdir(exist_ok=True)

def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2,default=lambda x:x.item() if hasattr(x,'item') else str(x),allow_nan=False)+'\n',encoding='utf-8')

def csv(df,path):
    df.to_csv(path,index=False,lineterminator='\n')

def gate(checks,path):
    dump(path,checks)
    failed=[k for k,v in checks.items() if not v]
    if failed:
        raise AssertionError('STOP: failed checks: '+', '.join(failed))

def update_plan(text):
    with (ROOT/'IMPLEMENTATION_PLAN.md').open('a',encoding='utf-8') as stream:
        stream.write('\n'+text+'\n')
