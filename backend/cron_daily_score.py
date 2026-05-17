"""
Günlük BİST Skor Güncelleyici
Her hisse için finansal_taban + paynotu_skoru yazılır.
Manuel çalıştırma: python cron_daily_score.py
"""
import os
import sys
import time
import requests
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import json

FASTAPI_URL = os.environ.get("FASTAPI_URL", "http://192.168.1.2:8000").rstrip("/")
BATCH_SIZE  = 5    # Her N hissede 1s bekle (yfinance rate limit)
RETRY_WAIT  = 5    # 429 durumunda bekleme süresi (sn)


def _init_firebase():
    if firebase_admin._apps:
        return firestore.client()
    cred_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64") or os.getenv("FIREBASE_CREDENTIALS_JSON")
    if cred_b64:
        cred_b64 += "=" * (-len(cred_b64) % 4)
        cred_dict = json.loads(base64.b64decode(cred_b64).decode())
        cred = credentials.Certificate(cred_dict)
    else:
        cred_path = os.path.join(
            os.path.dirname(__file__),
            "pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json",
        )
        cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def fetch_active_tickers(db) -> list[str]:
    docs = db.collection("hisseler").where("kap_aktif", "==", True).stream()
    return sorted(doc.id for doc in docs)


def score_and_write(ticker: str, db, session: requests.Session) -> bool:
    """
    /score/{ticker} çağırır → finansal_taban + paynotu_skoru günceller.
    """
    url = f"{FASTAPI_URL}/score/{ticker}"
    try:
        r = session.get(url, timeout=90)
        if r.status_code == 429:
            print(f"  [{ticker}] 429 rate-limit, {RETRY_WAIT}s bekleniyor...")
            time.sleep(RETRY_WAIT)
            r = session.get(url, timeout=90)
        if r.status_code != 200:
            print(f"  [{ticker}] HTTP {r.status_code} — atlanıyor")
            return False
        data = r.json()
        if "error" in data:
            print(f"  [{ticker}] API hatası: {data['error']}")
            return False
        finansal  = data.get("financial_score")
        paynotu   = data.get("paynotu_score")
        duygusal  = data.get("emotional_score")
        if finansal is None or paynotu is None:
            print(f"  [{ticker}] Eksik alan — atlanıyor")
            return False

        # ── Firestore güncelle ────────────────────────────────────────────
        update_data = {
            "finansal_taban": round(float(finansal), 4),
            "paynotu_skoru":  round(float(paynotu),  4),
        }
        if duygusal is not None:
            update_data["duygusal_taban"] = round(float(duygusal), 4)

        # Temel analiz verileri varsa ekle
        temel = data.get("temel", {})
        if temel:
            if temel.get("roe") is not None:
                update_data["temel_roe"] = round(float(temel["roe"]), 4)
            if temel.get("kar_marji") is not None:
                update_data["temel_kar_marji"] = round(float(temel["kar_marji"]), 4)
            if temel.get("pd_dd") is not None:
                update_data["temel_pd_dd"] = round(float(temel["pd_dd"]), 4)
            if temel.get("borc_favok") is not None:
                update_data["temel_borc_favok"] = round(float(temel["borc_favok"]), 4)
            if temel.get("ok_buyume") is not None:
                update_data["temel_ok_buyume"] = round(float(temel["ok_buyume"]), 4)
            if temel.get("period"):
                update_data["temel_son_guncelleme"] = temel["period"]
            update_data["temel_kaynak"] = temel.get("kaynak", "fallback")

        db.collection("hisseler").document(ticker).update(update_data)

        spek    = data.get("details", {}).get("speculative_days", "?")
        has_rev = data.get("has_reviews", False)
        kaynak  = temel.get("kaynak", "-") if temel else "-"
        print(f"  fin={finansal:.4f}  pay={paynotu:.4f}  spek={spek}  temel={kaynak}  yorum={'E' if has_rev else '-'}")
        return True
    except Exception as e:
        print(f"  [{ticker}] HATA: {e}")
        return False


def main():
    print(f"[daily-score] Basliyor: {FASTAPI_URL}")
    db = _init_firebase()

    tickers = fetch_active_tickers(db)
    total   = len(tickers)
    print(f"[daily-score] {total} aktif hisse bulundu\n")

    ok = fail = 0
    t0 = time.time()
    session = requests.Session()

    for i, ticker in enumerate(tickers, 1):
        print(f"[{i:>3}/{total}] {ticker:<8}", end=" ", flush=True)
        if score_and_write(ticker, db, session):
            ok += 1
        else:
            fail += 1
        if i % BATCH_SIZE == 0:
            time.sleep(1)

    elapsed = time.time() - t0
    print(f"\n[daily-score] Tamamlandı — {ok} OK, {fail} hata, {elapsed/60:.1f} dk")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
