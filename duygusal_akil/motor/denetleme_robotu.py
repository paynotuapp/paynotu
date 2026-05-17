"""
Denetleme Robotu — Gece Çalışan Skor Kalite Kontrolü
=====================================================
Her gece:
  1. Cronbach alfa — iç tutarlılık
  2. Anchor güncelle — dağılıma göre A+/A- yenile
  3. Şişme kontrolü — std < 1.0 uyarısı
  4. Dağılım kontrolü — beklenen yüzde dilimlere uyum
  5. Entropi ağırlıklarını yeniden hesapla → Firestore'a yaz
"""

import logging
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

# Beklenen skor dağılımı
BEKLENEN_DAGILIM = {
    "0-3":  0.10,
    "3-5":  0.20,
    "5-7":  0.40,
    "7-9":  0.20,
    "9-10": 0.10,
}


def _firebase_db():
    import firebase_admin
    from firebase_admin import firestore as fb_firestore
    if not firebase_admin._apps:
        raise RuntimeError("Firebase başlatılmamış")
    return fb_firestore.client()


def cronbach_alpha_hesapla(skorlar: list) -> float:
    """
    Tek boyutlu skor listesi için basitleştirilmiş Cronbach alfa.
    Skor varyansı ile madde varyansları karşılaştırılır.
    < 0.70 → uyarı.
    """
    if len(skorlar) < 10:
        return 1.0
    arr = np.array(skorlar, dtype=float)
    # Tek seri için split-half yöntemi
    n   = len(arr)
    mid = n // 2
    a1  = arr[:mid]
    a2  = arr[mid:mid + len(a1)]
    if len(a1) < 2 or np.std(a1) == 0 or np.std(a2) == 0:
        return 1.0
    r = float(np.corrcoef(a1, a2)[0, 1])
    # Spearman-Brown düzeltmesi
    alpha = (2 * r) / (1 + r)
    return round(float(np.clip(alpha, 0.0, 1.0)), 4)


def anchor_guncelle(skorlar: list) -> dict:
    """
    Mevcut skor dağılımına göre A+ ve A- anchor'larını güncelle.
    %95 → A+ referans, %5 → A- referans.
    Büyük sapma (>0.5) varsa Firestore'a yaz.
    """
    if len(skorlar) < 30:
        return {"guncellendi": False, "aciklama": "Yetersiz veri"}

    arr    = np.array(skorlar, dtype=float)
    p95    = float(np.percentile(arr, 95))
    p05    = float(np.percentile(arr, 5))
    median = float(np.median(arr))

    guncellendi = False
    try:
        db  = _firebase_db()
        doc = db.collection("sistem_config").document("anchor_points").get()
        mevcut = doc.to_dict() if doc.exists else {}
        eski_p95 = float(mevcut.get("a_plus", 9.0))
        eski_p05 = float(mevcut.get("a_minus", 1.0))

        if abs(p95 - eski_p95) > 0.5 or abs(p05 - eski_p05) > 0.5:
            db.collection("sistem_config").document("anchor_points").set({
                "a_plus":           p95,
                "a_minus":          p05,
                "medyan":           median,
                "guncelleme_tarihi": datetime.now().isoformat(),
            })
            guncellendi = True
            logger.info(f"[denetleme] Anchor güncellendi: A+={p95:.2f}, A-={p05:.2f}")
    except Exception as e:
        logger.warning(f"[denetleme] Anchor güncelleme hatası: {e}")

    return {
        "guncellendi": guncellendi,
        "yeni_a_plus":  round(p95, 2),
        "yeni_a_minus": round(p05, 2),
        "medyan":       round(median, 2),
    }


def sisisme_kontrol(skorlar: list) -> dict:
    """Skor standart sapması < 1.0 ise şişme uyarısı."""
    if len(skorlar) < 10:
        return {"sisisme_var": False, "std": None}
    std = float(np.std(skorlar))
    return {
        "sisisme_var": std < 1.0,
        "std":         round(std, 4),
        "uyari":       "Skor dağılımı çok dar — şişme tespit edildi" if std < 1.0 else None,
    }


def dagilim_kontrol(skorlar: list) -> dict:
    """Beklenen yüzde dağılımıyla karşılaştır. >%15 sapma → uyarı."""
    if len(skorlar) < 10:
        return {"dagilim_uygun": True, "sapmalar": {}}

    arr = np.array(skorlar, dtype=float)
    n   = len(arr)

    araliklar = {
        "0-3":  ((arr >= 0)  & (arr < 3)).sum()  / n,
        "3-5":  ((arr >= 3)  & (arr < 5)).sum()  / n,
        "5-7":  ((arr >= 5)  & (arr < 7)).sum()  / n,
        "7-9":  ((arr >= 7)  & (arr < 9)).sum()  / n,
        "9-10": ((arr >= 9)  & (arr <= 10)).sum() / n,
    }

    sapmalar = {}
    dagilim_uygun = True
    for aralik, gercek in araliklar.items():
        beklenen = BEKLENEN_DAGILIM[aralik]
        sapma    = abs(gercek - beklenen)
        sapmalar[aralik] = {
            "gercek":   round(gercek * 100, 1),
            "beklenen": round(beklenen * 100, 1),
            "sapma_pct": round(sapma * 100, 1),
        }
        if sapma > 0.15:
            dagilim_uygun = False

    return {"dagilim_uygun": dagilim_uygun, "sapmalar": sapmalar}


