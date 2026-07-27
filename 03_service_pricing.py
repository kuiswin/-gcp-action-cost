#!/usr/bin/env python3
"""
Step 3: Step 1 (検出サービス) × Step 2 (全単価マスター) を動的にクロス照合し、
アクティブなすべてのGCPサービスの適用単価を汎用自動バインドして .data/target_pricing.json に保存
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
    print("【Step 3】 ハイブリッド単価マッピング (Step 1 検出サービス ✕ Step 2 単価マスターの動的結合)")
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
    project_id = services_data.get("project_id", "qiita-app-170")

    # API名と単価マスターキーの動的対応マッピング
    api_map = {
        "run.googleapis.com": ("Cloud Run", "cloud_run"),
        "storage.googleapis.com": ("Cloud Storage", "cloud_storage"),
        "storage-component.googleapis.com": ("Cloud Storage", "cloud_storage"),
        "generativelanguage.googleapis.com": ("Gemini API / Vertex AI", "gemini_api"),
        "aiplatform.googleapis.com": ("Gemini API / Vertex AI", "gemini_api"),
        "bigquery.googleapis.com": ("BigQuery", "bigquery"),
        "pubsub.googleapis.com": ("Cloud Pub/Sub", "pubsub"),
        "compute.googleapis.com": ("Compute Engine", "compute_engine"),
        "cloudfunctions.googleapis.com": ("Cloud Functions", "cloud_functions"),
        "secretmanager.googleapis.com": ("Secret Manager", "secret_manager"),
        "artifactregistry.googleapis.com": ("Artifact Registry", "artifact_registry")
    }

    target_unit_prices = {}
    matched_services = []

    print(f"・対象プロジェクトID: {project_id}")
    print(f"・検出有効サービス数: {len(active_list)} 件 (自動判別バインド実行中)")

    for srv in active_list:
        api_name = srv.get("api_name", "")
        if api_name in api_map:
            display_name, master_key = api_map[api_name]
            if master_key not in target_unit_prices:
                prices = master_prices.get(master_key, master_prices.get(display_name, {}))
                if prices:
                    target_unit_prices[master_key] = prices
                    matched_services.append(display_name)
                    print(f"  ・[✓ 自動バインド] {display_name} ({api_name})")

    target_pricing = {
        "project_id": project_id,
        "active_services_count": len(active_list),
        "matched_services": matched_services,
        "target_unit_prices": target_unit_prices
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(target_pricing, f, indent=2, ensure_ascii=False)

    print(f"✓ プロジェクトで動的に検出された {len(matched_services)} サービスの適用単価表を自動生成しました。")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
