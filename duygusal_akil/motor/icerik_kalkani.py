"""
İçerik Kalkanı Katmanı
Kullanıcı yazarken gerçek zamanlı çalışır.
Üç katmanlı analiz:
  1. Kural tabanlı  — Türkçe küfür + manipülatif kalıplar
  2. Detoxify       — evrensel toksisite modeli
  3. Hakem          — iki katmandan en kötüsü final karar

Flutter'da onChange her tetiklendiğinde çağrılabilir.
"""

import re
import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# ── KURAL TABLOLARI ────────────────────────────────────────────────────────────

KUFUR_LISTESI = [
    "orospu", "piç", "göt", "sik", "amk", "bok", "oç",
    "salak", "aptal", "gerizekalı", "mal", "dangalak",
    "şerefsiz", "haysiyetsiz", "kahpe", "sürtük"
]

PUMP_KALIPLARI = [
    r"kesin al[ın]?",
    r"fırsat[tı]? kaçırma",
    r"herkese söyle",
    r"yarın uçacak",
    r"guaranteed",
    r"100.*kazanç",
    r"garantili.*kâr",
    r"hemen al",
    r"son fırsat",
]

DUMP_KALIPLARI = [
    r"kesin sat[ın]?",
    r"batar",
    r"çöker",
    r"batacak",
    r"iflas",
    r"dolandırıcı",
    r"kaçın",
    r"hepsi yalan",
]

SPAM_KALIPLARI = [
    r"(.)\1{4,}",
    r"(\b\w+\b)(\s+\1){2,}",
]

# ── DETOXIFY YÜKLEYİCİ ────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _detoxify_modeli():
    """
    Detoxify modelini lazy + önbellekli yükler.
    İlk çağrıda model indirilir/yüklenir; sonrakiler önbellekten gelir.
    Yükleme başarısız olursa None döner — sistem kural tabanlıyla çalışmaya devam eder.
    """
    try:
        from detoxify import Detoxify
        return Detoxify("original")
    except Exception as e:
        logger.warning(f"Detoxify yüklenemedi, sadece kural tabanlı filtre aktif: {e}")
        return None


# ── KATMAN 1: KURAL TABANLI ────────────────────────────────────────────────────

def _kural_tabanlı_kontrol(metin: str) -> dict:
    """
    Türkçe küfür listesi + manipülatif kalıp eşleştirmesi.
    Dönüş: risk_puani (0-100) ve tespitler listesi.
    """
    metin_lower = metin.lower()
    risk_puani = 0
    tespitler = []

    for kelime in KUFUR_LISTESI:
        if kelime in metin_lower:
            risk_puani += 40
            tespitler.append("Uygunsuz içerik tespit edildi")
            break

    for kalip in PUMP_KALIPLARI:
        if re.search(kalip, metin_lower):
            risk_puani += 25
            tespitler.append("Yönlendirici alım ifadesi tespit edildi")
            break

    for kalip in DUMP_KALIPLARI:
        if re.search(kalip, metin_lower):
            risk_puani += 25
            tespitler.append("Yönlendirici satım ifadesi tespit edildi")
            break

    for kalip in SPAM_KALIPLARI:
        if re.search(kalip, metin_lower):
            risk_puani += 15
            tespitler.append("Spam içerik tespit edildi")
            break

    if len(metin.strip()) < 10:
        risk_puani += 10
        tespitler.append("Yorum çok kısa")

    return {"risk_puani": min(risk_puani, 100), "tespitler": tespitler}


# ── KATMAN 2: DETOXIFY ────────────────────────────────────────────────────────

def _detoxify_kontrol(metin: str) -> Optional[dict]:
    """
    Detoxify ile toksisite skoru hesaplar.
    Model yüklü değilse None döner.

    Kullanılan skor: results['toxicity']
      >= 0.7  → engellendi  (risk_puani += 60)
      >= 0.4  → şüpheli    (risk_puani += 30)
      < 0.4   → temiz      (risk_puani += 0)
    """
    model = _detoxify_modeli()
    if model is None:
        return None

    try:
        results = model.predict(metin)
        toxicity = float(results.get("toxicity", 0.0))

        if toxicity >= 0.7:
            return {
                "risk_puani": 60,
                "tespitler": [f"Yüksek toksisite skoru ({toxicity:.2f})"],
                "toxicity": toxicity,
            }
        elif toxicity >= 0.4:
            return {
                "risk_puani": 30,
                "tespitler": [f"Orta toksisite skoru ({toxicity:.2f})"],
                "toxicity": toxicity,
            }
        else:
            return {"risk_puani": 0, "tespitler": [], "toxicity": toxicity}

    except Exception as e:
        logger.warning(f"Detoxify tahmin hatası: {e}")
        return None


# ── KATMAN 3: HAKEM ───────────────────────────────────────────────────────────

def _hakem_karar(kural: dict, detoxify: Optional[dict]) -> dict:
    """
    İki katmanın çıktısını alır, en kötü sonucu final karar olarak seçer.
    Kümülatif değil; bağımsız kararlardan en yüksek risk_puanı kazanır.
    """
    risk_puani = kural["risk_puani"]
    tespitler = list(kural["tespitler"])

    if detoxify is not None:
        if detoxify["risk_puani"] > risk_puani:
            risk_puani = detoxify["risk_puani"]
        tespitler.extend(detoxify["tespitler"])

    if risk_puani >= 40:
        durum = "engellendi"
        aciklama = " | ".join(tespitler) if tespitler else "İçerik politikasına aykırı"
    elif risk_puani >= 20:
        durum = "şüpheli"
        aciklama = " | ".join(tespitler) if tespitler else "Şüpheli içerik"
    else:
        durum = "temiz"
        aciklama = "İçerik uygun"

    return {
        "durum": durum,
        "aciklama": aciklama,
        "risk_puani": min(risk_puani, 100),
    }


# ── ANA FONKSİYON ─────────────────────────────────────────────────────────────

def icerik_kontrol(metin: str) -> dict:
    """
    Metni üç katmandan geçirerek içerik durumunu döner.

    Dönüş:
    - durum:      "temiz" | "şüpheli" | "engellendi"
    - aciklama:   Neden bu karar verildi
    - risk_puani: 0-100
    """
    kural_sonuc = _kural_tabanlı_kontrol(metin)
    detoxify_sonuc = _detoxify_kontrol(metin)
    return _hakem_karar(kural_sonuc, detoxify_sonuc)
