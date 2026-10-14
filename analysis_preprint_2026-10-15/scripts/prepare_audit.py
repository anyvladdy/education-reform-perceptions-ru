"""Freeze blind AI-to-AI control packages before substantive summary analysis."""
from pathlib import Path
import json,random
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'audit/input_manifest.json').read_text(encoding='utf-8'))
out={}
for i,source in enumerate(['telegram','pikabu','tabiturient']):
    packages=json.loads((ROOT/'packets'/f'{source}_all.json').read_text(encoding='utf-8'))
    eligible=[p for p in packages if p['package'] not in manifest[source]['pilot_ids']]
    sample=random.Random(20261015+i).sample(eligible,min(30,len(eligible)))
    sample.sort(key=lambda p:p['package'])
    out[source]={'seed':20261015+i,'package_ids':[p['package'] for p in sample],
                 'record_ids':[r['id'] for p in sample for r in p['records']],
                 'reason':'AI-only cross-coding diagnostic; not human validation, not evaluation of truth.'}
    for j in range(0,len(sample),5):
        (ROOT/'audit'/f'blind_{source}_{j//5+1:02}.json').write_text(json.dumps(sample[j:j+5],ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'audit/control_selection.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print({s:len(v['record_ids']) for s,v in out.items()})
