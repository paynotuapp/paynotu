from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import os

import firebase_admin
from firebase_admin import credentials, firestore as fb_firestore

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from motor.icerik_kalkani     import icerik_kontrol
from motor.denetleme_robotu   import gece_kontrol
from motor.kap_scraper        import finansal_saglik_analiz
from motor.nlp_katmani        import nlp_analiz
from motor.anomali_tespiti    import anomali_kontrol
from motor.fuzzy_motor        import fuzzy_guven_hesapla
from motor.bayesian_motor     import bayesian_itibar_hesapla
from motor.zaman_agirlik      import zaman_agirlikli_skor
from motor.hakem              import hakem_karar

logger = logging.getLogger(__name__)

# ── FİREBASE BAŞLAT ───────────────────────────────────────────────────────────

def _firebase_db():
    if not firebase_admin._apps:
        cred_path = os.getenv(
            "FIREBASE_CREDENTIALS_PATH",
            "../pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json",
        )
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    return fb_firestore.client()

app = FastAPI(
    title="Duygusal Akıl API",
    description="SPK tabanlı manipülasyona dayanıklı hibrit puanlama motoru",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── MODELLer ─────────────────────────────────────────────────────────────────

class IcerikKontrolGirdisi(BaseModel):
    metin: str


class YorumSkorlaGirdisi(BaseModel):
    yorum_metni: str
    puan: float                  # 1-5 yıldız
    kullanici_id: str
    hesap_yas_gun: int
    toplam_yorum_sayisi: int
    yorum_cesitliligi: float     # 0-1 (çeşitli hisselere yorum oranı)
    yorum_timestamp: int         # Unix timestamp (saniye)
    faydali_oy: int
    faydali_olmayan_oy: int
    hisse_kodu: str

# ── ENDPOİNTLER ──────────────────────────────────────────────────────────────

@app.get("/")
def anasayfa():
    return {
        "sistem": "Duygusal Akıl v3",
        "durum":  "aktif",
    }


@app.post("/icerik-kontrol")
def icerik_kontrol_endpoint(girdi: IcerikKontrolGirdisi):
    sonuc = icerik_kontrol(girdi.metin)
    return sonuc


@app.get("/finansal-saglik/{hisse_kodu}")
def finansal_saglik_endpoint(hisse_kodu: str):
    return finansal_saglik_analiz(hisse_kodu)


@app.post("/denetleme-robotu-calistir")
async def denetleme_robotu_calistir():
    """Gece kontrol robotunu çalıştırır."""
    try:
        sonuc = await asyncio.to_thread(gece_kontrol)
        return sonuc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/yorumu-skorla")
def yorumu_skorla(girdi: YorumSkorlaGirdisi):
    """
    Yorum submit edildiğinde çağrılır.
    6 bağımsız katmandan gelen sinyalleri hakem ile birleştirerek
    bu yoruma özgü güven, itibar ve manipülasyon skorunu döndürür.

    Flutter'da soz_hakki_screen onPressed → DuygusalAkilService.yorumuSkorla()
    """
    # ── 1. İÇERİK KONTROLÜ ────────────────────────────────────────────────
    icerik = icerik_kontrol(girdi.yorum_metni)
    if icerik["durum"] == "engellendi":
        raise HTTPException(
            status_code=400,
            detail=f"İçerik engellendi: {icerik['aciklama']}"
        )

    # ── 2. NLP ANALİZİ ────────────────────────────────────────────────────
    nlp = nlp_analiz(girdi.yorum_metni)

    # ── 3. ANOMALİ TESPİTİ ────────────────────────────────────────────────
    anomali = anomali_kontrol(
        puan        =girdi.puan,
        hisse_kodu  =girdi.hisse_kodu,
        timestamp   =girdi.yorum_timestamp,
    )

    # ── 4. FUZZY GÜVEN ────────────────────────────────────────────────────
    fuzzy = fuzzy_guven_hesapla(
        hesap_yas_gun       =girdi.hesap_yas_gun,
        toplam_yorum_sayisi =girdi.toplam_yorum_sayisi,
        yorum_cesitliligi   =girdi.yorum_cesitliligi,
        faydali_oy          =girdi.faydali_oy,
        faydali_olmayan_oy  =girdi.faydali_olmayan_oy,
    )

    # ── 5. BAYESIAN İTİBAR ────────────────────────────────────────────────
    bayesian = bayesian_itibar_hesapla(puan=girdi.puan)

    # ── 6. ZAMAN AĞIRLIĞI ─────────────────────────────────────────────────
    zaman = zaman_agirlikli_skor(girdi.yorum_timestamp)

    # ── 7. HAKEM KARARI ───────────────────────────────────────────────────
    hakem = hakem_karar(
        nlp     =nlp,
        anomali =anomali,
        fuzzy   =fuzzy,
        bayesian=bayesian,
        zaman   =zaman,
        icerik  =icerik,
    )

    # ── 8. PAYNOTU SKORU ──────────────────────────────────────────────────
    # Yorumun 1-5 puanını 0-10'a çevir, hakem ağırlığıyla dampingle
    puan_0_10  = (girdi.puan - 1) / 4 * 10
    final_ağırlık = hakem["final_agirlik"]
    # Nötr (5.0) ile harmanlama: düşük ağırlıklı yorum nötral çekilir
    paynotu    = round(puan_0_10 * final_ağırlık + 5.0 * (1 - final_ağırlık), 2)
    paynotu    = max(0.0, min(10.0, paynotu))

    # Ham skor (makro düzeltme öncesi): sadece puan × zaman ağırlığı
    ham_skor = round(puan_0_10 * zaman["agirlik"], 2)

    # Makro düzeltme katsayısı: anomali veya yüksek risk varsa küçülür
    if hakem["manipulasyon_riski"] == "Yüksek":
        makro_k = 0.4
    elif hakem["manipulasyon_riski"] == "Orta":
        makro_k = 0.7
    else:
        makro_k = 1.0

    return {
        "paynotu":                   paynotu,
        "ham_skor":                  ham_skor,
        "guven_skoru":               hakem["guven_skoru"],
        "itibar_skoru":              hakem["itibar_skoru"],
        "manipulasyon_riski":        hakem["manipulasyon_riski"],
        "duygu_tonu":                nlp["duygu_tonu"],
        "icerik_durumu":             icerik["durum"],
        "zaman_agirlik":             zaman["agirlik"],
        "makro_duzeltme_katsayisi":  makro_k,
        "bilesenler": {
            "fuzzy_guven":   fuzzy["bilesenler"],
            "bayesian":      bayesian["bayesian_anchor"],
            "zscore":        anomali["z_skoru"],
            "nlp_guven":     nlp["duygu_skoru"],
            "final_agirlik": hakem["final_agirlik"],
        },
        "aciklama": hakem["aciklama"],
    }


@app.get("/hisse-ozet/{hisse_kodu}")
def hisse_ozet(hisse_kodu: str):
    return {
        "hisse_kodu": hisse_kodu,
        "genel_guven": 0.0,
        "toplam_yorum": 0,
        "manipulasyon_uyarisi": False,
        "son_guncelleme": 0
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
