"""Общие функции второго этапа: настройки, реестр, окна, периоды, запись и журналы."""

import csv
import hashlib
import json
import os
import re
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

MOSCOW = timezone(timedelta(hours=3))
ROOT = Path(__file__).resolve().parents[1]
PARSER_VERSION = 'stage2-0.1'
REGISTRY = ROOT.parent / 'docs' / 'sources' / 'source-registry.csv'

# Единая таблица сообщений по схеме methodology 4.3 (`messages` + поля происхождения).
COLUMNS = [
    'source_id', 'record_id', 'row_type', 'thread_id', 'parent_id', 'published_at',
    'date_precision', 'period_v1', 'window_id', 'title', 'text_raw', 'url', 'tags',
    'sender_kind', 'sender_hash', 'sender_rank', 'reply_count', 'collected_at',
    'run_id', 'parser_version', 'extraction',
]
PERIODS_V1 = [  # METHODOLOGY.md, часть 2, раздел 4
    ('pre_covid', '2018-01-01', '2020-03-10'),
    ('covid', '2020-03-11', '2022-02-23'),
    ('svo_early', '2022-02-24', '2023-12-31'),
    ('svo_late', '2024-01-01', '2026-10-06'),
]
MONTHS = {m: i + 1 for i, m in enumerate(
    'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())}


def load_config(path=None):
    return json.loads(Path(path or ROOT / 'config.json').read_text(encoding='utf-8'))


def load_env(path=None):
    """Простой разбор .env без зависимостей; значения окружения имеют приоритет."""
    values = {}
    path = Path(path or ROOT / '.env')
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k in values or k.startswith(('TG_', 'VK_', 'HASH_', 'RU_CA'))})
    return values


def load_registry(platform=None, roles=('official', 'admissions'), statuses=('основной',), path=REGISTRY):
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    return [r for r in rows if r['corpus_role'] in roles and r['status'] in statuses
            and (platform is None or r['platform'] == platform)]


def windows(config, kind):
    """Окна сбора из config.json: [{'id','start','end'}], без пересечений и внутри периода."""
    result = []
    for year in config[kind]['years']:
        start = f"{year}-{config[kind]['start_md']}"
        end = min(f"{year}-{config[kind]['end_md']}", config['period']['end'])
        if start <= end and start >= config['period']['start']:
            result.append(dict(id=f'{kind}_{year}', start=start, end=end))
    return result


def window_of(day, wins):
    day = str(day)[:10]
    return next((w['id'] for w in wins if w['start'] <= day <= w['end']), None)


def period_v1(day):
    day = str(day)[:10]
    return next((name for name, start, end in PERIODS_V1 if start <= day <= end), None)


def to_moscow(value):
    """datetime/ISO → ISO-строка по Москве; дата без времени остаётся датой."""
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        if re.fullmatch(r'\d{4}-\d\d-\d\d', value):
            return value
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=MOSCOW)
    return value.astimezone(MOSCOW).isoformat(timespec='seconds')


def parse_ru_date(text):
    """«14 октября 2026, 18:46», «14.10.2026», «2026-10-14» → (ISO, точность)."""
    text = ' '.join(str(text).split()).lower()
    m = re.search(r'(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(\d{4})(?:\D{0,3}(\d{1,2}):(\d\d))?', text)
    if m:
        d = datetime(int(m[3]), MONTHS[m[2]], int(m[1]), int(m[4] or 0), int(m[5] or 0), tzinfo=MOSCOW)
        return (d.isoformat(timespec='seconds'), 'minute') if m[4] else (d.date().isoformat(), 'day')
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d\d))?', text)
    if m:
        d = datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4] or 0), int(m[5] or 0), tzinfo=MOSCOW)
        return (d.isoformat(timespec='seconds'), 'minute') if m[4] else (d.date().isoformat(), 'day')
    m = re.search(r'(\d{4})-(\d\d)-(\d\d)', text)
    if m:
        return f'{m[1]}-{m[2]}-{m[3]}', 'day'
    return None, 'unknown'


def sender_hash(sender_id, salt):
    """Псевдоним автора: участников можно различать, но не узнать по таблице."""
    if sender_id is None:
        return None
    if not salt:
        raise ValueError('Задайте HASH_SALT в stage2/.env: без соли псевдонимы обратимы перебором')
    return hashlib.sha256(f'{salt}:{sender_id}'.encode()).hexdigest()[:16]


def now():
    return datetime.now(MOSCOW).isoformat(timespec='seconds')


def new_run_id(source):
    return f"{source}-{datetime.now(MOSCOW).strftime('%Y%m%dT%H%M%S')}"


class Store:
    """CSV с контрольной точкой: повторный запуск продолжает работу без дублей."""

    def __init__(self, folder, name):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.state_path = self.folder / f'{name}_checkpoint.json'
        self.state = {'records': {}, 'done': []}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding='utf-8'))

    def has(self, key):
        return key in self.state['records']

    def add(self, row):
        key = f"{row['source_id']}|{row['row_type']}|{row['record_id']}"
        self.state['records'].setdefault(key, {c: row.get(c) for c in COLUMNS})

    def done(self, task):
        return task in self.state['done']

    def mark(self, task):
        if task not in self.state['done']:
            self.state['done'].append(task)
        self.save()

    def save(self):
        temporary = self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.state_path)
        frame = pd.DataFrame(self.state['records'].values(), columns=COLUMNS)
        if not frame.empty:
            frame = frame.sort_values(['source_id', 'published_at', 'record_id'], na_position='last')
        frame.to_csv(self.folder / f'{self.name}.csv', index=False, encoding='utf-8-sig')
        return frame


def note(folder, source, url, reason, kind='error'):
    """Журнал: техническая ошибка, недоступность и пропуск различаются полем kind."""
    path = Path(folder) / 'collection_log.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open('a', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        if not exists:
            writer.writerow(['logged_at', 'kind', 'source', 'url', 'reason'])
        writer.writerow([now(), kind, source, url, reason])


def write_manifest(folder, run_id, settings):
    """Происхождение запуска: параметры, версия парсера и SHA-256 таблиц."""
    folder = Path(folder)
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(folder.glob('*.csv'))}
    manifest = dict(run_id=run_id, finished_at=now(), parser_version=PARSER_VERSION,
                    settings=settings, sha256=files)
    (folder / f'manifest_{run_id}.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


class Http:
    """requests с паузой, повторами и явной политикой TLS для сайтов с российским УЦ.

    Если сертификат сайта выдан российским удостоверяющим центром, укажите путь
    к корневому сертификату в RU_CA_BUNDLE. Без него проверка для хостов из
    config['insecure_tls_hosts'] отключается с записью в журнал; для остальных — нет.
    """

    def __init__(self, config, env, folder):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = config.get('user_agent', 'Mozilla/5.0 (research crawler)')
        self.pause = config.get('pause_seconds', 1.5)
        self.insecure = set(config.get('insecure_tls_hosts', []))
        self.bundle = env.get('RU_CA_BUNDLE')
        self.folder = folder
        self.warned = set()
        self.last = 0.0

    def get(self, address, params=None, **extra):
        params = {**(params or {}), **extra}
        host = urlparse(address).hostname or ''
        verify = True
        if host in self.insecure:
            verify = self.bundle or False
            if verify is False and host not in self.warned:
                self.warned.add(host)
                note(self.folder, 'http', address, 'Проверка TLS отключена: задайте RU_CA_BUNDLE', kind='warning')
        for attempt in range(4):
            wait = self.pause - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    response = self.session.get(address, params=params or None, timeout=40, verify=verify)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                return response
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
