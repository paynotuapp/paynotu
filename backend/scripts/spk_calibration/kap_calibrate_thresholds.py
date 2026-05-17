"""
SPK Esik + Pump&Dump Parmak Izi Kalibrasyon Scripti
Kaynak: ws.spk.gov.tr/IdariYaptirimlar/api/IslemYasaklari

Gorev 1: Eşik kalibrasyonu
  Karar oncesi 60 gunluk pencereleri analiz et,
  volume_spike / mahalanobis / gini / daily_return esiklerini hesapla.

Gorev 2: Pump&Dump parmak izi
  Her vaka icin zirve oncesi/sonrasi metrikleri hesapla:
    pump_duration   : zirveye kaç günde ulaşıldı
    volume_surge    : zirve öncesi hacim artışı (pump/baseline)
    pump_rate       : zirve öncesi ortalama günlük getiri
    dump_rate       : zirve sonrası ortalama günlük getiri
    post_peak_volume: zirve sonrası hacim / zirve öncesi hacim
  Ortalamaları ve std'leri motor_config.json'a pump_dump_fingerprint olarak yaz.
"""

import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd
import yfinance as yf
import requests
import urllib3
import warnings
urllib3.disable_warnings()
warnings.filterwarnings('ignore')

SPK_WS_URL    = "https://ws.spk.gov.tr/IdariYaptirimlar/api/IslemYasaklari"
OUTPUT_PATH   = "C:/pay/motor_config.json"
DAYS_BEFORE   = 60    # Karar oncesi esik analiz penceresi
PD_WINDOW     = 180   # Pump&dump analiz penceresi (gun)
PD_PUMP_DAYS  = 60    # Zirve oncesi pump fazı maks uzunlugu
PD_DUMP_DAYS  = 60    # Zirve sonrasi dump fazı maks uzunlugu
PERCENTILE    = 90


# ─────────────────────────────────────────────────────────────────────────────
# Ortak yardimcilar
# ─────────────────────────────────────────────────────────────────────────────

def fetch_islem_yasaklari() -> list[dict]:
    print("SPK ws.spk.gov.tr cekiliyor...")
    r = requests.get(
        SPK_WS_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=20,
        verify=False,
    )
    r.raise_for_status()
    data = r.json()
    print(f"  {len(data)} kayit alindi.")
    return data


def build_records(raw: list[dict]) -> list[dict]:
    seen: dict[str, pd.Timestamp] = {}
    for item in raw:
        ticker = (item.get("payKodu") or "").strip().upper()
        tarih_str = item.get("kurulKararTarihi") or ""
        if not ticker or not tarih_str:
            continue
        try:
            ts = pd.Timestamp(tarih_str)
        except Exception:
            continue
        key = f"{ticker}_{ts.date()}"
        seen[key] = ts
    return [
        {"ticker": k.split("_")[0], "karar_tarihi": v}
        for k, v in sorted(seen.items())
    ]


def _gini(arr: np.ndarray) -> float:
    arr = np.abs(arr[~np.isnan(arr)])
    if len(arr) < 2 or arr.sum() == 0:
        return 0.0
    arr = np.sort(arr)
    n   = len(arr)
    cs  = np.cumsum(arr)
    return float(
        (2 * np.sum(np.arange(1, n + 1) * arr) - (n + 1) * cs[-1])
        / (n * cs[-1] + 1e-10)
    )


def _fetch_df(ticker: str) -> pd.DataFrame | None:
    try:
        df = yf.Ticker(ticker + ".IS").history(period="5y", auto_adjust=True)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Görev 1: Eşik kalibrasyonu
# ─────────────────────────────────────────────────────────────────────────────

