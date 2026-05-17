"""
Bayesian İtibar Motoru
======================
Yorumun Bayesian çapalı itibar skorunu hesaplar.
Yeni yorumlar sistemi aniden hareket ettirmez; n arttıkça gerçek veri öne çıkar.

Sabitler:
  C          = 100   (çapa kuvveti — ilk 100 yorum piyasa ortalamasına yakın durur)
  MARKET_MEAN = 3.0  (1-5 ölçekte beklenen piyasa ortalaması)

Formül: bayesian_anchor = (n × avg + C × mean) / (n + C)
"""

BAYESIAN_C   = 100
MARKET_MEAN  = 3.0   # 1-5 ölçekte


def bayesian_itibar_hesapla(
    puan: float,
    hisse_yorumlari: list | None = None,
) -> dict:
    """
    Tek bir yorumun Bayesian çapalı itibar skorunu hesaplar.

    puan             : Bu yorumun puanı (1-5)
    hisse_yorumlari  : Bu hissedeki tüm yorumlar [{puan: x}] (isteğe bağlı)

    Dönüş:
      itibar_skoru    : 0-10 (Bayesian smoothing sonrası normalize)
      bayesian_anchor : 1-5 ölçek değeri
      n_efektif       : Etkili yorum sayısı
    """
    if hisse_yorumlari:
        puanlar = [float(y.get("puan", MARKET_MEAN)) for y in hisse_yorumlari]
        n   = len(puanlar)
        avg = sum(puanlar) / n
    else:
        # Sadece bu tek yorumu kullan
        n   = 1
        avg = float(puan)

    # Bayesian smoothing
    bayesian_anchor = (n * avg + BAYESIAN_C * MARKET_MEAN) / (n + BAYESIAN_C)

    # 1-5 → 0-10
    itibar_0_10  = (bayesian_anchor - 1) / 4 * 10
    itibar_skoru = round(max(0.0, min(10.0, itibar_0_10)), 2)

    return {
        "itibar_skoru":    itibar_skoru,
        "bayesian_anchor": round(bayesian_anchor, 4),
        "n_efektif":       n,
    }
