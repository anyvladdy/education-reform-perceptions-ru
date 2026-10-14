"""ВКонтакте через официальный API: стена сообщества, комментарии с ветками, обсуждения.

Токен пользователя — в stage2/.env (VK_TOKEN). Ответ от имени сообщества
(from_id = -id группы) помечается как organization. Личные аккаунты сотрудников
не отличимы от пользователей без ручной проверки: они остаются user.
"""

import re
import time

import requests

from common import PARSER_VERSION, note, now, period_v1, sender_hash, to_moscow, window_of

API = 'https://api.vk.com/method/'
VERSION = '5.199'
RETRY_CODES = {6, 9, 10, 29}          # частота запросов, временная ошибка сервера
ACCESS_CODES = {15, 18, 19, 30, 203}  # закрыто, удалено, нет доступа


class VkAccessError(Exception):
    pass


class Vk:
    def __init__(self, token, pause=0.35):
        if not token:
            raise SystemExit('Нет VK_TOKEN в stage2/.env — см. stage2/README.md')
        self.token, self.pause, self.last = token, pause, 0.0
        self.session = requests.Session()

    def call(self, method, **params):
        for attempt in range(5):
            wait = self.pause - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            data = self.session.post(API + method, data=dict(params, access_token=self.token, v=VERSION),
                                     timeout=40).json()
            if 'error' not in data:
                return data['response']
            code, message = data['error'].get('error_code'), data['error'].get('error_msg')
            if code in RETRY_CODES and attempt < 4:
                time.sleep(2 * (attempt + 1))
                continue
            if code in ACCESS_CODES:
                raise VkAccessError(f'{code}: {message}')
            raise RuntimeError(f'VK API {method}: {code} {message}')


def screen_name(url):
    m = re.match(r'https?://(?:m\.)?vk\.(?:com|ru)/([A-Za-z0-9_.]+)', url)
    if not m:
        raise ValueError(f'Не ссылка VK: {url}')
    return m[1]


def resolve_group(vk, url):
    name = screen_name(url)
    m = re.fullmatch(r'(?:club|public|event)(\d+)', name)
    response = vk.call('groups.getById', group_id=m[1] if m else name)
    groups = response['groups'] if isinstance(response, dict) else response
    return groups[0]['id'], groups[0].get('screen_name') or name


def vk_row(item, source_id, row_type, gid, salt, wins, run_id, url, *, thread_id, parent_id=None, title=None,
           record_id=None):
    from_id = item.get('from_id', item.get('owner_id'))
    kind = 'organization' if from_id == -gid else 'user'
    published = to_moscow(item['date'])
    tags = []
    if item.get('copy_history'):
        tags.append('repost')
    if item.get('attachments'):
        tags.append('media')
    if item.get('is_pinned'):
        tags.append('pinned')
    comments = item.get('comments') or item.get('thread') or {}
    return dict(
        source_id=source_id, record_id=record_id or f"{row_type[0]}{item['id']}", row_type=row_type,
        thread_id=str(thread_id), parent_id=str(parent_id) if parent_id else None,
        published_at=published, date_precision='second', period_v1=period_v1(published),
        window_id=window_of(published, wins), title=title, text_raw=item.get('text') or '',
        url=url, tags=';'.join(tags), sender_kind=kind,
        sender_hash=None if kind == 'organization' else sender_hash(from_id, salt), sender_rank=None,
        reply_count=comments.get('count'), collected_at=now(), run_id=run_id,
        parser_version=PARSER_VERSION, extraction='api')


def in_scope(ts, wins, period, pilot):
    day = to_moscow(ts)[:10]
    if pilot:
        return period['start'] <= day <= period['end']
    return window_of(day, wins) is not None


