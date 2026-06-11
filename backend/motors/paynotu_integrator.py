"""
PayNotu Entegratör
Görev: Spek motoru (davranış) + Duygusal motor (topluluk) = PayNotu Skoru

NOT: financial_engine v2.2'den itibaren spek_score üretir (kalite değil
davranış yoğunluğu). f_score yüksek = riskli/spekülatif yönlüdür.

Yön hizalama:
  f_score : yüksek → riskli   (ters çevrilmez, spek_score zaten bu yönde)
  e_score : yüksek → memnun   (ters çevrilir → r_h = 10 - e_score)

Robust kalibrasyon:
  q05/q95 geçerliyse f_raw → 0–10 aralığına percentile-normalize edilir.
  Değilse doğrudan clamp(f_raw, 0, 10).

Dinamik duygusal ağırlık:
  e_base  = effective_review_weight ?? effective_review_count ?? 0
  e_conf  = e_base / (e_base + 500)           ← Bayesian güven [0, 1)
  e_weight = 0.35 * e_conf                    ← max 0.35
  f_weight = 1.0 - e_weight

  Duygu ayrışması (f > 7.0 AND r_h < 3.0):
  e_weight = min(e_weight, 0.10), f_weight = 1.0 - e_weight

Veri yoksa:
  f_raw is None → paynotu_score = None (erken dönüş)

Semantik:
  f_raw == 0.0 geçerli minimum skordur — en temiz / en düşük riskli hisse.
  0.0 hiçbir zaman "veri yok" anlamına gelmez.

Düşük P = sakin / temiz
Yüksek P = dikkat / anomali / risk
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .financial_engine import SpekResult
from .emotional_engine import EmotionalResult

# Dinamik ağırlık tavanı
MAX_EMOTIONAL_WEIGHT     = 0.35
BAYESIAN_CONFIDENCE_N    = 500.0   # Bayesian çapa gücü (yorum sayısı birimi)

# Duygu ayrışması override eşikleri
HIGH_SPEK_THRESHOLD      = 7.0
LOW_PUBLIC_RISK_THRESHOLD = 3.0
DIVERGENCE_MAX_E_WEIGHT  = 0.10

# Bayesian anchor nötr değeri — yorum yoksa emotional_score buraya çöker
_BAYESIAN_NEUTRAL = 5.0


@dataclass(frozen=True)
class PayNotuResult:
    ticker:                  str
    paynotu_score:           Optional[float]  # None = veri yetersiz (IPO vb.)
    raw_spek_score:          float            # ham spek_score (kalibrasyon öncesi)
    emotional_score:         float            # ham emotional_score (ters çevrilmemiş)
    emotional_risk:          float            # r_h = 10 - emotional_score
    emotional_grip:          float
    grip_intensity:          float
    is_sentiment_divergence: bool             # override bayrağı
    has_reviews:             bool

    def copyWith(self, **kwargs) -> "PayNotuResult":
        import dataclasses
        return dataclasses.replace(self, **kwargs)


class PayNotuIntegrator:
    """Robust kalibrasyon + dinamik duygusal ağırlık."""

    def calculate(
        self,
        financial: SpekResult,
        emotional: EmotionalResult,
        q05: Optional[float] = None,
        q95: Optional[float] = None,
    ) -> PayNotuResult:

        f_raw = financial.spek_score

        # ── Veri yoksa erken dönüş ───────────────────────────────────────────
        # Yalnızca f_raw is None gerçek "veri yok" durumudur.
        # f_raw == 0.0 geçerli minimum skordur; hesaplama devam eder.
        if f_raw is None:
            return PayNotuResult(
                ticker=financial.ticker,
                paynotu_score=None,
                raw_spek_score=0.0,
                emotional_score=_BAYESIAN_NEUTRAL,
                emotional_risk=10.0 - _BAYESIAN_NEUTRAL,
                emotional_grip=0.0,
                grip_intensity=0.0,
                is_sentiment_divergence=False,
                has_reviews=False,
            )

        # ── Robust kalibrasyon ───────────────────────────────────────────────
        if q05 is not None and q95 is not None and q95 > q05:
            f = 10.0 * (f_raw - q05) / (q95 - q05)
        else:
            f = float(f_raw)
        f = max(0.0, min(10.0, f))

        # ── Duygusal skor ────────────────────────────────────────────────────
        raw_e   = emotional.emotional_score
        e_score = raw_e if raw_e is not None else _BAYESIAN_NEUTRAL
        e_score = max(0.0, min(10.0, e_score))

        has_reviews = emotional.effective_review_count > 0

        # Yön hizalama
        r_h = 10.0 - e_score

        # ── Dinamik duygusal ağırlık ─────────────────────────────────────────
        e_base = (
            getattr(emotional, "effective_review_weight", None)
            or getattr(emotional, "effective_review_count", None)
            or 0.0
        )
        e_conf   = float(e_base) / (float(e_base) + BAYESIAN_CONFIDENCE_N)
        e_weight = MAX_EMOTIONAL_WEIGHT * e_conf
        f_weight = 1.0 - e_weight

        # ── Duygu ayrışması override ─────────────────────────────────────────
        is_sentiment_divergence = (
            f > HIGH_SPEK_THRESHOLD and r_h < LOW_PUBLIC_RISK_THRESHOLD
        )
        if is_sentiment_divergence:
            e_weight = min(e_weight, DIVERGENCE_MAX_E_WEIGHT)
            f_weight = 1.0 - e_weight

        # ── Nihai skor — AAS tabanlı ─────────────────────────────────────────
        aas = (
            financial.anomaly_metrics.anomaly_activity_score
            if getattr(financial, "anomaly_metrics", None) is not None
            else None
        )
        paynotu_score = aas

        emotional_grip  = round(e_weight * r_h, 4)
        grip_intensity  = round(e_weight, 4)

        return PayNotuResult(
            ticker=financial.ticker,
            paynotu_score=paynotu_score,
            raw_spek_score=round(f_raw, 4),
            emotional_score=e_score,
            emotional_risk=round(r_h, 4),
            emotional_grip=emotional_grip,
            grip_intensity=grip_intensity,
            is_sentiment_divergence=is_sentiment_divergence,
            has_reviews=has_reviews,
        )
