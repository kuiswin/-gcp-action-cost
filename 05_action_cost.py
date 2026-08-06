#!/usr/bin/env python3
"""
Step 5: 既定のGCP公式無料枠 (Always Free) からの実用引き算プロファイリング

- 表①: リソース別・既定のGCP無料枠からの引き算 & 枠残り容量 & 確定請求額
- 表②: 時間軸マトリックス (消費量 × 単価の定価計算 ➔ 確定請求額)

出力形式: JSON (日本語混じりターミナル表はアライメントが崩れるため)
を .data/action_cost_result.json に保存・ターミナル出力
"""

import json
import os
import sys

DATA_DIR            = os.path.abspath(".data")
TARGET_PRICING_FILE = os.path.join(DATA_DIR, "target_pricing.json")
USAGE_DELTA_FILE    = os.path.join(DATA_DIR, "usage_delta.json")
OUTPUT_FILE         = os.path.join(DATA_DIR, "action_cost_result.json")
SERVICE_RULES_FILE  = os.path.join(DATA_DIR, "..", "service_rules.json")
if not os.path.exists(SERVICE_RULES_FILE):
    SERVICE_RULES_FILE = os.path.join(DATA_DIR, "service_rules.json")

def load_provisioned_services():
    rules_path = os.path.abspath(SERVICE_RULES_FILE)
    if os.path.exists(rules_path):
        try:
            with open(rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("provisioned_services", []))
        except Exception:
            pass
    return {"bigtable_node_hours", "spanner_node_hours", "alloydb_cpu_hours"}

PROVISIONED_SERVICES = load_provisioned_services()

def build_metric_catalog(pricing_data):
    """
    target_pricing.json の target_unit_prices から
    {metric_key: {label, unit, price_jpy, free_limit, free_limit_display, service_key}} を構築する。
    """
    catalog = {}
    for service_key, service_entry in pricing_data.items():
        unit_prices  = service_entry.get("unit_prices", service_entry)  # 旧形式互換
        free_metrics = service_entry.get("free_tier_metrics", {})

        for metric_key, meta in free_metrics.items():
            price_key = meta.get("price_key", "")
            price_jpy = unit_prices.get(price_key, 0.0)
            catalog[metric_key] = {
                "label":              meta.get("label", metric_key),
                "unit":               meta.get("unit", ""),
                "price_jpy":          price_jpy,
                "free_limit":         meta.get("free_limit", 0.0),
                "free_limit_display": meta.get("free_limit_display", "従量制"),
                "service_key":        service_key,
            }
    return catalog


def fmt_val(val, unit):
    """数値を読みやすく整形して単位を付ける。"""
    if val == int(val):
        return f"{int(val):,} {unit}"
    return f"{val:,.2f} {unit}"


