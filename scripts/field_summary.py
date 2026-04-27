"""Compact summary of fields per form."""
import json
import pathlib

for form_name in ['schedule5', 'schedule7', 'schedule8', 't777', 't2209', 'worksheet_fed']:
    path = pathlib.Path(f'app/static/forms/{form_name}-fields.json')
    fields = json.loads(path.read_text())
    pages = sorted(set(f['page'] for f in fields))
    print(f'=== {form_name} ({len(fields)} fields, pages {pages}) ===')
    for f in fields:
        name = f['name'].split('.')[-1].replace('[0]','')
        print(f"  P{f['page']} {f['type']:8s} {name:40s} L={f['left']:6.2f} T={f['top']:6.2f} W={f['width']:6.2f} H={f['height']:5.2f}")
    print()
