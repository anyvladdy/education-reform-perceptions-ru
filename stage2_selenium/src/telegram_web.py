"""Публичные каналы Telegram без ключей и входа: лента t.me/s (requests) + комментарии (Selenium).

Лента канала отдаётся сервером целиком, поэтому читается обычными запросами, как веб-витрина
первого этапа. Комментарии под постом показывает только виджет обсуждения на JavaScript:
его открывает Selenium. Чаты (группы) без входа не видны — их здесь нет.

Имена и логины комментаторов не сохраняются: только псевдоним sender_hash и роль
(organization — ответ от имени канала, user — остальные). Реакции не собираются.
"""

import re
import time

from bs4 import BeautifulSoup

from common import note, now, period_v1, sender_hash, to_moscow, window_of

PARSER_VERSION = 'stage2-selenium-0.1'


def channel_name(url):
    m = re.match(r'https?://(?:t|telegram)\.me/(?:s/)?([A-Za-z0-9_]+)/?$', url)
    if not m:
        raise ValueError(f'Не публичный канал Telegram: {url}')
    return m[1]


def parse_feed(soup):
    """Посты страницы t.me/s/<канал>: список словарей и название канала."""
    title = soup.select_one('meta[property="og:title"]')
    posts = []
    for message in soup.select('.tgme_widget_message[data-post]'):
        channel, number = message['data-post'].split('/')
        stamp = message.select_one('a.tgme_widget_message_date time[datetime]')
        if stamp is None:
            continue
        body = message.select_one('.tgme_widget_message_text')
        for br in body.find_all('br') if body else []:
            br.replace_with('\n')
        media = [kind for kind, selector in {
            'photo': '.tgme_widget_message_photo_wrap', 'video': '.tgme_widget_message_video_player',
            'document': '.tgme_widget_message_document_wrap', 'audio': '.tgme_widget_message_audio',
            'voice': '.tgme_widget_message_voice', 'poll': '.tgme_widget_message_poll'}.items()
            if message.select_one(selector)]
        views = message.select_one('.tgme_widget_message_views')
        posts.append(dict(
            id=int(number), channel=channel, published_at=to_moscow(stamp['datetime']),
            text=body.get_text('\n', strip=True) if body else '',
            forward=message.select_one('.tgme_widget_message_forwarded_from') is not None,
            media=media, views=views.get_text(strip=True) if views else None))
    return posts, title['content'] if title else None


def parse_comments(soup, channel, channel_title, salt):
    """Комментарии виджета обсуждения. Цитата родительского сообщения в текст не входит."""
    rows = []
    for message in soup.select('.tgme_widget_message[data-post-id]'):
        stamp = message.select_one('time[datetime]')
        reply = message.select_one('.js-reply_to[data-reply-to]')
        texts = [t for t in message.select('.tgme_widget_message_text')
                 if 'js-message_reply_text' not in (t.get('class') or [])]
        for br in texts[0].find_all('br') if texts else []:
            br.replace_with('\n')
        author = message.select_one('a.tgme_widget_message_author_name, span.tgme_widget_message_author_name')
        if reply is not None:  # имя автора цитаты не должно приниматься за автора комментария
            author = next((a for a in message.select('.tgme_widget_message_author_name')
                           if not a.find_parent(class_='js-reply_to')), None)
        href = (author.get('href') or '') if author else ''
        username = href.rstrip('/').rsplit('/', 1)[-1] if 't.me/' in href else None
        display = author.get_text(' ', strip=True) if author else ''
        is_channel = (username or '').lower() == channel.lower() or (channel_title and display == channel_title)
        rows.append(dict(
            id=int(message['data-post-id']), reply_to=int(reply['data-reply-to']) if reply else None,
            published_at=to_moscow(stamp['datetime']) if stamp else None,
            text=texts[0].get_text('\n', strip=True) if texts else '',
            sender_kind='organization' if is_channel else 'user',
            sender_hash=None if is_channel else sender_hash(username or f'name:{display}', salt)))
    return rows


def post_row(post, source_id, wins, run_id):
    published = post['published_at']
    tags = (['forward'] if post['forward'] else []) + (['media'] if post['media'] else [])
    return dict(source_id=source_id, record_id=str(post['id']), row_type='post', thread_id=str(post['id']),
                parent_id=None, published_at=published, date_precision='second',
                period_v1=period_v1(published), window_id=window_of(published, wins), title=None,
                text_raw=post['text'], url=f"https://t.me/{post['channel']}/{post['id']}", tags=';'.join(tags),
                sender_kind='organization', sender_hash=None, sender_rank=None, reply_count=None,
                collected_at=now(), run_id=run_id, parser_version=PARSER_VERSION, extraction='web')


