import pandas as pd
import pytest

from flatfair.affordability import (
    LoanAssumptions,
    assess,
    buyers_stamp_duty,
    loan_from_repayment,
    max_price,
    monthly_repayment,
    rank_towns,
)


@pytest.fixture
def assumptions(cfg):
    return LoanAssumptions.from_config(cfg)


def test_monthly_repayment_matches_annuity_formula():
    # $400k over 25 years at 2.6% p.a. -> ~$1,814.69 a month.
    assert monthly_repayment(400_000, 0.026, 25) == pytest.approx(1814.69, abs=0.5)


def test_zero_rate_and_zero_principal():
    assert monthly_repayment(120_000, 0.0, 10) == pytest.approx(1000)
    assert monthly_repayment(0, 0.026, 25) == 0


def test_loan_from_repayment_inverts_repayment():
    payment = monthly_repayment(500_000, 0.03, 30)
    assert loan_from_repayment(payment, 0.03, 30) == pytest.approx(500_000)


def test_buyers_stamp_duty_tiers(assumptions):
    # 1% of 180k + 2% of 180k + 3% of the remaining 240k.
    assert buyers_stamp_duty(600_000, assumptions.bsd_tiers) == pytest.approx(1_800 + 3_600 + 7_200)
    assert buyers_stamp_duty(100_000, assumptions.bsd_tiers) == pytest.approx(1_000)


def test_assess_breakdown(assumptions):
    result = assess(600_000, 9_000, 200_000, assumptions)
    assert result["min_downpayment"] == 150_000
    assert result["stamp_duty"] == 12_600
    # 200k covers 150k + 12.6k; the 37.4k left over shrinks the loan.
    assert result["loan"] == 450_000 - 37_400
    assert result["upfront_shortfall"] == 0
    assert result["repayment_ratio"] == pytest.approx(result["monthly_repayment"] / 9_000, abs=1e-4)
    assert result["price_to_income"] == pytest.approx(600_000 / 108_000, abs=0.01)


def test_status_thresholds(assumptions):
    assert assess(400_000, 20_000, 120_000, assumptions)["status"] == "comfortable"
    assert assess(900_000, 6_000, 250_000, assumptions)["status"] == "over"


def test_upfront_shortfall(assumptions):
    assert assess(600_000, 9_000, 100_000, assumptions)["upfront_shortfall"] == 62_600


def test_max_price_is_affordable(assumptions):
    budget = max_price(9_000, 200_000, assumptions)
    at_budget = assess(budget["max_price"], 9_000, 200_000, assumptions)
    assert at_budget["repayment_ratio"] <= assumptions.msr_limit + 1e-6
    assert at_budget["upfront_shortfall"] == 0


def test_max_price_without_savings_is_zero(assumptions):
    budget = max_price(9_000, 0, assumptions)
    assert budget["max_price"] == 0
    assert budget["limited_by"] == "upfront cash"


def test_rank_towns_orders_by_burden(assumptions):
    prices = pd.DataFrame(
        {"town": ["A", "B", "C"], "median_price": [800_000, 500_000, 650_000], "transactions": [10, 10, 10]}
    )
    ranked = rank_towns(prices, 9_000, 200_000, assumptions)
    assert ranked["town"].tolist() == ["B", "C", "A"]
    assert ranked["rank"].tolist() == [1, 2, 3]


def test_assumption_validation(cfg):
    with pytest.raises(ValueError):
        LoanAssumptions.from_config(cfg, loan_to_value=1.5)
