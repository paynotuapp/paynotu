"""
Zaman Ağırlıklı Skor Katmanı
Eski yorumların etkisini zamanla azaltır.
Borsada eski bilgi = geçersiz bilgi olabilir.
Steam'in kullandığı yarı-ömür modeli kullanılıyor.

Yarı ömür seçimi — BIST hisseleri görece stabil şirketler olduğundan
30 günlük yarı ömür çok agresif; 1 yıllık yorum neredeyse sıfır ağırlık
alıyordu. Düzeltildi:
  normal : 90 gün  → 1 yıllık yorum ~0.06 ağırlık (anlamlı katkı)
  yavas  : 180 gün → 1 yıllık yorum ~0.25 ağırlık (uzun vadeli sektörler)
"""

import time
import math

# Yarı ömür değerleri (saniye cinsinden)
YARI_OMUR_90_GUN  = 90  * 24 * 3600   # normal mod
YARI_OMUR_180_GUN = 180 * 24 * 3600   # yavaş mod

# Minimum ağırlık — çok eski yorumlar bile tamamen silinmez
MIN_AGIRLIK = 0.05


def zaman_agirlikli_skor(yorum_timestamp: int, mod: str = "normal") -> dict:
    """
    Yorumun zamanına göre ağırlık hesaplar.

    mod:
    - "normal": 90 günlük yarı ömür  (BIST genel)
    - "yavas" : 180 günlük yarı ömür (bankacılık, enerji gibi stabil sektörler)

    Dönüş:
    - agirlik: 0-1 arası (1 = taze, 0.05 = çok eski)
    - gun_farki: kaç gün önce yazılmış
    - kategori: "taze" | "güncel" | "eski" | "çok_eski"
    """
    simdi = int(time.time())
    gecen_sure = simdi - yorum_timestamp

    # Negatif değer koruması (gelecekteki timestamp)
    if gecen_sure < 0:
        gecen_sure = 0

    gun_farki = gecen_sure / (24 * 3600)

    # Yarı ömür seçimi
    yari_omur = YARI_OMUR_90_GUN if mod == "normal" else YARI_OMUR_180_GUN

    # Üstel azalma formülü: w = e^(-λt), λ = ln(2)/T½
    lam = math.log(2) / yari_omur
    agirlik = math.exp(-lam * gecen_sure)

    # Minimum ağırlık — tamamen sıfırlanmasın
    agirlik = max(agirlik, MIN_AGIRLIK)
    agirlik = round(agirlik, 4)

    # Kategori
    if gun_farki <= 7:
        kategori = "taze"
    elif gun_farki <= 30:
        kategori = "güncel"
    elif gun_farki <= 180:
        kategori = "eski"
    else:
        kategori = "çok_eski"

    return {
        "agirlik": agirlik,
        "gun_farki": round(gun_farki, 1),
        "kategori": kategori
    }
