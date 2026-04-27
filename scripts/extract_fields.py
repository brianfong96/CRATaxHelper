"""Extract AcroForm field positions from all 6 CRA PDFs."""
import fitz
import pathlib
import json

forms = [
    ("schedule5", "schedule5-2025.pdf"),
    ("schedule7", "schedule7-2025.pdf"),
    ("schedule8", "schedule8-2025.pdf"),
    ("t777",      "t777-2025.pdf"),
    ("t2209",     "t2209-2025.pdf"),
    ("worksheet_fed", "worksheet-fed-2025.pdf"),
]

results = {}

for form_name, pdf_file in forms:
    pdf_path = pathlib.Path(f"app/static/forms/{pdf_file}")
    if not pdf_path.exists():
        print(f"MISSING: {pdf_path}")
        continue

    doc = fitz.open(str(pdf_path))
    fields = []
    for pg_num, page in enumerate(doc):
        w, h = page.rect.width, page.rect.height
        for widget in page.widgets():
            if widget.field_type_string in ('Text', 'CheckBox'):
                r = widget.rect
                left  = r.x0 / w * 100
                top   = r.y0 / h * 100
                width = (r.x1 - r.x0) / w * 100
                height = (r.y1 - r.y0) / h * 100
                fields.append({
                    "page": pg_num + 1,
                    "name": widget.field_name,
                    "type": widget.field_type_string,
                    "left": round(left, 3),
                    "top":  round(top, 3),
                    "width": round(width, 3),
                    "height": round(height, 3),
                })
    doc.close()
    results[form_name] = fields
    print(f"{form_name}: {len(fields)} fields across pages")

# Save to JSON files for reference
for form_name, fields in results.items():
    out = pathlib.Path(f"app/static/forms/{form_name}-fields.json")
    out.write_text(json.dumps(fields, indent=2))
    print(f"  Saved {out}")

print("\nDone.")
