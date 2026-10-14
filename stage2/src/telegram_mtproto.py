"""Telegram через MTProto (Telethon): каналы, комментарии к постам и чаты приёмных комиссий.

Нужен отдельный исследовательский аккаунт и ключи my.telegram.org в stage2/.env.
Имена, логины и телефоны авторов не сохраняются: только псевдоним sender_hash и
роль (организация / администратор / пользователь). Реакции не собираются.
"""

import re
from datetime import datetime, timedelta, timezone

from common import (MOSCOW, PARSER_VERSION, note, now, period_v1, sender_hash,
                    to_moscow, window_of)


def parse_link(url):
    """https://t.me/name → ('username', name); https://t.me/+hash → ('invite', hash)."""
    m = re.match(r'https?://(?:t|telegram)\.me/(?:joinchat/|\+)([\w-]+)', url)
    if m:
        return 'invite', m[1]
    m = re.match(r'https?://(?:t|telegram)\.me/(?:s/)?([A-Za-z0-9_]+)', url)
    if m:
        return 'username', m[1]
    raise ValueError(f'Не ссылка Telegram: {url}')


def classify_sender(message, channel_id=None, chat_id=None, admins=None):
    """Кто написал сообщение. Только роль, без личных данных.

    organization — пост канала или сообщение от имени канала;
    admin_anonymous — анонимный администратор чата (отправитель — сам чат);
    admin — аккаунт из списка администраторов (ранг сохраняется отдельно);
    user — остальные участники.
    """
    sender = message.sender_id
    if getattr(message, 'post', False) or sender is None and channel_id is not None and chat_id is None:
        return 'organization'
    if channel_id is not None and sender in (channel_id, -1000000000000 - channel_id):
        return 'organization'
    if chat_id is not None and sender in (chat_id, -1000000000000 - chat_id):
        return 'admin_anonymous'
    if admins and sender in admins:
        return 'admin'
    return 'user'


def message_to_row(message, source_id, row_type, salt, wins, run_id, url, *,
                   channel_id=None, chat_id=None, admins=None, thread_id=None):
    kind = classify_sender(message, channel_id, chat_id, admins)
    reply = getattr(message, 'reply_to', None)
    parent = getattr(reply, 'reply_to_msg_id', None) if reply else None
    top = getattr(reply, 'reply_to_top_id', None) if reply else None
    published = to_moscow(message.date)
    tags = []
    if getattr(message, 'fwd_from', None):
        tags.append('forward')
    if getattr(message, 'media', None) is not None:
        tags.append('media')
    replies = getattr(message, 'replies', None)
    return dict(
        source_id=source_id, record_id=str(message.id) if row_type != 'comment' else f'c{message.id}',
        row_type=row_type, thread_id=str(thread_id or top or parent or message.id),
        parent_id=str(parent) if parent else None, published_at=published, date_precision='second',
        period_v1=period_v1(published), window_id=window_of(published, wins), title=None,
        text_raw=message.message or '', url=url, tags=';'.join(tags), sender_kind=kind,
        sender_hash=None if kind == 'organization' else sender_hash(message.sender_id, salt),
        sender_rank=(admins or {}).get(message.sender_id) if kind == 'admin' else None,
        reply_count=getattr(replies, 'replies', None) if replies else None,
        collected_at=now(), run_id=run_id, parser_version=PARSER_VERSION, extraction='api')


def message_url(username, internal_id, message_id, comment_id=None):
    base = f'https://t.me/{username}/{message_id}' if username else f'https://t.me/c/{internal_id}/{message_id}'
    return base + (f'?comment={comment_id}' if comment_id else '')


async def resolve(client, url, join, folder, source_id):
    """Сущность по ссылке. В чат по приглашению вступаем только при флаге --join."""
    from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
    from telethon.tl.types import ChatInviteAlready

    kind, value = parse_link(url)
    if kind == 'username':
        return await client.get_entity(value)
    invite = await client(CheckChatInviteRequest(value))
    if isinstance(invite, ChatInviteAlready):
        return invite.chat
    if not join:
        note(folder, source_id, url, 'Чат по приглашению: запустите с --join, чтобы вступить', kind='skip')
        return None
    updates = await client(ImportChatInviteRequest(value))
    note(folder, source_id, url, 'Исследовательский аккаунт вступил в чат по приглашению', kind='join')
    return updates.chats[0]


async def admin_ranks(client, entity, folder, source_id):
    """{user_id: ранг} администраторов; список может быть скрыт — тогда роль не устанавливается."""
    from telethon.tl.types import ChannelParticipantsAdmins
    try:
        ranks = {}
        async for user in client.iter_participants(entity, filter=ChannelParticipantsAdmins):
            participant = getattr(user, 'participant', None)
            ranks[user.id] = getattr(participant, 'rank', None) or 'admin'
        return ranks
    except Exception as error:  # noqa: BLE001 — любая ошибка доступа фиксируется и не прерывает сбор
        note(folder, source_id, '', f'Список администраторов недоступен: {type(error).__name__}', kind='warning')
        return {}


