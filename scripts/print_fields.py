"""Print field positions for all forms."""
import json
import pathlib

forms = ["schedule5", "schedule7", "schedule8", "t777", "t2209", "worksheet_fed"]

for form_name in forms:
    path = pathlib.Path(f"app/static/forms/{form_name}-fields.json")
    if not path.exists():
        continue
    fields = json.loads(path.read_text())
    print(f"\n{'='*80}")
    print(f"FORM: {form_name}  ({len(fields)} fields)")
    print(f"{'='*80}")
    for f in fields:
        print(f"  P{f['page']} [{f['type']:8s}] {f['name']:45s} left={f['left']:6.2f}% top={f['top']:6.2f}% w={f['width']:6.2f}% h={f['height']:5.2f}%")
