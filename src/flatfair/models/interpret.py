"""Plain-English reading of a forecast. No ML imports: the app uses this."""

from __future__ import annotations

from typing import Any

STABLE_BAND_PCT = 1.5
MODEST_BAND_PCT = 4.0


def interpret_forecast(
    subject: str,
    recent_level: float,
    final_forecast: float,
    final_lower: float,
    final_upper: float,
    final_month_label: str,
    interval_level: float,
) -> dict[str, Any]:
    """Describe the six-month projection without overstating certainty.

    `subject` is what the sentence is about, e.g. "4-room prices in Tampines".
    """
    change_pct = (final_forecast / recent_level - 1) * 100
    if abs(change_pct) < STABLE_BAND_PCT:
        direction, phrase = "stable", "stay about the same"
    elif change_pct > 0:
        direction = "up"
        phrase = "rise a little" if change_pct < MODEST_BAND_PCT else "rise"
    else:
        direction = "down"
        phrase = "dip a little" if change_pct > -MODEST_BAND_PCT else "fall"

    sentence = f"{subject} look set to {phrase} over the next six months"
    if direction != "stable":
        sentence += f", by about {abs(change_pct):.1f}% by {final_month_label}"
    sentence += "."

    straddles = final_lower < recent_level < final_upper
    caveat = f"The likely range for {final_month_label} is ${final_lower:,.0f} to ${final_upper:,.0f}."
    if straddles and direction != "stable":
        caveat += " That covers both a rise and a fall, so the direction is uncertain."
    return {
        "direction": direction,
        "change_pct": round(change_pct, 2),
        "headline": sentence,
        "caveat": caveat,
        "direction_uncertain": bool(straddles),
        "interval_level": interval_level,
    }
