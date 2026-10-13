"""Собирает автономный учебный notebook; не требуется для его запуска."""
import ast
import json
import pprint
from pathlib import Path
import nbformat as nbf

ROOT = Path(__file__).parent
DEST = ROOT.parent/'outputs'/'01a11318-2071-7052-80fa-6b378dc037f6'/'stage1'
DEST.mkdir(parents=True,exist_ok=True)


def pick(file,names):
    text = (ROOT/'src'/file).read_text(encoding='utf-8')
    tree = ast.parse(text)
    pieces = []
    for node in tree.body:
        name = getattr(node,'name',None)
        if isinstance(node,ast.Assign):
            name = node.targets[0].id if isinstance(node.targets[0],ast.Name) else None
        if name in names:
            segment = ast.get_source_segment(text,node)
            if isinstance(node,ast.Assign) and isinstance(node.value,(ast.List,ast.Dict,ast.Set)):
                try:
                    segment = name + ' = ' + pprint.pformat(ast.literal_eval(node.value),width=110,compact=True,sort_dicts=False)
                except (ValueError,TypeError):
                    pass
            pieces.append(segment)
    return '\n\n'.join(pieces)


cells = []
def md(text): cells.append(nbf.v4.new_markdown_cell(text))
def code(text): cells.append(nbf.v4.new_code_cell(text))

md('''# Первый этап: сбор цифровых следов переоценки ВО и СПО

**Три источника:** официальные Telegram-каналы Минпросвещения и Минобрнауки, публичные обсуждения Пикабу, вопросы и ответы «Табитуриента».

**Период публикаций:** 01.01.2018–06.10.2026 включительно, по московскому времени. Периодизация: 2018; 2019–2021; 2022–2026. Внутри второго этапа 2019 — допандемийный год, 2020–2021 — пандемийные годы. При последующем анализе их следует разделять.

Исходные документы: [исследовательский бриф](https://docs.google.com/document/d/1CoG8eakAeDvc_yytix-rmGgn6U09XQtnUfxVUEBjMuk/edit) и [требования преподавателя](https://docs.google.com/document/d/1Q6FDDf87wQtC3-ADtgcZIBB-ukvj-v6AXy4f21X8mI8/edit). Последующие решения команды имеют приоритет: расширенный период, срез по 06.10.2026, тематическая выборка вместо полного архива.

Это корпус **кандидатов для содержательного кодирования**. Совпадение слов не доказывает охлаждение притязаний, а число найденных текстов не измеряет популярность мнения в обществе. Сохраняются и критика, и защита ВО, и положительные аргументы о СПО.

## План до кода

1. Импортировать библиотеки; задать период, ключевые слова и режим запуска. Прочитать готовую выборку из Excel рядом с notebook. В демонстрации взять до 20 родительских публикаций каждого источника, равномерно разнесённых по сохранённому списку.
2. Открывать публичные страницы через Selenium с явным ожиданием элемента. BeautifulSoup разбирает только полученный `page_source`; pandas формирует таблицы. Прямых API/AJAX-запросов и работы с аккаунтами нет. Функции общих проверок нормализуют счётчики и московские даты; журнал фиксирует ошибки.
3. Для Telegram прочитать карточки `data-post`: дату публикации, полный текст, просмотры, реакции, медиа, признак пересылки. Альбом — одна строка. Для повторения выборки использовать сохранённые URL; для расширения — листать всю веб-ленту назад с `before` и применять словарь локально. Не использовать неполную поисковую выдачу как архив.
4. Для Пикабу прочитать полный пост, заголовок, теги, дату, рейтинг и число комментариев. Сохранить только первоначально загруженные комментарии с известной датой внутри периода, связав их с постом. Для расширения собирать ссылки из теговых лент по страницам. Отбор требует образовательного контекста и слов выбора, оценки или препятствий.
5. Для «Табитуриента» прочитать вопрос и каждый ответ отдельной строкой с общим `question_id`. Взять скрытое продолжение длинного текста из DOM, удалить только надпись «Показать полностью». Отдельно сохранить метку приёмной комиссии и счётчик вложенных комментариев; сами вложенные комментарии не подгружать. В режиме расширения обойти ID до максимального, видимого в списке.
6. Сформировать три DataFrame, проверить уникальность ключей и столбцов, даты и связи ответов с родительскими сообщениями. Добавить год, этап, хэштеги и вспомогательный признак тематического контекста. Этот признак не является содержательным кодом охлаждения.
7. Сохранить таблицы в один Excel с тремя листами и в CSV. Показать только объяснённые сводки: объём, виды сообщений и границы дат. Демонстрация сохраняется отдельно и не заменяет готовую исследовательскую выборку.

## Как запустить

Положить этот notebook и `База_трёх_источников.xlsx` в одну папку. Нужны Chrome и перечисленные ниже пакеты. Команда установки приведена только как справка и автоматически не выполняется:

```text
pip install selenium pandas beautifulsoup4 openpyxl
```

`Kernel → Restart & Run All` запускает демонстрацию. `FULL_RUN = True` повторно читает всю сохранённую выборку. Дополнительно `EXPAND_ARCHIVE = True` включает более долгий обход архивов; для Пикабу предел страниц задаётся явно. Для длительного сбора с возобновлением есть отдельные скрипты в приложенном архиве проекта. Все функции, нужные этому notebook, находятся ниже: внешние модули проекта ему не требуются.

При изменении вёрстки или проверке доступа ошибка остаётся видимой. Нельзя гарантировать вечную неизменность сайтов; конкретные селекторы проверены живыми загрузками 07.10.2026.''')

