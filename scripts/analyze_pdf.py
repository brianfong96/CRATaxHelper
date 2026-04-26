"""Analyze CRA PDF forms - extract field positions and render page images."""
import json
import re
import pymupdf

def analyze_pdf(path, label):
    doc = pymupdf.open(path)
    fields = []

    for page_num in range(doc.page_count):
        page = doc[page_num]
        for widget in page.widgets():
            fields.append({
                'page': page_num + 1,
                'name': widget.field_name,
                'type': widget.field_type_string,
                'rect': [round(x, 2) for x in widget.rect],
                'value': widget.field_value,
            })

    print(f"{label}: {doc.page_count} pages, {len(fields)} fields")
    for f in fields[:30]:
        print(f"  p{f['page']} [{f['type']:12s}] {f['name']!r:60s}  rect={f['rect']}")
    if len(fields) > 30:
        print(f"  ... {len(fields)-30} more fields")
    print()

    with open(f"{label}_fields.json", "w") as fh:
        json.dump(fields, fh, indent=2)

    # Render each page to PNG at 150 DPI
    for page_num in range(doc.page_count):
        page = doc[page_num]
        mat = pymupdf.Matrix(150/72, 150/72)  # 150 DPI
        pix = page.get_pixmap(matrix=mat)
        out_path = f"app/static/forms/screenshots/{label}_page{page_num+1}.png"
        pix.save(out_path)
        print(f"  Rendered page {page_num+1} -> {out_path} ({pix.width}x{pix.height})")

    return fields


import os
os.makedirs("app/static/forms/screenshots", exist_ok=True)

t1_fields = analyze_pdf("app/static/forms/t1-2025.pdf", "t1")
bc428_fields = analyze_pdf("app/static/forms/bc428-2025.pdf", "bc428")

# Show fields with numeric line numbers
print("\n=== T1 fields with line numbers ===")
for f in t1_fields:
    nums = re.findall(r'\b(\d{4,5})\b', f['name'])
    if nums:
        print(f"  Line {nums[0]:5s}  p{f['page']}  {f['name']!r}")

print("\n=== BC428 fields with line numbers ===")
for f in bc428_fields:
    nums = re.findall(r'\b(\d{4,5})\b', f['name'])
    if nums:
        print(f"  Line {nums[0]:5s}  p{f['page']}  {f['name']!r}")
