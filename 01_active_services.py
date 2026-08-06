#!/usr/bin/env python3
"""
Step 1: プロジェクト内で有効化されているすべてのGCPサービス・APIを絞らずマスター出力して .data/active_services.json に保存
"""

import json
import os
import subprocess
import sys
import urllib.request

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
    print("【Step 1】 プロジェクト内全有効化GCPサービスの網羅的マスター検出")
    print("================================================================================")
    print(f"・対象プロジェクトID: {project_id}")

    url = f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services?filter=state:ENABLED&pageSize=200"
    detected_services = []
    try:
        data = fetch_json(url, token)
        for s in data.get("services", []):
            api_name = s.get("config", {}).get("name", "")
            title = s.get("config", {}).get("title", api_name)
            detected_services.append({
                "service_name": title,
                "api_name": api_name,
                "status": "enabled"
            })
    except Exception as e:
        print(f"注: API取得フォールバック: {e}")

    FREE_INFRA_APIS = {
        "iam.googleapis.com",
        "iamcredentials.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "cloudbilling.googleapis.com",
        "serviceusage.googleapis.com",
        "logging.googleapis.com",
        "cloudaicompanion.googleapis.com",
        "geminicloudassist.googleapis.com"
    }

    core_services = []
    infra_apis = []

    for s in detected_services:
        if s["api_name"] in FREE_INFRA_APIS:
            infra_apis.append(s["service_name"])
        else:
            core_services.append(s["service_name"])

    print(f"✓ 有効化されている全GCPサービス: 計 {len(detected_services)} 件を検出")
    if core_services:
        print(f"  ・💰 コスト発生対象コアサービス ({len(core_services)} 件): {', '.join(core_services)}")
    else:
        print("  ・💰 コスト発生対象コアサービス (0 件): 現在プロビジョニング中の課金リソースはありません")

    if infra_apis:
        print(f"  ・🆓 無料管理・インフラ基盤API ({len(infra_apis)} 件): {', '.join(infra_apis)}")

    result = {
        "project_id": project_id,
        "total_count": len(detected_services),
        "core_services_count": len(core_services),
        "infra_apis_count": len(infra_apis),
        "active_services": detected_services
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
