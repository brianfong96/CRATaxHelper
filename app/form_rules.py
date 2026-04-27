"""
CRA Tax Helper – Cross-Form Rules Engine
=========================================
Single source of truth for every inter-form data connection.

Structure
---------
CROSS_FORM_RULES   – dict keyed by form slug; each entry describes what a
                     form sends TO T1 and what it reads FROM T1.
T1_LINE_SOURCES    – maps T1 line numbers to their source (user input,
                     auto-calculated within T1, or driven by a sub-form).
T1_EXPORTS         – what T1 publishes to localStorage so sub-forms can read it.

Every test in tests/test_cross_form.py is driven from these dicts.  Adding a
new form or a new connection only requires updating this file; the tests will
automatically cover the new entries.
"""

from __future__ import annotations
from typing import TypedDict, Optional


class SubFormExport(TypedDict):
    """One value a sub-form writes back to T1."""
    t1_line: Optional[int]        # CRA line number that gets filled in T1
    t1_field_id: Optional[str]    # HTML element id in t1.html
    url_param: str                # key in the ?query_string passed to /tax/t1
    localStorage_key: str         # key written to localStorage by the sub-form
    description: str


class T1Import(TypedDict):
    """One value T1 publishes so a sub-form can read it."""
    t1_line: int
    localStorage_key: str
    url_param: Optional[str]      # present if T1 also passes it as a URL param
    description: str


class FormRule(TypedDict):
    name: str
    template: str                 # path relative to app/templates/
    autosave_key: str             # localStorage key for the form's own data
    writes_to_t1: list[SubFormExport]
    reads_from_t1: list[T1Import]


# ---------------------------------------------------------------------------
# Sub-form rules
# ---------------------------------------------------------------------------

