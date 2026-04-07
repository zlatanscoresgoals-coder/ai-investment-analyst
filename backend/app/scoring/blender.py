from typing import Optional

from app.scoring.personas import (
    score_ackman,
    score_buffett,
    score_burry,
    score_institutional,
    score_wood,
)

# Pelosi Proxy removed — it was a hardcoded constant (55.0) that added no
# differentiation. Its 5% weight is redistributed: +3% to Buffett (most
# data-grounded quality lens) and +2% to Burry (balance-sheet rigour).
WEIGHTS = {
    "buffett":     0.28,
    "ackman":      0.20,
    "wood":        0.15,
    "burry":       0.22,
    "institutional": 0.15,
}


def score_all(metrics: dict, sector: Optional[str] = None) -> dict[str, float]:
    buffett     = score_buffett(metrics, sector)
    ackman      = score_ackman(metrics, sector)
    wood        = score_wood(metrics, sector)
    burry       = score_burry(metrics, sector)
    institutional = score_institutional(metrics, sector)

    final_score = (
        buffett      * WEIGHTS["buffett"]
        + ackman     * WEIGHTS["ackman"]
        + wood       * WEIGHTS["wood"]
        + burry      * WEIGHTS["burry"]
        + institutional * WEIGHTS["institutional"]
    )

    return {
        "buffett_score":      buffett,
        "ackman_score":       ackman,
        "wood_score":         wood,
        "burry_score":        burry,
        "pelosi_proxy_score": 0.0,   # kept in output for schema compat; always 0
        "institutional_score": institutional,
        "final_score":        final_score,
    }
