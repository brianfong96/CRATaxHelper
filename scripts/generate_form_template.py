#!/usr/bin/env python3
"""
Auto-generate CRA tax form HTML templates from PDF files.

Usage:
    python scripts/generate_form_template.py bc428-2025.pdf bc428
    python scripts/generate_form_template.py --all

For each PDF this script:
1. Exports every page as an SVG file (vector, perfect at any zoom)
2. Extracts all AcroForm field names, positions, and types
3. Writes a complete Jinja2 HTML template with exact input positions
4. Writes a JSON metadata file for use in tests

The generated template includes a stub recalcXxx() function — the developer
only needs to fill in the calculation logic; all positioning is automatic.
"""

import fitz  # PyMuPDF
import pathlib
import json
import re
import sys
import textwrap

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC_FORMS = REPO_ROOT / "app" / "static" / "forms"
SCREENSHOTS_DIR = STATIC_FORMS / "screenshots"
TEMPLATES_DIR = REPO_ROOT / "app" / "templates"

# Forms to auto-generate (pdf_file, form_key, form_title, route)
FORM_REGISTRY = {
    "bc428":        ("bc428-2025.pdf",          "BC428",        "British Columbia Tax",                  "bc428"),
    "t1":           ("t1-2025.pdf",              "T1",           "General Income and Benefit Return",     "t1"),
    "schedule3":    ("schedule3-2025.pdf",       "Schedule 3",   "Capital Gains (or Losses)",             "schedule3"),
    "schedule5":    ("schedule5-2025.pdf",       "Schedule 5",   "Amounts for Spouse / Dependants",       "schedule5"),
    "schedule7":    ("schedule7-2025.pdf",       "Schedule 7",   "RRSP, PRPP and SPP Contributions",      "schedule7"),
    "schedule8":    ("schedule8-2025.pdf",       "Schedule 8",   "CPP/QPP Contributions",                 "schedule8"),
    "schedule9":    ("schedule9-2025.pdf",       "Schedule 9",   "Donations and Gifts",                   "schedule9"),
    "t777":         ("t777-2025.pdf",            "T777",         "Statement of Employment Expenses",      "t777"),
    "t2209":        ("t2209-2025.pdf",           "T2209",        "Federal Foreign Tax Credits",           "t2209"),
    "worksheet_fed":("worksheet-fed-2025.pdf",   "5000-D1",      "Federal Worksheet",                     "worksheet_fed"),
}


# ─── Field name → short HTML id ────────────────────────────────────────────────

def field_to_id(form_key: str, field_name: str, page: int, idx: int,
               _seen: dict | None = None) -> str:
    """Convert a verbose PDF field name to a unique clean HTML element ID.

    _seen: mutable dict passed by the caller to track used IDs per page,
           ensuring no two inputs on the same page share an ID.
    """
    if _seen is None:
        _seen = {}

    def _make_base() -> str:
        # Try to extract a recognisable CRA line number from the field name
        # Patterns: Line12345, Line1, line_12345, L12345
        patterns = [
            r'Line(\d{5})',    # 5-digit CRA line numbers (most reliable)
            r'Line(\d{4})',
            r'Line(\d{1,3})',  # short line numbers (e.g. Line31)
            r'line_(\d+)',
            r'L(\d{5})',
        ]
        for pat in patterns:
            m = re.search(pat, field_name, re.IGNORECASE)
            if m:
                return f"f_{form_key}_p{page}_L{m.group(1)}"
        # Fall back to last meaningful path segment
        parts = re.split(r'[\[\]\.]+', field_name)
        parts = [p for p in parts if p and not p.isdigit()]
        if parts:
            slug = re.sub(r'[^a-zA-Z0-9_]', '_', parts[-1])[:20].strip('_').lower()
            return f"f_{form_key}_p{page}_{slug}"
        return f"f_{form_key}_p{page}_fld"

    base = _make_base()
    # Deduplicate: if base already used on this page, append _2, _3, ...
    page_key = (page, base)
    if page_key not in _seen:
        _seen[page_key] = 0
    _seen[page_key] += 1
    count = _seen[page_key]
    return base if count == 1 else f"{base}_{count}"


