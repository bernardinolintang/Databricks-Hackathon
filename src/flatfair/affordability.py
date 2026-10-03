"""Affordability maths. Every formula here is deliberately simple and visible.

Nothing in this module is financial advice. It ignores housing grants, CPF
accrued interest, loan eligibility rules, legal and agent fees, and renovation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LoanAssumptions:
    loan_to_value: float
    annual_interest_rate: float
    tenure_years: int
    msr_limit: float
    comfortable_ratio: float
    bsd_tiers: tuple[tuple[float | None, float], ...]

    @classmethod
    def from_config(cls, cfg: dict[str, Any], **overrides: Any) -> "LoanAssumptions":
        base = dict(cfg["affordability"])
        base.update({k: v for k, v in overrides.items() if v is not None})
        assumptions = cls(
            loan_to_value=float(base["loan_to_value"]),
            annual_interest_rate=float(base["annual_interest_rate"]),
            tenure_years=int(base["tenure_years"]),
            msr_limit=float(base["msr_limit"]),
            comfortable_ratio=float(base["comfortable_ratio"]),
            bsd_tiers=tuple((tier[0], float(tier[1])) for tier in base["bsd_tiers"]),
        )
        assumptions.validate()
        return assumptions

    def validate(self) -> None:
        if not 0 < self.loan_to_value <= 1:
            raise ValueError("loan_to_value must be between 0 and 1")
        if not 0 <= self.annual_interest_rate < 0.25:
            raise ValueError("annual_interest_rate must be between 0 and 0.25")
        if not 1 <= self.tenure_years <= 35:
            raise ValueError("tenure_years must be between 1 and 35")


def monthly_repayment(principal: float, annual_rate: float, years: int) -> float:
    """Level monthly instalment on a fully amortising loan."""
    if principal <= 0:
        return 0.0
    periods = years * 12
    rate = annual_rate / 12
    if rate == 0:
        return principal / periods
    return principal * rate / (1 - (1 + rate) ** -periods)


def loan_from_repayment(repayment: float, annual_rate: float, years: int) -> float:
    """Inverse of monthly_repayment: the loan a given instalment can service."""
    if repayment <= 0:
        return 0.0
    periods = years * 12
    rate = annual_rate / 12
    if rate == 0:
        return repayment * periods
    return repayment * (1 - (1 + rate) ** -periods) / rate


def buyers_stamp_duty(price: float, tiers: tuple[tuple[float | None, float], ...]) -> float:
    """Marginal-rate Buyer's Stamp Duty. A tier width of None means 'the rest'."""
    remaining, duty = max(price, 0.0), 0.0
    for width, rate in tiers:
        portion = remaining if width is None else min(remaining, width)
        duty += portion * rate
        remaining -= portion
        if remaining <= 0:
            break
    return duty


def assess(price: float, monthly_income: float, cash_cpf: float, a: LoanAssumptions) -> dict[str, Any]:
    """Cost breakdown and repayment burden for buying at `price`."""
    if price <= 0:
        raise ValueError("price must be positive")
    if monthly_income <= 0:
        raise ValueError("monthly_income must be positive")
    cash_cpf = max(cash_cpf, 0.0)

    stamp_duty = buyers_stamp_duty(price, a.bsd_tiers)
    max_loan = price * a.loan_to_value
    min_downpayment = price - max_loan
    upfront_needed = min_downpayment + stamp_duty
    # Savings beyond the minimum upfront cost reduce the loan.
    extra = max(cash_cpf - upfront_needed, 0.0)
    loan = max(max_loan - extra, 0.0)
    downpayment = price - loan
    repayment = monthly_repayment(loan, a.annual_interest_rate, a.tenure_years)
    ratio = repayment / monthly_income

    if ratio <= a.comfortable_ratio:
        status, label = "comfortable", "Comfortable"
    elif ratio <= a.msr_limit:
        status, label = "stretch", "Within the 30% limit"
    else:
        status, label = "over", "Over the 30% limit"

    return {
        "price": round(price),
        "stamp_duty": round(stamp_duty),
        "min_downpayment": round(min_downpayment),
        "downpayment": round(downpayment),
        "upfront_needed": round(upfront_needed),
        "upfront_shortfall": round(max(upfront_needed - cash_cpf, 0.0)),
        "loan": round(loan),
        "monthly_repayment": round(repayment),
        "repayment_ratio": round(ratio, 4),
        "price_to_income": round(price / (monthly_income * 12), 2),
        "status": status,
        "status_label": label,
    }


