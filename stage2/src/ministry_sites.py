"""Новости министерств: edu.gov.ru, minobrnauki.gov.ru (с 2024 г.) и снимки веб-архива.

Разбор страницы (parse_*) отделён от загрузки, чтобы проверять его на сохранённом HTML.
"""

import re
from datetime import date, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import (Http, Store, note, now, parse_ru_date, period_v1, window_of,
                    PARSER_VERSION)

EDU = 'https://edu.gov.ru'
MINOBR = 'https://minobrnauki.gov.ru'


def clean_text(node):
    """Текст абзацами; подписи к фото, слайдеры и кнопки «поделиться» не входят."""
    if node is None:
        return ''
    for junk in node.select('figcaption, script, style, .news-page-slider, .news-detail-share, .ya-share2'):
        junk.decompose()
    for br in node.find_all('br'):
        br.replace_with('\n')
    text = node.get_text('\n')
    lines = [' '.join(line.split()) for line in text.splitlines()]
    return '\n'.join(line for line in lines if line)


def edu_day_links(soup):
    """Ссылки на новости со страницы дня edu.gov.ru/press/news/?date=YYYY-MM-DD."""
    links = []
    for a in soup.select('h3 a[href]'):
        href = urljoin(EDU, a['href'])
        m = re.match(r'https://edu\.gov\.ru/press/(\d+)/', href)
        if m and href not in links:
            links.append(href)
    return links


def parse_edu_article(soup, url):
    m = re.search(r'/press/(\d+)/', url)
    published, precision = parse_ru_date(soup.select_one('.date').get_text(' ') if soup.select_one('.date') else '')
    body = '\n'.join(filter(None, [clean_text(soup.select_one('.page-press__item-anounce')),
                                   clean_text(soup.select_one('.page-press__item-body'))]))
    tags = [t.get_text(' ', strip=True) for t in soup.select('.badgelist a')]  # темы и персоны
    title = soup.select_one('h1')
    return dict(record_id=m[1] if m else url, title=title.get_text(' ', strip=True) if title else None,
                published_at=published, date_precision=precision, text_raw=body,
                tags=';'.join(dict.fromkeys(tags)), extraction='site_parser')


def minobr_list_links(soup):
    links = []
    for a in soup.select('.news-item a[href]'):
        href = urljoin(MINOBR, a['href'])
        if re.match(r'https://minobrnauki\.gov\.ru/press-center/news/[a-z0-9-]+/\d+/$', href) and href not in links:
            links.append(href)
    return links


def parse_minobr_article(soup, url):
    m = re.search(r'/news/([a-z0-9-]+)/(\d+)/', url)
    date_node = soup.select_one('.post-date-day_')
    published, precision = parse_ru_date(date_node.get_text(' ') if date_node else '')
    tags = [m[1]] if m else []
    tags += [t.get_text(' ', strip=True) for t in soup.select('.post-tags__item')]
    title = soup.select_one('h1')
    return dict(record_id=m[2] if m else url, title=title.get_text(' ', strip=True) if title else None,
                published_at=published, date_precision=precision,
                text_raw=clean_text(soup.select_one('.post-body')),
                tags=';'.join(dict.fromkeys(tags)), extraction='site_parser')


def parse_minobr_2018(soup, url):
    """Версия minobrnauki.gov.ru 2018–2020: /ru/press-center/card/?id_4=N.

    Раздел («Новости», «СМИ о Министерстве», «Анонсы») сохраняется в tags: пересказы
    публикаций СМИ — не собственные сообщения ведомства и отсеиваются при отборе.
    """
    stat = soup.select_one('.news-main__stat')
    published, precision = parse_ru_date(stat.select_one('time').get_text(' ') if stat and stat.select_one('time') else '')
    section = [a.get_text(' ', strip=True) for a in stat.select('a')] if stat else []
    m = re.search(r'id_4=(\d+)', url)
    title = soup.select_one('h1')
    return dict(record_id=m[1] if m else url, title=title.get_text(' ', strip=True) if title else None,
                published_at=published, date_precision=precision,
                text_raw=clean_text(soup.select_one('.content-text')), tags=';'.join(section),
                extraction='site_parser_2018')


