from dotenv import load_dotenv
load_dotenv()

import os
import json
import base64
import logging
import time
import concurrent.futures
from contextlib import asynccontextmanager
from datetime import datetime, timezone, date, timedelta

import re
import math
import traceback as _traceback
import statistics as _statistics
import threading as _threading
import numpy as np
import pandas as pd
import requests as _requests
import urllib3
import cloudscraper
urllib3.disable_warnings()

import firebase_admin
from firebase_admin import credentials, firestore as fb_firestore

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from motors import FinancialEngine, EmotionalEngine, PayNotuIntegrator, FundamentalEngine
from motors.emotional_engine import Review
from services.scenario_classifier import ScenarioClassifier, ClassifierConfig
from daily_ohlcv import fetch_ohlcv_from_firestore, run_daily_ohlcv_update
import borsapy as bp
import uvicorn

import warnings as _warnings
with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", DeprecationWarning)
    from borsapy._providers.isyatirim import IsYatirimProvider
    from borsapy.exceptions import APIError as _IsyAPIError, TickerNotFoundError as _IsyTickerNotFound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DUYGUSAL_AKIL_URL = os.getenv('DUYGUSAL_AKIL_URL', 'http://localhost:8001')


# ── FİREBASE ──────────────────────────────────────────────────────────────────

def _firebase_db():
    if not firebase_admin._apps:
        cred_b64  = (os.getenv("FIREBASE_CREDENTIALS_BASE64") or "").strip()
        cred_json = (os.getenv("FIREBASE_CREDENTIALS_JSON")  or "").strip()

        if cred_b64:
            if not cred_b64.isascii():
                raise ValueError(
                    "FIREBASE_CREDENTIALS_BASE64 içinde ASCII dışı karakter var — "
                    "Railway'de değeri silip yeniden base64 olarak yapıştırın"
                )
            cred_b64 += "=" * (-len(cred_b64) % 4)
            cred_dict = json.loads(base64.b64decode(cred_b64).decode())
        elif cred_json:
            cred_dict = json.loads(cred_json)
        else:
            cred_path = os.path.join(
                os.path.dirname(__file__),
                "pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json",
            )
            firebase_admin.initialize_app(credentials.Certificate(cred_path))
            return fb_firestore.client()

        firebase_admin.initialize_app(credentials.Certificate(cred_dict))
    return fb_firestore.client()


# ── MOTOR INSTANCE'LARI ───────────────────────────────────────────────────────

financial_engine    = FinancialEngine()
emotional_engine    = EmotionalEngine()
integrator          = PayNotuIntegrator()
fund_engine         = FundamentalEngine()
scenario_classifier = ScenarioClassifier(
    config=ClassifierConfig(),
    financial_engine=financial_engine,
)


# ── KALIBRASYON ───────────────────────────────────────────────────────────────

SPK_WS_URL = "https://ws.spk.gov.tr/IdariYaptirimlar/api/IslemYasaklari"
_ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def _gini_arr(arr: np.ndarray) -> float:
    arr = np.abs(arr[~np.isnan(arr)])
    if len(arr) < 2 or arr.sum() == 0:
        return 0.0
    arr = np.sort(arr)
    n = len(arr)
    cumsum = np.cumsum(arr)
    return float((2 * np.sum(np.arange(1, n + 1) * arr) - (n + 1) * cumsum[-1]) / (n * cumsum[-1] + 1e-10))


def _analyze_window(ticker: str, decision_date: pd.Timestamp, days_before: int = 60) -> dict:
    try:
        df = bp.Ticker(ticker).history(period="5y")
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    window = df[
        (df.index >= decision_date - pd.Timedelta(days=days_before)) &
        (df.index <= decision_date)
    ]
    if len(window) < 5:
        return {}
    returns = window["Close"].pct_change().dropna()
    volume  = window["Volume"].replace(0, np.nan).dropna()
    if len(returns) < 3:
        return {}
    vol_spike = float(volume.max() / volume.mean()) if len(volume) > 0 and volume.mean() > 0 else 1.0
    std_r = returns.std()
    z_score = float(abs((returns - returns.mean()) / std_r).max()) if std_r > 0 else 0.0
    return {
        "ticker":           ticker,
        "decision_date":    str(decision_date.date()),
        "max_volume_spike": round(vol_spike, 4),
        "max_z_score":      round(z_score, 4),
        "max_daily_return": round(float(returns.abs().max()), 4),
        "gini":             round(_gini_arr(np.asarray(returns.abs().values, dtype=float)), 4),
    }


def run_calibration() -> dict:
    """SPK web servisinden veri çek, eşikleri hesapla, Firestore'a yaz."""
    raw = _requests.get(
        SPK_WS_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=20, verify=False,
    ).json()

    seen: dict[str, tuple] = {}
    for item in raw:
        ticker = (item.get("payKodu") or "").strip().upper()
        ts_str = item.get("kurulKararTarihi") or ""
        if not ticker or not ts_str:
            continue
        try:
            ts = pd.Timestamp(ts_str)
        except Exception:
            continue
        seen[f"{ticker}_{ts.date()}"] = (ticker, ts)

    records = sorted(seen.values(), key=lambda x: x[1])
    logger.info(f"[calibrate] {len(records)} SPK karar/vaka")

    results = [m for ticker, karar in records if (m := _analyze_window(ticker, karar))]

    if not results:
        raise RuntimeError("Kalibrasyon için yeterli veri yok")

    cfg = {
        "hacim_spike_esigi":     round(float(np.percentile([r["max_volume_spike"]  for r in results], 90)), 2),
        "mahalanobis_esigi":     round(float(np.percentile([r["max_z_score"]       for r in results], 90)), 2),
        "gini_esigi":            round(float(np.percentile([r["gini"]              for r in results], 90)), 2),
        "gunluk_fiyat_esigi":    round(float(np.percentile([r["max_daily_return"]  for r in results], 90)), 4),
        "calibrated_from_n_decisions": len(results),
        "calibration_date":      str(pd.Timestamp.now().date()),
        "percentile_used":       90,
        "window_days":           60,
        "data_source":           SPK_WS_URL,
    }

    try:
        db = _firebase_db()
        db.collection("system_config").document("motor_thresholds").set(cfg)
        logger.info("[calibrate] Firestore güncellendi")
    except Exception as e:
        logger.warning(f"[calibrate] Firestore yazma hatası: {e}")

    financial_engine.reload_thresholds(cfg)
    logger.info(f"[calibrate] Eşikler güncellendi: {cfg}")
    return cfg


# ── TOPSIS RANK GÜNCELLEME ────────────────────────────────────────────────────

def _guncelle_topsis_rank(db) -> None:
    """
    Tüm hisselerin spek_score'larını okuyup büyükten küçüğe sıralar
    ve topsis_rank alanını Firestore'a yazar.
    """
    logger.info("[rank] Spek sıralama başladı")
    docs = list(db.collection("hisseler").where("kap_aktif", "==", True).stream())

    skorlar = []
    for doc in docs:
        d = doc.to_dict() or {}
        finansal = d.get("raw_spek_score") or d.get("spek_score")
        if finansal is not None:
            skorlar.append((doc.id, float(finansal)))

    if not skorlar:
        logger.warning("[rank] Hiç skor bulunamadı")
        return

    skorlar.sort(key=lambda x: x[1], reverse=True)
    toplam = len(skorlar)

    BATCH_SIZE = 400
    batch = db.batch()
    batch_cnt = 0

    for rank, (ticker, _) in enumerate(skorlar, 1):
        ref = db.collection("hisseler").document(ticker)
        batch.update(ref, {
            "topsis_rank":   rank,
            "topsis_toplam": toplam,
        })
        batch_cnt += 1
        if batch_cnt >= BATCH_SIZE:
            batch.commit()
            batch = db.batch()
            batch_cnt = 0

    if batch_cnt > 0:
        batch.commit()

    logger.info(f"[rank] {toplam} hisse sıralandı")


# ── YARDIMCI: Motor detay payload ─────────────────────────────────────────────

def _motor_detay_payload(f_result) -> dict:
    """
    SpekResult nesnesinden Firestore'a yazılacak motor_detay dict'ini üretir.
    Yeni motor v2.2 alanlarını kullanır.
    """
    _am = getattr(f_result, "anomaly_metrics", None)
    return {
        # ── Spek skorları ───────────────────────────────────────────────────
        "spek_score":             f_result.spek_score,
        "topsis_raw":             f_result.topsis_raw,
        "guven_skoru":            f_result.guven_skoru,

        # ── 4 kriter skoru ──────────────────────────────────────────────────
        "fiyat_anomali_skoru":    f_result.fiyat_anomali_skoru,
        "hacim_patlamasi_skoru":  f_result.hacim_patlamasi_skoru,
        "volatilite_skoru":       f_result.volatilite_skoru,
        "pump_benzerlik_skoru":   f_result.pump_benzerlik_skoru,

        # ── Açıklamalar (insan okuyabilir) ──────────────────────────────────
        "fiyat_anomali_aciklama":   f_result.fiyat_anomali_aciklama,
        "hacim_patlamasi_aciklama": f_result.hacim_patlamasi_aciklama,
        "volatilite_aciklama":      f_result.volatilite_aciklama,
        "pump_benzerlik_aciklama":  f_result.pump_benzerlik_aciklama,

        # ── Üç seviyeli spek günler ─────────────────────────────────────────
        "spek_gun_soft":          f_result.spek_gun_soft,
        "spek_gun_hard":          f_result.spek_gun_hard,
        "spek_gun_extreme":       f_result.spek_gun_extreme,
        "spek_orani":             f_result.spek_orani,
        "max_streak":             f_result.max_streak,
        "son_30g_spek_yuzdesi":   f_result.son_30g_spek_yuzdesi,

        # ── Hacim ──────────────────────────────────────────────────────────
        "hacim_spike_kati":       f_result.hacim_spike_kati,

        # ── Filtre (Temelden Kopuş) ─────────────────────────────────────────
        "fundamental_multiplier": f_result.fundamental_multiplier,
        "fundamental_aciklama":   f_result.fundamental_aciklama,

        # ── Entropi ─────────────────────────────────────────────────────────
        "entropi_agirliklari":    f_result.entropi_agirliklari,

        # ── Veri kalitesi ───────────────────────────────────────────────────
        "veri_gun_sayisi":        f_result.veri_gun_sayisi,
        "ipo_listede":            f_result.ipo_listede,
        "corp_action_maskelendi": f_result.corporate_action_maskelendi,
        "data_start":             f_result.data_start,
        "data_end":               f_result.data_end,

        # ── KAP haber ───────────────────────────────────────────────────────
        "kap_haber_sayisi":   f_result.kap_haber_sayisi,
        "haber_carpani":      f_result.haber_carpani,
        "kategori":           f_result.kategori,

        # ── Temel analiz (filtre verisi) ────────────────────────────────────
        "temel": {
            "roe":           f_result.temel_roe,
            "pd_dd":         f_result.temel_pd_dd,
            "fk":            f_result.temel_fk,
            "net_kar_marji": f_result.temel_net_kar_marji,
            "ok_buyume":     f_result.temel_ok_buyume,
            "borc_favok":    f_result.temel_borc_favok,
            "kaynak":        f_result.temel_kaynak,
            "period":        f_result.temel_period,
        },

        # ── Anomali metrikler ────────────────────────────────────────────────
        "anomaly_metrics": {
            "total_days":             _am.total_days,
            "hard_count":             _am.hard_count,
            "extreme_count":          _am.extreme_count,
            "weighted_count":         _am.weighted_count,
            "block_count":            _am.block_count,
            "longest_streak":         _am.longest_streak,
            "avg_streak":             _am.avg_streak,
            "hhi":                    _am.hhi,
            "recency_center":         _am.recency_center,
            "r_activity":             _am.r_activity,
            "r_streak":               _am.r_streak,
            "anomaly_activity_score": _am.anomaly_activity_score,
        } if _am is not None else None,

        # ── Zaman damgası ───────────────────────────────────────────────────
        "guncelleme_tarihi": pd.Timestamp.now().isoformat(),
    }


def _build_fundamental_payload(fund_res) -> dict:
    """FundamentalEngine sonucundan Firestore finansal alanları üretir."""
    _pio  = fund_res.piotroski
    _fsub = fund_res.subscores
    return {
        "finansal_skor":              fund_res.financial_score,
        "finansal_skor_label":        fund_res.financial_score_label,
        "finansal_skor_quality":      fund_res.financial_score_quality,
        "finansal_subscores": {
            "profitability": _fsub.profitability,
            "balance_sheet": _fsub.balance_sheet,
            "cash_flow":     _fsub.cash_flow,
            "growth":        _fsub.growth,
            "valuation":     _fsub.valuation,
            "stability":     _fsub.stability,
            "piotroski":     _fsub.piotroski,
        },
        "piotroski_score":            _pio.score               if _pio else None,
        "piotroski_normalized":       _pio.normalized          if _pio else None,
        "piotroski_total":            _pio.total_criteria      if _pio else 9,
        "piotroski_calculated":       _pio.calculated_criteria if _pio else 0,
        "piotroski_coverage":         _pio.coverage            if _pio else 0.0,
        "piotroski_confidence":       _pio.confidence          if _pio else "not_applicable",
        "piotroski_applicability":    _pio.applicability       if _pio else "not_applicable",
        "piotroski_missing_criteria": _pio.missing_criteria    if _pio else [],
        "finansal_aciklama":          fund_res.explanation,
        "finansal_flags":             fund_res.financial_flags,
        "finansal_data_source":       fund_res.data_source,
        "finansal_sector_group":      fund_res.sector_group,
        "finansal_period":            fund_res.period,
    }


# ── GÜNLÜK CRON JOB ───────────────────────────────────────────────────────────

CRON_BATCH = 5

