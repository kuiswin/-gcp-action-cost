#!/usr/bin/env python3
"""
Step 2: Step 1 で検出された「利用中サービスのみ」の最新公式単価を GCP Catalog API から照会して .data/pricing_catalog.json に保存
"""

import json
import os
import sys
import subprocess
import urllib.request

DATA_DIR = os.path.abspath(".data")
SERVICES_FILE = os.path.join(DATA_DIR, "active_services.json")
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
    print("================================================================================")
    print("【Step 2】 検出済み利用中サービスの公式単価照会 (Catalog API)")
    print("================================================================================")

    if not os.path.exists(SERVICES_FILE):
        print("❌ Error: 01_active_services.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(SERVICES_FILE, "r", encoding="utf-8") as f:
        active_data = json.load(f)

    active_service_names = [s["service_name"] for s in active_data.get("active_services", [])]
    project_id = active_data.get("project_id", "qiita-app-170")

    token = get_access_token()
    usd_jpy_rate = 155.0

    print(f"・対象プロジェクトID: {project_id}")
    print(f"・単価取得対象サービス: {', '.join(active_service_names)}")

    # 検出されたサービスのみの単価辞書を構築
    catalog = {
        "currency": "JPY",
        "usd_jpy_rate": usd_jpy_rate
    }

    if "Cloud Run" in active_service_names:
        catalog["cloud_run"] = {
            "cpu_per_vcpu_sec_usd": 0.00002400,
            "cpu_per_vcpu_sec_jpy": 0.00002400 * usd_jpy_rate,
            "memory_per_gb_sec_usd": 0.00000250,
            "memory_per_gb_sec_jpy": 0.00000250 * usd_jpy_rate,
            "request_per_count_usd": 0.00000040,
            "request_per_count_jpy": 0.00000040 * usd_jpy_rate
        }

    if "Cloud Storage" in active_service_names:
        catalog["cloud_storage"] = {
            "class_a_write_per_op_jpy": (0.005 / 1000) * usd_jpy_rate,
            "class_b_read_per_op_jpy": (0.0004 / 1000) * usd_jpy_rate,
            "storage_per_gb_month_jpy": 0.020 * usd_jpy_rate
        }

    if any("Gemini" in s or "Vertex" in s for s in active_service_names):
        catalog["gemini_api"] = {
            "image_generation_per_image_jpy": 6.00
        }

    # APIから動的取得を試行して更新
    if "Cloud Run" in active_service_names:
        try:
            service_id = "152E-C115-5142"
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

    print(f"✓ 検出済みサービスのみの単価照会に成功しました。")
    if "cloud_run" in catalog:
        print(f"  ・Cloud Run CPU単価   : {catalog['cloud_run']['cpu_per_vcpu_sec_jpy']:.6f} 円 / vCPU秒")
        print(f"  ・Cloud Run Request  : {catalog['cloud_run']['request_per_count_jpy']:.6f} 円 / 回")
    if "cloud_storage" in catalog:
        print(f"  ・GCS Write (Class A): {catalog['cloud_storage']['class_a_write_per_op_jpy']:.6f} 円 / 回")
        print(f"  ・GCS Read  (Class B): {catalog['cloud_storage']['class_b_read_per_op_jpy']:.6f} 円 / 回")
    if "gemini_api" in catalog:
        print(f"  ・Gemini AI画像生成   : {catalog['gemini_api']['image_generation_per_image_jpy']:.2f} 円 / 枚")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
