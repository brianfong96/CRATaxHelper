"""Extract full text from PDF pages to map field line numbers to CRA line numbers."""
import json
import re
import sys
import pymupdf

# Set stdout encoding to utf-8
sys.stdout.reconfigure(encoding='utf-8')

def extract_full_text(pdf_path, label):
    doc = pymupdf.open(pdf_path)
    print(f"\n=== {label} FULL TEXT ===")
    for page_num in range(doc.page_count):
        page = doc[page_num]
        text = page.get_text("text")
        print(f"\n--- Page {page_num + 1} ---")
        print(text[:5000])

def extract_line_number_mapping(pdf_path, label):
    """Find CRA line numbers (5-digit starting with 5 or 6) near each field."""
    doc = pymupdf.open(pdf_path)
    print(f"\n=== {label} - CRA Line Number Mapping ===")
    
    results = []
    for page_num in range(doc.page_count):
        page = doc[page_num]
        all_text = page.get_text("text")
        
        # Find all CRA line numbers (5-digit: 10100-99999)
        cra_nums = re.findall(r'\b(\d{5})\b', all_text)
        print(f"Page {page_num+1} CRA numbers found: {cra_nums[:50]}")
        
        # For each widget, look for nearby CRA numbers
        for widget in page.widgets():
            if widget.field_type_string != 'Text':
                continue
            wr = widget.rect
            # Wide search area
            search_rect = pymupdf.Rect(0, wr.y0 - 15, 600, wr.y1 + 15)
            row_text = page.get_text("text", clip=search_rect)
            cra_in_row = re.findall(r'\b(\d{5})\b', row_text)
            
            parts = widget.field_name.split('.')
            short = '.'.join(parts[-3:])
            if cra_in_row:
                print(f"  {short} -> CRA lines: {cra_in_row} | text: {row_text[:60].strip()!r}")
                results.append({
                    'field': widget.field_name,
                    'short': short,
                    'cra_lines': cra_in_row,
                    'rect': list(widget.rect),
                    'page': page_num + 1,
                })
    return results

# Run mapping
bc428_map = extract_line_number_mapping("app/static/forms/bc428-2025.pdf", "BC428")
t1_map = extract_line_number_mapping("app/static/forms/t1-2025.pdf", "T1")

# Save mappings
with open("bc428_line_map.json", "w", encoding='utf-8') as f:
    json.dump(bc428_map, f, indent=2, ensure_ascii=False)
with open("t1_line_map.json", "w", encoding='utf-8') as f:
    json.dump(t1_map, f, indent=2, ensure_ascii=False)

print(f"\nBC428 mapped fields: {len(bc428_map)}")
print(f"T1 mapped fields: {len(t1_map)}")
