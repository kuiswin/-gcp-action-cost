#!/usr/bin/env python3
"""
Step 4: Monitoring API をサービスごとに呼び出し、過去30日間のメトリクスから
1分 / 10分 / 1時間 / 1日 / 30日 の時間軸マトリックスをローカルで超高速計算して .data/usage_delta.json に保存

- メトリクスは target_pricing.json (free_tier_metrics) に定義された metric_key を軸に取得
- 各サービスの resource.type を正しく使い分け
- 値が取得できない（サービス未使用）場合は 0.0 をセット
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

DATA_DIR         = os.path.abspath(".data")
SERVICES_FILE    = os.path.join(DATA_DIR, "active_services.json")
TARGET_PRICING_FILE = os.path.join(DATA_DIR, "target_pricing.json")
OUTPUT_FILE      = os.path.join(DATA_DIR, "usage_delta.json")

def get_access_token():
    res = subprocess.run(
        ["/root/google-cloud-sdk/bin/gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True
    )
    return res.stdout.strip()

def get_project_id():
    res = subprocess.run(
        ["/root/google-cloud-sdk/bin/gcloud", "config", "get-value", "project"],
        capture_output=True, text=True
    )
    pid = res.stdout.strip()
    return pid if pid and pid != "(unset)" else ""

def fetch_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())

def query_metric(project_id, token, metric_type, resource_type, days=30):
    """指定 metric_type / resource_type で過去 days 日間の合計値を返す。取得失敗は 0.0。"""
    now        = datetime.now(timezone.utc)
    start_time = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    end_time   = now.strftime("%Y-%m-%dT23:59:59Z")
    filter_expr = (
        f'metric.type="{metric_type}"'
        + (f' AND resource.type="{resource_type}"' if resource_type else "")
    )
    params = urllib.parse.urlencode({
        "filter":                filter_expr,
        "interval.startTime":    start_time,
        "interval.endTime":      end_time,
    })
    url = f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries?{params}"
    try:
        data  = fetch_json(url, token)
        total = 0.0
        for ts in data.get("timeSeries", []):
            for p in ts.get("points", []):
                v = p.get("value", {})
                total += int(v["int64Value"]) if "int64Value" in v else float(v.get("doubleValue", 0))
        return total
    except Exception:
        return 0.0


# -----------------------------------------------------------------------
# metric_key → (Monitoring metric_type, resource_type) の対応テーブル
# free_tier.json の metric_key と一致させる
# -----------------------------------------------------------------------
METRIC_QUERY_MAP = {
    # Cloud Run
    "request_count": (
        "run.googleapis.com/request_count",
        "cloud_run_revision",
    ),
    "cpu_seconds": (
        "run.googleapis.com/container/cpu/allocation_time",
        "cloud_run_revision",
    ),
    # Cloud Storage (GCS operations は storage.googleapis.com メトリクス)
    "gcs_read_ops": (
        "storage.googleapis.com/api/request_count",
        "gcs_bucket",
    ),
    "gcs_write_ops": (
        "storage.googleapis.com/api/request_count",
        "gcs_bucket",
    ),
    # BigQuery
    "query_tb_scanned": (
        "bigquery.googleapis.com/storage/stored_bytes",
        "bigquery_dataset",
    ),
}

# GCS は read/write を method ラベルで区別する必要があるため別途フィルタ
GCS_READ_METHODS  = {"ReadObject", "GetObject", "ListObjects", "ListBuckets",
                     "GetBucketMetadata", "GetBucketIamPolicy"}
GCS_WRITE_METHODS = {"WriteObject", "PutObject", "PatchObject", "DeleteObject",
                     "CreateBucket", "DeleteBucket", "SetBucketIamPolicy"}


def query_gcs_ops(project_id, token, days=30):
    """GCS read / write オペレーション数を個別に取得して返す。"""
    now        = datetime.now(timezone.utc)
    start_time = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    end_time   = now.strftime("%Y-%m-%dT23:59:59Z")
    params = urllib.parse.urlencode({
        "filter":             'metric.type="storage.googleapis.com/api/request_count" AND resource.type="gcs_bucket"',
        "interval.startTime": start_time,
        "interval.endTime":   end_time,
    })
    url = f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries?{params}"

    read_total = write_total = 0.0
    try:
        data = fetch_json(url, token)
        for ts in data.get("timeSeries", []):
            method = ts.get("metric", {}).get("labels", {}).get("method", "")
            subtotal = sum(
                int(p["value"].get("int64Value", 0)) + float(p["value"].get("doubleValue", 0))
                for p in ts.get("points", [])
            )
            if method in GCS_READ_METHODS:
                read_total  += subtotal
            elif method in GCS_WRITE_METHODS:
                write_total += subtotal
            else:
                # 不明 method はどちらでもなければ read 扱い（保守的）
                read_total  += subtotal
    except Exception:
        pass
    return read_total, write_total


def scale_matrix(value_30, windows):
    """30日合計値を各時間窓にスケールして辞書で返す。"""
    per_day  = value_30 / 30.0
    per_hr   = per_day  / 24.0
    per_10m  = per_hr   / 6.0
    per_1m   = per_hr   / 60.0
    result = {}
    for label, minutes in windows.items():
        scale = minutes / (30 * 24 * 60)
        result[label] = value_30 * scale
    return result


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("================================================================================")
    print("【Step 4】 時間軸マトリックス別リソース消費量プロファイリング (API照会 ➔ ローカル高速算出)")
    print("================================================================================")

    if not os.path.exists(TARGET_PRICING_FILE):
        print("❌ Error: 03_service_pricing.py を先に実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(TARGET_PRICING_FILE, "r", encoding="utf-8") as f:
        target_pricing = json.load(f)

    token      = get_access_token()
    project_id = get_project_id()
    print(f"・対象プロジェクトID: {project_id}")
    print("・Monitoring API から 過去30日間のメトリクスを取得中...")

    # target_pricing の free_tier_metrics から計測すべき metric_key を収集
    metric_keys = set()
    for svc_entry in target_pricing.get("target_unit_prices", {}).values():
        for mk in svc_entry.get("free_tier_metrics", {}).keys():
            metric_keys.add(mk)

    # 30日間合計値を取得
    raw_30 = {}

    # GCS は read/write をまとめて1回のAPIで取得
    if "gcs_read_ops" in metric_keys or "gcs_write_ops" in metric_keys:
        gcs_r, gcs_w = query_gcs_ops(project_id, token, days=30)
        raw_30["gcs_read_ops"]  = gcs_r
        raw_30["gcs_write_ops"] = gcs_w
        print(f"  ・GCS Read  : {gcs_r:,.0f} ops  |  Write: {gcs_w:,.0f} ops")

    # その他メトリクス
    for mkey in metric_keys:
        if mkey in raw_30:
            continue   # GCS は上で取得済み
        if mkey not in METRIC_QUERY_MAP:
            print(f"  ・[スキップ] {mkey}: Monitoring マッピングなし")
            raw_30[mkey] = 0.0
            continue
        metric_type, resource_type = METRIC_QUERY_MAP[mkey]
        val = query_metric(project_id, token, metric_type, resource_type, days=30)
        raw_30[mkey] = val
        used_str = f"{val:,.4f}" if val else "0 (未使用)"
        print(f"  ・{mkey}: {used_str}")

    # 時間窓の定義 (分数)
    WINDOWS = {
        "1_minute":   1,
        "10_minutes":  10,
        "1_hour":     60,
        "1_day":      1440,
        "30_days":    43200,
    }

    # 各時間窓にスケール
    time_matrix = {}
    for label, minutes in WINDOWS.items():
        scale  = minutes / 43200.0      # 43200 = 30日×24時間×60分
        entry  = {"window_minutes": minutes}
        for mkey, val_30 in raw_30.items():
            scaled = val_30 * scale
            # 桁数に応じた丸め
            if minutes <= 10:
                entry[mkey] = round(scaled, 4)
            elif minutes <= 60:
                entry[mkey] = round(scaled, 2)
            elif minutes <= 1440:
                entry[mkey] = round(scaled, 1)
            else:
                entry[mkey] = round(scaled, 2)
        time_matrix[label] = entry

    usage_delta = {
        "project_id":  project_id,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "time_matrix": time_matrix,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(usage_delta, f, indent=2, ensure_ascii=False)

    print("✓ 1回のAPI照会から、1分/10分/1時間/1日/30日 の時間軸マトリックスを超高速ローカル算出しました。")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
