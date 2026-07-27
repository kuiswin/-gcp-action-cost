#!/usr/bin/env python3
"""
Step 3: Step 1 (検出サービス) × Step 2 (アクティブサービス単価) のハイブリッド単価マップを .data/target_pricing.json に保存
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
    print("【Step 3】 ハイブリッド単価マッピング (Step 1 サービス × Step 2 単価)")
    print("================================================================================")

    if not os.path.exists(SERVICES_FILE):
        print("❌ Error: 01_active_services.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(CATALOG_FILE):
        print("❌ Error: 02_catalog_pricing.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(SERVICES_FILE, "r", encoding="utf-8") as f:
        active_data = json.load(f)

    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    active_names = [s["service_name"] for s in active_data.get("active_services", [])]
    project_id = active_data.get("project_id", "qiita-app-170")

    target_pricing = {
        "project_id": project_id,
        "active_services": active_names,
        "resource_unit_prices": {}
    }

    print(f"・対象プロジェクト: {project_id}")
    print(f"・検出サービス数  : {len(active_names)} 件 ({', '.join(active_names)})")

    if "Cloud Run" in active_names and "cloud_run" in catalog:
        target_pricing["resource_unit_prices"]["cloud_run_cpu_vcpu_sec_jpy"] = catalog["cloud_run"]["cpu_per_vcpu_sec_jpy"]
        target_pricing["resource_unit_prices"]["cloud_run_request_jpy"] = catalog["cloud_run"]["request_per_count_jpy"]
        print(f"  ・[Cloud Run] CPU: {catalog['cloud_run']['cpu_per_vcpu_sec_jpy']:.6f} 円/vCPU秒, Req: {catalog['cloud_run']['request_per_count_jpy']:.6f} 円/回")

    if "Cloud Storage" in active_names and "cloud_storage" in catalog:
        target_pricing["resource_unit_prices"]["gcs_write_class_a_jpy"] = catalog["cloud_storage"]["class_a_write_per_op_jpy"]
        target_pricing["resource_unit_prices"]["gcs_read_class_b_jpy"] = catalog["cloud_storage"]["class_b_read_per_op_jpy"]
        print(f"  ・[Cloud Storage] Write: {catalog['cloud_storage']['class_a_write_per_op_jpy']:.6f} 円/回, Read: {catalog['cloud_storage']['class_b_read_per_op_jpy']:.6f} 円/回")

    if any("Gemini" in s or "Vertex" in s for s in active_names) and "gemini_api" in catalog:
        target_pricing["resource_unit_prices"]["gemini_image_generation_jpy"] = catalog["gemini_api"]["image_generation_per_image_jpy"]
        print(f"  ・[Gemini API] 画像生成: {catalog['gemini_api']['image_generation_per_image_jpy']:.2f} 円/枚")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(target_pricing, f, indent=2, ensure_ascii=False)

    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
