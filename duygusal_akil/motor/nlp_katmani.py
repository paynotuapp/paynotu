"""
Türkçe NLP Katmanı
HuggingFace'den Türkçe BERT modeli kullanır.
Yorumun duygu tonunu analiz eder.
savasy/bert-base-turkish-sentiment-cased modeli
"""

from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
import torch

# Model bir kere yükle, bellekte tut
_model = None
_tokenizer = None
_sentiment_pipeline = None


def _model_yukle():
    """Modeli ilk çağrıda yükler, sonraki çağrılarda cache'den kullanır."""
    global _sentiment_pipeline
    if _sentiment_pipeline is None:
        try:
            _sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model="savasy/bert-base-turkish-sentiment-cased",
                tokenizer="savasy/bert-base-turkish-sentiment-cased",
                device=0 if torch.cuda.is_available() else -1
            )
        except Exception:
            # Model yüklenemezse kural tabanlı fallback
            _sentiment_pipeline = "fallback"
    return _sentiment_pipeline


def _kural_tabanli_analiz(metin: str) -> dict:
    """
    BERT modeli yoksa çalışan basit kural tabanlı analiz.
    Finans argosuna özel Türkçe kelimeler içerir.
    """
    metin_lower = metin.lower()

    pozitif_kelimeler = [
        "güzel", "iyi", "harika", "mükemmel", "kazandı", "artı",
        "yükseldi", "güçlü", "başarılı", "kâr", "temettü", "büyüme",
        "fırsat", "değerli", "helal", "süper", "al", "beğen",
        "olumlu", "umut", "güven", "sağlam", "istikrar"
    ]

    negatif_kelimeler = [
        "kötü", "berbat", "düştü", "zararlı", "batık", "kayıp",
        "zarar", "düşüş", "tehlike", "risk", "endişe", "korkutucu",
        "belirsiz", "zayıf", "başarısız", "sat", "kaçın",
        "olumsuz", "manipülasyon", "şüpheli", "aldatıcı"
    ]

    # Finans argosuna özel
    finans_pozitif = [
        "roket", "uçuş", "dipten döndü", "dip yaptı", "fırsatçı",
        "toparladı", "güçlendi", "hacim arttı"
    ]

    finans_negatif = [
        "yaktı", "ezdi", "dibe vurdu", "eridi", "çöktü",
        "pompa", "manipüle", "oyun var"
    ]

    pozitif_skor = sum(1 for k in pozitif_kelimeler + finans_pozitif if k in metin_lower)
    negatif_skor = sum(1 for k in negatif_kelimeler + finans_negatif if k in metin_lower)

    if pozitif_skor > negatif_skor:
        return {"duygu_tonu": "Pozitif", "guven": 0.7, "yontem": "kural"}
    elif negatif_skor > pozitif_skor:
        return {"duygu_tonu": "Negatif", "guven": 0.7, "yontem": "kural"}
    else:
        return {"duygu_tonu": "Nötr", "guven": 0.5, "yontem": "kural"}


def nlp_analiz(metin: str) -> dict:
    """
    Türkçe yorumu analiz eder.

    Dönüş:
    - duygu_tonu: "Pozitif" | "Negatif" | "Nötr"
    - duygu_skoru: 0-1 (ne kadar emin)
    - manipulatif_mi: bool
    - yontem: "bert" | "kural"
    """
    model = _model_yukle()

    if model == "fallback":
        sonuc = _kural_tabanli_analiz(metin)
    else:
        try:
            tahmin = model(metin[:512])[0]  # BERT max 512 token
            label = tahmin["label"].upper()
            skor = tahmin["score"]

            if "POSITIVE" in label or "POZ" in label or label == "1":
                duygu = "Pozitif"
            elif "NEGATIVE" in label or "NEG" in label or label == "0":
                duygu = "Negatif"
            else:
                duygu = "Nötr"

            sonuc = {"duygu_tonu": duygu, "guven": skor, "yontem": "bert"}
        except Exception:
            sonuc = _kural_tabanli_analiz(metin)

    # Manipülatif kalıp kontrolü (NLP üstüne ekstra)
    manipulatif_kaliplar = [
        "kesin al", "kesin sat", "garantili", "100%", "fırsat kaçırma",
        "herkese söyle", "yarın uçar", "mutlaka al"
    ]
    metin_lower = metin.lower()
    manipulatif_mi = any(k in metin_lower for k in manipulatif_kaliplar)

    return {
        "duygu_tonu": sonuc["duygu_tonu"],
        "duygu_skoru": sonuc["guven"],
        "manipulatif_mi": manipulatif_mi,
        "yontem": sonuc["yontem"]
    }
