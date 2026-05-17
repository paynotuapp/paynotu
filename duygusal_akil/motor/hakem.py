"""
Hakem Katmanı — Kullanıcı Sinyali Değerlendirici
=================================================
NLP, anomali, fuzzy ve zaman katmanlarından gelen sinyalleri değerlendirir.
Manipülasyon riski, güven skoru ve itibar skoru döndürür.
Final paynotu_skoru topsis_motor tarafından hesaplanır.

Çözülen çatışmalar:
  1. Zaman ağırlığı vs Bayesian → en düşük ağırlık kuralı
  2. Anomali vs Gerçek Olay     → risk seviyesine göre ağırlık düşür
  3. Çoklu ceza çakışması       → kümülatif değil, en yüksek ceza seçilir
"""


# ── ETKİ ÇARPANI ─────────────────────────────────────────────────────────────

def _etki_carpani_hesapla(guven_10: float) -> float:
    """
    Güven skoru (0-10) → yorumun paynotu skoruna etki çarpanı.
    Düşük güvenli kullanıcının yorumu sistemi az etkiler.
    """
    if guven_10 >= 10:
        return 1.00
    elif guven_10 >= 7:
        return 0.90
    elif guven_10 >= 4:
        return 0.50
    else:
        return 0.10


# ── MANİPÜLASYON RİSKİ ────────────────────────────────────────────────────────

def _manipulasyon_riski_belirle(
    anomali_risk: str,
    icerik_risk: int,
    nlp_manipulatif: bool,
) -> str:
    """
    Farklı katmanlardan gelen riskleri birleştirerek final risk seviyesini belirler.
    """
    puan = 0

    if anomali_risk == "yüksek_risk":
        puan += 3
    elif anomali_risk == "şüpheli":
        puan += 2

    if icerik_risk >= 40:
        puan += 3
    elif icerik_risk >= 20:
        puan += 1

    if nlp_manipulatif:
        puan += 2

    if puan >= 4:
        return "Yüksek"
    elif puan >= 2:
        return "Orta"
    else:
        return "Düşük"


# ── FİNAL AĞIRLIK ─────────────────────────────────────────────────────────────

def _agirlik_hesapla(
    fuzzy_guven: float,
    zaman_agirlik: float,
    anomali_var: bool,
    icerik_risk: int,
) -> float:
    """
    Yorumun sisteme olan etkisini hesaplar (0-1).

    Çatışma Kuralı 1: Anomali ve içerik cezaları kümülatif değil;
                      en kötü olanı seçilir.
    Çatışma Kuralı 2: Fuzzy güven ve zaman ağırlığı çarpılır
                      (her ikisi bağımsız faktör, kök alınır).
    """
    anomali_carpan = 0.3 if anomali_var else 1.0

    if icerik_risk >= 40:
        icerik_carpan = 0.1
    elif icerik_risk >= 20:
        icerik_carpan = 0.5
    else:
        icerik_carpan = 1.0

    en_kotu_ceza = min(anomali_carpan, icerik_carpan)

    import math
    guven_zaman = math.sqrt(fuzzy_guven * zaman_agirlik)

    final = guven_zaman * en_kotu_ceza
    return round(max(0.01, min(1.0, final)), 4)


# ── ANA FONKSİYON ─────────────────────────────────────────────────────────────

def hakem_karar(
    nlp: dict,
    anomali: dict,
    fuzzy: dict,
    bayesian: dict,
    zaman: dict,
    icerik: dict,
) -> dict:
    """
    Kullanıcı sinyali katmanlarını değerlendirip manipülasyon riski,
    güven ve itibar skorlarını döndürür.
    Final paynotu_skoru topsis_motor.tam_topsis_hesapla tarafından hesaplanır.

    Dönüş:
      guven_skoru      : 0-10
      itibar_skoru     : 0-10
      etki_carpani     : 0.10 | 0.50 | 0.90 | 1.00
      manipulasyon_riski: Düşük | Orta | Yüksek
      final_agirlik    : 0-1
      aciklama         : str
    """
    manip_riski = _manipulasyon_riski_belirle(
        anomali_risk   =anomali["risk_seviyesi"],
        icerik_risk    =icerik["risk_puani"],
        nlp_manipulatif=nlp["manipulatif_mi"],
    )

    final_agirlik = _agirlik_hesapla(
        fuzzy_guven  =fuzzy["guven_normalized"],
        zaman_agirlik=zaman["agirlik"],
        anomali_var  =anomali["anomali_var"],
        icerik_risk  =icerik["risk_puani"],
    )

    etki_carpani = _etki_carpani_hesapla(fuzzy["guven_skoru"])

    guven_skoru  = round(max(0.0, min(10.0, fuzzy["guven_skoru"] * final_agirlik)), 1)
    itibar_skoru = round(max(0.0, min(10.0,
        bayesian["itibar_skoru"] * final_agirlik * etki_carpani
    )), 2)

    aciklamalar = []
    if zaman["kategori"] == "çok_eski":
        aciklamalar.append("Eski yorum, etkisi azaltıldı")
    if anomali["anomali_var"]:
        aciklamalar.append(f"Anomali: {anomali['aciklama']}")
    if nlp["manipulatif_mi"]:
        aciklamalar.append("Manipülatif içerik işareti var")
    if fuzzy["profil"] == "yeni":
        aciklamalar.append("Yeni kullanıcı, güven düşük")
    if not aciklamalar:
        aciklamalar.append("Normal yorum, standart ağırlıkla işlendi")

    return {
        "guven_skoru":       guven_skoru,
        "itibar_skoru":      itibar_skoru,
        "etki_carpani":      etki_carpani,
        "manipulasyon_riski": manip_riski,
        "final_agirlik":     final_agirlik,
        "aciklama":          " | ".join(aciklamalar),
    }