def parse_generic_article(soup, url):
    """Запасной разбор архивных страниц старых версий сайтов: заголовок, дата, крупнейший блок абзацев.

    Помечается extraction='heuristic' и требует выборочной ручной проверки в пилоте.
    """
    for selector, parser in [('.post-body', parse_minobr_article), ('.page-press__item-body', parse_edu_article),
                             ('.content-text', parse_minobr_2018)]:
        if soup.select_one(selector):
            row = parser(soup, url)
            if row['published_at']:
                return row
    title = soup.select_one('h1') or soup.select_one('title')
    published, precision = None, 'unknown'
    for node in soup.select('time[datetime], .date, .news-date, .post-date, .b-news__date, .news_date'):
        published, precision = parse_ru_date(node.get('datetime') or node.get_text(' '))
        if published:
            break
    if not published and title:
        nearby = ' '.join(x.get_text(' ') for x in title.find_all_next(limit=15))
        published, precision = parse_ru_date(nearby[:600])
    blocks = {}
    for p in soup.find_all('p'):
        blocks.setdefault(p.parent, []).append(p)
    best = max(blocks.items(), key=lambda kv: sum(len(p.get_text()) for p in kv[1]), default=(None, []))[0]
    m = re.search(r'(\d+)/?$', url.split('?')[0]) or re.search(r'(?:ELEMENT_ID|id_4)=(\d+)', url)
    return dict(record_id=m[1] if m else url, title=title.get_text(' ', strip=True) if title else None,
                published_at=published, date_precision=precision, text_raw=clean_text(best),
                tags='', extraction='heuristic')


def to_row(source_id, parsed, url, wins, run_id):
    if parsed.get('title'):
        parsed['title'] = ' '.join(parsed['title'].replace('\ufeff', '').split())
    return dict(parsed, source_id=source_id, row_type='post', thread_id=parsed['record_id'],
                parent_id=None, url=url, period_v1=period_v1(parsed['published_at'] or ''),
                window_id=window_of(parsed['published_at'] or '', wins), sender_kind='organization',
                sender_hash=None, sender_rank=None, reply_count=None, collected_at=now(),
                run_id=run_id, parser_version=PARSER_VERSION)


def _keep(row, wins, folder, source_id, url):
    if not row['published_at']:
        note(folder, source_id, url, 'Дата публикации не извлечена', kind='parse_error')
        return False
    if not row['window_id']:
        note(folder, source_id, url, f"Дата {row['published_at'][:10]} вне окон сбора", kind='skip')
        return False
    return True


def collect_edu(http: Http, store: Store, wins, run_id, folder, pilot=0):
    """Обход по дням окон: страница дня даёт точную дату без угадывания года."""
    source_id = 'state_minpros_site'
    days = []
    for w in wins:
        d, end = date.fromisoformat(w['start']), date.fromisoformat(w['end'])
        while d <= end:
            days.append(d.isoformat())
            d += timedelta(days=1)
    plan = [days, []] if not pilot else [days, list(reversed(days))]
    for part, sequence in enumerate(plan):
        taken = 0
        for day in sequence:
            if pilot and taken >= pilot // 2:
                break
            task = f'edu|{day}'
            if store.done(task) and not pilot:
                continue
            response = http.get(f'{EDU}/press/news/', date=day)
            if response.status_code != 200:
                note(folder, source_id, response.url, f'HTTP {response.status_code}', kind='unavailable')
                continue
            for url in edu_day_links(BeautifulSoup(response.text, 'html.parser')):
                if pilot and taken >= pilot // 2:
                    break
                record = re.search(r'/press/(\d+)/', url)[1]
                if store.has(f'{source_id}|post|{record}'):
                    continue
                page = http.get(url)
                if page.status_code != 200:
                    note(folder, source_id, url, f'HTTP {page.status_code}', kind='unavailable')
                    continue
                row = to_row(source_id, parse_edu_article(BeautifulSoup(page.text, 'html.parser'), url), url, wins, run_id)
                if row['published_at'] and row['published_at'][:10] != day:
                    note(folder, source_id, url, f'На странице дня {day} статья от {row["published_at"][:10]}', kind='warning')
                if _keep(row, wins, folder, source_id, url):
                    store.add(row)
                    taken += 1
            store.mark(task)
    return store.save()


