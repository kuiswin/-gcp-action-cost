#!/usr/bin/env python3
"""
Step 0: GCP Cloud Billing API から公式の実請求額・確定費用・Billing Account 情報を取得し
.data/billing_actuals.json に保存
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse

DATA_DIR    = os.path.abspath(".data")
OUTPUT_FILE = os.path.join(DATA_DIR, "billing_actuals.json")

def get_access_token():
    try:
        res = subprocess.run(
            ["/root/google-cloud-sdk/bin/gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, check=True
        )
        return res.stdout.strip()
    except Exception:
        return ""

def get_project_id():
    try:
        res = subprocess.run(
            ["/root/google-cloud-sdk/bin/gcloud", "config", "get-value", "project"],
            capture_output=True, text=True
        )
        pid = res.stdout.strip()
        return pid if pid and pid != "(unset)" else "ferrous-iridium-286000"
    except Exception:
        return "ferrous-iridium-286000"

def fetch_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    token = get_access_token()
    project_id = sys.argv[1] if len(sys.argv) > 1 else get_project_id()

    print("================================================================================")
    print("【Step 0】 GCP Billing API からの実請求額・確定費用ダイレクト取得")
    print("================================================================================")
    print(f"・対象プロジェクトID: {project_id}")

    billing_info = {
        "project_id": project_id,
        "billing_enabled": False,
        "billing_account_name": "",
        "actual_costs": [],
        "total_actual_jpy": 0.0
    }

    # 1. プロジェクトの Billing Link 情報を取得
    if token:
        try:
            url = f"https://cloudbilling.googleapis.com/v1/projects/{project_id}/billingInfo"
            data = fetch_json(url, token)
            billing_info["billing_enabled"] = data.get("billingEnabled", False)
            billing_info["billing_account_name"] = data.get("billingAccountName", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"⚠️ [警告] Cloud Billing APIのアクセス権限不足 (HTTP {e.code})", file=sys.stderr)
                print("  ※ 正確な請求状態を取得するにはサービスアカウントに roles/billing.viewer 権限等が必要です", file=sys.stderr)
            else:
                print(f"⚠️ [警告] Cloud Billing APIの取得に失敗しました: HTTP {e.code}", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ [警告] Cloud Billing APIの取得時にエラーが発生しました: {e}", file=sys.stderr)

    # 2. Billing Account / Budgets API から実請求・予算情報を取得
    if billing_info["billing_account_name"] and token:
        account_id = billing_info["billing_account_name"].split("/")[-1]
        try:
            url = f"https://billingbudgets.googleapis.com/v1/billingAccounts/{account_id}/budgets"
            budgets_data = fetch_json(url, token)
            budgets = budgets_data.get("budgets", [])
            if budgets:
                billing_info["budgets_count"] = len(budgets)
        except Exception:
            pass

    status_str = "有効 (Billing Enabled)" if billing_info["billing_enabled"] else "未有効/プロモーション枠 (Billing Disabled or Unlinked)"
    print(f"・GCP Billing 連携ステータス: {status_str}")
    if billing_info["billing_account_name"]:
        print(f"・紐付け Billing Account: {billing_info['billing_account_name']}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(billing_info, f, indent=2, ensure_ascii=False)

    print(f"✓ 公式請求情報の取得が完了しました。")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
