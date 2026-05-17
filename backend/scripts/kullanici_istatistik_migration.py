import os, sys, json, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict

if not firebase_admin._apps:
    cred_b64 = os.getenv('FIREBASE_CREDENTIALS_BASE64')
    if cred_b64:
        cred_b64 += '=' * (-len(cred_b64) % 4)
        cred = credentials.Certificate(json.loads(base64.b64decode(cred_b64).decode()))
    else:
        cred = credentials.Certificate('C:/pay/backend/pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json')
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Tüm yorumları gez, uid bazında topla
kullanici_yorumlar = defaultdict(list)  # uid -> [puan, puan, ...]

hisseler = list(db.collection('hisseler').stream())
print(f'{len(hisseler)} hisse taranıyor...')

for hisse in hisseler:
    yorumlar = list(db.collection('hisseler').document(hisse.id).collection('yorumlar').stream())
    for y in yorumlar:
        data = y.to_dict() or {}
        uid = data.get('uid') or y.id
        puan = data.get('puan')
        if uid and isinstance(puan, int) and 1 <= puan <= 5:
            kullanici_yorumlar[uid].append(puan)

print(f'{len(kullanici_yorumlar)} kullanıcı bulundu')

# Her kullanıcı için istatistikleri hesapla ve users dokümanına yaz
for uid, puanlar in kullanici_yorumlar.items():
    toplam = len(puanlar)
    ortalama = sum(puanlar) / toplam if toplam else 0
    try:
        db.collection('users').document(uid).update({
            'toplam_yorum':  toplam,
            'ortalama_puan': round(ortalama, 2),
        })
        print(f'[OK] {uid[:8]}... toplam={toplam} ortalama={ortalama:.2f}')
    except Exception as e:
        print(f'[HATA] {uid[:8]}... {e}')

print('Bitti.')
