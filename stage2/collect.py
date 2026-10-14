"""Сбор второго этапа.

Примеры:
    python collect.py --source sites --mode pilot
    python collect.py --source telegram --mode pilot --join
    python collect.py --source vk --mode full
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from common import Http, Store, load_config, load_env, load_registry, new_run_id, windows, write_manifest  # noqa: E402

parser = argparse.ArgumentParser(description='Министерства, Telegram и VK приёмных комиссий')
parser.add_argument('--source', choices=['sites', 'telegram', 'vk', 'all'], default='all')
parser.add_argument('--mode', choices=['pilot', 'full'], default='pilot')
parser.add_argument('--only', nargs='*', help='source_id из docs/sources/source-registry.csv')
parser.add_argument('--join', action='store_true', help='вступать в чаты по приглашению (Telegram)')
parser.add_argument('--output', type=Path, default=None)
args = parser.parse_args()

config, env = load_config(), load_env()
folder = args.output or Path(__file__).parent / 'data' / args.mode
pilot = config['pilot_per_source'] if args.mode == 'pilot' else 0
official, admissions = windows(config, 'official_windows'), windows(config, 'admissions_windows')
selected = lambda rows: [r for r in rows if not args.only or r['source_id'] in args.only]

if args.source in ('sites', 'all'):
    from ministry_sites import collect_edu, collect_minobr, collect_wayback
    run_id, http = new_run_id('sites'), Http(config, env, folder)
    store = Store(folder, 'official_sites')
    wanted = {r['source_id'] for r in selected(load_registry(platform=None, roles=('official',)))}
    if 'state_minpros_site' in wanted:
        collect_edu(http, store, official, run_id, folder, pilot)
    if 'state_minobr_site' in wanted:
        collect_minobr(http, store, official, run_id, folder, pilot, config['minobr_live_from'])
    for archive in config['wayback']:
        if archive['source_id'] in wanted:
            collect_wayback(http, store, official, run_id, folder, archive, pilot, config['minobr_live_from'])
    frame = store.save()
    write_manifest(folder, run_id, dict(source='sites', mode=args.mode, windows=official))
    print(f'Сайты министерств: {len(frame)} строк → {folder / "official_sites.csv"}')

if args.source in ('telegram', 'all'):
    from telegram_mtproto import collect_telegram
    run_id, store = new_run_id('telegram'), Store(folder, 'telegram')
    for role, wins in (('official', official), ('admissions', admissions)):
        sources = selected(load_registry(platform='Telegram', roles=(role,)))
        if sources:
            asyncio.run(collect_telegram(sources, env, store, wins, run_id, folder, config['period'], pilot, args.join))
    frame = store.save()
    write_manifest(folder, run_id, dict(source='telegram', mode=args.mode, join=args.join))
    print(f'Telegram: {len(frame)} строк → {folder / "telegram.csv"}')

if args.source in ('vk', 'all'):
    from vk_api import collect_vk
    run_id, store = new_run_id('vk'), Store(folder, 'vk')
    sources = selected(load_registry(platform='ВКонтакте', roles=('admissions',)))
    frame = collect_vk(sources, env, store, admissions, run_id, folder, config['period'], pilot)
    write_manifest(folder, run_id, dict(source='vk', mode=args.mode))
    print(f'VK: {len(frame)} строк → {folder / "vk.csv"}')