code('''# 1. Импорт, параметры и чтение готовой тематической выборки
import csv, json, os, re, time
from copy import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException, InvalidSessionIdException
from IPython.display import display

FULL_RUN = False
EXPAND_ARCHIVE = False
N_DEMO = 20
START, END = '2018-01-01', '2026-10-06'
MAX_TAG_PAGES = 500  # Явный предел расширения, а не обещание полного архива.
PAUSE = 2
MOSCOW = timezone(timedelta(hours=3))
ERROR_DIR = Path('logs')
saved = pd.read_excel('База_трёх_источников.xlsx', sheet_name=None)
config = dict(start=START, end=END)

def take_sample(items):
    if FULL_RUN or len(items) <= N_DEMO:
        return items
    if N_DEMO <= 1:
        return items[:max(0,N_DEMO)]
    return [items[round(i*(len(items)-1)/(N_DEMO-1))] for i in range(N_DEMO)]
'''+pick('common.py',{'TERMS'})+'''
config['terms'] = TERMS
# Вывод: размер готовой выборки, которую будем проверять повторным чтением сайтов.
display(pd.DataFrame({'источник': saved.keys(), 'строк в готовой базе': [len(x) for x in saved.values()]}))''')

md('''## 2. Общие операции

Драйвер не использует личный профиль. Отсутствующее число сохраняется как пропуск; `0` остаётся нулём. Обозначение `1.54K` преобразуется в приблизительное число 1540, а исходное отображение сохраняется отдельным полем. Изменение часового пояса учитывается до сравнения с границей 06.10.2026. Журнал ошибок служит для проверки пропусков.''')
code('# 2. Функции: запуск браузера, ожидание, нормализация и журнал\n'+pick('common.py',{'create_driver','load_page','parse_count','within_period','keyword_hits','note_error'}))

md('''## 3. Telegram

**Единица:** пост; каналы различаются переменной `channel`. Комментарии Telegram не входят в базу. `is_forward` — факт пересылки, а не её количество. Отсутствие блока реакций означает, что значение неизвестно. Валентность эмодзи здесь не присваивается.

В исходной выборке: до 30 тематических постов на канал и год, начиная с 31 июля назад в пределах того же года; дополнительное окно заканчивается 06.10.2026. Это сезонная целевая выборка. Её нельзя использовать как знаменатель доли темы во всех сообщениях канала. Даты и причины остановки окон находятся в протоколе сбора. Для повторной проверки notebook читает те же публикации по сохранённым адресам.''')
code('# 3.1. Одна карточка Telegram → словарь\n'+pick('telegram_parser.py',{'read_telegram_message'}))
code('''# 3.2. Цикл по сохранённым публикациям или по архиву канала
def telegram_table(driver):
    rows = {}
    def add(message, allowed=None):
        row = read_telegram_message(message)
        key = f"{row['channel']}/{row['post_id']}"
        hits = keyword_hits(row['text'], TERMS)
        if (allowed is None or key == allowed) and hits and within_period(row['published_at'], START, END):
            row.update(matched_terms='; '.join(hits), query_matches='', selection_method='archive' if EXPAND_ARCHIVE and FULL_RUN else 'saved_sample_reread')
            rows[key] = row

    if FULL_RUN and EXPAND_ARCHIVE:
        for channel in ['minprosrf', 'minobrnaukiofficial']:
            before = None
            while True:
                url = f'https://t.me/s/{channel}' + (f'?before={before}' if before else '')
                soup = load_page(driver, url, '.tgme_channel_history')
                messages = soup.select('.tgme_widget_message[data-post]')
                if not messages:
                    break
                for message in messages:
                    add(message)
                ids = [int(m['data-post'].split('/')[-1]) for m in messages]
                dates = [read_telegram_message(m)['published_at'][:10] for m in messages]
                following = min(ids)
                if max(dates) < START or following == before:
                    break
                before = following
                time.sleep(PAUSE)
    else:
        seeds = take_sample(list(saved['Telegram'][['channel','post_id']].drop_duplicates().itertuples(index=False,name=None)))
        for channel, post_id in seeds:
            key = f'{channel}/{int(post_id)}'
            soup = load_page(driver, f'https://t.me/s/{key}', '.tgme_channel_history')
            for message in soup.select('.tgme_widget_message[data-post]'):
                add(message, key)
            if key not in rows:
                note_error('telegram', f'https://t.me/{key}', 'Публикация не найдена или больше не отвечает условиям отбора')
            time.sleep(PAUSE)
    return pd.DataFrame(rows.values())''')

