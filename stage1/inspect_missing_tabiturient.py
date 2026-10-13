from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'src'))
from common import *
driver = create_driver()
try:
    for qid in [1,18,27]:
        soup = load_page(driver,f'https://tabiturient.ru/question/n/?{qid}','body')
        text = soup.get_text(' ',strip=True)
        Path(f'stage1/inspection/missing_{qid}.html').write_text(str(soup),encoding='utf-8')
        print(qid,driver.current_url,driver.title,text[:7000],flush=True)
finally:
    driver.quit()
