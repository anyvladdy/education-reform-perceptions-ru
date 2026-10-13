"""Табитуриент: список вопросов → полные ветки → одна таблица связанных сообщений."""
from copy import copy
import random
from urllib.parse import urlparse
from common import *

TABIT_URL = 'https://tabiturient.ru/question/'
TABIT_TERMS = [
    'СПО', 'колледж', 'техникум', 'ПТУ', 'высшее образован', 'диплом',
    '10 класс', 'десятый класс', '9 класс', 'престиж', 'не прой', 'не прош',
    'не поступ', 'не взяли', 'не приняли', 'передум', 'попроще', 'отказ',
    'не туда', 'низкие баллы', 'мало баллов', 'платн', 'дорого', 'перевест',
    'перевод', 'целево', 'бюджет', 'профессия', 'профессию', 'нужен ли',
    'нужно ли', 'стоит ли', 'работать', 'трудоустрой', 'не потян',
]
MONTHS = dict(zip('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split(), range(1,13)))


def tabit_text(node):
    if node is None:
        return ''
    node = copy(node)
    for label in node.select('[class*="slivmore-pre-"]'):
        label.decompose()  # Убираем «Показать полностью», продолжение уже есть в DOM.
    return node.get_text(' ', strip=True)


def tabit_date(node):
    date = node.select_one('[itemprop="dateCreated"][datetime]')
    if date:
        return date['datetime'][:10]  # Сайт показывает день; псевдоточное время не используем.
    match = re.search(r'(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(20\d{2})', node.get_text(' ', strip=True))
    return f'{match[3]}-{MONTHS[match[2]]:02d}-{int(match[1]):02d}' if match else None


def tabit_cards(soup):
    cards = {}
    for link in soup.select('#resultsliv a[href*="/question/n/?"]'):
        match = re.search(r'/question/n/\?(\d+)$', link.get('href', ''))
        if not match:
            continue
        card = link.find_parent('div', class_='p20')
        if card is None:
            continue
        content = card.find('div', class_='font2', recursive=False)
        answer_link = next((a for a in card.select('a') if 'Ответов' in a.get_text()), None)
        cards[match[1]] = dict(question_id=match[1], url=link['href'], date=tabit_date(card),
                              text=tabit_text(content), tags='; '.join(x.get_text(' ',strip=True) for x in card.select('.button5 b')),
                              replies_reported=parse_count(answer_link.select_one('b').text) if answer_link and answer_link.select_one('b') else None)
    return cards


def discover_tabiturient(driver, config):
    """Selenium нажимает реальную кнопку. Прямых AJAX/API-запросов нет."""
    path = Path(config['output_dir']) / 'tabiturient_discovery.json'
    if path.exists():
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('complete') and state.get('start') == config['start']:
            return state['cards']
    cards, stop = {}, 'running'
    soup = load_page(driver, TABIT_URL, '#resultsliv a[href*="/question/n/?"]')
    for page in range(1, config.get('tabit_max_pages', 300) + 1):
        current = tabit_cards(soup)
        new = {k:v for k,v in current.items() if k not in cards}
        cards.update(new)
        dates = [x['date'] for x in new.values() if x['date']]
        if not new:
            stop = 'no_new_cards'
        elif dates and max(dates) < config['start']:
            stop = 'before_start'
        elif config.get('demo'):
            stop = 'demo_first_page'
        buttons = driver.find_elements(By.CSS_SELECTOR, '.morediv[onclick*="morelimit5"]')
        visible = [b for b in buttons if b.is_displayed()]
        if not visible and stop == 'running':
            stop = 'end_of_list'
        if page == config.get('tabit_max_pages', 300) and stop == 'running':
            stop = 'page_limit'
        state = dict(start=config['start'], pages=page, complete=stop in ['end_of_list','before_start'],
                     stop_reason=stop, cards=cards)
        path.write_text(json.dumps(state,ensure_ascii=False), encoding='utf-8')
        print(f'Tabiturient: list page {page}, {len(cards)} questions, {min(dates) if dates else "?"}', flush=True)
        if stop != 'running':
            break
        old_count = len(driver.find_elements(By.CSS_SELECTOR, '#resultsliv a[href*="/question/n/?"]'))
        driver.execute_script('arguments[0].scrollIntoView({block:"center"})', visible[0])
        visible[0].click()
        try:
            WebDriverWait(driver, 25).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '#resultsliv a[href*="/question/n/?"]')) > old_count)
        except TimeoutException:
            note_error('tabiturient', TABIT_URL, f'Список перестал пополняться на странице {page}')
            break
        time.sleep(config.get('pause',1.5))
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    return cards


