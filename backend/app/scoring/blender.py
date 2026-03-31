from app.scoring.personas import (
    score_ackman,
    score_buffett,
    score_burry,
    score_institutional,
    score_pelosi_proxy,
    score_wood,
)

WEIGHTS = {
    "buffett": 0.25,
    "ackman": 0.20,
    "wood": 0.15,
    "burry": 0.20,
    "pelosi_proxy": 0.05,
    "institutional": 0.15,
}


def score_all(metrics: dict) -> dict[str, float]:
    buffett = score_buffett(metrics)
    ackman = score_ackman(metrics)
    wood = score_wood(metrics)
    burry = score_burry(metrics)
    pelosi_proxy = score_pelosi_proxy(metrics)
    institutional = score_institutional(metrics)

    final_score = (
        buffett * WEIGHTS["buffett"]
        + ackman * WEIGHTS["ackman"]
        + wood * WEIGHTS["wood"]
        + burry * WEIGHTS["burry"]
        + pelosi_proxy * WEIGHTS["pelosi_proxy"]
        + institutional * WEIGHTS["institutional"]
    )

    return {
        "buffett_score": buffett,
        "ackman_score": ackman,
        "wood_score": wood,
        "burry_score": burry,
        "pelosi_proxy_score": pelosi_proxy,
        "institutional_score": institutional,
        "final_score": final_score,
    }
