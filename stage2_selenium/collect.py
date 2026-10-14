"""Сбор без ключей и входа в аккаунты: сайты министерств и публичные каналы Telegram.

Примеры:
    python collect.py --source sites --mode pilot
    python collect.py --source telegram --mode pilot
    python collect.py --source all --mode full
"""
import argparse
import csv
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'src'))
sys.path.insert(1, str(HERE.parent / 'stage2' / 'src'))  # общие модули: схема, окна, сайты министерств
from common import REGISTRY, Http, Store, load_config, new_run_id, windows, write_manifest  # noqa: E402

parser = argparse.ArgumentParser(description='Сайты министерств и публичные каналы Telegram без ключей')
parser.add_argument('--source', choices=['sites', 'telegram', 'all'], default='all')
parser.add_argument('--mode', choices=['pilot', 'full'], default='pilot')
parser.add_argument('--only', nargs='*', help='source_id из docs/sources/source-registry.csv')
parser.add_argument('--output', type=Path, default=None)
args = parser.parse_args()

config = load_config(HERE / 'config.json')
folder = args.output or HERE / 'data' / args.mode
pilot = config['pilot_per_source'] if args.mode == 'pilot' else 0
official, admissions = windows(config, 'official_windows'), windows(config, 'admissions_windows')
registry = {r['source_id']: r for r in csv.DictReader(open(REGISTRY, encoding='utf-8'))}
wanted = lambda ids: [i for i in ids if not args.only or i in args.only]


def local_salt():
    """Соль псевдонимов создаётся один раз и хранится локально: ключей вводить не нужно."""
    path = HERE / '.secrets' / 'hash_salt'
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding='utf-8')
    return path.read_text(encoding='utf-8').strip()


if args.source in ('sites', 'all'):
    from ministry_sites import collect_edu, collect_minobr, collect_wayback
    run_id, http, store = new_run_id('sites'), Http(config, {}, folder), Store(folder, 'official_sites')
    ids = wanted(['state_minpros_site', 'state_minobr_site', 'state_minobr_wayback'])
    if 'state_minpros_site' in ids:
        collect_edu(http, store, official, run_id, folder, pilot)
    if 'state_minobr_site' in ids:
        collect_minobr(http, store, official, run_id, folder, pilot, config['minobr_live_from'])
    for archive in config['wayback']:
        if archive['source_id'] in ids:
            collect_wayback(http, store, official, run_id, folder, archive, pilot, config['minobr_live_from'])
    frame = store.save()
    write_manifest(folder, run_id, dict(source='sites', mode=args.mode, windows=official))
    print(f'Сайты министерств: {len(frame)} строк → {folder / "official_sites.csv"}')

if args.source in ('telegram', 'all'):
    from selenium import webdriver
    from telegram_web import collect_channel
    from common import note

    run_id, http, store = new_run_id('telegram_web'), Http(config, {}, folder), Store(folder, 'telegram_web')
    salt = local_salt()
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1200,1000')
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    try:
        for source_id in wanted(config['telegram_channels']):
            src = registry[source_id]
            if store.done(f'tgweb|{source_id}') and not pilot:
                continue
            wins = official if src['corpus_role'] == 'official' else admissions
            try:
                collect_channel(http, driver, src, store, wins, run_id, folder, salt, config['period'], pilot)
            except Exception as error:  # noqa: BLE001 — один канал не останавливает остальные
                note(folder, source_id, src['url'], f'{type(error).__name__}: {error}')
            print(f'  {source_id}: готово', flush=True)
    finally:
        driver.quit()
    frame = store.save()
    write_manifest(folder, run_id, dict(source='telegram_web', mode=args.mode))
    print(f'Telegram (публичные каналы): {len(frame)} строк → {folder / "telegram_web.csv"}')
