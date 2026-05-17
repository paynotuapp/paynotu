"""
KAP Scraper — kap.org.tr finansal veri çekici
Son 3 yıllık bilanço, kâr/zarar, borç/özkaynak, temettü → finansal_saglik_skoru 0-10

Katmanlar:
  1. KAP HTML scraper     — kap.org.tr birincil kaynak
  2. yfinance fallback    — KAP erişilemezse (BIST .IS sufiks)
  3. Nötr skor (0 veri)  — hiç veri yoksa 5.0 döner

Puanlama bileşenleri:
  - kâr_büyümesi   (3 yıl trend)          → 0-30 puan
  - karlılık        (net kâr/gelir oranı)  → 0-25 puan
  - borç_oranı     (D/E ratio)             → 0-25 puan
  - temettü        (ödenme tutarlılığı)    → 0-20 puan
  Toplam 0-100 → 0-10 ölçeğe normalize

Önbellek: 6 saatlik TTL (finansal veriler günlük güncellenir)
"""

import logging
import time
from functools import lru_cache
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── ÖNBELLEK ──────────────────────────────────────────────────────────────────

_CACHE: dict[str, dict] = {}
_TTL = 6 * 3600  # 6 saat

def _cache_al(anahtar: str) -> Optional[dict]:
    if anahtar in _CACHE:
        veri, zaman = _CACHE[anahtar]
        if time.time() - zaman < _TTL:
            return veri
        del _CACHE[anahtar]
    return None

def _cache_koy(anahtar: str, veri: dict) -> None:
    _CACHE[anahtar] = (veri, time.time())

# ── KAP SABİTLER ──────────────────────────────────────────────────────────────

_KAP_BASE = "https://www.kap.org.tr"
_KAP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.kap.org.tr/tr/",
}
_SESSION = requests.Session()
_SESSION.headers.update(_KAP_HEADERS)

# ── NÖTR SONUÇ ────────────────────────────────────────────────────────────────

def _notr_sonuc(hisse_kodu: str, sebep: str) -> dict:
    logger.info(f"[KAP] {hisse_kodu}: nötr skor — {sebep}")
    return {
        "finansal_saglik_skoru": 5.0,
        "bilesenler": {
            "kar_buyumesi": None,
            "karlilik": None,
            "borc_orani": None,
            "temettu": None,
        },
        "veri_kaynagi": "yok",
        "uyari": sebep,
    }

# ── KAP KATMANI ───────────────────────────────────────────────────────────────

def _kap_uye_id_bul(hisse_kodu: str) -> Optional[str]:
    """
    KAP API üzerinden şirket üye ID'sini döner.
    Endpoint: /tr/api/memberCompanyInfoList (GET, JSON array)
    Alan: 'memberCode' BIST koduna eşit olanın 'memberId'si
    """
    try:
        url = f"{_KAP_BASE}/tr/api/memberCompanyInfoList"
        r = _SESSION.get(url, timeout=10)
        if r.status_code != 200:
            logger.debug(f"[KAP] memberCompanyInfoList HTTP {r.status_code}")
            return None
        data = r.json()
        kod = hisse_kodu.upper()
        for item in data:
            if item.get("memberCode", "").upper() == kod:
                return str(item.get("memberId", ""))
        # Bazı şirketler stockCode alanında da listelenir
        for item in data:
            if item.get("stockCode", "").upper() == kod:
                return str(item.get("memberId", ""))
        return None
    except Exception as e:
        logger.debug(f"[KAP] üye ID bulunamadı: {e}")
        return None


def _kap_finansal_ozet(uye_id: str) -> Optional[dict]:
    """
    KAP şirket sayfasından özet finansal tablo verisi çeker.
    Dener: /tr/sirket/{uye_id}/finansal-tablolar
    Bilanço + gelir tablosu HTML table parse eder.
    """
    url = f"{_KAP_BASE}/tr/sirket/{uye_id}/finansal-tablolar"
    try:
        r = _SESSION.get(url, timeout=15)
        if r.status_code != 200:
            logger.debug(f"[KAP] finansal-tablolar HTTP {r.status_code}")
            return None
        soup = BeautifulSoup(r.text, "lxml")
        return _kap_tablolari_parse(soup)
    except Exception as e:
        logger.debug(f"[KAP] finansal-tablolar scrape hatası: {e}")
        return None


