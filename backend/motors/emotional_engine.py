"""
Duygusal Motor — PayNotu
Görev: Ham yorum verisini manipülasyondan arındırılmış bir itibar skoruna dönüştürmek.
Bu sınıf finansal motordan TAMAMEN bağımsızdır.
Dışarıya sadece tek bir şey verir: emotional_score (0.0 - 10.0)

4 Ana Hücre:
1. Giriş ve Arıtma (Bayesian + Time Decay)
2. Kullanıcı Güven (User Authority + Churn Check)
3. Duygu ve Mantık (Fuzzy Confidence)
4. Çıkış ve Koruma (Damping + Gini + Mahalanobis)
"""

import json
import os
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Kalibrasyon config yükle ──────────────────────────────────────────────────

_config_path = os.path.join(os.path.dirname(__file__), "../../motor_config.json")
if os.path.exists(_config_path):
    with open(_config_path) as _f:
        _cfg = json.load(_f)
    _MAHALANOBIS_THRESHOLD = _cfg.get("mahalanobis_threshold", 3.0)
    _GINI_THRESHOLD = _cfg.get("gini_threshold", 0.7)
else:
    _MAHALANOBIS_THRESHOLD = 3.0
    _GINI_THRESHOLD = 0.7


@dataclass
class Review:
    user_id: str
    star: float               # 1-5 arası yıldız
    timestamp: datetime
    user_reputation: float    # 0.5 (yeni) - 1.5 (kıdemli)
    is_churned: bool          # Uygulamayı terk etmiş mi?
    text_sentiment: float     # NLP sonucu: -1.0 ile +1.0 arası
    nps_score: Optional[int]  # 0-10 arası NPS (opsiyonel)
    position: str             # "AL", "SAT", "TUT"


@dataclass
class EmotionalResult:
    ticker: str
    emotional_score: float      # Ana çıktı: 0.0 - 10.0
    raw_score: float            # Damping öncesi ham skor
    bayesian_anchor: float      # Bayesian çapa değeri
    gini_coefficient: float     # Puan yoğunlaşması
    anomaly_detected: bool      # Mahalanobis anomali var mı?
    review_count: int
    effective_review_count: float  # Churn + ağırlık sonrası efektif yorum sayısı


