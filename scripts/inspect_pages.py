"""Inspect page/image structure of HTML templates."""
import re
import sys

for tname in ['t777', 'worksheet_fed', 'schedule8', 'schedule5', 't2209']:
    html = open(f'app/templates/{tname}.html', encoding='utf-8').read()
    pages = re.findall(r'<div[^>]+class="pdf-page"[^>]*>.*?(?=<div[^>]+class="pdf-page"|</main>)', html, re.DOTALL)
    print(f'\n=== {tname}: {len(pages)} pages ===')
    for i, pg in enumerate(pages):
        img = re.search(r'src="([^"]+)"', pg)
        inputs = re.findall(r'id="([^"]+)"', pg)
        img_name = img.group(1).split('/')[-1] if img else '?'
        inp_count = len(inputs)
        inp_preview = ','.join(inputs[:3])
        print(f'  Page {i+1}: img={img_name} inputs={inp_count} [{inp_preview}]')
