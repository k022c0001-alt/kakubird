from typing import Any, Dict, List, Optional


def analyze_price_history(
    observations: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Summarize a dated close-price series without imputing missing observations."""
    valid = [
        item
        for item in observations
        if isinstance(item.get("close"), (int, float))
        and item["close"] > 0
        and item.get("date")
    ]
    if len(valid) < 2:
        return None

    changes = []
    for previous, current in zip(valid, valid[1:]):
        delta = current["close"] - previous["close"]
        direction = 1 if delta > 0 else -1 if delta < 0 else 0
        if direction:
            changes.append(direction)

    alternating_moves = sum(
        previous != current
        for previous, current in zip(changes, changes[1:])
    )
    first = valid[0]
    latest = valid[-1]
    return {
        "period_start": first["date"],
        "period_end": latest["date"],
        "observation_count": len(valid),
        "first_close": first["close"],
        "latest_close": latest["close"],
        "change_percent": round(
            (latest["close"] / first["close"] - 1) * 100, 2
        ),
        "up_moves": changes.count(1),
        "down_moves": changes.count(-1),
        "alternating_moves": alternating_moves,
        "repeated_alternation": alternating_moves >= 2,
    }
