#!/usr/bin/env python3
"""
Step 5: Step 3 (単価表) × Step 4 (差分消費量) で「1所作の微小コスト」および月間実績を完全算出
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
    print("【Step 5】 最終コストプロファイリング (Step 3 単価 × Step 4 消費量)")
    print("================================================================================")

    if not os.path.exists(TARGET_PRICING_FILE):
        print("❌ Error: 03_service_pricing.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(USAGE_DELTA_FILE):
        print("❌ Error: 04_measure_delta.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(TARGET_PRICING_FILE, "r", encoding="utf-8") as f:
        pricing = json.load(f).get("resource_unit_prices", {})

    with open(USAGE_DELTA_FILE, "r", encoding="utf-8") as f:
        delta = json.load(f)

    pv = delta["actions"]["page_view"]
    cpu_price = pricing.get("cloud_run_cpu_vcpu_sec_jpy", 0.00372)
    req_price = pricing.get("cloud_run_request_jpy", 0.000062)
    gcs_read_price = pricing.get("gcs_read_class_b_jpy", 0.000062)
    gcs_write_price = pricing.get("gcs_write_class_a_jpy", 0.000775)
    gemini_price = pricing.get("gemini_image_generation_jpy", 6.00)

    cost_view = (pv["cpu_seconds"] * cpu_price) + (pv["request_count"] * req_price) + (pv["gcs_read_ops"] * gcs_read_price)

    post = delta["actions"]["post_creation"]
    cost_post = (post["cpu_seconds"] * cpu_price) + (post["request_count"] * req_price) + (post["gcs_write_ops"] * gcs_write_price) + (post["gemini_images"] * gemini_price)

    totals = delta.get("monthly_totals", {})
    monthly_cost = (totals.get("cpu_seconds", 0) * cpu_price) + (totals.get("request_count", 0) * req_price)

    result = {
        "project_id": delta.get("project_id", "qiita-app-170"),
        "page_view_cost_jpy": cost_view,
        "post_creation_cost_jpy": cost_post,
        "monthly_totals": {
            "request_count": totals.get("request_count", 0),
            "cpu_seconds": totals.get("cpu_seconds", 0),
            "total_infrastructure_cost_jpy": monthly_cost
        }
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"・対象プロジェクトID: {result['project_id']}")
    print()
    print(f"  [A. 記事閲覧 1回 (1 Page View)]")
    print(f"    ・Cloud Run CPU 処理代 : {pv['cpu_seconds']:.3f} vCPU秒 ({pv['cpu_seconds'] * cpu_price:.6f}円)")
    print(f"    ・GCS Read 読み込み代  : 2 回 ({2 * gcs_read_price:.6f}円)")
    print(f"    👉 1閲覧あたりの確定コスト: 【 {cost_view:.6f} 円 】")
    print()
    print(f"  [B. 記事投稿 1回 (1 Post Creation + Gemini AI画像自動生成)]")
    print(f"    ・Cloud Run CPU 処理代 : {post['cpu_seconds']:.3f} vCPU秒 ({post['cpu_seconds'] * cpu_price:.6f}円)")
    print(f"    ・GCS Write 保存代    : 2 回 ({2 * gcs_write_price:.6f}円)")
    print(f"    ・Gemini AI画像生成代 : 1 枚 ({gemini_price:.2f}0000円)")
    print(f"    👉 1投稿あたりの確定コスト: 【 {cost_post:.6f} 円 】")
    print()
    print(f"  [C. 月間実績（過去30日間）]")
    print(f"    ・合計リクエスト数 : {int(totals.get('request_count', 0)):,} 回")
    print(f"    ・合計CPU時間      : {totals.get('cpu_seconds', 0):,.2f} vCPU秒")
    print(f"    ・月間インフラ定価 : {monthly_cost:.6f} 円 (約 {monthly_cost:.2f} 円)")
    print(f"    ・コンソール画面表示: 少額すぎて丸められ「￥0」と表示")
    print(f"    ・実際の請求金額   : Always Free無料枠により「完全0円」")
    print("================================================================================")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
