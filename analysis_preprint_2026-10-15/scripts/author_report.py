"""Build report blocks from the publication manuscript, preserving its claims."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT.parent / 'DATA_ANALYSIS.md'
LOCAL = ROOT / 'report/data_analysis.md'


def clean(text):
    return re.sub(r'\*\*([^*]+)\*\*|\*([^*]+)\*', lambda m: m.group(1) or m.group(2), text).strip()


def parse(text):
    lines = text.splitlines()
    title = None
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        heading = re.fullmatch(r'(#{1,4})\s+(.+)', line)
        if heading:
            level, value = len(heading[1]), clean(heading[2])
            if level == 1 and title is None:
                title = value
            else:
                blocks.append({'type': 'heading', 'level': max(2, level), 'id': f'section-{len(blocks)}', 'text': value})
            i += 1
            continue
        figure = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line)
        if figure:
            file = Path(figure[2]).stem
            for suffix in ('.png', '.svg'):
                if not (ROOT / 'figures' / (file + suffix)).exists():
                    raise FileNotFoundError(file + suffix)
            caption = clean(figure[1])
            next_i = i + 1
            while next_i < len(lines) and not lines[next_i].strip():
                next_i += 1
            if next_i < len(lines) and clean(lines[next_i]).startswith('Рисунок '):
                caption = clean(lines[next_i])
                i = next_i
            blocks.append({'type': 'figure', 'file': file, 'caption': caption, 'alt': clean(figure[1])})
            i += 1
            continue
        if line.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                row = [clean(cell) for cell in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', cell.replace(' ', '')) for cell in row):
                    table_lines.append(row)
                i += 1
            if table_lines:
                assert all(len(row) == len(table_lines[0]) for row in table_lines), 'Uneven table rows'
                blocks.append({'type': 'table', 'headers': table_lines[0], 'rows': table_lines[1:]})
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#{1,4}\s|!\[|\|)', lines[i].strip()):
            paragraph.append(lines[i].strip())
            i += 1
        blocks.append({'type': 'p', 'text': clean(' '.join(paragraph))})
    if not title:
        raise ValueError('The manuscript requires a title')
    return {'title': title, 'subtitle': 'Анализ данных и результаты исследования', 'blocks': blocks}


def main():
    source = MASTER if MASTER.exists() else LOCAL
    text = source.read_text(encoding='utf-8-sig')
    spec = parse(text)
    spec['source_manuscript'] = str(source.relative_to(ROOT.parent))
    spec['author_review_record'] = '../audit/author_review_confirmation.json'
    (ROOT / 'report/report_content.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    if source == MASTER:
        LOCAL.write_text(text.replace('analysis_preprint_2026-10-15/figures/', '../figures/'), encoding='utf-8')
    print(f'Manuscript: {len(spec["blocks"])} blocks; {sum(b["type"] == "figure" for b in spec["blocks"])} figures.')


if __name__ == '__main__':
    main()
