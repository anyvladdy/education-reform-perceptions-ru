"""Упаковывает только нужные пользователю материалы, без среды и временных HTML."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
import nbformat
from openpyxl import load_workbook

root = Path(__file__).parent
dest = root.parent/'outputs'/'01a11318-2071-7052-80fa-6b378dc037f6'/'stage1'
report = json.loads((dest/'Проверка_запуска.json').read_text(encoding='utf-8'))
nb = nbformat.read(dest/'Этап_1_три_парсера.ipynb',4)
assert report['status']=='passed' and report['errors']==0
assert report['code_sha256'] == hashlib.sha256('\n'.join(c.source for c in nb.cells if c.cell_type=='code').encode()).hexdigest()
assert report['input_excel_sha256'] == hashlib.sha256((dest/'База_трёх_источников.xlsx').read_bytes()).hexdigest()
book = load_workbook(dest/'База_трёх_источников.xlsx',read_only=True,data_only=False)
assert book.sheetnames == ['Telegram','Пикабу','Табитуриент']
assert not any(c.data_type=='f' for s in book for row in s for c in row), 'В сыром тексте появилась формула'
book.close()

shutil.copy2(root/'Памятка_к_сдаче.txt',dest/'Памятка_к_сдаче.txt')
shutil.copy2(root/'column_dictionary.json',dest/'Словарь_переменных.json')
scripts = dest/'scripts'; scripts.mkdir(exist_ok=True)
(scripts/'src').mkdir(exist_ok=True)
for file in ['collect.py','requirements.txt']:
    shutil.copy2(root/file,scripts/file)
for file in ['common.py','telegram_parser.py','pikabu_parser.py','tabiturient_parser.py','prepare_data.py']:
    shutil.copy2(root/'src'/file,scripts/'src'/file)
protocol = dest/'protocol'; protocol.mkdir(exist_ok=True)
for file in (root/'data'/'sample').glob('*'):
    if file.is_file() and file.suffix in ['.csv','.json'] and file.name not in ['telegram.csv','pikabu.csv','tabiturient.csv','qa_pikabu.csv'] and 'checkpoint' not in file.name:
        shutil.copy2(file,protocol/file.name)

files = [f for f in dest.rglob('*') if f.is_file() and f.name!='manifest.json' and f.suffix not in ['.png','.ndjson','.zip','.pyc'] and '__pycache__' not in str(f)]
manifest = {str(f.relative_to(dest)):hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.name!='manifest.json'}
(dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
archive = dest.parent/'Этап_1_проект.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
    for file in files+[dest/'manifest.json']:
        output.write(file,Path('Этап_1')/file.relative_to(dest))
print(archive)
print('Files:',len(files)+1,'bytes:',archive.stat().st_size)
