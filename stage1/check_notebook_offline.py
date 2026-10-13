"""Проверяет автономность определений notebook на реальных сохранённых страницах."""
from pathlib import Path
import nbformat
import pandas as pd

root = Path(__file__).parent
file = root.parent/'outputs'/'01a11318-2071-7052-80fa-6b378dc037f6'/'stage1'/'Этап_1_три_парсера.ipynb'
nb = nbformat.read(file,4)
scope = {}
for cell in nb.cells:
    if cell.cell_type != 'code':
        continue
    if cell.source.startswith('# 6.2.'):
        continue
    code = cell.source
    if code.startswith('# 1.'):
        code = code.replace("saved = pd.read_excel('База_трёх_источников.xlsx', sheet_name=None)","saved = {}")
    if code.startswith('# 7.'):
        code = code.split("output_name =")[0]
    exec(compile(code,'notebook cell','exec'),scope)

html = (root/'inspection'/'question.html').read_text(encoding='utf-8')
rows = scope['parse_tabiturient'](scope['BeautifulSoup'](html,'html.parser'),dict(question_id='4538',url='https://tabiturient.ru/question/n/?4538'),scope['config'])
assert len(rows)==2
assert 'Будем рады' in rows[1]['text']
frame = scope['prepare_frame']('tabiturient',pd.DataFrame(rows))
assert frame['year'].eq(2026).all()
assert frame.record_id.is_unique
print('Offline notebook definitions OK; actual full answer and date preparation verified')
