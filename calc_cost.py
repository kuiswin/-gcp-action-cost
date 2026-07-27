#!/usr/bin/env python3
"""
GCP Action Cost Profiler (calc_cost.py)
--------------------------------------------------------------------------------
5ステップ（出世魚パイプライン）を順次実行して JSON パイプラインでデータを引き継ぎ、
1所作コストと月間実績を完全算出する All-in-One CLI エントリポイントです。
--------------------------------------------------------------------------------
"""

import argparse
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(__file__)

def run_step(step_num, project_id=None):
    step_scripts = {
        1: "01_catalog_pricing.py",
        2: "02_active_services.py",
        3: "03_service_pricing.py",
        4: "04_measure_delta.py",
        5: "05_action_cost.py",
    }
    script_name = step_scripts.get(step_num)
    if not script_name:
        print(f"❌ 無効なステップ番号です: {step_num}", file=sys.stderr)
        return False

    script_path = os.path.join(BASE_DIR, script_name)
    cmd = [sys.executable, script_path]
    if step_num == 2 and project_id:
        cmd.append(project_id)

    res = subprocess.run(cmd)
    return res.returncode == 0

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
