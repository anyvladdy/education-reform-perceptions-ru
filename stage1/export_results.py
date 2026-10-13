from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).parent/'src'))
from common import *
from prepare_data import prepare_frame, validate_relations

root = Path(__file__).parent
folder = root/'data'/'sample'
destination = root.parent/'outputs'/'01a11318-2071-7052-80fa-6b378dc037f6'/'stage1'
destination.mkdir(parents=True,exist_ok=True)
tables = {}
for source,sheet in [('telegram','Telegram'),('pikabu','Пикабу'),('tabiturient','Табитуриент')]:
    if source=='pikabu' and '--preview' in sys.argv:
        frame = pd.DataFrame(json.loads((folder/'pikabu_checkpoint.json').read_text(encoding='utf-8'))['rows'])
    else:
        frame = pd.read_csv(folder/f'{source}.csv',dtype={c:'string' for c in ['record_id','post_id','question_id','answer_id','parent_comment_id']})
    tables[sheet] = prepare_frame(source,frame)
    tables[sheet].to_csv(destination/f'{source}.csv',index=False,encoding='utf-8-sig')
summary = validate_relations(tables)
print(summary.to_json(orient='records',force_ascii=False,indent=2))
summary.to_json(destination/'summary.json',orient='records',force_ascii=False,indent=2)
save_excel(tables,destination/'База_трёх_источников.xlsx')
schema = json.loads((root/'column_dictionary.json').read_text(encoding='utf-8'))
for sheet,frame in tables.items():
    unknown = set(frame)-set(schema)
    assert not unknown, (sheet,unknown)
periods = pd.DataFrame({name:df.groupby('period').size() for name,df in tables.items()}).reindex(['2018','2019–2021','2022–2026']).fillna(0).astype(int)
periods.to_csv(destination/'period_coverage.csv',encoding='utf-8-sig')
notes = '## Результат исходного сбора 07.10.2026\n\n'
notes += '| Источник | Строки | Единицы наблюдения | Первое сообщение | Последнее сообщение |\n|---|---:|---|---|---|\n'
for row in summary.to_dict('records'):
    kinds = {'post':'посты','comment':'комментарии','question':'вопросы','answer':'ответы'}
    units = '; '.join(f'{kinds[k]}: {v}' for k,v in row['units'].items())
    notes += f'| {row["source"]} | {row["rows"]} | {units} | {row["first_date"]} | {row["last_date"]} |\n'
notes += '\nРаспределение **собранных сообщений**, включая связанные ответы и комментарии. Это характеристика выборки, а не частота мнений в генеральной совокупности.\n\n| Этап | Telegram | Пикабу | Табитуриент |\n|---|---:|---:|---:|\n'
for period,row in periods.iterrows():
    notes += f'| {period} | {row["Telegram"]} | {row["Пикабу"]} | {row["Табитуриент"]} |\n'
notes += '\nУ выбранных Telegram-витрин не наблюдается публикаций за 2018–2019; в выборке Табитуриента ранняя доступная дата начинается в 2020 году. Значения 0 здесь означают отсутствие **собранных** единиц; полноценную межплатформенную динамику с 2018 года по ним построить нельзя.\n'
notes += '\nНа «Табитуриенте» только 7 из 205 ответов имеют явную метку приёмной комиссии; они относятся к двум организациям. Остальные ответы нельзя использовать как высказывания вузов. Это ограничивает проверку институциональных стратегий на данном источнике.\n'
(root/'results_notes.txt').write_text(notes,encoding='utf-8')
# Обратное чтение проверяет сохранённые значения, типы и отсутствие потери строк.
restored = pd.read_excel(destination/'База_трёх_источников.xlsx',sheet_name=None)
for sheet,frame in tables.items():
    assert len(restored[sheet]) == len(frame)
    assert restored[sheet].columns.is_unique
    assert not restored[sheet]['record_id'].duplicated().any()
    assert pd.to_datetime(restored[sheet]['date_local']).between('2018-01-01','2026-10-06').all()
    for col in ['text','url','record_id']:
        actual = restored[sheet][col].fillna('').astype(str)
        for part in sorted((c for c in restored[sheet] if c.startswith(col+'_part_')),key=lambda c:int(c.rsplit('_',1)[1])):
            actual += restored[sheet][part].fillna('').astype(str)
        expected = frame[col].fillna('').astype(str).map(lambda x:re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',x))
        assert actual.tolist() == expected.tolist(), (sheet,col)
print('EXCEL ROUNDTRIP OK')
