#!/usr/bin/env python3
"""
Step 5: Step 3 (ハイブリッド適用単価) × Step 4 (時間軸マトリックス消費量) を掛け算して最終コストプロファイリングを出力
"""

import json
import os
import sys

DATA_DIR = os.path.abspath(".data")
TARGET_PRICING_FILE = os.path.join(DATA_DIR, "target_pricing.json")
USAGE_DELTA_FILE = os.path.join(DATA_DIR, "usage_delta.json")
OUTPUT_FILE = os.path.join(DATA_DIR, "action_cost_result.json")

def main():
    print("================================================================================")
    print("【Step 5】 最終時間軸マトリックス・コストプロファイリング (Step 3 単価 × Step 4 消費量)")
    print("================================================================================")

    if not os.path.exists(TARGET_PRICING_FILE):
        print("❌ Error: 03_service_pricing.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(USAGE_DELTA_FILE):
        print("❌ Error: 04_measure_delta.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(TARGET_PRICING_FILE, "r", encoding="utf-8") as f:
        pricing_data = json.load(f).get("target_unit_prices", {})

    with open(USAGE_DELTA_FILE, "r", encoding="utf-8") as f:
        delta_data = json.load(f)

    # 適用単価の取り出し
    run_prices = pricing_data.get("cloud_run", {})
    cpu_price = run_prices.get("cpu_per_vcpu_sec_jpy", 0.00372)
    req_price = run_prices.get("request_per_count_jpy", 0.000062)

    gcs_prices = pricing_data.get("cloud_storage", {})
    gcs_read_price = gcs_prices.get("class_b_read_per_op_jpy", 0.000062)
    gcs_write_price = gcs_prices.get("class_a_write_per_op_jpy", 0.000775)

    matrix = delta_data.get("time_matrix", {})
    project_id = delta_data.get("project_id", "qiita-app-170")

    result_matrix = {}

    print(f"・対象プロジェクトID: {project_id}\n")
    print(f"{'時間軸ウィンドウ':<15} | {'リクエスト数':<10} | {'CPU秒数':<12} | {'インフラ計算定価':<15} | {'実際の請求額'}")
    print("-" * 75)

    for label, metrics in matrix.items():
        reqs = metrics.get("request_count", 0)
        cpu_sec = metrics.get("cpu_seconds", 0.0)
        gcs_read = metrics.get("gcs_read_ops", 0)
        gcs_write = metrics.get("gcs_write_ops", 0)

        cost_cpu = cpu_sec * cpu_price
        cost_req = reqs * req_price
        cost_gcs = (gcs_read * gcs_read_price) + (gcs_write * gcs_write_price)
        total_list_cost = cost_cpu + cost_req + cost_gcs

        result_matrix[label] = {
            "request_count": reqs,
            "cpu_seconds": cpu_sec,
            "cost_cpu_jpy": cost_cpu,
            "cost_req_jpy": cost_req,
            "cost_gcs_jpy": cost_gcs,
            "total_list_cost_jpy": total_list_cost,
            "actual_billed_jpy": 0.0
        }

        disp_label = label.replace("_", " ")
        print(f"{disp_label:<15} | {reqs:>10,} 回 | {cpu_sec:>10.2f} 秒 | {total_list_cost:>12.6f} 円 | ￥0 (無料枠内)")

    result = {
        "project_id": project_id,
        "pricing_applied": {
            "cpu_price_per_sec": cpu_price,
            "request_price_per_count": req_price,
            "gcs_read_price": gcs_read_price,
            "gcs_write_price": gcs_write_price
        },
        "cost_matrix": result_matrix
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("-" * 75)
    print("💡 ポイント: GCP Web画面では少額すぎて「￥0」と表示されますが、Step 3 単価 × Step 4 時間軸マトリックスにより精密可視化に成功しました！")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