md('''## 4. Пикабу

**Единица:** пост или первоначально загруженный комментарий (`row_type`). Комментарии связаны с постом через `post_id`, ответы между собой — через `parent_comment_id`. Ники и ID авторов отдельно не собираются.

`total_comments` — счётчик сайта во время сбора; `collected_comments` — число действительно сохранённых комментариев внутри периода. В анализе нужны строки соответствующего типа: нельзя суммировать повторяющийся счётчик поста по его комментариям. Теговые и целенаправленно найденные материалы различаются способом обнаружения. Повторная загрузка может дать иной первоначальный комментарий из-за сортировки сайта.

Исходная рамка Пикабу: страницы 1, 11, 21… по шести тематическим тегам с добором соседних и крайних страниц; дополнительные точки в тегах «Высшее образование» и «Рабочие профессии». Точные посещения записаны в протоколе. Квоты до 60 постов на этап служат ориентиром объёма и не создают случайную выборку. `research_screen` — узкий автоматический отбор по заголовку и тексту с явно записанными ручными исключениями; комментарии наследуют признак поста. Поля `manual_review` и `text_available` помогают отделить непроверенные случаи и записи без доступного текста.''')
code('# 4.1. Словари, извлечение одного поста и доступных комментариев\n'+pick('pikabu_parser.py',{'PIKABU_TAGS','PIKABU_CONTEXT','PIKABU_CHOICE','_pk_text','_pk_date','_pk_topic','_pk_url','parse_pikabu_post'}))
code('''# 4.2. Циклы по теговым страницам и публикациям
def pikabu_table(driver):
    urls = list(saved['Пикабу'].loc[lambda d:d.row_type=='post','url'].drop_duplicates())
    if FULL_RUN and EXPAND_ARCHIVE:
        for tag in PIKABU_TAGS:
            old_pages, seen = 0, set()
            for page in range(1, MAX_TAG_PAGES+1):
                soup = load_page(driver, f'https://pikabu.ru/tag/{quote(tag)}?page={page}', 'article.story, #search-header, .stories-feed')
                cards = soup.select('article.story[data-story-id]')
                ids = {c.get('data-story-id') for c in cards if _pk_date(c)}
                if not ids:
                    note_error('pikabu',driver.current_url,'В доступной странице нет датированных карточек; проверьте, действительно ли это конец ленты')
                    break
                if ids <= seen:
                    break
                seen.update(ids)
                dates = [_pk_date(c)[:10] for c in cards if _pk_date(c)]
                old_pages = old_pages+1 if dates and max(dates)<START else 0
                for card in cards:
                    link = card.select_one('.story__title-link[href]')
                    if link and within_period(_pk_date(card),START,END):
                        url = _pk_url(link['href'])
                        if url:
                            urls.append(url)
                if old_pages >= 2:
                    break
                time.sleep(max(3,PAUSE))
    rows = []
    for url in take_sample(list(dict.fromkeys(urls))):
        try:
            soup = load_page(driver,url,'article.story[data-story-id]')
            rows.extend(parse_pikabu_post(soup,url,config,dict(method='archive' if FULL_RUN and EXPAND_ARCHIVE else 'saved_sample_reread',tags=[])))
        except (TimeoutException,ValueError) as error:
            note_error('pikabu',url,str(error))
        time.sleep(max(3,PAUSE))
    return pd.DataFrame(rows).drop_duplicates('record_id') if rows else pd.DataFrame()''')

