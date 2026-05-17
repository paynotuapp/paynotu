"""
Railway Cron Job — Aylık SPK Kalibrasyon
Her ayın 1'inde 02:00'de çalışır.
FastAPI /admin/calibrate endpoint'ini çağırır.
"""
import os
import sys
import requests

FASTAPI_URL = os.environ["FASTAPI_URL"].rstrip("/")
ADMIN_KEY   = os.getenv("ADMIN_KEY", "")

headers = {}
if ADMIN_KEY:
    headers["x-admin-key"] = ADMIN_KEY

print(f"[cron] POST {FASTAPI_URL}/admin/calibrate")
try:
    r = requests.post(
        f"{FASTAPI_URL}/admin/calibrate",
        headers=headers,
        timeout=300,  # kalibrasyon ~2-3 dk
    )
    r.raise_for_status()
    data = r.json()
    print(f"[cron] Kalibrasyon basarili: {data}")
    sys.exit(0)
except Exception as e:
    print(f"[cron] HATA: {e}")
    sys.exit(1)
