"""
PayNotu Entegratör
Görev: Spek motoru (davranış) + Duygusal motor (topluluk) = PayNotu Skoru

NOT: financial_engine v2.2'den itibaren spek_score üretir (kalite değil
davranış yoğunluğu). Bu integratör eski API yüzeyini koruyarak
spek_score'u finansal_skor olarak haritalar — gelecek sürümde anlam
değişikliği için integratör mantığı yeniden tasarlanacak.

Formül:
  Yorum varsa (effective_review_count > 0):
    paynotu_score = (spek_score * 0.65) + (emotional_score * 0.35)
  Yorum yoksa:
    paynotu_score = spek_score * 0.65

Spekülatif durumda (duygusal > 8.0 ve spek < 4.0) yorum varsa:
    paynotu_score = (spek_score * 0.90) + (emotional_score * 0.10)
"""

from dataclasses import dataclass
from .financial_engine import SpekResult
from .emotional_engine import EmotionalResult

FINANCIAL_WEIGHT  = 0.65
EMOTIONAL_WEIGHT  = 0.35
SPECULATIVE_EMOTIONAL_WEIGHT = 0.10


@dataclass(frozen=True)
class PayNotuResult:
    ticker: str
    paynotu_score: float
    financial_score: float    # Geriye uyumluluk: spek_score buradan haritalanır
    emotional_score: float
    emotional_grip: float
    grip_intensity: float
    is_speculative: bool
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

        f_score = financial.spek_score        # YENİ: spek_score
        e_score = emotional.emotional_score
        has_reviews = emotional.effective_review_count > 0

        if has_reviews:
            is_speculative = e_score > 8.0 and f_score < 4.0
            e_weight = SPECULATIVE_EMOTIONAL_WEIGHT if is_speculative else EMOTIONAL_WEIGHT
            f_weight = 1.0 - e_weight
            paynotu = f_weight * f_score + e_weight * e_score
            emotional_grip = round(e_weight * e_score, 4)
            grip_intensity = round(e_weight, 4)
        else:
            is_speculative = False
            paynotu = FINANCIAL_WEIGHT * f_score
            emotional_grip = 0.0
            grip_intensity = 0.0

        paynotu = round(max(0.0, min(10.0, paynotu)), 4)

        return PayNotuResult(
            ticker=financial.ticker,
            paynotu_score=paynotu,
            financial_score=f_score,
            emotional_score=e_score,
            emotional_grip=emotional_grip,
            grip_intensity=grip_intensity,
            is_speculative=is_speculative,
            has_reviews=has_reviews,
        )