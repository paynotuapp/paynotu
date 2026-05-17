"""
KAP Manipülasyon Scraper & Eşik Hesaplayıcı
============================================
1. KAP arama sayfalarından bildirim ID'lerini toplar
2. Her bildirimi parse eder: ticker, tarih, içerik
3. 3 ay öncesinden bildirimin tarihine kadar label=1 dönem oluşturur
4. yfinance ile teknik metrikler hesaplar
5. /tmp/spk_vakalar.csv  ve  /tmp/spk_esikler.json  yazar

Kullanım:
  python3 motor/spk_scraper.py
"""

import re
import json
import math
import logging
import time
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ── SABİTLER ──────────────────────────────────────────────────────────────────

BASE_URL = "https://kap.org.tr"

# Yıl → bildirim ID aralığı (yılı belirlemek için kullanılır)
ID_ARALIKLARI: dict[str, tuple[int, int]] = {
    "2020": (800000,  900000),
    "2021": (900000,  1000000),
    "2022": (996235,  1100000),
    "2023": (1100000, 1300000),
    "2024": (1300000, 1500000),
    "2025": (1500000, 1580000),
    "2026": (1580000, 1590000),
}

def _id_yil(bid: int) -> str:
    """Bildirim ID'sinden yılı tahmin eder."""
    for yil, (lo, hi) in ID_ARALIKLARI.items():
        if lo <= bid < hi:
            return yil
    return "bilinmiyor"

# URL-encoded arama terimleri ve maksimum sayfa sayısı
# Her terim için sonuç bitene kadar taranır (max_sayfa üst sınır)
ARAMA_TERIMLERI = [
    ("tedbir%20karar%C4%B1",                                    50),
    ("idari%20para%20cezas%C4%B1",                              50),
    ("piyasa%20doland%C4%B1r%C4%B1c%C4%B1l%C4%B1%C4%9F%C4%B1", 20),
    ("piyasa%20bozucu",                                          20),
    ("i%C5%9Flem%20yasa%C4%9F%C4%B1",                           50),
    ("107",                                                      30),
]

# Bildirimin label=1 sayılması için başlık/içerikte geçmesi gereken kelimeler
LABEL_KELIMELER = [
    "manipülasyon",
    "piyasa dolandırıcılığı",
    "piyasa bozucu",
    "pump",
    "işlem yasağı",
    "tedbir kararı",
    "idari para cezası",
    "107/1",
    "sermaye piyasası kurulu tedbir",
    "spt tedbir",
]

# SPK/kurumsal büyük harfler — ticker false positive önleme
YOKSAY = {
    "SPK", "KAP", "BIST", "MKK", "BDDK", "TEFAS", "TTK", "CMB",
    "USD", "EUR", "TRY", "TL", "DKB", "DUY", "ODA", "HZ",
    "DDK", "FR", "SPT", "IST", "BUL", "GBP", "CHF", "JPY",
    "TCMB", "TSPB", "VOB", "SPF", "IAS", "TMS", "GDS",
}

VAKA_CSV  = Path("/tmp/spk_vakalar.csv")
ESIK_JSON = Path("/tmp/spk_esikler.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9",
}


# ── 1. BİLDİRİM ID TOPLAMA ────────────────────────────────────────────────────

def bildirim_id_topla() -> list[int]:
    """
    Tüm arama terimleri için KAP sayfalarını tarar.
    Sonuç kalmayınca veya max_sayfa'ya ulaşınca durur.
    ID'leri yıl aralıklarına göre filtreler: sadece 2020-2026.
    """
    tum_ids: set[int] = set()
    session  = requests.Session()

    yil_sinir_lo = min(lo for lo, _ in ID_ARALIKLARI.values())
    yil_sinir_hi = max(hi for _, hi in ID_ARALIKLARI.values())

    for terim, max_sayfa in ARAMA_TERIMLERI:
        ard_bos = 0  # ardışık boş sayfa sayacı
        for sayfa in range(1, max_sayfa + 1):
            url = f"{BASE_URL}/tr/search/{terim}/{sayfa}"
            try:
                r = session.get(url, headers=HEADERS, timeout=15)
                r.raise_for_status()
                ids_ham = re.findall(r'/Bildirim/(\d{6,})', r.text)
                # Yalnızca 2020-2026 aralığındaki ID'leri al
                ids_filtre = {
                    int(i) for i in ids_ham
                    if yil_sinir_lo <= int(i) < yil_sinir_hi
                }
                yeni = ids_filtre - tum_ids
                tum_ids |= ids_filtre

                if not yeni:
                    ard_bos += 1
                    if ard_bos >= 2:
                        break  # 2 ardışık boş sayfa → bu terim bitti
                else:
                    ard_bos = 0
                    logger.info(
                        f"[ID topla] {terim[:25]} s={sayfa} "
                        f"+{len(yeni)} → toplam={len(tum_ids)}"
                    )
                time.sleep(0.4)
            except Exception as exc:
                logger.warning(f"[ID topla] {url}: {exc}")
                break

    result = sorted(tum_ids, reverse=True)
    logger.info(f"[ID topla] TAMAMLANDI: {len(result)} benzersiz ID")
    return result


