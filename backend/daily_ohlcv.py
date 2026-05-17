"""
daily_ohlcv.py — PayNotu Günlük OHLCV Güncelleme
==================================================
Her gün 16:00 UTC'de çalışır (daily_job içinden çağrılır).
Sadece son 1 günlük veriyi çekip Firestore'a ekler,
1825 günü aşan en eski kaydı siler.

Rolling Window mantığı:
    Yeni gün → ekle
    En eski gün (1825+ gün önce) → sil
    Sonuç: her zaman tam 5 yıllık temiz veri
"""

import logging
import time
from datetime import datetime, timezone, timedelta

import borsapy as bp
import pandas as pd

logger = logging.getLogger(__name__)

ROLLING_WINDOW = 1825   # 5 yıl
TICKER_SLEEP   = 0.3    # Her hisse arasında bekleme


def _fetch_latest_ohlcv(ticker: str) -> dict | None:
    """
    borsapy ile son 5 günlük veri çeker, en son kapanış gününü döndürür.
    5 gün çekmemizin nedeni: hafta sonu/tatil günleri boş dönmesin.
    """
    try:
        t  = bp.Ticker(ticker)
        df = t.history(period="5d")
        if df is None or df.empty:
            return None

        df.index = pd.DatetimeIndex(df.index.date)

        df = df.sort_index()
        son_gun = df.iloc[-1]
        tarih   = df.index[-1]
        tarih_str = str(tarih.date()) if hasattr(tarih, 'date') else str(tarih)[:10]

        return {
            "tarih":  tarih_str,
            "open":   round(float(son_gun["Open"]),   4),
            "high":   round(float(son_gun["High"]),   4),
            "low":    round(float(son_gun["Low"]),     4),
            "close":  round(float(son_gun["Close"]),  4),
            "volume": int(son_gun["Volume"]),
        }

    except Exception as e:
        logger.warning(f"[{ticker}] borsapy hatası: {e}")
        return None


def _get_oldest_date(ticker: str, db) -> str | None:
    """Firestore'daki en eski OHLCV tarihini döndürür."""
    try:
        docs = list(
            db.collection("hisseler")
            .document(ticker)
            .collection("ohlcv")
            .order_by("tarih")
            .limit(1)
            .stream()
        )
        if docs:
            return docs[0].id
        return None
    except Exception:
        return None


def _get_ohlcv_count(ticker: str, db) -> int:
    """Firestore'daki OHLCV kayıt sayısını döndürür."""
    try:
        docs = list(
            db.collection("hisseler")
            .document(ticker)
            .collection("ohlcv")
            .stream()
        )
        return len(docs)
    except Exception:
        return 0


def update_ticker_ohlcv(ticker: str, db) -> dict:
    """
    Tek bir hisse için günlük OHLCV güncelleme yapar.
    
    Döndürür: {
        "durum": "guncellendi" | "zaten_var" | "hata",
        "tarih": str,
        "silinen": str | None
    }
    """
    # 1. Son günlük veriyi çek
    son_gun = _fetch_latest_ohlcv(ticker)
    if son_gun is None:
        return {"durum": "hata", "tarih": None, "silinen": None}

    tarih_str = son_gun["tarih"]
    ohlcv_ref = db.collection("hisseler").document(ticker).collection("ohlcv")

    # 2. Bu gün zaten var mı kontrol et
    mevcut = ohlcv_ref.document(tarih_str).get()
    if mevcut.exists:
        return {"durum": "zaten_var", "tarih": tarih_str, "silinen": None}

    # 3. Yeni günü ekle
    ohlcv_ref.document(tarih_str).set(son_gun)

    # 4. Rolling window — 1825'i aşıyorsa en eskiyi sil
    silinen = None
    kayit_sayisi = _get_ohlcv_count(ticker, db)
    if kayit_sayisi > ROLLING_WINDOW:
        en_eski = _get_oldest_date(ticker, db)
        if en_eski:
            ohlcv_ref.document(en_eski).delete()
            silinen = en_eski
            logger.debug(f"[{ticker}] En eski gün silindi: {en_eski}")

    return {"durum": "guncellendi", "tarih": tarih_str, "silinen": silinen}


def run_daily_ohlcv_update(ticker_list: list, db) -> dict:
    """
    Tüm hisseler için günlük OHLCV güncelleme çalıştırır.
    daily_job içinden çağrılır.
    
    Döndürür: {
        "guncellendi": int,
        "zaten_var": int,
        "hata": int,
    }
    """
    toplam      = len(ticker_list)
    guncellendi = 0
    zaten_var   = 0
    hata        = 0

    logger.info(f"[ohlcv] Günlük güncelleme başladı — {toplam} hisse")

    for i, ticker in enumerate(ticker_list, 1):
        try:
            sonuc = update_ticker_ohlcv(ticker, db)

            if sonuc["durum"] == "guncellendi":
                guncellendi += 1
                silindi_log = f"← {sonuc['silinen']} silindi" if sonuc["silinen"] else ""
                logger.info(
                    f"[{i}/{toplam}] {ticker} → "
                    f"✅ {sonuc['tarih']} eklendi {silindi_log}"
                )
            elif sonuc["durum"] == "zaten_var":
                zaten_var += 1
                logger.debug(f"[{i}/{toplam}] {ticker} → ⏭️ {sonuc['tarih']} zaten var")
            else:
                hata += 1
                logger.warning(f"[{i}/{toplam}] {ticker} → ❌ veri alınamadı")

        except Exception as e:
            hata += 1
            logger.error(f"[{ticker}] Beklenmeyen hata: {e}")

        time.sleep(TICKER_SLEEP)

    logger.info(
        f"[ohlcv] Güncelleme tamamlandı — "
        f"güncellendi:{guncellendi} zaten_var:{zaten_var} hata:{hata}"
    )

    return {
        "guncellendi": guncellendi,
        "zaten_var":   zaten_var,
        "hata":        hata,
    }


def fetch_ohlcv_from_firestore(ticker: str, db) -> pd.DataFrame | None:
    """
    financial_engine.calculate() için Firestore'dan OHLCV okur.
    yfinance'in yerini alır — main.py'de şöyle çağrılır:

        df = fetch_ohlcv_from_firestore(ticker, db)
        if df is None:
            _end   = date.today().strftime("%Y-%m-%d")
            _start = (date.today() - timedelta(days=1825)).strftime("%Y-%m-%d")
            df = bp.Ticker(ticker).history(start=_start, end=_end)  # fallback
    
    Döndürür: yfinance formatıyla uyumlu DataFrame
              kolonlar: Open, High, Low, Close, Volume
              index: DatetimeIndex
    """
    try:
        docs = list(
            db.collection("hisseler")
            .document(ticker)
            .collection("ohlcv")
            .order_by("tarih")
            .stream()
        )

        if not docs:
            return None

        rows = []
        for doc in docs:
            d = doc.to_dict()
            rows.append({
                "Date":   pd.Timestamp(d["tarih"]),
                "Open":   d.get("open",   0.0),
                "High":   d.get("high",   0.0),
                "Low":    d.get("low",    0.0),
                "Close":  d.get("close",  0.0),
                "Volume": d.get("volume", 0),
            })

        df = pd.DataFrame(rows)
        df = df.set_index("Date")
        df.index = pd.DatetimeIndex(df.index)
        df = df.sort_index()

        return df

    except Exception as e:
        logger.error(f"[{ticker}] Firestore OHLCV okuma hatası: {e}")
        return None
