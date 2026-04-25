"""
CRA Form Filler
===============
Fills official CRA fillable PDFs (AcroForm) with user-supplied line values.

Setup (one-time):
  Download the official fillable PDFs from Canada.ca and place them in
  app/static/forms/ OR upload them via the in-app Setup page (/admin/setup).

  T1 General 2025:
    https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5006-r/5006-r-fill-25e.pdf
    → save as  app/static/forms/t1-2025.pdf

  BC428 (5010-C) 2025:
    https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5010-c/5010-c-fill-25e.pdf
    → save as  app/static/forms/bc428-2025.pdf

How it works:
  The CRA fillable PDFs are AcroForm PDFs with named text fields.  Field names
  embed the CRA line number (e.g. "Line_10100", "T1_10100", "Box10100").
  This module discovers the mapping automatically by scanning every field name
  for a 4–5 digit sequence that matches a known line number, then writes the
  formatted dollar amount into that field.

  NeedAppearances is set so any PDF viewer renders the filled values even when
  the original font program is not embedded.
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
    Fill an official CRA fillable PDF and return the bytes.

    Parameters
    ----------
    form_name   : one of "t1-2025.pdf" or "bc428-2025.pdf"
    line_values : {str(line_number): float_amount} — zeros / None are skipped

    Returns None if the template is not installed.
    """
    path = FORMS_DIR / form_name
    if not path.exists() or path.stat().st_size < 10_000:
        logger.info("fill_official_pdf: template %s not installed", form_name)
        return None

    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import BooleanObject, NameObject

        reader = PdfReader(str(path))
        fields = reader.get_fields() or {}

        if not fields:
            logger.warning(
                "fill_official_pdf: %s has no AcroForm fields (may be XFA-only)",
                form_name,
            )
            return None

        # ── Auto-discover field → line mapping ───────────────────────────────
        # Strategy: for each PDF field name, extract every 4-5 digit number.
        # If that number exists in line_values, write the formatted amount.
        # This handles all CRA naming conventions:
        #   "Line_10100", "T1_10100", "Box10100", "f10100", "10100", etc.
        fill_map: dict[str, str] = {}
        for field_name in fields:
            # Normalise: strip AcroForm path hierarchy  (e.g. "form[0].p1[0].L10100[0]")
            last_part = field_name.split(".")[-1]
            nums = re.findall(r"\b(\d{4,5})\b", last_part)
            if not nums:
                # Try the full name
                nums = re.findall(r"\b(\d{4,5})\b", field_name)
            for num in nums:
                val = line_values.get(num)
                if val is not None and float(val) != 0.0:
                    fill_map[field_name] = f"{float(val):.2f}"
                    break  # only one match per field

        logger.info(
            "fill_official_pdf: %s — mapped %d / %d fields",
            form_name, len(fill_map), len(fields),
        )

        # ── Write filled PDF ──────────────────────────────────────────────────
        writer = PdfWriter()
        writer.append(reader)

        for page in writer.pages:
            try:
                writer.update_page_form_field_values(
                    page, fill_map, auto_regenerate=False
                )
            except TypeError:
                # older pypdf without auto_regenerate param
                writer.update_page_form_field_values(page, fill_map)

        # Force PDF viewers to render appearances for filled fields
        root = writer._root_object
        acroform = root.get("/AcroForm")
        if acroform:
            try:
                acroform[NameObject("/NeedAppearances")] = BooleanObject(True)
            except Exception:
                pass

        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    except Exception as exc:
        logger.error("fill_official_pdf(%s) failed: %s", form_name, exc, exc_info=True)
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
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(FORMS_DIR / form_name)).get_fields() or {})
    except Exception:
        return -1