# ── 2. BİLDİRİM PARSE ────────────────────────────────────────────────────────

def _send_data_cek(html: str) -> Optional[dict]:
    """
    KAP Next.js sayfasından 'sendData' JSON nesnesini çıkarır.
    Sayfa içindeki __next_f.push payload'larını tarar.
    """
    # sendData içeren script bloklarını ara
    pattern = re.compile(r'"sendData"\s*:\s*(\{.+?"disclosureBody":.+?\})\s*,\s*"notificationDetailMessage"', re.DOTALL)
    m = pattern.search(html)
    if m:
        try:
            raw = m.group(1)
            # disclosureBody array'ini basitçe çıkar — iç içe JSON kırılgın
            # sadece disclosureBasic kısmını al
            basic_m = re.search(r'"disclosureBasic"\s*:\s*(\{[^}]+\})', raw)
            if basic_m:
                return json.loads(basic_m.group(1))
        except (json.JSONDecodeError, Exception):
            pass

    # Alternatif: tüm sayfada disclosureBasic JSON'unu bul
    basic_pattern = re.compile(
        r'"disclosureBasic"\s*:\s*\{([^}]+)\}', re.DOTALL
    )
    for m in basic_pattern.finditer(html):
        try:
            return json.loads("{" + m.group(1) + "}")
        except json.JSONDecodeError:
            continue

    return None


def bildirim_parse(bildirim_id: int) -> Optional[dict]:
    """
    Tek bir KAP bildirimini parse eder.
    Dönüş: {ticker, tarih, baslik, icerik, label} veya None
    """
    url = f"{BASE_URL}/tr/Bildirim/{bildirim_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        logger.warning(f"[parse] {bildirim_id}: {exc}")
        return None

    # ── Ticker — 3 katmanlı çıkarım ──────────────────────────────────────────
    tickerlar: list[str] = []

    # Katman 1: relatedStocks JSON alanı (en güvenilir)
    related_m = re.search(r'"relatedStocks"\s*:\s*"([^"]+)"', html)
    if related_m:
        for t in related_m.group(1).split(","):
            t = t.strip()
            if t and t not in YOKSAY and re.match(r'^[A-Z]{3,5}$', t):
                tickerlar.append(t)

    # Katman 2: [ULAS] köşeli parantezli format
    if not tickerlar:
        brackets = re.findall(r'\[([A-Z]{3,5})\]', html)
        tickerlar = [t for t in brackets if t not in YOKSAY]

    # Katman 3: "İlgili Şirketler" / "Related Companies" bölümünden sonraki 200 karakter
    if not tickerlar:
        for bolum_pat in [
            r'[İI]lgili\s+[Şş]irketler[^<]{0,30}<[^>]+>([^<]{3,60})',
            r'Related\s+Compan[^<]{0,20}<[^>]+>([^<]{3,60})',
            r'gwt-Label[^>]*>\[([A-Z]{3,5})\]',
        ]:
            m = re.search(bolum_pat, html)
            if m:
                candidates = re.findall(r'[A-Z]{3,5}', m.group(1))
                tickerlar = [t for t in candidates if t not in YOKSAY]
                if tickerlar:
                    break

    tickerlar = list(dict.fromkeys(tickerlar))  # duplicate temizle, sıra koru
    if not tickerlar:
        return None

    # ── Tarih ──
    tarih = None
    tarih_m = re.search(r'"publishDate"\s*:\s*"(\d{4}\.\d{2}\.\d{2})', html)
    if tarih_m:
        try:
            tarih = datetime.strptime(tarih_m.group(1), "%Y.%m.%d")
        except ValueError:
            pass

    if tarih is None:
        # GG.AA.YYYY formatında da dene
        tarihler = re.findall(r'\b(\d{2}\.\d{2}\.\d{4})\b', html)
        for t_str in tarihler:
            try:
                tarih = datetime.strptime(t_str, "%d.%m.%Y")
                break
            except ValueError:
                continue

    if tarih is None:
        return None

    # ── Başlık ve içerik ──
    baslik_m = re.search(r'"title"\s*:\s*"([^"]+)"', html)
    baslik = baslik_m.group(1) if baslik_m else ""

    # Sayfa metninden Türkçe karakterleri koru
    metin_lower = html.lower()

    # label=1: başlıkta veya içerikte manipülasyon kelimesi geçiyor mu?
    label = 0
    for kw in LABEL_KELIMELER:
        if kw.lower() in metin_lower or kw.lower() in baslik.lower():
            label = 1
            break

    return {
        "bildirim_id": bildirim_id,
        "yil":         _id_yil(bildirim_id),
        "tickerlar":   tickerlar,
        "tarih":       tarih,
        "baslik":      baslik,
        "label":       label,
    }


