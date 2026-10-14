"""Офлайн-проверки варианта без ключей: лента канала и виджет комментариев, без сети и браузера."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'src'))
sys.path.insert(1, str(HERE.parent / 'stage2' / 'src'))
from bs4 import BeautifulSoup  # noqa: E402

from common import load_config, windows  # noqa: E402
from telegram_web import channel_name, comment_row, parse_comments, parse_feed, post_row  # noqa: E402

FIX = HERE / 'qa' / 'fixtures'
soup = lambda name: BeautifulSoup((FIX / name).read_bytes(), 'html.parser')
config = load_config(HERE / 'config.json')
wins = windows(config, 'admissions_windows')

assert channel_name('https://t.me/tvoidvfu') == 'tvoidvfu'
assert channel_name('https://telegram.me/urfu_ru') == 'urfu_ru'
assert all(x in json.dumps(config) for x in ['uni_dvfu_tg', 'state_minpros_tg'])

# Лента: посты канала с датой по Москве, текстом с переносами, пересылками и медиа.
posts, title = parse_feed(soup('feed_tvoidvfu.html'))
assert len(posts) == 11 and title == 'Абитуриенты ДВФУ'
assert all(p['channel'] == 'tvoidvfu' and p['published_at'].endswith('+03:00') for p in posts)
assert sum(p['forward'] for p in posts) == 3 and any(p['media'] for p in posts)
row = post_row(posts[0], 'uni_dvfu_tg', wins, 'run')
assert row['sender_kind'] == 'organization' and row['url'] == f"https://t.me/tvoidvfu/{posts[0]['id']}"

# Комментарии: ветки ответов, цитата родителя не попадает в текст, имена не сохраняются.
comments = parse_comments(soup('comments_synthetic.html'), 'test_channel', 'Абитуриенты Теста', 'salt')
assert [c['id'] for c in comments] == [100, 101, 102]
assert comments[0]['reply_to'] is None and comments[1]['reply_to'] == 100 and comments[2]['reply_to'] == 101
assert comments[0]['text'] == 'Не прошёл на бюджет,\nчто посоветуете?'
assert comments[1]['text'] == 'Рассмотрите платное обучение или другую программу.'
assert comments[1]['sender_kind'] == 'organization' and comments[1]['sender_hash'] is None
assert comments[0]['sender_kind'] == comments[2]['sender_kind'] == 'user'
assert comments[0]['sender_hash'] != comments[2]['sender_hash'] and len(comments[0]['sender_hash']) == 16
post = dict(id=7, channel='test_channel')
rows = [comment_row(c, post, 'uni_test_tg', wins, 'run') for c in comments]
assert rows[0]['parent_id'] == '7' and rows[1]['parent_id'] == 'c100' and rows[1]['thread_id'] == '7'
assert rows[0]['window_id'] == 'admissions_windows_2025' and rows[2]['window_id'] is None  # 1 октября вне окна
assert rows[1]['url'] == 'https://t.me/test_channel/7?comment=101'
dump = json.dumps(rows, ensure_ascii=False)
assert 'Тестовый' not in dump and 'test_applicant' not in dump and 'Без логина' not in dump

print('PASS: ссылки каналов; лента t.me/s; ветки комментариев; ответ от имени канала; '
      'цитата вне текста; имена не сохраняются; окна')
