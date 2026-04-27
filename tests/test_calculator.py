"""
Unit tests for the CRA Tax Helper calculator module (2025 tax year).

All expected values are derived from the publicly available 2025 federal and BC
tax rates and brackets.  Where possible, hand-computed values are provided in
comments so the test intent is clear without running the code.
"""

import pytest
from app.calculator import (
    BC428Input,
    BC_BRACKETS,
    BC_CREDIT_RATE,
    FEDERAL_BRACKETS,
    FEDERAL_CREDIT_RATE,
    T1Input,
    apply_brackets,
    bc_age_amount,
    calculate_bc428,
    calculate_t1,
    federal_age_amount,
)


# ── apply_brackets ─────────────────────────────────────────────────────────────

class TestApplyBrackets:
    def test_zero_income(self):
        assert apply_brackets(0, FEDERAL_BRACKETS) == 0.0

    def test_negative_income_clamped_to_zero(self):
        assert apply_brackets(-5000, FEDERAL_BRACKETS) == 0.0

    def test_first_bracket_only(self):
        # $40,000 × 15% = $6,000.00
        assert apply_brackets(40_000, FEDERAL_BRACKETS) == pytest.approx(6_000.00, abs=0.01)

    def test_crosses_first_bracket(self):
        # $57,375 × 15% = $8,606.25
        # + ($60,000 - $57,375) × 20.5% = $2,625 × 20.5% = $538.125
        # total = $9,144.375 ≈ $9,144.38
        result = apply_brackets(60_000, FEDERAL_BRACKETS)
        assert result == pytest.approx(9_144.38, abs=0.02)

    def test_exactly_at_bracket_boundary(self):
        expected = 57_375 * 0.15
        assert apply_brackets(57_375, FEDERAL_BRACKETS) == pytest.approx(expected, abs=0.01)

    def test_all_federal_brackets(self):
        # $250,000 income — crosses four brackets
        # Bracket 1: $57,375 × 15%              =  $8,606.25
        # Bracket 2: ($114,750-$57,375) × 20.5% = $11,761.875
        # Bracket 3: ($177,882-$114,750) × 26%  = $16,414.32
        # Bracket 4: ($250,000-$177,882) × 29%  = $20,914.22
        # Total                                  = $57,696.67
        result = apply_brackets(250_000, FEDERAL_BRACKETS)
        assert result == pytest.approx(57_696.67, abs=0.10)

    def test_bc_first_bracket(self):
        # $30,000 × 5.06% = $1,518.00
        result = apply_brackets(30_000, BC_BRACKETS)
        assert result == pytest.approx(1_518.00, abs=0.01)

    def test_bc_two_brackets(self):
        # $60,000:  $49,279 × 5.06%  = $2,493.52
        #         + $10,721 × 7.70%  = $825.52  → total ≈ $3,319.04
        result = apply_brackets(60_000, BC_BRACKETS)
        assert result == pytest.approx(3_319.04, abs=0.02)

    def test_bc_all_brackets(self):
        result_300k = apply_brackets(300_000, BC_BRACKETS)
        # Should be > result_200k
        result_200k = apply_brackets(200_000, BC_BRACKETS)
        assert result_300k > result_200k


# ── Age amount helpers ─────────────────────────────────────────────────────────

class TestFederalAgeAmount:
    def test_under_65(self):
        assert federal_age_amount(50_000, False) == 0.0

    def test_over_65_low_income(self):
        assert federal_age_amount(30_000, True) == pytest.approx(9_028.00, abs=0.01)

    def test_over_65_at_threshold(self):
        assert federal_age_amount(45_522, True) == pytest.approx(9_028.00, abs=0.01)

    def test_over_65_partial_reduction(self):
        # income = $60,000 → reduction = ($60,000 - $45,522) × 15% = $2,171.70
        # age amount = $9,028 - $2,171.70 = $6,856.30
        result = federal_age_amount(60_000, True)
        assert result == pytest.approx(6_856.30, abs=0.01)

    def test_over_65_fully_phased_out(self):
        assert federal_age_amount(110_000, True) == 0.0

    def test_over_65_at_ceiling(self):
        assert federal_age_amount(105_709, True) == 0.0


class TestBCageAmount:
    def test_under_65(self):
        assert bc_age_amount(40_000, False) == 0.0

    def test_over_65_low_income(self):
        assert bc_age_amount(20_000, True) == pytest.approx(5_799.00, abs=0.01)

    def test_over_65_fully_phased_out(self):
        assert bc_age_amount(85_000, True) == 0.0


# ── T1 calculate_t1 ────────────────────────────────────────────────────────────