def main():
    print("================================================================================")
    print("【Step 5】 既定GCP無料枠からの引き算プロファイリング ＆ 最終コスト試算")
    print("================================================================================")

    if not os.path.exists(TARGET_PRICING_FILE):
        print("❌ Error: 03_service_pricing.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(USAGE_DELTA_FILE):
        print("❌ Error: 04_measure_delta.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(TARGET_PRICING_FILE, "r", encoding="utf-8") as f:
        full_pricing = json.load(f)

    with open(USAGE_DELTA_FILE, "r", encoding="utf-8") as f:
        delta_data = json.load(f)

    BILLING_ACTUALS_FILE = os.path.join(DATA_DIR, "billing_actuals.json")
    billing_actuals = {}
    if os.path.exists(BILLING_ACTUALS_FILE):
        try:
            with open(BILLING_ACTUALS_FILE, "r", encoding="utf-8") as f:
                billing_actuals = json.load(f)
        except Exception:
            pass

    project_id   = delta_data.get("project_id", "")
    matrix       = delta_data.get("time_matrix", {})
    m30          = matrix.get("30_days", {})
    pricing_data = full_pricing.get("target_unit_prices", {})

    metric_catalog = build_metric_catalog(pricing_data)

    print(f"・対象プロジェクトID: {project_id}")
    if billing_actuals:
        status_txt = "有効 (Billing Enabled)" if billing_actuals.get("billing_enabled") else "未有効/プロモーション枠"
        print(f"・[公式Billing API] ステータス: {status_txt}")
        if billing_actuals.get("billing_account_name"):
            print(f"・[公式Billing API] アカウント: {billing_actuals.get('billing_account_name')}")

    raw_30_counters = delta_data.get("raw_30_counters", {})
    snap_elapsed_seconds = delta_data.get("snap_elapsed_seconds", 0.0)
    is_snap = bool(os.environ.get("COST_SNAP_SINCE", ""))

    def calculate_subtraction_rows(counters, is_diff_mode=False):
        rows = []
        total_billed = 0.0
        total_gross = 0.0
        val_header = "操作増分 (Diff)" if is_diff_mode else "30日累計消費量"

        for metric_key, value in counters.items():
            if metric_key == "window_minutes":
                continue
            meta = metric_catalog.get(metric_key)
            if meta is None:
                continue

            label       = meta["label"]
            unit        = meta["unit"]
            price_jpy   = meta["price_jpy"]
            free_limit  = meta["free_limit"]
            free_display= meta["free_limit_display"]

            display_value = value
            if is_diff_mode and metric_key in PROVISIONED_SERVICES and snap_elapsed_seconds > 0:
                live_nodes = value / 720.0
                inc_node_hours = live_nodes * (snap_elapsed_seconds / 3600.0)
                display_value = inc_node_hours
                gross = inc_node_hours * price_jpy
            else:
                gross = value * price_jpy

            total_gross += gross
            gross_str = f"￥{gross:,.4f}" if gross > 0 else "￥0 (未使用)"

            if free_limit > 0:
                over    = max(0.0, display_value - free_limit)
                rem     = free_limit - min(display_value, free_limit)
                pct_rem = (rem / free_limit) * 100.0
                billed  = over * price_jpy
                total_billed += billed
                row = {
                    "リソース":         label,
                    val_header:         fmt_val(display_value, unit),
                    "インフラ定価 (控除前)": gross_str,
                    "無料枠上限":       free_display,
                    "無料枠残量":       fmt_val(rem, unit),
                    "残量率":           f"{pct_rem:.2f}%",
                    "超過消費量":       fmt_val(over, unit),
                    "確定請求 (控除後)": "￥0 (完全無料)" if billed == 0 else f"￥{billed:,.4f}",
                }
            else:
                billed = gross
                total_billed += billed
                snap_time_suffix = f" (経過 {snap_elapsed_seconds:.0f}秒)" if (is_diff_mode and snap_elapsed_seconds > 0) else ""
                row = {
                    "リソース":         label,
                    val_header:         f"{fmt_val(display_value, unit)}{snap_time_suffix}",
                    "インフラ定価 (控除前)": gross_str,
                    "無料枠上限":       free_display,
                    "無料枠残量":       "従量制枠なし",
                    "残量率":           "N/A",
                    "超過消費量":       fmt_val(display_value, unit),
                    "確定請求 (控除後)": "￥0 (未使用)" if display_value == 0 else f"￥{billed:,.4f}",
                }

            rows.append(row)
        return rows, total_billed, total_gross

    # 1. 差分モード時: 表① (増分Diff明細)
    if is_snap:
        diff_rows, diff_billed_total, diff_gross_total = calculate_subtraction_rows(m30, is_diff_mode=True)
        print("\n【表①: 操作前後の増分コスト (Diff) 明細】")
        print(json.dumps(diff_rows, ensure_ascii=False, indent=2))
        print(f"👉 直前操作の増分定価 (控除前): ￥{diff_gross_total:,.4f}  ➔  無料枠控除後の増分確定請求額: ￥{diff_billed_total:,.4f}")

    # 2. 常に全量表示: 表② (過去30日間 全量累計消費 & 確定請求額明細)
    total_rows, total_billed_all, total_gross_all = calculate_subtraction_rows(raw_30_counters, is_diff_mode=False)
    table2_title = "【表②: 過去30日間 全量リソース消費 ＆ 確定・推計請求額明細】" if is_snap else "【表①: 過去30日間 全量リソース消費 ＆ 確定・推計請求額明細】"
    print(f"\n{table2_title}")
    print(json.dumps(total_rows, ensure_ascii=False, indent=2))
    print(f"\n👉 過去30日間の本来のインフラ定価合計 (控除前): ￥{total_gross_all:,.4f}")
    if total_billed_all == 0:
        print("👉 無料枠適用後の確定請求額合計 (控除後): 【 ￥0 (完全無料) 】")
    else:
        print(f"👉 無料枠適用後の確定請求額合計 (控除後): ￥{total_billed_all:,.4f}")

    # --------------------------------------------------------------------------
    # 表②: 時間軸マトリックス × 単価 (JSON出力)
    # --------------------------------------------------------------------------
    billable = {
        k: v for k, v in metric_catalog.items()
        if v.get("price_jpy", 0) > 0
    }

    label_order = ["1_minute", "10_minutes", "1_hour", "1_day", "30_days"]
    time_matrix_out = {}
    result_matrix   = {}

    for label in label_order:
        metrics = matrix.get(label)
        if metrics is None:
            continue

        disp_label = label.replace("_", " ")
        gross      = 0.0
        detail     = []

        for mkey, meta in billable.items():
            val   = metrics.get(mkey, 0.0)
            price = meta["price_jpy"]
            unit  = meta["unit"]
            cost  = val * price
            gross += cost
            if cost < 5e-7:     # 表示上ゼロになるものはスキップ
                continue
            detail.append({
                "サービス": meta["label"],
                "消費量":   fmt_val(val, unit),
                "単価":     f"{price:.6f} 円/{unit}",
                "掛け算結果": f"{cost:.6f} 円",
            })

        time_matrix_out[disp_label] = {
            "明細":         detail if detail else [{"サービス": "(消費なし)"}],
            "小計":         f"{gross:.6f} 円",
            "確定請求額":   "￥0 (無料枠内)",
        }

        result_matrix[label] = {
            **{k: metrics.get(k, 0.0) for k in billable},
            "gross_cost_jpy": round(gross, 6),
            "net_billed_jpy": 0.0,
        }

    print("\n【表②: 時間軸マトリックス・インフラ計算定価 ＆ 確定請求額】")
    print(json.dumps(time_matrix_out, ensure_ascii=False, indent=2))

    # --------------------------------------------------------------------------
    # JSON保存
    # --------------------------------------------------------------------------
    result = {
        "project_id":                    project_id,
        "free_tier_subtractions_30days": total_rows,
        "diff_subtractions":              diff_rows if is_snap else [],
        "time_matrix":                   result_matrix,
        "total_billed_jpy":              round(total_billed_all, 6),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n💾 保持ファイル: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
