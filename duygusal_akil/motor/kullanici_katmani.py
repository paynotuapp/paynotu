"""
Kullanıcı Katmanı — NPS, Churn, Kullanıcı Skoru
=================================================
yorumu-skorla endpoint'inden çağrılır.
TOPSIS matrisine eklenecek kullanıcı metriklerini normalize eder.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _firebase_db():
    import firebase_admin
    from firebase_admin import firestore as fb_firestore
    if not firebase_admin._apps:
        return None
    return fb_firestore.client()


# ── NPS HESAPLA ───────────────────────────────────────────────────────────────

def nps_hesapla(yorumlar: list) -> float:
    """
    Yorum listesindeki puanları (1-5 ölçek) NPS'e çevirir.
    1-5 → 2-10 dönüşümü (×2), sonra NPS kuralı:
      9-10 → Promoter  (puan 4.5-5)
      7-8  → Passive   (puan 3.5-4)
      0-6  → Detractor (puan < 3.5)
    Döner: 0-10 normalize NPS.
    """
    if not yorumlar:
        return 5.0   # veri yoksa nötr

    promoter   = 0
    passive    = 0
    detractor  = 0

    for y in yorumlar:
        puan = float(y.get("puan", 3)) * 2   # 1-5 → 2-10
        if puan >= 9:
            promoter += 1
        elif puan >= 7:
            passive += 1
        else:
            detractor += 1

    toplam = promoter + passive + detractor
    if toplam == 0:
        return 5.0

    nps_ham = (promoter - detractor) / toplam   # -1 ile +1 arası
    # -1..+1 → 0..10
    nps_norm = (nps_ham + 1) / 2 * 10
    return round(float(nps_norm), 4)


# ── CHURN RATE HESAPLA ────────────────────────────────────────────────────────

def churn_rate_hesapla(kullanici_id: str) -> float:
    """
    Kullanıcı son 30 günde aktif mi?
    Aktif  → churn_risk düşük  (0.1)
    Pasif  → churn_risk yüksek (0.8)
    Döner: 0-1 churn risk.
    """
    try:
        db = _firebase_db()
        if db is None:
            return 0.5

        sinir = datetime.now(timezone.utc) - timedelta(days=30)
        yorumlar = (
            db.collection("yorumlar")
            .where("kullanici_id", "==", kullanici_id)
            .where("timestamp", ">=", sinir)
            .limit(1)
            .stream()
        )
        aktif = any(True for _ in yorumlar)
        return 0.1 if aktif else 0.8

    except Exception as e:
        logger.warning(f"[kullanici_katmani] churn hatası: {e}")
        return 0.5


# ── KULLANICI SKORU HESAPLA ───────────────────────────────────────────────────

def kullanici_skoru_hesapla(
    fuzzy_guven: float,
    nps: float,
    churn_rate: float,
    zaman_agirlik: float,
    soz_hakki: float,
) -> dict:
    """
    Tüm kullanıcı metriklerini TOPSIS için normalize et (0-1 arası).

    fuzzy_guven  : 0-1  (güvenilir kullanıcı)
    nps          : 0-10 (hisseye verilen genel puan trendi)
    churn_rate   : 0-1  (yüksek = pasif kullanıcı, cost kriterden tersine çevrilir)
    zaman_agirlik: 0-1  (yorumun güncelliği)
    soz_hakki    : 0-1  (kullanıcının genel söz hakkı ağırlığı)
    """
    def _norm(v: float, lo: float, hi: float, invert: bool = False) -> float:
        r = hi - lo
        if r == 0:
            return 0.0
        n = (v - lo) / r
        return round(max(0.0, min(1.0, 1.0 - n if invert else n)), 4)

    return {
        "nps":           _norm(nps,           0.0, 10.0),
        "fuzzy_guven":   _norm(fuzzy_guven,   0.0,  1.0),
        "churn_rate":    _norm(churn_rate,    0.0,  1.0, invert=True),
        "zaman_agirlik": _norm(zaman_agirlik, 0.0,  1.0),
        "soz_hakki":     _norm(soz_hakki,     0.0,  1.0),
    }