md('''## 5. «Табитуриент»

**Единица:** вопрос или ответ; связь — `question_id`. Организация записывается только при явно указанной на сайте приёмной комиссии. Остальные ответы остаются пользовательскими, даже если звучат профессионально.

Исходный отбор: псевдослучайные 400 ID из диапазона до максимального ID, найденного в публичном списке, `seed=42`, затем тематический словарь и проверка дат. Пропуски в нумерации не заменяются вымышленными вопросами. Дополнительно включены проверочные ветки пилота; они маркированы `purposive_seed`. Это выборка из доступных ID, а не всех российских абитуриентов.

Счётчик «Ответов» в ленте может включать вложенные комментарии. Поэтому сохраняются отдельно `replies_reported`, `answers_in_dom` и `nested_comments_reported`. При повторном чтении только страницы ветки `replies_reported` остаётся неизвестным: старый счётчик из готовой базы не переносится как свежий. Сведения из советов не принимаются за проверенные правила поступления.''')
code('# 5.1. Даты, полные тексты и разбор ветки\n'+pick('tabiturient_parser.py',{'TABIT_URL','TABIT_TERMS','MONTHS','tabit_text','tabit_date','tabit_cards','parse_tabiturient'}))
code('''# 5.2. Цикл по вопросам; ответы сохраняются вместе с вопросом
def tabiturient_table(driver):
    questions = saved['Табитуриент'].loc[lambda d:d.row_type=='question','question_id'].drop_duplicates()
    ids = [str(int(i)) for i in questions]
    if FULL_RUN and EXPAND_ARCHIVE:
        soup = load_page(driver,TABIT_URL,'#resultsliv a[href*="/question/n/?"]')
        last_id = max(map(int,tabit_cards(soup)))
        ids = [str(i) for i in range(1,last_id+1)]
    rows = []
    for question_id in take_sample(ids):
        url = f'{TABIT_URL}n/?{question_id}'
        soup = load_page(driver,url,'body')
        if not soup.select_one(f'#voprosdivin{question_id}'):
            note_error('tabiturient',url,'Вопрос отсутствует в доступной странице')
            continue
        items = parse_tabiturient(soup,dict(question_id=question_id,url=url),config)
        for row in items:
            row['selection_method'] = 'archive' if FULL_RUN and EXPAND_ARCHIVE else 'saved_sample_reread'
        rows.extend(items)
        time.sleep(PAUSE)
    return pd.DataFrame(rows).drop_duplicates('record_id') if rows else pd.DataFrame()''')

md('''## 6. Выполнение и проверка

Каждый источник открывается в отдельной короткой браузерной сессии; сессия закрывается и при ошибке. В ходе выполнения сохраняются CSV. Если источник изменит структуру, выполнение остановится с ошибкой, а уже записанные таблицы останутся в папке запуска. Для многочасового обхода рекомендуется версия со страницами состояния из папки `scripts`.

Сводка ниже относится **к текущему повторному сбору**. Готовая выборка из приложенного Excel показана отдельно в начале notebook. Небольшая демонстрация не является полной исследовательской базой.''')
code('# 6.1. Производные поля и проверки качества\n'+pick('prepare_data.py',{'FOCUS_CONTEXT','FOCUS_CHOICE','SCREEN_CONTEXT','SCREEN_CHOICE','MANUAL_EXCLUDE','PILOT_RELEVANT','prepare_frame','validate_relations'}))
code('''# 6.2. Selenium → список словарей → DataFrame → проверки
tables = {}
for source, sheet, collector in [('telegram','Telegram',telegram_table),('pikabu','Пикабу',pikabu_table),('tabiturient','Табитуриент',tabiturient_table)]:
    driver = create_driver()
    try:
        frame = collector(driver)
    finally:
        driver.quit()
    if frame.empty:
        raise ValueError(f'{sheet}: пустая выгрузка, проверьте доступность и журнал')
    tables[sheet] = prepare_frame(source,frame)
    suffix = 'repeat' if FULL_RUN else 'demo'
    tables[sheet].to_csv(f'{source}_{suffix}.csv',index=False,encoding='utf-8-sig')
# Вывод: объём, типы сообщений и реальные временные границы свежего сбора.
display(validate_relations(tables))''')

