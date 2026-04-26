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

# 2025 BC amounts  (source: BC government official credits page)
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
