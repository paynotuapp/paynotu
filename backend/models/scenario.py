"""
PayNotu ScenarioSegment Modeli

Bir hissenin zaman ekseninde tespit edilen davranış segmentlerini
temsil eden immutable Pydantic modelleri. Rule-based scenario classifier
tarafından üretilir, daily_job içinde Firestore'a yazılır.

Her segment, [start_index, end_index] aralığına ait precomputed
alt skorları (subscores) içerir. PayNotu sekmesindeki dinamik
anomali bileşeni kutuları bu subscores'u render eder.
"""

from enum import Enum
from typing import List
from pydantic import BaseModel, Field, ConfigDict


class ScenarioType(str, Enum):
    """
    Rule-based classifier tarafından üretilen davranış kategorileri.
    SPK kalibre threshold'lar üzerinden tespit edilir.
    """
    PUMP = "pump"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    BREAKOUT = "breakout"
    MANIPULATION = "manipulation"
    CONSOLIDATION = "consolidation"
    IPO_PERIOD = "ipo_period"
    SPK_PUMP_DUMP = "spk_pump_dump"


class AnomalyComponents(BaseModel):
    """
    Bir segment'e özgü alt skorlar (0.0 - 1.0 normalize).
    Chart üzerinde bayrak seçildiğinde PayNotu sekmesindeki
    dinamik anomali kutularında gösterilir.

    Kaynak: financial_engine.py'deki spek_score alt kriterleri,
    segment'in [start_index, end_index] aralığında recompute edilir.
    """
    model_config = ConfigDict(frozen=True)

    fiyat: float = Field(..., ge=0.0, le=1.0, description="Fiyat hareketi anomali skoru")
    hacim: float = Field(..., ge=0.0, le=1.0, description="Hacim anomali skoru")
    volatilite: float = Field(..., ge=0.0, le=1.0, description="Volatilite anomali skoru")
    pump: float = Field(..., ge=0.0, le=1.0, description="Pump-and-dump benzerlik skoru")


class ScenarioSegment(BaseModel):
    """
    Hisse fiyat/hacim zaman ekseninde tespit edilmiş bir davranış segmenti.

    UI tarafında:
      - Chart üzerinde dolu nokta (start) + halka (end) olarak çizilir
      - SPEKÜLASYON NOKTALARI listesinde chip olarak görünür
      - Chip/bayrak tıklanınca subscores aktif kutulara yansır

    Backend tarafında:
      - scenario_classifier.py tarafından sliding window analiziyle üretilir
      - daily_job içinde her hisse için Firestore'a yazılır
      - SPK kalibre threshold'lara dayanır (rule-based, deterministik)
    """
    model_config = ConfigDict(frozen=True)

    type: ScenarioType = Field(..., description="Davranış kategorisi")
    start_index: int = Field(..., ge=0, description="OHLCV serisinde başlangıç indeksi")
    end_index: int = Field(..., ge=0, description="OHLCV serisinde bitiş indeksi")
    start_date: str = Field(..., description="ISO 8601 tarih (YYYY-MM-DD), timezone-naive")
    end_date: str = Field(..., description="ISO 8601 tarih (YYYY-MM-DD), timezone-naive")
    title: str = Field(..., min_length=1, max_length=80, description="Template-based başlık")
    description: str = Field(..., min_length=1, max_length=240, description="Template-based 1-2 cümle açıklama")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Sınıflandırma güven skoru")
    subscores: AnomalyComponents = Field(..., description="Segment-level precomputed alt skorlar")


class ScenarioBundle(BaseModel):
    """
    Bir hissenin tüm scenario segmentlerinin Firestore'a yazılan paket hali.

    Firestore yolu: stocks/{ticker}/scenarios (sub-document)
    Yazım: collection.document(ticker).update({"scenarios": bundle.model_dump()})
    """
    model_config = ConfigDict(frozen=True)

    segments: List[ScenarioSegment] = Field(default_factory=list, description="Tespit edilen segmentler, kronolojik sıralı")
    total_window_days: int = Field(..., ge=0, description="Analiz penceresi gün sayısı (örn. 1825)")
    classifier_version: str = Field(..., min_length=1, description="Classifier sürümü, traceability için")
