"""Офлайн-проверки второго этапа: сохранённые страницы и имитация ответов API, без сети и ключей."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from bs4 import BeautifulSoup  # noqa: E402

import common  # noqa: E402
from common import Store, load_config, load_registry, parse_ru_date, period_v1, sender_hash, windows  # noqa: E402
from ministry_sites import (edu_day_links, minobr_list_links, parse_edu_article,  # noqa: E402
                            parse_generic_article, parse_minobr_article)
from telegram_mtproto import classify_sender, message_to_row, parse_link  # noqa: E402
import vk_api  # noqa: E402

FIX = Path(__file__).parent / 'qa' / 'fixtures'
soup = lambda name: BeautifulSoup((FIX / name).read_bytes(), 'html.parser')
config = load_config()
wins = windows(config, 'admissions_windows')

# Окна и периоды: без пересечений, внутри общего периода, верхняя граница 06.10.2026.
assert wins[0] == dict(id='admissions_windows_2018', start='2018-06-01', end='2018-09-30')
assert wins[-1]['end'] == '2026-09-30'
assert period_v1('2020-03-10') == 'pre_covid' and period_v1('2020-03-11') == 'covid'
assert period_v1('2022-02-24') == 'svo_early' and period_v1('2024-01-01') == 'svo_late'
assert period_v1('2026-10-07') is None
assert parse_ru_date('14 октября 2026, 18:46') == ('2026-10-14T18:46:00+03:00', 'minute')
assert parse_ru_date('14.10.2026 ') == ('2026-10-14', 'day')
assert common.to_moscow(datetime(2026, 10, 6, 20, 59, tzinfo=timezone.utc)) == '2026-10-06T23:59:00+03:00'

# Реестр: десять основных организаций, по одной на город и тип.
orgs = {(r['org_type'], r['city']) for r in load_registry(roles=('admissions',))}
assert len(orgs) == 10

# Псевдонимы: стабильны, различимы и требуют соли.
assert sender_hash(42, 's') == sender_hash(42, 's') != sender_hash(43, 's')
try:
    sender_hash(42, '')
    raise AssertionError('пустая соль должна запрещаться')
except ValueError:
    pass

# edu.gov.ru: страница дня → ссылки; статья → дата с минутами, текст без подписей к фото.
links = edu_day_links(soup('edu_day_2019-06-03.html'))
assert len(links) == 3 and all('/press/' in x for x in links)
row = parse_edu_article(soup('edu_article_1484.html'), links[0])
assert row['record_id'] == '1484' and row['published_at'].startswith('2019-06-03T18:03')
assert 'школ' in row['text_raw'] and 'Пресс-служба' not in row['text_raw'] and row['tags']

# minobrnauki.gov.ru: список окна и статья; рубрика из адреса попадает в теги.
assert len(minobr_list_links(soup('minobr_list_2024.html'))) == 9
url = 'https://minobrnauki.gov.ru/press-center/news/novosti-ministerstva/101935/'
row = parse_minobr_article(soup('minobr_article.html'), url)
assert row['published_at'] == '2026-10-14' and row['tags'].startswith('novosti-ministerstva')
assert 'АСЕАН' in row['text_raw'] and 'Поделиться' not in row['text_raw']
assert parse_generic_article(soup('minobr_article.html'), url)['extraction'] == 'site_parser'
row = parse_generic_article(soup('minobr_2018_card.html'), 'http://www.minobrnauki.gov.ru:80/ru/press-center/card/?id_4=10')
assert row['record_id'] == '10' and row['published_at'] == '2018-09-03T14:00:00+03:00'
assert row['tags'] == 'СМИ о Министерстве' and row['text_raw'].startswith('Министр науки')
assert 'При цитировании' not in row['text_raw'] and row['extraction'] == 'site_parser_2018'
old = BeautifulSoup('<html><title>Минобрнауки</title><h1>Новость</h1><div class="date">3 июня 2019</div>'
                    '<div><p>Первый абзац о приёме.</p><p>Второй абзац.</p></div><div><p>Меню</p></div></html>',
                    'html.parser')
row = parse_generic_article(old, 'https://minobrnauki.gov.ru/ru/press-center/card/?id_4=777')
assert row['record_id'] == '777' and row['published_at'] == '2019-06-03' and row['extraction'] == 'heuristic'
assert 'Второй абзац' in row['text_raw'] and 'Меню' not in row['text_raw']

# Telegram: ссылки и роли отправителей без личных данных.
assert parse_link('https://t.me/+i31fW9Dj1AgyNzdi') == ('invite', 'i31fW9Dj1AgyNzdi')
assert parse_link('https://telegram.me/urfu_ru') == ('username', 'urfu_ru')
CHANNEL, CHAT = 1111, 2222
msg = lambda **kw: NS(**dict(dict(id=5, date=datetime(2025, 7, 1, 9, tzinfo=timezone.utc), message='Вопрос',
                                  sender_id=777, post=False, reply_to=None, fwd_from=None, media=None,
                                  replies=None), **kw))
assert classify_sender(msg(post=True, sender_id=None), channel_id=CHANNEL) == 'organization'
assert classify_sender(msg(sender_id=-1000000000000 - CHANNEL), CHANNEL, CHAT) == 'organization'
assert classify_sender(msg(sender_id=-1000000000000 - CHAT), None, CHAT) == 'admin_anonymous'
assert classify_sender(msg(sender_id=99), None, CHAT, {99: 'Приёмная комиссия'}) == 'admin'
assert classify_sender(msg(), None, CHAT, {99: 'x'}) == 'user'
reply = msg(id=6, sender_id=99, reply_to=NS(reply_to_msg_id=5, reply_to_top_id=None))
row = message_to_row(reply, 'uni_dvfu_chat', 'message', 'salt', wins, 'run', 'u', chat_id=CHAT,
                     admins={99: 'Приёмная комиссия'})
assert row['parent_id'] == '5' and row['thread_id'] == '5' and row['sender_kind'] == 'admin'
assert row['sender_rank'] == 'Приёмная комиссия' and row['window_id'] == 'admissions_windows_2025'
assert row['published_at'] == '2025-07-01T12:00:00+03:00' and '99' not in json.dumps(row)
row = message_to_row(msg(post=True, sender_id=None), 'uni_itmo_tg', 'post', 'salt', wins, 'run', 'u', channel_id=CHANNEL)
assert row['sender_hash'] is None and row['sender_kind'] == 'organization'
comment = message_to_row(msg(id=9), 'uni_itmo_tg', 'comment', 'salt', wins, 'run', 'u', channel_id=CHANNEL,
                         chat_id=CHAT, thread_id=5)
assert comment['record_id'] == 'c9' and comment['thread_id'] == '5' and comment['sender_kind'] == 'user'


# VK: ответ от имени сообщества — organization; ветки догружаются; окна фильтруют комментарии.
class FakeVk:
    def __init__(self):
        self.calls = []

    def call(self, method, **p):
        self.calls.append(method)
        ts = lambda d: int(datetime.fromisoformat(d + 'T12:00:00+03:00').timestamp())
        if method == 'groups.getById':
            return {'groups': [{'id': 500, 'screen_name': 'abit'}]}
        if method == 'wall.get':
            items = [dict(id=3, date=ts('2025-07-10'), from_id=-500, text='Пост', comments={'count': 2}),
                     dict(id=2, date=ts('2025-03-01'), from_id=-500, text='Вне окна', comments={'count': 0}),
                     dict(id=1, date=ts('2017-05-01'), from_id=-500, text='Старый', comments={'count': 0})]
            return {'count': 3, 'items': items[p.get('offset', 0):p.get('offset', 0) + p['count']]}
        if method == 'wall.getComments' and 'comment_id' not in p:
            return {'count': 1, 'items': [dict(id=10, date=ts('2025-07-11'), from_id=8, text='Не прошёл на бюджет',
                                               thread=dict(count=2, items=[dict(id=11, date=ts('2025-07-11'),
                                                                                 from_id=-500, text='Ответ')]))]}
        if method == 'wall.getComments':
            return {'count': 2, 'items': [dict(id=11, date=ts('2025-07-11'), from_id=-500, text='Ответ'),
                                          dict(id=12, date=ts('2025-07-12'), from_id=8, text='Спасибо')]}
        if method == 'board.getTopics':
            return {'count': 1, 'items': [dict(id=70, title='Вопросы абитуриентов')]}
        if method == 'board.getComments':
            return {'count': 1, 'items': [dict(id=1, date=ts('2024-08-01'), from_id=-500, text='Ответ комиссии')]}
        raise AssertionError(method)


with tempfile.TemporaryDirectory() as folder:
    store = Store(folder, 'vk')
    src = dict(source_id='uni_test_vk', url='https://vk.com/club500')
    vk_api.collect_group(FakeVk(), src, store, wins, 'run', folder, 'salt', config['period'])
    rows = {r['record_id']: r for r in store.state['records'].values()}
    assert set(rows) == {'p3', 'c10', 'c11', 'c12', 'b70_1'}, rows.keys()  # пост вне окна не взят
    assert rows['c11']['sender_kind'] == 'organization' and rows['c11']['parent_id'] == 'c10'
    assert rows['c10']['sender_kind'] == 'user' and rows['c10']['parent_id'] == 'p3'
    assert rows['b70_1']['title'] == 'Вопросы абитуриентов' and rows['b70_1']['thread_id'] == 't70'
    assert store.done('vk|uni_test_vk') and (Path(folder) / 'vk.csv').exists()
    assert vk_api.screen_name('https://vk.ru/abit.itmo') == 'abit.itmo'

print('PASS: окна и периоды; реестр; псевдонимы; edu.gov.ru; minobrnauki; архивный разбор; '
      'роли Telegram; ветки и обсуждения VK')
