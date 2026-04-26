"""
CRA Form Filler
===============
Fills official CRA fillable PDFs with user-supplied line values using PyMuPDF.

The CRA PDFs are Adobe LiveCycle XFA forms — pypdf cannot fill them.  This
module uses PyMuPDF (fitz) to:
  1. Read all widget positions from the original PDF
  2. Map each widget to a CRA line number
  3. Insert the user's value as a text overlay at the exact field coordinates
  4. Return the resulting PDF bytes

Setup (one-time):
  Download the official fillable PDFs from Canada.ca and place them in
  app/static/forms/ OR upload them via the in-app Setup page (/admin/setup).

  T1 General 2025:
    https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5006-r/5006-r-fill-25e.pdf
    → save as  app/static/forms/t1-2025.pdf

  BC428 (5010-C) 2025:
    https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5010-c/5010-c-fill-25e.pdf
    → save as  app/static/forms/bc428-2025.pdf
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FORMS_DIR = Path(__file__).parent / "static" / "forms"
FORMS_DIR.mkdir(parents=True, exist_ok=True)

# ── BC428 ordinal line number → CRA line number ──────────────────────────────
# BC428 XFA fields use ordinal names (Line1, Line16, ...) — no CRA numbers embedded.
# This maps each ordinal to the CRA line number used in line_values.
BC428_LINE_TO_CRA: dict[int, str] = {
    1: "26000",    # taxable income (from T1)
    # Bracket rows 2-15 are internal calculations — mapped dynamically below
    16: "58040",   # basic personal amount
    17: "58080",   # age amount
    18: "58120_base",  # spouse/partner base (read-only $12,932)
    19: "58120_net",   # net income of spouse
    20: "58120",   # spouse/partner amount
    21: "58160_base",  # eligible dependant base
    22: "58160_net",   # net income of eligible dependant
    23: "58160",   # eligible dependant amount
    24: "58175a",  # caregiver for eligible dependant or dependent
    25: "58175b",  # caregiver for infirm dependent 18+
    26: "58175_sub",   # subtotal lines 20+21+23+24+25
    27: "58240",   # CPP/QPP contributions (= T1 line 30800)
    28: "58280",   # employment insurance premiums (= T1 line 31000)
    29: "58300",   # employment insurance premiums on self-employment
    30: "58305",   # volunteer firefighters' amount
    31: "58315",   # search and rescue volunteers' amount
    32: "58316",   # search and rescue workers' amount
    33: "58330_sub",   # subtotal lines 27-32
    34: "58330",   # adoption expenses
    35: "58330_total", # subtotal lines 26+33+34
    36: "58360",   # pension income amount
    37: "58360_total", # subtotal line 35+36
    38: "58440",   # disability amount (self)
    39: "58480",   # disability transferred from dependant
    40: "58480_total", # subtotal line 37+38+39
    41: "58520",   # interest paid on student loans
    42: "58560",   # tuition, education, and textbook amounts
    43: "58600",   # tuition transferred from child/grandchild
    44: "58640",   # amounts transferred from spouse/partner
    45: "58640_total", # subtotal line 40+41+42+43+44
    46: "58689_total_med",  # total eligible medical expenses
    47: "58689_net",        # 3% of net income
    48: "58689_threshold",  # threshold ($2,759)
    49: "58689_lesser",     # lesser of line 47 and 48
    50: "58689_sub",        # line 46 minus line 49
    51: "58689",   # allowable medical expenses
    52: "58729",   # additional medical expenses (supplement)
    53: "58769",   # total medical (line 51 + 52)
    54: "58800",   # total (line 45 + line 53)
    55: "58840_rate",  # 5.06% (read-only)
    56: "58840",   # BC non-refundable tax credits (line 54 × 5.06%)
    57: "58969",   # donations and gifts
    58: "58969_total", # subtotal line 56 + 57
    59: "58980",   # farmers' food bank credit
    60: "58980_total", # total BC non-refundable credits
    61: "61510",   # BC tax before adjustments (from Part A line 8 or 15)
    62: "61510_split", # BC tax on split income
    63: "61510_total", # line 61 + 62
    64: "61510_credits",   # BC non-refundable credits (line 60)
    65: "61520",   # BC dividend tax credit
    66: "61540",   # minimum tax carryover
    67: "61540_net",   # BC net tax (line 63-64-65-66)
    68: "bc_surtax",   # BC surtax
    69: "bc_surtax_total",  # line 67 + 68
    70: "bc_additional",    # BC additional tax
    71: "bc_additional_total",  # line 69 + 70
    72: "bc_dividend_refund",   # BC dividend refund
    73: "bc_low_income_net",    # net income for low-income reduction
    74: "bc_low_income_thresh", # low income threshold
    75: "bc_low_income_base",   # base low income reduction
    76: "bc_low_income_factor", # reduction factor amount
    77: "bc_low_income_calc",   # calculated reduction
    78: "bc_low_income_apply",  # amount applied
    79: "bc_low_income_total",  # low income credit total
    80: "bc_political",         # BC political contribution credit
    81: "bc_political_calc",
    82: "bc_investment_credit",
    83: "bc_venture_credit",
    84: "bc_mining_credit",
    85: "bc_sr_ed_credit",
    86: "bc_training_credit",
    87: "bc_credits_sub",
    88: "bc_credits_total",
    89: "bc_employee_credit",
    90: "bc_employee_total",
    91: "42800",   # BC provincial income tax (→ T1 line 47900)
}

# Official CRA download URLs (used in the setup UI)
FORM_URLS: dict[str, str] = {
    "t1-2025.pdf": (
        "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5006-r/"
        "5006-r-fill-25e.pdf"
    ),
    "bc428-2025.pdf": (
        "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5010-c/"
        "5010-c-fill-25e.pdf"
    ),
}


# ── Public helpers ────────────────────────────────────────────────────────────

def forms_status() -> dict[str, dict]:
    """Return availability / metadata for each expected CRA template."""
    out: dict[str, dict] = {}
    for name, url in FORM_URLS.items():
        path = FORMS_DIR / name
        exists = path.exists() and path.stat().st_size > 10_000
        out[name] = {
            "available": exists,
            "size_kb": round(path.stat().st_size / 1024) if exists else 0,
            "download_url": url,
            "field_count": _count_fields(name) if exists else 0,
        }
    return out


def list_fields(form_name: str) -> list[str]:
    """Return sorted list of AcroForm field names found in the template."""
    path = FORMS_DIR / form_name
    if not path.exists():
        return []
    try:
        from pypdf import PdfReader
        fields = PdfReader(str(path)).get_fields() or {}
        return sorted(fields.keys())
    except Exception as exc:
        logger.error("list_fields(%s): %s", form_name, exc)
        return []


def fill_official_pdf(
    form_name: str,
    line_values: dict[str, float],
) -> Optional[bytes]:
    """
    Fill an official CRA fillable PDF with user values and return the bytes.

    Uses PyMuPDF to overlay text at the exact widget coordinates of each field.
    Works for both XFA-only and AcroForm CRA PDFs.

    Parameters
    ----------
    form_name   : one of "t1-2025.pdf" or "bc428-2025.pdf"
    line_values : {str(cra_line_number): float_amount}

    Returns None if the template is not installed.
    """
    path = FORMS_DIR / form_name
    if not path.exists() or path.stat().st_size < 10_000:
        logger.info("fill_official_pdf: template %s not installed", form_name)
        return None

    try:
        import pymupdf  # PyMuPDF

        # Normalise values: str keys, skip zeros/None
        value_map: dict[str, str] = {}
        for k, v in line_values.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv != 0.0:
                value_map[str(k)] = f"{fv:,.2f}"

        doc = pymupdf.open(str(path))
        filled = 0

        for page in doc:
            for widget in page.widgets():
                field_name: str = widget.field_name or ""
                cra_num = _extract_cra_line(field_name, form_name)
                if not cra_num:
                    continue
                text = value_map.get(cra_num)
                if not text:
                    continue

                rect = widget.rect
                # Right-align text within the field rect using a freetext annotation.
                # fontsize ~7 matches the CRA form's small digit boxes.
                annot = page.add_freetext_annot(
                    rect,
                    text,
                    fontsize=7,
                    fontname="Courier",
                    text_color=(0, 0, 0),
                    fill_color=None,
                    align=pymupdf.TEXT_ALIGN_RIGHT,
                )
                annot.set_border(width=0)
                annot.update()
                filled += 1

        logger.info(
            "fill_official_pdf: %s — filled %d fields from %d values",
            form_name, filled, len(value_map),
        )

        buf = io.BytesIO()
        doc.save(buf, garbage=4, deflate=True)
        return buf.getvalue()

    except Exception as exc:
        logger.error("fill_official_pdf(%s) failed: %s", form_name, exc, exc_info=True)
        return None


def _extract_cra_line(field_name: str, form_name: str) -> Optional[str]:
    """
    Extract the CRA line number string from a PDF widget field name.

    T1 fields:   "form1[0].Page3[0].Line_10100_Amount[0]"  → "10100"
    BC428 fields: "form1[0].Page1[0].PartB[0].Line16[0].Amount[0]" → "58040"
                  via BC428_LINE_TO_CRA mapping
    """
    if "t1" in form_name.lower():
        # T1: look for Line_NNNNN_Amount pattern (5006-r field names)
        m = re.search(r"Line_(\d{4,5})_Amount", field_name)
        if m:
            return m.group(1)
        # Fallback: any standalone 5-digit number in the full name
        m = re.search(r"(?<!\d)(\d{5})(?!\d)", field_name)
        if m:
            return m.group(1)

    elif "bc428" in form_name.lower() or "5010" in form_name.lower():
        # BC428: resolve ordinal line number through lookup table.
        # Field path contains e.g. "...Line16[0]..." or "...Column3[0].Line6[0]..."
        m = re.search(r"(?:^|[^a-zA-Z])Line(\d+)\[", field_name)
        if m:
            ordinal = int(m.group(1))
            return BC428_LINE_TO_CRA.get(ordinal)

    return None


def save_uploaded_form(form_name: str, content: bytes) -> dict:
    """
    Persist an uploaded CRA PDF template.

    Returns a status dict with field_count and whether it looks like a valid PDF.
    """
    if form_name not in FORM_URLS:
        raise ValueError(f"Unknown form name: {form_name!r}")
    if not content.startswith(b"%PDF"):
        raise ValueError("File does not appear to be a PDF (missing %PDF header)")

    path = FORMS_DIR / form_name
    path.write_bytes(content)
    logger.info("Saved uploaded form: %s (%d bytes)", form_name, len(content))

    fields = list_fields(form_name)
    return {
        "saved": True,
        "size_kb": round(len(content) / 1024),
        "field_count": len(fields),
        "sample_fields": fields[:10],
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _count_fields(form_name: str) -> int:
    path = FORMS_DIR / form_name
    try:
        import pymupdf
        doc = pymupdf.open(str(path))
        return sum(1 for page in doc for _ in page.widgets())
    except Exception:
        try:
            from pypdf import PdfReader
            return len(PdfReader(str(path)).get_fields() or {})
        except Exception:
            return -1