class TestCalculateT1:
    def _simple(self, **kwargs):
        inp = T1Input(**kwargs)
        return calculate_t1(inp)

    def test_zero_input(self):
        r = self._simple()
        assert r.line_15000 == 0.0
        assert r.line_23600 == 0.0
        assert r.line_26000 == 0.0
        assert r.line_40424 == 0.0

    def test_total_income_employment_only(self):
        r = self._simple(line_10100=80_000)
        assert r.line_15000 == pytest.approx(80_000.00, abs=0.01)

    def test_total_income_multiple_sources(self):
        r = self._simple(line_10100=50_000, line_12100=5_000, line_12600=10_000)
        assert r.line_15000 == pytest.approx(65_000.00, abs=0.01)

    def test_net_income_with_deductions(self):
        # $80,000 income, $5,000 RRSP deduction → net = $75,000
        r = self._simple(line_10100=80_000, line_20800=5_000)
        assert r.line_23300 == pytest.approx(5_000.00, abs=0.01)
        assert r.line_23400 == pytest.approx(75_000.00, abs=0.01)
        assert r.line_23600 == pytest.approx(75_000.00, abs=0.01)

    def test_net_income_cannot_go_negative(self):
        # Deductions exceed income
        r = self._simple(line_10100=10_000, line_20800=50_000)
        assert r.line_23400 == 0.0
        assert r.line_23600 == 0.0

    def test_taxable_income_with_capital_losses(self):
        r = self._simple(line_10100=80_000, line_25300=5_000)
        assert r.line_26000 == pytest.approx(75_000.00, abs=0.01)

    def test_canada_employment_amount_capped(self):
        # Employment income > $1,471 → capped at $1,471
        r = self._simple(line_10100=100_000)
        assert r.line_31260 == pytest.approx(1_471.00, abs=0.01)

    def test_canada_employment_amount_partial(self):
        # Employment income = $800 → employment amount = $800
        r = self._simple(line_10100=800)
        assert r.line_31260 == pytest.approx(800.00, abs=0.01)

    def test_pension_income_amount_capped(self):
        r = self._simple(line_31401=5_000)
        assert r.line_31400 == pytest.approx(2_000.00, abs=0.01)

    def test_pension_income_amount_partial(self):
        r = self._simple(line_31401=1_200)
        assert r.line_31400 == pytest.approx(1_200.00, abs=0.01)

    def test_age_amount_auto_computed(self):
        # Net income $30,000 is below the $45,522 threshold → full $9,028 age amount
        r = calculate_t1(T1Input(line_10100=30_000, age_65_or_over=True))
        assert r.line_30100 == pytest.approx(9_028.00, abs=0.01)

    def test_age_amount_partially_reduced(self):
        # Net income $50,000: reduction = ($50,000 - $45,522) × 15% = $671.70
        # age amount = $9,028 - $671.70 = $8,356.30
        r = calculate_t1(T1Input(line_10100=50_000, age_65_or_over=True))
        assert r.line_30100 == pytest.approx(8_356.30, abs=0.01)

    def test_federal_credits_total(self):
        # Only basic personal amount filled in
        inp = T1Input(line_10100=0)
        inp.line_30000 = 16_129
        r = calculate_t1(inp)
        assert r.line_35000 == pytest.approx(16_129.00, abs=0.01)
        assert r.line_35100 == pytest.approx(16_129 * 0.15, abs=0.01)

    def test_federal_tax_single_bracket(self):
        # Taxable income $30,000 → all in 14.5% bracket
        # Federal tax = $30,000 × 14.5% = $4,350
        # Credits: basic personal $16,129 × 14.5% + employment $1,471 × 14.5%
        r = calculate_t1(T1Input(
            line_10100=30_000,
            line_30000=16_129,
        ))
        fed_tax = apply_brackets(r.line_26000, FEDERAL_BRACKETS)
        assert r.line_38000 == pytest.approx(fed_tax, abs=0.01)
        assert r.line_40424 >= 0

    def test_net_federal_tax_is_non_negative(self):
        # Very low income — credits exceed tax, result clamped to 0
        r = calculate_t1(T1Input(line_10100=10_000, line_30000=16_129))
        assert r.line_40424 == 0.0

    def test_dividend_tax_credit_eligible(self):
        # Eligible dividends taxable amount $10,000 (grossed-up)
        # DTC = $10,000 × (6/11) × (0.38/1.38) ≈ $1,501.98
        from app.calculator import FEDERAL_ELIGIBLE_DTC_RATE
        r = calculate_t1(T1Input(line_12000=10_000, line_30000=16_129))
        expected_dtc = 10_000 * FEDERAL_ELIGIBLE_DTC_RATE
        assert r.line_40425 == pytest.approx(expected_dtc, abs=0.01)

    def test_dividend_tax_credit_non_eligible(self):
        from app.calculator import FEDERAL_NON_ELIGIBLE_DTC_RATE
        r = calculate_t1(T1Input(line_12010=5_000, line_30000=16_129))
        expected_dtc = 5_000 * FEDERAL_NON_ELIGIBLE_DTC_RATE
        assert r.line_40425 == pytest.approx(expected_dtc, abs=0.01)

    def test_refund_when_tax_deducted_exceeds_payable(self):
        r = calculate_t1(T1Input(
            line_10100=30_000,
            line_30000=16_129,
            line_43700=10_000,
        ))
        assert r.line_48400 > 0
        assert r.line_48500 == 0.0

    def test_balance_owing_when_underpaid(self):
        # No tax deducted, large income
        r = calculate_t1(T1Input(
            line_10100=200_000,
            line_30000=16_129,
            line_43700=0,
        ))
        assert r.line_48500 > 0
        assert r.line_48400 == 0.0

    def test_refund_and_balance_not_both_positive(self):
        r = calculate_t1(T1Input(line_10100=80_000, line_30000=16_129, line_43700=20_000))
        # Exactly one of them should be > 0 (or both 0 if exactly equal)
        assert not (r.line_48400 > 0 and r.line_48500 > 0)

    def test_bc_provincial_tax_fed_into_payable(self):
        r = calculate_t1(T1Input(line_10100=80_000, line_30000=16_129), bc_net_tax=5_000)
        assert r.line_42000 == pytest.approx(5_000.00, abs=0.01)
        assert r.line_48200 == pytest.approx(r.line_40424 + 5_000, abs=0.01)

    def test_workers_compensation_in_total_income(self):
        r = self._simple(line_14400=20_000)
        assert r.line_15000 == pytest.approx(20_000.00, abs=0.01)

    def test_known_scenario_medium_income(self):
        """
        Scenario: $90,000 employment income, $10,000 RRSP deduction,
        CPP $3,867.50, EI $1,049.12, basic personal + employment credits.
        Validates the full pipeline produces a reasonable (positive) net tax.
        """
        r = calculate_t1(T1Input(
            line_10100=90_000,
            line_20800=10_000,
            line_30000=16_129,
            line_31000=3_867.50,
            line_31200=1_049.12,
            line_43700=18_000,
        ))
        assert r.line_15000 == pytest.approx(90_000, abs=0.01)
        assert r.line_23600 == pytest.approx(80_000, abs=0.01)
        assert r.line_26000 == pytest.approx(80_000, abs=0.01)
        assert r.line_38000 > 0
        assert r.line_40424 >= 0
        # With $18,000 withheld on $90k income, expect a refund
        assert r.line_48400 > 0 or r.line_48500 > 0  # one or the other


# ── BC428 calculate_bc428 ──────────────────────────────────────────────────────

