#!/usr/bin/env python3
"""
Step 3: Step 1 (全有効化サービス) × Step 2 (全単価マスター) を照合して「実際に利用中のサービスと適用単価」のハイブリッドを生成
"""

import json
import os
import sys

DATA_DIR = os.path.abspath(".data")
SERVICES_FILE = os.path.join(DATA_DIR, "active_services.json")
CATALOG_FILE = os.path.join(DATA_DIR, "pricing_catalog.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "target_pricing.json")

def main():
    print("================================================================================")
    print("【Step 3】 ハイブリッド単価マッピング (Step 1 サービス × Step 2 単価マスター)")
    print("================================================================================")

    if not os.path.exists(SERVICES_FILE):
        print("❌ Error: 01_active_services.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(CATALOG_FILE):
        print("❌ Error: 02_catalog_pricing.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(SERVICES_FILE, "r", encoding="utf-8") as f:
        services_data = json.load(f)

    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    master_prices = catalog.get("master_prices", catalog.get("master_pricing", {}))

    active_list = services_data.get("active_services", [])
    active_api_names = [s["api_name"] for s in active_list]
    project_id = services_data.get("project_id", "qiita-app-170")

    target_pricing = {
        "project_id": project_id,
        "active_services_count": len(active_list),
        "target_unit_prices": {}
    }

    print(f"・対象プロジェクトID: {project_id}")
    print(f"・検出有効サービス数: {len(active_list)} 件")

    if "run.googleapis.com" in active_api_names:
        prices = master_prices.get("cloud_run", master_prices.get("Cloud Run", {}))
        target_pricing["target_unit_prices"]["cloud_run"] = prices
        print(f"  ・[✓ マッチ] Cloud Run 適用単価を設定")

    if "storage.googleapis.com" in active_api_names or "storage-component.googleapis.com" in active_api_names:
        prices = master_prices.get("cloud_storage", master_prices.get("Cloud Storage", {}))
        target_pricing["target_unit_prices"]["cloud_storage"] = prices
        print(f"  ・[✓ マッチ] Cloud Storage 適用単価を設定")

    if "generativelanguage.googleapis.com" in active_api_names or "aiplatform.googleapis.com" in active_api_names:
        prices = master_prices.get("gemini_api", master_prices.get("Gemini API / Vertex AI", {}))
        target_pricing["target_unit_prices"]["gemini_api"] = prices
        print(f"  ・[✓ マッチ] Gemini API 適用単価を設定")

    if "bigquery.googleapis.com" in active_api_names:
        prices = master_prices.get("bigquery", master_prices.get("BigQuery", {}))
        target_pricing["target_unit_prices"]["bigquery"] = prices
        print(f"  ・[✓ マッチ] BigQuery 適用単価を設定")

    if "pubsub.googleapis.com" in active_api_names:
        prices = master_prices.get("pubsub", master_prices.get("Cloud Pub/Sub", {}))
        target_pricing["target_unit_prices"]["pubsub"] = prices
        print(f"  ・[✓ マッチ] Cloud Pub/Sub 適用単価を設定")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(target_pricing, f, indent=2, ensure_ascii=False)

    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
