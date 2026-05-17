"""
Railway Cron Runner (Birleşik)
Schedule: 0 16 * * 1-5  →  Pazartesi–Cuma 19:00 TR (16:00 UTC)

Her çalışmada:
  1. Tüm aktif hisseler için finansal skor güncelle (her gün)
  2. Ayın 1'iyse ek olarak SPK kalibrasyon çalıştır (aylık)
"""
import os
import sys
import time
import json
import base64
import logging
from datetime import datetime, timezone, timedelta

import requests
import firebase_admin
from firebase_admin import credentials, firestore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("cron")

FASTAPI_URL  = os.environ["FASTAPI_URL"].rstrip("/")
ADMIN_KEY    = os.getenv("ADMIN_KEY", "")
CONCURRENCY  = 5   # yfinance throttle için batch boyutu
RETRY_WAIT   = 5   # 429 sonrası bekleme (sn)

TR_TZ = timezone(timedelta(hours=3))


# ── Firebase ─────────────────────────────────────────────────────────────────

def _init_db():
    if firebase_admin._apps:
        return firestore.client()
    cred_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64") or os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_b64:
        cred_b64 += "=" * (-len(cred_b64) % 4)
        cred = credentials.Certificate(
            json.loads(base64.b64decode(cred_b64).decode())
        )
    else:
        cred = credentials.Certificate(
            os.path.join(
                os.path.dirname(__file__),
                "pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json",
            )
        )
    firebase_admin.initialize_app(cred)
    return firestore.client()


# ── Görev 1: Günlük Finansal Skor ────────────────────────────────────────────

def run_daily_scores(db, session: requests.Session):
    log.info("=== Günlük finansal skor güncelleme başlıyor ===")
    tickers = [
        doc.id for doc in
        db.collection("hisseler").where("kap_aktif", "==", True).stream()
    ]
    log.info(f"{len(tickers)} aktif hisse")

    ok = fail = 0
    for i, ticker in enumerate(sorted(tickers), 1):
        try:
            r = session.get(
                f"{FASTAPI_URL}/score/{ticker}/financial-only", timeout=60
            )
            if r.status_code == 429:
                log.warning(f"[{ticker}] 429 — {RETRY_WAIT}s bekleniyor")
                time.sleep(RETRY_WAIT)
                r = session.get(
                    f"{FASTAPI_URL}/score/{ticker}/financial-only", timeout=60
                )
            if r.status_code != 200:
                log.warning(f"[{ticker}] HTTP {r.status_code} — atlandı")
                fail += 1
                continue
            data = r.json()
            score = data.get("financial_score")
            if score is None or "error" in data:
                log.warning(f"[{ticker}] skor yok — atlandı")
                fail += 1
                continue
            db.collection("hisseler").document(ticker).update({
                "finansal_taban": round(float(score), 2),
            })
            log.info(f"[{i}/{len(tickers)}] {ticker} → {score:.2f}")
            ok += 1
        except Exception as e:
            log.error(f"[{ticker}] HATA: {e}")
            fail += 1

        if i % CONCURRENCY == 0:
            time.sleep(1)

    log.info(f"Günlük skor tamamlandı — {ok} OK, {fail} hata")
    return fail == 0


# ── Görev 2: Aylık Kalibrasyon ────────────────────────────────────────────────

def run_monthly_calibration(session: requests.Session):
    log.info("=== Aylık SPK kalibrasyon başlıyor ===")
    headers = {}
    if ADMIN_KEY:
        headers["x-admin-key"] = ADMIN_KEY
    try:
        r = session.post(
            f"{FASTAPI_URL}/admin/calibrate",
            headers=headers,
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
        log.info(f"Kalibrasyon tamamlandı: {data}")
        return True
    except Exception as e:
        log.error(f"Kalibrasyon HATA: {e}")
        return False


# ── Ana Akış ──────────────────────────────────────────────────────────────────

def main():
    now_tr = datetime.now(TR_TZ)
    log.info(f"Cron başladı — TR saati: {now_tr.strftime('%Y-%m-%d %H:%M %Z')}")

    db      = _init_db()
    session = requests.Session()
    exit_ok = True

    # 1. Her gün: finansal skor
    exit_ok &= run_daily_scores(db, session)

    # 2. Ayın 1'i: kalibrasyon
    if now_tr.day == 1:
        log.info("Ayın 1'i — aylık kalibrasyon tetikleniyor")
        exit_ok &= run_monthly_calibration(session)
    else:
        log.info(f"Kalibrasyon atlandı (bugün ayın {now_tr.day}'i)")

    log.info("Cron tamamlandı.")
    sys.exit(0 if exit_ok else 1)


if __name__ == "__main__":
    main()
