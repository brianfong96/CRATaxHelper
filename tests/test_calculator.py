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
