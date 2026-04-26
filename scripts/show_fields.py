"""Show all fields from the extracted JSON files."""
import json

def show_fields(fname, label):
    with open(fname) as f:
        fields = json.load(f)
    print(f"=== {label} ({len(fields)} total) ===")
    for fld in fields:
        if fld['type'] in ('Text', 'CheckBox', 'RadioButton', 'ComboBox'):
            parts = fld['name'].split('.')
            short = '.'.join(parts[-3:]) if len(parts) > 3 else fld['name']
            y = fld['rect'][1]
            print(f"  p{fld['page']}  y={y:6.1f}  [{fld['type']:9s}]  {short}")
    print()

show_fields('bc428_fields.json', 'BC428')
show_fields('t1_fields.json', 'T1 (first page fields)')
