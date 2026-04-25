"""
Registry of CRA forms organised by tax year.

Add new years or forms here to extend the application.  Each entry is a dict
with the following keys:

  id            – unique slug for the form
  name          – short display name  (e.g. "T1 General")
  form_num      – official CRA form number  (e.g. "T1-2025")
  category      – badge label  (e.g. "FEDERAL FORM")
  description   – one-line description
  lines_summary – brief feature summary for the home-page card
  url           – app-relative URL  (e.g. "/tax/t1")
  cra_url       – URL of the official CRA PDF on canada.ca
"""

from __future__ import annotations

FORMS_BY_YEAR: dict[str, list[dict]] = {
    "2025": [
        {
            "id": "t1-2025",
            "name": "T1 General",
            "form_num": "T1-2025",
            "category": "FEDERAL FORM",
            "description": "Income Tax and Benefit Return",
            "lines_summary": "Steps 2–5 · ~60 lines · Auto-calculation",
            "url": "/tax/t1",
            "cra_url": (
                "https://www.canada.ca/content/dam/cra-arc/formspubs/"
                "pbg/5006-r/5006-r-25e.pdf"
            ),
        },
        {
            "id": "bc428-2025",
            "name": "BC428",
            "form_num": "5010-C",
            "category": "BC PROVINCIAL FORM",
            "description": "British Columbia Tax",
            "lines_summary": "Parts 1–3 · ~20 lines · Links back to T1",
            "url": "/tax/bc428",
            "cra_url": (
                "https://www.canada.ca/content/dam/cra-arc/formspubs/"
                "pbg/5010-c/5010-c-25e.pdf"
            ),
        },
    ],
}
