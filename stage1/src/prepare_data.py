"""Проверка ключей, временных границ и добавление явных исследовательских полей."""
from common import *

FOCUS_CONTEXT = ['колледж','техникум','СПО','ПТУ','вуз','университет','высшее образован','10 класс','десятый класс','профориент','Профессионалитет','рабочие профессии']
FOCUS_CHOICE = ['поступ','приём','прием','выбор','выбира','выбрал','отбор','отказ','не берут','не приняли','балл','бюджет','платн','диплом','престиж','передум','стоит','нужен','нужно','зарплат','зарабат','успех','карьер','востреб','трудоустр','дефицит','профориент','хочу','хотел','возможност','доступ','професси','перевод','перевест']
SCREEN_CONTEXT = ['колледж','техникум','вуз','университет','образован','ПТУ','СПО','школ','ЕГЭ','ОГЭ','абитуриент','училищ','диплом','10 класс','10-й класс','десятый класс']
SCREEN_CHOICE = ['поступ','вступительн','приемная комисс','приёмная комисс','отбор','зачисл','абитуриент','профориент','диплом','престиж','трудоустрой','востребованност','рабочие профессии','Профессионалитет','бюджетные места','платное обучение','платное образование','конкурс аттестатов','не берут в','не взяли в','не приняли в','после 9','после девятого','10 класс','10-й класс','десятый класс','после колледжа','вуз после','из колледжа в','из вуза в','перевестись в','перевод в вуз','перевод в колледж','выбор профессии','смена профессии','ценность образования','образование не нужно','образование нужно','вуз не нужен','нужен диплом']
MANUAL_EXCLUDE = {
    '10641449':'Запрос названия американской комедии; образовательный выбор не обсуждается',
    '6355320':'Бытовая история о телефоне и конфликте в семье; образование лишь в тегах',
    '6360292':'Анекдот о коньяке преподавателя; не об образовательной траектории',
    '9080062':'Реклама волонтёрской работы; колледж только в тегах',
}
PILOT_RELEVANT = {'5622243','10410436','11441073','11554177','12639540','14388561'}


def prepare_frame(source, frame):
    frame = frame.copy()
    if source == 'telegram':
        frame['record_id'] = frame['channel'].astype(str) + '/' + frame['post_id'].astype(str)
        frame['row_type'] = 'post'
    assert frame.columns.is_unique, f'{source}: повторяются столбцы'
    assert not frame['record_id'].duplicated().any(), f'{source}: повторяются ID'
    assert not frame.duplicated().any(), f'{source}: повторяются строки'
    date_column = 'published_at' if source == 'telegram' else 'date'
    assert frame[date_column].map(lambda x:within_period(x,'2018-01-01','2026-10-06')).all(), f'{source}: дата вне периода'
    dates = frame[date_column].map(lambda x:datetime.fromisoformat(str(x).replace('Z','+00:00')))
    frame['date_local'] = dates.map(lambda d:(d.astimezone(MOSCOW) if d.tzinfo else d).date().isoformat())
    frame['year'] = frame['date_local'].str[:4].astype(int)
    frame['period'] = frame['year'].map(lambda y:'2018' if y==2018 else ('2019–2021' if y<=2021 else '2022–2026'))
    frame['hashtags'] = frame['text'].fillna('').map(lambda s:'; '.join(dict.fromkeys(re.findall(r'(?<!\w)#\w+',s))))
    frame['text_available'] = frame['text'].fillna('').str.strip().str.len().gt(0)
    # Это признак для сортировки кандидатов; он не заменяет ручное кодирование охлаждения.
    context = frame['text'].fillna('') + ' ' + frame.get('title',pd.Series('',index=frame.index)).fillna('')
    context = context.map(lambda s:' '.join(s.split()))
    frame['focus_candidate'] = context.map(lambda s:bool(keyword_hits(s,FOCUS_CONTEXT) and keyword_hits(s,FOCUS_CHOICE)))
    if source == 'pikabu':
        posts = frame[frame.row_type.eq('post')]
        screen,review = {},{}
        for _,row in posts.iterrows():
            pid = str(row.post_id)
            text = ' '.join((str(row.title) + ' ' + str(row.text)).split())  # Теги не подменяют содержание.
            screen[pid] = bool(keyword_hits(text,SCREEN_CONTEXT) and keyword_hits(text,SCREEN_CHOICE))
            review[pid] = 'not_reviewed'
            if pid in MANUAL_EXCLUDE:
                screen[pid],review[pid] = False,'excluded: '+MANUAL_EXCLUDE[pid]
            elif pid in PILOT_RELEVANT:
                screen[pid],review[pid] = True,'included: проверен в предварительном пилоте'
        frame['research_screen'] = frame['post_id'].astype(str).map(screen)
        frame['manual_review'] = frame['post_id'].astype(str).map(review)
    if source == 'telegram':
        snapshots = pd.to_datetime(frame['collected_at'],utc=True)
        publications = pd.to_datetime(frame['published_at'],utc=True)
        frame['age_days_at_collection'] = (snapshots-publications).dt.total_seconds().div(86400).round(2)
        frame['at_least_14_days'] = frame['age_days_at_collection'] >= 14
    leading = ['record_id','row_type','date_local','period']
    leading += [c for c in ['channel','title','text','url'] if c in frame]
    frame = frame[leading + [c for c in frame.columns if c not in leading]]
    return frame.sort_values(['date_local','record_id']).reset_index(drop=True)


def validate_relations(tables):
    pikabu = tables['Пикабу']
    assert set(pikabu.loc[pikabu.row_type=='comment','post_id']) <= set(pikabu.loc[pikabu.row_type=='post','post_id'])
    tabit = tables['Табитуриент']
    assert set(tabit.loc[tabit.row_type=='answer','question_id']) <= set(tabit.loc[tabit.row_type=='question','question_id'])
    return pd.DataFrame([dict(source=name,rows=len(df),units=df['row_type'].value_counts().to_dict(),
                              first_date=df.date_local.min(),last_date=df.date_local.max(),focus_candidates=int(df.focus_candidate.sum()))
                         for name,df in tables.items()])
