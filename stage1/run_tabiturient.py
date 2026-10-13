from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'src'))
import common
from tabiturient_parser import collect_tabiturient, discover_tabiturient

demo = '--demo' in sys.argv
sample = '--sample' in sys.argv
folder = Path(__file__).parent/'data'/('demo_v2' if demo else ('sample' if sample else 'full'))
folder.mkdir(parents=True,exist_ok=True)
common.ERROR_DIR = folder
config = dict(start='2018-01-01',end='2026-10-06',output_dir=folder,demo=demo,limit=20 if demo else None,pause=1.5)
if sample:
    config.update(tabit_mode='sample_ids',tabit_sample_size=400)
driver = common.create_driver()
try:
    if '--discover' in sys.argv:
        result = discover_tabiturient(driver,config)
        print('DISCOVERED',len(result))
    else:
        result = collect_tabiturient(driver,config)
        print('DONE',len(result),result['row_type'].value_counts().to_dict() if len(result) else {})
finally:
    driver.quit()
