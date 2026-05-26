"""
PayNotu Entegratör
Görev: Spek motoru (davranış) + Duygusal motor (topluluk) = PayNotu Skoru

NOT: financial_engine v2.2'den itibaren spek_score üretir (kalite değil
davranış yoğunluğu). f_score yüksek = riskli/spekülatif yönlüdür.

Yön hizalama:
  f_score : yüksek → riskli   (ters çevrilmez, spek_score zaten bu yönde)
  e_score : yüksek → memnun   (ters çevrilir → r_h = 10 - e_score)

Formül:
  r_h     = 10.0 - e_score                      ← halk risk skoru
  paynotu = 0.65 × f_score + 0.35 × r_h         ← normal

  Duygu ayrışması (f_score > HIGH_SPEK_THRESHOLD ve r_h < LOW_PUBLIC_RISK_THRESHOLD):
  paynotu = 0.90 × f_score + 0.10 × r_h         ← spek yüksek + halk aşırı olumlu

  is_sentiment_divergence: override bayrağı — "hisse spekülatif mi?" değil,
  "spek yüksekken halk anlamlı biçimde ayrışıyor mu?" sorusunu yanıtlar.

Yorum yok durumu:
  Bayesian anchor emotional_score'u 5.0'a çeker.
  e_score None ise 5.0 fallback atanır.
  Ayrı else bloğu yoktur; formül her koşulda aynıdır.

Düşük P = sakin / temiz
Yüksek P = dikkat / anomali / risk
"""

from dataclasses import dataclass
from .financial_engine import SpekResult
from .emotional_engine import EmotionalResult

# Birleşim ağırlıkları
FINANCIAL_WEIGHT             = 0.65
EMOTIONAL_WEIGHT             = 0.35

# Duygu ayrışması override ağırlıkları
DIVERGENCE_FINANCIAL_WEIGHT  = 0.90
DIVERGENCE_EMOTIONAL_WEIGHT  = 0.10

# Override eşikleri — tek yerden ayarlanır
HIGH_SPEK_THRESHOLD          = 7.0   # f_score bu değerin üzerindeyse spek güçlü
LOW_PUBLIC_RISK_THRESHOLD    = 3.0   # r_h bu değerin altındaysa halk aşırı olumlu

# Bayesian anchor nötr değeri — yorum yoksa emotional_score buraya çöker
_BAYESIAN_NEUTRAL = 5.0


@dataclass(frozen=True)
class PayNotuResult:
    ticker: str
    paynotu_score: float
    financial_score: float          # spek_score haritası (geriye uyumluluk)
    emotional_score: float          # ham emotional_score (ters çevrilmemiş)
    emotional_risk: float           # r_h = 10 - emotional_score (yön hizalanmış)
    emotional_grip: float
    grip_intensity: float
    is_sentiment_divergence: bool   # override bayrağı: spek yüksek + halk aşırı olumlu
    has_reviews: bool

    def copyWith(self, **kwargs) -> "PayNotuResult":
        import dataclasses
        return dataclasses.replace(self, **kwargs)


class PayNotuIntegrator:
    """Yeni SpekResult API'sini kullanır, eski PayNotuResult yüzeyini korur."""

    def calculate(
        self,
        financial: SpekResult,
        emotional: EmotionalResult,
    ) -> PayNotuResult:

        # --- Girdi güvenliği: her iki skor da 0–10 aralığına clamp edilir ---
        f_score = max(0.0, min(10.0, financial.spek_score))

        raw_e   = emotional.emotional_score
        e_score = raw_e if raw_e is not None else _BAYESIAN_NEUTRAL
        e_score = max(0.0, min(10.0, e_score))

        has_reviews = emotional.effective_review_count > 0

        # Yön hizalama: halk olumlu skoru → halk risk skoru
        r_h = 10.0 - e_score

        # Duygu ayrışması:
        # Spek güçlü (f yüksek) + halk aşırı olumlu (r_h düşük)
        # → halkın sinyali finansal sinyalden kopmuş → halk ağırlığı kısılır
        is_sentiment_divergence = (
            f_score > HIGH_SPEK_THRESHOLD
            and r_h < LOW_PUBLIC_RISK_THRESHOLD
        )

        if is_sentiment_divergence:
            f_weight = DIVERGENCE_FINANCIAL_WEIGHT
            e_weight = DIVERGENCE_EMOTIONAL_WEIGHT
        else:
            f_weight = FINANCIAL_WEIGHT
            e_weight = EMOTIONAL_WEIGHT

        paynotu = f_weight * f_score + e_weight * r_h

        emotional_grip = round(e_weight * r_h, 4)
        grip_intensity = round(e_weight, 4)

        paynotu = round(max(0.0, min(10.0, paynotu)), 4)

        return PayNotuResult(
            ticker=financial.ticker,
            paynotu_score=paynotu,
            financial_score=f_score,
            emotional_score=e_score,
            emotional_risk=round(r_h, 4),
            emotional_grip=emotional_grip,
            grip_intensity=grip_intensity,
            is_sentiment_divergence=is_sentiment_divergence,
            has_reviews=has_reviews,
        )
