#!/usr/bin/env python3
"""
Step 3: Step 1 (検出サービス) × Step 2 (全単価マスター) を動的にクロス照合し、
アクティブなすべてのGCPサービスの適用単価を汎用自動バインドして .data/target_pricing.json に保存

free_tier.json (GitHub or ローカル) から無料枠情報を取得して単価と一緒に書き出す。
"""

import json
import os
import sys
import time
import urllib.request

DATA_DIR = os.path.abspath(".data")
SERVICES_FILE = os.path.join(DATA_DIR, "active_services.json")
CATALOG_FILE  = os.path.join(DATA_DIR, "pricing_catalog.json")
OUTPUT_FILE   = os.path.join(DATA_DIR, "target_pricing.json")

RAW_BASE_URL = "https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/"
FREE_TIER_FILENAME = "free_tier.json"

def load_free_tier():
    """GitHubから free_tier.json を取得。失敗したらローカルのファイルを使う。"""
    # まずローカルの同ディレクトリを確認
    local_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), FREE_TIER_FILENAME),
        os.path.join(os.getcwd(), FREE_TIER_FILENAME),
    ]
    for path in local_candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"  ・[無料枠定義] ローカルファイルから読み込み: {path}")
            return data.get("free_tier", {})

    # ローカルになければ GitHub から取得
    url = f"{RAW_BASE_URL}{FREE_TIER_FILENAME}?t={int(time.time() * 1000)}"
    try:
        req = urllib.request.Request(
            url,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"  ・[無料枠定義] GitHubから取得: {url.split('?')[0]}")
        return data.get("free_tier", {})
    except Exception as e:
        print(f"  ・[無料枠定義] GitHub取得失敗 ({e}) → 無料枠情報なしで続行", file=sys.stderr)
        return {}


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
    active_list   = services_data.get("active_services", [])
    project_id    = services_data.get("project_id", "")

    # 無料枠定義を取得
    free_tier_map = load_free_tier()

    # API名 → (表示名, master_keyの対応マップ)
    api_map = {
        "run.googleapis.com":                  ("Cloud Run",             "cloud_run"),
        "storage.googleapis.com":              ("Cloud Storage",         "cloud_storage"),
        "storage-component.googleapis.com":    ("Cloud Storage",         "cloud_storage"),
        "generativelanguage.googleapis.com":   ("Gemini API / Vertex AI","gemini_api"),
        "aiplatform.googleapis.com":           ("Gemini API / Vertex AI","gemini_api"),
        "bigquery.googleapis.com":             ("BigQuery",              "bigquery"),
        "pubsub.googleapis.com":               ("Cloud Pub/Sub",         "pubsub"),
        "compute.googleapis.com":              ("Compute Engine",        "compute_engine"),
        "cloudfunctions.googleapis.com":       ("Cloud Functions",       "cloud_functions"),
        "secretmanager.googleapis.com":        ("Secret Manager",        "secret_manager"),
        "artifactregistry.googleapis.com":     ("Artifact Registry",     "artifact_registry"),
    }

    target_unit_prices = {}
    matched_services   = []

    print(f"・対象プロジェクトID: {project_id}")
    print(f"・検出有効サービス数: {len(active_list)} 件 (自動判別バインド実行中)")

    for srv in active_list:
        api_name = srv.get("api_name", "")
        if api_name in api_map:
            display_name, master_key = api_map[api_name]
            if master_key not in target_unit_prices:
                prices = master_prices.get(master_key, master_prices.get(display_name, {}))
                if prices:
                    entry = {
                        "display_name": display_name,
                        "unit_prices":  prices,
                    }
                    # 無料枠情報があれば同梱
                    if master_key in free_tier_map:
                        entry["free_tier_metrics"] = free_tier_map[master_key].get("metrics", {})

                    target_unit_prices[master_key] = entry
                    matched_services.append(display_name)
                    print(f"  ・[✓ 自動バインド] {display_name} ({api_name})")

    target_pricing = {
        "project_id":            project_id,
        "active_services_count": len(active_list),
        "matched_services":      matched_services,
        "target_unit_prices":    target_unit_prices,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(target_pricing, f, indent=2, ensure_ascii=False)

    print(f"✓ プロジェクトで動的に検出された {len(matched_services)} サービスの適用単価表を自動生成しました。")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