def daily_job(tickers: list[str] | None = None):
    """
    Her gün 03:00 UTC çalışır.
    1. PASS 1 — Tüm hisseler için finansal/duygusal sonuçları ticker_cache'e alır.
    2. q05/q95 — Geçerli spek_score dağılımından robust eşikler hesaplanır,
       system_config/motor_thresholds dökümanına yazılır.
    3. PASS 2 (Prompt 3) — Cache + q05/q95 kullanılarak integrator çalışır,
       Firestore hisse yazımı yapılır. (Henüz eklenmedi.)
    4. Ayın 1'iyse ek olarak SPK kalibrasyon çalıştırır.
    """
    now_utc = datetime.now(timezone.utc)
    logger.info(f"[scheduler] Günlük iş başladı — {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        db = _firebase_db()
        ticker_docs = {
            doc.id: doc.to_dict()
            for doc in db.collection("hisseler").where("kap_aktif", "==", True).stream()
        }
        total_tickers = len(ticker_docs)
        logger.info(f"[scheduler] {total_tickers} aktif hisse")

        ticker_list = sorted(tickers) if tickers else sorted(ticker_docs.keys())
        _end_date   = date.today().strftime("%Y-%m-%d")
        _start_date = "2021-01-01"

        # ── PASS 1: Hesaplama cache'i ────────────────────────────────────────
        # Her ticker için financial + emotional motor çalıştırılır.
        # Firestore hisse yazımı yapılmaz — bu Prompt 3'te tamamlanacak.
        ticker_cache: dict = {}
        ok = fail = 0

        for i, ticker in enumerate(ticker_list, 1):
            try:
                hd        = ticker_docs[ticker] or {}
                endeksler = hd.get("endeksler", []) or []
                sektor    = hd.get("industry") or hd.get("sektor") or ""

                df = bp.Ticker(ticker).history(start=_start_date, end=_end_date)
                if df.empty:
                    ticker_cache[ticker] = {"valid": False, "error": "empty OHLCV"}
                    fail += 1
                    continue

                reviews = _yorumlar_oku(ticker, db)

                from kap_client import get_oda_count
                try:
                    kap_haber = get_oda_count(ticker, days=30)
                except Exception as e:
                    logger.warning(f'[{ticker}] KAP haber çekilemedi: {e}')
                    kap_haber = hd.get('kap_oda_30g', 0)

                f_result = financial_engine.calculate(
                    ticker, df,
                    endeksler=endeksler,
                    sektor=sektor,
                    kap_haber_sayisi=kap_haber,
                    corporate_action_dates=None,
                )
                e_result = emotional_engine.calculate(ticker, reviews)

                ticker_cache[ticker] = {
                    "f":     f_result,
                    "e":     e_result,
                    "df":    df,
                    "kap":   kap_haber,
                    "valid": f_result.spek_score is not None,
                    "error": None,
                }
                ok += 1

            except Exception as ex:
                ticker_cache[ticker] = {"valid": False, "error": str(ex)}
                logger.error(f"[{ticker}] {ex}")
                fail += 1

            if i % CRON_BATCH == 0:
                time.sleep(1)

        cache_success_count = sum(1 for c in ticker_cache.values() if "f" in c)
        logger.info(
            f"[scheduler] Pass 1 tamamlandı — "
            f"total_tickers={total_tickers} "
            f"cache_success_count={cache_success_count} "
            f"ok={ok} fail={fail}"
        )

        # ── q05/q95 robust kalibrasyon eşikleri ─────────────────────────────
        valid_scores = [
            cache["f"].spek_score
            for cache in ticker_cache.values()
            if cache.get("valid") is True
        ]
        valid_score_count = len(valid_scores)

        q05 = q95 = None
        if valid_score_count >= 100:
            q05 = float(np.percentile(valid_scores, 5))
            q95 = float(np.percentile(valid_scores, 95))

        if valid_score_count >= 100 and q05 is not None and q95 is not None and q95 > q05:
            db.collection("system_config").document("motor_thresholds").set({
                "spek_q05":               round(float(q05), 4),
                "spek_q95":               round(float(q95), 4),
                "spek_distribution_date": date.today().strftime("%Y-%m-%d"),
                "spek_universe_count":    valid_score_count,
                "spek_percentile_method": "q05_q95",
                "updated_at":             fb_firestore.SERVER_TIMESTAMP,
            }, merge=True)
            logger.info(
                f"[scheduler] Robust calibration — "
                f"valid_score_count={valid_score_count} "
                f"q05={q05:.4f} q95={q95:.4f}"
            )
        else:
            logger.warning(
                f"[scheduler] Robust calibration skipped: insufficient valid scores "
                f"(valid_score_count={valid_score_count})"
            )

        # ── PASS 2: integrator + Firestore hisse yazımı ─────────────────────
        pass2_total_count       = len(ticker_cache)
        pass2_written_count     = 0
        pass2_null_paynotu_count = 0
        pass2_error_count       = 0

        for j, (ticker, cache) in enumerate(ticker_cache.items(), 1):
            try:
                if not cache.get("valid") or "f" not in cache:
                    db.collection("hisseler").document(ticker).update({
                        "paynotu_skoru": None,
                        "has_paynotu":   False,
                        "paynotu_error": cache.get("error"),
                        "last_updated":  fb_firestore.SERVER_TIMESTAMP,
                    })
                    pass2_null_paynotu_count += 1
                    pass2_written_count += 1
                    # OHLCV başarısız olsa da finansal tablo verisi bağımsız hesaplanır
                    try:
                        _hd_fund = ticker_docs.get(ticker) or {}
                        _sector_group = (
                            _hd_fund.get("paynotu_sector_group") or
                            _hd_fund.get("financial_model") or
                            None
                        )
                        _sektor = (
                            _hd_fund.get("kap_alt_sektor") or
                            _hd_fund.get("kap_ana_sektor") or
                            _hd_fund.get("sektor") or
                            _hd_fund.get("sector") or
                            ""
                        )
                        _sector_profile = _hd_fund.get("sector_profile")
                        fund_res = fund_engine.calculate(
                            ticker,
                            sektor=_sektor,
                            sector_group=_sector_group,
                            sector_profile=_sector_profile,
                        )
                        db.collection("hisseler").document(ticker).update(
                            _build_fundamental_payload(fund_res)
                        )
                        logger.info(
                            f"[{ticker}] fund_engine OK (ohlcv_fail) — "
                            f"skor={fund_res.financial_score} "
                            f"quality={fund_res.financial_score_quality} "
                            f"label={fund_res.financial_score_label}"
                        )
                    except Exception as fund_err:
                        logger.warning(f"[{ticker}] fund_engine hatası (ohlcv_fail): {fund_err}")
                    continue

                final = integrator.calculate(cache["f"], cache["e"], q05, q95)

                _am = getattr(cache["f"], "anomaly_metrics", None)
                db.collection("hisseler").document(ticker).update({
                    "paynotu_skoru":           final.paynotu_score,
                    "has_paynotu":             final.paynotu_score is not None,
                    "halk_skoru":              final.emotional_score,
                    "raw_spek_score":          cache["f"].spek_score,
                    "anomali_skoru":           final.paynotu_score,
                    "emotional_risk":          final.emotional_risk,
                    "emotional_grip":          final.emotional_grip,
                    "grip_intensity":          final.grip_intensity,
                    "is_sentiment_divergence": final.is_sentiment_divergence,
                    "has_reviews":             final.has_reviews,
                    "kap_oda_30g":             cache["kap"],
                    "motor_detay":             _motor_detay_payload(cache["f"]),
                    "kategori":                cache["f"].kategori,
                    "financial_score":         fb_firestore.DELETE_FIELD,
                    "anomaly_metrics": {
                        "total_days":             _am.total_days,
                        "hard_count":             _am.hard_count,
                        "extreme_count":          _am.extreme_count,
                        "weighted_count":         _am.weighted_count,
                        "block_count":            _am.block_count,
                        "longest_streak":         _am.longest_streak,
                        "avg_streak":             _am.avg_streak,
                        "hhi":                    _am.hhi,
                        "recency_center":         _am.recency_center,
                        "r_activity":             _am.r_activity,
                        "r_streak":               _am.r_streak,
                        "anomaly_activity_score": _am.anomaly_activity_score,
                    } if _am is not None else fb_firestore.DELETE_FIELD,
                    "last_updated":            fb_firestore.SERVER_TIMESTAMP,
                })
                if final.paynotu_score is None:
                    pass2_null_paynotu_count += 1
                pass2_written_count += 1

                # ── Senaryo Classifier ──────────────────────────────────────
                # Bilinçli resilience: classifier hatası ana skoru etkilemez.
                try:
                    xu100 = financial_engine.xu100_returns
                    cached_df = cache.get("df")
                    if cached_df is None or xu100.empty:
                        logger.info(f"[{ticker}] scenario_classifier atlandı")
                    else:
                        bundle = scenario_classifier.classify(
                            ohlcv_df=cached_df,
                            xu100_series=xu100,
                            sector_baseline_df=None,
                            ticker=ticker,
                            kategori=cache["f"].kategori,
                            ipo_date=None,
                            current_date=date.today(),
                        )
                        db.collection("hisseler").document(ticker).update({
                            "scenarios": {
                                "classifier_version": bundle.classifier_version,
                                "total_window_days":  bundle.total_window_days,
                                "segments": [
                                    seg.model_dump(mode="json")
                                    for seg in bundle.segments
                                ],
                                "updated_at": fb_firestore.SERVER_TIMESTAMP,
                            }
                        })
                        logger.info(
                            f"[{ticker}] scenario_classifier OK — "
                            f"{len(bundle.segments)} segment"
                        )
                except Exception as scn_err:
                    logger.error(f"[{ticker}] scenario_classifier failed: {scn_err}")

                # ── Fundamental Engine ──────────────────────────────────────
                try:
                    _hd_fund      = ticker_docs.get(ticker) or {}
                    # Firestore KAP sector routing öncelik sırası:
                    # paynotu_sector_group > financial_model > kap_alt_sektor > kap_ana_sektor > sektor
                    _sector_group = (
                        _hd_fund.get("paynotu_sector_group") or
                        _hd_fund.get("financial_model") or
                        None
                    )
                    _sektor = (
                        _hd_fund.get("kap_alt_sektor") or
                        _hd_fund.get("kap_ana_sektor") or
                        _hd_fund.get("sektor") or
                        _hd_fund.get("sector") or
                        ""
                    )
                    _sector_profile = _hd_fund.get("sector_profile")
                    fund_res  = fund_engine.calculate(
                        ticker,
                        sektor=_sektor,
                        sector_group=_sector_group,
                        sector_profile=_sector_profile,
                    )
                    db.collection("hisseler").document(ticker).update(
                        _build_fundamental_payload(fund_res)
                    )
                    logger.info(
                        f"[{ticker}] fund_engine OK — "
                        f"skor={fund_res.financial_score} "
                        f"quality={fund_res.financial_score_quality} "
                        f"label={fund_res.financial_score_label}"
                    )
                except Exception as fund_err:
                    logger.warning(f"[{ticker}] fund_engine hatası: {fund_err}")

                logger.info(
                    f"[{j}/{pass2_total_count}] {ticker} → "
                    f"paynotu={final.paynotu_score} "
                    f"duy={final.emotional_score:.4f}"
                )

            except Exception as ex:
                logger.error(f"[{ticker}] Pass 2 hatası: {ex}")
                pass2_error_count += 1

            if j % CRON_BATCH == 0:
                time.sleep(1)

        logger.info(
            f"[scheduler] Pass 2 tamamlandı — "
            f"pass2_total_count={pass2_total_count} "
            f"pass2_written_count={pass2_written_count} "
            f"pass2_null_paynotu_count={pass2_null_paynotu_count} "
            f"pass2_error_count={pass2_error_count}"
        )

        logger.info(f"[scheduler] Skor tamamlandı — {ok} OK, {fail} hata")

        try:
            _guncelle_topsis_rank(db)
        except Exception as e:
            logger.error(f"[scheduler] Spek rank hatası: {e}")

        if now_utc.day == 1:
            logger.info("[scheduler] Ayın 1'i — SPK kalibrasyon başlıyor")
            try:
                run_calibration()
                logger.info("[scheduler] Kalibrasyon tamamlandı")
            except Exception as e:
                logger.error(f"[scheduler] Kalibrasyon hatası: {e}")

    except Exception as e:
        logger.error(f"[scheduler] Job hatası: {e}")


# ── FİNTABLES SYNC JOB ────────────────────────────────────────────────────────

FINTABLES_SECTOR_MAP: dict[int, str] = {
    1:  "Taş, Toprak, Çimento",
    2:  "Otomotiv",
    3:  "Bankacılık",
    4:  "Sigorta",
    5:  "Otomotiv Yan Sanayi",
    6:  "Gayrimenkul",
    7:  "Kimya ve Plastik",
    8:  "Bilişim ve Yazılım",
    9:  "Tarım, Hayvancılık, Balıkçılık",
    10: "Madencilik ve Taş Ocakçılığı",
    11: "Gıda ve İçecek",
    12: "Tekstil, Giyim ve Deri",
    13: "Mobilya ve Dekorasyon",
    14: "Kağıt ve Kağıt Ürünleri",
    15: "Ana Metal",
    16: "Dayanıklı Tüketim Ürünleri",
    17: "Enerji Üretim ve Dağıtım",
    18: "İnşaat",
    19: "Turizm",
    20: "Toptan ve Perakende Ticaret",
    21: "Ulaştırma",
    22: "Haberleşme",
    23: "Holding",
    24: "Aracı Kurum",
    25: "Finansal Kiralama",
    26: "Faktoring",
    27: "Spor",
    28: "İlaç ve Sağlık",
    29: "Savunma",
    30: "Destek ve Hizmet",
    31: "İmalat",
    32: "Cam, Seramik, Porselen",
    33: "Emeklilik",
    35: "Menkul Kıymet Yat. Ort.",
    36: "Girişim Sermayesi Yat. Ort.",
    37: "Ambalaj",
    38: "Metal Eşya ve Makine",
    39: "Varlık Yönetimi",
    44: "Enerji Teknolojileri",
    45: "Gıda Perakendeciliği",
    46: "Servis Taşımacılığı ve Araç Kiralama",
    47: "Teknolojik Ürün Ticareti",
    48: "Giyim, Tekstil ve Deri Ürünleri Perakendeciliği",
    49: "Tasarruf Finansman",
}

FINTABLES_SECTOR_TO_GROUP: dict[int, str] = {
    3:  "bank",
    4:  "insurance",
    33: "insurance",
    6:  "gyo",
    23: "holding",
    24: "financial_special",
    25: "financial_special",
    26: "financial_special",
    39: "financial_special",
    49: "financial_special",
    17: "energy_utility",
    44: "energy_utility",
    8:  "technology_operational",
    22: "technology_operational",
    29: "technology_operational",
    35: "investment_trust",
    36: "investment_trust",
    27: "service_operational",
    19: "service_operational",
    30: "service_operational",
    21: "transportation",
    46: "service_operational",
}


def _fmt_session(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.fullmatch(r'(\d{4})-(\d{4})', raw.strip())
    if not m:
        return None
    def ins(t: str) -> str:
        return t[:2] + ':' + t[2:]
    return ins(m.group(1)) + ' - ' + ins(m.group(2))


def _parse_fintables_symbols() -> tuple[dict, str]:
    scraper = cloudscraper.create_scraper()
    r = scraper.get('https://api.fintables.com/symbols.js/', timeout=30)
    r.raise_for_status()
    text = r.text

    es_val = re.search(r'const es\s*=\s*"([^"]+)"', text).group(1)

    mgmt_start = text.index('const mgmt = ') + len('const mgmt = ')
    mgmt_raw   = text[mgmt_start : text.index('const uwl = ')].strip().rstrip(';')
    mgmt: dict = json.loads(mgmt_raw)

    uwl_start = text.index('const uwl = ') + len('const uwl = ')
    uwl_raw   = text[uwl_start : text.index('window.symbols', uwl_start)].strip().rstrip(';')
    uwl: dict = json.loads(uwl_raw)

    sym_start = text.index('window.symbols = ') + len('window.symbols = ')
    sym_raw   = text[sym_start:].rstrip().rstrip(';')

    ef_json = '{"decimals": 2, "thousand": true}'
    ff_json = '{"decimals": 6, "thousand": true}'

    sym_fixed = sym_raw
    for var, val in [('ef', ef_json), ('ff', ff_json), ('es', f'"{es_val}"')]:
        sym_fixed = sym_fixed.replace(f': {var},', f': {val},').replace(f': {var}}}', f': {val}}}')

    def _sub(d: dict, m: re.Match) -> str:
        v = d.get(m.group(1))
        return 'null' if v is None else '"' + v + '"'

    sym_fixed = re.sub(r"mgmt\['([^']+)'\]", lambda m: _sub(mgmt, m), sym_fixed)
    sym_fixed = re.sub(r"uwl\['([^']+)'\]",  lambda m: _sub(uwl,  m), sym_fixed)

    symbols: dict = json.loads(sym_fixed)
    return {
        k: v for k, v in symbols.items()
        if isinstance(v, dict) and v.get('type') == 'equity'
    }, es_val


def fintables_sync_job():
    """Her gün 02:00 UTC çalışır."""
    logger.info("[fintables] Sync başladı")
    try:
        equities, es_val = _parse_fintables_symbols()
        logger.info(f"[fintables] {len(equities):,} equity parse edildi")
    except Exception as e:
        logger.error(f"[fintables] symbols.js parse hatası: {e}")
        return

    try:
        db = _firebase_db()
        fs_docs: dict[str, dict] = {
            doc.id: (doc.to_dict() or {})
            for doc in db.collection('hisseler').stream()
        }
    except Exception as e:
        logger.error(f"[fintables] Firestore okuma hatası: {e}")
        return

    BATCH_SIZE = 400
    batch = db.batch()
    batch_cnt = 0
    guncellenen = 0
    yeni_eklenen = 0

    def _commit():
        nonlocal batch, batch_cnt
        if batch_cnt:
            batch.commit()
            batch = db.batch()
            batch_cnt = 0

    for symbol in fs_docs.keys():
        eq = equities.get(symbol)
        if eq is None:
            continue
        updates: dict = {}
        title = (eq.get('title') or '').strip()
        if title:
            updates['name'] = title
        logo = eq.get('logo')
        if logo:
            updates['logo'] = logo
        session_raw = eq.get('session') or es_val
        saati = _fmt_session(session_raw)
        if saati:
            updates['islem_saati'] = saati
        # flags → fintables_sector_id + fintables_sector_title
        _flags = eq.get('flags') or []
        if isinstance(_flags, str):
            _flags = [_flags]
        _sector_id: int | None = None
        for _f in _flags:
            if str(_f).startswith('sector:'):
                try:
                    _sector_id = int(str(_f).split(':')[1])
                except ValueError:
                    pass
                break
        if _sector_id is not None:
            updates['fintables_sector_id']    = _sector_id
            updates['fintables_sector_title'] = FINTABLES_SECTOR_MAP.get(
                _sector_id, f"Sektör {_sector_id}"
            )
            _group = FINTABLES_SECTOR_TO_GROUP.get(_sector_id)
            if _group:
                updates['paynotu_sector_group'] = _group
        _sheet = eq.get('sheet_template')
        if _sheet:
            updates['fintables_sheet_template'] = _sheet
        if not updates:
            continue
        batch.update(db.collection('hisseler').document(symbol), updates)
        batch_cnt += 1
        guncellenen += 1
        if batch_cnt >= BATCH_SIZE:
            _commit()

    _commit()
    logger.info(f"[fintables] {guncellenen} mevcut hisse güncellendi")

    for symbol, data in equities.items():
        if symbol in fs_docs:
            continue
        session_raw = data.get('session') or es_val
        _nflags = data.get('flags') or []
        if isinstance(_nflags, str):
            _nflags = [_nflags]
        _nsector_id: int | None = None
        for _nf in _nflags:
            if str(_nf).startswith('sector:'):
                try:
                    _nsector_id = int(str(_nf).split(':')[1])
                except ValueError:
                    pass
                break
        new_doc: dict = {
            'symbol':       symbol,
            'name':         (data.get('title') or symbol).strip(),
            'logo':         data.get('logo'),
            'islem_saati':  _fmt_session(session_raw),
            'kap_aktif':    True,
            'temel_kaynak': 'fintables',
        }
        if _nsector_id is not None:
            new_doc['fintables_sector_id']    = _nsector_id
            new_doc['fintables_sector_title'] = FINTABLES_SECTOR_MAP.get(
                _nsector_id, f"Sektör {_nsector_id}"
            )
            _ngroup = FINTABLES_SECTOR_TO_GROUP.get(_nsector_id)
            if _ngroup:
                new_doc['paynotu_sector_group'] = _ngroup
        _nsheet = data.get('sheet_template')
        if _nsheet:
            new_doc['fintables_sheet_template'] = _nsheet
        batch.set(db.collection('hisseler').document(symbol), new_doc)
        batch_cnt += 1
        yeni_eklenen += 1
        if batch_cnt >= BATCH_SIZE:
            _commit()

    _commit()
    logger.info(f"[fintables] Sync tamamlandı — {guncellenen} güncellendi, {yeni_eklenen} yeni")


# ── LIFESPAN ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db = _firebase_db()
        doc = db.collection("system_config").document("motor_thresholds").get()
        if doc.exists:
            financial_engine.reload_thresholds(doc.to_dict())
            logger.info("[startup] Firestore'dan motor eşikleri yüklendi")
    except Exception:
        logger.exception("[startup] Firestore eşik yüklenemedi")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(daily_job,          CronTrigger(hour=3, minute=0), id="daily_score")
    scheduler.add_job(fintables_sync_job, CronTrigger(hour=2, minute=0), id="fintables_sync")
    scheduler.start()
    logger.info("[startup] APScheduler başlatıldı — daily_score 03:00 UTC, fintables_sync 02:00 UTC")

    yield

    scheduler.shutdown(wait=False)
    logger.info("[shutdown] APScheduler durduruldu")


# ── FASTAPI APP ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="PayNotu Skor API",
    description="Spek motoru + duygusal motor — PayNotu skorlama sistemi",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── YARDIMCI: Yorumları oku ───────────────────────────────────────────────────

def _yorumlar_oku(ticker: str, db) -> list[Review]:
    reviews: list[Review] = []
    for doc in db.collection("hisseler").document(ticker).collection("yorumlar").stream():
        d = doc.to_dict()
        try:
            ts_raw = d.get("tarih") or d.get("timestamp")
            if ts_raw is None:
                ts = datetime.now(timezone.utc)
            elif hasattr(ts_raw, "seconds"):
                ts = datetime.fromtimestamp(ts_raw.seconds, tz=timezone.utc)
            elif isinstance(ts_raw, datetime):
                ts = ts_raw
            else:
                ts = datetime.now(timezone.utc)
            pos = d.get("position") or d.get("pozisyon") or "TUT"
            reviews.append(Review(
                user_id=doc.id,
                star=float(d.get("puan", 3)),
                timestamp=ts,
                user_reputation=float(d.get("agirlik", 1.0)),
                is_churned=bool(d.get("is_churned", False)),
                text_sentiment=float(d.get("text_sentiment", 0.0)),
                nps_score=d.get("nps_score"),
                position=pos,
            ))
        except Exception:
            continue
    return reviews


# ── ENDPOİNTLER ──────────────────────────────────────────────────────────────

# ── CANLI / GECİKMELİ FİYAT ENDPOINTİ ────────────────────────────────────────
# NOT:
# - Firestore'a fiyat yazmaz.
# - Sadece detay ekranı açıkken Flutter tarafından çağrılır.
# - Aynı hisse için kısa süre içinde tekrar borsapy çağrısı yapmamak için
#   in-memory cache kullanır.
_QUOTE_CACHE: dict[str, dict] = {}
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "300"))
QUOTE_DELAY_MINUTES = int(os.getenv("QUOTE_DELAY_MINUTES", "15"))
QUOTE_LOOKBACK_DAYS = int(os.getenv("QUOTE_LOOKBACK_DAYS", "450"))