md('''## 7. Экспорт

В Excel одна строка соответствует одному сообщению. Полный текст хранится в ячейке; высота строк компактная, для чтения длинного текста можно увеличить её или открыть строку формул. Если текст превышает предел Excel, продолжение переносится в `text_part_2`, `text_part_3` и т. д.; CSV сохраняет его единым полем. Текст сайта не исполняется как формула.

Исходный файл `База_трёх_источников.xlsx` не перезаписывается. Демо сохраняется как `Демонстрация.xlsx`, повторный сбор — как `Повторный_сбор.xlsx`.''')
code('# 7. Запись трёх таблиц в один Excel\n'+pick('common.py',{'save_excel'})+'''
output_name = 'Повторный_сбор.xlsx' if FULL_RUN else 'Демонстрация.xlsx'
save_excel(tables,output_name)
# Вывод подтверждает имя созданного файла, а не полноту охвата сайтов.
print(f'Сохранено: {output_name}')''')

schema_path = ROOT/'column_dictionary.json'
if schema_path.exists():
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    md('## Словарь переменных\n\nВсе перечисленные поля относятся к шагам 3–7. Пустая ячейка — отсутствие доступного значения, а не ноль.\n\n| Поле | Значение |\n|---|---|\n'+'\n'.join(f'| `{k}` | {v} |' for k,v in schema.items()))

notes = ROOT/'results_notes.txt'
if notes.exists():
    md(notes.read_text(encoding='utf-8'))
md('''## Зафиксированные затруднения и ограничения

- **Поиск Telegram оказался неполным.** Перешли к чтению обычной ленты. Первый доступный пост Минпросвещения — 07.04.2022; Минобрнауки — 16.03.2020. Это границы наблюдаемой витрины, а не доказательство отсутствия прежней государственной риторики.
- **Старые периоды неодинаково представлены.** Нулевую ячейку покрытия нельзя заменять вымышленной публикацией; источник не позволяет построить сбалансированную панель за 2018–2026.
- **Редкая сетка Пикабу пропускала ранние публикации.** Дополнительно проверены соседние страницы и края доступных лент; точные страницы сохранены в протоколе. Пустая страница и счётчик теговой ленты не приняты за доказательство полного охвата архива.
- **Синхронизация папки временно блокировала промежуточный файл.** В длительном парсере Пикабу добавлены ограниченные повторы записи; продолжение использовало уже сохранённые страницы.
- **Дата видео отличается от даты поста.** В Telegram выбирается дата постоянной ссылки, а не длительность ролика. В Пикабу используется `time[datetime]`, а не ненадёжный числовой атрибут карточки.
- **Длинные ответы были визуально свёрнуты.** Читаем весь DOM и убираем только служебную кнопку; продолжение не теряется и не дублируется.
- **Комментарии доступны не полностью.** На Пикабу — первоначальный DOM; на «Табитуриенте» — ответы без загрузки вложенных комментариев; в Telegram комментарии не собираются. Эти ограничения сохраняются в полях.
- **Дата публикации и дата измерения счётчика различаются.** Публикации/ответы обрезаны 06.10.2026; просмотры, оценки и реакции измерены при сборе 07.10.2026. Восстановить их значение на конец 06.10 по текущей странице нельзя. Посты моложе 14 дней сохранены, но выделены для будущего анализа вовлечённости.
- **Отбор словарём широкий.** `focus_candidate` помогает просматривать тексты, но ручная проверка остаётся обязательной. Нельзя заранее приписывать всем совпадениям «охлаждение», а всем эмодзи — согласие с политикой.
- **Надёжность проверялась на живых страницах и граничных случаях:** переход московской даты, пропуск против нуля, полный скрытый ответ, метка приёмной комиссии, различение ответа и комментария, привязка сообщения к родителю. Перезапуск всех ячеек проверен отдельно; результаты проверки приложены к проекту.

Следующий содержательный этап: проверка связи с российским образовательным контекстом, уточнение релевантности, двойная ручная разметка стратегий и направлений переориентации; только затем оценка согласованности кодировщиков и анализ изменений. Для оценки доли тем во всей коммуникации требуется расширенная рамка отбора с соответствующим знаменателем.''')

notebook = nbf.v4.new_notebook(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.12'}})
nbf.write(notebook,DEST/'Этап_1_три_парсера.ipynb')
print('Notebook written:',DEST/'Этап_1_три_парсера.ipynb')