def comment_row(comment, post, source_id, wins, run_id):
    published = comment['published_at']
    return dict(source_id=source_id, record_id=f"c{comment['id']}", row_type='comment', thread_id=str(post['id']),
                parent_id=f"c{comment['reply_to']}" if comment['reply_to'] else str(post['id']),
                published_at=published, date_precision='second', period_v1=period_v1(published or ''),
                window_id=window_of(published or '', wins), title=None, text_raw=comment['text'],
                url=f"https://t.me/{post['channel']}/{post['id']}?comment={comment['id']}", tags='',
                sender_kind=comment['sender_kind'], sender_hash=comment['sender_hash'], sender_rank=None,
                reply_count=None, collected_at=now(), run_id=run_id, parser_version=PARSER_VERSION,
                extraction='web')


def load_comments(driver, channel, post_id, pause=2.5, max_rounds=200):
    """Открыть виджет и догрузить все комментарии кнопкой «ещё». None — обсуждения нет."""
    driver.get(f'https://t.me/{channel}/{post_id}?embed=1&discussion=1')
    time.sleep(pause)
    if 'Discussion is not available' in driver.page_source:
        return None
    seen = -1
    for _ in range(max_rounds):
        count = len(driver.find_elements('css selector', '.tgme_widget_message[data-post-id]'))
        more = driver.find_elements('css selector', '.js-messages_more:not(.hide)')
        if not more or count == seen:
            break
        seen = count
        driver.execute_script('arguments[0].scrollIntoView(); arguments[0].click();', more[0])
        time.sleep(pause)
    return BeautifulSoup(driver.page_source, 'html.parser')


def iter_feed(http, channel, wins, period, pilot, folder, source_id):
    """Лента от новых к старым (?before=) или пилот: N последних и N первых (?after=)."""
    if pilot:
        late, before = [], None  # последние посты не позже конца периода: листаем назад
        for _ in range(50):
            page, _ = parse_feed(BeautifulSoup(http.get(f'https://t.me/s/{channel}', **(
                {'before': before} if before else {})).text, 'html.parser'))
            if not page:
                break
            late += [p for p in page if p['published_at'][:10] <= period['end']]
            if len(late) >= pilot // 2 or min(p['id'] for p in page) <= 1:
                break
            before = min(p['id'] for p in page)
        early, after = [], 1  # первые посты не раньше начала периода: листаем вперёд
        for _ in range(300):
            page, _ = parse_feed(BeautifulSoup(http.get(f'https://t.me/s/{channel}', after=after).text, 'html.parser'))
            if not page:
                break
            early += [p for p in page if p['published_at'][:10] >= period['start']]
            if len(early) >= pilot // 2 or max(p['id'] for p in page) <= after:
                break
            after = max(p['id'] for p in page)
        chosen = sorted(late, key=lambda p: -p['id'])[:pilot // 2] + sorted(early, key=lambda p: p['id'])[:pilot // 2]
        seen = set()
        for post in chosen:
            if post['id'] not in seen and period['start'] <= post['published_at'][:10] <= period['end']:
                seen.add(post['id'])
                yield post
        return
    earliest = min(w['start'] for w in wins)
    before = None
    while True:
        response = http.get(f'https://t.me/s/{channel}', **({'before': before} if before else {}))
        if response.status_code != 200:
            note(folder, source_id, response.url, f'HTTP {response.status_code}', kind='unavailable')
            return
        posts, _ = parse_feed(BeautifulSoup(response.text, 'html.parser'))
        if not posts:
            return
        for post in sorted(posts, key=lambda p: -p['id']):
            if window_of(post['published_at'], wins):
                yield post
        oldest = min(posts, key=lambda p: p['id'])
        if oldest['published_at'][:10] < earliest or oldest['id'] <= 1 or before == oldest['id']:
            return
        before = oldest['id']


def collect_channel(http, driver, src, store, wins, run_id, folder, salt, period, pilot=0):
    source_id = src['source_id']
    channel = channel_name(src['url'])
    _, title = parse_feed(BeautifulSoup(http.get(f'https://t.me/s/{channel}').text, 'html.parser'))
    comments = src['corpus_role'] == 'admissions'
    no_discussion = 0
    for post in iter_feed(http, channel, wins, period, pilot, folder, source_id):
        store.add(post_row(post, source_id, wins, run_id))
        task = f'tgweb|{source_id}|{post["id"]}'
        if not comments or store.done(task):
            continue
        soup = load_comments(driver, channel, post['id'])
        if soup is None:
            no_discussion += 1
        else:
            for comment in parse_comments(soup, channel, title, salt):
                day = (comment['published_at'] or '')[:10]
                if (period['start'] <= day <= period['end']) if pilot else window_of(day, wins):
                    store.add(comment_row(comment, post, source_id, wins, run_id))
        store.mark(task)
    if no_discussion:
        note(folder, source_id, src['url'], f'Постов без доступного обсуждения: {no_discussion}', kind='skip')
    store.mark(f'tgweb|{source_id}')
    return store.save()
