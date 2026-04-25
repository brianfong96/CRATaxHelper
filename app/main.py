"""
CRA Tax Helper — FastAPI application.

Routes:
  GET  /                       Landing page
  GET  /health                 Health check
  GET  /tax/t1                 T1 General 2024 form
  GET  /tax/bc428              BC428 2024 form
  GET  /tax/compare            Side-by-side scenario comparison
  POST /tax/t1/calculate       JSON API – compute all T1 derived lines
  POST /tax/bc428/calculate    JSON API – compute all BC428 derived lines
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.calculator import (
    BC428Input,
    T1Input,
    calculate_bc428,
    calculate_t1,
)
from app.config import settings

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

# ── App & templates ───────────────────────────────────────────────────────────

app = FastAPI(
    title="CRA Tax Helper",
    description="Interactive CRA T1 General and BC428 tax calculator",
    version="1.0.0",
    # When deployed behind Atlas the root path is /app/cra-taxhelper
    root_path=settings.ROOT_PATH,
)

_TMPL_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TMPL_DIR))


def _ctx(request: Request, **extra):
    """Build a base template context."""
    return {"request": request, "root_path": settings.ROOT_PATH, **extra}


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", _ctx(request))


@app.get("/tax/t1", response_class=HTMLResponse)
async def t1_form(request: Request):
    return templates.TemplateResponse("t1.html", _ctx(request))


@app.get("/tax/bc428", response_class=HTMLResponse)
async def bc428_form(request: Request):
    return templates.TemplateResponse("bc428.html", _ctx(request))


@app.get("/tax/compare", response_class=HTMLResponse)
async def compare(request: Request):
    return templates.TemplateResponse("compare.html", _ctx(request))


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
    line_30000: float = 15705; line_30100: float = 0; line_30300: float = 0
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
    line_58040: float = 11981; line_58080: float = 0; line_58120: float = 0
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


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"service": "taxhelper", "status": "ok"}