class TestCalculateBC428:
    def test_zero_input(self):
        r = calculate_bc428(BC428Input(), taxable_income=0)
        assert r.bc_tax_on_income == 0.0
        assert r.line_42800 == 0.0

    def test_bc_tax_on_income(self):
        # $60,000 → 2 brackets: $49,279 × 5.06% + $10,721 × 7.70% ≈ $3,319.04
        r = calculate_bc428(BC428Input(), taxable_income=60_000)
        assert r.bc_tax_on_income == pytest.approx(3_319.04, abs=0.02)

    def test_bc_basic_personal_credit(self):
        # Only basic personal amount → credits = $12,932 × 5.06%
        r = calculate_bc428(BC428Input(line_58040=12_932), taxable_income=50_000)
        assert r.bc_credits == pytest.approx(12_932 * BC_CREDIT_RATE, abs=0.01)

    def test_age_amount_auto_computed(self):
        r = calculate_bc428(BC428Input(age_65_or_over=True), taxable_income=30_000)
        assert r.line_58080 == pytest.approx(5_799.00, abs=0.01)

    def test_age_amount_zero_if_not_65(self):
        r = calculate_bc428(BC428Input(age_65_or_over=False), taxable_income=30_000)
        assert r.line_58080 == 0.0

    def test_bc_pension_amount_capped(self):
        r = calculate_bc428(
            BC428Input(bc_eligible_pension=5_000),
            taxable_income=50_000,
        )
        assert r.bc_pension_amt == pytest.approx(1_000.00, abs=0.01)

    def test_bc_pension_amount_partial(self):
        r = calculate_bc428(
            BC428Input(bc_eligible_pension=600),
            taxable_income=50_000,
        )
        assert r.bc_pension_amt == pytest.approx(600.00, abs=0.01)

    def test_bc_volunteer_amount_passed_through(self):
        # line_58300 is now user-entered; value should pass through unchanged
        r = calculate_bc428(BC428Input(line_58300=3_000), taxable_income=80_000)
        assert r.line_58300 == 3_000.0

    def test_bc_dividend_tax_credit_eligible(self):
        from app.calculator import BC_ELIGIBLE_DTC_RATE
        r = calculate_bc428(
            BC428Input(),
            taxable_income=50_000,
            eligible_div_taxable=10_000,
        )
        expected = 10_000 * BC_ELIGIBLE_DTC_RATE
        assert r.bc_dtc == pytest.approx(expected, abs=0.01)

    def test_bc_net_tax_is_non_negative(self):
        # Low income — credits should exceed tax
        r = calculate_bc428(BC428Input(line_58040=12_932), taxable_income=10_000)
        assert r.line_42800 == 0.0

    def test_bc_net_tax_positive_high_income(self):
        r = calculate_bc428(BC428Input(line_58040=12_932), taxable_income=150_000)
        assert r.line_42800 > 0

    def test_known_scenario_bc428(self):
        """
        $80,000 taxable income, basic personal amount only (2025).
        BC tax: $49,279×5.06% + $30,721×7.70% = $2,493.52 + $2,365.52 = $4,859.04
        Credits: $12,932 × 5.06% = $654.36 (basic personal only)
        Net BC tax ≈ $4,859.04 - $654.36 = $4,204.68
        """
        inp = BC428Input(line_58040=12_932)
        r = calculate_bc428(inp, taxable_income=80_000)
        bc_raw = apply_brackets(80_000, BC_BRACKETS)
        assert r.bc_tax_on_income == pytest.approx(bc_raw, abs=0.01)
        assert r.line_42800 == pytest.approx(
            max(0, bc_raw - r.bc_credits - r.bc_dtc), abs=0.01
        )


# ── Integration: T1 + BC428 together ──────────────────────────────────────────

class TestIntegration:
    def test_full_pipeline_bc_resident(self):
        """
        BC resident, $100,000 employment income.
        1) Compute T1 to get taxable income.
        2) Feed taxable income into BC428.
        3) Feed BC net tax back into T1.
        4) Verify total payable = federal + provincial.
        """
        t1_inp = T1Input(
            line_10100=100_000,
            line_20800=15_000,   # RRSP deduction
            line_30000=16_129,
            line_31000=3_867.50,
            line_31200=1_049.12,
        )
        t1_first = calculate_t1(t1_inp)

        bc_inp = BC428Input(
            line_58040=12_932,
            line_58240=3_867.50,
            line_58280=1_049.12,
        )
        bc_result = calculate_bc428(bc_inp, taxable_income=t1_first.line_26000)

        t1_final = calculate_t1(t1_inp, bc_net_tax=bc_result.line_42800)

        assert t1_final.line_42000 == pytest.approx(bc_result.line_42800, abs=0.01)
        expected_payable = t1_final.line_40424 + bc_result.line_42800
        assert t1_final.line_48200 == pytest.approx(expected_payable, abs=0.01)

    def test_refund_decreases_with_higher_income(self):
        """Adding more income should not increase the refund (with same tax withheld)."""
        withheld = 20_000

        t1_low = calculate_t1(T1Input(
            line_10100=60_000, line_30000=16_129, line_43700=withheld
        ))
        t1_high = calculate_t1(T1Input(
            line_10100=120_000, line_30000=16_129, line_43700=withheld
        ))

        # Higher income → higher tax → smaller refund (or larger balance owing)
        assert t1_high.line_48400 <= t1_low.line_48400

    def test_rrsp_deduction_reduces_tax(self):
        """An RRSP deduction should reduce or maintain the net federal tax."""
        base = calculate_t1(T1Input(line_10100=80_000, line_30000=16_129))
        with_rrsp = calculate_t1(T1Input(
            line_10100=80_000, line_20800=15_000, line_30000=16_129
        ))
        assert with_rrsp.line_40424 <= base.line_40424


# ── Schedule 9 calculate_schedule9 ────────────────────────────────────────────

from app.calculator import Schedule9Input, calculate_schedule9


