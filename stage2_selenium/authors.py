"""Роли авторов комментариев: сводка для ручной проверки и производная таблица с ролями.

Без входа в Telegram не видно, кто в обсуждении администратор. Сотрудник приёмной комиссии,
отвечающий с личного аккаунта, выглядит как обычный пользователь. Поэтому:

1. python authors.py summary   → data/<mode>/authors_summary.csv: самые активные псевдонимы,
   сколько раз они отвечали другим и ссылка на пример комментария. Откройте ссылку
   в браузере и проверьте профиль: подпись, указание на приёмную комиссию, ответы
   от имени организации.
2. Подтверждённые псевдонимы впишите в config.json → "staff_verified": {"uni_dvfu_tg": ["hash", ...]}.
3. python authors.py apply      → telegram_web_roles.csv: копия таблицы, где у них
   sender_kind = staff_verified. Исходная telegram_web.csv не меняется.
"""
import argparse
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument('action', choices=['summary', 'apply'])
parser.add_argument('--mode', choices=['pilot', 'full'], default='pilot')
parser.add_argument('--top', type=int, default=15, help='сколько авторов на источник')
args = parser.parse_args()

folder = HERE / 'data' / args.mode
frame = pd.read_csv(folder / 'telegram_web.csv', dtype=str)
comments = frame[frame.row_type == 'comment'].copy()

if args.action == 'summary':
    parents = dict(zip(comments.record_id, comments.sender_hash))
    comments['answers_other'] = [parents.get(p) not in (None, h) for p, h in zip(comments.parent_id, comments.sender_hash)]
    summary = (comments.dropna(subset=['sender_hash'])
               .groupby(['source_id', 'sender_hash'])
               .agg(comments=('record_id', 'size'), answers_to_others=('answers_other', 'sum'),
                    threads=('thread_id', 'nunique'), first_seen=('published_at', 'min'),
                    last_seen=('published_at', 'max'), example_url=('url', 'first'))
               .reset_index().sort_values(['source_id', 'comments'], ascending=[True, False]))
    summary = summary.groupby('source_id').head(args.top)
    summary['staff_verified'] = ''
    summary.to_csv(folder / 'authors_summary.csv', index=False, encoding='utf-8-sig')
    print(summary.drop(columns=['example_url']).to_string(index=False))
    print(f'\nСводка с ссылками: {folder / "authors_summary.csv"}')
else:
    staff = json.loads((HERE / 'config.json').read_text(encoding='utf-8')).get('staff_verified', {})
    roles = frame.copy()
    for source_id, hashes in staff.items():
        mask = (roles.source_id == source_id) & roles.sender_hash.isin(hashes)
        roles.loc[mask, 'sender_kind'] = 'staff_verified'
    roles.to_csv(folder / 'telegram_web_roles.csv', index=False, encoding='utf-8-sig')
    print(roles[roles.row_type == 'comment'].groupby(['source_id', 'sender_kind']).size().to_string())