_QUOTE_LITE_CACHE: dict[str, dict] = {}
QUOTE_LITE_CACHE_TTL = 60  # saniye — anlık fiyat, sık yenilenir

# İş Yatırım OneEndeks singleton — quote-lite birincil kaynağı
_ISY_PROVIDER: IsYatirimProvider | None = None

def _get_isy_provider() -> IsYatirimProvider:
    global _ISY_PROVIDER
    if _ISY_PROVIDER is None:
        _ISY_PROVIDER = IsYatirimProvider()
    return _ISY_PROVIDER

_DIVIDEND_YIELD_CACHE: dict[str, dict] = {}
_DIVIDEND_YIELD_TTL_SECONDS = 24 * 60 * 60

def _safe_pos_float(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _teorik_limitler(teorik_baz: float) -> dict:
    """Baz fiyattan teorik taban/tavan hesaplar. Saf fonksiyon."""
    try:
        _MARJI = 0.10
        adim = _bist_fiyat_adimi(teorik_baz)
        taban = round(math.ceil(round(teorik_baz * (1 - _MARJI) / adim, 9)) * adim, 2)
        tavan = round(math.floor(round(teorik_baz * (1 + _MARJI) / adim, 9)) * adim, 2)
        return {
            "teorik_taban_fiyat":     taban,
            "teorik_tavan_fiyat":     tavan,
            "fiyat_marji_yuzde":      10.0,
            "fiyat_adimi":            adim,
            "teorik_limit_kaynagi":   "bist_marji_010_adim_yuvarlanmis",
            "teorik_limit_baz_fiyat": round(teorik_baz, 2),
        }
    except Exception:
        return {
            "teorik_taban_fiyat":     None,
            "teorik_tavan_fiyat":     None,
            "fiyat_marji_yuzde":      None,
            "fiyat_adimi":            None,
            "teorik_limit_kaynagi":   None,
            "teorik_limit_baz_fiyat": None,
        }


def _quote_lite_via_isyatirim_full(ticker: str) -> dict:
    """
    İş Yatırım OneEndeks API üzerinden hızlı fiyat verisi döner.
    Döner: {"payload": dict|None, "ticker_not_found": bool}
    """
    _t0 = time.time()
    try:
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore", DeprecationWarning)
            q = _get_isy_provider().get_realtime_quote(ticker)

        son_fiyat  = _safe_pos_float(q.get("last"))
        teorik_baz = _safe_pos_float(q.get("close"))
        gun_yuksek = _safe_pos_float(q.get("high"))
        gun_dusuk  = _safe_pos_float(q.get("low"))
        hacim      = q.get("volume")

        if not son_fiyat:
            return {"payload": None, "ticker_not_found": False}

        gunluk_degisim: float | None = None
        if son_fiyat and teorik_baz:
            gunluk_degisim = round((son_fiyat / teorik_baz - 1) * 100, 2)
        else:
            raw_chp = q.get("change_percent")
            if raw_chp is not None:
                try:
                    gunluk_degisim = round(float(raw_chp), 2)
                except (TypeError, ValueError):
                    pass

        limitler = _teorik_limitler(teorik_baz) if teorik_baz else {
            "teorik_taban_fiyat": None, "teorik_tavan_fiyat": None,
            "fiyat_marji_yuzde": None, "fiyat_adimi": None,
            "teorik_limit_kaynagi": None, "teorik_limit_baz_fiyat": None,
        }

        guncelleme_str: str | None = None
        if q.get("update_time"):
            try:
                guncelleme_str = q["update_time"].isoformat()
            except Exception:
                pass

        elapsed_ms = round((time.time() - _t0) * 1000)
        logger.info(f"[quote-lite] {ticker} isyatirim: {elapsed_ms}ms")

        payload = {
            "symbol":                  ticker,
            "fiyat":                   round(son_fiyat, 2),
            "gunluk_degisim_yuzde":    gunluk_degisim,
            "gun_ici_dusuk_fiyat":     round(gun_dusuk, 2) if gun_dusuk else None,
            "gun_ici_yuksek_fiyat":    round(gun_yuksek, 2) if gun_yuksek else None,
            "onceki_kapanis":          round(teorik_baz, 2) if teorik_baz else None,
            "toplam_islem_hacmi":      int(hacim) if hacim else None,
            **limitler,
            "para_birimi":             "TRY",
            "borsa":                   "BIST",
            "lite":                    True,
            "fiyat_kaynagi":           "isyatirim_oneendeks",
            "fiyat_araligi_kaynagi":   "isyatirim_oneendeks_quote_lite",
            "fiyat_gecikme_dk":        0,
            "fiyat_guncelleme_tarihi": guncelleme_str or datetime.now(timezone.utc).isoformat(),
        }
        return {"payload": payload, "ticker_not_found": False}

    except _IsyTickerNotFound as e:
        elapsed_ms = round((time.time() - _t0) * 1000)
        logger.warning(f"[quote-lite] {ticker} isyatirim bulunamadi ({elapsed_ms}ms): {e}")
        return {"payload": None, "ticker_not_found": True}
    except _IsyAPIError as e:
        elapsed_ms = round((time.time() - _t0) * 1000)
        logger.warning(f"[quote-lite] {ticker} isyatirim api hata ({elapsed_ms}ms): {e}")
        return {"payload": None, "ticker_not_found": False}
    except Exception as e:
        elapsed_ms = round((time.time() - _t0) * 1000)
        logger.warning(f"[quote-lite] {ticker} isyatirim beklenmedik hata ({elapsed_ms}ms): {e}")
        return {"payload": None, "ticker_not_found": False}


# Eski isim alias — kod boyunca eski çağrı varsa çalışmaya devam etsin
def _quote_lite_via_isyatirim(ticker: str) -> dict | None:
    return _quote_lite_via_isyatirim_full(ticker)["payload"]


def _quote_lite_via_borsapy(ticker: str) -> dict:
    """
    borsapy fast_info + info ile hızlı fiyat verisi döner (fallback).
    Cold miss ~6-9s sürebilir.
    """
    def _do_fast_info():
        try:
            return bp.Ticker(ticker).fast_info.todict()
        except Exception as e:
            logger.warning(f"[quote-lite] {ticker} fast_info hatası: {e}")
            return {}

    def _do_info():
        try:
            return bp.Ticker(ticker).info
        except Exception as e:
            logger.warning(f"[quote-lite] {ticker} info hatası: {e}")
            return {}

    _BORSAPY_LITE_TIMEOUT = 12  # saniye — geçerse boş dict döner
    _t0 = time.time()
    _pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        _fut_fi   = _pool.submit(_do_fast_info)
        _fut_info = _pool.submit(_do_info)
        try:
            fi       = _fut_fi.result(timeout=_BORSAPY_LITE_TIMEOUT)
        except concurrent.futures.TimeoutError:
            fi = {}
            logger.warning(f"[quote-lite] {ticker} borsapy fast_info timeout")
        try:
            info_obj = _fut_info.result(timeout=_BORSAPY_LITE_TIMEOUT)
        except concurrent.futures.TimeoutError:
            info_obj = {}
            logger.warning(f"[quote-lite] {ticker} borsapy info timeout")
    finally:
        _pool.shutdown(wait=False)  # takılı thread'leri bekleme

    elapsed_ms = round((time.time() - _t0) * 1000)
    logger.info(f"[quote-lite] {ticker} borsapy fallback: {elapsed_ms}ms")

    son_fiyat: float | None = None
    for k in ('last_price', 'regularMarketPrice', 'currentPrice', 'price'):
        son_fiyat = _safe_pos_float(fi.get(k))
        if son_fiyat:
            break
    if son_fiyat is None:
        for k in ('currentPrice', 'regularMarketPrice', 'price'):
            son_fiyat = _safe_pos_float(info_obj.get(k))
            if son_fiyat:
                break

    teorik_baz: float | None = None
    for k in ('previous_close', 'regularMarketPreviousClose', 'prev_close'):
        teorik_baz = _safe_pos_float(fi.get(k))
        if teorik_baz:
            break
    if teorik_baz is None:
        for k in ('prev_close', 'previous_close', 'regularMarketPreviousClose'):
            teorik_baz = _safe_pos_float(info_obj.get(k))
            if teorik_baz:
                break

    gunluk_degisim: float | None = None
    if son_fiyat and teorik_baz:
        gunluk_degisim = round((son_fiyat / teorik_baz - 1) * 100, 2)
    else:
        for k in ('regular_market_change_percent', 'regularMarketChangePercent'):
            v = fi.get(k)
            if v is not None:
                try:
                    gunluk_degisim = round(float(v), 2)
                    break
                except (TypeError, ValueError):
                    pass

    gun_ici_dusuk  = _safe_pos_float(fi.get('day_low'))
    gun_ici_yuksek = _safe_pos_float(fi.get('day_high'))

    limitler = _teorik_limitler(teorik_baz) if teorik_baz else {
        "teorik_taban_fiyat": None, "teorik_tavan_fiyat": None,
        "fiyat_marji_yuzde": None, "fiyat_adimi": None,
        "teorik_limit_kaynagi": None, "teorik_limit_baz_fiyat": None,
    }

    return {
        "symbol":                  ticker,
        "fiyat":                   round(son_fiyat, 2) if son_fiyat else None,
        "gunluk_degisim_yuzde":    gunluk_degisim,
        "gun_ici_dusuk_fiyat":     round(gun_ici_dusuk, 2) if gun_ici_dusuk else None,
        "gun_ici_yuksek_fiyat":    round(gun_ici_yuksek, 2) if gun_ici_yuksek else None,
        "onceki_kapanis":          round(teorik_baz, 2) if teorik_baz else None,
        "toplam_islem_hacmi":      None,
        **limitler,
        "para_birimi":             "TRY",
        "borsa":                   "BIST",
        "lite":                    True,
        "fiyat_kaynagi":           "borsapy_fallback",
        "fiyat_araligi_kaynagi":   "borsapy_fallback",
        "fiyat_gecikme_dk":        QUOTE_DELAY_MINUTES,
        "fiyat_guncelleme_tarihi": datetime.now(timezone.utc).isoformat(),
    }


def _quote_lite_payload(ticker: str) -> dict:
    """
    İş Yatırım OneEndeks birincil kaynak (~30–70ms cold).
    TickerNotFoundError → borsapy'e düşme (sembol her iki sistemde de yok).
    Diğer İş Yatırım hatalar → borsapy fallback (~6–9s cold).
    """
    _isy_result = _quote_lite_via_isyatirim_full(ticker)
    if _isy_result["payload"] is not None:
        return _isy_result["payload"]
    if _isy_result["ticker_not_found"]:
        # Symbol her iki sistemde de yok — hızlı boş döndür
        logger.warning(f"[quote-lite] {ticker} iki sistemde de bulunamadi, null payload")
        return {
            "symbol": ticker, "fiyat": None, "gunluk_degisim_yuzde": None,
            "gun_ici_dusuk_fiyat": None, "gun_ici_yuksek_fiyat": None,
            "onceki_kapanis": None, "toplam_islem_hacmi": None,
            "teorik_taban_fiyat": None, "teorik_tavan_fiyat": None,
            "fiyat_marji_yuzde": None, "fiyat_adimi": None,
            "teorik_limit_kaynagi": None, "teorik_limit_baz_fiyat": None,
            "para_birimi": "TRY", "borsa": "BIST", "lite": True,
            "fiyat_kaynagi": "not_found", "fiyat_araligi_kaynagi": "not_found",
            "fiyat_gecikme_dk": 0,
            "fiyat_guncelleme_tarihi": datetime.now(timezone.utc).isoformat(),
        }
    return _quote_lite_via_borsapy(ticker)


# XU100 benchmark cache — beta hesabı için her /quote'ta yeniden çekilmez
_BENCHMARK_CLOSE_CACHE: dict = {}
_BENCHMARK_CLOSE_TTL = 30 * 60  # 30 dakika


def _get_xu100_close_cached(start_date: str, end_date: str) -> pd.Series | None:
    """XU100 Close serisini cache'den veya borsapy'den alır. 30 dk TTL."""
    now_ts = time.time()
    cached = _BENCHMARK_CLOSE_CACHE.get("XU100")
    if cached is not None and (now_ts - cached["ts"]) <= _BENCHMARK_CLOSE_TTL:
        return cached["close"]
    try:
        xu100_df = bp.Ticker("XU100").history(start=start_date, end=end_date)
        close = _close_series(xu100_df)
        if not close.empty:
            _BENCHMARK_CLOSE_CACHE["XU100"] = {"ts": now_ts, "close": close}
            logger.info("[benchmark_cache] XU100 guncellendi")
            return close
    except Exception as e:
        logger.warning(f"[benchmark_cache] XU100 hatasi: {e}")
    return None


def _normalize_quote_ticker(ticker: str) -> str:
    """
    PayNotu sembol standardı:
    - A1CAP, THYAO, ASELS gibi BIST sembolleri
    - .IS eki kullanılmaz
    """
    return (ticker or "").upper().strip().replace(".IS", "")


def _close_series(df: pd.DataFrame) -> pd.Series:
    """
    Borsapy OHLCV DataFrame'inden temiz Close serisi üretir.
    Index'i gün bazına normalize eder ki hisse / XU100 getirileri
    ve hacim lookup aynı index formatında çalışsın.
    """
    if df is None or df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float)

    close = df["Close"].dropna().astype(float).copy()
    close.index = pd.DatetimeIndex(pd.to_datetime(close.index).date)
    close = close[close > 0]

    return close.sort_index()