CROSS_FORM_RULES: dict[str, FormRule] = {
    "bc428": {
        "name": "BC 428",
        "template": "bc428.html",
        "autosave_key": "cra_bc428_autosave",
        "writes_to_t1": [
            {
                "t1_line": None,       # drives the BC provincial tax calc
                "t1_field_id": None,
                "url_param": "bc_net_tax",
                "localStorage_key": "cra_bc428_net_tax",
                "description": "BC provincial net tax",
            },
        ],
        "reads_from_t1": [
            {
                "t1_line": 26000,
                "localStorage_key": "cra_t1_line26000",
                "url_param": "ti",
                "description": "Taxable income (line 26000)",
            },
            {
                "t1_line": 12000,
                "localStorage_key": "cra_t1_line12000",
                "url_param": "d1",
                "description": "Eligible dividends (line 12000)",
            },
            {
                "t1_line": 12010,
                "localStorage_key": "cra_t1_line12010",
                "url_param": "d2",
                "description": "Other dividends (line 12010)",
            },
        ],
    },
    "bc479": {
        "name": "BC 479",
        "template": "bc479.html",
        "autosave_key": "cra_bc479_autosave",
        "writes_to_t1": [
            {
                "t1_line": 47900,
                "t1_field_id": "f47900",
                "url_param": "bc479_credits",
                "localStorage_key": "cra_bc479_credits",
                "description": "BC tax credits (line 47900)",
            },
        ],
        "reads_from_t1": [],
    },
    "schedule3": {
        "name": "Schedule 3",
        "template": "schedule3.html",
        "autosave_key": "cra_s3_autosave",
        "writes_to_t1": [
            {
                "t1_line": 12700,
                "t1_field_id": "f12700",
                "url_param": "s3_cap_gains",
                "localStorage_key": "cra_s3_cap_gains",
                "description": "Net capital gains (line 12700)",
            },
        ],
        "reads_from_t1": [],
    },
    "schedule5": {
        "name": "Schedule 5",
        "template": "schedule5.html",
        "autosave_key": "cra_schedule5_autosave",
        "writes_to_t1": [
            {
                "t1_line": 30300,
                "t1_field_id": "f30300",
                "url_param": "s5_30300",
                "localStorage_key": "cra_s5_30300",
                "description": "Spousal/CLP amount (line 30300)",
            },
            {
                "t1_line": 30400,
                "t1_field_id": "f30400",
                "url_param": "s5_30400",
                "localStorage_key": "cra_s5_30400",
                "description": "Eligible dependant amount (line 30400)",
            },
        ],
        "reads_from_t1": [],
    },
    "schedule7": {
        "name": "Schedule 7",
        "template": "schedule7.html",
        "autosave_key": "cra_schedule7_autosave",
        "writes_to_t1": [
            {
                "t1_line": 20800,
                "t1_field_id": "f20800",
                "url_param": "s7_20800",
                "localStorage_key": "cra_s7_20800",
                "description": "RRSP/FHSA deduction (line 20800)",
            },
        ],
        "reads_from_t1": [],
    },
    "schedule8": {
        "name": "Schedule 8",
        "template": "schedule8.html",
        "autosave_key": "cra_schedule8_autosave",
        "writes_to_t1": [
            {
                "t1_line": 22200,
                "t1_field_id": "f22200",
                "url_param": "s8_22200",
                "localStorage_key": "cra_s8_22200",
                "description": "CPP/EI deduction (line 22200)",
            },
        ],
        "reads_from_t1": [],
    },
    "schedule9": {
        "name": "Schedule 9",
        "template": "schedule9.html",
        "autosave_key": "cra_s9_autosave",
        "writes_to_t1": [
            {
                "t1_line": 34900,
                "t1_field_id": "f34900",
                "url_param": "s9_donations",
                "localStorage_key": "cra_s9_donations",
                "description": "Charitable donations (line 34900)",
            },
        ],
        "reads_from_t1": [
            {
                "t1_line": 23600,
                "localStorage_key": "cra_t1_autosave",   # reads full autosave
                "url_param": None,
                "description": "Net income (line 23600) — read from full T1 autosave",
            },
        ],
    },
    "t777": {
        "name": "T777",
        "template": "t777.html",
        "autosave_key": "cra_t777_autosave",
        "writes_to_t1": [
            {
                "t1_line": 22900,
                "t1_field_id": "f22900",
                "url_param": "t777_22900",
                "localStorage_key": "cra_t777_22900",
                "description": "Employment expenses (line 22900)",
            },
        ],
        "reads_from_t1": [],
    },
    "t2209": {
        "name": "T2209",
        "template": "t2209.html",
        "autosave_key": "cra_t2209_autosave",
        "writes_to_t1": [
            {
                "t1_line": 40500,
                "t1_field_id": "f40500",
                "url_param": "t2209_40500",
                "localStorage_key": "cra_t2209_40500",
                "description": "Federal foreign tax credit (line 40500)",
            },
        ],
        "reads_from_t1": [],
    },
}

# ---------------------------------------------------------------------------
# What T1 exports to localStorage (for sub-forms to consume)
# ---------------------------------------------------------------------------

T1_EXPORTS: list[T1Import] = [
    {
        "t1_line": 26000,
        "localStorage_key": "cra_t1_line26000",
        "url_param": "ti",
        "description": "Taxable income (line 26000)",
    },
    {
        "t1_line": 12000,
        "localStorage_key": "cra_t1_line12000",
        "url_param": "d1",
        "description": "Eligible dividends (line 12000)",
    },
    {
        "t1_line": 12010,
        "localStorage_key": "cra_t1_line12010",
        "url_param": "d2",
        "description": "Other dividends (line 12010)",
    },
]

# ---------------------------------------------------------------------------
# T1 line classification
# ---------------------------------------------------------------------------
# "input"     – user types directly in T1
# "sub_form"  – driven by a sub-form (listed in CROSS_FORM_RULES above)
# "calc"      – auto-calculated within T1's recalcT1()