def max_price(monthly_income: float, cash_cpf: float, a: LoanAssumptions, max_monthly_repayment: float | None = None) -> dict[str, Any]:
    """Highest price that satisfies both the repayment cap and the upfront cash."""
    cap = monthly_income * a.msr_limit
    if max_monthly_repayment is not None and max_monthly_repayment > 0:
        cap = min(cap, max_monthly_repayment)
    max_loan = loan_from_repayment(cap, a.annual_interest_rate, a.tenure_years)

    def upfront(price: float) -> float:
        return price * (1 - a.loan_to_value) + buyers_stamp_duty(price, a.bsd_tiers)

    def feasible(price: float) -> bool:
        if cash_cpf < upfront(price):
            return False
        loan = max(price * a.loan_to_value - (cash_cpf - upfront(price)), 0.0)
        return loan <= max_loan

    # Feasibility is monotone in price, so bisect.
    low, high = 0.0, 5_000_000.0
    for _ in range(60):
        mid = (low + high) / 2
        low, high = (mid, high) if feasible(mid) else (low, mid)

    # Which constraint binds just above the budget?
    limited_by = "upfront cash" if cash_cpf < upfront(low * 1.01 + 1) else "monthly repayment"
    return {
        "max_price": int(low // 1000 * 1000),
        "repayment_cap": round(cap),
        "max_loan": round(max_loan),
        "limited_by": limited_by,
    }


def rank_towns(
    town_prices: pd.DataFrame,
    monthly_income: float,
    cash_cpf: float,
    a: LoanAssumptions,
    max_monthly_repayment: float | None = None,
) -> pd.DataFrame:
    """Rank towns from most to least financially accessible for one household.

    `town_prices` needs columns town, median_price, transactions. Towns are
    ordered by repayment-to-income ratio at the town's median price: the lower
    the ratio, the more accessible. A town is 'within reach' when the repayment
    fits the cap and savings cover the upfront cost.
    """
    cap = monthly_income * a.msr_limit
    if max_monthly_repayment is not None and max_monthly_repayment > 0:
        cap = min(cap, max_monthly_repayment)
    rows = []
    for record in town_prices.itertuples(index=False):
        result = assess(float(record.median_price), monthly_income, cash_cpf, a)
        rows.append(
            {
                "town": record.town,
                "median_price": result["price"],
                "transactions": int(record.transactions),
                "monthly_repayment": result["monthly_repayment"],
                "repayment_ratio": result["repayment_ratio"],
                "upfront_needed": result["upfront_needed"],
                "upfront_shortfall": result["upfront_shortfall"],
                "price_to_income": result["price_to_income"],
                "status": result["status"],
                "status_label": result["status_label"],
                "within_reach": result["monthly_repayment"] <= cap and result["upfront_shortfall"] == 0,
            }
        )
    ranked = pd.DataFrame(rows).sort_values("repayment_ratio").reset_index(drop=True)
    ranked["rank"] = ranked.index + 1
    return ranked


def build_gold_affordability(town_summary: pd.DataFrame, income: pd.DataFrame | None, cfg: dict[str, Any]) -> pd.DataFrame:
    """Affordability of each town x flat type for the official median household.

    Uses the default loan assumptions and no savings beyond the minimum
    downpayment. Empty when no income benchmark is available.
    """
    columns = [
        "town", "flat_type", "median_price_12m", "benchmark_year", "benchmark_monthly_income",
        "price_to_income", "loan", "monthly_repayment", "repayment_ratio", "status",
    ]
    if income is None or income.empty:
        return pd.DataFrame(columns=columns)
    latest = income.sort_values("year").iloc[-1]
    monthly_income = float(latest["median_monthly_household_income"])
    a = LoanAssumptions.from_config(cfg)
    rows = []
    for record in town_summary.dropna(subset=["median_price_12m"]).itertuples(index=False):
        result = assess(float(record.median_price_12m), monthly_income, 0.0, a)
        rows.append(
            {
                "town": record.town,
                "flat_type": record.flat_type,
                "median_price_12m": result["price"],
                "benchmark_year": int(latest["year"]),
                "benchmark_monthly_income": monthly_income,
                "price_to_income": result["price_to_income"],
                "loan": result["loan"],
                "monthly_repayment": result["monthly_repayment"],
                "repayment_ratio": result["repayment_ratio"],
                "status": result["status"],
            }
        )
    return pd.DataFrame(rows, columns=columns)
