#!/usr/bin/env python3
"""
GCP Action Cost Profiler (calc_cost.py)
--------------------------------------------------------------------------------
5ステップ順次実行（ローカルJSONパイプライン）エントリポイント:

Step 1: 01_active_services.py  (プロジェクト内全有効化GCPサービスの網羅的マスター検出)
Step 2: 02_catalog_pricing.py  (GCP Catalog API 全サービス完全網羅・単価マスターの取得)
Step 3: 03_service_pricing.py  (アプリ稼働コアサービスへの厳選マッピング)
Step 4: 04_measure_delta.py    (時間軸マトリックス別リソース消費量 1回API照会 ➔ ローカル高速算出)
Step 5: 05_action_cost.py      (サービス別数式明細 ＆ 時間軸マトリックス・コストプロファイリング)
--------------------------------------------------------------------------------
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request

RAW_BASE_URL = "https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/"

def get_base_dir():
    try:
        main_file = __file__
        if main_file and not main_file.startswith("/dev/fd") and os.path.exists(main_file):
            return os.path.dirname(os.path.abspath(main_file))
    except Exception:
        pass
    return os.getcwd()

def run_step(step_num, project_id=None):
    step_scripts = {
        1: "01_active_services.py",
        2: "02_catalog_pricing.py",
        3: "03_service_pricing.py",
        4: "04_measure_delta.py",
        5: "05_action_cost.py",
    }
    script_name = step_scripts.get(step_num)
    if not script_name:
        print(f"❌ 無効なステップ番号です: {step_num}", file=sys.stderr)
        return False

    base_dir = get_base_dir()
    script_path = os.path.join(base_dir, script_name)

    if os.path.exists(script_path):
        cmd = [sys.executable, script_path]
        if step_num == 1 and project_id:
            cmd.append(project_id)
        res = subprocess.run(cmd)
        return res.returncode == 0
    else:
        # キャッシュ完全回避のタイムスタンプ付きURLで最新スクリプトを取得
        raw_url = f"{RAW_BASE_URL}{script_name}?t={int(time.time() * 1000)}"
        tmp_dir = os.path.abspath(".data")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, f"_tmp_{script_name}")

        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass

        try:
            req = urllib.request.Request(raw_url, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})
            with urllib.request.urlopen(req) as resp:
                code = resp.read().decode("utf-8")
                
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(code)
                
            cmd = [sys.executable, tmp_file]
            if step_num == 1 and project_id:
                cmd.append(project_id)
            res = subprocess.run(cmd)
            
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            return res.returncode == 0
        except Exception as e:
            print(f"❌ GitHubからのステップ読み込みに失敗しました ({raw_url}): {e}", file=sys.stderr)
            return False

def main():
    parser = argparse.ArgumentParser(description="GCP Action Cost Profiler (All-in-One CLI)")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5], help="指定したステップのみ実行 (1-5)")
    parser.add_argument("--project", help="GCP Project ID")

    args = parser.parse_args()

    if args.step:
        print(f"🚀 Step {args.step} を実行します...")
        success = run_step(args.step, args.project)
        sys.exit(0 if success else 1)

    print("================================================================================")
    print("🚀 GCP Action Cost Profiler (5ステップ・一括実行パイプライン)")
    print("================================================================================")

    for step in range(1, 6):
        print()
        success = run_step(step, args.project)
        if not success:
            print(f"❌ Step {step} の実行でエラーが発生したため中断しました。", file=sys.stderr)
            sys.exit(1)

    print("\n🎉 全5ステップの処理およびJSON連携が完了しました！")

if __name__ == "__main__":
    main()