def _volume_for_last_close(df: pd.DataFrame, close: pd.Series) -> int | None:
    """
    Son geçerli close gününün hacmini döndürür.
    _close_series index'i normalize ettiği için df index'ini de normalize ederek
    lookup yapar. Aksi halde hacim alanı gereksiz yere null kalabilir.
    """
    if df is None or df.empty or "Volume" not in df.columns or close.empty:
        return None

    try:
        volume = df["Volume"].dropna().astype(float).copy()
        volume.index = pd.DatetimeIndex(pd.to_datetime(volume.index).date)
        volume = volume.sort_index()

        son_index = close.index[-1]
        if son_index not in volume.index:
            return None

        hacim_raw = volume.loc[son_index]

        # Aynı güne birden fazla satır düşerse son değeri al.
        if isinstance(hacim_raw, pd.Series):
            hacim_raw = hacim_raw.iloc[-1]

        if pd.notna(hacim_raw):
            return int(float(hacim_raw))
    except Exception as e:
        logger.debug(f"[quote] hacim okunamadı: {e}")

    return None


def _rsi_14(close: pd.Series, period: int = 14) -> float | None:
    close = close.dropna().astype(float)

    if len(close) < period + 1:
        return None

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    last_loss = avg_loss.iloc[-1]

    if pd.isna(last_loss):
        return None

    if last_loss == 0:
        return 100.0

    rs = avg_gain.iloc[-1] / last_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    return round(float(rsi), 2)


def _beta_vs_xu100(stock_close: pd.Series, xu100_close: pd.Series | None = None) -> float | None:
    """
    Beta = hissenin günlük getirileri ile XU100 günlük getirilerinin kovaryansı
           / XU100 getirilerinin varyansı

    Firestore'a yazmaz. Quote endpoint yanıtına beta ekler.
    xu100_close verilmezse cache'den veya borsapy'den çeker.
    """
    try:
        if stock_close is None or len(stock_close) < 60:
            return None

        if xu100_close is None:
            start_date = stock_close.index.min().strftime("%Y-%m-%d")
            end_date   = stock_close.index.max().strftime("%Y-%m-%d")
            xu100_close = _get_xu100_close_cached(start_date, end_date)
            if xu100_close is None:
                # doğrudan çek (cache yazamadı)
                xu100_df    = bp.Ticker("XU100").history(start=start_date, end=end_date)
                xu100_close = _close_series(xu100_df)

        if xu100_close.empty or len(xu100_close) < 60:
            return None

        stock_ret = stock_close.pct_change().dropna()
        market_ret = xu100_close.pct_change().dropna()

        joined = pd.concat(
            [
                stock_ret.rename("stock"),
                market_ret.rename("market"),
            ],
            axis=1,
            join="inner",
        ).dropna()

        if len(joined) < 60:
            return None

        market_variance = float(joined["market"].var())

        if market_variance <= 1e-12:
            return None

        covariance = float(joined["stock"].cov(joined["market"]))
        beta = covariance / market_variance

        return round(float(beta), 4)

    except Exception as e:
        logger.warning(f"[quote] beta hesaplanamadı: {e}")
        return None


def _pct_change_from_close(close: pd.Series, n_back: int) -> float | None:
    """close[-1] / close[-n_back] - 1 hesaplar. Veri yetersizse None döner."""
    if len(close) < n_back:
        return None
    ref = float(close.iloc[-n_back])
    if ref <= 0:
        return None
    return round((float(close.iloc[-1]) / ref - 1.0) * 100.0, 2)


def _ytd_change_from_close(close: pd.Series) -> float | None:
    """Yılın ilk işlem gününden bu yana yüzdesel değişim."""
    current_year = date.today().year
    year_data = close[close.index.year == current_year]
    if year_data.empty:
        return None
    ref = float(year_data.iloc[0])
    if ref <= 0:
        return None
    return round((float(close.iloc[-1]) / ref - 1.0) * 100.0, 2)


def _get_dividend_yield_cached(symbol: str, son_fiyat: float) -> float | None:
    """Son 12 ayın temettüsünü borsapy'den çeker, 24 saat cache'ler."""
    now_ts = time.time()
    cached = _DIVIDEND_YIELD_CACHE.get(symbol)
    if cached is not None and (now_ts - cached["ts"]) <= _DIVIDEND_YIELD_TTL_SECONDS:
        logger.debug(f"[dividend_cache] {symbol} cache hit → {cached['value']}")
        return cached["value"]

    result: float | None = None
    try:
        div = bp.Ticker(symbol).dividends
        if div is not None and not div.empty and son_fiyat > 0:
            one_year_ago = pd.Timestamp(date.today() - timedelta(days=365))
            recent = div[pd.to_datetime(div.index) >= one_year_ago]
            if not recent.empty:
                col = "Amount" if "Amount" in recent.columns else recent.columns[0]
                annual_div = float(recent[col].sum())
                if annual_div > 0:
                    result = round(annual_div / son_fiyat * 100.0, 2)
    except Exception as e:
        logger.warning(f"[dividend_cache] {symbol} temettü hatası: {e}")

    _DIVIDEND_YIELD_CACHE[symbol] = {"value": result, "ts": now_ts}
    logger.debug(f"[dividend_cache] {symbol} cache miss → {result}")
    return result