def is_amount_field(field_name: str) -> bool:
    return bool(re.search(r'Amount|Amt|amount', field_name))


def is_text_only(field_name: str) -> bool:
    return bool(re.search(r'Text_Fld|Name|Addr|SIN|Date', field_name, re.IGNORECASE))


# ─── SVG generation ────────────────────────────────────────────────────────────

def export_page_svg(page: fitz.Page, out_path: pathlib.Path) -> None:
    """Export a single PDF page as an SVG file (vector, lossless)."""
    # Use 2× scale for sharper text on retina displays
    mat = fitz.Matrix(1.5, 1.5)
    svg_text = page.get_svg_image(matrix=mat)
    out_path.write_text(svg_text, encoding="utf-8")


def export_page_png(page: fitz.Page, out_path: pathlib.Path, dpi: int = 150) -> None:
    """Export a single PDF page as a high-res PNG (fallback)."""
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    pix.save(str(out_path))


# ─── Field extraction ──────────────────────────────────────────────────────────

def extract_fields(doc: fitz.Document, form_key: str) -> list[dict]:
    """Extract all interactive fields from a PDF document."""
    all_fields = []
    id_counter = {}
    seen_ids: dict = {}  # tracks (page, base_id) → count for deduplication

    for pg_idx, page in enumerate(doc):
        w, h = page.rect.width, page.rect.height
        page_num = pg_idx + 1

        for widget in page.widgets():
            if widget.field_type_string not in ("Text", "CheckBox", "RadioButton"):
                continue

            r = widget.rect
            left   = round(r.x0 / w * 100, 3)
            top    = round(r.y0 / h * 100, 3)
            width  = round((r.x1 - r.x0) / w * 100, 3)
            height = round((r.y1 - r.y0) / h * 100, 3)

            # Get surrounding text for context/label
            ctx_rect = fitz.Rect(0, r.y0 - 10, w, r.y1 + 10)
            ctx = page.get_text("text", clip=ctx_rect).replace("\n", " ").strip()[:80]

            idx = id_counter.get((pg_idx, widget.field_type_string), 0) + 1
            id_counter[(pg_idx, widget.field_type_string)] = idx

            html_id = field_to_id(form_key, widget.field_name, page_num, idx, seen_ids)

            all_fields.append({
                "page":      page_num,
                "html_id":   html_id,
                "pdf_name":  widget.field_name,
                "type":      widget.field_type_string,
                "left":      left,
                "top":       top,
                "width":     width,
                "height":    height,
                "context":   ctx,
                "is_amount": is_amount_field(widget.field_name),
                "is_text":   is_text_only(widget.field_name),
            })

    return all_fields


# ─── Template generation ───────────────────────────────────────────────────────

INPUT_TEMPLATE_AMOUNT = (
    '<input type="text" data-numeric="1" id="{html_id}" class="pdf-input" '
    'value="" inputmode="decimal" '
    'oninput="recalc{func_name}(); autoSave();" '
    'style="left:{left}%;top:{top}%;width:{width}%;height:{height}%;" '
    'title="{ctx}">'
)

INPUT_TEMPLATE_TEXT = (
    '<input type="text" id="{html_id}" class="pdf-input text-left" '
    'oninput="autoSave();" '
    'style="left:{left}%;top:{top}%;width:{width}%;height:{height}%;" '
    'title="{ctx}">'
)

INPUT_TEMPLATE_CHECKBOX = (
    '<input type="checkbox" id="{html_id}" class="pdf-input" '
    'onchange="recalc{func_name}(); autoSave();" '
    'style="left:{left}%;top:{top}%;width:{width}%;height:{height}%;">'
)

INPUT_TEMPLATE_READONLY = (
    '<input type="text" id="{html_id}" class="pdf-input" readonly value="0.00" '
    'style="left:{left}%;top:{top}%;width:{width}%;height:{height}%;" '
    'title="{ctx}">'
)


def render_input(field: dict, func_name: str) -> str:
    ctx = field["context"].replace('"', "'")
    kw = {**field, "func_name": func_name, "ctx": ctx}

    if field["type"] == "CheckBox":
        return INPUT_TEMPLATE_CHECKBOX.format(**kw)
    if field["is_text"]:
        return INPUT_TEMPLATE_TEXT.format(**kw)
    # Amount fields — editable for user input, readonly for computed
    # Without calculation mapping, generate as editable (user can fill in)
    return INPUT_TEMPLATE_AMOUNT.format(**kw)


