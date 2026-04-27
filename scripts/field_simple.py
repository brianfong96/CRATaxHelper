"""Full field data for schedule5, schedule7, t2209."""
import json, pathlib

for n in ['schedule5', 'schedule7', 't2209']:
    f = json.loads(pathlib.Path(f'app/static/forms/{n}-fields.json').read_text())
    pages = sorted(set(x['page'] for x in f))
    print(f'=== {n} ({len(f)} fields) pages: {pages}')
    for x in f:
        nm = x['name'].split('.')[-1].replace('[0]','')
        print(f"  P{x['page']} {x['type']:8s} {nm:40s} L={x['left']:6.2f} T={x['top']:6.2f} W={x['width']:6.2f} H={x['height']:5.2f}")
    print()
