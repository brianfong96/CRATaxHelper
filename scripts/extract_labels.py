"""Extract text near each field to understand BC428 and T1 line number mappings."""
import json
import re
import pymupdf

def extract_text_near_fields(pdf_path, label):
    doc = pymupdf.open(pdf_path)
    print(f"\n=== {label} - Text extraction ===")
    
    for page_num in range(doc.page_count):
        page = doc[page_num]
        # Get all text blocks with their bounding boxes
        text_dict = page.get_text("dict")
        
        # Get all widgets
        widgets = list(page.widgets())
        if not widgets:
            continue
            
        print(f"\n--- Page {page_num + 1} ---")
        # For each widget, find nearby text (line number labels)
        for widget in widgets:
            if widget.field_type_string not in ('Text',):
                continue
            
            wr = widget.rect  # widget rect
            # Search for text within 60 points to the left of the widget
            search_rect = pymupdf.Rect(wr.x0 - 200, wr.y0 - 5, wr.x0 + 5, wr.y1 + 5)
            nearby_text = page.get_text("text", clip=search_rect).strip()
            
            # Also look for text below/above for label
            label_rect = pymupdf.Rect(0, wr.y0 - 20, 600, wr.y1 + 20)
            row_text = page.get_text("text", clip=label_rect).strip()
            
            parts = widget.field_name.split('.')
            short = '.'.join(parts[-3:])
            print(f"  [{short:50s}] nearby={nearby_text!r:30s} row={row_text[:80]!r}")

extract_text_near_fields("app/static/forms/bc428-2025.pdf", "BC428")