def _kap_tablolari_parse(soup: BeautifulSoup) -> Optional[dict]:
    """
    KAP finansal tablo sayfasındaki <table> elementlerini işler.
    Hedef satırlar (Türkçe):
      - Net dönem kârı/zararı
      - Toplam varlıklar
      - Toplam yükümlülükler
      - Özkaynaklar
      - Net satışlar / Gelirler
    """
    tablolar = soup.find_all("table")
    if not tablolar:
        return None

    anahtar_eslesme = {
        "net_kar":    ["net dönem kârı", "net dönem zararı", "dönem net kârı", "dönem net karı"],
        "gelir":      ["net satışlar", "hasılat", "toplam gelirler", "satış gelirleri"],
        "varlik":     ["toplam varlıklar", "varlıklar toplamı"],
        "yukumluluk": ["toplam yükümlülükler", "yükümlülükler toplamı", "toplam borçlar"],
        "ozkaynak":   ["toplam özkaynaklar", "özkaynaklar toplamı", "ana ortaklığa ait özkaynaklar"],
    }

    yillik_veriler: list[dict] = []

    for tablo in tablolar:
        satirlar = tablo.find_all("tr")
        if len(satirlar) < 3:
            continue

        # Başlık satırından yıl bilgisini çıkar
        baslik = satirlar[0]
        baslik_metinleri = [th.get_text(strip=True) for th in baslik.find_all(["th", "td"])]
        yillar = []
        for metin in baslik_metinleri:
            for parca in metin.split("/"):
                parca = parca.strip()
                if parca.isdigit() and 2000 < int(parca) < 2100:
                    yillar.append(int(parca))
                    break

        if not yillar:
            continue

        # Yıl bazlı dict başlat
        while len(yillik_veriler) < len(yillar):
            yillik_veriler.append({})

        for satir in satirlar[1:]:
            hucreler = satir.find_all(["td", "th"])
            if not hucreler:
                continue
            satir_adi = hucreler[0].get_text(strip=True).lower()

            eslesen_alan = None
            for alan, anahtar_kelimeler in anahtar_eslesme.items():
                for anahtar in anahtar_kelimeler:
                    if anahtar in satir_adi:
                        eslesen_alan = alan
                        break
                if eslesen_alan:
                    break

            if not eslesen_alan:
                continue

            degerler = hucreler[1:]
            for i, hucre in enumerate(degerler[:len(yillar)]):
                deger = _sayi_parse(hucre.get_text(strip=True))
                if deger is not None and i < len(yillik_veriler):
                    yillik_veriler[i][eslesen_alan] = deger

    if not yillik_veriler or not any(yillik_veriler):
        return None

    # Yıllara göre eşleştir (en son yıl ilk)
    yil_veri = []
    for i, veri in enumerate(yillik_veriler[:3]):
        yil = yillar[i] if i < len(yillar) else None
        if veri:
            yil_veri.append({"yil": yil, **veri})

    return {"yillik": yil_veri} if yil_veri else None


def _sayi_parse(metin: str) -> Optional[float]:
    """'1.234.567,89' veya '1,234,567.89' formatını float'a çevirir."""
    metin = metin.strip().replace(" ", "").replace("\u00a0", "")
    if not metin or metin in ("-", "—", ""):
        return None
    metin = metin.replace(".", "").replace(",", ".")
    try:
        return float(metin)
    except ValueError:
        return None


def _kap_temettu_gecmisi(uye_id: str) -> list[float]:
    """
    KAP bildirim arşivinden temettü ödemelerini çeker.
    Endpoint: /tr/bildirim-sorgu?memberId={id}&subject=TEMETTÜ
    Son 3 yılda gerçekleşen temettü bildirimi sayısını döner.
    """
    try:
        url = f"{_KAP_BASE}/tr/bildirim-sorgu"
        params = {
            "memberId": uye_id,
            "subject": "TEMETTÜ",
            "pageSize": 20,
        }
        r = _SESSION.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "lxml")
        satirlar = soup.select("table tbody tr")
        temettu_yillari = set()
        for satir in satirlar:
            metin = satir.get_text()
            for yil in range(2022, 2026):
                if str(yil) in metin:
                    temettu_yillari.add(yil)
        return list(temettu_yillari)
    except Exception as e:
        logger.debug(f"[KAP] temettü geçmişi hatası: {e}")
        return []

