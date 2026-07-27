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

    active_list = services_data.get("active_services", [])
    active_api_names = [s["api_name"] for s in active_list]
    active_titles = [s["service_name"] for s in active_list]
    project_id = services_data.get("project_id", "qiita-app-170")

    target_pricing = {
        "project_id": project_id,
        "active_services_count": len(active_list),
        "target_unit_prices": {}
    }

    print(f"・対象プロジェクトID: {project_id}")
    print(f"・検出有効サービス数: {len(active_list)} 件")

    if "run.googleapis.com" in active_api_names:
        target_pricing["target_unit_prices"]["cloud_run"] = catalog.get("cloud_run", {})
        print(f"  ・[✓ マッチ] Cloud Run 適用単価を設定")

    if "storage.googleapis.com" in active_api_names or "storage-component.googleapis.com" in active_api_names:
        target_pricing["target_unit_prices"]["cloud_storage"] = catalog.get("cloud_storage", {})
        print(f"  ・[✓ マッチ] Cloud Storage 適用単価を設定")

    if "generativelanguage.googleapis.com" in active_api_names or "aiplatform.googleapis.com" in active_api_names:
        target_pricing["target_unit_prices"]["gemini_api"] = catalog.get("gemini_api", {})
        print(f"  ・[✓ マッチ] Gemini API 適用単価を設定")

    if "bigquery.googleapis.com" in active_api_names:
        target_pricing["target_unit_prices"]["bigquery"] = catalog.get("bigquery", {})
        print(f"  ・[✓ マッチ] BigQuery 適用単価を設定")

    if "pubsub.googleapis.com" in active_api_names:
        target_pricing["target_unit_prices"]["pubsub"] = catalog.get("pubsub", {})
        print(f"  ・[✓ マッチ] Cloud Pub/Sub 適用単価を設定")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(target_pricing, f, indent=2, ensure_ascii=False)

    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
