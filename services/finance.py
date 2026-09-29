"""Savings and loan math. Mirrored client-side in static/js/calculators.js.

All rates are annual percentages compounded monthly; all money values are
plain numbers in whole currency units (not cents) since these are projections.
"""

import math


def _monthly_rate(annual_rate_pct):
    return annual_rate_pct / 100 / 12


def future_value(principal, monthly_contribution, annual_rate_pct, months):
    """Balance after `months` of contributions made at the end of each month."""
    if months < 0:
        raise ValueError("months must be >= 0")
    r = _monthly_rate(annual_rate_pct)
    if r == 0:
        return principal + monthly_contribution * months
    growth = (1 + r) ** months
    return principal * growth + monthly_contribution * (growth - 1) / r


def required_monthly_saving(target, current, annual_rate_pct, months):
    """Monthly contribution needed to grow `current` into `target` in `months`."""
    if months <= 0:
        return max(target - current, 0)
    r = _monthly_rate(annual_rate_pct)
    if r == 0:
        needed = (target - current) / months
    else:
        growth = (1 + r) ** months
        needed = (target - current * growth) * r / (growth - 1)
    return max(needed, 0)


def months_to_goal(target, current, monthly_contribution, annual_rate_pct, max_months=1200):
    """Months until the balance reaches `target`, or None if it never does."""
    if current >= target:
        return 0
    r = _monthly_rate(annual_rate_pct)
    if r == 0:
        if monthly_contribution <= 0:
            return None
        return math.ceil((target - current) / monthly_contribution)
    if monthly_contribution <= 0 and current <= 0:
        return None
    # Closed form: n = ln((T*r + C) / (P*r + C)) / ln(1 + r)
    numerator = target * r + monthly_contribution
    denominator = current * r + monthly_contribution
    if denominator <= 0:
        return None
    months = math.log(numerator / denominator) / math.log(1 + r)
    months = math.ceil(months - 1e-9)
    return months if months <= max_months else None


def loan_emi(principal, annual_rate_pct, months):
    """Equated monthly instalment for a fully amortising loan."""
    if months <= 0:
        raise ValueError("months must be > 0")
    r = _monthly_rate(annual_rate_pct)
    if r == 0:
        return principal / months
    growth = (1 + r) ** months
    return principal * r * growth / (growth - 1)


def savings_rate(income, expense):
    """Share of income kept, as a percentage. None when there is no income."""
    if income <= 0:
        return None
    return (income - expense) / income * 100
