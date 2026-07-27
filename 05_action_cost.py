#!/usr/bin/env python3
"""
Step 5: 既定のGCP公式無料枠 (Always Free) からの実用引き算プロファイリング

- 表①: リソース別・既定のGCP無料枠からの引き算 & 枠残り容量 & 確定請求額
         → usage_delta.json のメトリクスキー × target_pricing.json の free_tier_metrics
            で完全動的生成 (ハードコードなし)
- 表②: 時間軸マトリックス (消費量 × 単価の定価計算数式 ➔ 確定請求額)
         → 計算対象メトリクスも target_pricing.json から動的に決定

を .data/action_cost_result.json に保存・ターミナル出力
"""

import json
import os
import sys

DATA_DIR         = os.path.abspath(".data")
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
        unit_prices    = service_entry.get("unit_prices", service_entry)  # 旧形式互換
        free_metrics   = service_entry.get("free_tier_metrics", {})

        for metric_key, meta in free_metrics.items():
            price_key  = meta.get("price_key", "")
            price_jpy  = unit_prices.get(price_key, 0.0)
            catalog[metric_key] = {
                "label":              meta.get("label", metric_key),
                "unit":               meta.get("unit", ""),
                "price_jpy":          price_jpy,
                "free_limit":         meta.get("free_limit", 0.0),
                "free_limit_display": meta.get("free_limit_display", "従量制"),
                "service_key":        service_key,
            }
    return catalog


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

    # メトリクスカタログを動的構築
    metric_catalog = build_metric_catalog(pricing_data)

    print(f"・対象プロジェクトID: {project_id}\n")

    # --------------------------------------------------------------------------
    # 表①: 動的メトリクスループで無料枠引き算明細を生成
    # --------------------------------------------------------------------------
    print("【表①: 既定のGCP公式無料枠 (Always Free) からの引き算明細 (過去30日間)】")

    h1 = (
        f"{'確定請求':<14} | "
        f"{'超過消費量':<14} | "
        f"{'無料枠残量 (引き算結果)':<34} | "
        f"{'無料枠上限 (月額)':<24} | "
        f"{'30日消費量':<16} | "
        f"リソース項目"
    )
    sep = "-" * 125
    print(h1)
    print(sep)

    result_items = []
    billed_total = 0.0

    # usage_delta の 30日メトリクスキーを走査
    for metric_key, value_30 in m30.items():
        if metric_key == "window_minutes":
            continue

        meta = metric_catalog.get(metric_key)
        if meta is None:
            continue  # カタログに定義がないメトリクスはスキップ

        label       = meta["label"]
        unit        = meta["unit"]
        price_jpy   = meta["price_jpy"]
        free_limit  = meta["free_limit"]
        free_display= meta["free_limit_display"]

        gross = value_30 * price_jpy

        if free_limit > 0:
            over   = max(0.0, value_30 - free_limit)
            rem    = free_limit - min(value_30, free_limit)
            pct_rem = (rem / free_limit) * 100.0
            billed = over * price_jpy
            billed_total += billed

            usage_str = f"{value_30:,.2f} {unit}" if value_30 != int(value_30) else f"{int(value_30):,} {unit}"
            over_str  = f"{over:,.2f} {unit}"     if over  != int(over)  else f"{int(over):,} {unit}"
            rem_str   = f"{rem:,.2f} {unit} ({pct_rem:.2f}%残)" if rem != int(rem) else f"{int(rem):,} {unit} ({pct_rem:.2f}%残)"
            bill_str  = f"￥0 (完全無料)" if billed == 0 else f"￥{billed:,.4f}"
        else:
            # 従量制（無料枠なし）
            over     = value_30
            billed   = gross
            billed_total += billed
            usage_str = f"{value_30:,.2f} {unit}" if value_30 != int(value_30) else f"{int(value_30):,} {unit}"
            over_str  = usage_str
            rem_str   = "従量制枠なし"
            bill_str  = f"￥0 (未使用)" if value_30 == 0 else f"￥{billed:,.4f}"

        print(
            f"{bill_str:<14} | "
            f"{over_str:<14} | "
            f"{rem_str:<34} | "
            f"{free_display:<24} | "
            f"{usage_str:<16} | "
            f"{label}"
        )

        result_items.append({
            "metric_key":   metric_key,
            "label":        label,
            "usage_30days": value_30,
            "unit":         unit,
            "free_limit":   free_limit,
            "over":         over,
            "billed_jpy":   round(billed, 6),
        })

    print(sep)
    if billed_total == 0:
        print("👉 結論: 全てのリソースにおいて無料枠が十分に残っており、確定請求額は【 ￥0 】です。\n")
    else:
        print(f"👉 確定請求合計: ￥{billed_total:,.4f}\n")

    # --------------------------------------------------------------------------
    # 表②: 時間軸マトリックス × 単価で計算定価を動的生成
    # --------------------------------------------------------------------------
    print("【表②: 時間軸マトリックス・インフラ計算定価 ＆ 確定請求額】")

    # 課金対象メトリクスのみ（price_jpy > 0 のもの）を収集
    billable = {
        k: v for k, v in metric_catalog.items()
        if v.get("price_jpy", 0) > 0
    }

    # 数式ラベル用に短縮表示
    formula_parts_tmpl = [
        (mkey, meta["price_jpy"], meta["unit"])
        for mkey, meta in billable.items()
    ]

    h2 = (
        f"{'確定請求額':<12} | "
        f"{'インフラ計算定価':<16} | "
        f"{'定価計算数式':<60} | "
        f"{'時間軸':>10}"
    )
    sep2 = "-" * 110
    print(h2)
    print(sep2)

    result_matrix = {}
    label_order = ["1_minute", "10_minutes", "1_hour", "1_day", "30_days"]

    for label in label_order:
        metrics = matrix.get(label)
        if metrics is None:
            continue

        gross = 0.0
        formula_parts = []
        for mkey, price, unit in formula_parts_tmpl:
            val = metrics.get(mkey, 0.0)
            cost = val * price
            gross += cost
            if val != 0.0:  # 値が0のメトリクスは数式から省略
                formula_parts.append(f"({val:.4g} {unit} × {price:.6f}円)")

        formula_str = " + ".join(formula_parts) if formula_parts else "(消費なし)"
        disp_label  = label.replace("_", " ")

        result_matrix[label] = {
            **{k: metrics.get(k, 0.0) for k in billable},
            "gross_cost_jpy":  round(gross, 6),
            "net_billed_jpy":  0.0,
        }

        print(
            f"{'￥0 (無料枠内)':<12} | "
            f"{gross:>14.6f} 円 | "
            f"{formula_str:<60} | "
            f"{disp_label:>10}"
        )

    print(sep2)

    # --------------------------------------------------------------------------
    # JSON保存
    # --------------------------------------------------------------------------
    result = {
        "project_id":                   project_id,
        "free_tier_subtractions_30days": result_items,
        "time_matrix":                   result_matrix,
        "total_billed_jpy":              round(billed_total, 6),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n💾 保持ファイル: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
