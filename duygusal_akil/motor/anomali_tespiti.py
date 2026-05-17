"""
Anomali Tespiti Katmanı (Z-score)
Belirli bir hisse için anormal yorum patlamalarını tespit eder.
Pump/dump hareketlerini, bot saldırılarını yakalar.
"""

import time
from collections import defaultdict

# Basit in-memory cache (production'da Redis kullanılmalı)
# hisse_kodu -> [timestamp listesi]
_yorum_gecmisi: dict = defaultdict(list)

# Z-score eşiği — bu değerin üstü anormal
ANOMALI_ESIGI = 2.5

# Kaç dakikayı izleyeceğiz
PENCERE_DAKIKA = 60


def _ortalama_ve_std(degerler: list) -> tuple:
    """Basit ortalama ve standart sapma hesabı."""
    if len(degerler) < 2:
        return 0, 1
    n = len(degerler)
    ort = sum(degerler) / n
    varyans = sum((x - ort) ** 2 for x in degerler) / n
    std = varyans ** 0.5
    return ort, max(std, 0.001)  # sıfıra bölmeyi önle


def anomali_kontrol(puan: float, hisse_kodu: str, timestamp: int) -> dict:
    """
    Bir hisse için gelen yorumun anomali içerip içermediğini kontrol eder.

    Dönüş:
    - anomali_var: bool
    - z_skoru: float
    - risk_seviyesi: "normal" | "şüpheli" | "yüksek_risk"
    - aciklama: str
    """
    simdi = timestamp if timestamp else int(time.time())
    pencere_baslangic = simdi - (PENCERE_DAKIKA * 60)

    # Eski kayıtları temizle
    _yorum_gecmisi[hisse_kodu] = [
        t for t in _yorum_gecmisi[hisse_kodu]
        if t > pencere_baslangic
    ]

    # Şimdiki penceredeki yorum sayısı
    mevcut_yorumlar = _yorum_gecmisi[hisse_kodu]
    mevcut_sayi = len(mevcut_yorumlar)

    # Son kaydı ekle
    _yorum_gecmisi[hisse_kodu].append(simdi)

    # Yeterli veri yoksa — yeni hisse, anomali sayma
    if mevcut_sayi < 3:
        return {
            "anomali_var": False,
            "z_skoru": 0.0,
            "risk_seviyesi": "normal",
            "aciklama": "Yeterli geçmiş veri yok"
        }

    # Son 24 saati 1 saatlik dilimlere böl
    dilim_sayilari = []
    for i in range(24):
        dilim_bitis = simdi - (i * 3600)
        dilim_baslangic = dilim_bitis - 3600
        sayi = sum(
            1 for t in _yorum_gecmisi[hisse_kodu]
            if dilim_baslangic <= t < dilim_bitis
        )
        dilim_sayilari.append(sayi)

    ort, std = _ortalama_ve_std(dilim_sayilari)
    z_skoru = (mevcut_sayi - ort) / std

    # Risk seviyesi
    if z_skoru >= ANOMALI_ESIGI * 1.5:
        risk = "yüksek_risk"
        aciklama = f"Çok yüksek yorum patlaması tespit edildi (Z={z_skoru:.1f})"
        anomali = True
    elif z_skoru >= ANOMALI_ESIGI:
        risk = "şüpheli"
        aciklama = f"Anormal yorum artışı tespit edildi (Z={z_skoru:.1f})"
        anomali = True
    else:
        risk = "normal"
        aciklama = "Normal yorum akışı"
        anomali = False

    return {
        "anomali_var": anomali,
        "z_skoru": round(z_skoru, 2),
        "risk_seviyesi": risk,
        "aciklama": aciklama
    }