def parse_tabiturient(soup, card, config):
    qid = card['question_id']
    question = soup.select_one(f'#voprosdivin{qid}')
    if question is None:
        raise ValueError('Не найдена карточка вопроса: изменилась разметка или вопрос удалён')
    qtext = tabit_text(question.select_one('[itemprop="text"]'))
    tags = '; '.join(x.get_text(' ',strip=True) for x in question.select('.button5 b'))
    hits = keyword_hits(qtext + ' ' + tags, config.get('tabit_terms', TABIT_TERMS))
    qdate = tabit_date(question)
    if not qdate:
        raise ValueError('missing_date: у вопроса не найдена дата публикации')
    if not hits or not within_period(qdate,config['start'],config['end']):
        return []
    answers = soup.select('#resultdivcomment > .answ1[id^="commentpad"]')
    rows = []
    for kind, node in [('question',question)] + [('answer',a) for a in answers]:
        ident = qid if kind == 'question' else re.search(r'(\d+)$',node['id'])[1]
        date = tabit_date(node)
        if not date:
            note_error('tabiturient',card['url'],f'{kind} {ident}: дата отсутствует')
            continue
        if not within_period(date,config['start'],config['end']):
            continue
        author = node.select_one('[itemprop="author"]')
        author_text = author.get_text(' ',strip=True) if author else ''
        university = bool(re.search(r'при[её]мн\w* комисси',author_text,re.I))
        comments_link = node.select_one('a[onclick^="showdopcomment"] b')
        vote = node.select_one('[itemprop="upvoteCount"]')
        rows.append(dict(record_id=f'{kind}_{ident}', row_type=kind, question_id=qid,
                         answer_id=ident if kind=='answer' else None,
                         url=card['url'] + (f'#commentpad{ident}' if kind=='answer' else ''),
                         date=date, text=tabit_text(node.select_one('[itemprop="text"]')),
                         tags=tags, author_type='university_label' if university else ('question_author' if kind=='question' else 'user'),
                         organization=author_text if university else None, likes=parse_count(vote.text) if vote else None,
                         replies_reported=card.get('replies_reported'), answers_in_dom=len(answers),
                         nested_comments_reported=parse_count(comments_link.text) if comments_link else None,
                         matched_terms='; '.join(hits),
                         collected_at=datetime.now(MOSCOW).isoformat(timespec='seconds'),
                         comments_scope='answers in initial DOM; nested comments not loaded'))
    return rows


