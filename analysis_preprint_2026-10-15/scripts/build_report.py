"""Build a readable local HTML and editable plain-text report from reviewed prose."""
from pathlib import Path
import json,html,csv,sys
ROOT=Path(__file__).resolve().parents[1]

def esc(s):return html.escape(str(s))
def build():
    spec=json.loads((ROOT/'report/report_content.json').read_text(encoding='utf-8'))
    body=[];plain=[]
    body.append(f'<h1>{esc(spec["title"])}</h1>')
    subtitle=spec.get('subtitle','Анализ данных и результаты исследования')
    body.append(f'<p class="subtitle">{esc(subtitle)}</p>')
    plain.extend([spec['title'],subtitle,''])
    for block in spec['blocks']:
        kind=block['type']
        if kind in ('h2','heading'):
            level=min(4,max(2,block.get('level',2)))
            body.append(f'<h{level} id="{esc(block["id"])}">{esc(block["text"])}</h{level}>');plain+=['',block['text'],'']
        elif kind=='p':body.append(f'<p>{esc(block["text"])}</p>');plain+=[block['text'],'']
        elif kind=='figure':
            stem=block['file'];cap=block['caption']
            body.append(f'<figure><a href="../figures/{stem}.svg"><img src="../figures/{stem}.png" alt="{esc(block["alt"])}"></a><figcaption>{esc(cap)} <a href="../figures/{stem}.svg">SVG</a> · <a href="../figures/{stem}.png">PNG</a></figcaption></figure>')
            plain+=[cap, f'Файл: ../figures/{stem}.png','']
        elif kind=='table':
            body.append('<div class="table-wrap"><table><thead><tr>'+''.join(f'<th>{esc(c)}</th>' for c in block['headers'])+'</tr></thead><tbody>')
            for row in block['rows']:body.append('<tr>'+''.join(f'<td>{esc(c)}</td>' for c in row)+'</tr>')
            body.append('</tbody></table></div>')
            plain+=[' | '.join(block['headers'])]+[' | '.join(map(str,row)) for row in block['rows']]+['']
        elif kind=='links':
            body.append('<ul>'+''.join(f'<li><a href="{esc(x["url"])}">{esc(x["text"])}</a></li>' for x in block['items'])+'</ul>')
            plain += [f'{x["text"]}: {x["url"]}' for x in block['items']]+['']
    style='''
    :root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f2f3f5;color:#17212a;font-family:Georgia,"Times New Roman",serif;line-height:1.65;font-size:18px}
    main{max-width:1080px;margin:32px auto;padding:54px 66px;background:white;box-shadow:0 4px 24px #00000008}h1,h2,th,.subtitle,figcaption{font-family:Arial,sans-serif}h1{font-size:32px;line-height:1.23;font-weight:700;margin:0 0 14px;color:#121820}h2{font-size:23px;line-height:1.3;margin:42px 0 16px;color:#121820}p{margin:0 0 18px}.subtitle{font-size:14px;color:#59636d;margin-bottom:28px}a{color:#255d7e;text-decoration-thickness:1px;text-underline-offset:3px}figure{margin:26px 0 32px}img{width:100%;height:auto;display:block}figcaption{font-size:13px;line-height:1.5;color:#4b5563;margin-top:10px}table{border-collapse:collapse;width:100%;margin:20px 0;font-family:Arial,sans-serif;font-size:14px;line-height:1.45}th,td{border:1px solid #d8dee3;padding:10px 12px;text-align:left;vertical-align:top}th{background:#eaf0f4;font-weight:600}tbody tr:nth-child(even){background:#f8fafb}.table-wrap{overflow-x:auto}ul{padding-left:24px;font-size:16px}
    @media(max-width:760px){body{font-size:17px}main{margin:0;padding:28px 20px}h1{font-size:27px}h2{font-size:21px}}
    @media print{body{background:white;font-size:11pt;line-height:1.5}main{max-width:none;margin:0;padding:0;box-shadow:none}h1{font-size:21pt}h2{font-size:15pt;break-after:avoid}figure{break-inside:avoid}p{orphans:3;widows:3}th,td{font-size:9pt}.subtitle,figcaption{font-size:9pt}a{color:inherit} @page{size:A4;margin:22mm}}
    '''
    page=f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(spec["title"])}</title><style>{style}</style></head><body><main>'+''.join(body)+'</main></body></html>'
    (ROOT/'report/preprint_analysis.html').write_text(page,encoding='utf-8')
    (ROOT/'report/preprint_analysis.txt').write_text('\n'.join(plain),encoding='utf-8')
    print(f'Report: {len(plain)} text blocks; {len(page)} HTML characters.')

if __name__=='__main__':build()
