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

    project_id   = delta_data.get("project_id", "")
    matrix       = delta_data.get("time_matrix", {})
    m30          = matrix.get("30_days", {})
    pricing_data = full_pricing.get("target_unit_prices", {})

    metric_catalog = build_metric_catalog(pricing_data)

    print(f"・対象プロジェクトID: {project_id}")

    # --------------------------------------------------------------------------
    # 表①: 無料枠引き算明細 (JSON出力)
    # --------------------------------------------------------------------------
    free_tier_rows = []
    billed_total   = 0.0
    is_snap = bool(os.environ.get("COST_SNAP_SINCE", ""))
    val_key = "操作増分 (Diff)" if is_snap else "30日累計消費量"

    snap_elapsed_seconds = delta_data.get("snap_elapsed_seconds", 0.0)

    for metric_key, value_30 in m30.items():
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

        # スナップモード（差分モード）時の継続稼働ノード時間補正
        display_value = value_30
        if is_snap and metric_key in ("bigtable_node_hours", "spanner_node_hours", "alloydb_cpu_hours") and snap_elapsed_seconds > 0:
            live_nodes = value_30 / 720.0
            inc_node_hours = live_nodes * (snap_elapsed_seconds / 3600.0)
            display_value = inc_node_hours
            gross = inc_node_hours * price_jpy
        else:
            gross = value_30 * price_jpy

        if free_limit > 0:
            over   = max(0.0, display_value - free_limit)
            rem    = free_limit - min(display_value, free_limit)
            pct_rem = (rem / free_limit) * 100.0
            billed  = over * price_jpy
            billed_total += billed
            row = {
                "リソース":         label,
                val_key:            fmt_val(display_value, unit),
                "無料枠上限":       free_display,
                "無料枠残量":       fmt_val(rem, unit),
                "残量率":           f"{pct_rem:.2f}%",
                "超過消費量":       fmt_val(over, unit),
                "確定請求":         "￥0 (完全無料)" if billed == 0 else f"￥{billed:,.4f}",
            }
        else:
            billed = gross
            billed_total += billed
            snap_time_suffix = f" (経過 {snap_elapsed_seconds:.0f}秒)" if (is_snap and snap_elapsed_seconds > 0) else ""
            row = {
                "リソース":         label,
                val_key:            f"{fmt_val(display_value, unit)}{snap_time_suffix}",
                "無料枠上限":       free_display,
                "無料枠残量":       "従量制枠なし",
                "残量率":           "N/A",
                "超過消費量":       fmt_val(display_value, unit),
                "確定請求":         "￥0 (未使用)" if display_value == 0 else f"￥{billed:,.4f}",
            }

        free_tier_rows.append(row)

    table_title = "【表①: 操作前後の増分コスト (Diff) 明細】" if is_snap else "【表①: 既定のGCP公式無料枠 (Always Free) からの引き算明細 (過去30日間)】"
    print(f"\n{table_title}")
    print(json.dumps(free_tier_rows, ensure_ascii=False, indent=2))

    if billed_total == 0:
        print("\n👉 結論: 全リソースで無料枠が十分に残っており、確定請求額は【 ￥0 】です。")
    else:
        print(f"\n👉 確定請求合計: ￥{billed_total:,.4f}")

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
        "free_tier_subtractions_30days": free_tier_rows,
        "time_matrix":                   result_matrix,
        "total_billed_jpy":              round(billed_total, 6),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n💾 保持ファイル: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
