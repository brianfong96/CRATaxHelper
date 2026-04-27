"""
CRA Tax Helper — calculation engine (2025 tax year).

All formulas are based on publicly available CRA tax rates, brackets, and
credit amounts for the 2025 tax year.  Line numbers match the official
T1 General and BC428 (5010-C) forms.

Rules:
- All monetary inputs are in Canadian dollars (floats).
- Negative results are floored to 0 unless the field is explicitly a loss.
- Line numbers follow the 2025 T1 General and BC428 forms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

# ── 2025 Tax Constants ────────────────────────────────────────────────────────

# Federal income tax brackets (upper limit, marginal rate) — 2025 CRA Schedule 1
FEDERAL_BRACKETS: list[tuple[float, float]] = [
    (57_375,       0.1500),
    (114_750,      0.2050),
    (177_882,      0.2600),
    (253_414,      0.2900),
    (float("inf"), 0.3300),
]

# BC provincial income tax brackets
BC_BRACKETS: list[tuple[float, float]] = [
    (49_279,       0.0506),
    (98_560,       0.0770),
    (113_158,      0.1050),
    (137_407,      0.1229),
    (186_306,      0.1470),
    (259_829,      0.1680),
    (float("inf"), 0.2050),
]

# 2025 Federal amounts
FEDERAL_BASIC_PERSONAL       = 16_129.00
FEDERAL_AGE_AMOUNT_MAX       = 9_028.00
FEDERAL_AGE_INCOME_THRESHOLD = 45_522.00   # reduction begins here
FEDERAL_AGE_INCOME_CEILING   = 105_709.00  # 45,522 + 9,028 / 0.15
FEDERAL_EMPLOYMENT_MAX       = 1_471.00
FEDERAL_PENSION_MAX          = 2_000.00
FEDERAL_CREDIT_RATE          = 0.15        # 15% — federal non-refundable credit rate (Schedule 1)

# CPP 2025
CPP_RATE             = 0.0595
CPP_MAX_EARNINGS     = 73_200.0
CPP_BASIC_EXEMPT     = 3_500.0
CPP_MAX_CONTRIBUTION = round((CPP_MAX_EARNINGS - CPP_BASIC_EXEMPT) * CPP_RATE, 2)  # 4166.45
CPP2_RATE            = 0.04
CPP2_MAX_EARNINGS    = 81_900.0

# Federal 2025 (aliases for schedule calculations)
FED_BPA               = FEDERAL_BASIC_PERSONAL  # 16129.00
FED_CAREGIVER         = 8_375.0
CHILD_CAREGIVER_AMOUNT = 2_273.0
MEDICAL_THRESHOLD_MAX = 2_759.0

# 2025 BC amounts(source: BC government official credits page)
BC_BASIC_PERSONAL            = 12_932.00
BC_AGE_AMOUNT_MAX            = 5_799.00
BC_AGE_INCOME_THRESHOLD      = 43_169.00
BC_AGE_INCOME_CEILING        = 81_829.00   # 43,169 + 5,799 / 0.15
BC_PENSION_MAX               = 1_000.00
BC_DISABILITY                = 9_699.00
BC_CREDIT_RATE               = 0.0506

# Dividend gross-up factors (unchanged)
ELIGIBLE_GROSS_UP            = 1.38
NON_ELIGIBLE_GROSS_UP        = 1.15

# Federal dividend tax credit rates (applied to grossed-up taxable amount)
FEDERAL_ELIGIBLE_DTC_RATE    = (6 / 11) * (0.38 / 1.38)   # ≈ 15.0198 %
FEDERAL_NON_ELIGIBLE_DTC_RATE = (9 / 13) * (0.15 / 1.15)  # ≈  9.0301 %

# BC dividend tax credit rates — applied to grossed-up taxable dividend (2025)
BC_ELIGIBLE_DTC_RATE         = 0.12    # 12 % of taxable eligible dividends
BC_NON_ELIGIBLE_DTC_RATE     = 0.0196  # 1.96 % of taxable non-eligible dividends


# ── Helpers ───────────────────────────────────────────────────────────────────

def apply_brackets(income: float, brackets: list[tuple[float, float]]) -> float:
    """Apply progressive tax brackets to *income* and return total tax."""
    income = max(0.0, income)
    tax = 0.0
    prev = 0.0
    for limit, rate in brackets:
        if income <= prev:
            break
        taxable = min(income, limit) - prev
        tax += taxable * rate
        prev = limit
    return round(tax, 2)


def federal_age_amount(net_income: float, age_65_or_over: bool) -> float:
    """Return the 2025 federal age amount (line 30100)."""
    if not age_65_or_over:
        return 0.0
    if net_income <= FEDERAL_AGE_INCOME_THRESHOLD:
        return FEDERAL_AGE_AMOUNT_MAX
    if net_income >= FEDERAL_AGE_INCOME_CEILING:
        return 0.0
    reduction = (net_income - FEDERAL_AGE_INCOME_THRESHOLD) * 0.15
    return max(0.0, round(FEDERAL_AGE_AMOUNT_MAX - reduction, 2))


def bc_age_amount(net_income: float, age_65_or_over: bool) -> float:
    """Return the 2025 BC age amount (line 58080)."""
    if not age_65_or_over:
        return 0.0
    if net_income <= BC_AGE_INCOME_THRESHOLD:
        return BC_AGE_AMOUNT_MAX
    if net_income >= BC_AGE_INCOME_CEILING:
        return 0.0
    reduction = (net_income - BC_AGE_INCOME_THRESHOLD) * 0.15
    return max(0.0, round(BC_AGE_AMOUNT_MAX - reduction, 2))


# ── T1 Data Model ─────────────────────────────────────────────────────────────

@dataclass
class T1Input:
    """User-supplied fields on the 2025 T1 General (Step 2 – Step 5)."""

    # ── Step 2 — Total Income ──────────────────────────────────────────
    line_10100: float = 0.0   # Employment income
    line_10400: float = 0.0   # Other employment income
    line_11300: float = 0.0   # OAS pension
    line_11400: float = 0.0   # CPP/QPP benefits
    line_11500: float = 0.0   # Other pensions and superannuation
    line_11700: float = 0.0   # RDSP income
    line_11900: float = 0.0   # EI and other benefits
    line_12000: float = 0.0   # Taxable eligible dividends (grossed up 38 %)
    line_12010: float = 0.0   # Taxable non-eligible dividends (grossed up 15 %)
    line_12100: float = 0.0   # Interest and other investment income
    line_12200: float = 0.0   # Net partnership income (limited/non-active)
    line_12500: float = 0.0   # RDSP income (second RDSP line on form)
    line_12600: float = 0.0   # Net rental income (loss)
    line_12700: float = 0.0   # Taxable capital gains
    line_12900: float = 0.0   # RRSP income
    line_13000: float = 0.0   # Other income
    line_13010: float = 0.0   # Taxable scholarships / bursaries
    line_13500: float = 0.0   # Net business income
    line_13700: float = 0.0   # Net professional income
    line_13900: float = 0.0   # Net commission income
    line_14100: float = 0.0   # Net farming income
    line_14300: float = 0.0   # Net fishing income
    line_14400: float = 0.0   # Workers' compensation benefits
    line_14500: float = 0.0   # Social assistance payments
    line_14600: float = 0.0   # Net federal supplements

    # ── Step 3 — Net Income ────────────────────────────────────────────
    line_20600: float = 0.0   # Pension adjustment
    line_20700: float = 0.0   # RPP deduction
    line_20800: float = 0.0   # RRSP/PRPP deduction
    line_20810: float = 0.0   # FHSA deduction
    line_21000: float = 0.0   # Elected split-pension amount
    line_21200: float = 0.0   # Union / professional dues
    line_21300: float = 0.0   # UCCB repayment
    line_21400: float = 0.0   # Child care expenses
    line_21500: float = 0.0   # Disability supports deduction
    line_21699: float = 0.0   # Business investment loss
    line_21900: float = 0.0   # Moving expenses
    line_22000: float = 0.0   # Support payments made
    line_22100: float = 0.0   # Carrying charges and interest expenses
    line_22200: float = 0.0   # CPP/QPP on self-employment
    line_22215: float = 0.0   # CPP2 on self-employment
    line_22400: float = 0.0   # Exploration and development expenses
    line_22900: float = 0.0   # Other employment expenses
    line_23100: float = 0.0   # Clergy residence deduction
    line_23200: float = 0.0   # Other deductions
    line_23500: float = 0.0   # Social benefits repayment

    # ── Step 4 — Taxable Income ────────────────────────────────────────
    line_24400: float = 0.0   # Employee home relocation loan deduction
    line_24900: float = 0.0   # Security options deductions
    line_25000: float = 0.0   # Other payments deduction (workers' comp etc.)
    line_25100: float = 0.0   # Limited partnership losses
    line_25200: float = 0.0   # Non-capital losses of other years
    line_25300: float = 0.0   # Net capital losses of other years
    line_25400: float = 0.0   # Capital gains deduction
    line_25500: float = 0.0   # Northern residents deductions
    line_25600: float = 0.0   # Additional deductions

    # ── Schedule 1 — Federal Non-Refundable Tax Credits ───────────────
    # Personal amounts (most are entered by user; some are computed)
    line_30000: float = FEDERAL_BASIC_PERSONAL  # Basic personal amount
    line_30100: float = 0.0   # Age amount (auto-computed if age flag set)
    line_30300: float = 0.0   # Spouse/CLP amount
    line_30400: float = 0.0   # Amount for eligible dependant
    line_30425: float = 0.0   # Canada caregiver — spouse
    line_30450: float = 0.0   # Canada caregiver — other dependants 18+
    line_30500: float = 0.0   # Canada caregiver — children under 18
    line_31000: float = 0.0   # CPP/QPP contributions through employment
    line_31200: float = 0.0   # EI premiums through employment
    line_31205: float = 0.0   # CPP2 contributions through employment
    line_31217: float = 0.0   # EI premiums on self-employment
    line_31220: float = 0.0   # CPP/QPP contributions on self-employment
    line_31260: float = 0.0   # Canada employment amount (auto-computed)
    line_31270: float = 0.0   # Home buyers' amount
    line_31285: float = 0.0   # Home accessibility expenses
    line_31300: float = 0.0   # Adoption expenses
    line_31350: float = 0.0   # Digital news subscription expenses
    line_31400: float = 0.0   # Pension income amount (auto-computed, max $2,000)
    line_31401: float = 0.0   # Eligible pension income (source for 31400)
    line_31600: float = 0.0   # Disability amount (self)
    line_31800: float = 0.0   # Disability amount transferred from dependant
    line_31900: float = 0.0   # Interest paid on student loans
    line_32300: float = 0.0   # Tuition amounts
    line_32400: float = 0.0   # Tuition transferred from child
    line_32600: float = 0.0   # Amounts transferred from spouse/CLP
    line_33099: float = 0.0   # Medical expenses — self/spouse/minor children
    line_33199: float = 0.0   # Medical expenses — other dependants
    line_34900: float = 0.0   # Donations and gifts

    # ── Other Federal Tax items ────────────────────────────────────────
    line_40427: float = 0.0   # Minimum tax carryover
    line_40600: float = 0.0   # Federal political contribution tax credit
    line_40900: float = 0.0   # Investment tax credit
    line_43700: float = 0.0   # Total income tax deducted (from T4s etc.)
    line_44000: float = 0.0   # Refundable Quebec abatement
    line_44800: float = 0.0   # CPP contributions payable on self-employment
    line_45200: float = 0.0   # Social benefits repayment (= line_23500)
    line_47600: float = 0.0   # CPP overpayment
    line_47900: float = 0.0   # Provincial/territorial credits (Form 479)

    # Convenience flags
    age_65_or_over: bool = False


@dataclass
class T1Result:
    """All computed lines for the 2025 T1 General."""

    # Step 2
    line_15000: float = 0.0   # Total income

    # Step 3
    line_23300: float = 0.0   # Total deductions
    line_23400: float = 0.0   # Net income before social-benefits repayment
    line_23600: float = 0.0   # Net income

    # Step 4
    line_26000: float = 0.0   # Taxable income

    # Schedule 1 — credits
    line_30100: float = 0.0   # Age amount (computed)
    line_31260: float = 0.0   # Canada employment amount (computed)
    line_31400: float = 0.0   # Pension income amount (computed)
    line_35000: float = 0.0   # Total federal credit amounts
    line_35100: float = 0.0   # Federal non-refundable tax credit (35000 × 15 %)

    # Schedule 1 — tax
    line_38000: float = 0.0   # Federal tax on taxable income
    line_40425: float = 0.0   # Federal dividend tax credit
    line_40424: float = 0.0   # Net federal tax

    # Final
    line_42000: float = 0.0   # BC provincial tax (from BC428)
    line_48200: float = 0.0   # Total payable
    line_48400: float = 0.0   # Refund
    line_48500: float = 0.0   # Balance owing


def calculate_t1(inp: T1Input, bc_net_tax: float = 0.0) -> T1Result:
    """
    Compute all derived T1 lines from *inp*.

    Pass *bc_net_tax* (line 42800 from BC428) to include provincial tax in the
    refund / balance-owing calculation.
    """
    r = T1Result()

    # ── Step 2: Total income ──────────────────────────────────────────
    r.line_15000 = round(sum([
        inp.line_10100, inp.line_10400, inp.line_11300, inp.line_11400,
        inp.line_11500, inp.line_11700, inp.line_11900, inp.line_12000,
        inp.line_12010, inp.line_12100, inp.line_12200, inp.line_12500,
        inp.line_12600, inp.line_12700, inp.line_12900, inp.line_13000,
        inp.line_13010, inp.line_13500, inp.line_13700, inp.line_13900,
        inp.line_14100, inp.line_14300, inp.line_14400, inp.line_14500,
        inp.line_14600,
    ]), 2)

    # ── Step 3: Net income ────────────────────────────────────────────
    r.line_23300 = round(sum([
        inp.line_20600, inp.line_20700, inp.line_20800, inp.line_20810,
        inp.line_21000, inp.line_21200, inp.line_21300, inp.line_21400,
        inp.line_21500, inp.line_21699, inp.line_21900, inp.line_22000,
        inp.line_22100, inp.line_22200, inp.line_22215, inp.line_22400,
        inp.line_22900, inp.line_23100, inp.line_23200,
    ]), 2)

    r.line_23400 = round(max(0.0, r.line_15000 - r.line_23300), 2)
    r.line_23600 = round(max(0.0, r.line_23400 - inp.line_23500), 2)

    # ── Step 4: Taxable income ────────────────────────────────────────
    step4_deductions = round(sum([
        inp.line_24400, inp.line_24900, inp.line_25000, inp.line_25100,
        inp.line_25200, inp.line_25300, inp.line_25400, inp.line_25500,
        inp.line_25600,
    ]), 2)
    r.line_26000 = round(max(0.0, r.line_23600 - step4_deductions), 2)

    # ── Schedule 1: Computed credit amounts ──────────────────────────
    r.line_30100 = federal_age_amount(r.line_23600, inp.age_65_or_over)
    r.line_31260 = round(min(inp.line_10100 + inp.line_10400, FEDERAL_EMPLOYMENT_MAX), 2)
    r.line_31400 = round(min(inp.line_31401, FEDERAL_PENSION_MAX), 2)

    # ── Schedule 1: Total credit base (35000) ────────────────────────
    r.line_35000 = round(sum([
        inp.line_30000, r.line_30100, inp.line_30300, inp.line_30400,
        inp.line_30425, inp.line_30450, inp.line_30500,
        inp.line_31000, inp.line_31200, inp.line_31205, inp.line_31217,
        inp.line_31220, r.line_31260, inp.line_31270, inp.line_31285,
        inp.line_31300, inp.line_31350, r.line_31400,
        inp.line_31600, inp.line_31800, inp.line_31900,
        inp.line_32300, inp.line_32400, inp.line_32600,
        inp.line_33099, inp.line_33199, inp.line_34900,
    ]), 2)

    r.line_35100 = round(r.line_35000 * FEDERAL_CREDIT_RATE, 2)

    # ── Schedule 1: Federal tax ───────────────────────────────────────
    r.line_38000 = apply_brackets(r.line_26000, FEDERAL_BRACKETS)

    # Federal dividend tax credit (line 40425)
    eligible_dtc     = inp.line_12000 * FEDERAL_ELIGIBLE_DTC_RATE
    non_eligible_dtc = inp.line_12010 * FEDERAL_NON_ELIGIBLE_DTC_RATE
    r.line_40425 = round(eligible_dtc + non_eligible_dtc, 2)

    # Net federal tax (line 40424)
    r.line_40424 = round(max(0.0,
        r.line_38000
        - r.line_35100
        - r.line_40425
        - inp.line_40427
        - inp.line_40600
        - inp.line_40900
    ), 2)

    # ── Provincial tax ────────────────────────────────────────────────
    r.line_42000 = round(max(0.0, bc_net_tax), 2)

    # ── Total payable ─────────────────────────────────────────────────
    r.line_48200 = round(
        r.line_40424 + r.line_42000 + inp.line_44800 + inp.line_45200, 2
    )

    # ── Refund / balance owing ────────────────────────────────────────
    total_credits = inp.line_43700 + inp.line_47600 + inp.line_47900
    diff = round(total_credits - r.line_48200, 2)
    r.line_48400 = round(max(0.0,  diff), 2)   # refund
    r.line_48500 = round(max(0.0, -diff), 2)   # balance owing

    return r


# ── BC428 Data Model ──────────────────────────────────────────────────────────

@dataclass
class BC428Input:
    """User-supplied fields on the 2025 BC428 (5010-C)."""

    # BC428 Part 2 — Non-refundable tax credits
    # Line numbers match the 2024 BC428 form
    line_58040: float = BC_BASIC_PERSONAL  # BC basic personal amount
    line_58080: float = 0.0   # BC age amount (auto-computed if age flag set)
    line_58120: float = 0.0   # BC spousal/CLP amount
    line_58160: float = 0.0   # BC amount for eligible dependant
    line_58200: float = 0.0   # BC caregiver for spouse/CLP
    line_58240: float = 0.0   # BC CPP/QPP contributions through employment
    line_58280: float = 0.0   # BC EI premiums through employment
    line_58300: float = 0.0   # Volunteer firefighter / SAR volunteer amount (user-entered, max $3,000)
    line_58360: float = 0.0   # BC disability amount (self) (max $9,428)
    line_58400: float = 0.0   # BC disability amount transferred
    line_58440: float = 0.0   # BC interest paid on student loans
    line_58480: float = 0.0   # BC tuition and education amounts
    line_58560: float = 0.0   # BC tuition transferred from child
    line_58640: float = 0.0   # BC amounts transferred from spouse/CLP
    line_58689: float = 0.0   # BC medical expenses — self/spouse/minor children
    line_58729: float = 0.0   # BC medical expenses — other dependants
    line_58800: float = 0.0   # BC donations and gifts

    # Other BC tax items
    line_61520: float = 0.0   # BC political contribution tax credit
    line_61600: float = 0.0   # BC mining exploration tax credit

    # Eligible pension income (for BC pension income amount, max $1,000)
    bc_eligible_pension: float = 0.0

    age_65_or_over: bool = False


@dataclass
class BC428Result:
    """All computed lines for the 2025 BC428."""

    bc_tax_on_income: float = 0.0    # BC tax before credits (Part 1)
    line_58080:       float = 0.0    # BC age amount (computed)
    line_58300:       float = 0.0    # Volunteer firefighter / SAR volunteer amount
    bc_pension_amt:   float = 0.0    # BC pension income amount (computed, max $1,000)
    line_59090:       float = 0.0    # Total BC credit amounts
    bc_credits:       float = 0.0    # 59090 × 5.06 %
    bc_dtc:           float = 0.0    # BC dividend tax credit
    line_42800:       float = 0.0    # Net BC tax


# ── Schedule 9 Data Model ─────────────────────────────────────────────────────

@dataclass
class Schedule9Input:
    """User-supplied fields on the 2025 Schedule 9 (5000-S9)."""

    line_1: float = 0.0    # charitable org donations (current year)
    line_2: float = 0.0    # govt/municipality donations
    line_3: float = 0.0    # outside-Canada universities
    line_4: float = 0.0    # UN/foreign charities
    line_11: float = 0.0   # ecological/cultural gifts
    line_15: float = 0.0   # ecological gifts 2014-2016
    amt_B: float = 0.0     # depreciable capital property gifts
    amt_C: float = 0.0     # other capital property gifts
    net_income_23600: float = 0.0        # T1 line 23600
    taxable_income_26000: float = 0.0   # T1 line 26000


def calculate_schedule9(inp: Schedule9Input) -> dict[str, float]:
    """
    Compute all derived Schedule 9 lines from *inp*.

    Returns a dict keyed by line identifier (matching the form).
    line23 is the total charitable donations credit → T1 line 34900.
    """
    line5  = round(inp.line_1 + inp.line_2 + inp.line_3 + inp.line_4, 2)
    line6A = round(inp.net_income_23600 * 0.75, 2)
    line7D = round((inp.amt_B + inp.amt_C) * 0.25, 2)
    line8  = round(line6A + line7D, 2)
    line9  = round(min(line6A, line8), 2)
    line10 = round(min(line5, line9), 2)
    line12 = round(line10 + inp.line_11, 2)
    line13 = round(min(line12, 200.0), 2)
    line14 = round(line12 - line13, 2)
    line16 = round(max(0.0, line14 - inp.line_15), 2)
    line19 = round(max(0.0, inp.taxable_income_26000 - 253_414.0), 2)
    f      = min(line16, line19)
    line20 = round(f * 0.33, 2)
    line21 = round((line14 - f) * 0.29, 2)
    line22 = round(line13 * 0.145, 2)
    line23 = round(line20 + line21 + line22, 2)

    return {
        "line5":  line5,
        "line6A": line6A,
        "line7D": line7D,
        "line8":  line8,
        "line9":  line9,
        "line10": line10,
        "line12": line12,
        "line13": line13,
        "line14": line14,
        "line16": line16,
        "line19": line19,
        "line20": line20,
        "line21": line21,
        "line22": line22,
        "line23": line23,
    }


# ── BC479 Data Model ──────────────────────────────────────────────────────────

@dataclass
class BC479Input:
    """User-supplied fields on the 2025 BC479 (5010-TC)."""

    # Sales tax credit — two-column income chart
    line1_col1: float = 0.0   # net income (you)
    line1_col2: float = 0.0   # net income (spouse)
    line2_col1: float = 0.0   # UCCB/RDSP repayments (you)
    line2_col2: float = 0.0   # UCCB/RDSP repayments (spouse)
    line4_col1: float = 0.0   # UCCB/RDSP income (you)
    line4_col2: float = 0.0   # UCCB/RDSP income (spouse)
    has_spouse: bool = False   # True → $18,000 threshold; False → $15,000
    # Home renovation (senior/disability)
    line14_input: float = 0.0   # home renovation eligible expenses (max $10,000)
    # Venture capital (simplified totals)
    line17: float = 0.0
    line18: float = 0.0
    line21: float = 0.0
    line23: float = 0.0
    # Mining exploration
    line26: float = 0.0
    line27: float = 0.0
    # Clean buildings
    line28: float = 0.0
    line29: float = 0.0
    # Training tax credit
    line31: float = 0.0
    line32: float = 0.0
    line33: float = 0.0
    # Renter's tax credit
    rental_months: int = 0
    line39: float = 0.0   # adjusted family net income for renter's credit


def calculate_bc479(inp: BC479Input) -> dict[str, float]:
    """
    Compute all derived BC479 lines from *inp*.

    line45 is the total BC credits → T1 line 47900.
    """
    # ── Sales tax credit ─────────────────────────────────────────────
    line3_col1 = round(inp.line1_col1 + inp.line2_col1, 2)
    line3_col2 = round(inp.line1_col2 + inp.line2_col2, 2)
    line5_col1 = round(max(0.0, line3_col1 - inp.line4_col1), 2)
    line5_col2 = round(max(0.0, line3_col2 - inp.line4_col2), 2)
    line6  = round(line5_col1 + line5_col2, 2)
    line7  = 18_000.0 if inp.has_spouse else 15_000.0
    line8  = round(max(0.0, line6 - line7), 2)
    line9  = 75.0
    line10 = 75.0 if inp.has_spouse else 0.0
    line11 = round(line9 + line10, 2)
    line12_credit = round(line8 * 0.02, 2)
    line13 = round(max(0.0, line11 - line12_credit), 2)

    # ── Home renovation (10 %) ────────────────────────────────────────
    line14_result = round(min(inp.line14_input, 10_000.0) * 0.10, 2)
    line15 = round(line13 + line14_result, 2)

    # ── Carry-forward ────────────────────────────────────────────────
    line16 = line15

    # ── Venture capital (simplified: sum up input credits) ────────────
    line25 = round(inp.line17 + inp.line18 + inp.line21 + inp.line23, 2)

    # ── Mining exploration ────────────────────────────────────────────
    line26 = inp.line26
    line27 = inp.line27

    # ── Clean buildings ───────────────────────────────────────────────
    line30 = round(inp.line28 + inp.line29, 2)

    # ── Training tax credit ───────────────────────────────────────────
    line34 = round(inp.line31 + inp.line32 + inp.line33, 2)

    # ── Subtotal ──────────────────────────────────────────────────────
    line35 = round(line16 + line25 + line26 + line30 + line34, 2)

    # ── Renter's tax credit ───────────────────────────────────────────
    line36 = line35
    line40 = 64_764.0
    line41 = round(max(0.0, inp.line39 - line40), 2)
    line43 = round(line41 * 0.02, 2)
    line44 = round(max(0.0, 400.0 - line43), 2) if inp.rental_months > 0 else 0.0

    # ── Total BC credits ──────────────────────────────────────────────
    line45 = round(line36 + line44, 2)

    return {
        "line3_col1":  line3_col1,
        "line3_col2":  line3_col2,
        "line5_col1":  line5_col1,
        "line5_col2":  line5_col2,
        "line6":       line6,
        "line7":       line7,
        "line8":       line8,
        "line9":       line9,
        "line10":      line10,
        "line11":      line11,
        "line12_credit": line12_credit,
        "line13":      line13,
        "line14_result": line14_result,
        "line15":      line15,
        "line16":      line16,
        "line25":      line25,
        "line26":      line26,
        "line27":      line27,
        "line30":      line30,
        "line34":      line34,
        "line35":      line35,
        "line36":      line36,
        "line41":      line41,
        "line43":      line43,
        "line44":      line44,
        "line45":      line45,
    }


# ── Schedule 3 Data Model ─────────────────────────────────────────────────────

@dataclass
class Schedule3Input:
    """User-supplied fields on the 2025 Schedule 3 (5000-S3)."""

    # 10 disposition rows: proceeds, adjusted cost base, outlays/expenses
    proceeds: list[float] = field(default_factory=lambda: [0.0] * 10)
    cost:     list[float] = field(default_factory=lambda: [0.0] * 10)
    outlays:  list[float] = field(default_factory=lambda: [0.0] * 10)

    # Part 4 additional gains/losses from other schedules
    line13: float = 0.0   # additional gains (add)
    line14: float = 0.0   # deductions (subtract)
    line15: float = 0.0   # additional gains (add)
    line16: float = 0.0   # deductions (subtract)
    line17: float = 0.0   # additional gains (add)
    line18: float = 0.0   # deductions (subtract)
    line19: float = 0.0   # additional gains (add)
    line20: float = 0.0   # deductions (subtract)

    # Part 5
    line23_deduction: float = 0.0   # capital gains deduction
    line24_employee:  float = 0.0   # employee stock option deduction


def calculate_schedule3(inp: Schedule3Input) -> dict[str, float]:
    """
    Compute all derived Schedule 3 lines from *inp*.

    line26 is taxable capital gains (50 % inclusion) → T1 line 12700.
    """
    # ── Part 3: per-row gain/loss ─────────────────────────────────────
    gain_loss = [
        round(inp.proceeds[i] - inp.cost[i] - inp.outlays[i], 2)
        for i in range(10)
    ]
    line11 = round(sum(gain_loss), 2)

    # ── Part 4: net capital gains/losses ─────────────────────────────
    line12 = line11
    line21 = round(
        line12
        + inp.line13 - inp.line14
        + inp.line15 - inp.line16
        + inp.line17 - inp.line18
        + inp.line19 - inp.line20,
        2,
    )

    # ── Part 5: taxable capital gains ────────────────────────────────
    line22 = round(max(0.0, line21), 2)
    line25 = round(max(0.0, line22 - inp.line23_deduction - inp.line24_employee), 2)
    line26 = round(line25 * 0.5, 2)

    return {
        "gain_loss": gain_loss,
        "line11":    line11,
        "line12":    line12,
        "line21":    line21,
        "line22":    line22,
        "line25":    line25,
        "line26":    line26,
    }


def calculate_bc428(
    inp: BC428Input,
    taxable_income: float,
    eligible_div_taxable: float = 0.0,
    non_eligible_div_taxable: float = 0.0,
) -> BC428Result:
    """
    Compute BC428.

    *taxable_income*          — T1 line 26000 (BC uses same taxable income as federal)
    *eligible_div_taxable*    — T1 line 12000 (grossed-up eligible dividends)
    *non_eligible_div_taxable*— T1 line 12010 (grossed-up non-eligible dividends)
    """
    r = BC428Result()

    # Part 1 — BC tax on taxable income
    r.bc_tax_on_income = apply_brackets(taxable_income, BC_BRACKETS)

    # Part 2 — Computed credit amounts
    r.line_58080 = bc_age_amount(taxable_income, inp.age_65_or_over)
    r.line_58300 = inp.line_58300  # volunteer firefighter/SAR — user-entered
    r.bc_pension_amt = round(min(inp.bc_eligible_pension, BC_PENSION_MAX), 2)

    r.line_59090 = round(sum([
        inp.line_58040, r.line_58080, inp.line_58120, inp.line_58160,
        inp.line_58200, inp.line_58240, inp.line_58280, r.line_58300,
        inp.line_58360, inp.line_58400, inp.line_58440, inp.line_58480,
        inp.line_58560, inp.line_58640, inp.line_58689, inp.line_58729,
        inp.line_58800, r.bc_pension_amt,
    ]), 2)

    r.bc_credits = round(r.line_59090 * BC_CREDIT_RATE, 2)

    # BC dividend tax credit
    bc_eligible_dtc     = eligible_div_taxable     * BC_ELIGIBLE_DTC_RATE
    bc_non_eligible_dtc = non_eligible_div_taxable * BC_NON_ELIGIBLE_DTC_RATE
    r.bc_dtc = round(bc_eligible_dtc + bc_non_eligible_dtc, 2)

    # Net BC tax (line 42800)
    r.line_42800 = round(max(0.0,
        r.bc_tax_on_income
        - r.bc_credits
        - r.bc_dtc
        - inp.line_61520
        - inp.line_61600
    ), 2)

    return r


# ── Schedule 5 Data Model ─────────────────────────────────────────────────────

@dataclass
class Schedule5Input:
    """User-supplied fields on the 2025 Schedule 5 (5000-S5)."""
    spouse_net_income: float = 0.0
    dep_net_income: float = 0.0
    spouse_infirm: bool = False
    dep_infirm: bool = False
    num_children_under18: int = 0
    has_spouse: bool = False
    has_eligible_dep: bool = False


def calculate_schedule5(inp: Schedule5Input) -> dict:
    """
    Schedule 5 -- spouse/dependant amounts.
    2025: BPA = 16129, caregiver = 8375
    """
    BPA = FEDERAL_BASIC_PERSONAL
    CAREGIVER = 8_375.0
    CHILD_CAREGIVER = 2_273.0

    line30300 = round(max(0.0, BPA - inp.spouse_net_income), 2) if inp.has_spouse else 0.0
    line30400 = round(max(0.0, BPA - inp.dep_net_income), 2) if inp.has_eligible_dep else 0.0

    if inp.has_spouse and inp.spouse_infirm:
        line30425 = round(min(BPA + CAREGIVER, max(0.0, BPA - inp.spouse_net_income + CAREGIVER)), 2)
    else:
        line30425 = 0.0

    line30450 = CAREGIVER if inp.dep_infirm and inp.has_eligible_dep else 0.0
    line30500 = round(CHILD_CAREGIVER * inp.num_children_under18, 2)

    return {
        "line30300": line30300,
        "line30400": line30400,
        "line30425": line30425,
        "line30450": line30450,
        "line30500": line30500,
    }


# ── Schedule 7 Data Model ─────────────────────────────────────────────────────

@dataclass
class Schedule7Input:
    """User-supplied fields on the 2025 Schedule 7 (5000-S7)."""
    rrsp_unused_prior: float = 0.0
    rrsp_contrib_this_year: float = 0.0
    rrsp_contrib_jan60: float = 0.0
    prpp_contrib: float = 0.0
    rrsp_deduction: float = 0.0
    fhsa_unused_prior: float = 0.0
    fhsa_contrib_this_year: float = 0.0
    fhsa_deduction: float = 0.0
    llp_balance: float = 0.0
    llp_repayment: float = 0.0
    hbp_balance: float = 0.0
    hbp_repayment: float = 0.0


def calculate_schedule7(inp: Schedule7Input) -> dict:
    """Schedule 7 -- RRSP/FHSA/PRPP unused contributions."""
    rrsp_total = round(inp.rrsp_unused_prior + inp.rrsp_contrib_this_year + inp.rrsp_contrib_jan60, 2)
    rrsp_after_deduction = round(max(0.0, rrsp_total - inp.rrsp_deduction), 2)
    fhsa_total = round(inp.fhsa_unused_prior + inp.fhsa_contrib_this_year, 2)
    fhsa_after_deduction = round(max(0.0, fhsa_total - inp.fhsa_deduction), 2)
    llp_min_repayment = round(inp.llp_balance / 10, 2) if inp.llp_balance > 0 else 0.0
    hbp_min_repayment = round(inp.hbp_balance / 15, 2) if inp.hbp_balance > 0 else 0.0
    return {
        "rrsp_total": rrsp_total,
        "rrsp_after_deduction": rrsp_after_deduction,
        "fhsa_total": fhsa_total,
        "fhsa_after_deduction": fhsa_after_deduction,
        "llp_min_repayment": llp_min_repayment,
        "hbp_min_repayment": hbp_min_repayment,
        "line20800": inp.rrsp_deduction,
        "line20805": inp.fhsa_deduction,
        "line24500": inp.llp_repayment,
        "line24600": inp.hbp_repayment,
    }


# ── Schedule 8 Data Model ─────────────────────────────────────────────────────

@dataclass
class Schedule8Input:
    """User-supplied fields on the 2025 Schedule 8 (5000-S8)."""
    net_self_emp_income: float = 0.0
    cpp_thru_employment: float = 0.0
    cpp2_thru_employment: float = 0.0
    ei_self_emp: float = 0.0


def calculate_schedule8(inp: Schedule8Input) -> dict:
    """Schedule 8 -- CPP/QPP contributions on self-employment."""
    _CPP_RATE = 0.0595
    _CPP_MAX = 73_200.0
    _CPP_EXEMPT = 3_500.0
    _CPP_MAX_CONTRIB = round((_CPP_MAX - _CPP_EXEMPT) * _CPP_RATE, 2)  # 4166.45
    _CPP2_RATE = 0.04
    _CPP2_MAX = 81_900.0

    base = round(max(0.0, min(inp.net_self_emp_income, _CPP_MAX) - _CPP_EXEMPT), 2)
    cpp1_on_se = round(base * _CPP_RATE, 2)
    cpp1_on_se = round(min(cpp1_on_se, max(0.0, _CPP_MAX_CONTRIB - inp.cpp_thru_employment)), 2)
    line22200 = round(cpp1_on_se * 0.5, 2)
    line31000 = line22200

    cpp2_base = round(max(0.0, min(inp.net_self_emp_income, _CPP2_MAX) - _CPP_MAX), 2)
    cpp2_on_se = round(cpp2_base * _CPP2_RATE, 2)
    line22215 = round(cpp2_on_se * 0.5, 2)

    return {
        "cpp1_on_se": cpp1_on_se,
        "cpp2_on_se": cpp2_on_se,
        "line22200": line22200,
        "line22215": line22215,
        "line31000": line31000,
        "line31205": round(cpp2_on_se * 0.5, 2),
    }


# ── T777 Data Model ───────────────────────────────────────────────────────────

@dataclass
class T777Input:
    """User-supplied fields on the 2025 T777."""
    total_km: float = 0.0
    work_km: float = 0.0
    fuel: float = 0.0
    maintenance: float = 0.0
    insurance: float = 0.0
    license: float = 0.0
    lease: float = 0.0
    depreciation: float = 0.0
    interest: float = 0.0
    home_office_expenses: float = 0.0
    home_office_work_pct: float = 0.0
    supplies: float = 0.0
    legal_fees: float = 0.0
    other_expenses: float = 0.0


def calculate_t777(inp: T777Input) -> dict:
    """T777 -- Statement of employment expenses."""
    work_pct = round(inp.work_km / inp.total_km, 6) if inp.total_km > 0 else 0.0
    vehicle_total = round(inp.fuel + inp.maintenance + inp.insurance + inp.license + inp.lease + inp.depreciation + inp.interest, 2)
    vehicle_work = round(vehicle_total * work_pct, 2)
    home_office_work = round(inp.home_office_expenses * inp.home_office_work_pct / 100, 2)
    line22900 = round(vehicle_work + home_office_work + inp.supplies + inp.legal_fees + inp.other_expenses, 2)
    return {
        "work_pct": round(work_pct * 100, 2),
        "vehicle_total": vehicle_total,
        "vehicle_work": vehicle_work,
        "home_office_work": home_office_work,
        "line22900": line22900,
    }


# ── T2209 Data Model ──────────────────────────────────────────────────────────

@dataclass
class T2209Input:
    """User-supplied fields on the 2025 T2209."""
    foreign_income_non_business: float = 0.0
    foreign_tax_non_business: float = 0.0
    net_income: float = 0.0
    federal_tax_before_credits: float = 0.0
    foreign_income_business: float = 0.0
    foreign_tax_business: float = 0.0


def calculate_t2209(inp: T2209Input) -> dict:
    """T2209 -- Federal foreign tax credits."""
    if inp.net_income > 0 and inp.federal_tax_before_credits > 0:
        proportion = round(inp.foreign_income_non_business / inp.net_income, 6)
        limit_non_biz = round(proportion * inp.federal_tax_before_credits, 2)
    else:
        limit_non_biz = 0.0
    credit_non_biz = round(min(inp.foreign_tax_non_business, limit_non_biz), 2)
    credit_biz = round(min(inp.foreign_tax_business, inp.foreign_income_business * 0.15), 2)
    line40500 = round(credit_non_biz + credit_biz, 2)
    return {
        "limit_non_biz": limit_non_biz,
        "credit_non_biz": credit_non_biz,
        "credit_biz": credit_biz,
        "line40500": line40500,
    }


# ── Worksheet Fed Data Model ──────────────────────────────────────────────────

@dataclass
class WorksheetFedInput:
    """User-supplied fields on the 2025 Federal Worksheet (5000-D1)."""
    net_income: float = 0.0
    age_65_or_over: bool = False
    cpp_thru_employment: float = 0.0
    cpp2_thru_employment: float = 0.0
    ei_premiums: float = 0.0
    ei_premiums_se: float = 0.0
    employment_income: float = 0.0
    eligible_pension: float = 0.0
    disability_amount: float = 0.0
    student_loan_interest: float = 0.0
    tuition_amount: float = 0.0
    medical_expenses: float = 0.0
    income_over_165430: float = 0.0


def calculate_worksheet_fed(inp: WorksheetFedInput) -> dict:
    """Federal Worksheet (5000-D1) -- federal non-refundable tax credits worksheet."""
    BPA = FEDERAL_BASIC_PERSONAL
    age_amt = federal_age_amount(inp.net_income, inp.age_65_or_over)
    employment_amt = round(min(inp.employment_income, FEDERAL_EMPLOYMENT_MAX), 2)
    pension_amt = round(min(inp.eligible_pension, FEDERAL_PENSION_MAX), 2)

    medical_threshold = round(min(inp.net_income * 0.03, MEDICAL_THRESHOLD_MAX), 2)
    medical_credit_base = round(max(0.0, inp.medical_expenses - medical_threshold), 2)

    total_credits = round(sum([
        BPA,
        age_amt,
        inp.cpp_thru_employment,
        inp.cpp2_thru_employment,
        inp.ei_premiums,
        inp.ei_premiums_se,
        employment_amt,
        pension_amt,
        inp.disability_amount,
        inp.student_loan_interest,
        inp.tuition_amount,
        medical_credit_base,
    ]), 2)

    return {
        "bpa": BPA,
        "age_amt": age_amt,
        "employment_amt": employment_amt,
        "pension_amt": pension_amt,
        "medical_threshold": medical_threshold,
        "medical_credit_base": medical_credit_base,
        "total_credits": total_credits,
        "credit_value": round(total_credits * FEDERAL_CREDIT_RATE, 2),
    }