# ── 3. VAKA OLUŞTUR ───────────────────────────────────────────────────────────

def vaka_olustur(bildirimler: list[dict]) -> list[dict]:
    """
    Her bildirimden (label=1) bir manipülasyon vakası oluşturur.
    Dönem: bildirimin 3 ay öncesinden bildirimin tarihine kadar.
    Her vaka için aynı hissenin 3 ay öncesini label=0 olarak ekler.
    """
    vakalar: list[dict] = []

    for b in bildirimler:
        if b["label"] != 1:
            continue

        bitis_dt = b["tarih"]
        bas_dt   = bitis_dt - timedelta(days=90)  # 3 ay önce

        for ticker in b["tickerlar"]:
            # Manipülasyon vakası
            vakalar.append({
                "ticker":           ticker,
                "baslangic_tarihi": bas_dt.strftime("%Y-%m-%d"),
                "bitis_tarihi":     bitis_dt.strftime("%Y-%m-%d"),
                "label":            1,
                "bildirim_id":      b["bildirim_id"],
                "yil":              b.get("yil", ""),
            })
            # Normal dönem: 3 ay öncesinin 3 ayı (buffer: 2 hafta)
            normal_bit = bas_dt - timedelta(days=14)
            normal_bas = normal_bit - timedelta(days=90)
            vakalar.append({
                "ticker":           ticker,
                "baslangic_tarihi": normal_bas.strftime("%Y-%m-%d"),
                "bitis_tarihi":     normal_bit.strftime("%Y-%m-%d"),
                "label":            0,
                "bildirim_id":      b["bildirim_id"],
                "yil":              b.get("yil", ""),
            })

    return vakalar


# ── 4. CSV KAYDET ─────────────────────────────────────────────────────────────

def csv_kaydet(vakalar: list[dict]) -> None:
    if not vakalar:
        logger.warning("Kaydedilecek vaka yok.")
        return
    alanlar = ["ticker", "baslangic_tarihi", "bitis_tarihi", "label", "bildirim_id", "yil"]
    with open(VAKA_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=alanlar)
        writer.writeheader()
        for v in vakalar:
            writer.writerow({k: v.get(k, "") for k in alanlar})
    logger.info(f"CSV kaydedildi: {VAKA_CSV}  ({len(vakalar)} satır)")


# ── 5. TEKNİK METRİK HESAPLA ─────────────────────────────────────────────────

