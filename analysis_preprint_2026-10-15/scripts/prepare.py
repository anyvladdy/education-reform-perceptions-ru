"""Prepare immutable-source metadata and pseudonymized context packets for AI coding."""
from pathlib import Path
import csv, json, hashlib, re, random, collections, sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
SOURCE = PROJECT / 'outputs/01a11318-2071-7052-80fa-6b378dc037f6/stage1'
for folder in ['data', 'packets', 'annotations', 'audit', 'tables', 'figures', 'report', 'private']:
    (ROOT/folder).mkdir(parents=True, exist_ok=True)

def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def anon(text):
    text = re.sub(r'https?://\S+|www\.\S+', '[ССЫЛКА]', text, flags=re.I)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', '[EMAIL]', text)
    text = re.sub(r'(?<!\w)@[\w.]+', '[АККАУНТ]', text)
    text = re.sub(r'(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[ -]*\d{2}[ -]*\d{2}(?!\d)', '[ТЕЛЕФОН]', text)
    text = re.sub(r'(?i)(меня зовут|моё имя|мое имя)\s+[А-ЯЁA-Z][а-яёa-z]+', r'\1 [ИМЯ]', text)
    # Remove multiword personal names/initials conservatively; institutions are retained elsewhere.
    text = re.sub(r'\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|ична)\b', '[ФИО]', text)
    text = re.sub(r'\b[А-ЯЁ]\.[ ]?[А-ЯЁ]\.[ ]?[А-ЯЁ][а-яё]+\b', '[ФИО]', text)
    return text.strip()

def period(date):
    if date < '2020-03-11': return 'P1'
    if date < '2022-02-24': return 'P2'
    if date < '2024-01-01': return 'P3'
    return 'P4'

allrows, mapping, manifest, packets = [], [], {}, {}
for source, prefix in [('telegram','TG'),('pikabu','PK'),('tabiturient','TB')]:
    path = SOURCE/f'{source}.csv'
    manifest[source] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    with path.open(encoding='utf-8-sig', newline='') as f: raw=list(csv.DictReader(f))
    raw.sort(key=lambda x:(x['date_local'], x['record_id']))
    group_key = 'question_id' if source=='tabiturient' else 'post_id'
    def group_value(r):
        return (r.get('channel',''), r[group_key]) if source=='telegram' else r[group_key]
    root_ids = {}
    for i,r in enumerate(raw,1):
        sid=f'{prefix}{i:04d}'
        if r['row_type'] in ['post','question']: root_ids[group_value(r)]=sid
    sr=[]
    for i,r in enumerate(raw,1):
        sid=f'{prefix}{i:04d}'
        text = anon(r.get('text',''))
        title = anon(r.get('title',''))
        content = f'{title}\n{text}'.strip() if title and r['row_type']=='post' else text
        row=dict(id=sid, source=source, row_type=r['row_type'], date=r['date_local'],
                 period=period(r['date_local']), year=r['year'],
                 package=root_ids.get(group_value(r),sid), channel=r.get('channel',''),
                 author_type=r.get('author_type',''), organization=r.get('organization',''),
                 selection_method=r.get('selection_method',''), sample_windows=r.get('sample_windows',''),
                 discovery_method=r.get('discovery_method',''),
                 has_text=bool(text), text_chars=len(content), text=content,
                 content_hash=hashlib.sha256(re.sub(r'\s+',' ',content).lower().encode()).hexdigest() if content else '',
                 screening_only=r.get('focus_candidate',''))
        sr.append(row)
        mapping.append({'id':sid,'source':source,'record_id':r['record_id'],'url':r['url']})
    allrows+=sr
    grouped=collections.defaultdict(list)
    for r in sr: grouped[r['package']].append(r)
    ps=[]
    for pid,rows in grouped.items():
        rows.sort(key=lambda r: (r['row_type'] not in ['post','question'],r['id']))
        ps.append({'package':pid,'records':[{k:r[k] for k in ['id','row_type','date','channel','author_type','organization','text']} for r in rows]})
    packets[source]=ps
    dump(ROOT/'packets'/f'{source}_all.json', ps)
    # 8 diverse development packages selected deterministically across chronological extent.
    indices=sorted(set(round(i*(len(ps)-1)/7) for i in range(8)))
    pilot=[ps[i] for i in indices]
    dump(ROOT/'packets'/f'{source}_pilot.json',pilot)
    batches=[]; cur=[]; nchar=0
    for p in ps:
        size=sum(len(r['text']) for r in p['records'])
        if cur and (nchar+size>18000 or len(cur)>=10):
            batches.append(cur);cur=[];nchar=0
        cur.append(p);nchar+=size
    if cur: batches.append(cur)
    for i,b in enumerate(batches,1): dump(ROOT/'packets'/f'{source}_{i:03}.json',b)
    manifest[source].update(rows=len(sr),packages=len(ps),batches=len(batches),text_chars=sum(r['text_chars'] for r in sr),pilot_ids=[p['package'] for p in pilot])
dump(ROOT/'data'/'corpus.json',allrows)
dump(ROOT/'private'/'source_mapping.json',mapping)
dump(ROOT/'audit'/'input_manifest.json',manifest)
dump(ROOT/'audit'/'preparation_notes.json',{
    'date':'2026-10-15','timezone':'Europe/Moscow','raw_files_modified':False,
    'pseudonymization':'Автоматически удалены URL, email, аккаунты, телефоны и некоторые конструкции ФИО. Автоматическая процедура не гарантирует полной анонимности; в публичном отчёте используются только перефразы.',
    'periods':{'P1':'2018-01-01—2020-03-10','P2':'2020-03-11—2022-02-23','P3':'2022-02-24—2023-12-31','P4':'2024-01-01—2026-10-06'},
    'human_validation':'not_performed; deferred by user to main article',
    'annotation_model':'gpt-6-luna','reasoning_effort':'medium','mode':'tool-based agent semantic reading',
    'pilot':'8 systematic chronological development packages per corpus; AI-only, not methodological human pilot',
    'sampling':'Frozen collected snapshot; no new source collection.'})
print(json.dumps(manifest,ensure_ascii=False,indent=2))
