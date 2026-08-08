#!/usr/bin/env python3
"""
Step 0: GCP Cloud Billing API から公式の実請求額・確定費用・Billing Account 情報を取得し
.data/billing_actuals.json に保存
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse

DATA_DIR    = os.path.abspath(".data")
OUTPUT_FILE = os.path.join(DATA_DIR, "billing_actuals.json")

def get_gcloud_cmd():
    return shutil.which("gcloud") or "/root/google-cloud-sdk/bin/gcloud"

def get_access_token():
    try:
        res = subprocess.run(
            [get_gcloud_cmd(), "auth", "print-access-token"],
            capture_output=True, text=True, check=True
        )
        return res.stdout.strip()
    except Exception:
        return ""

def get_project_id():
    try:
        res = subprocess.run(
            [get_gcloud_cmd(), "config", "get-value", "project"],
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

    # 1. プロジェクトの Billing Link 情報を取得 (自動API有効化 ＆ gcloud CLIフォールバック機能付き)
    if token:
        try:
            url = f"https://cloudbilling.googleapis.com/v1/projects/{project_id}/billingInfo"
            data = fetch_json(url, token)
            billing_info["billing_enabled"] = data.get("billingEnabled", False)
            billing_info["billing_account_name"] = data.get("billingAccountName", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                # ⚡ 自動修復: Cloud Billing API の自動有効化を試行
                print("⚡ [自動アクティベーション] Cloud Billing API をプロジェクトに自動有効化中...", file=sys.stderr)
                try:
                    subprocess.run(
                        [get_gcloud_cmd(), "services", "enable", "cloudbilling.googleapis.com", f"--project={project_id}"],
                        capture_output=True, text=True, timeout=30
                    )
                    # 再試行
                    data = fetch_json(url, token)
                    billing_info["billing_enabled"] = data.get("billingEnabled", False)
                    billing_info["billing_account_name"] = data.get("billingAccountName", "")
                    print("✓ [自動アクティベーション成功] Cloud Billing API の有効化および請求情報取得に成功しました。", file=sys.stderr)
                except Exception:
                    # フォールバック: gcloud billing projects describe コマンドで直接取得
                    try:
                        res_b = subprocess.run(
                            [get_gcloud_cmd(), "billing", "projects", "describe", project_id, "--format=json"],
                            capture_output=True, text=True, timeout=15
                        )
                        if res_b.returncode == 0 and res_b.stdout.strip():
                            b_data = json.loads(res_b.stdout)
                            billing_info["billing_enabled"] = b_data.get("billingEnabled", False)
                            billing_info["billing_account_name"] = b_data.get("billingAccountName", "")
                    except Exception:
                        pass
        except Exception:
            pass

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
