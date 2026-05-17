import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# Firebase bağlantısı
cred = credentials.Certificate('pay-defteri-firebase-adminsdk-fbsvc-a78dbbe1b9.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# Excel'i oku
df = pd.read_excel('endeks_list.xlsx', header=None)

hisse_endeks = {}
current_endeks = None

for _, row in df.iterrows():
    val = str(row[0]).strip()
    kod = str(row[1]).strip() if pd.notna(row[1]) else ''
    
    if val.startswith('BIST') and (kod == 'nan' or kod == ''):
        current_endeks = val.strip()
    elif kod and kod != 'nan' and kod != 'Kod' and current_endeks:
        try:
            int(val)
            if kod not in hisse_endeks:
                hisse_endeks[kod] = []
            if current_endeks not in hisse_endeks[kod]:
                hisse_endeks[kod].append(current_endeks)
        except:
            pass

print(f"Toplam {len(hisse_endeks)} hisse endeks bilgisi hazır")
print(f"FROTO: {hisse_endeks.get('FROTO', [])}")

# Firebase'e yükle
for i, (sembol, endeksler) in enumerate(hisse_endeks.items()):
    try:
        db.collection('hisseler').document(sembol).update({'endeksler': endeksler})
        if (i + 1) % 50 == 0:
            print(f"{i+1} hisse güncellendi...")
    except Exception as e:
        print(f"Hata ({sembol}): {e}")

print("Tamamlandi!")