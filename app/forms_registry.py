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
        {
            "id": "schedule9-2025",
            "name": "Schedule 9",
            "form_num": "5000-S9",
            "category": "FEDERAL FORM",
            "description": "Donations and Gifts",
            "lines_summary": "Lines 1–23 · Charitable donations credit · Links to T1",
            "url": "/tax/schedule9",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5000-s9/5000-s9-fill-25e.pdf",
        },
        {
            "id": "bc479-2025",
            "name": "BC479",
            "form_num": "5010-TC",
            "category": "BC PROVINCIAL FORM",
            "description": "British Columbia Credits",
            "lines_summary": "Lines 1–45 · Sales tax, renter's & other BC credits · Links to T1",
            "url": "/tax/bc479",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5010-tc/5010-tc-fill-25e.pdf",
        },
        {
            "id": "schedule3-2025",
            "name": "Schedule 3",
            "form_num": "5000-S3",
            "category": "FEDERAL FORM",
            "description": "Capital Gains or Losses",
            "lines_summary": "Parts 1–5 · Disposition of property · Links to T1 line 12700",
            "url": "/tax/schedule3",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5000-s3/5000-s3-fill-25e.pdf",
        },
        {
            "id": "schedule5-2025",
            "name": "Schedule 5",
            "form_num": "5000-S5",
            "category": "FEDERAL FORM",
            "description": "Amounts for Spouse or Common-Law Partner and Dependants",
            "lines_summary": "Lines 30300–30500 · Spouse/dependant amounts · Links to T1",
            "url": "/tax/schedule5",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5000-s5/5000-s5-fill-25e.pdf",
        },
        {
            "id": "schedule7-2025",
            "name": "Schedule 7",
            "form_num": "5000-S7",
            "category": "FEDERAL FORM",
            "description": "RRSP, FHSA, and PRPP Unused Contributions, Transfers, and Activities",
            "lines_summary": "Lines 20800–24600 · RRSP/FHSA/HBP/LLP · Links to T1",
            "url": "/tax/schedule7",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5000-s7/5000-s7-fill-25e.pdf",
        },
        {
            "id": "schedule8-2025",
            "name": "Schedule 8",
            "form_num": "5000-S8",
            "category": "FEDERAL FORM",
            "description": "CPP/QPP Contributions on Self-Employment and Other Earnings",
            "lines_summary": "Lines 22200–31205 · CPP/CPP2 on SE · Links to T1",
            "url": "/tax/schedule8",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5000-s8/5000-s8-fill-25e.pdf",
        },
        {
            "id": "t777-2025",
            "name": "T777",
            "form_num": "T777",
            "category": "FEDERAL FORM",
            "description": "Statement of Employment Expenses",
            "lines_summary": "Line 22900 · Motor vehicle & home office · Links to T1",
            "url": "/tax/t777",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/t777/t777-fill-25e.pdf",
        },
        {
            "id": "t2209-2025",
            "name": "T2209",
            "form_num": "T2209",
            "category": "FEDERAL FORM",
            "description": "Federal Foreign Tax Credits",
            "lines_summary": "Line 40500 · Non-business & business credits · Links to T1",
            "url": "/tax/t2209",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/t2209/t2209-fill-25e.pdf",
        },
        {
            "id": "worksheet-fed-2025",
            "name": "Worksheet Fed",
            "form_num": "5000-D1",
            "category": "FEDERAL FORM",
            "description": "Federal Worksheet",
            "lines_summary": "Federal non-refundable tax credits worksheet · Links to T1",
            "url": "/tax/worksheet-fed",
            "cra_url": "https://www.canada.ca/content/dam/cra-arc/formspubs/pbg/5000-d1/5000-d1-fill-25e.pdf",
        },
    ],
}