class TestCalculateSchedule9:
    def _calc(self, **kwargs):
        return calculate_schedule9(Schedule9Input(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        assert r["line5"]  == 0.0
        assert r["line23"] == 0.0

    def test_line5_sum(self):
        r = self._calc(line_1=100, line_2=200, line_3=50, line_4=150)
        assert r["line5"] == pytest.approx(500.0, abs=0.01)

    def test_line6A_is_75pct_of_net_income(self):
        r = self._calc(net_income_23600=80_000)
        assert r["line6A"] == pytest.approx(60_000.0, abs=0.01)

    def test_line7D_is_25pct_of_b_plus_c(self):
        r = self._calc(amt_B=10_000, amt_C=6_000)
        assert r["line7D"] == pytest.approx(4_000.0, abs=0.01)

    def test_line13_capped_at_200(self):
        # With a small donation (e.g. $100), line12 < 200 → line13 = line12
        r = self._calc(line_1=100, net_income_23600=50_000)
        assert r["line13"] == pytest.approx(100.0, abs=0.01)
        # Larger: always capped at 200
        r2 = self._calc(line_1=1000, net_income_23600=50_000)
        assert r2["line13"] == pytest.approx(200.0, abs=0.01)

    def test_line19_excess_over_threshold(self):
        # Taxable income = 300,000 → 300,000 - 253,414 = 46,586
        r = self._calc(taxable_income_26000=300_000)
        assert r["line19"] == pytest.approx(46_586.0, abs=0.01)

    def test_line19_zero_when_below_threshold(self):
        r = self._calc(taxable_income_26000=100_000)
        assert r["line19"] == 0.0

    def test_line23_composite_calculation(self):
        """$1,000 charity donation, $80,000 net income, $90,000 taxable income."""
        r = self._calc(
            line_1=1_000,
            net_income_23600=80_000,
            taxable_income_26000=90_000,
        )
        # line5=1000, line6A=60000, line8=60000, line9=min(60000,60000)=60000
        # line10=min(1000,60000)=1000, line12=1000, line13=200, line14=800
        # line16=max(0,800-0)=800, line19=0 (90000<253414)
        # F=min(800,0)=0 → line20=0×0.33=0
        # G=800-0=800 → line21=800×0.29=232
        # line22=200×0.145=29, line23=0+232+29=261
        assert r["line23"] == pytest.approx(261.0, abs=0.01)

    def test_line23_high_income_uses_33pct_rate(self):
        """With taxable income above threshold, some of line14 is taxed at 33%."""
        r = self._calc(
            line_1=50_000,
            net_income_23600=400_000,
            taxable_income_26000=400_000,
        )
        # line19 = 400000 - 253414 = 146586
        # line6A = 300000, line10 = min(50000, 300000) = 50000
        # line12 = 50000, line13 = 200, line14 = 49800
        # line16 = 49800 (no line15), F = min(49800, 146586) = 49800
        # line20 = 49800 × 0.33 = 16434
        # G = 49800 - 49800 = 0 → line21 = 0
        # line22 = 200 × 0.145 = 29
        assert r["line20"] == pytest.approx(49_800 * 0.33, abs=0.01)
        assert r["line21"] == pytest.approx(0.0, abs=0.01)


# ── BC479 calculate_bc479 ──────────────────────────────────────────────────────

from app.calculator import BC479Input, calculate_bc479


class TestCalculateBC479:
    def _calc(self, **kwargs):
        return calculate_bc479(BC479Input(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        assert r["line13"] == pytest.approx(75.0, abs=0.01)  # basic $75, no reduction
        assert r["line45"] == pytest.approx(75.0, abs=0.01)

    def test_sales_tax_credit_no_spouse(self):
        # Single, $15,000 threshold; line6=0 → line8=0 → line12=0 → line13=75
        r = self._calc(has_spouse=False)
        assert r["line9"]  == pytest.approx(75.0, abs=0.01)
        assert r["line10"] == pytest.approx(0.0,  abs=0.01)
        assert r["line11"] == pytest.approx(75.0, abs=0.01)

    def test_sales_tax_credit_with_spouse(self):
        r = self._calc(has_spouse=True)
        assert r["line10"] == pytest.approx(75.0, abs=0.01)
        assert r["line11"] == pytest.approx(150.0, abs=0.01)

    def test_line13_reduces_when_income_high(self):
        # line6 = 50,000 (single, threshold 15,000) → line8=35,000 → line12=700
        # line13 = max(0, 75 - 700) = 0
        r = self._calc(line1_col1=50_000, has_spouse=False)
        assert r["line13"] == pytest.approx(0.0, abs=0.01)

    def test_home_reno_10pct(self):
        r = self._calc(line14_input=5_000)
        assert r["line14_result"] == pytest.approx(500.0, abs=0.01)

    def test_home_reno_capped_at_10000(self):
        r = self._calc(line14_input=20_000)
        assert r["line14_result"] == pytest.approx(1_000.0, abs=0.01)

    def test_renter_credit_no_months(self):
        r = self._calc(rental_months=0, line39=40_000)
        assert r["line44"] == pytest.approx(0.0, abs=0.01)

    def test_renter_credit_low_income(self):
        # income 40,000 < 64,764 → line41=0 → line43=0 → line44=400
        r = self._calc(rental_months=12, line39=40_000)
        assert r["line44"] == pytest.approx(400.0, abs=0.01)

    def test_renter_credit_partial_reduction(self):
        # income 74,764 → line41=10,000 → line43=200 → line44=200
        r = self._calc(rental_months=12, line39=74_764)
        assert r["line44"] == pytest.approx(200.0, abs=0.01)

    def test_line45_sums_credits(self):
        r = self._calc(rental_months=12, line39=40_000)
        assert r["line45"] == pytest.approx(r["line36"] + r["line44"], abs=0.01)


# ── Schedule 3 calculate_schedule3 ────────────────────────────────────────────

from app.calculator import Schedule3Input, calculate_schedule3


class TestCalculateSchedule3:
    def test_zero_input(self):
        r = calculate_schedule3(Schedule3Input())
        assert r["line11"] == 0.0
        assert r["line26"] == 0.0

    def test_single_row_gain(self):
        inp = Schedule3Input(
            proceeds=[10_000] + [0]*9,
            cost=[6_000] + [0]*9,
            outlays=[500] + [0]*9,
        )
        r = calculate_schedule3(inp)
        assert r["gain_loss"][0] == pytest.approx(3_500.0, abs=0.01)
        assert r["line11"] == pytest.approx(3_500.0, abs=0.01)

    def test_single_row_loss(self):
        inp = Schedule3Input(
            proceeds=[5_000] + [0]*9,
            cost=[8_000] + [0]*9,
            outlays=[200] + [0]*9,
        )
        r = calculate_schedule3(inp)
        assert r["gain_loss"][0] == pytest.approx(-3_200.0, abs=0.01)
        assert r["line11"] == pytest.approx(-3_200.0, abs=0.01)

    def test_multiple_rows_summed(self):
        inp = Schedule3Input(
            proceeds=[10_000, 20_000] + [0]*8,
            cost=[6_000, 12_000] + [0]*8,
            outlays=[0, 0] + [0]*8,
        )
        r = calculate_schedule3(inp)
        assert r["line11"] == pytest.approx(12_000.0, abs=0.01)

    def test_line21_net_with_part4_entries(self):
        inp = Schedule3Input(
            proceeds=[10_000] + [0]*9,
            cost=[0]*10,
            outlays=[0]*10,
            line13=2_000,
            line14=500,
        )
        r = calculate_schedule3(inp)
        # line12=10000, line21=10000+2000-500=11500
        assert r["line21"] == pytest.approx(11_500.0, abs=0.01)

    def test_line22_floored_at_zero(self):
        # Net loss: line21 < 0 → line22 = 0
        inp = Schedule3Input(
            proceeds=[0]*10,
            cost=[10_000] + [0]*9,
            outlays=[0]*10,
        )
        r = calculate_schedule3(inp)
        assert r["line22"] == 0.0

    def test_line26_taxable_at_50pct(self):
        inp = Schedule3Input(
            proceeds=[20_000] + [0]*9,
            cost=[0]*10,
            outlays=[0]*10,
        )
        r = calculate_schedule3(inp)
        assert r["line26"] == pytest.approx(10_000.0, abs=0.01)

    def test_deductions_reduce_line25(self):
        inp = Schedule3Input(
            proceeds=[20_000] + [0]*9,
            cost=[0]*10,
            outlays=[0]*10,
            line23_deduction=5_000,
        )
        r = calculate_schedule3(inp)
        assert r["line25"] == pytest.approx(15_000.0, abs=0.01)
        assert r["line26"] == pytest.approx(7_500.0, abs=0.01)

    def test_line25_floored_at_zero(self):
        inp = Schedule3Input(
            proceeds=[20_000] + [0]*9,
            cost=[0]*10,
            outlays=[0]*10,
            line23_deduction=30_000,
        )
        r = calculate_schedule3(inp)
        assert r["line25"] == 0.0
        assert r["line26"] == 0.0


# ── Schedule 5 calculate_schedule5 ────────────────────────────────────────────

from app.calculator import Schedule5Input, calculate_schedule5


class TestCalculateSchedule5:
    def _calc(self, **kwargs):
        return calculate_schedule5(Schedule5Input(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        assert r["line30300"] == 0.0
        assert r["line30400"] == 0.0
        assert r["line30425"] == 0.0
        assert r["line30450"] == 0.0
        assert r["line30500"] == 0.0

    def test_spouse_amount_no_income(self):
        # Full basic personal amount when spouse has zero net income
        r = self._calc(has_spouse=True, spouse_net_income=0)
        assert r["line30300"] == pytest.approx(16_129.0, abs=0.01)

    def test_spouse_amount_partial(self):
        # BPA - spouse income = 16,129 - 5,000 = 11,129
        r = self._calc(has_spouse=True, spouse_net_income=5_000)
        assert r["line30300"] == pytest.approx(11_129.0, abs=0.01)

    def test_spouse_amount_zero_when_income_exceeds_bpa(self):
        # Spouse income >= BPA → line30300 = 0
        r = self._calc(has_spouse=True, spouse_net_income=20_000)
        assert r["line30300"] == 0.0

    def test_no_spouse_gives_zero_line30300(self):
        r = self._calc(has_spouse=False, spouse_net_income=0)
        assert r["line30300"] == 0.0

    def test_eligible_dependant_amount(self):
        # Eligible dependant with zero income → full BPA
        r = self._calc(has_eligible_dep=True, dep_net_income=0)
        assert r["line30400"] == pytest.approx(16_129.0, abs=0.01)

    def test_eligible_dependant_partial_income(self):
        r = self._calc(has_eligible_dep=True, dep_net_income=3_000)
        assert r["line30400"] == pytest.approx(13_129.0, abs=0.01)

    def test_child_caregiver_amount(self):
        # 2 children × $2,273 = $4,546
        r = self._calc(num_children_under18=2)
        assert r["line30500"] == pytest.approx(4_546.0, abs=0.01)

    def test_caregiver_spouse_infirm(self):
        # Spouse infirm + no income: line30425 = BPA + CAREGIVER (capped)
        r = self._calc(has_spouse=True, spouse_net_income=0, spouse_infirm=True)
        assert r["line30425"] > 0

    def test_caregiver_dep_infirm(self):
        r = self._calc(has_eligible_dep=True, dep_net_income=0, dep_infirm=True)
        assert r["line30450"] == pytest.approx(8_375.0, abs=0.01)


# ── Schedule 7 calculate_schedule7 ────────────────────────────────────────────

from app.calculator import Schedule7Input, calculate_schedule7


class TestCalculateSchedule7:
    def _calc(self, **kwargs):
        return calculate_schedule7(Schedule7Input(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        assert r["rrsp_total"] == 0.0
        assert r["rrsp_after_deduction"] == 0.0

    def test_rrsp_total_sums_contributions(self):
        r = self._calc(rrsp_unused_prior=5_000, rrsp_contrib_this_year=10_000, rrsp_contrib_jan60=3_000)
        assert r["rrsp_total"] == pytest.approx(18_000.0, abs=0.01)

    def test_rrsp_after_deduction(self):
        r = self._calc(rrsp_unused_prior=10_000, rrsp_deduction=8_000)
        assert r["rrsp_after_deduction"] == pytest.approx(2_000.0, abs=0.01)

    def test_rrsp_after_deduction_floored_at_zero(self):
        r = self._calc(rrsp_unused_prior=5_000, rrsp_deduction=10_000)
        assert r["rrsp_after_deduction"] == 0.0

    def test_fhsa_total_and_remaining(self):
        r = self._calc(fhsa_unused_prior=3_000, fhsa_contrib_this_year=8_000, fhsa_deduction=5_000)
        assert r["fhsa_total"] == pytest.approx(11_000.0, abs=0.01)
        assert r["fhsa_after_deduction"] == pytest.approx(6_000.0, abs=0.01)

    def test_llp_minimum_repayment_is_one_tenth(self):
        r = self._calc(llp_balance=20_000)
        assert r["llp_min_repayment"] == pytest.approx(2_000.0, abs=0.01)

    def test_hbp_minimum_repayment_is_one_fifteenth(self):
        r = self._calc(hbp_balance=15_000)
        assert r["hbp_min_repayment"] == pytest.approx(1_000.0, abs=0.01)

    def test_line20800_equals_rrsp_deduction(self):
        r = self._calc(rrsp_deduction=12_000)
        assert r["line20800"] == pytest.approx(12_000.0, abs=0.01)

    def test_line20805_equals_fhsa_deduction(self):
        r = self._calc(fhsa_deduction=4_000)
        assert r["line20805"] == pytest.approx(4_000.0, abs=0.01)


# ── Schedule 8 calculate_schedule8 ────────────────────────────────────────────

from app.calculator import Schedule8Input, calculate_schedule8


class TestCalculateSchedule8:
    def _calc(self, **kwargs):
        return calculate_schedule8(Schedule8Input(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        assert r["cpp1_on_se"] == 0.0
        assert r["line22200"] == 0.0
        assert r["line31000"] == 0.0

    def test_cpp1_below_exemption(self):
        # Net SE income below $3,500 exemption → no CPP
        r = self._calc(net_self_emp_income=3_000)
        assert r["cpp1_on_se"] == 0.0

    def test_cpp1_basic_calculation(self):
        # (10,000 - 3,500) × 5.95% = 6,500 × 5.95% = 386.75
        r = self._calc(net_self_emp_income=10_000)
        assert r["cpp1_on_se"] == pytest.approx(386.75, abs=0.02)

    def test_line22200_is_half_of_cpp1(self):
        # Deduction = employee half
        r = self._calc(net_self_emp_income=10_000)
        assert r["line22200"] == pytest.approx(r["cpp1_on_se"] / 2, abs=0.01)

    def test_line31000_equals_line22200(self):
        r = self._calc(net_self_emp_income=10_000)
        assert r["line31000"] == r["line22200"]

    def test_cpp1_capped_at_max_earnings(self):
        # Earnings above $73,200 don't increase CPP1
        r_high = self._calc(net_self_emp_income=100_000)
        r_max  = self._calc(net_self_emp_income=73_200)
        assert r_high["cpp1_on_se"] == r_max["cpp1_on_se"]

    def test_cpp2_applies_above_max_pensionable(self):
        # Earnings above $73,200 up to $81,900 → CPP2 at 4%
        r = self._calc(net_self_emp_income=75_000)
        assert r["cpp2_on_se"] > 0

    def test_cpp2_zero_below_cpp1_ceiling(self):
        r = self._calc(net_self_emp_income=50_000)
        assert r["cpp2_on_se"] == 0.0

    def test_line22215_is_half_of_cpp2(self):
        r = self._calc(net_self_emp_income=80_000)
        assert r["line22215"] == pytest.approx(r["cpp2_on_se"] / 2, abs=0.01)


# ── T777 calculate_t777 ───────────────────────────────────────────────────────

from app.calculator import T777Input, calculate_t777


class TestCalculateT777:
    def _calc(self, **kwargs):
        return calculate_t777(T777Input(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        assert r["line22900"] == 0.0

    def test_vehicle_work_percentage(self):
        # 20,000 total km, 10,000 work km → 50%
        r = self._calc(total_km=20_000, work_km=10_000, fuel=4_000)
        assert r["work_pct"] == pytest.approx(50.0, abs=0.01)
        assert r["vehicle_work"] == pytest.approx(2_000.0, abs=0.01)

    def test_vehicle_total_sums_all_costs(self):
        r = self._calc(total_km=10_000, work_km=10_000,
                       fuel=1_000, maintenance=500, insurance=1_200,
                       license=100, lease=300, depreciation=2_000, interest=400)
        assert r["vehicle_total"] == pytest.approx(5_500.0, abs=0.01)

    def test_full_work_ratio(self):
        # 100% work km → vehicle_work = vehicle_total
        r = self._calc(total_km=10_000, work_km=10_000, fuel=2_000)
        assert r["vehicle_work"] == pytest.approx(2_000.0, abs=0.01)

    def test_home_office_percentage(self):
        # $10,000 home office, 20% work → $2,000
        r = self._calc(home_office_expenses=10_000, home_office_work_pct=20.0)
        assert r["home_office_work"] == pytest.approx(2_000.0, abs=0.01)

    def test_supplies_and_legal_direct(self):
        r = self._calc(supplies=500, legal_fees=1_000)
        assert r["line22900"] == pytest.approx(1_500.0, abs=0.01)

    def test_other_expenses_included(self):
        r = self._calc(other_expenses=750)
        assert r["line22900"] == pytest.approx(750.0, abs=0.01)

    def test_line22900_full_combination(self):
        r = self._calc(
            total_km=10_000, work_km=5_000,
            fuel=2_000, supplies=300, legal_fees=200,
            home_office_expenses=5_000, home_office_work_pct=40.0,
        )
        # vehicle_work = 1,000; home_office = 2,000; supplies+legal = 500
        assert r["line22900"] == pytest.approx(3_500.0, abs=0.01)


# ── T2209 calculate_t2209 ────────────────────────────────────────────────────

from app.calculator import T2209Input, calculate_t2209


class TestCalculateT2209:
    def _calc(self, **kwargs):
        return calculate_t2209(T2209Input(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        assert r["line40500"] == 0.0

    def test_credit_limit_proportional(self):
        # foreign_income=10,000, net_income=100,000, fed_tax=20,000
        # limit = (10,000/100,000) × 20,000 = 2,000
        r = self._calc(
            foreign_income_non_business=10_000,
            net_income=100_000,
            federal_tax_before_credits=20_000,
            foreign_tax_non_business=3_000,
        )
        assert r["limit_non_biz"] == pytest.approx(2_000.0, abs=0.01)

    def test_credit_is_lesser_of_tax_and_limit(self):
        # Foreign tax paid (1,500) < limit (2,000) → credit = 1,500
        r = self._calc(
            foreign_income_non_business=10_000,
            net_income=100_000,
            federal_tax_before_credits=20_000,
            foreign_tax_non_business=1_500,
        )
        assert r["credit_non_biz"] == pytest.approx(1_500.0, abs=0.01)

    def test_credit_capped_at_limit(self):
        # Foreign tax paid (5,000) > limit (2,000) → credit = 2,000
        r = self._calc(
            foreign_income_non_business=10_000,
            net_income=100_000,
            federal_tax_before_credits=20_000,
            foreign_tax_non_business=5_000,
        )
        assert r["credit_non_biz"] == pytest.approx(2_000.0, abs=0.01)

    def test_zero_net_income_gives_zero_credit(self):
        r = self._calc(
            foreign_income_non_business=5_000,
            net_income=0,
            federal_tax_before_credits=10_000,
            foreign_tax_non_business=1_000,
        )
        assert r["credit_non_biz"] == 0.0
        assert r["line40500"] == 0.0

    def test_business_credit_included(self):
        r = self._calc(
            foreign_income_business=10_000,
            foreign_tax_business=1_000,
        )
        assert r["credit_biz"] > 0
        assert r["line40500"] == r["credit_biz"]

    def test_line40500_is_sum_of_biz_and_nonbiz(self):
        r = self._calc(
            foreign_income_non_business=5_000,
            net_income=50_000,
            federal_tax_before_credits=10_000,
            foreign_tax_non_business=500,
            foreign_income_business=2_000,
            foreign_tax_business=200,
        )
        assert r["line40500"] == pytest.approx(r["credit_non_biz"] + r["credit_biz"], abs=0.01)


# ── WorksheetFed calculate_worksheet_fed ────────────────────────────────────

from app.calculator import WorksheetFedInput, calculate_worksheet_fed


class TestCalculateWorksheetFed:
    def _calc(self, **kwargs):
        return calculate_worksheet_fed(WorksheetFedInput(**kwargs))

    def test_zero_input(self):
        r = self._calc()
        # BPA is always 16,129 even with no input
        assert r["bpa"] == pytest.approx(16_129.0, abs=0.01)
        assert r["total_credits"] > 0

    def test_employment_amount_capped(self):
        r = self._calc(employment_income=100_000)
        assert r["employment_amt"] == pytest.approx(1_471.0, abs=0.01)

    def test_employment_amount_partial(self):
        r = self._calc(employment_income=800)
        assert r["employment_amt"] == pytest.approx(800.0, abs=0.01)

    def test_pension_amount_capped(self):
        r = self._calc(eligible_pension=5_000)
        assert r["pension_amt"] == pytest.approx(2_000.0, abs=0.01)

    def test_pension_amount_partial(self):
        r = self._calc(eligible_pension=1_200)
        assert r["pension_amt"] == pytest.approx(1_200.0, abs=0.01)

    def test_age_amount_under_65(self):
        r = self._calc(net_income=40_000, age_65_or_over=False)
        assert r["age_amt"] == 0.0

    def test_age_amount_over_65_low_income(self):
        r = self._calc(net_income=30_000, age_65_or_over=True)
        assert r["age_amt"] == pytest.approx(9_028.0, abs=0.01)

    def test_medical_threshold_is_3pct_capped_at_2759(self):
        # 3% of $80,000 = $2,400 < $2,759 → threshold = $2,400
        r = self._calc(net_income=80_000, medical_expenses=5_000)
        assert r["medical_threshold"] == pytest.approx(2_400.0, abs=0.01)
        assert r["medical_credit_base"] == pytest.approx(2_600.0, abs=0.01)

    def test_medical_threshold_capped(self):
        # 3% of $200,000 = $6,000 > $2,759 → threshold capped at $2,759
        r = self._calc(net_income=200_000, medical_expenses=5_000)
        assert r["medical_threshold"] == pytest.approx(2_759.0, abs=0.01)

    def test_total_credits_includes_bpa(self):
        r = self._calc()
        assert r["total_credits"] >= 16_129.0

    def test_credit_value_is_15pct_of_total(self):
        r = self._calc(employment_income=50_000)
        assert r["credit_value"] == pytest.approx(r["total_credits"] * 0.15, abs=0.01)


from app.calculator import (
    Schedule5Input, calculate_schedule5,
    Schedule7Input, calculate_schedule7,
    Schedule8Input, calculate_schedule8,
    T777Input, calculate_t777,
    T2209Input, calculate_t2209,
    WorksheetFedInput, calculate_worksheet_fed,
    FEDERAL_BASIC_PERSONAL, FEDERAL_EMPLOYMENT_MAX, FEDERAL_PENSION_MAX,
    FEDERAL_CREDIT_RATE,
)


class TestCalculateSchedule5:
    def test_zero_input(self):
        r = calculate_schedule5(Schedule5Input())
        assert r["line30300"] == 0.0
        assert r["line30400"] == 0.0
        assert r["line30500"] == 0.0

    def test_spouse_amount_full(self):
        # Spouse has no income -> 30300 = BPA = 16129
        r = calculate_schedule5(Schedule5Input(has_spouse=True, spouse_net_income=0.0))
        assert r["line30300"] == pytest.approx(16_129.0, abs=0.01)

    def test_spouse_amount_reduced(self):
        # Spouse earns 5000 -> 30300 = 16129 - 5000 = 11129
        r = calculate_schedule5(Schedule5Input(has_spouse=True, spouse_net_income=5_000.0))
        assert r["line30300"] == pytest.approx(11_129.0, abs=0.01)

    def test_spouse_amount_nil(self):
        # Spouse earns more than BPA -> 30300 = 0
        r = calculate_schedule5(Schedule5Input(has_spouse=True, spouse_net_income=20_000.0))
        assert r["line30300"] == 0.0

    def test_dep_amount(self):
        # Eligible dep with no income -> 30400 = 16129
        r = calculate_schedule5(Schedule5Input(has_eligible_dep=True, dep_net_income=0.0))
        assert r["line30400"] == pytest.approx(16_129.0, abs=0.01)

    def test_num_children(self):
        # 2 children -> 30500 = 2 * 2273 = 4546
        r = calculate_schedule5(Schedule5Input(num_children_under18=2))
        assert r["line30500"] == pytest.approx(4_546.0, abs=0.01)

    def test_no_spouse_flag_gives_zero(self):
        # has_spouse=False even with zero income -> 30300 = 0
        r = calculate_schedule5(Schedule5Input(has_spouse=False, spouse_net_income=0.0))
        assert r["line30300"] == 0.0


class TestCalculateSchedule7:
    def test_zero_input(self):
        r = calculate_schedule7(Schedule7Input())
        assert r["rrsp_total"] == 0.0
        assert r["fhsa_total"] == 0.0

    def test_rrsp_total(self):
        # prior 1000 + this year 2000 + jan60 500 = 3500
        r = calculate_schedule7(Schedule7Input(
            rrsp_unused_prior=1_000.0,
            rrsp_contrib_this_year=2_000.0,
            rrsp_contrib_jan60=500.0,
        ))
        assert r["rrsp_total"] == pytest.approx(3_500.0, abs=0.01)

    def test_rrsp_after_deduction(self):
        # total 5000 - deduction 3000 = 2000 remaining
        r = calculate_schedule7(Schedule7Input(
            rrsp_contrib_this_year=5_000.0,
            rrsp_deduction=3_000.0,
        ))
        assert r["rrsp_after_deduction"] == pytest.approx(2_000.0, abs=0.01)

    def test_fhsa_total(self):
        r = calculate_schedule7(Schedule7Input(
            fhsa_unused_prior=2_000.0,
            fhsa_contrib_this_year=3_000.0,
        ))
        assert r["fhsa_total"] == pytest.approx(5_000.0, abs=0.01)

    def test_hbp_min_repayment(self):
        # balance 30000, min repayment = 30000/15 = 2000
        r = calculate_schedule7(Schedule7Input(hbp_balance=30_000.0))
        assert r["hbp_min_repayment"] == pytest.approx(2_000.0, abs=0.01)

    def test_llp_min_repayment(self):
        # balance 20000, min repayment = 20000/10 = 2000
        r = calculate_schedule7(Schedule7Input(llp_balance=20_000.0))
        assert r["llp_min_repayment"] == pytest.approx(2_000.0, abs=0.01)

    def test_zero_balance_no_repayment(self):
        r = calculate_schedule7(Schedule7Input(hbp_balance=0.0, llp_balance=0.0))
        assert r["hbp_min_repayment"] == 0.0
        assert r["llp_min_repayment"] == 0.0


class TestCalculateSchedule8:
    def test_zero_input(self):
        r = calculate_schedule8(Schedule8Input())
        assert r["cpp1_on_se"] == 0.0
        assert r["line22200"] == 0.0

    def test_cpp1_basic(self):
        # income = 50000: base = min(50000, 73200) - 3500 = 46500; cpp1 = 46500 * 0.0595 = 2766.75
        r = calculate_schedule8(Schedule8Input(net_self_emp_income=50_000.0))
        assert r["cpp1_on_se"] == pytest.approx(2_766.75, abs=0.02)

    def test_cpp1_max(self):
        # income way above max -> capped at (73200 - 3500) * 0.0595 = 4147.15
        r = calculate_schedule8(Schedule8Input(net_self_emp_income=200_000.0))
        assert r["cpp1_on_se"] == pytest.approx(4_147.15, abs=0.02)

    def test_line22200_is_half_cpp1(self):
        r = calculate_schedule8(Schedule8Input(net_self_emp_income=50_000.0))
        assert r["line22200"] == pytest.approx(r["cpp1_on_se"] * 0.5, abs=0.01)

    def test_cpp2_only_above_73200(self):
        # income = 60000 < 73200 -> cpp2 = 0
        r = calculate_schedule8(Schedule8Input(net_self_emp_income=60_000.0))
        assert r["cpp2_on_se"] == 0.0

    def test_employment_cpp_reduces_se_cpp(self):
        # if already paid max through employment, SE cpp = 0
        r = calculate_schedule8(Schedule8Input(
            net_self_emp_income=100_000.0,
            cpp_thru_employment=4_147.15,
        ))
        assert r["cpp1_on_se"] == 0.0


class TestCalculateT777:
    def test_zero_input(self):
        r = calculate_t777(T777Input())
        assert r["line22900"] == 0.0

    def test_vehicle_proportion(self):
        # 5000 work km / 10000 total = 50%
        r = calculate_t777(T777Input(total_km=10_000.0, work_km=5_000.0, fuel=1_000.0))
        assert r["work_pct"] == pytest.approx(50.0, abs=0.01)
        assert r["vehicle_work"] == pytest.approx(500.0, abs=0.01)

    def test_home_office(self):
        # 10000 expenses * 40% = 4000
        r = calculate_t777(T777Input(home_office_expenses=10_000.0, home_office_work_pct=40.0))
        assert r["home_office_work"] == pytest.approx(4_000.0, abs=0.01)

    def test_line22900_total(self):
        r = calculate_t777(T777Input(
            total_km=10_000.0, work_km=5_000.0,
            fuel=2_000.0, supplies=500.0,
        ))
        # vehicle_total = 2000, work_pct = 0.5, vehicle_work = 1000
        # line22900 = 1000 + 0 + 500 + 0 + 0 = 1500
        assert r["line22900"] == pytest.approx(1_500.0, abs=0.01)

    def test_no_total_km_gives_zero_vehicle(self):
        r = calculate_t777(T777Input(total_km=0.0, work_km=100.0, fuel=500.0))
        assert r["vehicle_work"] == 0.0

    def test_supplies_added(self):
        r = calculate_t777(T777Input(supplies=1_234.56))
        assert r["line22900"] == pytest.approx(1_234.56, abs=0.01)


class TestCalculateT2209:
    def test_zero_input(self):
        r = calculate_t2209(T2209Input())
        assert r["line40500"] == 0.0

    def test_credit_non_business(self):
        # foreign_income = 10000, net_income = 100000 -> proportion = 0.1
        # fed_tax = 20000, limit = 0.1 * 20000 = 2000
        # foreign_tax = 1500 < 2000 -> credit = 1500
        r = calculate_t2209(T2209Input(
            foreign_income_non_business=10_000.0,
            foreign_tax_non_business=1_500.0,
            net_income=100_000.0,
            federal_tax_before_credits=20_000.0,
        ))
        assert r["credit_non_biz"] == pytest.approx(1_500.0, abs=0.01)

    def test_credit_at_limit(self):
        # foreign_tax paid > limit -> capped at limit
        r = calculate_t2209(T2209Input(
            foreign_income_non_business=10_000.0,
            foreign_tax_non_business=5_000.0,  # more than limit
            net_income=100_000.0,
            federal_tax_before_credits=20_000.0,
        ))
        assert r["credit_non_biz"] == pytest.approx(2_000.0, abs=0.01)  # limit = 0.1 * 20000

    def test_credit_is_min_of_tax_and_limit(self):
        r = calculate_t2209(T2209Input(
            foreign_income_non_business=5_000.0,
            foreign_tax_non_business=1_000.0,
            net_income=50_000.0,
            federal_tax_before_credits=10_000.0,
        ))
        limit = (5_000.0 / 50_000.0) * 10_000.0  # 1000
        assert r["credit_non_biz"] == pytest.approx(min(1_000.0, limit), abs=0.01)

    def test_line40500_sum(self):
        # credit_non_biz + credit_biz
        r = calculate_t2209(T2209Input(
            foreign_income_non_business=10_000.0,
            foreign_tax_non_business=500.0,
            net_income=100_000.0,
            federal_tax_before_credits=20_000.0,
        ))
        assert r["line40500"] == pytest.approx(r["credit_non_biz"] + r["credit_biz"], abs=0.01)

    def test_zero_net_income_gives_zero(self):
        r = calculate_t2209(T2209Input(
            foreign_income_non_business=5_000.0,
            foreign_tax_non_business=1_000.0,
            net_income=0.0,
            federal_tax_before_credits=5_000.0,
        ))
        assert r["credit_non_biz"] == 0.0


class TestCalculateWorksheetFed:
    def test_zero_input(self):
        # Even with zero input, BPA is included in total_credits
        r = calculate_worksheet_fed(WorksheetFedInput())
        assert r["bpa"] == pytest.approx(FEDERAL_BASIC_PERSONAL, abs=0.01)
        assert r["total_credits"] >= FEDERAL_BASIC_PERSONAL

    def test_bpa_always_included(self):
        r = calculate_worksheet_fed(WorksheetFedInput(net_income=50_000.0))
        assert r["total_credits"] >= FEDERAL_BASIC_PERSONAL

    def test_age_amount_computed(self):
        # age 65+, low income -> full age amount
        r = calculate_worksheet_fed(WorksheetFedInput(
            net_income=30_000.0, age_65_or_over=True
        ))
        assert r["age_amt"] == pytest.approx(9_028.0, abs=0.01)

    def test_employment_amount_capped(self):
        # employment_income > 1471 -> capped at 1471
        r = calculate_worksheet_fed(WorksheetFedInput(employment_income=100_000.0))
        assert r["employment_amt"] == pytest.approx(FEDERAL_EMPLOYMENT_MAX, abs=0.01)

    def test_pension_amount_capped(self):
        # pension > 2000 -> capped at 2000
        r = calculate_worksheet_fed(WorksheetFedInput(eligible_pension=5_000.0))
        assert r["pension_amt"] == pytest.approx(FEDERAL_PENSION_MAX, abs=0.01)

    def test_medical_threshold(self):
        # net income 50000, 3% = 1500 < 2759 -> threshold = 1500
        r = calculate_worksheet_fed(WorksheetFedInput(net_income=50_000.0, medical_expenses=3_000.0))
        assert r["medical_threshold"] == pytest.approx(1_500.0, abs=0.01)
        assert r["medical_credit_base"] == pytest.approx(1_500.0, abs=0.01)
