"""
BIST (XIST) -> Firestore Senkronizasyon Scripti
Kaynak: Twelve Data API (resmi BIST/XIST hisse listesi)
Gorev:
  - Twelve Data'dan tam XIST hisse listesini cek
  - Firestore'daki 635 hisseyle karsilastir
  - Fazladan gelenler varsa Firestore'a ekle
  - Twelve Data'da olmayan ama Firestore'da olan hisselere kap_aktif: false yaz
  - Aktif hisselerde sirket_adi, kap_aktif: true yaz
"""

# TODO(Etap 1.4d veya sonrası): Path güncellemesi gerekli — 3 kırık nokta:
#   1. load_dotenv(_root, ".env")          → _root artık backend/scripts/maintenance/,
#      .env project root'ta (C:/pay/.env). Düzelt:
#      PROJECT_ROOT = Path(__file__).resolve().parents[3]
#      load_dotenv(PROJECT_ROOT / ".env")
#   2. load_dotenv(_root, "duygusal_akil/.env") → duygusal_akil/ project root'ta,
#      bu path asla çözülmez. Düzelt: load_dotenv(PROJECT_ROOT / "duygusal_akil" / ".env")
#   3. CRED_PATH os.path.basename(_root) → credential dosyası _root yanında değil.
#      Düzelt: CRED_PATH = PROJECT_ROOT / os.path.basename(_cred_env)
#   Koşturmadan önce bu üç satırı güncelle.

import os
import json
import requests
from dotenv import load_dotenv

_root = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_root, ".env"))
load_dotenv(os.path.join(_root, "duygusal_akil", ".env"))

import firebase_admin
from firebase_admin import credentials, firestore

_cred_env = os.getenv("FIREBASE_CREDENTIALS_PATH", "pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json")
CRED_PATH = _cred_env if os.path.isabs(_cred_env) else os.path.join(_root, os.path.basename(_cred_env))
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY", "ad80135ab0b8444c8242830de8e20e2c")


def fetch_xist_stocks() -> dict[str, dict]:
    """Twelve Data'dan XIST hisse listesini cek. {symbol: data} donduror."""
    print("Twelve Data XIST hisse listesi cekiliyor...")
    r = requests.get(
        "https://api.twelvedata.com/stocks",
        params={"exchange": "XIST", "apikey": TWELVE_API_KEY},
        timeout=20,
    )
    r.raise_for_status()
    stocks = r.json().get("data", [])
    return {s["symbol"].upper(): s for s in stocks}


def sync():
    aktif_map = fetch_xist_stocks()
    print(f"Twelve Data: {len(aktif_map)} hisse bulundu.\n")

    cred = credentials.Certificate(CRED_PATH)
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    # Firestore'daki mevcut hisseler
    firestore_docs = {doc.id.upper(): doc for doc in db.collection("hisseler").stream()}
    print(f"Firestore: {len(firestore_docs)} hisse mevcut.\n")

    # Karsilastir
    aktif_set = set(aktif_map.keys())
    firestore_set = set(firestore_docs.keys())

    sadece_twelve = aktif_set - firestore_set   # Twelve'de var, Firestore'da yok -> EKLE
    sadece_firestore = firestore_set - aktif_set  # Firestore'da var, Twelve'de yok -> PASIF
    ikisinde_de = aktif_set & firestore_set       # Her ikisinde de var -> GUNCELLE

    print(f"Her ikisinde de: {len(ikisinde_de)}")
    print(f"Sadece Twelve Data (eklenecek): {len(sadece_twelve)}")
    print(f"Sadece Firestore  (pasif yapilacak): {len(sadece_firestore)}")
    if sadece_firestore:
        print(f"  Pasif: {sorted(sadece_firestore)}")
    if sadece_twelve:
        print(f"  Yeni: {sorted(sadece_twelve)}")
    print()

    guncellenen = 0
    eklenen = 0
    pasif = 0

    # Var olan hisseleri guncelle
    for ticker in ikisinde_de:
        h = aktif_map[ticker]
        firestore_docs[ticker].reference.update({
            "sirket_adi": h.get("name") or ticker,
            "kap_aktif": True,
        })
        guncellenen += 1
        if guncellenen % 100 == 0:
            print(f"  {guncellenen} hisse guncellendi...")

    # Yeni hisseleri ekle
    for ticker in sadece_twelve:
        h = aktif_map[ticker]
        db.collection("hisseler").document(ticker).set({
            "symbol":     ticker,
            "sirket_adi": h.get("name") or ticker,
            "kap_aktif":  True,
        }, merge=True)
        print(f"  EKLENDI: {ticker} - {h.get('name', '')}")
        eklenen += 1

    # Sadece Firestore'da olanları pasif yap
    for ticker in sadece_firestore:
        firestore_docs[ticker].reference.update({"kap_aktif": False})
        pasif += 1

    print(f"\nTamamlandi:")
    print(f"  {guncellenen} hisse guncellendi (kap_aktif: true)")
    print(f"  {eklenen}      hisse eklendi")
    print(f"  {pasif}       hisse pasif yapildi (kap_aktif: false)")
    print(f"\nSonuc: Firestore'da {len(firestore_docs) + eklenen - pasif} aktif hisse.")


if __name__ == "__main__":
    sync()
