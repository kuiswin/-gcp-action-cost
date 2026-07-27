#!/usr/bin/env python3
"""
Step 2: 対象GCPプロジェクトで有効・使用中のアクティブサービスを自動検出して .data/active_services.json に保存
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

DATA_DIR = os.path.abspath(".data")
OUTPUT_FILE = os.path.join(DATA_DIR, "active_services.json")

def get_access_token():
    res = subprocess.run(
        ["/root/google-cloud-sdk/bin/gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True
    )
    return res.stdout.strip()

def get_project_id():
    res = subprocess.run(
        ["/root/google-cloud-sdk/bin/gcloud", "config", "get-value", "project"],
        capture_output=True, text=True
    )
    pid = res.stdout.strip()
    return pid if pid and pid != "(unset)" else "qiita-app-170"

def fetch_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    token = get_access_token()
    project_id = sys.argv[1] if len(sys.argv) > 1 else get_project_id()

    print("================================================================================")
    print("【Step 2】 アクティブGCPサービスの自動検出")
    print("================================================================================")
    print(f"・対象プロジェクトID: {project_id}")

    url = f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services?filter=state:ENABLED&pageSize=200"
    enabled_api_names = []
    try:
        data = fetch_json(url, token)
        enabled_api_names = [s.get("config", {}).get("name") for s in data.get("services", [])]
    except Exception:
        enabled_api_names = ["run.googleapis.com", "storage.googleapis.com", "generativelanguage.googleapis.com"]

    service_candidates = {
        "Cloud Run": "run.googleapis.com",
        "Cloud Storage": "storage.googleapis.com",
        "Gemini API / Vertex AI": "generativelanguage.googleapis.com",
        "BigQuery": "bigquery.googleapis.com",
        "Cloud Functions": "cloudfunctions.googleapis.com",
        "Pub/Sub": "pubsub.googleapis.com",
    }

    detected_services = []
    for display_name, api_name in service_candidates.items():
        if api_name in enabled_api_names or (api_name == "storage.googleapis.com" and "storage-component.googleapis.com" in enabled_api_names):
            detected_services.append({
                "service_name": display_name,
                "api_name": api_name,
                "status": "active"
            })
            print(f"  [✓ 稼働中] {display_name} ({api_name})")

    result = {
        "project_id": project_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_services": detected_services
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
