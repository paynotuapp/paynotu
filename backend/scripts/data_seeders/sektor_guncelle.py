import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate(r'C:\pay\pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# Excel'den sembol → sektör mapping'i oluştur
df = pd.read_excel(r'C:\pay\sektörler.xlsx', header=None)

mapping = {}
current_sektor = None

for _, row in df.iterrows():
    col0 = str(row[0]).strip() if pd.notna(row[0]) else ''
    col1 = str(row[1]).strip() if pd.notna(row[1]) else ''

    if col1 == '' and col0 and not col0.replace('.', '').isdigit() and col0 != 'nan' and 'Kayıt' not in col0:
        current_sektor = col0
    elif col1 and col1 != 'nan' and current_sektor:
        mapping[col1] = current_sektor

print(f"Excel'den {len(mapping)} hisse eşleşmesi yüklendi.")

# Firestore'u güncelle
docs = db.collection('hisseler').stream()
toplam = 0
guncellenen = 0
eslesmedi = []

for doc in docs:
    toplam += 1
    data = doc.to_dict()
    symbol = data.get('symbol', doc.id)

    if symbol in mapping:
        yeni_sektor = mapping[symbol]
        doc.reference.update({'industry': yeni_sektor})
        guncellenen += 1
        print(f"✓ {symbol}: {yeni_sektor}")
    else:
        eslesmedi.append(symbol)

print(f"\nTamamlandı! {toplam} hisse tarandı, {guncellenen} güncellendi.")
if eslesmedi:
    print(f"Eşleşmeyen {len(eslesmedi)} hisse: {eslesmedi}")