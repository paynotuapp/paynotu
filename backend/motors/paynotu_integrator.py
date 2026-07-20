"""
PayNotu Entegratör
Görev: AAS (davranışsal anomali aktivite skoru) = PayNotu Skoru.

NOT: spek_score (TOPSIS + entropi + fundamental_multiplier + haber_carpani
bileşik sayısı) 2026-07-20'de emekli edildi — bkz.
backend/docs/paynotu_spekscore_emeklilik_is_emri.md. paynotu_score artık
doğrudan financial.anomaly_metrics.anomaly_activity_score'dur; başka bir
girdi karışmaz.

Semantik:
Düşük P = sakin / temiz
Yüksek P = dikkat / anomali / risk
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .financial_engine import SpekResult
from .emotional_engine import EmotionalResult

# Bayesian anchor nötr değeri — yorum yoksa emotional_score buraya çöker
_BAYESIAN_NEUTRAL = 5.0


@dataclass(frozen=True)
class PayNotuResult:
    ticker:          str
    paynotu_score:   Optional[float]  # None = veri yetersiz (IPO vb.), AAS tabanlı
    emotional_score: float            # ham emotional_score (ters çevrilmemiş)
    emotional_risk:  float            # r_h = 10 - emotional_score
    has_reviews:     bool

    def copyWith(self, **kwargs) -> "PayNotuResult":
        import dataclasses
        return dataclasses.replace(self, **kwargs)


class PayNotuIntegrator:
    """paynotu_score = AAS (anomaly_activity_score); emotional_score bilgi amaçlı taşınır."""

    def calculate(
        self,
        financial: SpekResult,
        emotional: EmotionalResult,
    ) -> PayNotuResult:
        aas = (
            financial.anomaly_metrics.anomaly_activity_score
            if getattr(financial, "anomaly_metrics", None) is not None
            else None
        )

        raw_e   = emotional.emotional_score
        e_score = raw_e if raw_e is not None else _BAYESIAN_NEUTRAL
        e_score = max(0.0, min(10.0, e_score))
        has_reviews = emotional.effective_review_count > 0
        r_h = 10.0 - e_score

        return PayNotuResult(
            ticker=financial.ticker,
            paynotu_score=aas,
            emotional_score=e_score,
            emotional_risk=round(r_h, 4),
            has_reviews=has_reviews,
        )
