"""
init_ohlcv.py — PayNotu İlk Kurulum Scripti
============================================
Bir kere çalıştırılır. 635 hissenin 5 yıllık OHLCV verisini
Firestore'a yazar.

Çalıştırma:
    python init_ohlcv.py

Firestore yapısı:
    hisseler/{ticker}/ohlcv/{tarih}
        open, high, low, close, volume
"""

import os
import time
import logging
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore as fb_firestore
import borsapy as bp
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Firebase ──────────────────────────────────────────────────────────────────

def _firebase_db():
    if not firebase_admin._apps:
        cred_path = os.path.join(
            os.path.dirname(__file__),
            "pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json",
        )
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    return fb_firestore.client()

# ── Sabitler ──────────────────────────────────────────────────────────────────

ROLLING_WINDOW = 1825   # 5 yıl (gün)
BATCH_SIZE     = 400    # Firestore batch limiti
TICKER_SLEEP   = 0.5    # Her hisse arasında bekleme (saniye)
BATCH_SLEEP    = 2.0    # Her 10 hissede bekleme

# ── OHLCV Çekme ───────────────────────────────────────────────────────────────

def _fetch_ohlcv(ticker: str) -> pd.DataFrame | None:
    """
    borsapy ile 5 yıllık OHLCV verisini çeker.
    Başarısız olursa None döner.
    """
    try:
        t  = bp.Ticker(ticker)
        df = t.history(period="5y")
        if df is None or df.empty:
            return None

        # Index timezone normalize
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Son ROLLING_WINDOW günü al
        df = df.sort_index().iloc[-ROLLING_WINDOW:]

        # Gerekli kolonların varlığını kontrol et
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(set(df.columns)):
            logger.warning(f"[{ticker}] Eksik kolon: {required - set(df.columns)}")
            return None

        return df

    except Exception as e:
        logger.error(f"[{ticker}] borsapy hatası: {e}")
        return None


# ── Firestore'a Yaz ───────────────────────────────────────────────────────────

def _write_ohlcv_to_firestore(ticker: str, df: pd.DataFrame, db) -> int:
    """
    DataFrame'i Firestore'a batch halinde yazar.
    Document ID = tarih string'i (ör. '2020-01-02')
    Döndürür: yazılan gün sayısı
    """
    ohlcv_ref = db.collection("hisseler").document(ticker).collection("ohlcv")

    batch     = db.batch()
    batch_cnt = 0
    yazilan   = 0

    for tarih, row in df.iterrows():
        tarih_str = str(tarih.date()) if hasattr(tarih, 'date') else str(tarih)[:10]

        doc_ref = ohlcv_ref.document(tarih_str)
        batch.set(doc_ref, {
            "open":   round(float(row["Open"]),   4),
            "high":   round(float(row["High"]),   4),
            "low":    round(float(row["Low"]),     4),
            "close":  round(float(row["Close"]),  4),
            "volume": int(row["Volume"]),
            "tarih":  tarih_str,
        })

        batch_cnt += 1
        yazilan   += 1

        if batch_cnt >= BATCH_SIZE:
            batch.commit()
            batch     = db.batch()
            batch_cnt = 0

    if batch_cnt > 0:
        batch.commit()

    return yazilan


# ── Ana Fonksiyon ─────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("PayNotu OHLCV İlk Kurulum Başladı")
    logger.info("=" * 60)

    db = _firebase_db()

    # Firestore'dan aktif hisseleri çek
    ticker_docs = {
        doc.id: doc.to_dict()
        for doc in db.collection("hisseler").where("kap_aktif", "==", True).stream()
    }
    ticker_list = sorted(ticker_docs.keys())
    toplam      = len(ticker_list)
    logger.info(f"{toplam} aktif hisse bulundu")

    ok = fail = atla = 0

    for i, ticker in enumerate(ticker_list, 1):
        logger.info(f"[{i}/{toplam}] {ticker} işleniyor...")

        # Zaten veri varsa atla
        try:
            mevcut = list(
                db.collection("hisseler")
                .document(ticker)
                .collection("ohlcv")
                .limit(1)
                .stream()
            )
            if mevcut:
                logger.info(f"[{ticker}] Zaten mevcut, atlanıyor")
                atla += 1
                continue
        except Exception:
            pass

        # OHLCV çek
        df = _fetch_ohlcv(ticker)
        if df is None:
            logger.warning(f"[{ticker}] Veri alınamadı")
            fail += 1
            time.sleep(TICKER_SLEEP)
            continue

        # Firestore'a yaz
        try:
            yazilan = _write_ohlcv_to_firestore(ticker, df, db)
            logger.info(f"[{ticker}] ✅ {yazilan} gün yazıldı")
            ok += 1
        except Exception as e:
            logger.error(f"[{ticker}] Firestore yazma hatası: {e}")
            fail += 1

        time.sleep(TICKER_SLEEP)
        if i % 10 == 0:
            logger.info(f"--- {i}/{toplam} tamamlandı | OK:{ok} FAIL:{fail} ATLA:{atla} ---")
            time.sleep(BATCH_SLEEP)

    logger.info("=" * 60)
    logger.info(f"İlk Kurulum Tamamlandı")
    logger.info(f"✅ Başarılı : {ok}")
    logger.info(f"⏭️  Atlanan  : {atla}")
    logger.info(f"❌ Başarısız: {fail}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