def metrik_hesapla(vakalar: list[dict]) -> list[dict]:
    """
    Her vaka için yfinance'den veri çeker ve teknik metrikler hesaplar.
    """
    import yfinance as yf
    import pandas as pd
    try:
        from ta.momentum import RSIIndicator
    except ImportError:
        logger.error("ta kütüphanesi kurulu değil: pip install ta")
        return []

    satırlar: list[dict] = []

    for i, vaka in enumerate(vakalar):
        ticker  = vaka["ticker"]
        sembol  = ticker + ".IS"
        label   = vaka["label"]
        bas_str = vaka["baslangic_tarihi"]
        bit_str = vaka["bitis_tarihi"]

        try:
            bas_dt  = datetime.strptime(bas_str, "%Y-%m-%d")
            bit_dt  = datetime.strptime(bit_str, "%Y-%m-%d")
            # Gösterge ısınması için 60 gün önce başla
            cek_bas = (bas_dt - timedelta(days=60)).strftime("%Y-%m-%d")
        except ValueError:
            continue

        try:
            df = yf.Ticker(sembol).history(
                start=cek_bas, end=bit_str, interval="1d"
            )
            if df.empty or len(df) < 10:
                logger.warning(f"[metrik] {sembol}: veri yok ({bas_str}–{bit_str})")
                continue

            close  = df["Close"]
            volume = df["Volume"]
            open_  = df["Open"]
            returns = close.pct_change()

            rsi          = RSIIndicator(close, window=14).rsi()
            volume_spike = volume / volume.rolling(20).mean()
            volatilite   = returns.rolling(14).std() * math.sqrt(252)
            z_score      = (close - close.rolling(20).mean()) / close.rolling(20).std()
            momentum     = close / close.shift(5)
            gunluk_deg   = returns * 100

            # Ardışık yükseliş serisi
            up = (close > close.shift(1)).astype(int)
            streak = up.copy().astype(float)
            for j in range(1, len(up)):
                streak.iloc[j] = streak.iloc[j - 1] + 1 if up.iloc[j] == 1 else 0

            # Balina tuzağı: açılışta +%9, kapanışta -%9
            balik_tuzagi = (
                ((close - open_) / open_ * 100 <= -9) &
                ((open_ - close.shift(1)) / close.shift(1) * 100 >= 9)
            ).astype(int)

            # Vaka dönemine kırp
            tz = df.index.tz
            donem = df.loc[
                (df.index >= pd.Timestamp(bas_str, tz=tz)) &
                (df.index <= pd.Timestamp(bit_str,  tz=tz))
            ]
            if donem.empty:
                continue

            for tarih in donem.index:
                def _f(ser, t):
                    try:
                        v = ser.get(t)
                        return float("nan") if v is None else float(v)
                    except Exception:
                        return float("nan")

                satırlar.append({
                    "ticker":         ticker,
                    "tarih":          tarih.strftime("%Y-%m-%d"),
                    "label":          label,
                    "gunluk_degisim": round(_f(gunluk_deg,   tarih), 4),
                    "rsi":            round(_f(rsi,          tarih), 2),
                    "volume_spike":   round(_f(volume_spike, tarih), 4),
                    "volatilite":     round(_f(volatilite,   tarih), 4),
                    "z_score":        round(_f(z_score,      tarih), 4),
                    "momentum":       round(_f(momentum,     tarih), 4),
                    "streak":         int(_f(streak,         tarih) or 0),
                    "balik_tuzagi":   int(_f(balik_tuzagi,   tarih) or 0),
                })

            logger.info(
                f"[metrik] {i+1}/{len(vakalar)} {sembol} "
                f"label={label} {bas_str}→{bit_str} ({len(donem)} gün)"
            )
            time.sleep(0.3)

        except Exception as exc:
            logger.warning(f"[metrik] {sembol} hata: {exc}")

    return satırlar


# ── 6. EŞİK HESAPLA ───────────────────────────────────────────────────────────

def esik_hesapla(satırlar: list[dict]) -> dict:
    """Manipülasyon dönemlerinin (label=1) 75. yüzdelik eşiklerini üretir."""
    manip = [s for s in satırlar if s["label"] == 1]

    if not manip:
        logger.warning("Eşik hesaplanamadı: manipülasyon verisi yok.")
        return {}

    def q75(vals: list) -> float:
        temiz = sorted(v for v in vals if v == v and v is not None)
        if not temiz:
            return 0.0
        return round(temiz[min(int(len(temiz) * 0.75), len(temiz) - 1)], 4)

    esikler = {
        "rsi_75":            q75([s["rsi"]            for s in manip]),
        "volume_spike_75":   q75([s["volume_spike"]   for s in manip]),
        "volatilite_75":     q75([s["volatilite"]     for s in manip]),
        "zscore_75":         q75([s["z_score"]        for s in manip]),
        "streak_75":         q75([s["streak"]         for s in manip]),
        "gunluk_degisim_75": q75([s["gunluk_degisim"] for s in manip]),
        "balik_tuzagi_oran": round(sum(s["balik_tuzagi"] for s in manip) / len(manip), 4),
        "manip_gun_sayisi":  len(manip),
        "normal_gun_sayisi": len([s for s in satırlar if s["label"] == 0]),
        "hesap_tarihi":      datetime.now().strftime("%Y-%m-%d"),
    }

    with open(ESIK_JSON, "w", encoding="utf-8") as f:
        json.dump(esikler, f, ensure_ascii=False, indent=2)

    logger.info(f"Eşikler: {json.dumps(esikler, ensure_ascii=False)}")
    return esikler


