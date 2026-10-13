"""Долгий сбор с возобновлением: python collect.py --source telegram --mode archive."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'src'))
import common
from telegram_parser import collect_telegram, collect_telegram_sample
from pikabu_parser import collect_pikabu, collect_pikabu_sample
from tabiturient_parser import collect_tabiturient

parser = argparse.ArgumentParser(description='Три публичных источника, Selenium + pandas, без API')
parser.add_argument('--source',choices=['all','telegram','pikabu','tabiturient'],default='all')
parser.add_argument('--mode',choices=['sample','archive'],default='sample')
parser.add_argument('--output',type=Path,default=None)
args = parser.parse_args()
folder = args.output or Path('data')/args.mode
folder.mkdir(parents=True,exist_ok=True)
common.ERROR_DIR = folder
config = dict(start='2018-01-01',end='2026-10-06',terms=common.TERMS,output_dir=folder,
              demo=False,limit=None,pause=3)
if args.mode == 'sample':
    config.update(tabit_mode='sample_ids',tabit_sample_size=400,matcher_version='matcher_v1')
    collectors = dict(telegram=collect_telegram_sample,pikabu=collect_pikabu_sample,tabiturient=collect_tabiturient)
else:
    config.update(telegram_mode='feed',pikabu_max_pages=None)
    collectors = dict(telegram=collect_telegram,pikabu=collect_pikabu,tabiturient=collect_tabiturient)
for source,collector in collectors.items():
    if args.source not in ['all',source]:
        continue
    driver = common.create_driver()
    try:
        frame = collector(driver,config)
    finally:
        driver.quit()
    print(f'{source}: сохранено {len(frame)} строк в {folder}',flush=True)
