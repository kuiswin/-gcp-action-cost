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
    {metric_key: {label, unit, editions, price_jpy, free_limit, free_limit_display, service_key}} を構築する。
    """
    catalog = {}
    for service_key, service_entry in pricing_data.items():
        unit_prices  = service_entry.get("unit_prices", service_entry)
        free_metrics = service_entry.get("free_tier_metrics", {})

        for metric_key, meta in free_metrics.items():
            editions = meta.get("editions")
            if editions:
                parsed_editions = []
                for ed in editions:
                    price_jpy = unit_prices.get(ed["price_key"], 0.0)
                    parsed_editions.append({"code": ed["code"], "price_jpy": price_jpy, "is_default": ed.get("is_default", False)})
            else:
                price_key = meta.get("price_key", "")
                price_jpy = unit_prices.get(price_key, 0.0)
                parsed_editions = [{"code": "ST", "price_jpy": price_jpy, "is_default": True}]

            catalog[metric_key] = {
                "label":              meta.get("label", metric_key),
                "unit":               meta.get("unit", ""),
                "editions":           parsed_editions,
                "price_jpy":          parsed_editions[0]["price_jpy"],
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
            if metric_key == "window_minutes": continue
            meta = metric_catalog.get(metric_key)
            if meta is None: continue

            label       = meta["label"]
            unit        = meta["unit"]
            free_limit  = meta["free_limit"]
            free_display= meta["free_limit_display"]

            display_value = value
            if is_diff_mode and metric_key in PROVISIONED_SERVICES and snap_elapsed_seconds > 0:
                live_nodes = value / 720.0
                inc_node_hours = live_nodes * (snap_elapsed_seconds / 3600.0)
                display_value = inc_node_hours

            for ed in meta["editions"]:
                price_jpy = ed["price_jpy"]
                code      = ed["code"]
                is_def    = ed["is_default"]

                disp_label = f"{label} ({code})" if len(meta["editions"]) > 1 else label
                gross = display_value * price_jpy

                if is_def:
                    total_gross += gross

                gross_str = f"￥{gross:09.4f}"
                snap_time_suffix = f" (経過 {snap_elapsed_seconds:.0f}秒)" if (is_diff_mode and snap_elapsed_seconds > 0) else ""

                if free_limit > 0:
                    over    = max(0.0, display_value - free_limit)
                    rem     = free_limit - min(display_value, free_limit)
                    pct_rem = (rem / free_limit) * 100.0
                    billed  = over * price_jpy
                    if is_def: total_billed += billed
                    row = {
                        "リソース":         disp_label,
                        val_header:         fmt_val(display_value, unit),
                        "インフラ定価 (控除前)": gross_str,
                        "無料枠上限":       free_display,
                        "無料枠残量":       fmt_val(rem, unit),
                        "残量率":           f"{pct_rem:.2f}%",
                        "超過消費量":       fmt_val(over, unit),
                        "確定請求 (控除後)": f"￥{billed:09.4f}",
                    }
                else:
                    billed = gross
                    if is_def: total_billed += billed
                    row = {
                        "リソース":         disp_label,
                        val_header:         f"{fmt_val(display_value, unit)}{snap_time_suffix}",
                        "インフラ定価 (控除前)": gross_str,
                        "無料枠上限":       free_display,
                        "無料枠残量":       "従量制枠なし",
                        "残量率":           "N/A",
                        "超過消費量":       fmt_val(display_value, unit),
                        "確定請求 (控除後)": f"￥{billed:09.4f}",
                    }
                rows.append(row)
        return rows, total_billed, total_gross

    month_counters = delta_data.get("month_counters", {})

    # 1. 差分モード時: 表① (増分Diff明細)
    if is_snap:
        diff_rows, diff_billed_total, diff_gross_total = calculate_subtraction_rows(m30, is_diff_mode=True)
        print("\n【表①: 操作前後の増分コスト (Diff) 明細】")
        print(json.dumps(diff_rows, ensure_ascii=False, indent=2))
        print(f"👉 直前操作の増分定価 (控除前): ￥{diff_gross_total:,.4f}  ➔  無料枠控除後の増分確定請求額: ￥{diff_billed_total:,.4f}")

    # 2. 当月実績 (1M / 当月1日~現在): 全サービス網羅のマージテーブル
    target_counters = raw_30_counters.copy()
    if month_counters:
        target_counters.update(month_counters)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    month_name = f"{now.month}月1日〜現在"
    table2_title = f"【表②: 当月分 ({month_name}) リソース消費 ＆ 確定請求額明細】"
    month_rows, month_billed_all, month_gross_all = calculate_subtraction_rows(target_counters, is_diff_mode=False)
    print(f"\n{table2_title}")
    print("※注記: 本ツールは標準単価（Standardエディション / デフォルトリージョン等）での概算プロファイラです。")
    print("     Spanner Enterprise Plusなど上位エディションを利用している場合、実際の請求額とは乖離が生じます。")
    print(json.dumps(month_rows, ensure_ascii=False, indent=2))
    print(f"\n👉 当月分 (1M) 本来のインフラ定価合計 (控除前): ￥{month_gross_all:,.4f}")
    if month_billed_all == 0:
        print("👉 当月分 (1M) 無料枠適用後の確定請求額合計 (控除後): 【 ￥0 (完全無料) 】")
    else:
        print(f"👉 当月分 (1M) 無料枠適用後の確定請求額合計 (控除後): ￥{month_billed_all:,.4f}")

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

        scale_map = {"1_minute": 1/43200, "10_minutes": 10/43200, "1_hour": 60/43200, "1_day": 1440/43200, "30_days": 1.0}
        net_billed = month_billed_all * scale_map.get(label, 0)
        net_str = f"￥{net_billed:09.4f}"

        time_matrix_out[disp_label] = {
            "明細":         detail if detail else [{"サービス": "(消費なし)"}],
            "小計":         f"￥{gross:09.4f}",
            "確定請求額":   net_str,
        }

        result_matrix[label] = {
            **{k: metrics.get(k, 0.0) for k in billable},
            "gross_cost_jpy": round(gross, 6),
            "net_billed_jpy": round(net_billed, 6),
        }

    print("\n【表②: 時間軸マトリックス・インフラ計算定価 ＆ 確定請求額】")
    print(json.dumps(time_matrix_out, ensure_ascii=False, indent=2))

    # --------------------------------------------------------------------------
    # JSON保存
    # --------------------------------------------------------------------------
    result = {
        "project_id":                    project_id,
        "free_tier_subtractions_30days": month_rows,
        "diff_subtractions":              diff_rows if is_snap else [],
        "time_matrix":                   result_matrix,
        "total_billed_jpy":              round(month_billed_all, 6),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # --------------------------------------------------------------------------
    # ユーザーフレンドリーな 01 Day / 07 Days / 30 Days サマリーテーブル出力
    # --------------------------------------------------------------------------
    print("\n" + "=" * 122)
    print("📊 期間別 (01 Day / 07 Days / 30 Days) リソース消費量・定価・無料枠・最終確定額サマリー")
    print("=" * 122)

    raw_01_counters = delta_data.get("raw_01_counters", {})
    raw_07_counters = delta_data.get("raw_07_counters", {})

    def ljust_jp(text, width):
        text = str(text)
        text_width = sum(2 if ord(c) > 0x255 else 1 for c in text)
        return text + " " * max(0, width - text_width)

    for mkey, meta in metric_catalog.items():
        label = meta["label"]
        unit = meta["unit"]
        free_limit_val = meta["free_limit"]
        free_limit_str = meta["free_limit_display"]

        val_01 = raw_01_counters.get(mkey, 0.0)
        val_07 = raw_07_counters.get(mkey, 0.0)
        val_30 = raw_30_counters.get(mkey, 0.0)

        print(f"\n★ {label}")
        print("-" * 122)
        print(f" {ljust_jp('ED', 2)} │ {ljust_jp('期間', 10)} │ {ljust_jp('定価 (控除前)', 16)} │ {ljust_jp('最終確定額 (控除後)', 16)} │ {ljust_jp('無料枠上限定義', 26)} │ {ljust_jp('実測消費量', 26)}")
        print("-" * 122)

        for ed in meta["editions"]:
            code = ed["code"]
            price_jpy = ed["price_jpy"]

            g01 = val_01 * price_jpy
            g07 = val_07 * price_jpy
            g30 = val_30 * price_jpy

            if free_limit_val > 0:
                b30 = max(0.0, val_30 - free_limit_val) * price_jpy
                b01 = b30 * (val_01 / val_30) if val_30 > 0 else 0.0
                b07 = b30 * (val_07 / val_30) if val_30 > 0 else 0.0
            else:
                b01 = g01; b07 = g07; b30 = g30

            used_01_disp = fmt_val(val_01, unit)
            used_07_disp = fmt_val(val_07, unit)
            used_30_disp = fmt_val(val_30, unit)

            print(f" {code:<2} │ {ljust_jp('01 Day', 10)} │ ￥{g01:09.4f}       │ ￥{b01:09.4f}       │ {ljust_jp(free_limit_str, 26)} │ {ljust_jp(used_01_disp, 26)}")
            print(f" {code:<2} │ {ljust_jp('07 Days', 10)} │ ￥{g07:09.4f}       │ ￥{b07:09.4f}       │ {ljust_jp(free_limit_str, 26)} │ {ljust_jp(used_07_disp, 26)}")
            print(f" {code:<2} │ {ljust_jp('30 Days', 10)} │ ￥{g30:09.4f}       │ ￥{b30:09.4f}       │ {ljust_jp(free_limit_str, 26)} │ {ljust_jp(used_30_disp, 26)}")

    # --------------------------------------------------------------------------
    # 🚨 放置ゾンビリソース警告アラートの表示
    # --------------------------------------------------------------------------
    zombies = delta_data.get("zombie_resources", [])
    if zombies:
        print("\n" + "🚨" * 60)
        print("【重大警告】 放置された未解放リソース（ゾンビリソース）を検知しました！")
        print("🚨" * 60)
        print("以下のリソースがプロジェクト内に残存しています。意図せず放置している場合、")
        print("バックグラウンドでの無駄なPush通信やエラーリトライを引き起こす原因になります。")
        print("直ちに用途を確認し、不要であれば gcloud CLI 等で削除してください！\n")
        for z in zombies:
            print(f"  ❌ {z}")
        print("\n" + "🚨" * 60)

    print("\n" + "=" * 122)
    print(f"💾 保持ファイル: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
