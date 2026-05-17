import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import timedelta

warnings.filterwarnings('ignore')

CSV_IN  = "C:/pay/spk_belgeleri/vakalar_analiz.csv"
OUT_CSV = "C:/pay/spk_belgeleri/vakalar_metrikler.csv"
OUT_JSON = "C:/pay/spk_belgeleri/esikler_final.json"

# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def gini(arr):
    arr = np.array(arr, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2 or arr.mean() == 0:
        return np.nan
    arr = np.sort(arr)
    n   = len(arr)
    idx = np.arange(1, n + 1)
    return (2 * (idx * arr).sum()) / (n * arr.sum()) - (n + 1) / n

def max_streak(series):
    """Ardışık kapanış artış günü sayısı maks."""
    streak = cur = 0
    for a, b in zip(series[:-1], series[1:]):
        if b > a:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    return streak

def zscore_max(series, ref_mean, ref_std):
    if ref_std == 0 or np.isnan(ref_std):
        return np.nan
    return float(((series - ref_mean) / ref_std).abs().max())

# ── Veri yükle ────────────────────────────────────────────────────────────────
df = pd.read_csv(CSV_IN, encoding='utf-8-sig')
df = df[df['hata'].isna() | (df['hata'] == '')].copy()   # sadece başarılılar
df['baslangic'] = pd.to_datetime(df['baslangic'], format='%d.%m.%Y')
df['bitis']     = pd.to_datetime(df['bitis'],     format='%d.%m.%Y')

print(f"İşlenecek vaka: {len(df)}")

rows = []

for i, row in df.iterrows():
    t     = row['ticker']
    bas   = row['baslangic']
    bit   = row['bitis']
    yftic = t + ".IS"

    ref_start = bas - timedelta(days=365)
    fetch_end = bit + timedelta(days=1)

    try:
        raw = yf.download(
            yftic,
            start=ref_start.strftime('%Y-%m-%d'),
            end=fetch_end.strftime('%Y-%m-%d'),
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        print(f"  [{t}] hata: {e}")
        continue

    if raw.empty or len(raw) < 5:
        print(f"  [{t}] veri yok")
        continue

    # MultiIndex düzelt
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.dropna(subset=['Close'])

    ref   = raw[raw.index <  bas]
    manip = raw[(raw.index >= bas) & (raw.index <= bit)]

    if len(ref) < 5:
        ref = raw  # referans yoksa tüm veri

    close_ref   = ref['Close']
    close_manip = manip['Close'] if not manip.empty else close_ref.iloc[:0]
    vol_ref     = ref['Volume'].replace(0, np.nan)
    vol_manip   = manip['Volume'].replace(0, np.nan) if not manip.empty else vol_ref.iloc[:0]

    # ── Referans dönem metrikleri ─────────────────────────────────────────────
    r_price_mean  = float(close_ref.mean())
    r_price_std   = float(close_ref.std())
    r_vol_mean    = float(vol_ref.mean())
    r_vol_std     = float(vol_ref.std())
    r_volatilite  = float(close_ref.pct_change().std() * np.sqrt(252))
    r_adr         = float(close_ref.pct_change().abs().mean() * 100)
    r_rsi_mean    = float(rsi(close_ref).mean())
    r_gini_fiyat  = float(gini(close_ref.values))
    r_gini_hacim  = float(gini(vol_ref.dropna().values))
    r_streak_mean = float(max_streak(close_ref.values))

    # ── Manipülasyon dönem metrikleri ─────────────────────────────────────────
    if len(close_manip) < 2:
        m_rsi_max = m_hacim_spike = m_volatilite = m_zscore_max = np.nan
        m_gini_fiyat = m_gini_hacim = m_streak_max = m_adr = np.nan
        pump_orani = row['pump_orani']
    else:
        rsi_series    = rsi(pd.concat([close_ref.tail(28), close_manip]))
        m_rsi_max     = float(rsi_series.loc[close_manip.index].max())
        m_hacim_spike = float(vol_manip.max() / r_vol_mean) if r_vol_mean > 0 else np.nan
        m_volatilite  = float(close_manip.pct_change().std() * np.sqrt(252))
        m_zscore_max  = zscore_max(close_manip, r_price_mean, r_price_std)
        m_gini_fiyat  = float(gini(close_manip.values))
        m_gini_hacim  = float(gini(vol_manip.dropna().values))
        m_streak_max  = float(max_streak(close_manip.values))
        m_adr         = float(close_manip.pct_change().abs().mean() * 100)
        pump_orani    = float(close_manip.max() / r_price_mean) if r_price_mean > 0 else np.nan

    rec = {
        'dosya':          row['dosya'],
        'ticker':         t,
        'baslangic':      bas.strftime('%d.%m.%Y'),
        'bitis':          bit.strftime('%d.%m.%Y'),
        'ref_gun':        len(close_ref),
        'manip_gun':      len(close_manip),
        # Referans (normal dönem)
        'ref_price_mean':  round(r_price_mean, 4),
        'ref_price_std':   round(r_price_std,  4),
        'ref_volatilite':  round(r_volatilite, 4),
        'ref_adr':         round(r_adr,        4),
        'ref_rsi_mean':    round(r_rsi_mean,   4),
        'ref_gini_fiyat':  round(r_gini_fiyat, 4),
        'ref_gini_hacim':  round(r_gini_hacim, 4),
        'ref_streak_max':  round(r_streak_mean,4),
        # Manipülasyon dönemi
        'manip_rsi_max':    round(m_rsi_max,     4) if not np.isnan(m_rsi_max)     else None,
        'manip_hacim_spike':round(m_hacim_spike,  4) if not np.isnan(m_hacim_spike) else None,
        'manip_volatilite': round(m_volatilite,   4) if not np.isnan(m_volatilite)  else None,
        'manip_zscore_max': round(m_zscore_max,   4) if not np.isnan(m_zscore_max)  else None,
        'manip_gini_fiyat': round(m_gini_fiyat,   4) if not np.isnan(m_gini_fiyat)  else None,
        'manip_gini_hacim': round(m_gini_hacim,   4) if not np.isnan(m_gini_hacim)  else None,
        'manip_streak_max': round(m_streak_max,   4) if not np.isnan(m_streak_max)  else None,
        'manip_adr':        round(m_adr,          4) if not np.isnan(m_adr)         else None,
        'pump_orani':       round(pump_orani,      4) if pump_orani and not np.isnan(pump_orani) else None,
    }
    rows.append(rec)
    print(f"  [{t:8s}] manip={len(close_manip):3d}g  rsi_max={rec['manip_rsi_max']}  "
          f"spike={rec['manip_hacim_spike']}  pump={rec['pump_orani']}")

# ── DataFrame ─────────────────────────────────────────────────────────────────
mdf = pd.DataFrame(rows)
mdf.to_csv(OUT_CSV, index=False, encoding='utf-8-sig')
print(f"\nMetrik CSV kaydedildi: {OUT_CSV}  ({len(mdf)} satır)\n")

# ── 75. yüzdelik eşikler ─────────────────────────────────────────────────────
manip_cols = {
    'rsi_max':      'manip_rsi_max',
    'hacim_spike':  'manip_hacim_spike',
    'volatilite':   'manip_volatilite',
    'zscore_max':   'manip_zscore_max',
    'gini_fiyat':   'manip_gini_fiyat',
    'gini_hacim':   'manip_gini_hacim',
    'streak_max':   'manip_streak_max',
    'pump_orani':   'pump_orani',
    'adr_ref_pct':  'manip_adr',
}

ref_cols = {
    'rsi_max':      'ref_rsi_mean',
    'hacim_spike':  None,
    'volatilite':   'ref_volatilite',
    'zscore_max':   None,
    'gini_fiyat':   'ref_gini_fiyat',
    'gini_hacim':   'ref_gini_hacim',
    'streak_max':   'ref_streak_max',
    'pump_orani':   None,
    'adr_ref_pct':  'ref_adr',
}

print("=" * 65)
print(f"{'Metrik':<18} {'Manip_Ort':>10} {'Ref_Ort':>10} {'Fark':>10} {'P75_Eşik':>10}")
print("-" * 65)

esikler = {}
karsilastirma = {}

for key, mcol in manip_cols.items():
    manip_vals = mdf[mcol].dropna()
    p75 = float(np.percentile(manip_vals, 75)) if len(manip_vals) > 0 else None
    m_mean = float(manip_vals.mean()) if len(manip_vals) > 0 else None

    rcol = ref_cols[key]
    if rcol and rcol in mdf.columns:
        ref_vals = mdf[rcol].dropna()
        r_mean = float(ref_vals.mean()) if len(ref_vals) > 0 else None
    else:
        r_mean = None

    fark = round(m_mean - r_mean, 4) if (m_mean is not None and r_mean is not None) else None

    esikler[key] = round(p75, 4) if p75 is not None else None
    karsilastirma[key] = {
        'manip_ort': round(m_mean, 4) if m_mean else None,
        'ref_ort':   round(r_mean, 4) if r_mean else None,
        'fark':      round(fark, 4)   if fark   else None,
        'p75_esik':  round(p75, 4)    if p75    else None,
    }

    print(f"  {key:<16} {str(round(m_mean,3)) if m_mean else 'N/A':>10} "
          f"{str(round(r_mean,3)) if r_mean else 'N/A':>10} "
          f"{str(round(fark,3)) if fark else 'N/A':>10} "
          f"{str(round(p75,3)) if p75 else 'N/A':>10}")

# ── pump_orani > 2 analizi ────────────────────────────────────────────────────
pump_df = mdf[mdf['pump_orani'] > 2].copy()
print(f"\n{'='*65}")
print(f"pump_orani > 2  →  {len(pump_df)} vaka  ({len(pump_df)/len(mdf)*100:.0f}%)")
print(f"{'-'*65}")

pump_ortak = {}
if not pump_df.empty:
    cols_ortak = ['manip_rsi_max','manip_hacim_spike','manip_volatilite',
                  'manip_zscore_max','manip_streak_max','manip_adr']
    for col in cols_ortak:
        vals = pump_df[col].dropna()
        if len(vals):
            pump_ortak[col] = {'ort': round(vals.mean(),3), 'med': round(vals.median(),3)}
            print(f"  {col:<22} ort={pump_ortak[col]['ort']:>8}  medyan={pump_ortak[col]['med']:>8}")

    print(f"\n  Pump>2 tickerlar: {list(pump_df['ticker'].unique())}")

# ── JSON çıktısı ─────────────────────────────────────────────────────────────
output = {
    "meta": {
        "vaka_sayisi":       len(mdf),
        "pump_gt2_sayisi":   int(len(pump_df)),
        "pump_gt2_pct":      round(len(pump_df)/len(mdf)*100, 1),
        "yuzdelik":          75,
        "aciklama": "SPK manipülasyon kararlarından türetilen 75. yüzdelik eşikler"
    },
    "esikler_p75": esikler,
    "karsilastirma": karsilastirma,
    "pump_gt2_ortak_ozellikler": pump_ortak,
    "pump_gt2_tickerlar": list(pump_df['ticker'].unique()),
}

with open(OUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n{'='*65}")
print(f"esikler_final.json kaydedildi: {OUT_JSON}")
print(f"vakalar_metrikler.csv  kayıt : {OUT_CSV}")