def entropi_agirlik_guncelle() -> dict:
    """
    Firestore'daki tüm hisse finansal metriklerini okuyup
    entropi ağırlıklarını yeniden hesapla, Firestore'a yaz.
    """
    try:
        from motor.finansal_motor import entropi_agirlik_hesapla, VARSAYILAN_AGIRLIKLAR
        db = _firebase_db()

        alan_listesi = [
            "finansal_saglik_skoru", "spekulatif_skor", "gini_fiyat",
            "gini_hacim", "volatilite", "zscore_max", "hacim_spike_max", "entropi_fiyat"
        ]
        # Alan adı → TOPSIS anahtar eşlemesi
        alan_map = {
            "finansal_saglik_skoru": "finansal_saglik",
            "spekulatif_skor":       "spekulatif_skor",
            "gini_fiyat":            "gini_fiyat",
            "gini_hacim":            "gini_hacim",
            "volatilite":            "volatilite",
            "zscore_max":            "zscore_max",
            "hacim_spike_max":       "hacim_spike",
            "entropi_fiyat":         "entropi_fiyat",
        }

        docs = list(db.collection("hisseler").stream())
        tum_metrikler = []
        for doc in docs:
            d = doc.to_dict()
            satir = {}
            for alan, key in alan_map.items():
                v = d.get(alan)
                if v is not None:
                    satir[key] = float(v)
            if len(satir) >= 4:
                tum_metrikler.append(satir)

        if len(tum_metrikler) < 10:
            return {"guncellendi": False, "aciklama": "Yetersiz veri"}

        agirliklar = entropi_agirlik_hesapla(tum_metrikler)
        agirliklar["guncelleme_tarihi"] = datetime.now().isoformat()
        agirliklar["hisse_sayisi"]      = len(tum_metrikler)

        db.collection("sistem_config").document("entropi_agirliklar").set(agirliklar)
        logger.info(f"[denetleme] Entropi ağırlıkları güncellendi: {len(tum_metrikler)} hisse")

        return {"guncellendi": True, "agirliklar": agirliklar, "hisse_sayisi": len(tum_metrikler)}
    except Exception as e:
        logger.error(f"[denetleme] Entropi ağırlık güncelleme hatası: {e}")
        return {"guncellendi": False, "hata": str(e)}


def gece_kontrol() -> dict:
    """Tüm denetleme adımlarını çalıştır, sonuçları Firestore'a yaz."""
    sonuc = {"zaman": datetime.now().isoformat(), "adimlar": {}}

    try:
        db    = _firebase_db()
        docs  = list(db.collection("hisseler").stream())
        taban_puanlar  = [float(d.to_dict().get("taban_puan")  or 0.0) for d in docs if d.to_dict().get("taban_puan")]
        paynotu_skorlar = [float(d.to_dict().get("paynotu_skoru") or 0.0) for d in docs if d.to_dict().get("paynotu_skoru")]
    except Exception as e:
        return {"hata": str(e)}

    # 1. Cronbach alfa
    alpha = cronbach_alpha_hesapla(taban_puanlar)
    cronbach_sonuc = {
        "alpha": alpha,
        "uyari": "İç tutarlılık düşük (<0.70)" if alpha < 0.70 else None,
    }
    sonuc["adimlar"]["cronbach"] = cronbach_sonuc

    # 2. Anchor güncelle
    sonuc["adimlar"]["anchor"] = anchor_guncelle(taban_puanlar)

    # 3. Şişme kontrolü
    sonuc["adimlar"]["sisisme"] = sisisme_kontrol(paynotu_skorlar)

    # 4. Dağılım kontrolü
    sonuc["adimlar"]["dagilim"] = dagilim_kontrol(paynotu_skorlar)

    # 5. Entropi ağırlık güncelle
    sonuc["adimlar"]["entropi_agirlik"] = entropi_agirlik_guncelle()

    # Genel durum
    uyarilar = [v.get("uyari") for v in sonuc["adimlar"].values()
                if isinstance(v, dict) and v.get("uyari")]
    sonuc["uyari_sayisi"] = len(uyarilar)
    sonuc["uyarilar"]     = uyarilar
    sonuc["durum"]        = "sorunlu" if uyarilar else "normal"

    # Firestore'a yaz
    try:
        db.collection("sistem_config").document("gece_kontrol").set(sonuc)
    except Exception as e:
        logger.warning(f"[denetleme] Sonuç yazılamadı: {e}")

    logger.info(f"[denetleme] Gece kontrolü tamamlandı: {sonuc['durum']}")
    return sonuc