def make_func_name(form_key: str) -> str:
    """Convert form key to camelCase function name, e.g. schedule3 -> S3."""
    mappings = {
        "bc428": "BC428", "t1": "T1", "schedule3": "S3", "schedule5": "S5",
        "schedule7": "S7", "schedule8": "S8", "schedule9": "S9",
        "t777": "T777", "t2209": "T2209", "worksheet_fed": "WF",
    }
    return mappings.get(form_key, form_key.replace("_", "").title())


SVG_INLINE_THRESHOLD = 200_000  # bytes; inline smaller SVGs, <img> for larger


def generate_template(form_key: str, pdf_path: pathlib.Path,
                      fields: list[dict], page_count: int,
                      use_svg: bool = True) -> str:
    """Generate a complete Jinja2 HTML template for a CRA form."""
    _, form_number, form_title, route = FORM_REGISTRY[form_key]
    func_name = make_func_name(form_key)

    # Group fields by page
    by_page: dict[int, list] = {}
    for f in fields:
        by_page.setdefault(f["page"], []).append(f)

    # Build all input IDs (non-readonly only)
    all_ids = [f["html_id"] for f in fields
               if f["type"] != "CheckBox" and not f.get("readonly")]
    checkbox_ids = [f["html_id"] for f in fields if f["type"] == "CheckBox"]

    # Build page HTML
    pages_html = []
    for pg in range(1, page_count + 1):
        ext = "svg" if use_svg else "png"
        img_name = f"{form_key.replace('_', '-')}_page{pg}.{ext}"
        img_src = "{{ root_path }}/static/forms/screenshots/" + img_name
        alt = f"{form_number} Page {pg}"

        page_fields = by_page.get(pg, [])
        inputs_html = "\n    ".join(
            f"<!-- {f['context'][:60]} -->\n    " + render_input(f, func_name)
            for f in page_fields
        )

        pages_html.append(f"""
  <div id="pg-anchor-{pg}"></div>
  <div class="pdf-page">
    <img class="pdf-bg" src="{img_src}" alt="{alt}">
    {inputs_html}
  </div>""")

    pages_block = "\n".join(pages_html)

    # Build nav
    nav_links = "\n    ".join(
        f'<a href="#pg-anchor-{pg}">Page {pg}</a>'
        for pg in range(1, page_count + 1)
    )

    # Build FORM_INPUT_IDS JS
    ids_js = ",\n  ".join(f"'{i}'" for i in all_ids[:50])  # first 50
    cb_js  = ",\n  ".join(f"'{i}'" for i in checkbox_ids[:20])

    template = f"""{{% extends "base.html" %}}
{{% block title %}}{form_number} &mdash; {form_title} 2025{{% endblock %}}

{{% block content %}}
<style>
.pdf-form-container {{ max-width: 850px; margin: 0 auto; }}
.pdf-nav {{
  position: sticky; top: 0; z-index: 100;
  background: #26374a; padding: 6px 12px;
  display: flex; gap: 4px; flex-wrap: wrap;
}}
.pdf-nav a {{
  color: #fff; text-decoration: none;
  padding: 3px 10px; border-radius: 2px;
  font-size: 12px; border: 1px solid rgba(255,255,255,.35);
}}
.pdf-nav a:hover {{ background: rgba(255,255,255,.18); }}
.pdf-page {{ position: relative; width: 100%; margin-bottom: 8px; }}
.pdf-bg {{ width: 100%; display: block; }}
.pdf-input {{
  position: absolute;
  background: rgba(255,255,200,0.75);
  border: 1px solid #0066cc;
  font-size: 0.60em;
  padding: 0 2px;
  text-align: right;
  box-sizing: border-box;
  font-family: "Courier New", monospace;
  line-height: 1;
}}
.pdf-input:focus {{
  background: rgba(255,255,200,1);
  border-color: #003399;
  outline: 2px solid rgba(0,51,153,0.4);
  z-index: 10;
}}
.pdf-input[readonly] {{
  background: rgba(200,230,255,0.65);
  border-color: #888;
  cursor: default;
}}
.pdf-input.text-left {{ text-align: left; }}
</style>

<div class="cra-form pdf-form-container">

  <div class="form-header">
    <div>
      <div class="form-title">{form_number} &mdash; {form_title}</div>
      <div class="form-subtitle">Form {form_number} &nbsp;&middot;&nbsp; 2025 tax year</div>
    </div>
    <div class="form-number" style="display:flex;flex-direction:column;align-items:flex-end;gap:6px;">
      <strong>{form_number}-2025</strong>
      Canada Revenue Agency
      <a class="cra-orig-badge"
         href="https://www.canada.ca/en/revenue-agency/services/forms-publications.html"
         target="_blank" rel="noopener" title="Open official CRA {form_number} PDF">
        <svg class="icon"><use href="#ic-external"/></svg> Official CRA form
      </a>
    </div>
  </div>
  <div class="form-meta-bar">
    <span>Protected B when completed</span>
    <span>2025 tax year</span>
  </div>

  <nav class="pdf-nav">
    {nav_links}
  </nav>
{pages_block}

  <!-- Toolbar -->
  <div class="form-toolbar">
    <button class="btn btn-primary" onclick="saveAndReturnToT1()"><svg class="icon"><use href="#ic-arrow-left"/></svg> Save &amp; Return to T1</button>
    <button class="btn btn-success" onclick="saveSnapshot()"><svg class="icon"><use href="#ic-save"/></svg> Save Snapshot</button>
    <button class="btn btn-outline" onclick="window.print()"><svg class="icon"><use href="#ic-printer"/></svg> Print</button>
    <a class="btn btn-outline" href="{{{{ root_path }}}}/tax/t1"><svg class="icon"><use href="#ic-arrow-left"/></svg> Back to T1</a>
    <button class="btn btn-outline" onclick="clearForm()"><svg class="icon"><use href="#ic-trash"/></svg> Clear</button>
    <button class="btn btn-outline" onclick="loadLastSnapshot()"><svg class="icon"><use href="#ic-history"/></svg> Load Last Snapshot</button>
    <span style="font-size:11px; color:var(--muted); margin-left:auto;" id="last-saved"></span>
  </div>

</div>{{# /.cra-form #}}
{{% endblock %}}

{{% block scripts %}}
<script>
const ROOT = '{{{{ root_path }}}}';
const FORM_KEY = 'cra_{form_key}_autosave';
const FORM_INPUT_IDS = [
  {ids_js}
];
const CHECKBOX_IDS = [
  {cb_js}
];

// ── Helpers ──────────────────────────────────────────────────────────────────
function g(id) {{
  const el = document.getElementById(id);
  if (!el) return 0;
  const dollars = Math.max(0, parseFloat((el.value||'').replace(/,/g,'')) || 0);
  const ci = el.parentElement ? el.parentElement.querySelector('.cents-input[data-for="'+id+'"]') : null;
  return dollars + (ci ? (parseInt(ci.value,10)||0) : 0) / 100;
}}
function s(id, v) {{
  const el = document.getElementById(id);
  if (!el) return;
  const formatted = Math.abs(v) < 0.005 ? '0.00' : v.toFixed(2).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ',');
  const dot = formatted.indexOf('.');
  el.value = dot >= 0 ? formatted.slice(0, dot) : formatted;
  const ci = el.parentElement ? el.parentElement.querySelector('.cents-input[data-for="'+id+'"]') : null;
  if (ci) ci.value = dot >= 0 ? formatted.slice(dot+1) : '00';
}}
function fmtInput(el) {{
  const raw = parseFloat((el.value||'').replace(/,/g,'')) || 0;
  el.setAttribute('data-raw', String(raw));
  if (raw === 0) {{ el.value = ''; return; }}
  const fmt = raw.toLocaleString('en-CA', {{minimumFractionDigits:2, maximumFractionDigits:2}});
  const dot = fmt.indexOf('.');
  el.value = dot >= 0 ? fmt.slice(0, dot) : fmt;
  const ci = el.parentElement ? el.parentElement.querySelector('.cents-input[data-for="'+el.id+'"]') : null;
  if (ci) ci.value = dot >= 0 ? fmt.slice(dot+1) : '00';
}}
function initAmountBoxes() {{
  document.querySelectorAll('.pdf-input[data-numeric], .pdf-input[readonly]').forEach(inp => {{
    const left = parseFloat(inp.style.left);
    const wrap = document.createElement('span');
    wrap.style.cssText = `position:absolute;left:${{inp.style.left}};top:${{inp.style.top}};width:${{inp.style.width}};height:${{inp.style.height}};display:flex;gap:1px;`;
    inp.style.cssText = 'position:static;width:calc(100% - 28px);height:100%;font-size:0.60em;padding:0 2px;text-align:right;box-sizing:border-box;font-family:"Courier New",monospace;line-height:1;background:inherit;border:inherit;';
    const ci = document.createElement('input');
    ci.type = 'text'; ci.className = 'cents-input';
    ci.setAttribute('data-for', inp.id);
    ci.style.cssText = 'width:26px;height:100%;font-size:0.60em;padding:0 1px;text-align:center;box-sizing:border-box;font-family:"Courier New",monospace;line-height:1;border:1px solid #aaa;background:rgba(255,255,200,0.75);';
    ci.maxLength = 2; ci.placeholder='00';
    ci.addEventListener('input', () => {{ if (ci.value.length===2 || ci.value==='') autoSave(); }});
    inp.parentElement.insertBefore(wrap, inp);
    wrap.appendChild(inp); wrap.appendChild(ci);
  }});
}}

// ── Calculations ─────────────────────────────────────────────────────────────
// TODO: implement recalc{func_name}() using field IDs listed in FORM_INPUT_IDS
function recalc{func_name}() {{
  // Add your calculation logic here.
  // Use g(id) to read values, s(id, value) to write computed results.
  // Example: s('f_{form_key}_p1_Ltotal', g('f_{form_key}_p1_L1') + g('f_{form_key}_p1_L2'));
}}

// ── Auto-save ────────────────────────────────────────────────────────────────
let _saveTimer;
function autoSave() {{
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {{
    const data = {{}};
    FORM_INPUT_IDS.forEach(id => {{
      const el = document.getElementById(id);
      if (el) data[id] = el.value;
    }});
    CHECKBOX_IDS.forEach(id => {{
      const el = document.getElementById(id);
      if (el) data[id] = el.checked;
    }});
    try {{
      const enc = typeof CRAEncrypt === 'function' ? CRAEncrypt(JSON.stringify(data)) : JSON.stringify(data);
      localStorage.setItem(FORM_KEY, enc);
      document.getElementById('last-saved').textContent = 'Saved ' + new Date().toLocaleTimeString();
    }} catch(e) {{}}
  }}, 400);
}}

function loadFormData() {{
  try {{
    const raw = localStorage.getItem(FORM_KEY);
    if (!raw) return;
    const str = typeof CRADecrypt === 'function' ? CRADecrypt(raw) : raw;
    const data = JSON.parse(str);
    FORM_INPUT_IDS.forEach(id => {{
      const el = document.getElementById(id);
      if (el && data[id] !== undefined) el.value = data[id];
    }});
    CHECKBOX_IDS.forEach(id => {{
      const el = document.getElementById(id);
      if (el && data[id] !== undefined) el.checked = data[id];
    }});
  }} catch(e) {{}}
}}

function clearForm() {{
  if (!confirm('Clear all data?')) return;
  localStorage.removeItem(FORM_KEY);
  FORM_INPUT_IDS.forEach(id => {{ const el = document.getElementById(id); if(el) el.value=''; }});
  CHECKBOX_IDS.forEach(id => {{ const el = document.getElementById(id); if(el) el.checked=false; }});
  recalc{func_name}();
}}

function saveSnapshot() {{
  const data = {{}};
  FORM_INPUT_IDS.forEach(id => {{ const el = document.getElementById(id); if(el) data[id]=el.value; }});
  CHECKBOX_IDS.forEach(id => {{ const el = document.getElementById(id); if(el) data[id]=el.checked; }});
  localStorage.setItem(FORM_KEY + '_snap', JSON.stringify(data));
  alert('Snapshot saved!');
}}

function loadLastSnapshot() {{
  try {{
    const data = JSON.parse(localStorage.getItem(FORM_KEY + '_snap') || '{{}}');
    FORM_INPUT_IDS.forEach(id => {{ const el = document.getElementById(id); if(el && data[id]) el.value=data[id]; }});
    CHECKBOX_IDS.forEach(id => {{ const el = document.getElementById(id); if(el && data[id]!==undefined) el.checked=data[id]; }});
    recalc{func_name}();
  }} catch(e) {{}}
}}

function saveAndReturnToT1() {{
  autoSave();
  setTimeout(() => window.location.href = ROOT + '/tax/t1', 500);
}}

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  initAmountBoxes();
  loadFormData();
  document.querySelectorAll('.pdf-input[data-numeric]').forEach(el => {{
    el.addEventListener('blur', () => fmtInput(el));
    el.addEventListener('focus', () => {{
      const raw = el.getAttribute('data-raw');
      if (raw && raw !== '0') el.value = raw;
    }});
  }});
  recalc{func_name}();
}});
</script>
{{% endblock %}}
"""
    return template


