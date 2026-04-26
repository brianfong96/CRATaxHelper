"""
CRA Tax Helper — FastAPI application.

Routes:
  GET  /                           Landing page (year-grouped form registry)
  GET  /health                     Health check
  GET  /profile                    User profile page
  GET  /tax/t1                     T1 General 2025 form
  GET  /tax/bc428                  BC428 2025 form
  GET  /tax/compare                Side-by-side scenario comparison
  POST /tax/t1/calculate           JSON API – compute all T1 derived lines
  POST /tax/bc428/calculate        JSON API – compute all BC428 derived lines
  POST /tax/t1/pdf                 Export filled T1 PDF (official CRA form if installed)
  POST /tax/bc428/pdf              Export filled BC428 PDF (official CRA form if installed)
  GET  /api/userdata/{form}        Fetch server-saved form data for logged-in user
  POST /api/userdata/{form}        Upsert server-saved form data for logged-in user
  GET  /admin/setup                Setup page – install official CRA PDF templates
  GET  /admin/forms-status         JSON – which official PDFs are installed
  GET  /admin/list-fields/{name}   JSON – AcroForm field names in an installed PDF
  POST /admin/upload-form/{name}   Upload an official CRA fillable PDF
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.calculator import (
    BC428Input,
    T1Input,
    calculate_bc428,
    calculate_t1,
)
from app.auth import get_current_user, require_auth_response
from app.config import settings
from app.form_filler import (
    fill_official_pdf,
    forms_status,
    list_fields,
    save_uploaded_form,
)
from app.forms_registry import FORMS_BY_YEAR
from app.userdata import (
    ensure_archive_project,
    get_form_data,
    grant_user_access,
    save_form_data,
)

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='{"ts":"%(asctime)s","logger":"%(name)s","level":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger("taxhelper")

try:
    from app.log_shipper import AetherLogHandler
    logging.getLogger().addHandler(
        AetherLogHandler(service="taxhelper", archive_url="http://archive:7000")
    )
except Exception:  # noqa: BLE001
    pass

from contextlib import asynccontextmanager

# ── App & templates ───────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app):
    """Initialise Archive project/table/RLS on startup (idempotent, non-fatal)."""
    asyncio.create_task(ensure_archive_project())
    yield


app = FastAPI(
    title="CRA Tax Helper",
    description="Interactive CRA T1 General and BC428 tax calculator",
    version="1.0.0",
    root_path=settings.ROOT_PATH,
    lifespan=_lifespan,
)

_TMPL_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TMPL_DIR))

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


# ── Auth middleware ───────────────────────────────────────────────────────────

_FORBIDDEN_TMPL = """\
<!doctype html><html><head><meta charset=utf-8>
<title>Access Restricted — CRA Tax Helper</title>
<style>
  body{{font-family:Arial,sans-serif;background:#f5f5f5;display:flex;align-items:center;
        justify-content:center;min-height:100vh;margin:0}}
  .box{{background:#fff;border:1px solid #ccc;border-radius:4px;padding:40px 48px;
        max-width:420px;text-align:center}}
  h1{{color:#af3c43;font-size:22px;margin-bottom:12px}}
  p{{color:#555;font-size:14px;margin:8px 0}}
  a{{color:#26374a;font-size:13px}}
</style></head><body>
<div class="box">
  <h1>&#128274; Access Restricted</h1>
  <p>Your account (<strong>{email}</strong>) is not authorised to access CRA Tax Helper.</p>
  <p>Contact the administrator to request access.</p>
  <p style="margin-top:20px"><a href="https://api.aether-data.net/logout">Sign out</a></p>
</div></body></html>"""


@app.middleware("http")
async def taxhelper_auth_middleware(request: Request, call_next):
    """Require valid Aether session; enforce per-app RBAC if ALLOWED_EMAILS is set."""
    path = request.url.path
    if path.endswith("/health"):
        return await call_next(request)
    if not settings.AUTH_ENABLED or not settings.SESSION_SECRET:
        return await call_next(request)

    user = get_current_user(request)
    if not user:
        return require_auth_response(request)

    email = (user.get("email") or "").lower()

    # Per-app RBAC: if ALLOWED_EMAILS is configured, gate access
    allowed = settings.allowed_emails
    if allowed and email not in allowed:
        return HTMLResponse(
            content=_FORBIDDEN_TMPL.format(email=email),
            status_code=403,
        )

    request.state.user = user

    # Grant Archive access once per process lifetime (fire-and-forget)
    if email:
        asyncio.create_task(grant_user_access(email))

    return await call_next(request)


def _ctx(request: Request, **extra):
    """Build a base template context including the logged-in user."""
    user = getattr(request.state, "user", None)
    return {"request": request, "root_path": settings.ROOT_PATH, "user": user, **extra}


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html", _ctx(request, forms_by_year=FORMS_BY_YEAR)
    )


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    user = getattr(request.state, "user", {}) or {}
    archive_enabled = bool(settings.ARCHIVE_URL and settings.SESSION_SECRET)
    return templates.TemplateResponse(
        "profile.html",
        _ctx(request, archive_enabled=archive_enabled),
    )


@app.get("/tax/t1", response_class=HTMLResponse)
async def t1_form(request: Request):
    return templates.TemplateResponse("t1.html", _ctx(request))


@app.get("/tax/bc428", response_class=HTMLResponse)
async def bc428_form(request: Request):
    return templates.TemplateResponse("bc428.html", _ctx(request))


@app.get("/tax/compare", response_class=HTMLResponse)
async def compare(request: Request):
    return templates.TemplateResponse("compare.html", _ctx(request))


# ── User data API (server-side per-user persistence via Archive) ──────────────

_ALLOWED_FORMS = {"t1", "bc428"}


@app.get("/api/userdata/{form}")
async def userdata_get(form: str, request: Request):
    """Return the logged-in user's saved form data from Archive."""
    if form not in _ALLOWED_FORMS:
        raise HTTPException(400, f"Unknown form '{form}'")
    cookie = request.cookies.get("aether_session", "")
    data = await get_form_data(cookie, form)
    if data is None:
        raise HTTPException(404, "No saved data found")
    return data


@app.post("/api/userdata/{form}")
async def userdata_post(form: str, request: Request):
    """Upsert the logged-in user's form data to Archive."""
    if form not in _ALLOWED_FORMS:
        raise HTTPException(400, f"Unknown form '{form}'")
    user = getattr(request.state, "user", {}) or {}
    email = user.get("email", "")
    if not email:
        raise HTTPException(401, "Not authenticated")
    cookie = request.cookies.get("aether_session", "")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    ok = await save_form_data(cookie, email, form, body)
    if not ok:
        raise HTTPException(502, "Archive save failed; data kept in localStorage")
    return {"saved": True}


# ── Admin / setup routes ──────────────────────────────────────────────────────

@app.get("/admin/setup", response_class=HTMLResponse)
async def admin_setup(request: Request):
    status = forms_status()
    return templates.TemplateResponse(
        "setup.html", _ctx(request, forms=status)
    )


@app.get("/admin/forms-status")
async def admin_forms_status():
    return forms_status()


@app.get("/admin/list-fields/{form_name}")
async def admin_list_fields(form_name: str):
    if form_name not in ("t1-2025.pdf", "bc428-2025.pdf"):
        raise HTTPException(status_code=400, detail="Unknown form name")
    return {"form": form_name, "fields": list_fields(form_name)}


@app.post("/admin/upload-form/{form_name}")
async def admin_upload_form(form_name: str, file: UploadFile = File(...)):
    if form_name not in ("t1-2025.pdf", "bc428-2025.pdf"):
        raise HTTPException(status_code=400, detail="Unknown form name")
    content = await file.read()
    try:
        result = save_uploaded_form(form_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result


# ── JSON calculation API ──────────────────────────────────────────────────────

class T1CalcRequest(BaseModel):
    """All user-editable T1 fields (floats default to 0)."""
    line_10100: float = 0; line_10400: float = 0; line_11300: float = 0
    line_11400: float = 0; line_11500: float = 0; line_11700: float = 0
    line_11900: float = 0; line_12000: float = 0; line_12010: float = 0
    line_12100: float = 0; line_12200: float = 0; line_12500: float = 0
    line_12600: float = 0; line_12700: float = 0; line_12900: float = 0
    line_13000: float = 0; line_13010: float = 0; line_13500: float = 0
    line_13700: float = 0; line_13900: float = 0; line_14100: float = 0
    line_14300: float = 0; line_14400: float = 0; line_14500: float = 0
    line_14600: float = 0; line_20600: float = 0; line_20700: float = 0
    line_20800: float = 0; line_20810: float = 0; line_21000: float = 0
    line_21200: float = 0; line_21300: float = 0; line_21400: float = 0
    line_21500: float = 0; line_21699: float = 0; line_21900: float = 0
    line_22000: float = 0; line_22100: float = 0; line_22200: float = 0
    line_22215: float = 0; line_22400: float = 0; line_22900: float = 0
    line_23100: float = 0; line_23200: float = 0; line_23500: float = 0
    line_24400: float = 0; line_24900: float = 0; line_25000: float = 0
    line_25100: float = 0; line_25200: float = 0; line_25300: float = 0
    line_25400: float = 0; line_25500: float = 0; line_25600: float = 0
    line_30000: float = 16129; line_30100: float = 0; line_30300: float = 0
    line_30400: float = 0; line_30425: float = 0; line_30450: float = 0
    line_30500: float = 0; line_31000: float = 0; line_31200: float = 0
    line_31205: float = 0; line_31217: float = 0; line_31220: float = 0
    line_31260: float = 0; line_31270: float = 0; line_31285: float = 0
    line_31300: float = 0; line_31350: float = 0; line_31400: float = 0
    line_31401: float = 0; line_31600: float = 0; line_31800: float = 0
    line_31900: float = 0; line_32300: float = 0; line_32400: float = 0
    line_32600: float = 0; line_33099: float = 0; line_33199: float = 0
    line_34900: float = 0; line_40427: float = 0; line_40600: float = 0
    line_40900: float = 0; line_43700: float = 0; line_44800: float = 0
    line_45200: float = 0; line_47600: float = 0; line_47900: float = 0
    age_65_or_over: bool = False
    bc_net_tax: float = 0   # pass BC428 line 42800 here


class BC428CalcRequest(BaseModel):
    """All user-editable BC428 fields."""
    taxable_income: float = 0         # T1 line 26000
    eligible_div_taxable: float = 0   # T1 line 12000
    non_eligible_div_taxable: float = 0  # T1 line 12010
    line_58040: float = 12932; line_58080: float = 0; line_58120: float = 0
    line_58160: float = 0; line_58200: float = 0; line_58240: float = 0
    line_58280: float = 0; line_58300: float = 0; line_58360: float = 0
    line_58400: float = 0; line_58440: float = 0; line_58480: float = 0
    line_58560: float = 0; line_58640: float = 0; line_58689: float = 0
    line_58729: float = 0; line_58800: float = 0; line_61520: float = 0
    line_61600: float = 0; bc_eligible_pension: float = 0
    age_65_or_over: bool = False


@app.post("/tax/t1/calculate")
async def calculate_t1_api(body: T1CalcRequest):
    inp = T1Input(**{k: v for k, v in body.model_dump().items() if k != "bc_net_tax"})
    result = calculate_t1(inp, bc_net_tax=body.bc_net_tax)
    return result.__dict__


@app.post("/tax/bc428/calculate")
async def calculate_bc428_api(body: BC428CalcRequest):
    data = body.model_dump()
    taxable_income = data.pop("taxable_income")
    eligible_div   = data.pop("eligible_div_taxable")
    non_eligible   = data.pop("non_eligible_div_taxable")
    inp = BC428Input(**data)
    result = calculate_bc428(inp, taxable_income, eligible_div, non_eligible)
    return result.__dict__


# ── PDF export ────────────────────────────────────────────────────────────────

# Line labels used when generating PDF printouts
_T1_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Step 2 — Total Income", [
        ("10100","Employment income"), ("10400","Other employment income"),
        ("11300","OAS pension"), ("11400","CPP/QPP benefits"),
        ("11500","Other pensions"), ("11700","RDSP income"),
        ("11900","Employment insurance"), ("12000","Eligible dividends (grossed-up)"),
        ("12010","Other dividends (grossed-up)"), ("12100","Interest income"),
        ("12200","Net partnership income"), ("12500","RDSP income"),
        ("12600","Net rental income"), ("12700","Taxable capital gains"),
        ("12900","RRSP income"), ("13000","Other income"),
        ("13500","Business income"), ("13700","Professional income"),
        ("13900","Commission income"), ("14100","Farming income"),
        ("14300","Fishing income"), ("14400","Workers' compensation"),
        ("14500","Social assistance"), ("14600","Net federal supplements"),
        ("15000","Total income ←"),
    ]),
    ("Step 3 — Net Income", [
        ("20800","RRSP/PRPP deduction"), ("21200","Union/professional dues"),
        ("20700","RPP deduction"), ("21000","Split-pension deduction"),
        ("22100","Carrying charges"), ("22200","CPP/QPP (self-employment)"),
        ("23300","Total deductions"), ("23400","Line 15000 − 23300"),
        ("23500","Social benefits repayment"), ("23600","Net income ←"),
    ]),
    ("Step 4 — Taxable Income", [
        ("25000","Other payments deduction"), ("25200","Non-capital losses"),
        ("25300","Net capital losses"), ("26000","Taxable income ←"),
    ]),
    ("Schedule 1 — Federal Credits", [
        ("30000","Basic personal amount"), ("30100","Age amount"),
        ("31000","CPP contributions"), ("31200","EI premiums"),
        ("31260","Canada employment amount"), ("31400","Pension income amount"),
        ("31600","Disability amount"), ("32300","Tuition amounts"),
        ("33099","Medical expenses"), ("34900","Donations and gifts"),
        ("35000","Total federal credit amounts"), ("35100","Federal non-refundable credit (×14.5%)"),
    ]),
    ("Step 5 — Federal Tax", [
        ("38000","Federal tax on taxable income"), ("40425","Federal dividend tax credit"),
        ("40424","Net federal tax"), ("42000","BC provincial tax"),
        ("44800","CPP payable on self-employment"), ("48200","Total payable ←"),
        ("43700","Total income tax deducted"), ("47600","CPP overpayment"),
        ("47900","Provincial credits"), ("48400","Refund ←"),
        ("48500","Balance owing ←"),
    ]),
]

_BC428_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Part 1 — BC Tax on Taxable Income", [
        ("taxableIncome","Taxable income (from T1 line 26000)"),
        ("bcTax","BC tax on taxable income"),
    ]),
    ("Part 2 — BC Non-Refundable Tax Credits", [
        ("58040","BC basic personal amount"), ("58080","BC age amount"),
        ("58120","Spouse/partner amount"), ("58160","Eligible dependant"),
        ("58240","CPP contributions"), ("58280","EI premiums"),
        ("58300","Volunteer firefighter / SAR amount"),
        ("bcPensionAmt","BC pension income amount"),
        ("58360","BC disability amount"), ("58400","Disability (dependant)"),
        ("58440","Student loan interest"), ("58480","Tuition amounts"),
        ("58689","Medical expenses"), ("58800","Donations and gifts"),
        ("59090","Total BC credit amounts"), ("bcCredits","BC non-refundable credit (×5.06%)"),
    ]),
    ("Part 3 — Net BC Tax", [
        ("bcDTC","BC dividend tax credit"), ("61520","BC political contribution credit"),
        ("42800","BC tax ← (enter on T1 line 42000)"),
    ]),
]


def _build_pdf(
    title: str,
    subtitle: str,
    form_num: str,
    sections: list[tuple[str, list[tuple[str, str]]]],
    lines: dict[str, float],
) -> bytes:
    """Generate a filled-form PDF using fpdf2."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    NL = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}

    def _safe(s: str) -> str:
        """Replace characters outside Latin-1 with ASCII equivalents."""
        return (
            s.replace("\u2014", "-").replace("\u2013", "-")   # em/en dash
             .replace("\u2019", "'").replace("\u2018", "'")   # curly apostrophes
             .replace("\u201c", '"').replace("\u201d", '"')   # curly quotes
             .replace("\u00e9", "e").replace("\u00e8", "e")   # accents
             .replace("\u00e0", "a").replace("\u00f9", "u")
             .encode("latin-1", errors="replace").decode("latin-1")
        )

    MARGIN = 12
    ROW_H  = 6
    HDR_H  = 8

    pdf = FPDF()
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.add_page()

    eff_w  = pdf.epw   # effective page width after margins

    # ── Form header ──────────────────────────────────────────────────────────
    pdf.set_fill_color(38, 55, 74)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(eff_w, HDR_H + 2, _safe(f"  {title}"), fill=True, **NL)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(eff_w, 5, _safe(f"  {subtitle}"), fill=True, **NL)

    pdf.set_fill_color(51, 80, 117)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(eff_w, 5,
             f"  Protected B when completed   .   2025 tax year   .   {form_num}",
             fill=True, **NL)
    pdf.ln(3)

    # column widths
    desc_w = eff_w * 0.62
    line_w = eff_w * 0.12
    amt_w  = eff_w - desc_w - line_w

    # ── Sections ─────────────────────────────────────────────────────────────
    for sec_title, items in sections:
        # Section header
        pdf.set_fill_color(28, 28, 28)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(eff_w, ROW_H, _safe(f"  {sec_title.upper()}"), fill=True, **NL)

        # Column headers
        pdf.set_fill_color(210, 210, 210)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(desc_w, ROW_H - 1, " Description",  border="B", fill=True)
        pdf.cell(line_w, ROW_H - 1, "Line",  border="B", fill=True, align="C")
        pdf.cell(amt_w,  ROW_H - 1, "Amount ($)",  border="B", fill=True,
                 align="R", **NL)

        # Data rows
        for line_id, label in items:
            val      = lines.get(str(line_id), 0.0)
            is_total = label.endswith("←")
            disp     = _safe(label.rstrip(" ←"))

            if is_total:
                pdf.set_font("Helvetica", "B", 7)
                pdf.set_fill_color(225, 225, 225)
                fill = True
                pdf.set_text_color(0, 0, 128)
            else:
                pdf.set_font("Helvetica", "", 7)
                pdf.set_fill_color(255, 255, 255)
                fill = False
                pdf.set_text_color(0, 0, 0)

            amt_str = f"{val:,.2f}" if val else "0.00"

            pdf.cell(desc_w, ROW_H, f" {disp}", border="B", fill=fill)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(line_w, ROW_H, str(line_id), border="B", fill=fill, align="C")
            if is_total:
                pdf.set_text_color(0, 0, 128)
            pdf.cell(amt_w, ROW_H, f"{amt_str} ", border="B", fill=fill,
                     align="R", **NL)
            pdf.set_text_color(0, 0, 0)

        pdf.ln(2)

    # Footer
    pdf.set_y(-10)
    pdf.set_font("Helvetica", "I", 6)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 4,
             "Generated by CRA Tax Helper  .  2025 tax year  .  All calculations are estimates.",
             align="C")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


class T1PDFBody(BaseModel):
    """All T1 line values (user-entered + calculated) for PDF generation."""
    lines: Dict[str, float] = {}
    age_65: bool = False


class BC428PDFBody(BaseModel):
    """All BC428 line values for PDF generation."""
    lines: Dict[str, float] = {}
    age_65: bool = False


@app.post("/tax/t1/pdf")
async def t1_pdf(body: T1PDFBody):
    # ── Preferred: fill the official CRA fillable PDF ─────────────────────────
    str_lines = {k: v for k, v in body.lines.items()}
    official = fill_official_pdf("t1-2025.pdf", str_lines)
    if official:
        return Response(
            content=official,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="T1-2025-filled.pdf"'},
        )
    # ── Fallback: generated summary PDF ───────────────────────────────────────
    pdf_bytes = _build_pdf(
        title="T1 General — Income Tax and Benefit Return",
        subtitle="Steps 2, 3, 4 and 5  ·  British Columbia resident",
        form_num="T1-2025",
        sections=_T1_SECTIONS,
        lines=body.lines,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="T1-2025.pdf"',
            "X-Pdf-Source": "generated-summary",
        },
    )


@app.post("/tax/bc428/pdf")
async def bc428_pdf(body: BC428PDFBody):
    # ── Preferred: fill the official CRA fillable PDF ─────────────────────────
    str_lines = {k: v for k, v in body.lines.items()}
    official = fill_official_pdf("bc428-2025.pdf", str_lines)
    if official:
        return Response(
            content=official,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="BC428-2025-filled.pdf"'},
        )
    # ── Fallback: generated summary PDF ───────────────────────────────────────
    pdf_bytes = _build_pdf(
        title="BC428 — British Columbia Tax",
        subtitle="Form 5010-C  ·  British Columbia residents",
        form_num="BC428-2025",
        sections=_BC428_SECTIONS,
        lines=body.lines,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="BC428-2025.pdf"',
            "X-Pdf-Source": "generated-summary",
        },
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"service": "taxhelper", "status": "ok"}