# yfinance fallback kaldırıldı — şirket bilgisi/finansal veri artık sadece KAP'tan gelir.
# yfinance yalnızca fiyat geçmişi için kullanılır (bkz. backend/motors/financial_engine.py).


def _en_yakin_kolon(kolonlar, hedef):
    """Bilanço kolonlarından hedef tarihe en yakın olanı döner."""
    import pandas as pd
    en_iyi = None
    en_kucuk_fark = float("inf")
    for k in kolonlar:
        try:
            fark = abs((k - hedef).days) if hasattr(k, 'days') else abs(
                (pd.Timestamp(k) - pd.Timestamp(hedef)).days
            )
            if fark < en_kucuk_fark:
                en_kucuk_fark = fark
                en_iyi = k
        except Exception:
            continue
    return en_iyi

# ── PUANLAMA MOTORu ───────────────────────────────────────────────────────────

def _puan_hesapla(yillik: list[dict], temettu_yillari: list) -> dict:
    """
    Finansal verileri alır, 0-100 arası ham puan üretir.

    Bileşenler:
      kar_buyumesi   (0-30): 3 yıl net kâr trendi
      karlilik       (0-25): net kâr marjı
      borc_orani     (0-25): borç/özkaynak oranı (düşük iyi)
      temettu        (0-20): son 3 yılda kaç yıl temettü

    Dönüş: {
      ham_puan: 0-100,
      bilesenler: {kar_buyumesi, karlilik, borc_orani, temettu},
      detay: {...}
    }
    """
    puan_kar_buyumesi = 0.0
    puan_karlilik = 0.0
    puan_borc = 0.0
    puan_temettu = 0.0
    detay = {}

    # ── KÂR BÜYÜMESİ (0-30) ──────────────────────────────────────────────────
    net_karlar = [y.get("net_kar") for y in yillik if y.get("net_kar") is not None]
    detay["net_karlar"] = net_karlar

    if len(net_karlar) >= 2:
        buyumeler = []
        for i in range(len(net_karlar) - 1):
            eski = net_karlar[i + 1]
            yeni = net_karlar[i]
            if eski != 0:
                buyumeler.append((yeni - eski) / abs(eski))
        if buyumeler:
            ort_buyume = sum(buyumeler) / len(buyumeler)
            detay["ort_kar_buyumesi"] = round(ort_buyume * 100, 1)
            # +%30 üzeri büyüme → 30 puan, -%30 altı → 0 puan, doğrusal
            puan_kar_buyumesi = max(0.0, min(30.0, 30.0 * (ort_buyume + 0.30) / 0.60))
            # Zararda ise ek ceza
            if net_karlar[0] < 0:
                puan_kar_buyumesi *= 0.5
                detay["zarar_cezasi"] = True

    # ── KARLILIK (0-25) ───────────────────────────────────────────────────────
    if yillik:
        son_yil = yillik[0]
        net_kar = son_yil.get("net_kar")
        gelir = son_yil.get("gelir")
        if net_kar is not None and gelir and gelir > 0:
            marj = net_kar / gelir
            detay["net_kar_marji"] = round(marj * 100, 1)
            # %20 üzeri marj → tam puan, %0 → 0 puan, doğrusal
            puan_karlilik = max(0.0, min(25.0, 25.0 * marj / 0.20))
        elif net_kar is not None and net_kar < 0:
            puan_karlilik = 0.0
            detay["net_kar_marji"] = None

    # ── BORÇ/ÖZKAYNAK (0-25) ─────────────────────────────────────────────────
    if yillik:
        son_yil = yillik[0]
        yukumluluk = son_yil.get("yukumluluk")
        ozkaynak = son_yil.get("ozkaynak")
        if yukumluluk is not None and ozkaynak and ozkaynak > 0:
            de_ratio = yukumluluk / ozkaynak
            detay["borc_ozkaynak_orani"] = round(de_ratio, 2)
            # D/E < 0.5 → 25 puan, D/E > 3.0 → 0 puan
            if de_ratio <= 0.5:
                puan_borc = 25.0
            elif de_ratio >= 3.0:
                puan_borc = 0.0
            else:
                puan_borc = 25.0 * (3.0 - de_ratio) / 2.5
        elif yukumluluk is None and ozkaynak is not None:
            # Sadece özkaynak var, borç bilinmiyor → orta puan
            puan_borc = 12.5
            detay["borc_ozkaynak_orani"] = None

    # ── TEMETTÜ (0-20) ────────────────────────────────────────────────────────
    temettu_sayisi = len([y for y in temettu_yillari if y >= 2022])
    detay["temettu_yillari"] = temettu_yillari
    # 3 yılda 3 kez → 20, 2 kez → 13, 1 kez → 7, 0 → 0
    puan_temettu = [0.0, 7.0, 13.0, 20.0][min(temettu_sayisi, 3)]

    ham_puan = puan_kar_buyumesi + puan_karlilik + puan_borc + puan_temettu

    return {
        "ham_puan": round(ham_puan, 1),
        "bilesenler": {
            "kar_buyumesi": round(puan_kar_buyumesi, 1),
            "karlilik": round(puan_karlilik, 1),
            "borc_orani": round(puan_borc, 1),
            "temettu": round(puan_temettu, 1),
        },
        "detay": detay,
    }