# ── 7. ANA PIPELINE ───────────────────────────────────────────────────────────

def pipeline_calistir(ilerleme_cb=None) -> dict:
    def _log(adim, mesaj):
        logger.info(f"[{adim}] {mesaj}")
        if ilerleme_cb:
            ilerleme_cb(adim, mesaj)

    # 1. ID topla
    _log("ID_TOPLA", "KAP arama sayfaları taranıyor...")
    ids = bildirim_id_topla()
    _log("ID_TOPLA", f"{len(ids)} bildirim ID'si bulundu")

    # 2. Her bildirimi parse et
    _log("PARSE", f"{len(ids)} bildirim parse ediliyor...")
    bildirimler: list[dict] = []
    for i, bid in enumerate(ids):
        sonuc = bildirim_parse(bid)
        if sonuc:
            bildirimler.append(sonuc)
            if sonuc["label"] == 1:
                _log("PARSE", f"  ✓ {bid} → {sonuc['tickerlar']} | {sonuc['tarih'].date()} | {sonuc['baslik'][:50]}")
        if (i + 1) % 10 == 0:
            _log("PARSE", f"  {i+1}/{len(ids)} işlendi, {len(bildirimler)} geçerli")
        time.sleep(0.3)

    label1 = [b for b in bildirimler if b["label"] == 1]
    _log("PARSE", f"Tamamlandı: {len(bildirimler)} geçerli bildirim, {len(label1)} manipülasyon")

    # 3. Vaka oluştur
    vakalar = vaka_olustur(bildirimler)
    _log("VAKA", f"{len(vakalar)} vaka satırı oluşturuldu "
         f"({len([v for v in vakalar if v['label']==1])} manip + "
         f"{len([v for v in vakalar if v['label']==0])} normal)")

    # 4. CSV kaydet
    csv_kaydet(vakalar)

    # 5. Teknik metrikler
    _log("METRIK", "yfinance'den veri çekiliyor...")
    satırlar = metrik_hesapla(vakalar)
    _log("METRIK", f"{len(satırlar)} günlük satır hesaplandı")

    # 6. Eşikler
    esikler: dict = {}
    if satırlar:
        esikler = esik_hesapla(satırlar)
        _log("ESIK", "Eşikler hesaplandı ve kaydedildi")
    else:
        _log("ESIK", "Metrik verisi yok — eşik hesaplanamadı")

    return {
        "bildirim_sayisi":  len(ids),
        "gecerli_bildirim": len(bildirimler),
        "manip_bildirim":   len(label1),
        "toplam_vaka":      len(vakalar),
        "metrik_satir":     len(satırlar),
        "esikler":          esikler,
        "csv_yolu":         str(VAKA_CSV),
        "esik_yolu":        str(ESIK_JSON),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("KAP Manipülasyon Scraper")
    print("=" * 60)

    sonuc = pipeline_calistir()

    print("\n── SONUÇ ──────────────────────────────────")
    print(f"Bildirim ID      : {sonuc['bildirim_sayisi']}")
    print(f"Geçerli bildirim : {sonuc['gecerli_bildirim']}")
    print(f"Manipülasyon     : {sonuc['manip_bildirim']}")
    print(f"Toplam vaka      : {sonuc['toplam_vaka']}")
    print(f"Metrik satır     : {sonuc['metrik_satir']}")
    if sonuc["esikler"]:
        print("\n── EŞİKLER ────────────────────────────────")
        for k, v in sonuc["esikler"].items():
            print(f"  {k:30s}: {v}")
    print(f"\nCSV  : {sonuc['csv_yolu']}")
    print(f"JSON : {sonuc['esik_yolu']}")
