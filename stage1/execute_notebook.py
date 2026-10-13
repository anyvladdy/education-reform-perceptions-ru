"""Проверка всех ячеек в новом ядре. Путь среды не попадает в notebook."""
import json
import os
import shutil
import sys
import hashlib
import platform
from datetime import datetime,timezone,timedelta
from pathlib import Path
import nbformat
from nbclient import NotebookClient

root = Path(__file__).parent.resolve()
destination = root.parent/'outputs'/'01a11318-2071-7052-80fa-6b378dc037f6'/'stage1'
qa = root/'qa'/'notebook'
qa.mkdir(parents=True,exist_ok=True)
kernel = root/'qa'/'jupyter'/'kernels'/'project'
kernel.mkdir(parents=True,exist_ok=True)
(kernel/'kernel.json').write_text(json.dumps(dict(argv=[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],display_name='Project Python',language='python')),encoding='utf-8')
os.environ['JUPYTER_PATH'] = str(root/'qa'/'jupyter')
shutil.copy2(destination/'База_трёх_источников.xlsx',qa/'База_трёх_источников.xlsx')
path = destination/'Этап_1_три_парсера.ipynb'
notebook = nbformat.read(path,as_version=4)
client = NotebookClient(notebook,timeout=1800,kernel_name='project',resources={'metadata':{'path':str(qa)}})
report_path = destination/'Проверка_запуска.json'
report_path.write_text(json.dumps({'status':'running'},ensure_ascii=False),encoding='utf-8')
try:
    client.execute()
except Exception as error:
    report_path.write_text(json.dumps({'status':'failed','error':str(error)},ensure_ascii=False,indent=2),encoding='utf-8')
    raise
notebook.metadata['kernelspec'] = dict(display_name='Python 3',language='python',name='python3')
nbformat.write(notebook,path)
report = {'status':'passed','all_cells_executed':True,'code_cells':sum(c.cell_type=='code' for c in notebook.cells),
          'errors':sum(o.output_type=='error' for c in notebook.cells if c.cell_type=='code' for o in c.outputs),
          'tested_at_msk':datetime.now(timezone(timedelta(hours=3))).isoformat(timespec='seconds'),
          'mode':'FULL_RUN=False; N_DEMO=20; three live Selenium sessions',
          'python_version':platform.python_version(),
          'code_sha256':hashlib.sha256('\n'.join(c.source for c in notebook.cells if c.cell_type=='code').encode()).hexdigest(),
          'input_excel_sha256':hashlib.sha256((qa/'База_трёх_источников.xlsx').read_bytes()).hexdigest()}
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report))