# ─── Main ──────────────────────────────────────────────────────────────────────

def process_form(form_key: str, export_svg: bool = True,
                 overwrite_template: bool = False) -> None:
    """Process one form: export SVGs, extract fields, generate template."""
    pdf_filename, form_number, form_title, route = FORM_REGISTRY[form_key]
    pdf_path = STATIC_FORMS / pdf_filename

    if not pdf_path.exists():
        print(f"  MISSING PDF: {pdf_path}")
        return

    doc = fitz.open(str(pdf_path))
    n_pages = doc.page_count
    print(f"\n{'='*60}")
    print(f"  {form_key}: {n_pages} pages  ({pdf_filename})")

    # 1. Export page images
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    for pg_idx, page in enumerate(doc):
        pg_num = pg_idx + 1
        ext = "svg" if export_svg else "png"
        # Use hyphen for forms with hyphen (worksheet-fed), else underscore
        base = form_key.replace("_", "-")
        out_path = SCREENSHOTS_DIR / f"{base}_page{pg_num}.{ext}"
        if not out_path.exists():
            if export_svg:
                print(f"    Exporting SVG page {pg_num}…")
                export_page_svg(page, out_path)
            else:
                print(f"    Exporting PNG page {pg_num}…")
                export_page_png(page, out_path)
        else:
            print(f"    Page {pg_num} image already exists, skipping.")

    # 2. Extract fields
    fields = extract_fields(doc, form_key)
    print(f"  Extracted {len(fields)} fields")

    # Save metadata JSON
    meta_path = STATIC_FORMS / f"{form_key}-auto-fields.json"
    meta_path.write_text(json.dumps(fields, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved field metadata → {meta_path.name}")

    doc.close()

    # 3. Generate template
    tmpl_path = TEMPLATES_DIR / f"{form_key}_auto.html"
    if tmpl_path.exists() and not overwrite_template:
        print(f"  Template {tmpl_path.name} already exists. Use --overwrite to regenerate.")
        return

    template_str = generate_template(form_key, pdf_path, fields, n_pages,
                                     use_svg=export_svg)
    tmpl_path.write_text(template_str, encoding="utf-8")
    print(f"  Generated template → {tmpl_path.name}")
    print(f"  NOTE: Fill in recalc{make_func_name(form_key)}() with calculation logic.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("form_key", nargs="?", choices=list(FORM_REGISTRY), help="Form to process")
    parser.add_argument("--all", action="store_true", help="Process all registered forms")
    parser.add_argument("--png", action="store_true", help="Use PNG instead of SVG (faster)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing templates")
    args = parser.parse_args()

    if args.all:
        for key in FORM_REGISTRY:
            process_form(key, export_svg=not args.png, overwrite_template=args.overwrite)
    elif args.form_key:
        process_form(args.form_key, export_svg=not args.png, overwrite_template=args.overwrite)
    else:
        parser.print_help()
        print("\nRegistered forms:", ", ".join(FORM_REGISTRY))


if __name__ == "__main__":
    main()
