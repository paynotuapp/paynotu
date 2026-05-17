import os, sys, json, base64, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import firebase_admin
from firebase_admin import credentials, firestore
import requests

DUYGUSAL_AKIL_URL = 'http://localhost:8001'

if not firebase_admin._apps:
    cred_b64 = os.getenv('FIREBASE_CREDENTIALS_BASE64')
    if cred_b64:
        cred_b64 += '=' * (-len(cred_b64) % 4)
        cred = credentials.Certificate(json.loads(base64.b64decode(cred_b64).decode()))
    else:
        cred = credentials.Certificate('C:/pay/backend/pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json')
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Tüm hisselerin yorumlarını gez
hisseler = list(db.collection('hisseler').stream())
print(f'{len(hisseler)} hisse taranacak')

toplam_yorum = 0
guncellenen = 0
hata = 0

for hisse in hisseler:
    yorumlar = list(db.collection('hisseler').document(hisse.id).collection('yorumlar').stream())
    for y in yorumlar:
        toplam_yorum += 1
        data = y.to_dict() or {}
        # Zaten duygu_tonu varsa atla
        if data.get('duygu_tonu'):
            continue
        metin = data.get('yorum') or ''
        if not metin.strip():
            continue
        try:
            r = requests.post(
                f'{DUYGUSAL_AKIL_URL}/yorumu-skorla',
                json={
                    'yorum_metni':         metin,
                    'puan':                float(data.get('puan', 3)),
                    'kullanici_id':        y.id,
                    'hesap_yas_gun':       365,
                    'toplam_yorum_sayisi': 1,
                    'yorum_cesitliligi':   0.5,
                    'yorum_timestamp':     int(time.time()),
                    'faydali_oy':          int(data.get('faydali_oy', 0)),
                    'faydali_olmayan_oy':  int(data.get('faydali_olmayan_oy', 0)),
                    'hisse_kodu':          hisse.id,
                },
                timeout=20,
            )
            if r.status_code == 200:
                sonuc = r.json()
                y.reference.update({
                    'duygu_tonu':         sonuc.get('duygu_tonu', 'Nötr'),
                    'guven_skoru':        sonuc.get('guven_skoru', 50),
                    'itibar_skoru':       sonuc.get('itibar_skoru', 5),
                    'manipulasyon_riski': sonuc.get('manipulasyon_riski', 'Düşük'),
                })
                guncellenen += 1
                print(f'[{guncellenen}] {hisse.id}/{y.id} → {sonuc.get("duygu_tonu")}')
            else:
                hata += 1
        except Exception as e:
            hata += 1
            print(f'HATA {hisse.id}/{y.id}: {e}')

print(f'\nToplam: {toplam_yorum} yorum, {guncellenen} güncellendi, {hata} hata')
