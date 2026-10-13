"""Проверки существенных для исследования ошибок на сохранённых страницах."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'src'))
import common
from common import *
from tabiturient_parser import parse_tabiturient, tabit_cards
from telegram_parser import read_telegram_message
from pikabu_parser import parse_pikabu_post

config = dict(start='2018-01-01',end='2026-10-06',terms=TERMS)
common.ERROR_DIR = Path(__file__).parent/'qa'
assert within_period('2026-10-06T20:59:59Z',config['start'],config['end'])
assert not within_period('2026-10-06T21:00:00Z',config['start'],config['end'])
assert parse_count('1.54K') == 1540 and parse_count('-12') == -12
assert parse_count(None) is None and parse_count('0') == 0
assert not keyword_hits('спокойно вспомнил', ['СПО'])
assert keyword_hits('вузы', ['вуз']) == ['вуз']

folder = Path(__file__).parent/'inspection'
soup = BeautifulSoup((folder/'question.html').read_text(encoding='utf-8'),'html.parser')
rows = parse_tabiturient(soup,dict(question_id='4538',url='https://tabiturient.ru/question/n/?4538'),config)
assert len(rows)==2 and rows[1]['author_type']=='university_label'
assert 'Будем рады видеть Вас' in rows[1]['text'] and 'Показать полностью' not in rows[1]['text']
assert rows[1]['text'].count('Здравствуйте!') == 1
soup.select('#resultdivcomment [itemprop="dateCreated"]')[0]['datetime'] = '2026-10-07T00:00Z'
assert len(parse_tabiturient(soup,dict(question_id='4538',url='x'),config)) == 1
soup = BeautifulSoup((folder/'nested.html').read_text(encoding='utf-8'),'html.parser')
rows = parse_tabiturient(soup,dict(question_id='4901',url='https://tabiturient.ru/question/n/?4901',replies_reported=2),config)
assert len(rows)==2 and rows[1]['nested_comments_reported']==1
assert rows[1]['author_type']=='user'
cards = tabit_cards(BeautifulSoup((folder/'list.html').read_text(encoding='utf-8'),'html.parser'))
assert len(cards)==25 and cards['4901']['replies_reported']==2

message = BeautifulSoup('<div data-post="channel/8"><time>2:14</time><a class="tgme_widget_message_date"><time datetime="2026-10-06T20:59:00Z"></time></a><div class="tgme_widget_message_text">Колледж</div><span class="tgme_widget_message_views">1.2K</span></div>','html.parser').div
row = read_telegram_message(message)
assert row['published_at'].startswith('2026-10-06T23:59') and row['views']==1200
assert row['reactions'] is None

html = '''<article class="story" data-story-id="123" data-comments="2"><time datetime="2020-01-02T12:00:00+03:00"></time><a class="story__title-link">Поступление в колледж</a><div class="story-block_type_text">Стоит ли поступать в колледж?</div><div class="story__rating-count">-2</div></article>
<div class="comment" id="comment_7" data-id="7" data-meta="sid=123;pid=0;aid=999"><div class="comment__body"><time datetime="2020-01-03T12:00:00+03:00"></time><div class="comment__content">Стоит подумать о вузе.</div><div class="comment__rating-count">0</div></div></div>
<div class="comment" id="comment_8"><div class="comment__body"><time datetime="2026-10-07T00:00:00+03:00"></time><div class="comment__content">Поздний ответ</div></div></div>
<div class="comment" id="comment_9" data-meta="sid=456"><div class="comment__body"><time datetime="2020-01-04T12:00:00+03:00"></time><div class="comment__content">Комментарий к другому посту</div></div></div>'''
rows = parse_pikabu_post(BeautifulSoup(html,'html.parser'),'https://pikabu.ru/story/test_123',config)
assert len(rows)==2 and rows[0]['rating']==-2 and rows[0]['collected_comments']==1
assert all('aid' not in x for x in rows)
print('PASS: cutoff Moscow; missing vs zero; acronym boundaries; full answer; university label; nested reply; video time; linked comments')
