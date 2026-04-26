"""Understand the full T1 and BC428 field structure for overlay implementation."""
import json, re

def summarize(fname, label):
    with open(fname) as f:
        fields = json.load(f)
    
    print(f"\n=== {label} FIELDS BY PAGE ===")
    for page in range(1, 15):
        page_fields = [f for f in fields if f['page'] == page and f['type'] == 'Text']
        if not page_fields:
            continue
        print(f"\nPage {page}: {len(page_fields)} text fields")
        for fld in page_fields:
            parts = fld['name'].split('.')
            short = parts[-1]
            r = fld['rect']
            # extract line numbers from field name
            nums = re.findall(r'\b(\d{4,5})\b', fld['name'])
            num_str = '/'.join(nums) if nums else '-'
            print(f"  [{num_str:10s}] {short:55s} rect=[{r[0]:5.0f},{r[1]:5.0f},{r[2]:5.0f},{r[3]:5.0f}]")

summarize('t1_fields.json', 'T1')
summarize('bc428_fields.json', 'BC428')
