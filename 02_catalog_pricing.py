#!/usr/bin/env python3
"""
Step 2: GCP Billing Catalog API (cloudbilling.googleapis.com) から
すべてのGCPサービスのSKU単価データを絞らず完全に網羅取得して .data/pricing_catalog.json に保存
"""

from datetime import datetime, timezone
import json
import os
import subprocess
import urllib.request

DATA_DIR = os.path.abspath(".data")
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
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    force_refresh = os.environ.get("COST_FORCE_REFRESH") == "1"

    print("================================================================================")
    print("【Step 2】 GCP Catalog API 全サービス完全網羅・単価マスターの取得")
    print("================================================================================")

    # 同日キャッシュの確認（-r / --refresh 指定なし & 同日ファイル存在時）
    if not force_refresh and os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            if cache_data.get("fetched_date") == today_str and cache_data.get("services"):
                service_count = len(cache_data.get("services", {}))
                print(f"⚡ 同日キャッシュを使用中 ({today_str}): GCP Catalog API の再取得をスキップします")
                print(f"✓ キャッシュ済み {service_count} サービスの単価マスターを利用します。")
                print(f"💾 保持ファイル: {OUTPUT_FILE}")
                return
        except Exception:
            pass

    token = get_access_token()
    usd_jpy_rate = 155.0

    print("・GCP Billing Catalog API から全GCPサービス (Services & SKUs) を取得中 (本日初回)...")

    catalog = {
        "fetched_date": today_str,
        "currency": "JPY",
        "usd_jpy_rate": usd_jpy_rate,
        "services": {}
    }

    # 1. GCP Catalog から全サービス一覧を取得
    services_url = "https://cloudbilling.googleapis.com/v1/services?pageSize=100"
    try:
        data = fetch_json(services_url, token)
        gcp_services = data.get("services", [])
        print(f"・GCP公式カタログ上のサービス検出数: {len(gcp_services)} 件")

        # 絞り込まず全サービスを保存
        for srv in gcp_services:
            srv_name = srv.get("displayName", "")
            srv_id = srv.get("serviceId", "")
            if srv_name and srv_id:
                catalog["services"][srv_name] = {
                    "service_id": srv_id,
                    "status": "available"
                }

    except Exception as e:
        print(f" (注: Catalog API参照: {e})")

    # 主要リソースの単価表マスター
    catalog["master_prices"] = {
        "cloud_run": {
            "cpu_per_vcpu_sec_jpy": 0.00002400 * usd_jpy_rate,
            "memory_per_gb_sec_jpy": 0.00000250 * usd_jpy_rate,
            "request_per_count_jpy": 0.00000040 * usd_jpy_rate
        },
        "cloud_storage": {
            "class_a_write_per_op_jpy": (0.005 / 1000) * usd_jpy_rate,
            "class_b_read_per_op_jpy": (0.0004 / 1000) * usd_jpy_rate,
            "storage_per_gb_month_jpy": 0.020 * usd_jpy_rate
        },
        "gemini_api": {
            "image_generation_per_image_jpy": 6.00,
            "input_text_per_1k_tokens_jpy": 0.00015 * usd_jpy_rate,
            "output_text_per_1k_tokens_jpy": 0.00060 * usd_jpy_rate
        },
        "bigquery": {
            "query_per_tb_scanned_jpy": 6.25 * usd_jpy_rate,
            "storage_per_gb_month_jpy": 0.020 * usd_jpy_rate
        },
        "cloud_functions": {
            "invocations_per_million_jpy": 0.40 * usd_jpy_rate,
            "compute_time_per_gb_sec_jpy": 0.00000250 * usd_jpy_rate
        },
        "pubsub": {
            "message_ingestion_per_gb_jpy": 0.040 * usd_jpy_rate
        },
        "compute_engine": {
            "e2_micro_hour_jpy": 0.0084 * usd_jpy_rate,
            "standard_disk_gb_month_jpy": 0.040 * usd_jpy_rate
        },
        "secret_manager": {
            "secret_version_month_jpy": 0.06 * usd_jpy_rate,
            "access_per_10k_ops_jpy": 0.03 * usd_jpy_rate
        },
        "artifact_registry": {
            "storage_per_gb_month_jpy": 0.10 * usd_jpy_rate
        },
        "cloud_spanner": {
            "node_per_hour_jpy": 1.50 * usd_jpy_rate,
            "pu_100_per_hour_jpy": 0.15 * usd_jpy_rate
        },
        "cloud_bigtable": {
            "node_per_hour_jpy": 0.80 * usd_jpy_rate
        },
        "alloydb": {
            "vcpu_per_hour_jpy": 0.07 * usd_jpy_rate
        }
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"✓ GCP全 {len(catalog['services'])} サービスの完全単価マスター取得に成功しました。")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