async def _iterate(client, entity, wins, pilot, period, **kwargs):
    """Сообщения в окнах (новые → старые) либо пилот: N последних и N первых в периоде."""
    if pilot:
        start = datetime.fromisoformat(period['start']).replace(tzinfo=MOSCOW)
        end = datetime.fromisoformat(period['end']).replace(tzinfo=MOSCOW) + timedelta(days=1)
        seen = set()
        async for m in client.iter_messages(entity, limit=pilot // 2, offset_date=end, **kwargs):
            seen.add(m.id)
            yield None, m
        async for m in client.iter_messages(entity, limit=pilot // 2, offset_date=start, reverse=True, **kwargs):
            if m.id not in seen:
                yield None, m
        return
    for w in sorted(wins, key=lambda w: w['start'], reverse=True):
        start = datetime.fromisoformat(w['start']).replace(tzinfo=MOSCOW)
        end = datetime.fromisoformat(w['end']).replace(tzinfo=MOSCOW) + timedelta(days=1)
        async for m in client.iter_messages(entity, offset_date=end, **kwargs):
            if m.date < start.astimezone(timezone.utc):
                break
            yield w['id'], m


async def collect_source(client, src, store, wins, run_id, folder, salt, period, pilot=0, join=False):
    from telethon.tl.functions.channels import GetFullChannelRequest

    source_id = src['source_id']
    entity = await resolve(client, src['url'], join, folder, source_id)
    if entity is None:
        return
    username = getattr(entity, 'username', None)
    is_broadcast = bool(getattr(entity, 'broadcast', False))
    collect_comments = is_broadcast and src['corpus_role'] == 'admissions'
    admins, discussion_id = {}, None
    if is_broadcast and collect_comments:
        full = await client(GetFullChannelRequest(entity))
        discussion_id = full.full_chat.linked_chat_id
        if discussion_id:
            admins = await admin_ranks(client, await client.get_entity(discussion_id), folder, source_id)
        else:
            note(folder, source_id, src['url'], 'У канала нет привязанного обсуждения: комментариев нет', kind='skip')
    elif not is_broadcast:
        admins = await admin_ranks(client, entity, folder, source_id)
    row_type = 'post' if is_broadcast else 'message'
    empty = 0
    async for window_id, message in _iterate(client, entity, wins, pilot, period):
        if getattr(message, 'action', None) is not None:
            continue  # служебные сообщения: вступления, закрепления
        if not message.message and message.media is None:
            empty += 1
            continue
        url = message_url(username, entity.id, message.id)
        store.add(message_to_row(message, source_id, row_type, salt, wins, run_id, url,
                                 channel_id=entity.id if is_broadcast else None,
                                 chat_id=None if is_broadcast else entity.id, admins=admins))
        replies = getattr(message, 'replies', None)
        if collect_comments and discussion_id and replies and replies.replies:
            count = 0
            async for comment in client.iter_messages(entity, reply_to=message.id):
                if pilot and count >= pilot:
                    break
                store.add(message_to_row(comment, source_id, 'comment', salt, wins, run_id,
                                         message_url(username, entity.id, message.id, comment.id),
                                         channel_id=entity.id, chat_id=discussion_id, admins=admins,
                                         thread_id=message.id))
                count += 1
        if window_id and len(store.state['records']) % 200 == 0:
            store.save()
    if empty:
        note(folder, source_id, src['url'], f'Пропущено сообщений без текста и вложений: {empty}', kind='skip')
    store.mark(f'telegram|{source_id}')


async def collect_telegram(sources, env, store, wins, run_id, folder, period, pilot=0, join=False):
    from telethon import TelegramClient
    from common import ROOT

    if not env.get('TG_API_ID') or not env.get('TG_API_HASH'):
        raise SystemExit('Нет TG_API_ID / TG_API_HASH в stage2/.env — см. stage2/README.md')
    session = ROOT / '.secrets' / env.get('TG_SESSION', 'research')
    session.parent.mkdir(exist_ok=True)
    client = TelegramClient(str(session), int(env['TG_API_ID']), env['TG_API_HASH'])
    client.flood_sleep_threshold = 300
    await client.start()  # первый запуск спросит телефон и код из Telegram
    try:
        for src in sources:
            if store.done(f"telegram|{src['source_id']}") and not pilot:
                continue
            try:
                await collect_source(client, src, store, wins, run_id, folder, env.get('HASH_SALT'),
                                     period, pilot, join)
            except Exception as error:  # noqa: BLE001 — один источник не останавливает остальные
                note(folder, src['source_id'], src['url'], f'{type(error).__name__}: {error}')
            store.save()
    finally:
        await client.disconnect()
    return store.save()