def _bist_fiyat_adimi(fiyat: float) -> float:
    """BIST Pay Piyasası resmi fiyat adımı (tick size), baz fiyata göre."""
    if fiyat < 20:
        return 0.01
    if fiyat < 50:
        return 0.02
    if fiyat < 100:
        return 0.05
    if fiyat < 250:
        return 0.10
    if fiyat < 500:
        return 0.25
    if fiyat < 1000:
        return 0.50
    if fiyat < 2500:
        return 1.00
    return 2.50


def _quote_payload_from_borsapy(ticker: str) -> dict:
    """
    Borsapy üzerinden fiyat verisi çeker.
    Firestore'a yazmaz; sadece API response payload'ı üretir.

    Beklenen kolonlar:
    - Close
    - Volume opsiyonel
    """
    ticker = _normalize_quote_ticker(ticker)

    if not ticker:
        raise HTTPException(status_code=400, detail="ticker zorunlu")

    # Beta ve RSI için kısa pencere yetmez; varsayılan 450 takvim günü.
    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=QUOTE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    # ── Paralel fetch: history, fast_info, info, XU100 ──────────────────────
    _t0 = time.time()

    def _do_history():
        return bp.Ticker(ticker).history(start=start_date, end=end_date)

    def _do_fast_info():
        try:
            return bp.Ticker(ticker).fast_info.todict()
        except Exception as e:
            logger.warning(f"[quote] {ticker} fast_info hatası: {e}")
            return {}

    def _do_info():
        try:
            return bp.Ticker(ticker).info
        except Exception as e:
            logger.warning(f"[quote] {ticker} info hatası: {e}")
            return {}

    def _do_xu100():
        return _get_xu100_close_cached(start_date, end_date)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as _pool:
        _fut_hist  = _pool.submit(_do_history)
        _fut_fi    = _pool.submit(_do_fast_info)
        _fut_info  = _pool.submit(_do_info)
        _fut_xu100 = _pool.submit(_do_xu100)
        df         = _fut_hist.result()
        fi         = _fut_fi.result()
        _info_obj  = _fut_info.result()
        xu100_cl   = _fut_xu100.result()

    logger.debug(f"[quote] {ticker} paralel fetch: {time.time() - _t0:.2f}s")

    if df is None or df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} için fiyat verisi bulunamadı",
        )

    df = df.sort_index().copy()

    if "Close" not in df.columns:
        raise HTTPException(
            status_code=500,
            detail=f"{ticker} verisinde Close kolonu yok",
        )

    close = _close_series(df)

    if close.empty:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker} için geçerli kapanış/fiyat verisi yok",
        )

    son_fiyat = float(close.iloc[-1])

    onceki_fiyat = (
        float(close.iloc[-2])
        if len(close) >= 2
        else son_fiyat
    )

    hafta_ref = (
        float(close.iloc[-6])
        if len(close) >= 6
        else onceki_fiyat
    )

    gunluk_degisim_yuzde = (
        ((son_fiyat / onceki_fiyat) - 1.0) * 100.0
        if onceki_fiyat > 0
        else 0.0
    )

    haftalik_degisim_yuzde = (
        ((son_fiyat / hafta_ref) - 1.0) * 100.0
        if hafta_ref > 0
        else 0.0
    )

    # ── Fiyat Aralığı alanları ──────────────────────────────────────────────
    gun_ici_dusuk = gun_ici_yuksek = None
    _fa_fast_info_ok = False
    try:
        dlow  = fi.get("day_low")
        dhigh = fi.get("day_high")
        if dlow is not None:
            gun_ici_dusuk = round(float(dlow), 2)
        if dhigh is not None:
            gun_ici_yuksek = round(float(dhigh), 2)
        if gun_ici_dusuk is not None or gun_ici_yuksek is not None:
            _fa_fast_info_ok = True
    except Exception as e:
        logger.warning(f"[quote] {ticker} fast_info parse hatası: {e}")

    yillik_dip = yillik_zirve = None
    _fa_ohlcv_ok = False
    if "Low" in df.columns and "High" in df.columns:
        try:
            df252 = df.tail(252)
            if not df252.empty:
                low_min  = df252["Low"].dropna()
                high_max = df252["High"].dropna()
                if not low_min.empty:
                    yillik_dip = round(float(low_min.min()), 2)
                if not high_max.empty:
                    yillik_zirve = round(float(high_max.max()), 2)
                if yillik_dip is not None or yillik_zirve is not None:
                    _fa_ohlcv_ok = True
        except Exception as e:
            logger.warning(f"[quote] {ticker} OHLCV 12A hesap hatası: {e}")

    bant_konum = dipten_uzaklik = zirveye_uzaklik = None
    if yillik_dip is not None and yillik_zirve is not None and yillik_dip < yillik_zirve:
        bant_konum = round(
            max(0.0, min(100.0, (son_fiyat - yillik_dip) / (yillik_zirve - yillik_dip) * 100)),
            2,
        )
    if yillik_dip is not None and yillik_dip > 0:
        dipten_uzaklik = round(((son_fiyat / yillik_dip) - 1) * 100, 2)
    if yillik_zirve is not None and yillik_zirve > 0:
        zirveye_uzaklik = round(((son_fiyat / yillik_zirve) - 1) * 100, 2)

    # Teorik taban/tavan — baz fiyat öncelik zinciri, BIST marjı, adıma içeri yuvarlanır
    teorik_taban = teorik_tavan = None
    teorik_marji: float | None = None
    teorik_adim: float | None = None
    teorik_limit_kaynagi: str | None = None
    teorik_baz: float | None = None

    try:
        for _k in ('prev_close', 'previous_close', 'regularMarketPreviousClose'):
            _v = _info_obj.get(_k)
            if _v is not None:
                try:
                    _fv = float(_v)
                    if _fv > 0:
                        teorik_baz = _fv
                        break
                except (TypeError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"[quote] {ticker} baz fiyat (info) hatası: {e}")

    if teorik_baz is None and _fa_fast_info_ok:
        try:
            _fi_prev = fi.get('previous_close')
            if _fi_prev is not None and float(_fi_prev) > 0:
                teorik_baz = float(_fi_prev)
        except Exception:
            pass

    if teorik_baz is None and len(close) >= 2 and onceki_fiyat > 0:
        teorik_baz = onceki_fiyat

    if teorik_baz is not None:
        try:
            _MARJI = 0.10
            adim = _bist_fiyat_adimi(teorik_baz)
            ham_taban = teorik_baz * (1 - _MARJI)
            ham_tavan = teorik_baz * (1 + _MARJI)
            teorik_taban = round(math.ceil(round(ham_taban / adim, 9)) * adim, 2)
            teorik_tavan = round(math.floor(round(ham_tavan / adim, 9)) * adim, 2)
            teorik_marji = 10.0
            teorik_adim = adim
            teorik_limit_kaynagi = "bist_marji_010_adim_yuvarlanmis"
        except Exception as e:
            logger.warning(f"[quote] {ticker} teorik limit hesap hatası: {e}")

    # Resmi taban/tavan: borsapy doğrudan sağlamıyor → None
    taban = tavan = None

    if _fa_fast_info_ok and _fa_ohlcv_ok:
        fa_kaynak: str | None = "borsapy_tradingview_fast_info_ohlcv"
    elif _fa_ohlcv_ok:
        fa_kaynak = "borsapy_tradingview_ohlcv"
    elif _fa_fast_info_ok:
        fa_kaynak = "partial"
    else:
        fa_kaynak = None
    # ────────────────────────────────────────────────────────────────────────

    return {
        "symbol": ticker,
        "fiyat": round(son_fiyat, 2),
        "gunluk_degisim_yuzde": round(gunluk_degisim_yuzde, 2),
        "haftalik_degisim_yuzde": round(haftalik_degisim_yuzde, 2),
        "aylik_degisim_yuzde": _pct_change_from_close(close, 22),
        "uc_ay_degisim_yuzde": _pct_change_from_close(close, 64),
        "alti_ay_degisim_yuzde": _pct_change_from_close(close, 127),
        "ybb_degisim_yuzde": _ytd_change_from_close(close),
        "yillik_degisim_yuzde": _pct_change_from_close(close, 253),
        "temettu_verimi": _get_dividend_yield_cached(ticker, son_fiyat),
        "toplam_islem_hacmi": _volume_for_last_close(df, close),
        "rsi_14": _rsi_14(close),
        "beta": _beta_vs_xu100(close, xu100_cl),
        "gun_ici_dusuk_fiyat": gun_ici_dusuk,
        "gun_ici_yuksek_fiyat": gun_ici_yuksek,
        "yillik_dip_fiyat": yillik_dip,
        "yillik_zirve_fiyat": yillik_zirve,
        "taban_fiyat": taban,
        "tavan_fiyat": tavan,
        "teorik_taban_fiyat": teorik_taban,
        "teorik_tavan_fiyat": teorik_tavan,
        "fiyat_marji_yuzde": teorik_marji,
        "fiyat_adimi": teorik_adim,
        "teorik_limit_kaynagi": teorik_limit_kaynagi,
        "teorik_limit_baz_fiyat": round(teorik_baz, 2) if teorik_baz is not None else None,
        "yillik_bant_konum_yuzde": bant_konum,
        "yillik_dipten_uzaklik_yuzde": dipten_uzaklik,
        "yillik_zirveye_uzaklik_yuzde": zirveye_uzaklik,
        "fiyat_araligi_kaynagi": fa_kaynak,
        "para_birimi": "TRY",
        "borsa": "BIST",
        "fiyat_kaynagi": "borsapy",
        "fiyat_gecikme_dk": QUOTE_DELAY_MINUTES,
        "fiyat_guncelleme_tarihi": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/quote/{ticker}")
def get_quote(ticker: str):
    """
    Detay ekranı fiyat endpoint'i.

    Kullanım:
      GET /quote/A1CAP

    Davranış:
    - Firestore'a yazmaz.
    - Cache tazeyse borsapy'ye tekrar gitmez.
    - Cache süresi env ile değiştirilebilir:
        QUOTE_CACHE_TTL_SECONDS=60
    """
    ticker = _normalize_quote_ticker(ticker)

    if not ticker:
        raise HTTPException(status_code=400, detail="ticker zorunlu")

    now_ts = time.time()
    cached = _QUOTE_CACHE.get(ticker)

    if cached is not None:
        age = now_ts - cached["ts"]
        if age <= QUOTE_CACHE_TTL_SECONDS:
            return {
                **cached["payload"],
                "cache": True,
                "cache_age_seconds": round(age, 1),
            }

    payload = _quote_payload_from_borsapy(ticker)

    _QUOTE_CACHE[ticker] = {
        "ts": now_ts,
        "payload": payload,
    }

    return {
        **payload,
        "cache": False,
        "cache_age_seconds": 0,
    }


@app.get("/quote-lite/{ticker}")
def get_quote_lite(ticker: str):
    """
    Hızlı fiyat endpoint'i — İş Yatırım OneEndeks birincil (~30–70ms),
    borsapy fallback (~6–9s). Header fiyat, gün içi aralık, teorik limit döner.
    Ağır alanlar (RSI, beta, 12A dip/zirve, uzun dönem getiriler) için /quote kullanın.
    """
    ticker = _normalize_quote_ticker(ticker)
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker zorunlu")

    now_ts = time.time()
    cached = _QUOTE_LITE_CACHE.get(ticker)
    if cached is not None:
        age = now_ts - cached["ts"]
        if age <= QUOTE_LITE_CACHE_TTL:
            return {**cached["payload"], "cache": True, "cache_age_seconds": round(age, 1)}

    payload = _quote_lite_payload(ticker)
    _QUOTE_LITE_CACHE[ticker] = {"ts": now_ts, "payload": payload}
    return {**payload, "cache": False, "cache_age_seconds": 0}


# ── GETİRİ KARŞILAŞTIRMASI ────────────────────────────────────────────────────

_COMPARE_CACHE: dict[str, dict] = {}
_COMPARE_CACHE_TTL = 60 * 60  # 60 dakika

# Sembol bağımsız piyasa verisi cache (XU100, USD, EUR, altın, faiz)
_MARKET_DATA_CACHE: dict = {}
_MARKET_CACHE_TTL = 60 * 60  # 60 dakika


def _fetch_market_data(lookback: int, evds_start: str, evds_end: str, api_key: str | None) -> dict:
    """
    XU100, USD/TRY, EUR/TRY, altın ve faiz verilerini paralel olarak çeker.
    Sonuçlar _MARKET_DATA_CACHE'e yazılır; TTL geçmedikçe tekrar fetch edilmez.
    """
    now_ts = time.time()
    cached = _MARKET_DATA_CACHE.get("data")
    if cached is not None and (now_ts - cached["ts"]) <= _MARKET_CACHE_TTL:
        return cached

    m: dict = {
        "ts":        now_ts,
        "bist100":   None,
        "usdtry":    None,
        "eurtry":    None,
        "altin":     None,
        "faiz_oran": None,
    }

    def _do_bist():
        return _fetch_borsapy_ohlcv("XU100", lookback)

    def _do_usd():
        return _fetch_evds_series("TP.DK.USD.A.YTL", evds_start, evds_end)

    def _do_eur():
        return _fetch_evds_series("TP.DK.EUR.A.YTL", evds_start, evds_end)

    def _do_gold():
        return _fetch_gold_try_series(lookback)

    def _do_faiz():
        s = _fetch_evds_series("TP.APIFON4", evds_start, evds_end)
        if s is not None and not s.empty:
            return _safe_float(s.iloc[-1])
        return None

    tasks: dict = {"bist100": _do_bist}
    if api_key:
        tasks["usdtry"]    = _do_usd
        tasks["eurtry"]    = _do_eur
        tasks["altin"]     = _do_gold
        tasks["faiz_oran"] = _do_faiz

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {key: pool.submit(fn) for key, fn in tasks.items()}
        for key, fut in futures.items():
            try:
                m[key] = fut.result()
            except Exception as exc:
                logger.warning(f"[market_cache] {key} hatası: {exc}")

    _MARKET_DATA_CACHE["data"] = m
    logger.info("[market_cache] Piyasa verisi güncellendi")
    return m


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _calculate_period_returns(series: pd.Series) -> dict:
    """Tarihe göre sıralı fiyat serisinden dönemsel getiri yüzdeleri (%) üretir."""
    PERIODS = ("1G", "1H", "1A", "3A", "6A", "YBB", "1Y")
    result: dict = {p: None for p in PERIODS}
    if series is None or len(series) < 2:
        return result

    son = series.iloc[-1]
    for period, n in {"1G": 1, "1H": 5, "1A": 21, "3A": 63, "6A": 126, "1Y": 252}.items():
        if len(series) > n:
            baz = _safe_float(series.iloc[-(n + 1)])
            if baz and baz > 0:
                result[period] = round((son / baz - 1) * 100, 2)

    try:
        ytd = series[series.index >= pd.Timestamp(f"{date.today().year}-01-01")]
        if len(ytd) >= 2:
            baz_ytd = _safe_float(ytd.iloc[0])
            if baz_ytd and baz_ytd > 0:
                result["YBB"] = round((son / baz_ytd - 1) * 100, 2)
    except Exception:
        pass

    return result


def _calculate_simple_interest_returns(annual_rate: float) -> dict:
    """Yıllık basit faiz oranından (%) dönemsel getiri yüzdeleri üretir."""
    PERIODS = ("1G", "1H", "1A", "3A", "6A", "YBB", "1Y")
    result: dict = {p: None for p in PERIODS}
    if annual_rate is None:
        return result
    for period, days in {"1G": 1, "1H": 7, "1A": 30, "3A": 91, "6A": 182, "1Y": 365}.items():
        result[period] = round(annual_rate / 365 * days, 2)
    ytd_days = max((date.today() - date(date.today().year, 1, 1)).days, 1)
    result["YBB"] = round(annual_rate / 365 * ytd_days, 2)
    return result


def _fetch_evds_series(series_name: str, start_date: str, end_date: str) -> pd.Series | None:
    """EVDS API'den günlük seri çeker. Tarihler 'DD-MM-YYYY' formatında olmalı."""
    api_key = os.getenv("TCMB_API_KEY")
    if not api_key:
        return None
    try:
        from evds import evdsAPI
        client = evdsAPI(api_key)
        df = client.get_data([series_name], startdate=start_date, enddate=end_date)
        if df is None or df.empty or "Tarih" not in df.columns:
            return None
        col = series_name if series_name in df.columns else next(
            (c for c in df.columns if c not in ("Tarih", "UNIXTIME")), None
        )
        if col is None:
            return None
        s = pd.Series(
            pd.to_numeric(df[col], errors="coerce").values,
            index=pd.to_datetime(df["Tarih"], dayfirst=True, errors="coerce"),
        ).dropna()
        s = s[~s.index.isna()]
        s.index = pd.DatetimeIndex([d.date() for d in s.index])
        s = s[s > 0].sort_index()
        return s if not s.empty else None
    except Exception as ex:
        logger.warning(f"[compare] EVDS {series_name} hatası: {ex}")
        return None


def _fetch_borsapy_ohlcv(symbol: str, lookback_days: int = 450) -> pd.Series | None:
    """borsapy OHLCV geçmişinden Close serisi döner."""
    try:
        end_dt   = date.today().strftime("%Y-%m-%d")
        start_dt = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        df = bp.Ticker(symbol).history(start=start_dt, end=end_dt)
        if df is None or df.empty:
            return None
        return _close_series(df)
    except Exception as ex:
        logger.warning(f"[compare] {symbol} borsapy hatası: {ex}")
        return None


def _fetch_gold_try_series(lookback_days: int = 450) -> pd.Series | None:
    """yfinance GC=F × EVDS USD/TRY → TL/gram altın serisi döner."""
    try:
        import yfinance as yf
        end_dt   = date.today()
        start_dt = end_dt - timedelta(days=lookback_days + 30)

        gc_df = yf.Ticker("GC=F").history(
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
        )
        if gc_df is None or gc_df.empty or "Close" not in gc_df.columns:
            return None

        ons = gc_df["Close"].dropna().astype(float).copy()
        ons.index = pd.DatetimeIndex([d.date() for d in ons.index])
        ons = ons[ons > 0].sort_index()

        usd_s = _fetch_evds_series(
            "TP.DK.USD.A.YTL",
            start_dt.strftime("%d-%m-%Y"),
            end_dt.strftime("%d-%m-%Y"),
        )
        if usd_s is None or usd_s.empty:
            return None

        combined = pd.concat([ons.rename("ons"), usd_s.rename("usd")], axis=1, join="inner")
        if combined.empty:
            return None

        gram = (combined["ons"] / 31.1035 * combined["usd"]).dropna()
        gram = gram[gram > 0].sort_index()
        return gram if not gram.empty else None
    except Exception as ex:
        logger.warning(f"[compare] Altın TRY hatası: {ex}")
        return None


def _compare_payload(symbol: str) -> dict:
    PERIODS   = ("1G", "1H", "1A", "3A", "6A", "YBB", "1Y")
    NULL_RET  = {p: None for p in PERIODS}
    LOOKBACK  = 450
    now       = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    source_info: dict = {}

    api_key    = os.getenv("TCMB_API_KEY")
    evds_start = (date.today() - timedelta(days=LOOKBACK + 30)).strftime("%d-%m-%Y")
    evds_end   = date.today().strftime("%d-%m-%Y")

    # ── Hisse OHLCV + piyasa verisi paralel fetch ──────────────────────────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fut_sym    = pool.submit(_fetch_borsapy_ohlcv, symbol, LOOKBACK)
        fut_market = pool.submit(_fetch_market_data, LOOKBACK, evds_start, evds_end, api_key)
        sym_s    = fut_sym.result()
        market   = fut_market.result()

    # ── Hisse getirisi ─────────────────────────────────────────────────────────
    sym_ret = dict(NULL_RET)
    if sym_s is not None and len(sym_s) >= 2:
        sym_ret = _calculate_period_returns(sym_s)
        source_info["symbol"] = "borsapy_tradingview_ohlcv"
    else:
        errors.append(f"{symbol}: OHLCV verisi yetersiz")
        source_info["symbol"] = "hata"

    # ── BIST100 ────────────────────────────────────────────────────────────────
    bist_ret = dict(NULL_RET)
    bist_s = market.get("bist100")
    if bist_s is not None and len(bist_s) >= 2:
        bist_ret = _calculate_period_returns(bist_s)
        source_info["bist100"] = "borsapy_XU100"
    else:
        errors.append("XU100: veri yetersiz")
        source_info["bist100"] = "hata"

    # ── EVDS varlıkları ────────────────────────────────────────────────────────
    usd_ret = dict(NULL_RET)
    eur_ret = dict(NULL_RET)
    alt_ret = dict(NULL_RET)
    fiz_ret = dict(NULL_RET)

    if not api_key:
        errors.append("TCMB_API_KEY eksik — EVDS verileri atlandı")
        for k in ("usdtry", "eurtry", "altin", "faiz"):
            source_info[k] = "hata_api_key_eksik"
    else:
        usd_s = market.get("usdtry")
        if usd_s is not None and len(usd_s) >= 2:
            usd_ret = _calculate_period_returns(usd_s)
            source_info["usdtry"] = "evds_TP.DK.USD.A.YTL"
        else:
            errors.append("USD/TRY: veri yetersiz")
            source_info["usdtry"] = "hata"

        eur_s = market.get("eurtry")
        if eur_s is not None and len(eur_s) >= 2:
            eur_ret = _calculate_period_returns(eur_s)
            source_info["eurtry"] = "evds_TP.DK.EUR.A.YTL"
        else:
            errors.append("EUR/TRY: veri yetersiz")
            source_info["eurtry"] = "hata"

        alt_s = market.get("altin")
        if alt_s is not None and len(alt_s) >= 2:
            alt_ret = _calculate_period_returns(alt_s)
            source_info["altin"] = "yfinance_GC_F_x_evds_usdtry"
        else:
            errors.append("Altın TRY: veri yetersiz")
            source_info["altin"] = "hata"

        faiz_oran = market.get("faiz_oran")
        if faiz_oran is not None:
            fiz_ret = _calculate_simple_interest_returns(faiz_oran)
            source_info["faiz"] = "evds_TP.APIFON4"
        else:
            errors.append("Faiz: veri alınamadı")
            source_info["faiz"] = "hata"

    periods = {
        p: {
            "symbol":  sym_ret[p],
            "altin":   alt_ret[p],
            "usdtry":  usd_ret[p],
            "eurtry":  eur_ret[p],
            "bist100": bist_ret[p],
            "faiz":    fiz_ret[p],
        }
        for p in PERIODS
    }

    return {
        "symbol":     symbol,
        "updated_at": now,
        "periods":    periods,
        "labels": {
            "symbol":  symbol,
            "altin":   "Altın (TL/gr)",
            "usdtry":  "USD/TRY",
            "eurtry":  "EUR/TRY",
            "bist100": "BIST 100",
            "faiz":    "Faiz (TCMB AOFM)",
        },
        "source_info": source_info,
        "notes": [
            "Altın değeri ons altın fiyatının TCMB USD kuru ile TL/gram karşılığına çevrilmesiyle hesaplanır.",
            "Faiz değeri TCMB AOFM yıllık oranından basit dönemsel orana çevrilmiştir; politika faizi değildir.",
        ],
        "errors": errors,
    }


# ── GRUP KARŞILAŞTIRMASI ──────────────────────────────────────────────────────

SECTOR_NAME_ALIASES: dict[str, str] = {
    "TEKSTİL GİYİM EŞYASI VE DERİ": "TEKSTİL, GİYİM EŞYASI VE DERİ",
}


def _normalize_sector_name(name: str | None) -> str:
    if not name:
        return ""
    normalized = " ".join(name.strip().split())
    return SECTOR_NAME_ALIASES.get(normalized, normalized)


_ALL_HISSE_CACHE: list[dict] | None = None
_ALL_HISSE_CACHE_AT: float = 0.0
_ALL_HISSE_CACHE_TTL_SECONDS: int = 3600
_ALL_HISSE_CACHE_LOCK = _threading.Lock()


def _firestore_val(v: dict):
    """Firestore REST format'tan Python'a donustur."""
    if "stringValue" in v:
        return v["stringValue"]
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "nullValue" in v:
        return None
    if "mapValue" in v:
        return {k: _firestore_val(fv) for k, fv in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [_firestore_val(av) for av in v["arrayValue"].get("values", [])]
    return None  # bytes, reference, timestamp


def _fetch_hisse_via_rest() -> list[dict]:
    """Firestore REST API ile aktif hisseleri cek — gRPC tamamen bypass."""
    import google.auth.transport.requests as _gtr
    app = firebase_admin.get_app()
    google_cred = app.credential.get_credential()
    if not google_cred.valid:
        google_cred.refresh(_gtr.Request())
    token = google_cred.token

    # project_id: service account email'den cikar
    sa_email = google_cred.service_account_email  # xxx@project.iam.gserviceaccount.com
    project_id = sa_email.split("@")[1].replace(".iam.gserviceaccount.com", "")

    base = (
        f"https://firestore.googleapis.com/v1/"
        f"projects/{project_id}/databases/(default)/documents/hisseler"
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    result: list[dict] = []
    page_token: str | None = None
    while True:
        params: dict = {"pageSize": 300}
        if page_token:
            params["pageToken"] = page_token
        resp = _requests.get(base, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        for doc in data.get("documents", []):
            doc_id = doc["name"].split("/")[-1]
            d = {k: _firestore_val(fv) for k, fv in doc.get("fields", {}).items()}
            if d.get("kap_aktif") is not True:
                continue
            d["_symbol"] = doc_id
            result.append(d)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return result


def _fetch_all_hisse_snapshot(db) -> tuple[list[dict], bool]:
    """Tum kap_aktif=True hisselerin snapshot'i. Thread-safe, TTL 3600s.
    REST API kullanir (gRPC bypass). stale=True: hata, eski cache."""
    global _ALL_HISSE_CACHE, _ALL_HISSE_CACHE_AT

    now = time.time()
    if _ALL_HISSE_CACHE is not None and (now - _ALL_HISSE_CACHE_AT) < _ALL_HISSE_CACHE_TTL_SECONDS:
        return _ALL_HISSE_CACHE, False

    with _ALL_HISSE_CACHE_LOCK:
        now = time.time()
        if _ALL_HISSE_CACHE is not None and (now - _ALL_HISSE_CACHE_AT) < _ALL_HISSE_CACHE_TTL_SECONDS:
            return _ALL_HISSE_CACHE, False
        try:
            snapshot = _fetch_hisse_via_rest()
            _ALL_HISSE_CACHE = snapshot
            _ALL_HISSE_CACHE_AT = time.time()
            logger.info(f"[group_compare] REST snapshot yenilendi: {len(snapshot)} aktif hisse")
            return snapshot, False
        except Exception as exc:
            logger.warning(
                f"[group_compare] REST snapshot hatasi: {type(exc).__name__}: {exc}\n"
                + _traceback.format_exc()
            )
            if _ALL_HISSE_CACHE is not None:
                return _ALL_HISSE_CACHE, True
            raise


def _sym(d: dict) -> str:
    return d.get("_symbol") or d.get("symbol") or ""


def _build_group(snapshot: list[dict], target: dict) -> dict | None:
    """Grup seçim hiyerarşisi:
    A: kap_alt_sektor ≥5 → normal
    B: kap_alt_sektor 3-4 → limited (ana sektöre genişleme YOK)
    C: kap_alt_sektor <3 → kap_ana_sektor ∩ paynotu_sector_group
    D: paynotu_sector_group
    E: None — BIST geneli fallback yasak
    """
    target_alt = _normalize_sector_name(target.get("kap_alt_sektor"))
    target_ana = _normalize_sector_name(target.get("kap_ana_sektor"))
    target_sg  = target.get("paynotu_sector_group") or ""

    def _syms_where(fn) -> list[str]:
        return [_sym(d) for d in snapshot if fn(d) and _sym(d)]

    # A / B — kap_alt_sektor
    if target_alt:
        alt_syms = _syms_where(
            lambda d: _normalize_sector_name(d.get("kap_alt_sektor")) == target_alt
        )
        n = len(alt_syms)
        if n >= 3:
            return {
                "level": "kap_alt_sektor",
                "name": target_alt,
                "fallback_used": False,
                "limited_group": n < 5,
                "members": alt_syms,
                "model_group": target_sg,
            }

    # C — kap_ana_sektor ∩ paynotu_sector_group
    if target_ana and target_sg:
        inter_syms = _syms_where(
            lambda d: (
                _normalize_sector_name(d.get("kap_ana_sektor")) == target_ana
                and d.get("paynotu_sector_group") == target_sg
            )
        )
        n = len(inter_syms)
        if n >= 3:
            return {
                "level": "kap_ana_sektor_and_model_group",
                "name": target_ana,
                "fallback_used": True,
                "limited_group": n < 5,
                "members": inter_syms,
                "model_group": target_sg,
            }

    # D — paynotu_sector_group
    if target_sg:
        sg_syms = _syms_where(lambda d: d.get("paynotu_sector_group") == target_sg)
        n = len(sg_syms)
        if n >= 3:
            return {
                "level": "paynotu_sector_group",
                "name": target_sg,
                "fallback_used": True,
                "limited_group": n < 5,
                "members": sg_syms,
                "model_group": target_sg,
            }

    return None


def _safe_float(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _temel_val(d: dict, key: str) -> float | None:
    # 1. flat top-level alan: temel_roe, temel_pd_dd, temel_fk...
    v = _safe_float(d.get(f"temel_{key}"))
    if v is not None:
        return v
    # 2. motor_detay.temel nested map (F/K buradan geliyor)
    motor = d.get("motor_detay")
    if isinstance(motor, dict):
        temel = motor.get("temel")
        if isinstance(temel, dict):
            return _safe_float(temel.get(key))
    return None


def _compute_metric_stats(
    values: list[float | None],
    selected: float | None,
    direction: str,
) -> dict:
    valid = [v for v in values if v is not None]
    n = len(valid)
    result: dict = {
        "valid_count": n,
        "group_median": None,
        "group_average": None,
        "rank": None,
        "limited_data": n < 5,
    }
    if n >= 3:
        result["group_median"] = round(_statistics.median(valid), 4)
        result["group_average"] = round(sum(valid) / n, 4)
    if selected is not None and n >= 3 and direction in ("ascending", "descending"):
        if direction == "ascending":
            sorted_unique = sorted(set(valid))
        else:
            sorted_unique = sorted(set(valid), reverse=True)
        rank_map = {v: i + 1 for i, v in enumerate(sorted_unique)}
        result["rank"] = rank_map.get(selected)
    return result


def _build_metric(
    label: str,
    vals: list[float | None],
    selected: float | None,
    member_count: int,
    unit: str,
    direction: str,
    extra: dict | None = None,
) -> dict | None:
    stats = _compute_metric_stats(vals, selected, direction)
    if stats["valid_count"] < 3:
        return None
    return {
        "label": label,
        "selected_value": selected,
        "group_member_count": member_count,
        "unit": unit,
        "direction": direction,
        "interpretation": "display_only",
        **(extra or {}),
        **stats,
    }


def _get_group_compare_payload(symbol: str, db) -> dict:
    logger.info(f"[group_compare] payload başladı: {symbol}")
    t0 = time.time()
    was_cold = _ALL_HISSE_CACHE is None or (t0 - _ALL_HISSE_CACHE_AT) >= _ALL_HISSE_CACHE_TTL_SECONDS

    try:
        snapshot, stale = _fetch_all_hisse_snapshot(db)
        logger.info(f"[group_compare] snapshot alındı: {len(snapshot)} hisse")
    except Exception as _snap_exc:
        logger.error(
            f"[group_compare] snapshot hatası (iç): {type(_snap_exc).__name__}: {_snap_exc}\n"
            + _traceback.format_exc()
        )
        raise HTTPException(status_code=503, detail="Grup verisi şu anda kullanılamıyor")

    target = next((d for d in snapshot if _sym(d) == symbol), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"{symbol} aktif hisseler arasında bulunamadı")

    model_group  = target.get("paynotu_sector_group") or ""
    cache_status = "stale" if stale else ("miss" if was_cold else "hit")

    target_sector_id    = target.get("fintables_sector_id")
    target_sector_title = target.get("fintables_sector_title")

    # ── Fintables birincil, kap_alt_sektor fallback ──
    if target_sector_id is not None:
        group_level = "fintables_sector"
        group_name  = target_sector_title or FINTABLES_SECTOR_MAP.get(
            target_sector_id, f"Sektör {target_sector_id}"
        )
        all_peers = [
            d for d in snapshot
            if _sym(d) != symbol
            and d.get("fintables_sector_id") == target_sector_id
        ]
    else:
        target_alt = _normalize_sector_name(target.get("kap_alt_sektor"))
        if not target_alt:
            elapsed = round((time.time() - t0) * 1000)
            logger.info(
                f"[group_compare] symbol={symbol} cache={cache_status} "
                f"sector=None elapsed_ms={elapsed}"
            )
            return {
                "symbol": symbol,
                "group": None,
                "companies": [],
                "available_metrics": {},
                "metric_summaries": {},
                "metrics": {},
                "members": [],
                "notes": ["Bu sembol için sektör bilgisi bulunamadı."],
                "reason": "no_sector",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "cache": not was_cold,
                "cache_age_seconds": round(time.time() - _ALL_HISSE_CACHE_AT, 1),
                "stale_cache": stale,
            }
        group_level = "kap_alt_sektor"
        group_name  = target_alt
        all_peers = [
            d for d in snapshot
            if _sym(d) != symbol
            and _normalize_sector_name(d.get("kap_alt_sektor")) == target_alt
        ]

    # Piyasa değerine göre büyükten küçüğe sırala; eksik değer en sona.
    # piyasa_degeri şu an Firestore'a yazılmıyor; finansal_skor proxy olarak kullanılıyor.
    # Gelecekte piyasa_degeri yazılırsa ölçek farkı (milyar TL > 10) nedeniyle otomatik kazanır.
    def _mc(d: dict) -> float:
        v = _safe_float(d.get("piyasa_degeri"))
        if v is not None and v > 0:
            return v
        fs = _safe_float(d.get("finansal_skor"))
        if fs is not None and fs > 0:
            return fs
        return -1.0

    peers_sorted = sorted(all_peers, key=_mc, reverse=True)
    selected_peers = peers_sorted[:5]
    actual_peer_count = len(selected_peers)
    limited_peer_group = len(all_peers) < 5

    # ── Şirket verisi ──
    def _name(d: dict) -> str:
        return d.get("company_name") or d.get("name") or _sym(d)

    def _company_metrics(d: dict) -> dict:
        m: dict = {}
        if model_group != "bank":
            m["fk"] = _temel_val(d, "fk")
        m["finansal_skor"] = _safe_float(d.get("finansal_skor"))
        m["paynotu_skoru"] = (
            _safe_float(d.get("paynotu_skoru"))
            if d.get("has_paynotu") is True else None
        )
        m["roe"]   = _temel_val(d, "roe")
        m["pd_dd"] = _temel_val(d, "pd_dd")
        return m

    companies: list[dict] = [
        {
            "symbol":     symbol,
            "name":       _name(target),
            "selected":   True,
            "market_cap": _safe_float(target.get("piyasa_degeri")),
            "metrics":    _company_metrics(target),
        }
    ]
    for d in selected_peers:
        companies.append({
            "symbol":     _sym(d),
            "name":       _name(d),
            "selected":   False,
            "market_cap": _safe_float(d.get("piyasa_degeri")),  # null — piyasa_degeri henüz yazılmıyor
            "metrics":    _company_metrics(d),
        })

    # ── Kullanılabilir metrikler ──
    _METRIC_DEFS = [
        ("fk",            "Fiyat/Kazanç",  "ratio"),
        ("finansal_skor", "Finansal Skor", "score"),
        ("paynotu_skoru", "PayNotu",        "score"),
        ("roe",           "ROE",            "percent"),
        ("pd_dd",         "PD/DD",          "ratio"),
    ]

    available_metrics: dict = {}
    metric_summaries: dict  = {}
    peer_companies = [c for c in companies if not c["selected"]]

    for key, label, unit in _METRIC_DEFS:
        if key == "fk" and model_group == "bank":
            continue
        available_metrics[key] = {"label": label, "unit": unit}
        peer_vals = [
            c["metrics"].get(key)
            for c in peer_companies
            if c["metrics"].get(key) is not None
        ]
        n = len(peer_vals)
        if n > 0:
            metric_summaries[key] = {
                "peer_average":     round(sum(peer_vals) / n, 4),
                "peer_median":      round(_statistics.median(peer_vals), 4),
                "valid_peer_count": n,
                "min":              round(min(peer_vals), 4),
                "max":              round(max(peer_vals), 4),
            }
        else:
            metric_summaries[key] = {
                "peer_average":     None,
                "peer_median":      None,
                "valid_peer_count": 0,
                "min":              None,
                "max":              None,
            }

    elapsed = round((time.time() - t0) * 1000)
    logger.info(
        f"[group_compare] symbol={symbol} cache={cache_status} "
        f"sector_source={group_level!r} group={group_name!r} "
        f"peers={actual_peer_count} limited={limited_peer_group} elapsed_ms={elapsed}"
    )

    return {
        "symbol": symbol,
        "group": {
            "level":              group_level,
            "name":               group_name,
            "member_count":       len(all_peers) + 1,
            "limited_peer_group": limited_peer_group,
        },
        "peer_selection": {
            "method":                    "market_cap_desc",
            "label":                     "Piyasa değerine göre en büyük rakipler",
            "requested_peer_count":      5,
            "actual_peer_count":         actual_peer_count,
            "selected_company_included": True,
        },
        "companies":         companies,
        "available_metrics": available_metrics,
        "metric_summaries":  metric_summaries,
        "members": [
            {"symbol": c["symbol"], "name": c["name"], "selected": c["selected"]}
            for c in companies
        ],
        "metrics": {},
        "notes": [
            "Rakipler piyasa değerine göre seçilmektedir.",
            "Eksik değerler yalnızca ilgili metriğin hesabından çıkarılmıştır.",
        ],
        "updated_at":       datetime.now(timezone.utc).isoformat(),
        "cache":            not was_cold,
        "cache_age_seconds": round(time.time() - _ALL_HISSE_CACHE_AT, 1),
        "stale_cache":      stale,
    }


@app.get("/group-compare/{symbol}")
def get_group_compare(symbol: str):
    """Hissenin benzer şirket grubundaki sayısal konumu. Yalnızca mevcut Firestore verisi."""
    logger.info(f"[gc_diag] A: endpoint cagrildi symbol_raw={symbol!r}")
    symbol = _normalize_quote_ticker(symbol)
    logger.info(f"[gc_diag] B: normalize tamam symbol={symbol!r}")
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol zorunlu")
    try:
        logger.info("[gc_diag] C: firebase_db cagrilmadan once")
        db = _firebase_db()
        logger.info("[gc_diag] D: firebase_db tamam, payload cagrilacak")
        result = _get_group_compare_payload(symbol, db)
        logger.info(f"[gc_diag] E: payload tamam")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            f"[group_compare] {symbol} beklenmeyen hata: {type(exc).__name__}: {exc}\n"
            + _traceback.format_exc()
        )
        raise HTTPException(status_code=503, detail="Servis geçici olarak kullanılamıyor")


@app.get("/compare/{symbol}")
def get_compare(symbol: str):
    """Hisse getirisini altın, döviz, BIST100 ve faiz ile karşılaştırır. 60 dk cache."""
    symbol = _normalize_quote_ticker(symbol)
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol zorunlu")

    now_ts = time.time()
    cached = _COMPARE_CACHE.get(symbol)
    if cached is not None:
        age = now_ts - cached["ts"]
        if age <= _COMPARE_CACHE_TTL:
            return {
                **cached["payload"],
                "cache": True,
                "cache_age_seconds": round(age, 1),
            }

    payload = _compare_payload(symbol)
    _COMPARE_CACHE[symbol] = {"ts": now_ts, "payload": payload}
    return {**payload, "cache": False, "cache_age_seconds": 0}


@app.get("/")
def anasayfa():
    return {
        "sistem":    "PayNotu Skor API v2.0",
        "durum":     "aktif",
        "motorlar":  ["FinancialEngine v2.2 (Spek)", "EmotionalEngine", "PayNotuIntegrator"],
        "scheduler": "APScheduler — daily_score 03:00 UTC, fintables_sync 02:00 UTC",
    }


@app.get("/score/{ticker}")
def get_score(ticker: str):
    """Bir hisse için tam PayNotu skoru hesapla ve Firestore'a yaz."""
    ticker = ticker.upper().strip()

    _ed = date.today().strftime("%Y-%m-%d")
    _sd = (date.today() - timedelta(days=1825)).strftime("%Y-%m-%d")
    df = bp.Ticker(ticker).history(start=_sd, end=_ed)
    if df.empty:
        return {"error": f"{ticker} için veri bulunamadı"}

    endeksler: list = []
    sektor: str = ""
    reviews: list[Review] = []
    hd: dict = {}

    try:
        db = _firebase_db()
        hisse_doc = db.collection("hisseler").document(ticker).get()
        if hisse_doc.exists:
            hd = hisse_doc.to_dict() or {}
            endeksler = hd.get("endeksler", []) or []
            sektor    = hd.get("industry") or hd.get("sektor") or ""
        reviews = _yorumlar_oku(ticker, db)
    except Exception as e:
        logger.warning(f"[{ticker}] Firestore okunamadı: {e}")

    from kap_client import get_oda_count
    try:
        kap_haber = get_oda_count(ticker, days=30)
    except Exception as e:
        logger.warning(f'[{ticker}] KAP haber çekilemedi: {e}')
        kap_haber = hd.get('kap_oda_30g', 0)

    f_result = financial_engine.calculate(
        ticker, df,
        endeksler=endeksler,
        sektor=sektor,
        kap_haber_sayisi=kap_haber,
        corporate_action_dates=None,
    )
    e_result = emotional_engine.calculate(ticker, reviews)
    final    = integrator.calculate(f_result, e_result)

    # ── Firestore atomic update ──────────────────────────────────────────────
    try:
        db = _firebase_db()
        _am_gs = getattr(f_result, "anomaly_metrics", None)
        db.collection("hisseler").document(ticker).update({
            "halk_skoru":      round(final.emotional_score, 4),
            "anomali_skoru":   round(final.paynotu_score, 4) if final.paynotu_score is not None else None,
            "paynotu_skoru":   round(final.paynotu_score, 4) if final.paynotu_score is not None else None,
            "financial_score": fb_firestore.DELETE_FIELD,
            "finansal_taban":  fb_firestore.DELETE_FIELD,
            "duygusal_taban":  fb_firestore.DELETE_FIELD,
            "last_updated":    fb_firestore.SERVER_TIMESTAMP,
            "motor_detay":     _motor_detay_payload(f_result),
            "kap_oda_30g":     kap_haber,
            "kategori":        f_result.kategori,
            "anomaly_metrics": {
                "total_days":             _am_gs.total_days,
                "hard_count":             _am_gs.hard_count,
                "extreme_count":          _am_gs.extreme_count,
                "weighted_count":         _am_gs.weighted_count,
                "block_count":            _am_gs.block_count,
                "longest_streak":         _am_gs.longest_streak,
                "avg_streak":             _am_gs.avg_streak,
                "hhi":                    _am_gs.hhi,
                "recency_center":         _am_gs.recency_center,
                "r_activity":             _am_gs.r_activity,
                "r_streak":               _am_gs.r_streak,
                "anomaly_activity_score": _am_gs.anomaly_activity_score,
            } if _am_gs is not None else fb_firestore.DELETE_FIELD,
        })
    except Exception as e:
        logger.warning(f"[{ticker}] Firestore yazma hatası: {e}")

    # JSON yanıt — yeni ve eski alan adları (geri uyumluluk)
    return {
        "ticker":          ticker,

        "spek_score":      f_result.spek_score,
        "paynotu_score":   final.paynotu_score,
        "emotional_score": final.emotional_score,
        "guven_skoru":     f_result.guven_skoru,

        "emotional_grip":  final.emotional_grip,
        "grip_intensity":  final.grip_intensity,
        "is_sentiment_divergence":  final.is_sentiment_divergence,
        "has_reviews":     final.has_reviews,

        "details": {
            "topsis_raw":             f_result.topsis_raw,
            "entropi_agirliklari":    f_result.entropi_agirliklari,
            "fiyat_anomali_skoru":    f_result.fiyat_anomali_skoru,
            "hacim_patlamasi_skoru":  f_result.hacim_patlamasi_skoru,
            "volatilite_skoru":       f_result.volatilite_skoru,
            "pump_benzerlik_skoru":   f_result.pump_benzerlik_skoru,
            "spek_gun_soft":          f_result.spek_gun_soft,
            "spek_gun_hard":          f_result.spek_gun_hard,
            "spek_gun_extreme":       f_result.spek_gun_extreme,
            "max_streak":             f_result.max_streak,
            "fundamental_multiplier": f_result.fundamental_multiplier,
            "veri_gun_sayisi":        f_result.veri_gun_sayisi,
            "endeksler":              endeksler,
            "ipo_listede":            f_result.ipo_listede,
            "kap_oda_sayisi":         f_result.kap_haber_sayisi,

            # Eski alan adları (geri uyumluluk)
            "speculative_days": f_result.spek_gun_hard,
            "topsis":           f_result.topsis_raw,
            "pump_similarity":  f_result.pump_benzerlik_skoru,
            "data_points":      f_result.veri_gun_sayisi,
            "review_count":     e_result.review_count,
            "effective_review_count": e_result.effective_review_count,
        },
        "temel": {
            "roe":           f_result.temel_roe,
            "pd_dd":         f_result.temel_pd_dd,
            "fk":            f_result.temel_fk,
            "net_kar_marji": f_result.temel_net_kar_marji,
            "ok_buyume":     f_result.temel_ok_buyume,
            "borc_favok":    f_result.temel_borc_favok,
            "kaynak":        f_result.temel_kaynak,
            "period":        f_result.temel_period,
        },
        "motor_detay": _motor_detay_payload(f_result),
    }


@app.get("/score/{ticker}/financial-only")
def get_financial_score(ticker: str):
    """Sadece finansal skor — motor testleri için."""
    ticker = ticker.upper().strip()
    _ed = date.today().strftime("%Y-%m-%d")
    _sd = (date.today() - timedelta(days=1825)).strftime("%Y-%m-%d")
    df = bp.Ticker(ticker).history(start=_sd, end=_ed)
    if df.empty:
        return {"error": "Veri bulunamadı"}
    endeksler: list = []
    sektor: str = ""
    try:
        db = _firebase_db()
        hisse_doc = db.collection("hisseler").document(ticker).get()
        if hisse_doc.exists:
            hd = hisse_doc.to_dict() or {}
            endeksler = hd.get("endeksler", []) or []
            sektor    = hd.get("industry") or hd.get("sektor") or ""
    except Exception:
        pass

    result = financial_engine.calculate(
        ticker, df,
        endeksler=endeksler,
        sektor=sektor,
    )

    return {
        # Yeni
        "ticker":          result.ticker,
        "spek_score":      result.spek_score,
        "guven_skoru":     result.guven_skoru,
        "topsis_raw":      result.topsis_raw,
        "spek_gun_hard":   result.spek_gun_hard,
        "spek_gun_extreme": result.spek_gun_extreme,
        "max_streak":      result.max_streak,
        # Eski (geri uyumluluk)
        "financial_score": result.spek_score,
        "speculative_days": result.spek_gun_hard,
        "topsis_score":    result.topsis_raw,
        # Detay
        "fiyat_anomali_skoru":   result.fiyat_anomali_skoru,
        "hacim_patlamasi_skoru": result.hacim_patlamasi_skoru,
        "volatilite_skoru":      result.volatilite_skoru,
        "pump_benzerlik_skoru":  result.pump_benzerlik_skoru,
        "fundamental_multiplier": result.fundamental_multiplier,
        "fundamental_aciklama":  result.fundamental_aciklama,
        "ipo_listede":           result.ipo_listede,
        "veri_gun_sayisi":       result.veri_gun_sayisi,
        "entropi_agirliklari":   result.entropi_agirliklari,
        "temel": {
            "roe":           result.temel_roe,
            "pd_dd":         result.temel_pd_dd,
            "fk":            result.temel_fk,
            "net_kar_marji": result.temel_net_kar_marji,
            "ok_buyume":     result.temel_ok_buyume,
            "borc_favok":    result.temel_borc_favok,
            "kaynak":        result.temel_kaynak,
            "period":        result.temel_period,
        },
    }


@app.post("/icerik-kontrol")
def icerik_kontrol(body: dict):
    try:
        r = _requests.post(
            f'{DUYGUSAL_AKIL_URL}/icerik-kontrol',
            json={'metin': body.get('metin', '')},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except _requests.RequestException:
        return {'durum': 'temiz', 'aciklama': 'Servis erişilemedi', 'risk_puani': 0}


@app.post("/yorumu-skorla")
def yorumu_skorla(body: dict):
    hisse_kodu = (body.get('hisse_kodu') or '').upper().strip()
    if not hisse_kodu:
        raise HTTPException(status_code=400, detail='hisse_kodu zorunlu')

    try:
        r = _requests.post(
            f'{DUYGUSAL_AKIL_URL}/yorumu-skorla',
            json={
                'yorum_metni':         body.get('yorum_metni', ''),
                'puan':                float(body.get('puan', 3)),
                'kullanici_id':        body.get('kullanici_id', ''),
                'hesap_yas_gun':       int(body.get('hesap_yas_gun', 0)),
                'toplam_yorum_sayisi': int(body.get('toplam_yorum_sayisi', 0)),
                'yorum_cesitliligi':   float(body.get('yorum_cesitliligi', 0)),
                'yorum_timestamp':     int(body.get('yorum_timestamp', int(time.time()))),
                'faydali_oy':          int(body.get('faydali_oy', 0)),
                'faydali_olmayan_oy':  int(body.get('faydali_olmayan_oy', 0)),
                'hisse_kodu':          hisse_kodu,
            },
            timeout=30,
        )
        if r.status_code == 400:
            hata = r.json()
            raise HTTPException(status_code=400, detail=hata.get('detail', 'İçerik engellendi'))
        r.raise_for_status()
        sonuc = r.json()
    except _requests.RequestException as e:
        logger.error(f'[yorumu-skorla] Duygusal akıl servisi hatası: {e}')
        raise HTTPException(status_code=503, detail='Sentiment servisi şu an erişilemiyor')

    duygusal = float(sonuc.get('itibar_skoru', 5.0))
    try:
        db = _firebase_db()
        hisse_doc = db.collection('hisseler').document(hisse_kodu).get()
        spek_score = 5.0
        if hisse_doc.exists:
            spek_score = float((hisse_doc.to_dict() or {}).get('finansal_taban', 5.0) or 5.0)

        spek_score  = max(0.0, min(10.0, spek_score))
        # Finansal veri yoksa PayNotu üretilmez
        if spek_score == 0.0:
            db.collection('hisseler').document(hisse_kodu).update({
                'duygusal_taban': round(duygusal, 4),
                'paynotu_skoru': None,
            })
            return sonuc
        duygusal    = max(0.0, min(10.0, duygusal))
        r_h         = 10.0 - duygusal
        divergence  = spek_score > 7.0 and r_h < 3.0
        f_w         = 0.90 if divergence else 0.65
        e_w         = 0.10 if divergence else 0.35
        paynotu     = round(max(0.0, min(10.0, f_w * spek_score + e_w * r_h)), 4)

        db.collection('hisseler').document(hisse_kodu).update({
            'duygusal_taban': round(duygusal, 4),
            'paynotu_skoru':  round(paynotu, 4),
        })
    except Exception as e:
        logger.warning(f'[yorumu-skorla/{hisse_kodu}] Firestore: {e}')

    return sonuc


@app.post("/admin/calibrate")
def calibrate(x_admin_key: str = Header(default="")):
    """SPK IslemYasaklari verisiyle motor eşiklerini kalibre et."""
    if _ADMIN_KEY and x_admin_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Yetkisiz")
    try:
        cfg = run_calibration()
        return {"status": "ok", "thresholds": cfg}
    except Exception as e:
        logger.error(f"[calibrate] Hata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── KAP HABERLER ──────────────────────────────────────────────────────────────

@app.get("/haberler/kap")
def haberler_kap(ticker: str = "", days: int = 30):
    """
    KAP bildirim listesi.
    ticker boşsa son tüm bildirimler, dolu ise sadece o hissenin bildirimleri.
    """
    try:
        from kap_client import get_disclosures_by_ticker

        if ticker:
            ticker = ticker.upper().strip()
            disclosures = get_disclosures_by_ticker(ticker, days=days)
        else:
            # Tüm bildirimler için ileride genişletilebilir
            disclosures = []

        result = []
        for d in disclosures:
            if not isinstance(d, dict):
                continue
            result.append({
                "disclosureIndex": str(d.get("disclosureIndex") or ""),
                "stockCodes":      str(d.get("stockCodes") or "").strip(),
                "title":           str(d.get("subject") or "").strip(),
                "summary":         str(d.get("summary") or "").strip(),
                "publishDate":     str(d.get("publishDate") or ""),
                "disclosureType":  str(d.get("disclosureType") or ""),
                "disclosureClass": str(d.get("disclosureClass") or ""),
            })

        logger.info(f"[haberler/kap] ticker={ticker or 'ALL'} → {len(result)} bildirim")
        return {"ok": True, "ticker": ticker, "disclosures": result}

    except Exception as e:
        logger.error(f"[haberler/kap] Hata: {e}")
        raise HTTPException(status_code=502, detail=str(e))


class DailyJobRequest(BaseModel):
    tickers: list[str] | None = None


@app.post("/admin/run-daily-job")
def trigger_daily_job(
    body: DailyJobRequest = DailyJobRequest(),
    x_admin_key: str = Header(default=""),
):
    """Günlük cron job'ı manuel tetikle (test için)."""
    if _ADMIN_KEY and x_admin_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Yetkisiz")
    import threading
    threading.Thread(target=daily_job, args=(body.tickers,), daemon=True).start()
    return {"status": "started", "message": "daily_job arka planda çalışıyor", "tickers": body.tickers}


@app.post("/admin/run-fintables-sync")
def admin_run_fintables_sync(x_admin_key: str = Header(default="")):
    """Fintables sync'i manuel tetikle (sector_id dahil)."""
    if _ADMIN_KEY and x_admin_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Yetkisiz")
    try:
        fintables_sync_job()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/update-ranks")
def update_ranks(x_admin_key: str = Header(default="")):
    """Tüm hisselerin spek sıralamasını güncelle."""
    if _ADMIN_KEY and x_admin_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Yetkisiz")
    try:
        db = _firebase_db()
        _guncelle_topsis_rank(db)
        return {"status": "ok", "mesaj": "Spek sıralama güncellendi"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test/xu100")
def test_xu100():
    """XU100 borsapy testi"""
    sonuclar = {}
    for ticker in ["XU100", "XU030", "BIST100", "^XU100"]:
        try:
            df = bp.Ticker(ticker).history(period="5d")
            if df is not None and not df.empty:
                sonuclar[ticker] = f"OK {len(df)} gün, son: {df['Close'].iloc[-1]:.2f}"
            else:
                sonuclar[ticker] = "Bos veri"
        except Exception as e:
            sonuclar[ticker] = f"HATA: {str(e)[:100]}"
    return sonuclar


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)