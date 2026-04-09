import logging

from domain.models import DecisionScore, ScoreBreakdown
from infra.config import Config

logger = logging.getLogger(__name__)


class DecisionScorer:
    """
    Combines 4 sub-scores into a single Decision Score (0-100).
    The trade only executes if score > threshold AND no hard veto.
    """

    WEIGHTS = {
        "market_quality": 0.20,
        "strategy": 0.35,
        "ai_overlay": 0.20,
        "risk": 0.25,
    }

    def __init__(self):
        self.threshold = Config.DECISION_THRESHOLD  # 65

    def calculate(self, mq: int, ss: int, ao: int, rs: int) -> DecisionScore:
        """
        mq: Market Quality Score (0-100) from pre_filter
        ss: Strategy Score (0-100) from signal_parser
        ao: AI Overlay Score (0-100) from confidence_adjuster
        rs: Risk Score (0-100) from risk engine
        """
        w = self.WEIGHTS

        # Calculate weighted total
        total = (
            mq * w["market_quality"] +
            ss * w["strategy"] +
            ao * w["ai_overlay"] +
            rs * w["risk"]
        )

        # Hard veto: any sub-score < 20 blocks execution
        hard_veto = any(s < 20 for s in [mq, ss, ao, rs])
        veto_reasons = []
        if mq < 20:
            veto_reasons.append(f"MQ={mq}")
        if ss < 20:
            veto_reasons.append(f"SS={ss}")
        if ao < 20:
            veto_reasons.append(f"AO={ao}")
        if rs < 20:
            veto_reasons.append(f"RS={rs}")

        go = total >= self.threshold and not hard_veto

        # Build breakdown
        breakdown = {
            "market_quality": ScoreBreakdown(
                score=mq, weight=w["market_quality"],
                contribution=round(mq * w["market_quality"], 1)
            ),
            "strategy": ScoreBreakdown(
                score=ss, weight=w["strategy"],
                contribution=round(ss * w["strategy"], 1)
            ),
            "ai_overlay": ScoreBreakdown(
                score=ao, weight=w["ai_overlay"],
                contribution=round(ao * w["ai_overlay"], 1)
            ),
            "risk": ScoreBreakdown(
                score=rs, weight=w["risk"],
                contribution=round(rs * w["risk"], 1)
            ),
        }

        veto_reason = ""
        if hard_veto:
            veto_reason = f"Hard veto: {', '.join(veto_reasons)}"
        elif total < self.threshold:
            veto_reason = f"Score {total:.1f} < threshold {self.threshold}"

        result = DecisionScore(
            total=round(total, 1),
            go=go,
            breakdown=breakdown,
            threshold=self.threshold,
            hard_veto=hard_veto,
            veto_reason=veto_reason,
        )

        status = "GO" if go else f"NO-GO ({veto_reason})"
        logger.info(
            f"Decision Score: {total:.1f}/100 [{status}] "
            f"(MQ={mq} SS={ss} AO={ao} RS={rs})"
        )

        return result