class EmotionalEngine:
    """
    Duygusal Motor — 4 hücreli mimari.

    Önemli sabitler:
    - BAYESIAN_ANCHOR = 500 (çapa gücü — manip. direnci)
    - MARKET_MEAN = 2.5 (sistem ortalaması, 1-5 skala)
    - TIME_DECAY_MONTHLY = 0.10 (aylık %10 erime)
    - DAMPING_MAX_DAILY_CHANGE = 0.20 (günlük max %20 değişim)
    - MAHALANOBIS_THRESHOLD = kalibrasyon config'den (varsayılan 3.0)
    """

    BAYESIAN_ANCHOR = 500
    MARKET_MEAN = 3.0
    TIME_DECAY_MONTHLY = 0.10
    DAMPING_MAX_DAILY_CHANGE = 0.20
    MAHALANOBIS_THRESHOLD = _MAHALANOBIS_THRESHOLD

    def __init__(self):
        self._previous_score: dict[str, float] = {}  # ticker -> son skor (damping için)

    def calculate(self, ticker: str, reviews: list[Review]) -> EmotionalResult:
        """Ana hesaplama metodu."""

        if not reviews:
            return EmotionalResult(
                ticker=ticker,
                emotional_score=self.MARKET_MEAN * 2,  # 0-10 skalada 6.0
                raw_score=self.MARKET_MEAN * 2,
                bayesian_anchor=self.MARKET_MEAN * 2,
                gini_coefficient=0.0,
                anomaly_detected=False,
                review_count=0,
                effective_review_count=0.0
            )

        # HÜCRE 1: Giriş ve Arıtma
        filtered_reviews = self._churn_filter(reviews)
        time_weights = self._time_decay_weights(filtered_reviews)
        authority_weights = self._user_authority_weights(filtered_reviews)
        combined_weights = time_weights * authority_weights
        combined_weights /= combined_weights.sum() + 1e-10

        # HÜCRE 2: Fuzzy Confidence (çelişki analizi)
        fuzzy_weights = self._fuzzy_confidence(filtered_reviews)
        final_weights = combined_weights * fuzzy_weights
        final_weights /= final_weights.sum() + 1e-10

        # Ağırlıklı ham skor (1-5 skalada)
        stars = np.array([r.star for r in filtered_reviews])
        weighted_star_avg = float(np.sum(stars * final_weights))

        # HÜCRE 3: Bayesian Stabilizer
        n_effective = float(np.sum(final_weights) * len(filtered_reviews))
        bayesian_score = self._bayesian_stabilize(weighted_star_avg, n_effective)

        # 1-5 skaladan 0-10'a çevir
        score_0_10 = (bayesian_score - 1) / 4 * 10

        # HÜCRE 4: Anomali Kontrolü
        gini = self._gini_coefficient(filtered_reviews, final_weights)
        if gini > _GINI_THRESHOLD:
            # Yoğunlaşma var — skoru ortaya çek
            score_0_10 = score_0_10 * 0.6 + 5.0 * 0.4

        anomaly = self._mahalanobis_check(filtered_reviews, final_weights)
        if anomaly:
            # Anomali var — skoru nötre çek
            score_0_10 = score_0_10 * 0.5 + 5.0 * 0.5

        # Damping: Ani sıçramayı zamana yay
        score_0_10 = self._apply_damping(ticker, score_0_10)

        return EmotionalResult(
            ticker=ticker,
            emotional_score=round(float(np.clip(score_0_10, 0.0, 10.0)), 4),
            raw_score=round((bayesian_score - 1) / 4 * 10, 4),
            bayesian_anchor=round(bayesian_score, 4),
            gini_coefficient=round(gini, 4),
            anomaly_detected=anomaly,
            review_count=len(reviews),
            effective_review_count=round(n_effective, 1)
        )

    # --- HÜCRE 1A: Churn Filtresi ---
    def _churn_filter(self, reviews: list[Review]) -> list[Review]:
        """
        Uygulamayı terk etmiş kullanıcıların yorumlarını listede bırak
        ama ağırlıklarını sonraki adımda minimize et.
        (Burada sadece tamamen sil — reputation weight'te de 0.1 kat alır)
        """
        return [r for r in reviews if not r.is_churned]

    # --- HÜCRE 1B: Time Decay ---
    def _time_decay_weights(self, reviews: list[Review]) -> np.ndarray:
        """
        Aylık %10 erime: w = (0.90)^(ay_sayisi)
        2 yıl önceki yorum neredeyse sıfır etkiye düşer.
        """
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc)
        weights = []
        for r in reviews:
            ts = r.timestamp
            # offset-naive timestamp'i UTC'ye çevir (Firestore'dan gelen eski kayıtlar)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz.utc)
            days_old = (now - ts).days
            months_old = days_old / 30.0
            w = (1 - self.TIME_DECAY_MONTHLY) ** months_old
            weights.append(max(w, 1e-6))
        return np.array(weights)

    # --- HÜCRE 2: User Authority ---
    def _user_authority_weights(self, reviews: list[Review]) -> np.ndarray:
        """
        Kullanıcı reputasyonuna göre çarpan:
        - Yeni kullanıcı: 0.5
        - Orta: 1.0
        - Kıdemli + isabetli: 1.5
        Bu değer zaten Review.user_reputation'da geliyor.
        """
        return np.array([r.user_reputation for r in reviews])

    # --- HÜCRE 3: Fuzzy Confidence ---
    def _fuzzy_confidence(self, reviews: list[Review]) -> np.ndarray:
        """
        Yıldız ile metin/seçenek arasındaki çelişkiyi tespit et.
        Örnek çelişki: 5 yıldız + negatif sentiment → ağırlığı 0.3'e indir.
        Örnek uyum: 5 yıldız + pozitif sentiment → ağırlık 1.0.
        """
        weights = []
        for r in reviews:
            star_normalized = (r.star - 1) / 4  # 0-1
            sentiment_normalized = (r.text_sentiment + 1) / 2  # 0-1

            conflict = abs(star_normalized - sentiment_normalized)

            if conflict > 0.6:
                w = 0.3  # Yüksek çelişki — şüpheli
            elif conflict > 0.3:
                w = 0.7  # Orta çelişki
            else:
                w = 1.0  # Uyumlu
            weights.append(w)
        return np.array(weights)

    # --- HÜCRE 1C: Bayesian Stabilizer ---
    def _bayesian_stabilize(self, weighted_avg: float, n_effective: float) -> float:
        """
        Bayesian Anchor: İlk yorumlarda puan sistem ortalamasında kalır.
        n arttıkça çapanın etkisi azalır, asıl veri öne çıkar.

        Formül: score = (n * avg + C * mean) / (n + C)
        C = BAYESIAN_ANCHOR (500)
        """
        C = self.BAYESIAN_ANCHOR
        return (n_effective * weighted_avg + C * self.MARKET_MEAN) / (n_effective + C)

    # --- HÜCRE 4A: Gini Yoğunlaşma ---
    def _gini_coefficient(self, reviews: list[Review], weights: np.ndarray) -> float:
        """
        Puanlar dar bir kullanıcı grubundan mı geliyor?
        Yüksek Gini = yoğunlaşma = manipülasyon riski.
        """
        if len(reviews) < 3:
            return 0.0

        stars = np.array([r.star for r in reviews])
        weighted_stars = stars * weights
        sorted_vals = np.sort(weighted_stars)
        n = len(sorted_vals)
        cumsum = np.cumsum(sorted_vals)
        gini = (2 * np.sum(np.arange(1, n+1) * sorted_vals) - (n+1) * cumsum[-1]) / (n * cumsum[-1] + 1e-10)
        return float(np.clip(gini, 0, 1))

    # --- HÜCRE 4B: Mahalanobis Anomali ---
    def _mahalanobis_check(self, reviews: list[Review], weights: np.ndarray) -> bool:
        """
        Puanlar normal dağılımdan ne kadar sapıyor?
        Eşik: kalibrasyon config'den (varsayılan 3.0)
        """
        if len(reviews) < 5:
            return False

        stars = np.array([r.star for r in reviews])
        mean = np.average(stars, weights=weights)
        std = np.sqrt(np.average((stars - mean)**2, weights=weights))

        if std < 1e-6:
            return False

        z_scores = np.abs((stars - mean) / std)
        max_z = float(z_scores.max())

        return max_z > self.MAHALANOBIS_THRESHOLD

    # --- HÜCRE 4C: Damping Factor ---
    def _apply_damping(self, ticker: str, new_score: float) -> float:
        """
        Günlük max %20 değişime izin ver.
        Ani sıçramaları zamana yay — devre kesici.
        """
        if ticker not in self._previous_score:
            self._previous_score[ticker] = new_score
            return new_score

        prev = self._previous_score[ticker]
        max_change = prev * self.DAMPING_MAX_DAILY_CHANGE
        damped = float(np.clip(new_score, prev - max_change, prev + max_change))
        self._previous_score[ticker] = damped
        return damped
