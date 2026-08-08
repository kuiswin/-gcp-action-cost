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
from datetime import datetime, timezone, timedelta
import json
import os
import subprocess
import sys
import time
import urllib.request

RAW_BASE_URL = "https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/"

def to_jst_str(iso_str):
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        jst_dt = dt.astimezone(timezone(timedelta(hours=9)))
        return jst_dt.strftime("%Y-%m-%d %H:%M:%S JST")
    except Exception:
        return iso_str

def get_base_dir():
    try:
        main_file = __file__
        if main_file and not main_file.startswith("/dev/fd") and os.path.exists(main_file):
            return os.path.dirname(os.path.abspath(main_file))
    except Exception:
        pass
    return os.getcwd()

def run_step(step_num, project_id=None, extra_env=None):
    step_scripts = {
        0: "00_billing_actuals.py",
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

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    if os.path.exists(script_path):
        cmd = [sys.executable, script_path]
        if step_num == 1 and project_id:
            cmd.append(project_id)
        res = subprocess.run(cmd, env=env)
        return res.returncode == 0
    else:
        # キャッシュ完全回避のタイムスタンプ付きURLで最新スクリプトを取得
        raw_url = f"{RAW_BASE_URL}{script_name}?t={int(time.time() * 1000)}"
        tmp_dir = os.path.abspath(".data")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_file = os.path.join(tmp_dir, f"_tmp_{script_name}")

        # 古い一時キャッシュスクリプトの即時強制削除
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass

        try:
            req = urllib.request.Request(raw_url, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                code = resp.read().decode("utf-8")
                
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(code)
                
            cmd = [sys.executable, tmp_file]
            if step_num == 1 and project_id:
                cmd.append(project_id)
            res = subprocess.run(cmd, env=env)
            
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            return res.returncode == 0
        except Exception as e:
            print(f"❌ GitHubからのステップ読み込みに失敗しました ({raw_url}): {e}", file=sys.stderr)
            return False

SNAP_DIR  = os.path.join(os.path.abspath(".data"), "snapshots")
SNAP_FILE = os.path.join(os.path.abspath(".data"), "snapshot.json")


def save_snapshot(usage_delta_file):
    """生カウンター累積値をタイムスタンプ付きスナップショットファイルとして保存する。"""
    if not os.path.exists(usage_delta_file):
        return
    with open(usage_delta_file, "r", encoding="utf-8") as f:
        delta = json.load(f)

    os.makedirs(SNAP_DIR, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    ts_str = now_dt.strftime("%Y%m%d_%H%M%S")
    snap_filename = f"snap_{ts_str}.json"
    snap_filepath = os.path.join(SNAP_DIR, snap_filename)

    raw_counters = delta.get("raw_30_counters") or delta.get("time_matrix", {}).get("30_days", {})
    snap = {
        "snapshot_filename": snap_filename,
        "saved_at_utc":      delta.get("measured_at"),
        "project_id":        delta.get("project_id"),
        "raw_counters":      raw_counters,
    }

    # 履歴フォルダ (.data/snapshots/) へ保存
    with open(snap_filepath, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)

    # 基準点ショートカット (.data/snapshot.json) を最新値で更新
    with open(SNAP_FILE, "w", encoding="utf-8") as f:
        json.dump({"saved_at": delta.get("measured_at"), "project_id": delta.get("project_id"), "raw_30d": raw_counters}, f, indent=2, ensure_ascii=False)

    print(f"\n💾 スナップショット保存完了: .data/snapshots/{snap_filename}")


def main():
    parser = argparse.ArgumentParser(description="GCP Action Cost Profiler (All-in-One CLI)")
    parser.add_argument("--step",    type=int, choices=[0, 1, 2, 3, 4, 5], help="指定したステップのみ実行 (0-5)")
    parser.add_argument("--project", help="GCP Project ID")
    parser.add_argument("-r", "--refresh", action="store_true",
                        help="キャッシュを破棄してGCP Catalog APIから単価マスターを強制再取得")
    parser.add_argument("-s", "--snap", action="store_true",
                        help="差分計測モード (.data/snapshot.jsonの有無で自動判定されるため指定は任意)")

    args, unknown = parser.parse_known_args()
    if "-r" in unknown or "--refresh" in unknown:
        args.refresh = True

    if args.step:
        print(f"🚀 Step {args.step} を実行します...")
        success = run_step(args.step, args.project)
        sys.exit(0 if success else 1)

    # ----------------------------------------------------------------
    # 自動スナップショット＆差分計算モード（.data/snapshot.json の有無で自動分岐）
    # ----------------------------------------------------------------
    has_snap    = os.path.exists(SNAP_FILE)
    extra_env   = {}

    if args.refresh:
        extra_env["COST_FORCE_REFRESH"] = "1"
        print("🔄 強制リフレッシュモード: キャッシュを無効化してGCP APIから最新データを再取得します")

    if has_snap:
        # 差分モード: 前回スナップのタイムスタンプ以降のデータと直前カウンターを比較
        try:
            with open(SNAP_FILE, "r", encoding="utf-8") as f:
                snap = json.load(f)
            snap_time = snap.get("saved_at") or snap.get("data_until")
            extra_env["COST_SNAP_SINCE"] = snap_time or ""
            extra_env["COST_SNAP_RAW"]   = json.dumps(snap.get("raw_30d", {}))
            print("================================================================================")
            print("🔍 自動差分比較モード: 直前のスナップショットとの比較＆現行コスト表示")
            print(f"   直前基準点: {to_jst_str(snap_time)}")
            print("================================================================================")
        except Exception:
            has_snap = False

    if not has_snap:
        print("================================================================================")
        print("🚀 GCP Action Cost Profiler (初回実行: スナップショット自動生成)")
        print("================================================================================")

    for step in range(0, 6):
        print()
        success = run_step(step, args.project, extra_env=extra_env)
        if not success:
            print(f"❌ Step {step} の実行でエラーが発生したため中断しました。", file=sys.stderr)
            sys.exit(1)

    # 毎回自動で最新状態をスナップショットとして保存・更新
    usage_delta_file = os.path.join(os.path.abspath(".data"), "usage_delta.json")
    save_snapshot(usage_delta_file)

    if has_snap:
        print("\n💰 差分計算および現行コスト計算が完了しました。スナップショットを更新しました。")
    else:
        print("\n🎉 初回プロファイリング完了！スナップショットを自動作成しました。")
        print("👉 アプリの操作を実行後、再度 `python3 calc_cost.py` を実行すると自動で増分コストが表示されます💰")


if __name__ == "__main__":
    main()

