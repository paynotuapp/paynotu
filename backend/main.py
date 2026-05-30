from dotenv import load_dotenv
load_dotenv()

import os
import json
import base64
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, date, timedelta

import re
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DUYGUSAL_AKIL_URL = os.getenv('DUYGUSAL_AKIL_URL', 'http://localhost:8001')


# ── FİREBASE ──────────────────────────────────────────────────────────────────

def _firebase_db():
    if not firebase_admin._apps:
        cred_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64") or os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_b64:
            cred_b64 += "=" * (-len(cred_b64) % 4)
            cred_dict = json.loads(base64.b64decode(cred_b64).decode())
            cred = credentials.Certificate(cred_dict)
        else:
            cred_path = os.path.join(
                os.path.dirname(__file__),
                "pay-defteri-firebase-adminsdk-fbsvc-58f68bd69c.json",
            )
            cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
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
                    "valid": f_result.spek_score is not None and f_result.spek_score > 0.0,
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
                    fund_res  = fund_engine.calculate(
                        ticker,
                        sektor=_sektor,
                        sector_group=_sector_group,
                    )
                    _pio      = fund_res.piotroski
                    _fsub     = fund_res.subscores
                    db.collection("hisseler").document(ticker).update({
                        "finansal_skor":          fund_res.financial_score,
                        "finansal_skor_label":    fund_res.financial_score_label,
                        "finansal_skor_quality":  fund_res.financial_score_quality,
                        "finansal_subscores": {
                            "profitability": _fsub.profitability,
                            "balance_sheet": _fsub.balance_sheet,
                            "cash_flow":     _fsub.cash_flow,
                            "growth":        _fsub.growth,
                            "valuation":     _fsub.valuation,
                            "stability":     _fsub.stability,
                            "piotroski":     _fsub.piotroski,
                        },
                        "piotroski_score":         _pio.score                if _pio else None,
                        "piotroski_normalized":    _pio.normalized           if _pio else None,
                        "piotroski_total":         _pio.total_criteria       if _pio else 9,
                        "piotroski_calculated":    _pio.calculated_criteria  if _pio else 0,
                        "piotroski_coverage":      _pio.coverage             if _pio else 0.0,
                        "piotroski_confidence":    _pio.confidence           if _pio else "not_applicable",
                        "piotroski_applicability": _pio.applicability        if _pio else "not_applicable",
                        "piotroski_missing_criteria": _pio.missing_criteria  if _pio else [],
                        "finansal_aciklama":       fund_res.explanation,
                        "finansal_flags":         fund_res.financial_flags,
                        "finansal_data_source":   fund_res.data_source,
                        "finansal_sector_group":  fund_res.sector_group,
                        "finansal_period":        fund_res.period,
                    })
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
        new_doc = {
            'symbol':       symbol,
            'name':         (data.get('title') or symbol).strip(),
            'logo':         data.get('logo'),
            'islem_saati':  _fmt_session(session_raw),
            'kap_aktif':    True,
            'temel_kaynak': 'fintables',
        }
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
    except Exception as e:
        logger.warning(f"[startup] Firestore eşik yüklenemedi: {e}")

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
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "60"))
QUOTE_DELAY_MINUTES = int(os.getenv("QUOTE_DELAY_MINUTES", "15"))
QUOTE_LOOKBACK_DAYS = int(os.getenv("QUOTE_LOOKBACK_DAYS", "450"))


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


def _beta_vs_xu100(stock_close: pd.Series) -> float | None:
    """
    Beta = hissenin günlük getirileri ile XU100 günlük getirilerinin kovaryansı
           / XU100 getirilerinin varyansı

    Firestore'a yazmaz. Quote endpoint yanıtına beta ekler.
    """
    try:
        if stock_close is None or len(stock_close) < 60:
            return None

        start_date = stock_close.index.min().strftime("%Y-%m-%d")
        end_date = stock_close.index.max().strftime("%Y-%m-%d")

        xu100_df = bp.Ticker("XU100").history(
            start=start_date,
            end=end_date,
        )

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
    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=QUOTE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    try:
        df = bp.Ticker(ticker).history(start=start_date, end=end_date)
    except Exception as e:
        logger.error(f"[quote] {ticker} borsapy hatası: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"{ticker} fiyat verisi şu an alınamadı",
        )

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

    return {
        "symbol": ticker,
        "fiyat": round(son_fiyat, 2),
        "gunluk_degisim_yuzde": round(gunluk_degisim_yuzde, 2),
        "haftalik_degisim_yuzde": round(haftalik_degisim_yuzde, 2),
        "toplam_islem_hacmi": _volume_for_last_close(df, close),
        "rsi_14": _rsi_14(close),
        "beta": _beta_vs_xu100(close),
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
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)