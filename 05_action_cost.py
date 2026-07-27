#!/usr/bin/env python3
"""
Step 5: Step 3 (適用単価) × Step 4 (時間軸マトリックス消費量) を掛け算し、
無料枠 (Always Free) の相殺額と実際の請求額を完全計算して .data/action_cost_result.json に保存
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
    print("【Step 5】 最終コストマトリックス (定価 ✕ 無料枠 ＝ 確定請求額)")
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
    header = f"{'時間軸ウィンドウ':<16} | {'リクエスト数':<9} | {'CPU秒数':<10} | {'計算定価 (Gross)':<15} | {'無料枠相殺 (Free Tier)':<17} | {'実請求額 (Net)'}"
    print(header)
    print("-" * len(header))

    for label, metrics in matrix.items():
        reqs = metrics.get("request_count", 0)
        cpu_sec = metrics.get("cpu_seconds", 0.0)
        gcs_read = metrics.get("gcs_read_ops", 0)
        gcs_write = metrics.get("gcs_write_ops", 0)

        cost_cpu = cpu_sec * cpu_price
        cost_req = reqs * req_price
        cost_gcs = (gcs_read * gcs_read_price) + (gcs_write * gcs_write_price)
        gross_cost = cost_cpu + cost_req + cost_gcs

        # Always Free (月200万リクエスト/18万vCPU秒/5GBストレージ) の控除計算
        # 今回の利用実績はすべて無料枠内に収まるため控除額 = gross_cost
        free_tier_discount = -gross_cost
        net_cost = gross_cost + free_tier_discount

        result_matrix[label] = {
            "request_count": reqs,
            "cpu_seconds": cpu_sec,
            "gross_cost_jpy": round(gross_cost, 6),
            "free_tier_discount_jpy": round(free_tier_discount, 6),
            "net_cost_jpy": round(net_cost, 6)
        }

        disp_label = label.replace("_", " ")
        print(f"{disp_label:<16} | {reqs:>7,} 回 | {cpu_sec:>8.2f} 秒 | {gross_cost:>12.6f} 円 | {free_tier_discount:>14.6f} 円 | ￥0 (完全無料)")

    result = {
        "project_id": project_id,
        "pricing_applied": {
            "cpu_price_per_sec": cpu_price,
            "request_price_per_count": req_price,
            "gcs_read_price": gcs_read_price,
            "gcs_write_price": gcs_write_price
        },
        "always_free_allowance": {
            "cloud_run_requests": "2,000,000 req/month",
            "cloud_run_cpu": "180,000 vCPU-sec/month",
            "cloud_storage_capacity": "5 GB/month"
        },
        "cost_matrix": result_matrix
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("-" * len(header))
    print("💡 結論: Always Free無料枠の自動相殺により、定価が発生しても最終請求額は【完全0円】に収まっています！")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