# ── ANA FONKSİYON ─────────────────────────────────────────────────────────────

def finansal_saglik_analiz(hisse_kodu: str) -> dict:
    """
    BIST hissesi için finansal sağlık skoru üretir.

    Parametre:
      hisse_kodu — BIST kodu (örn: 'THYAO', 'GARAN')

    Dönüş:
      finansal_saglik_skoru: float 0-10
        0-3   → Zayıf finansal yapı
        4-6   → Orta (dikkat gerekli)
        7-8   → Sağlıklı
        9-10  → Çok güçlü finansal yapı

      bilesenler: {
        kar_buyumesi, karlilik, borc_orani, temettu  (0-30/25/25/20)
      }
      veri_kaynagi: 'kap' | 'yfinance' | 'yok'
      detay: {...}
    """
    kod = hisse_kodu.upper().strip()
    onbellek = _cache_al(kod)
    if onbellek:
        return onbellek

    yillik = []
    temettu_yillari: list = []
    veri_kaynagi = "yok"

    # ── KAP birincil ──────────────────────────────────────────────────────────
    uye_id = _kap_uye_id_bul(kod)
    if uye_id:
        kap_veri = _kap_finansal_ozet(uye_id)
        if kap_veri and kap_veri.get("yillik"):
            yillik = kap_veri["yillik"]
            temettu_yillari = _kap_temettu_gecmisi(uye_id)
            veri_kaynagi = "kap"
            logger.info(f"[KAP] {kod}: veri çekildi ({len(yillik)} yıl)")

    # ── veri yok ─────────────────────────────────────────────────────────────
    if not yillik:
        sonuc = _notr_sonuc(kod, "Finansal veri bulunamadı")
        _cache_koy(kod, sonuc)
        return sonuc

    # ── puanlama ─────────────────────────────────────────────────────────────
    puan_sonuc = _puan_hesapla(yillik, temettu_yillari)
    ham_puan = puan_sonuc["ham_puan"]

    # 0-100 → 0-10
    finansal_saglik_skoru = round(ham_puan / 10.0, 1)
    finansal_saglik_skoru = max(0.0, min(10.0, finansal_saglik_skoru))

    # Derece etiketi
    if finansal_saglik_skoru >= 8.5:
        derece = "Çok Güçlü"
    elif finansal_saglik_skoru >= 6.5:
        derece = "Sağlıklı"
    elif finansal_saglik_skoru >= 4.0:
        derece = "Orta"
    else:
        derece = "Zayıf"

    sonuc = {
        "finansal_saglik_skoru": finansal_saglik_skoru,
        "derece": derece,
        "bilesenler": puan_sonuc["bilesenler"],
        "veri_kaynagi": veri_kaynagi,
        "yillik_veri": [
            {
                "yil": y.get("yil"),
                "net_kar": y.get("net_kar"),
                "gelir": y.get("gelir"),
            }
            for y in yillik[:3]
        ],
        "detay": puan_sonuc["detay"],
    }

    _cache_koy(kod, sonuc)
    return sonuc