def wall_posts(vk, gid, wins, period, pilot):
    """Посты стены. Полный режим: от новых к старым до начала самого раннего окна."""
    first = vk.call('wall.get', owner_id=-gid, count=1)
    total = first['count']
    if pilot:
        late = vk.call('wall.get', owner_id=-gid, count=pilot // 2)['items']
        early = vk.call('wall.get', owner_id=-gid, count=pilot // 2, offset=max(total - pilot // 2, 0))['items']
        seen = set()
        for post in late + early:
            if post['id'] not in seen and in_scope(post['date'], wins, period, pilot):
                seen.add(post['id'])
                yield post
        return
    earliest = min(w['start'] for w in wins)
    for offset in range(0, total, 100):
        items = vk.call('wall.get', owner_id=-gid, count=100, offset=offset)['items']
        for post in items:
            if in_scope(post['date'], wins, period, pilot):
                yield post
        unpinned = [p for p in items if not p.get('is_pinned')]
        if not items or unpinned and to_moscow(unpinned[-1]['date'])[:10] < earliest:
            return


def post_comments(vk, gid, post_id, limit=None):
    """Комментарии по порядку; ветки догружаются целиком, если в ответе их часть."""
    offset, taken = 0, 0
    while True:
        batch = vk.call('wall.getComments', owner_id=-gid, post_id=post_id, count=100, offset=offset,
                        sort='asc', thread_items_count=10)
        for comment in batch['items']:
            yield comment, None
            taken += 1
            thread = comment.get('thread') or {}
            items = thread.get('items', [])
            if thread.get('count', 0) > len(items):
                items, sub = [], 0
                while True:
                    part = vk.call('wall.getComments', owner_id=-gid, post_id=post_id, comment_id=comment['id'],
                                   count=100, offset=sub, sort='asc')
                    items += part['items']
                    sub += 100
                    if sub >= part['count']:
                        break
            for reply in items:
                yield reply, comment['id']
            if limit and taken >= limit:
                return
        offset += 100
        if offset >= batch['count']:
            return


def collect_group(vk, src, store, wins, run_id, folder, salt, period, pilot=0):
    source_id = src['source_id']
    gid, name = resolve_group(vk, src['url'])
    base = f'https://vk.com/wall-{gid}_'
    for post in wall_posts(vk, gid, wins, period, pilot):
        store.add(vk_row(post, source_id, 'post', gid, salt, wins, run_id, f"{base}{post['id']}", thread_id=post['id']))
        if (post.get('comments') or {}).get('count'):
            try:
                for comment, parent in post_comments(vk, gid, post['id'], limit=pilot or None):
                    if not pilot and not in_scope(comment['date'], wins, period, pilot):
                        continue
                    store.add(vk_row(comment, source_id, 'comment', gid, salt, wins, run_id,
                                     f"{base}{post['id']}?reply={comment['id']}", thread_id=post['id'],
                                     parent_id=f'c{parent}' if parent else f"p{post['id']}"))
            except VkAccessError as error:
                note(folder, source_id, f"{base}{post['id']}", f'Комментарии недоступны: {error}', kind='unavailable')
    store.save()
    try:
        topics = vk.call('board.getTopics', group_id=gid, count=100)['items']
    except VkAccessError as error:
        note(folder, source_id, src['url'], f'Обсуждения недоступны: {error}', kind='unavailable')
        topics = []
    for topic in topics[:2] if pilot else topics:
        offset, taken = 0, 0
        while True:
            batch = vk.call('board.getComments', group_id=gid, topic_id=topic['id'], count=100, offset=offset, sort='asc')
            for comment in batch['items']:
                if in_scope(comment['date'], wins, period, pilot):
                    store.add(vk_row(comment, source_id, 'board_comment', gid, salt, wins, run_id,
                                     f"https://vk.com/topic-{gid}_{topic['id']}?post={comment['id']}",
                                     thread_id=f"t{topic['id']}", title=topic.get('title'),
                                     record_id=f"b{topic['id']}_{comment['id']}"))
                    taken += 1
            offset += 100
            if offset >= batch['count'] or (pilot and taken >= pilot):
                break
    if not topics:
        note(folder, source_id, src['url'], 'Обсуждений нет или они скрыты', kind='skip')
    store.mark(f'vk|{source_id}')


def collect_vk(sources, env, store, wins, run_id, folder, period, pilot=0):
    vk = Vk(env.get('VK_TOKEN'))
    for src in sources:
        if store.done(f"vk|{src['source_id']}") and not pilot:
            continue
        try:
            collect_group(vk, src, store, wins, run_id, folder, env.get('HASH_SALT'), period, pilot)
        except (VkAccessError, RuntimeError, requests.RequestException) as error:
            note(folder, src['source_id'], src['url'], f'{type(error).__name__}: {error}')
        store.save()
    return store.save()
