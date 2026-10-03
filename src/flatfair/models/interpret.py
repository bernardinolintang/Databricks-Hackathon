"""Plain-English reading of a forecast. No ML imports: the app uses this."""

from __future__ import annotations

from typing import Any

STABLE_BAND_PCT = 1.5
MODEST_BAND_PCT = 4.0


def interpret_forecast(
    place: str,
    recent_level: float,
    final_forecast: float,
    final_lower: float,
    final_upper: float,
    final_month_label: str,
    interval_level: float,
) -> dict[str, Any]:
    """Describe the six-month projection without overstating certainty."""
    change_pct = (final_forecast / recent_level - 1) * 100
    if abs(change_pct) < STABLE_BAND_PCT:
        direction, phrase = "stable", "remain broadly stable"
    elif change_pct > 0:
        direction = "up"
        phrase = "rise modestly" if change_pct < MODEST_BAND_PCT else "rise"
    else:
        direction = "down"
        phrase = "ease modestly" if change_pct > -MODEST_BAND_PCT else "decline"

    sentence = (
        f"Based on recent market patterns, median resale prices in {place} are projected to {phrase} "
        f"over the next six months"
    )
    if direction != "stable":
        sentence += f" (about {change_pct:+.1f}% by {final_month_label})"
    sentence += "."

    straddles = final_lower < recent_level < final_upper
    caveat = (
        f"The {interval_level:.0%} range for {final_month_label} runs from ${final_lower:,.0f} to ${final_upper:,.0f}"
    )
    caveat += (
        ", which spans both higher and lower than today, so the direction is uncertain."
        if straddles and direction != "stable"
        else "."
    )
    return {
        "direction": direction,
        "change_pct": round(change_pct, 2),
        "headline": sentence,
        "caveat": caveat,
        "direction_uncertain": bool(straddles),
    }
