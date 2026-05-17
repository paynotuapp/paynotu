"""
Fuzzy Güven Motoru
==================
Kullanıcı hesap metriklerinden fuzzy mantık ile güven skoru hesaplar.
Girdi  : hesap_yas_gun, toplam_yorum_sayisi, yorum_cesitliligi,
         faydali_oy, faydali_olmayan_oy
Çıktı  : guven_skoru (0-10), guven_normalized (0-1), profil ("yeni"|"orta"|"kıdemli")

Bileşen ağırlıkları:
  - Hesap yaşı        → 0-3 puan  (365+ gün = 3)
  - Yorum sayısı      → 0-3 puan  (50+  = 3)
  - Yorum çeşitlilik  → 0-2 puan  (tam çeşitlilik = 2)
  - Faydalılık oranı  → 0-2 puan  (tüm oylar faydalı = 2)
Toplam: 0-10
"""


def fuzzy_guven_hesapla(
    hesap_yas_gun: int,
    toplam_yorum_sayisi: int,
    yorum_cesitliligi: float,   # 0-1 arası
    faydali_oy: int,
    faydali_olmayan_oy: int,
) -> dict:
    """
    Kullanıcı profilinden fuzzy güven skoru hesaplar.

    Dönüş:
      guven_skoru      : 0-10
      guven_normalized : 0-1
      profil           : "yeni" | "orta" | "kıdemli"
      bilesenler       : alt puan detayı
    """

    # ── Hesap yaşı puanı (0-3) ─────────────────────────────────────────────
    if hesap_yas_gun >= 365:
        yas_puan = 3.0
    elif hesap_yas_gun >= 180:
        yas_puan = 2.0
    elif hesap_yas_gun >= 90:
        yas_puan = 1.5
    elif hesap_yas_gun >= 30:
        yas_puan = 0.5
    else:
        yas_puan = 0.0

    # ── Yorum sayısı puanı (0-3) ────────────────────────────────────────────
    if toplam_yorum_sayisi >= 50:
        yorum_puan = 3.0
    elif toplam_yorum_sayisi >= 20:
        yorum_puan = 2.0
    elif toplam_yorum_sayisi >= 10:
        yorum_puan = 1.5
    elif toplam_yorum_sayisi >= 3:
        yorum_puan = 0.5
    else:
        yorum_puan = 0.0

    # ── Yorum çeşitliliği puanı (0-2) ───────────────────────────────────────
    # 0 = hep aynı hisseye yorum, 1 = çok farklı hisseye yorum
    cesitlilik_puan = round(min(2.0, float(yorum_cesitliligi) * 2.0), 4)

    # ── Faydalılık oranı puanı (0-2) ────────────────────────────────────────
    toplam_oy = faydali_oy + faydali_olmayan_oy
    if toplam_oy > 0:
        faydalilik_orani = faydali_oy / toplam_oy
        faydalilik_puan = round(min(2.0, faydalilik_orani * 2.0), 4)
    else:
        faydalilik_puan = 1.0  # Oy yoksa nötr başla

    ham_puan = yas_puan + yorum_puan + cesitlilik_puan + faydalilik_puan
    guven_skoru = round(max(0.0, min(10.0, ham_puan)), 2)
    guven_normalized = round(guven_skoru / 10.0, 4)

    # ── Profil sınıflandırması ───────────────────────────────────────────────
    if guven_skoru >= 7.0:
        profil = "kıdemli"
    elif guven_skoru >= 3.0:
        profil = "orta"
    else:
        profil = "yeni"

    return {
        "guven_skoru":      guven_skoru,
        "guven_normalized": guven_normalized,
        "profil":           profil,
        "bilesenler": {
            "hesap_yasi":  round(yas_puan,          2),
            "yorum_sayisi": round(yorum_puan,        2),
            "cesitlilik":  round(cesitlilik_puan,    2),
            "faydalilik":  round(faydalilik_puan,    2),
        },
    }