def collect_tabiturient(driver, config):
    folder = Path(config['output_dir']); folder.mkdir(parents=True,exist_ok=True)
    mode = config.get('tabit_mode','archive_ids')
    if mode in ['sample_ids','archive_ids']:
        # Верхняя граница взята из публичного списка, а не задана устаревшим числом.
        manifest_path = folder/'tabiturient_sample_ids.json'
        if mode == 'sample_ids' and manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            maximum,ids,latest = manifest['maximum'],manifest['ids'],{}
        else:
            soup = load_page(driver,TABIT_URL,'#resultsliv a[href*="/question/n/?"]')
            latest = tabit_cards(soup)
            maximum = max(map(int,latest))
            if mode == 'sample_ids':
                ids = random.Random(42).sample(range(1,maximum+1),min(config.get('tabit_sample_size',400),maximum))
                ids = sorted(set(ids + [1,4538,4892,4898,4901,4908,4910,4915]))
                manifest_path.write_text(json.dumps(dict(maximum=maximum,seed=42,ids=ids),ensure_ascii=False),encoding='utf-8')
            else:
                ids = list(range(1,maximum+1))
        candidates = [dict(question_id=str(i),url=f'{TABIT_URL}n/?{i}',replies_reported=latest.get(str(i),{}).get('replies_reported')) for i in ids]
        cards = {c['question_id']:c for c in candidates}
    else:
        cards = discover_tabiturient(driver,config)
        candidates = [c for c in cards.values() if within_period(c['date'],config['start'],config['end'])
                      and keyword_hits(c['text']+' '+c['tags'],config.get('tabit_terms',TABIT_TERMS))]
        candidates.sort(key=lambda x:(x['date'],int(x['question_id'])))
    if config.get('demo'):
        candidates = candidates[-config.get('limit',20):]
    path = folder / 'tabiturient_checkpoint.json'
    signature = [config['start'],config['end'],config.get('tabit_terms',TABIT_TERMS),bool(config.get('demo')),mode,config.get('tabit_sample_size',400)]
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(signature=signature,done=[],rows=[],audit=[])
    if state['signature'] != signature:
        raise ValueError('Изменены настройки: выберите новую output_dir')
    for i,card in enumerate(candidates,1):
        if card['question_id'] in state['done']:
            continue
        try:
            soup = load_page(driver,card['url'],'body')
            question = soup.select_one(f'#voprosdivin{card["question_id"]}')
            if question is None and 'Этот вопрос не существует или был удален' not in soup.get_text(' ',strip=True):
                raise ValueError('Неожиданная страница без вопроса и без явной отметки об удалении; ID оставлен для повтора')
            rows = parse_tabiturient(soup,card,config) if question else []
            seed = card['question_id'] in {'1','4538','4892','4898','4901','4908','4910','4915'}
            for row in rows:
                row['selection_method'] = ('purposive_seed' if seed else 'random_id_seed42') if mode=='sample_ids' else ('archive_ids' if mode=='archive_ids' else 'keyword_in_list')
            state['rows'].extend(rows)
            state['done'].append(card['question_id'])
            state['audit'].append(dict(question_id=card['question_id'],url=card['url'],date=tabit_date(question) if question else None,
                                       status='selected' if rows else ('not_matched_or_out_of_period' if question else 'not_found_confirmed'),rows=len(rows)))
        except (PermissionError, InvalidSessionIdException):
            raise
        except Exception as error:
            note_error('tabiturient',card['url'],str(error))
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8'); temporary.replace(path)
        pd.DataFrame(state['rows']).to_csv(folder/'tabiturient.csv',index=False,encoding='utf-8-sig')
        pd.DataFrame(state['audit']).to_csv(folder/'tabiturient_audit.csv',index=False,encoding='utf-8-sig')
        print(f'Tabiturient: {i}/{len(candidates)} threads, {len(state["rows"])} rows',flush=True)
        time.sleep(config.get('pause',1.5))
    frame = pd.DataFrame(state['rows'])
    if not frame.empty:
        frame = frame.drop_duplicates('record_id').sort_values(['date','question_id','row_type']).reset_index(drop=True)
        for col in ['likes','replies_reported','answers_in_dom','nested_comments_reported']:
            frame[col] = pd.to_numeric(frame[col],errors='coerce').astype('Int64')
    frame.to_csv(folder/'tabiturient.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([dict(source='tabiturient',discovered=len(cards),candidates=len(candidates),
                       completed=len(state['done']),rows=len(frame),start=config['start'],end=config['end'])]).to_csv(folder/'tabiturient_coverage.csv',index=False,encoding='utf-8-sig')
    return frame