T1_LINE_SOURCES: dict[int, dict] = {
    # ── Income (page 3) ──────────────────────────────────────────────────
    10100: {"source": "input",    "desc": "Employment income"},
    10400: {"source": "input",    "desc": "Other employment income"},
    11300: {"source": "input",    "desc": "OAS pension"},
    11400: {"source": "input",    "desc": "CPP/QPP benefits"},
    11500: {"source": "input",    "desc": "Other pensions"},
    11600: {"source": "input",    "desc": "Elected split-pension amount"},
    11700: {"source": "input",    "desc": "UCCB"},
    11900: {"source": "input",    "desc": "Employment insurance"},
    12000: {"source": "input",    "desc": "Eligible dividends"},
    12010: {"source": "input",    "desc": "Other dividends"},
    12100: {"source": "input",    "desc": "Interest and investment income"},
    12200: {"source": "input",    "desc": "Net partnership income"},
    12500: {"source": "input",    "desc": "RDSP income"},
    12600: {"source": "input",    "desc": "Rental income (gross)"},
    12599: {"source": "input",    "desc": "Rental income (net)"},
    12700: {"source": "sub_form", "desc": "Net capital gains — from Schedule 3",    "sub_form": "schedule3"},
    12900: {"source": "input",    "desc": "RRSP income"},
    13000: {"source": "input",    "desc": "Other income"},
    13500: {"source": "input",    "desc": "Self-employment income (gross)"},
    13499: {"source": "input",    "desc": "Self-employment income (net)"},
    14300: {"source": "calc",     "desc": "Total income (line 15000 subtotal)"},
    15000: {"source": "calc",     "desc": "Total income"},
    # ── Deductions (page 3/4) ─────────────────────────────────────────────
    20600: {"source": "input",    "desc": "Pension adjustment"},
    20700: {"source": "input",    "desc": "RPP deduction"},
    20800: {"source": "sub_form", "desc": "RRSP/FHSA deduction — from Schedule 7", "sub_form": "schedule7"},
    20810: {"source": "input",    "desc": "PRPP deduction"},
    21000: {"source": "input",    "desc": "Split-pension deduction"},
    21200: {"source": "input",    "desc": "Annual union/professional dues"},
    21300: {"source": "input",    "desc": "Universal child care benefit repaid"},
    21400: {"source": "input",    "desc": "Child care expenses"},
    21500: {"source": "input",    "desc": "Disability supports deduction"},
    21699: {"source": "input",    "desc": "Business investment loss"},
    21900: {"source": "input",    "desc": "Moving expenses"},
    22000: {"source": "input",    "desc": "Support payments made"},
    22100: {"source": "input",    "desc": "Carrying charges and interest"},
    22200: {"source": "sub_form", "desc": "CPP/EI deduction — from Schedule 8",    "sub_form": "schedule8"},
    22215: {"source": "input",    "desc": "Deduction for enhanced CPP/QPP"},
    22400: {"source": "input",    "desc": "Exploration/development expenses"},
    22900: {"source": "sub_form", "desc": "Employment expenses — from T777",       "sub_form": "t777"},
    23100: {"source": "input",    "desc": "Other employment expenses"},
    23200: {"source": "input",    "desc": "Other deductions"},
    23300: {"source": "calc",     "desc": "Total deductions"},
    23400: {"source": "calc",     "desc": "Net income before adjustments"},
    23500: {"source": "input",    "desc": "Social benefits repayment"},
    23600: {"source": "calc",     "desc": "Net income"},
    24400: {"source": "input",    "desc": "Military/police deduction"},
    24900: {"source": "input",    "desc": "Security options deductions"},
    25000: {"source": "input",    "desc": "Other payments deduction"},
    25100: {"source": "input",    "desc": "Limited partnership losses of other years"},
    25200: {"source": "input",    "desc": "Non-capital losses of other years"},
    25300: {"source": "input",    "desc": "Net capital losses of other years"},
    25400: {"source": "input",    "desc": "Capital gains deduction"},
    25500: {"source": "input",    "desc": "Northern residents deductions"},
    25600: {"source": "input",    "desc": "Additional deductions"},
    26000: {"source": "calc",     "desc": "Taxable income"},
    # ── Federal credits (page 4/5) ────────────────────────────────────────
    30000: {"source": "calc",     "desc": "Basic personal amount"},
    30100: {"source": "calc",     "desc": "Age amount"},
    30300: {"source": "sub_form", "desc": "Spousal/CLP amount — from Schedule 5",  "sub_form": "schedule5"},
    30400: {"source": "sub_form", "desc": "Eligible dependant — from Schedule 5",  "sub_form": "schedule5"},
    30425: {"source": "input",    "desc": "Eligible dependant supplement"},
    30450: {"source": "input",    "desc": "Infirm dependant 18+"},
    30500: {"source": "input",    "desc": "CPP/QPP contributions (employment)"},
    31000: {"source": "input",    "desc": "CPP/QPP contributions (self-employment)"},
    31200: {"source": "input",    "desc": "Employment insurance premiums"},
    31217: {"source": "input",    "desc": "Employment insurance premiums (self-emp)"},
    31220: {"source": "input",    "desc": "Volunteer firefighter/SAR amount"},
    31240: {"source": "input",    "desc": "Canada employment amount"},
    31260: {"source": "input",    "desc": "Public transit amount"},
    31270: {"source": "input",    "desc": "Children's arts amount"},
    31285: {"source": "input",    "desc": "Home accessibility expenses"},
    31300: {"source": "input",    "desc": "Adoption expenses"},
    31350: {"source": "input",    "desc": "Home buyers' amount"},
    32300: {"source": "input",    "desc": "Tuition, education and textbook amounts"},
    32400: {"source": "input",    "desc": "Tuition transferred from child"},
    32600: {"source": "input",    "desc": "Tuition transferred from spouse"},
    33099: {"source": "input",    "desc": "Medical expenses (self/spouse)"},
    33199: {"source": "input",    "desc": "Medical expenses (other dependants)"},
    34900: {"source": "sub_form", "desc": "Donations/gifts — from Schedule 9",     "sub_form": "schedule9"},
    35000: {"source": "calc",     "desc": "Total federal non-refundable credits"},
    35100: {"source": "calc",     "desc": "Federal non-refundable tax credits"},
    # ── Federal tax (page 5) ──────────────────────────────────────────────
    38000: {"source": "calc",     "desc": "Net federal tax before credits"},
    40424: {"source": "calc",     "desc": "Federal dividend tax credit"},
    40425: {"source": "calc",     "desc": "Federal political contribution tax credit"},
    40500: {"source": "sub_form", "desc": "Federal foreign tax credit — from T2209","sub_form": "t2209"},
    42000: {"source": "calc",     "desc": "Net federal tax"},
    47900: {"source": "sub_form", "desc": "BC credits — from BC479",               "sub_form": "bc479"},
    # ── Payments/refund ───────────────────────────────────────────────────
    43700: {"source": "input",    "desc": "Total income tax deducted"},
    44800: {"source": "input",    "desc": "CPP overpayment"},
    45200: {"source": "input",    "desc": "Medical expense supplement"},
    45300: {"source": "calc",     "desc": "Canada workers benefit"},
    46800: {"source": "input",    "desc": "Climate action incentive"},
    46900: {"source": "input",    "desc": "Disability tax credit supplement"},
    47600: {"source": "input",    "desc": "Tax instalments paid"},
    48200: {"source": "calc",     "desc": "Total credits/payments"},
    48400: {"source": "calc",     "desc": "Refund"},
    48500: {"source": "calc",     "desc": "Balance owing"},
}


def get_sub_form_lines() -> dict[int, str]:
    """Return {t1_line: form_slug} for every line driven by a sub-form."""
    result: dict[int, str] = {}
    for slug, rule in CROSS_FORM_RULES.items():
        for export in rule["writes_to_t1"]:
            if export["t1_line"] is not None:
                result[export["t1_line"]] = slug
    return result


def get_all_url_params_to_t1() -> list[dict]:
    """Return all URL params that any sub-form sends to T1."""
    params = []
    for slug, rule in CROSS_FORM_RULES.items():
        for export in rule["writes_to_t1"]:
            params.append({
                "form": slug,
                "url_param": export["url_param"],
                "localStorage_key": export["localStorage_key"],
                "t1_field_id": export.get("t1_field_id"),
                "description": export["description"],
            })
    return params


def get_all_t1_exports() -> list[dict]:
    """Return all localStorage keys T1 writes for sub-forms to read."""
    return [
        {"form": slug, **imp}
        for slug, rule in CROSS_FORM_RULES.items()
        for imp in rule["reads_from_t1"]
    ]
