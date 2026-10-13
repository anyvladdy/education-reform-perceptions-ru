from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from common import create_driver, load_page

folder = Path(__file__).parent / 'inspection'
folder.mkdir(exist_ok=True)
driver = create_driver()
try:
    for name, url in [('list','https://tabiturient.ru/question/'), ('question','https://tabiturient.ru/question/n/?4538'), ('nested','https://tabiturient.ru/question/n/?4901')]:
        soup = load_page(driver, url, 'body')
        (folder / f'{name}.html').write_text(str(soup), encoding='utf-8')
        print(name, driver.current_url, soup.get_text(' ', strip=True)[-22000:], flush=True)
finally:
    driver.quit()