def analyze_pre_decision_window(ticker: str, decision_date: pd.Timestamp,
                                 df: pd.DataFrame) -> dict:
    window_start = decision_date - pd.Timedelta(days=DAYS_BEFORE)
    window = df[(df.index >= window_start) & (df.index <= decision_date)]

    if len(window) < 5:
        return {}

    returns = window["Close"].pct_change().dropna()
    volume  = window["Volume"].replace(0, np.nan).dropna()
    if len(returns) < 3:
        return {}

    vol_spike = (
        float(volume.max() / volume.mean())
        if len(volume) > 0 and volume.mean() > 0 else 1.0
    )
    std_r   = returns.std()
    z_score = float(abs((returns - returns.mean()) / std_r).max()) if std_r > 0 else 0.0

    return {
        "ticker":              ticker,
        "decision_date":       str(decision_date.date()),
        "max_volume_spike":    round(vol_spike, 4),
        "max_z_score":         round(z_score, 4),
        "max_daily_return":    round(float(returns.abs().max()), 4),
        "gini":                round(_gini(returns.abs().values), 4),
        "window_days_actual":  len(window),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Görev 2: Pump&Dump parmak izi
# ─────────────────────────────────────────────────────────────────────────────

def analyze_pump_dump(ticker: str, karar_tarihi: pd.Timestamp,
                       df: pd.DataFrame) -> dict | None:
    """
    Tedbir karari oncesindeki PD_WINDOW gunluk pencerede pump&dump fazlarini
    tespit et ve metriklerini dondur.

    pump_duration   : pump fazinin gun sayisi (local_min -> peak)
    volume_surge    : pump donemi ortalama hacim / baseline ortalama hacim
    pump_rate       : pump donemi ortalama gunluk getiri
    dump_rate       : dump donemi ortalama gunluk getiri
    post_peak_volume: dump donemi ort. hacim / pump donemi ort. hacim
    """
    window_end   = karar_tarihi
    window_start = karar_tarihi - pd.Timedelta(days=PD_WINDOW)
    window       = df[(df.index >= window_start) & (df.index <= window_end)].copy()

    if len(window) < 30:
        return None

    # ── Zirve tespiti ────────────────────────────────────────────────────────
    peak_loc = int(window['Close'].values.argmax())
    peak_idx = window.index[peak_loc]

    # Pump fazı: zirveye kadar olan son PD_PUMP_DAYS gün
    pump_start_loc = max(0, peak_loc - PD_PUMP_DAYS)
    pump_window    = window.iloc[pump_start_loc : peak_loc + 1]

    # Dump fazı: zirve sonrası PD_DUMP_DAYS gün
    dump_end_loc = min(len(window), peak_loc + PD_DUMP_DAYS + 1)
    dump_window  = window.iloc[peak_loc : dump_end_loc]

    if len(pump_window) < 5 or len(dump_window) < 3:
        return None

    # ── Baseline hacim (pump öncesi veya daha uzak geçmiş) ───────────────────
    baseline_start = karar_tarihi - pd.Timedelta(days=PD_WINDOW + 90)
    baseline       = df[(df.index >= baseline_start) & (df.index < window_start)]
    if len(baseline) >= 10:
        baseline_vol = float(baseline['Volume'].replace(0, np.nan).mean())
    else:
        pre_pump = window.iloc[:pump_start_loc]
        baseline_vol = (
            float(pre_pump['Volume'].replace(0, np.nan).mean())
            if len(pre_pump) >= 5 else float(pump_window['Volume'].mean())
        )
    if np.isnan(baseline_vol) or baseline_vol <= 0:
        baseline_vol = float(pump_window['Volume'].mean())

    # ── Metrikler ────────────────────────────────────────────────────────────
    pump_vol  = float(pump_window['Volume'].replace(0, np.nan).mean())
    dump_vol  = float(dump_window['Volume'].replace(0, np.nan).mean())

    pump_rets = pump_window['Close'].pct_change().dropna()
    dump_rets = dump_window['Close'].pct_change().dropna()

    pump_duration    = len(pump_window)
    volume_surge     = pump_vol / (baseline_vol + 1e-10)
    pump_rate        = float(pump_rets.mean()) if len(pump_rets) > 0 else 0.0
    dump_rate        = float(dump_rets.mean()) if len(dump_rets) > 0 else 0.0
    post_peak_volume = dump_vol / (pump_vol + 1e-10)

    return {
        "ticker":           ticker,
        "karar_tarihi":     str(karar_tarihi.date()),
        "peak_date":        str(peak_idx.date()),
        "pump_duration":    pump_duration,
        "volume_surge":     round(volume_surge,     4),
        "pump_rate":        round(pump_rate,         6),
        "dump_rate":        round(dump_rate,         6),
        "post_peak_volume": round(post_peak_volume,  4),
        "pump_window_days": len(pump_window),
        "dump_window_days": len(dump_window),
    }


def compute_pd_fingerprint(pd_results: list[dict]) -> dict:
    """Tum vakalardan parmak izi olustur (ortalama + std)."""
    metrics = ["pump_duration", "volume_surge", "pump_rate",
               "dump_rate", "post_peak_volume"]
    fp: dict = {}
    for m in metrics:
        vals = [r[m] for r in pd_results
                if r.get(m) is not None and not np.isnan(float(r[m]))]
        if vals:
            fp[f"{m}_mean"] = round(float(np.mean(vals)), 6)
            fp[f"{m}_std"]  = round(float(np.std(vals)),  6)
            fp[f"{m}_p10"]  = round(float(np.percentile(vals, 10)), 6)
            fp[f"{m}_p90"]  = round(float(np.percentile(vals, 90)), 6)
    fp["n_cases"] = len(pd_results)
    return fp


# ─────────────────────────────────────────────────────────────────────────────
# Ana kalibrasyon
# ─────────────────────────────────────────────────────────────────────────────

def calibrate():
    raw     = fetch_islem_yasaklari()
    records = build_records(raw)

    unique_tickers = sorted(set(r["ticker"] for r in records))
    date_range = (
        min(r["karar_tarihi"] for r in records).date(),
        max(r["karar_tarihi"] for r in records).date(),
    )
    print(f"\nToplam karar   : {len(records)}")
    print(f"Benzersiz hisse: {len(unique_tickers)}")
    print(f"Tarih araligi  : {date_range[0]} - {date_range[1]}")
    print(f"Hisseler       : {unique_tickers}\n")

    # Her hisse için yfinance verisi bir kez indir
    df_cache: dict[str, pd.DataFrame] = {}
    for ticker in unique_tickers:
        df = _fetch_df(ticker)
        if df is not None:
            df_cache[ticker] = df

    print(f"yfinance: {len(df_cache)}/{len(unique_tickers)} hisse verisi alindi.\n")

    # ── Görev 1: Eşik analizi ────────────────────────────────────────────────
    threshold_results = []
    pd_results        = []

    for i, rec in enumerate(records):
        ticker = rec["ticker"]
        karar  = rec["karar_tarihi"]
        df     = df_cache.get(ticker)
        if df is None:
            print(f"[{i+1}/{len(records)}] {ticker} - veri yok, atlaniyor")
            continue

        print(f"[{i+1}/{len(records)}] {ticker} ({karar.date()}) analiz ediliyor...")

        # Eşik metrikleri
        th = analyze_pre_decision_window(ticker, karar, df)
        if th:
            threshold_results.append(th)
            print(f"  Esik  → vol={th['max_volume_spike']:.2f}  "
                  f"z={th['max_z_score']:.2f}  gini={th['gini']:.2f}")

        # Pump&dump metrikleri
        pd_m = analyze_pump_dump(ticker, karar, df)
        if pd_m:
            pd_results.append(pd_m)
            print(f"  P&D   → pump_dur={pd_m['pump_duration']}  "
                  f"vol_surge={pd_m['volume_surge']:.2f}  "
                  f"pump_rate={pd_m['pump_rate']:.4f}  "
                  f"dump_rate={pd_m['dump_rate']:.4f}")

    # ── Eşik hesaplama ───────────────────────────────────────────────────────
    print()
    if not threshold_results:
        print("Kalibrasyon icin yeterli veri yok.")
        return

    config = {
        "hacim_spike_esigi":           round(float(np.percentile(
            [r["max_volume_spike"] for r in threshold_results], PERCENTILE)), 2),
        "mahalanobis_esigi":           round(float(np.percentile(
            [r["max_z_score"]      for r in threshold_results], PERCENTILE)), 2),
        "gini_esigi":                  round(float(np.percentile(
            [r["gini"]             for r in threshold_results], PERCENTILE)), 2),
        # BIST devre kesici %10 — manipülasyon eşiği bir alt seviye %9'da sabitlenir
        "gunluk_fiyat_esigi":          min(round(float(np.percentile(
            [r["max_daily_return"] for r in threshold_results], PERCENTILE)), 4), 0.09),
        "calibrated_from_n_decisions": len(threshold_results),
        "calibration_date":            str(pd.Timestamp.now().date()),
        "percentile_used":             PERCENTILE,
        "window_days":                 DAYS_BEFORE,
        "data_source":                 SPK_WS_URL,
    }

    # ── Pump&Dump parmak izi ─────────────────────────────────────────────────
    if pd_results:
        fp = compute_pd_fingerprint(pd_results)
        config["pump_dump_fingerprint"] = fp
        print(f"Pump&Dump parmak izi ({fp['n_cases']} vaka):")
        for k, v in fp.items():
            print(f"  {k}: {v}")
    else:
        print("Pump&dump analizi icin yeterli veri yok.")

    # ── Yazma ────────────────────────────────────────────────────────────────
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    detail_path = OUTPUT_PATH.replace(".json", "_detail.json")
    with open(detail_path, "w", encoding="utf-8") as f:
        pd_detail = {"threshold_results": threshold_results, "pd_results": pd_results}
        json.dump(pd_detail, f, indent=2, ensure_ascii=False)

    print(f"\nKalibrasyon tamamlandi ({len(threshold_results)} vaka).")
    print(json.dumps({k: v for k, v in config.items()
                      if k != "pump_dump_fingerprint"}, indent=2))
    print(f"\nDetay : {detail_path}")
    print(f"Config: {OUTPUT_PATH}")


if __name__ == "__main__":
    calibrate()
