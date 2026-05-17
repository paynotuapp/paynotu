"""
Fintables symbols.js → Firestore logo güncelleme scripti
- Tüm aktif hisselerin logo'sunu Fintables CDN'den günceller
- Firestore'da olmayan yeni equity hisseler varsa ekler (kap_aktif: True)
- Rapor: güncellenen, yeni eklenen, logo bulunamayan
"""

import re
import json
import sys
import cloudscraper
import firebase_admin
from firebase_admin import credentials, firestore

# ── Firebase başlat ──────────────────────────────────────────────────────────
cred = credentials.Certificate('pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── 1. Fintables'dan veriyi çek ─────────────────────────────────────────────
print('Fintables verisi çekiliyor...', flush=True)
scraper = cloudscraper.create_scraper()
r = scraper.get('https://api.fintables.com/symbols.js/', timeout=30)
r.raise_for_status()
text = r.text
print(f'  İndirilen: {len(text):,} karakter')

# ── 2. Değişkenleri parse et ─────────────────────────────────────────────────
es_val = re.search(r'const es\s*=\s*"([^"]+)"', text).group(1)

mgmt_start = text.index('const mgmt = ') + len('const mgmt = ')
mgmt_raw   = text[mgmt_start : text.index('const uwl = ')].strip().rstrip(';')
mgmt = json.loads(mgmt_raw)
print(f'  mgmt: {len(mgmt)} fon yöneticisi logo')

uwl_start = text.index('const uwl = ') + len('const uwl = ')
uwl_raw   = text[uwl_start : text.index('window.symbols', uwl_start)].strip().rstrip(';')
uwl = json.loads(uwl_raw)
print(f'  uwl: {len(uwl)} sembol logo')

# ── 3. window.symbols parse (JS referanslarını çöz) ──────────────────────────
sym_start = text.index('window.symbols = ') + len('window.symbols = ')
sym_raw   = text[sym_start:].rstrip().rstrip(';')

ef_json = '{"decimals": 2, "thousand": true}'
ff_json = '{"decimals": 6, "thousand": true}'

sym_fixed = sym_raw
for var, val in [('ef', ef_json), ('ff', ff_json), ('es', f'"{es_val}"')]:
    sym_fixed = sym_fixed.replace(f': {var},', f': {val},').replace(f': {var}}}', f': {val}}}')

def _sub(d, m):
    v = d.get(m.group(1))
    return 'null' if v is None else '"' + v + '"'

sym_fixed = re.sub(r"mgmt\['([^']+)'\]", lambda m: _sub(mgmt, m), sym_fixed)
sym_fixed = re.sub(r"uwl\['([^']+)'\]",  lambda m: _sub(uwl,  m), sym_fixed)

symbols: dict = json.loads(sym_fixed)
print(f'  window.symbols: {len(symbols):,} sembol parse edildi')

# ── 4. Field & type analizi ──────────────────────────────────────────────────
print('\n' + '='*50)
print('=== FIELD ANALİZİ ===')
print('='*50)

all_fields: dict[str, int] = {}
type_counts: dict[str, int] = {}
for v in symbols.values():
    if isinstance(v, dict):
        for f in v:
            all_fields[f] = all_fields.get(f, 0) + 1
        t = v.get('type', '?')
        type_counts[t] = type_counts.get(t, 0) + 1

print('\nType dağılımı:')
for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
    print(f'  {t:25s}: {c:,}')

print('\nField\'lar (kaç sembolde var):')
for f, c in sorted(all_fields.items(), key=lambda x: -x[1]):
    print(f'  {f:35s}: {c:,}')

# Equity örnek
equities: dict[str, dict] = {k: v for k, v in symbols.items()
                               if isinstance(v, dict) and v.get('type') == 'equity'}
print(f'\nEquity (hisse) sayısı: {len(equities):,}')
sample_k = list(equities.keys())[3]
print(f'\nEquity örnek ({sample_k}):')
print(json.dumps(equities[sample_k], indent=2, ensure_ascii=False))

# ── 5. Firestore'dan mevcut hisseleri çek ───────────────────────────────────
print('\n' + '='*50)
print('=== FİRESTORE GÜNCELLEME ===')
print('='*50)
print('Firestore\'dan mevcut hisseler çekiliyor...')
fs_snap = db.collection('hisseler').stream()
fs_docs: dict[str, dict] = {doc.id: (doc.to_dict() or {}) for doc in fs_snap}
print(f'  Firestore\'da: {len(fs_docs):,} hisse')

# ── 6. Güncelleme + yeni ekleme ─────────────────────────────────────────────
BATCH_SIZE = 400
guncellenen = 0
yeni_eklenen = 0
logo_yok = 0

batch = db.batch()
batch_cnt = 0

def commit_batch():
    global batch, batch_cnt
    if batch_cnt > 0:
        batch.commit()
        batch = db.batch()
        batch_cnt = 0

print('\n[1/2] Mevcut hisselerin logosu güncelleniyor...')
for symbol, fs_data in fs_docs.items():
    eq = equities.get(symbol)
    if eq is None:
        logo_yok += 1
        continue
    logo = eq.get('logo')
    if logo is None:
        logo_yok += 1
        continue
    ref = db.collection('hisseler').document(symbol)
    batch.update(ref, {'logo': logo})
    batch_cnt += 1
    guncellenen += 1
    if batch_cnt >= BATCH_SIZE:
        commit_batch()
        print(f'  {guncellenen} güncellendi...', flush=True)

commit_batch()
print(f'  Tamamlandı: {guncellenen} güncellendi, {logo_yok} atlandı (Fintables\'ta yok)')

print('\n[2/2] Fintables\'ta olup Firestore\'da olmayan yeni hisseler ekleniyor...')
for symbol, data in equities.items():
    if symbol in fs_docs:
        continue
    new_doc = {
        'symbol':    symbol,
        'name':      data.get('title', symbol),
        'logo':      data.get('logo'),
        'kap_aktif': True,
        'kaynak':    'fintables_import',
    }
    ref = db.collection('hisseler').document(symbol)
    batch.set(ref, new_doc)
    batch_cnt += 1
    yeni_eklenen += 1
    if batch_cnt >= BATCH_SIZE:
        commit_batch()
        print(f'  {yeni_eklenen} yeni eklendi...', flush=True)

commit_batch()
print(f'  Tamamlandı: {yeni_eklenen} yeni hisse eklendi')

# ── 7. Özet rapor ────────────────────────────────────────────────────────────
print('\n' + '='*50)
print('=== SONUÇ RAPORU ===')
print('='*50)
print(f'  Fintables toplam sembol   : {len(symbols):>6,}')
print(f'  Fintables equity (hisse)  : {len(equities):>6,}')
print(f'  Firestore\'da mevcut       : {len(fs_docs):>6,}')
print(f'  ---------------------------------')
print(f'  Logo güncellenen          : {guncellenen:>6,}')
print(f'  Yeni eklenen              : {yeni_eklenen:>6,}')
print(f'  Fintables\'ta logosu yok   : {logo_yok:>6,}')
print('='*50)
print('✓ Tamamlandı.')