def collect_minobr(http: Http, store: Store, wins, run_id, folder, pilot=0, live_from='2024-01-01'):
    """Текущий сайт Минобрнауки отдаёт новости только с 2024 г.; ранние годы — collect_wayback."""
    source_id = 'state_minobr_site'
    live = [w for w in wins if w['end'] >= live_from]
    if pilot:
        live = [live[0], live[-1]] if len(live) > 1 else live
    for w in live:
        start = max(w['start'], live_from)
        fmt = lambda iso: '.'.join(reversed(iso.split('-')))
        links, page = [], 1
        while True:
            response = http.get(f'{MINOBR}/press-center/news/',
                                active_date=f'{fmt(start)};{fmt(w["end"])}', PAGEN_1=page)
            found = [u for u in minobr_list_links(BeautifulSoup(response.text, 'html.parser')) if u not in links]
            if response.status_code != 200 or not found:
                break
            links += found
            page += 1
        links.sort(key=lambda u: int(re.search(r'/(\d+)/$', u)[1]))
        if pilot:
            links = links[:pilot // 4] + links[-(pilot // 4):]
        for url in links:
            record = re.search(r'/(\d+)/$', url)[1]
            if store.has(f'{source_id}|post|{record}'):
                continue
            response = http.get(url)
            if response.status_code != 200:
                note(folder, source_id, url, f'HTTP {response.status_code}', kind='unavailable')
                continue
            row = to_row(source_id, parse_minobr_article(BeautifulSoup(response.text, 'html.parser'), url), url, wins, run_id)
            if _keep(row, wins, folder, source_id, url):
                store.add(row)
        store.mark(f'minobr|{w["id"]}')
    return store.save()


def collect_wayback(http: Http, store: Store, wins, run_id, folder, archive, pilot=0, live_from='2024-01-01'):
    """Снимки Internet Archive по шаблону адреса.

    archive: {source_id, url, from, to, article_regex}. Дата снимка не равна дате
    публикации: окно проверяется по дате, извлечённой со страницы.
    """
    response = http.get('https://web.archive.org/cdx/search/cdx', params={
        'url': archive['url'], 'from': archive['from'], 'to': archive['to'], 'output': 'json',
        'fl': 'timestamp,original', 'collapse': 'urlkey', 'filter': 'statuscode:200'})
    if response.status_code != 200 or not response.text.startswith('['):
        note(folder, archive['source_id'], response.url, f'CDX недоступен: HTTP {response.status_code}', kind='unavailable')
        return store.save()
    captures = [r for r in response.json()[1:] if re.search(archive['article_regex'], r[1])]
    captures.sort()
    if pilot:
        captures = captures[:pilot // 2] + captures[-(pilot // 2):]
    for timestamp, original in captures:
        task = f"wayback|{archive['source_id']}|{original}"
        if store.done(task):
            continue
        snapshot = f'https://web.archive.org/web/{timestamp}id_/{original}'
        page = http.get(snapshot)
        if page.status_code != 200:
            note(folder, archive['source_id'], snapshot, f'HTTP {page.status_code}', kind='unavailable')
            continue
        parsed = parse_generic_article(BeautifulSoup(page.content, 'html.parser'), original)
        row = to_row(archive['source_id'], parsed, original, wins, run_id)
        row['url'] = snapshot
        if row['published_at'] and row['published_at'][:10] >= live_from:
            note(folder, archive['source_id'], snapshot, 'Публикация есть на текущем сайте: не дублируем', kind='skip')
        elif _keep(row, wins, folder, archive['source_id'], snapshot):
            store.add(row)
        store.mark(task)
    return store.save()
