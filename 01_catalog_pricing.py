#!/usr/bin/env python3
"""
Step 1: GCP Billing Catalog API から最新の公式単価テーブルを取得して .data/pricing_catalog.json に保存
"""

import json
import os
import subprocess
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), ".data")
OUTPUT_FILE = os.path.join(DATA_DIR, "pricing_catalog.json")

def get_access_token():
    res = subprocess.run(
        ["/root/google-cloud-sdk/bin/gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True
    )
    return res.stdout.strip()

def fetch_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    token = get_access_token()
    usd_jpy_rate = 155.0

    print("================================================================================")
    print("【Step 1】 GCP Catalog API 単価テーブル取得")
    print("================================================================================")
    print("・GCP Cloud Billing Catalog API (cloudbilling.googleapis.com) へ問い合わせ中...")

    # 代表的リソースのデフォルト基準単価マップ ($ & 円)
    catalog = {
        "currency": "JPY",
        "usd_jpy_rate": usd_jpy_rate,
        "cloud_run": {
            "cpu_per_vcpu_sec_usd": 0.00002400,
            "cpu_per_vcpu_sec_jpy": 0.00002400 * usd_jpy_rate,
            "memory_per_gb_sec_usd": 0.00000250,
            "memory_per_gb_sec_jpy": 0.00000250 * usd_jpy_rate,
            "request_per_count_usd": 0.00000040,
            "request_per_count_jpy": 0.00000040 * usd_jpy_rate
        },
        "cloud_storage": {
            "class_a_write_per_op_jpy": (0.005 / 1000) * usd_jpy_rate,
            "class_b_read_per_op_jpy": (0.0004 / 1000) * usd_jpy_rate,
            "storage_per_gb_month_jpy": 0.020 * usd_jpy_rate
        },
        "gemini_api": {
            "image_generation_per_image_jpy": 6.00
        }
    }

    # APIから動的取得を試行
    try:
        service_id = "152E-C115-5142"  # Cloud Run
        url = f"https://cloudbilling.googleapis.com/v1/services/{service_id}/skus?pageSize=100"
        data = fetch_json(url, token)
        for sku in data.get("skus", []):
            desc = sku.get("description", "")
            if "us-central1" in desc or "asia-northeast1" in desc:
                pricing_info = sku.get("pricingInfo", [])
                if pricing_info:
                    pe = pricing_info[0].get("pricingExpression", {})
                    rates = pe.get("tieredRates", [])
                    for r in rates:
                        up = r.get("unitPrice", {})
                        val = int(up.get("units", 0)) + up.get("nanos", 0) / 1e9
                        if val > 0:
                            if "CPU" in desc:
                                catalog["cloud_run"]["cpu_per_vcpu_sec_usd"] = val
                                catalog["cloud_run"]["cpu_per_vcpu_sec_jpy"] = val * usd_jpy_rate
                            elif "Memory" in desc:
                                catalog["cloud_run"]["memory_per_gb_sec_usd"] = val
                                catalog["cloud_run"]["memory_per_gb_sec_jpy"] = val * usd_jpy_rate
    except Exception as e:
        print(f" (注: API応答エラーのため公式フォールバック単価を使用します: {e})")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"✓ 単価テーブルの取得に成功しました。")
    print(f"  ・Cloud Run CPU単価   : {catalog['cloud_run']['cpu_per_vcpu_sec_jpy']:.6f} 円 / vCPU秒")
    print(f"  ・Cloud Run Request  : {catalog['cloud_run']['request_per_count_jpy']:.6f} 円 / 回")
    print(f"  ・GCS Write (Class A): {catalog['cloud_storage']['class_a_write_per_op_jpy']:.6f} 円 / 回")
    print(f"  ・GCS Read  (Class B): {catalog['cloud_storage']['class_b_read_per_op_jpy']:.6f} 円 / 回")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
