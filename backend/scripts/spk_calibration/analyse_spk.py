import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import yfinance as yf
from datetime import timedelta
import warnings
warnings.filterwarnings('ignore')

CSV = "C:/pay/spk_belgeleri/vakalar.csv"
OUT = "C:/pay/spk_belgeleri/vakalar_analiz.csv"

# ── 1. CSV oku ve tarihleri doldur ────────────────────────────────────────────
df = pd.read_csv(CSV, encoding="utf-8-sig")

df['karar_tarihi'] = pd.to_datetime(df['karar_tarihi'], format='%d.%m.%Y', errors='coerce')
df['baslangic']    = pd.to_datetime(df['baslangic'],    format='%d.%m.%Y', errors='coerce')
df['bitis']        = pd.to_datetime(df['bitis'],        format='%d.%m.%Y', errors='coerce')

mask = df['baslangic'].isna() | df['bitis'].isna()
df.loc[mask, 'baslangic'] = df.loc[mask, 'karar_tarihi'] - timedelta(days=90)
df.loc[mask, 'bitis']     = df.loc[mask, 'karar_tarihi']

print(f"Tarih doldurulan satır: {mask.sum()}")

# ── 2. Ticker listesini düz al ────────────────────────────────────────────────
ticker_meta = []   # (ticker, baslangic, bitis, dosya)
for _, row in df.iterrows():
    for t in str(row['ticker']).split(';'):
        t = t.strip()
        if t:
            ticker_meta.append({
                'ticker':     t,
                'baslangic':  row['baslangic'],
                'bitis':      row['bitis'],
                'dosya':      row['dosya'],
            })

all_tickers = list({x['ticker'] for x in ticker_meta})
print(f"Benzersiz ticker: {len(all_tickers)}")
print("Tickers:", sorted(all_tickers))

# ── 3. yfinance'den veri çek ve eşikleri hesapla ─────────────────────────────
results = []

for meta in ticker_meta:
    t = meta['ticker']
    bas = meta['baslangic']
    bit = meta['bitis']
    yfticker = t + ".IS"   # Borsa Istanbul suffix

    # Manipülasyon döneminden 1 yıl öncesini de referans al
    ref_start = bas - timedelta(days=365)

    try:
        raw = yf.download(
            yfticker,
            start=ref_start.strftime('%Y-%m-%d'),
            end=(bit + timedelta(days=1)).strftime('%Y-%m-%d'),
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        print(f"  [{t}] indirme hatası: {e}")
        results.append({'ticker': t, 'dosya': meta['dosya'], 'hata': str(e)})
        continue

    if raw.empty or len(raw) < 5:
        print(f"  [{t}] veri yok veya yetersiz")
        results.append({'ticker': t, 'dosya': meta['dosya'], 'hata': 'veri_yok'})
        continue

    # Sütun indeksini düzleştir (MultiIndex gelebilir)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    close = raw['Close'].dropna()

    # Referans dönem (bas öncesi 1 yıl) ve manipülasyon dönemi
    ref  = close[close.index < bas]
    manip = close[(close.index >= bas) & (close.index <= bit)]

    if len(ref) < 5:
        ref = close  # Referans dönem boşsa tümünü kullan

    # Günlük getiri
    returns_all   = close.pct_change().dropna()
    returns_ref   = ref.pct_change().dropna()
    returns_manip = manip.pct_change().dropna() if len(manip) > 1 else pd.Series(dtype=float)

    # Fiyat istatistikleri
    price_mean_ref  = ref.mean()
    price_std_ref   = ref.std()
    price_min_manip = manip.min() if not manip.empty else None
    price_max_manip = manip.max() if not manip.empty else None

    # Eşikler
    threshold_upper = price_mean_ref + 2 * price_std_ref   # +2σ
    threshold_lower = price_mean_ref - 2 * price_std_ref   # -2σ

    vol_ref   = returns_ref.std() * (252 ** 0.5) if len(returns_ref) > 1 else None
    vol_manip = returns_manip.std() * (252 ** 0.5) if len(returns_manip) > 1 else None

    adr_ref   = (ref.pct_change().abs().mean() * 100) if len(ref) > 1 else None
    adr_manip = (manip.pct_change().abs().mean() * 100) if len(manip) > 1 else None

    # Manip dönem max fiyat / ref ortalama
    pump_ratio = (price_max_manip / price_mean_ref) if (price_max_manip and price_mean_ref) else None

    r = {
        'dosya':            meta['dosya'],
        'ticker':           t,
        'baslangic':        bas.strftime('%d.%m.%Y'),
        'bitis':            bit.strftime('%d.%m.%Y'),
        'ref_fiyat_ort':    round(price_mean_ref, 4) if price_mean_ref else None,
        'ref_fiyat_std':    round(price_std_ref, 4)  if price_std_ref  else None,
        'esik_ust_2sigma':  round(threshold_upper, 4) if threshold_upper else None,
        'esik_alt_2sigma':  round(threshold_lower, 4) if threshold_lower else None,
        'manip_min_fiyat':  round(price_min_manip, 4) if price_min_manip else None,
        'manip_max_fiyat':  round(price_max_manip, 4) if price_max_manip else None,
        'pump_orani':       round(pump_ratio, 4)       if pump_ratio      else None,
        'vol_ref_yillik':   round(vol_ref, 4)          if vol_ref         else None,
        'vol_manip_yillik': round(vol_manip, 4)        if vol_manip       else None,
        'adr_ref_pct':      round(adr_ref, 4)          if adr_ref         else None,
        'adr_manip_pct':    round(adr_manip, 4)        if adr_manip       else None,
        'ref_gun_sayisi':   len(ref),
        'manip_gun_sayisi': len(manip),
        'hata':             '',
    }
    results.append(r)
    print(f"  [{t}] OK — ref={len(ref)}g manip={len(manip)}g "
          f"pump={r['pump_orani']} vol_ref={r['vol_ref_yillik']}")

# ── 4. Sonuçları kaydet ───────────────────────────────────────────────────────
res_df = pd.DataFrame(results)
res_df.to_csv(OUT, index=False, encoding='utf-8-sig')

# Güncellenen vakalar.csv'yi de yaz
df['baslangic']    = df['baslangic'].dt.strftime('%d.%m.%Y')
df['bitis']        = df['bitis'].dt.strftime('%d.%m.%Y')
df['karar_tarihi'] = df['karar_tarihi'].dt.strftime('%d.%m.%Y')
df.to_csv(CSV, index=False, encoding='utf-8-sig')

# ── 5. Özet ───────────────────────────────────────────────────────────────────
ok   = res_df[res_df['hata'] == '']
fail = res_df[res_df['hata'] != '']

print("\n" + "="*65)
print(f"Tarih doldurulan satır : {mask.sum()}/38")
print(f"Başarılı ticker        : {len(ok)}/{len(res_df)}")
print(f"Veri çekilemeyen       : {len(fail)}")
if not fail.empty:
    print("  ->", list(fail['ticker']))
print(f"\nAnaliz CSV kaydedildi  : {OUT}")
print(f"vakalar.csv güncellendi: {CSV}")

if not ok.empty:
    print("\n── Eşik Özeti (başarılı tickerlar) ──────────────────────────")
    cols = ['ticker','ref_fiyat_ort','esik_ust_2sigma','esik_alt_2sigma',
            'pump_orani','vol_ref_yillik','adr_ref_pct']
    print(ok[cols].to_string(index=False))
