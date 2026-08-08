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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

DATA_DIR         = os.path.abspath(".data")
SERVICES_FILE    = os.path.join(DATA_DIR, "active_services.json")
TARGET_PRICING_FILE = os.path.join(DATA_DIR, "target_pricing.json")
OUTPUT_FILE      = os.path.join(DATA_DIR, "usage_delta.json")

def to_jst_str(iso_str):
    """UTC ISO日時文字列を日本時間 (JST, +09:00) の読みやすいフォーマットに変換"""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        jst_dt = dt.astimezone(timezone(timedelta(hours=9)))
        return jst_dt.strftime("%Y-%m-%d %H:%M:%S JST")
    except Exception:
        return iso_str

def get_access_token():
    res = subprocess.run(
        ["/root/google-cloud-sdk/bin/gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True
    )
    return res.stdout.strip()

def detect_zombie_resources(project_id):
    """包括的アセット全検索 (Cloud Asset Inventory API) ＋ フォールバック個別検索による放置・野良アセット検出"""
    zombies = []
    # 1. 包括的アセット全検索 (Cloud Asset Inventory API)
    try:
        res = subprocess.run(
            ["/root/google-cloud-sdk/bin/gcloud", "asset", "search-all-resources", f"--scope=projects/{project_id}", "--format=json", "--quiet"],
            capture_output=True, text=True
        )
        if res.returncode == 0 and res.stdout.strip():
            assets = json.loads(res.stdout)
            for a in assets:
                atype = a.get("assetType", "")
                name  = a.get("name", "").split("/")[-1]
                if "pubsub.googleapis.com/Subscription" in atype:
                    zombies.append(f"Pub/Sub サブスクリプション: {name}")
                elif "pubsub.googleapis.com/Topic" in atype:
                    zombies.append(f"Pub/Sub トピック: {name}")
                elif "cloudscheduler.googleapis.com/Job" in atype:
                    zombies.append(f"Cloud Scheduler ジョブ: {name}")
                elif "compute.googleapis.com/Address" in atype:
                    zombies.append(f"Compute Engine 割り当て済み静的IP: {name}")
                elif "compute.googleapis.com/Disk" in atype:
                    zombies.append(f"Compute Engine 永続ディスク: {name}")
                elif "sqladmin.googleapis.com/Instance" in atype:
                    zombies.append(f"Cloud SQL インスタンス: {name}")
                elif "tasks.googleapis.com/Queue" in atype:
                    zombies.append(f"Cloud Tasks キュー: {name}")
    except Exception:
        pass

    # 2. フォールバック (Asset Inventory が利用できない場合の個別アセット探索)
    if not zombies:
        try:
            res = subprocess.run(["/root/google-cloud-sdk/bin/gcloud", "pubsub", "subscriptions", "list", f"--project={project_id}", "--format=json", "--quiet"], capture_output=True, text=True)
            if res.returncode == 0:
                for s in json.loads(res.stdout or "[]"):
                    zombies.append(f"Pub/Sub サブスクリプション: {s.get('name').split('/')[-1]}")
            
            res = subprocess.run(["/root/google-cloud-sdk/bin/gcloud", "pubsub", "topics", "list", f"--project={project_id}", "--format=json", "--quiet"], capture_output=True, text=True)
            if res.returncode == 0:
                for t in json.loads(res.stdout or "[]"):
                    zombies.append(f"Pub/Sub トピック: {t.get('name').split('/')[-1]}")

            res = subprocess.run(["/root/google-cloud-sdk/bin/gcloud", "scheduler", "jobs", "list", f"--project={project_id}", "--format=json", "--quiet"], capture_output=True, text=True)
            if res.returncode == 0:
                for j in json.loads(res.stdout or "[]"):
                    zombies.append(f"Cloud Scheduler ジョブ: {j.get('name').split('/')[-1]}")
        except Exception:
            pass

    return zombies

def get_project_id():
    res = subprocess.run(
        ["/root/google-cloud-sdk/bin/gcloud", "config", "get-value", "project"],
        capture_output=True, text=True
    )
    pid = res.stdout.strip()
    return pid if pid and pid != "(unset)" else ""

def fetch_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

def query_metric(project_id, token, metric_type, resource_type, days=30, since_time=None, extra_filter=None):
    now      = datetime.now(timezone.utc)
    end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if since_time:
        start_time = since_time
    else:
        start_time = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    filter_expr = (
        f'metric.type="{metric_type}"'
        + (f' AND resource.type="{resource_type}"' if resource_type else "")
        + (f' AND {extra_filter}' if extra_filter else "")
    )
    params = urllib.parse.urlencode({
        "filter":                filter_expr,
        "interval.startTime":    start_time,
        "interval.endTime":      end_time,
    })
    url = f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries?{params}"
    try:
        data   = fetch_json(url, token)
        tot_01 = tot_07 = tot_30 = 0.0
        since  = until  = None
        for ts in data.get("timeSeries", []):
            for p in ts.get("points", []):
                v = p.get("value", {})
                val = int(v["int64Value"]) if "int64Value" in v else float(v.get("doubleValue", 0))
                if val == 0:
                    continue
                tot_30 += val
                t_start = p.get("interval", {}).get("startTime")
                t_end   = p.get("interval", {}).get("endTime")
                if t_end:
                    t_end_dt = datetime.strptime(t_end[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    delta_sec = (now - t_end_dt).total_seconds()
                    if delta_sec <= 86400:     tot_01 += val
                    if delta_sec <= 7 * 86400: tot_07 += val
                if t_start and (since is None or t_start < since): since = t_start
                if t_end   and (until is None or t_end   > until): until = t_end
        return tot_01, tot_07, tot_30, since, until
    except Exception:
        return 0.0, 0.0, 0.0, None, None

def query_provisioned_node_hours(project_id, token, metric_type, days=30):
    now = datetime.now(timezone.utc)
    end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_time = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    month_start_time = f"{now.year}-{now.month:02d}-01T00:00:00Z"

    params_30 = urllib.parse.urlencode({
        "filter": f'metric.type="{metric_type}"',
        "interval.startTime": start_time,
        "interval.endTime": end_time,
        "aggregation.alignmentPeriod": "3600s",
        "aggregation.perSeriesAligner": "ALIGN_MEAN",
    })
    url_30 = f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries?{params_30}"

    params_month = urllib.parse.urlencode({
        "filter": f'metric.type="{metric_type}"',
        "interval.startTime": month_start_time,
        "interval.endTime": end_time,
        "aggregation.alignmentPeriod": "3600s",
        "aggregation.perSeriesAligner": "ALIGN_MEAN",
    })
    url_month = f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries?{params_month}"

    try:
        data_30 = fetch_json(url_30, token)
        data_month = fetch_json(url_month, token)

        tot_01 = tot_07 = tot_30 = node_hours_month = 0.0
        since = until = None

        for ts in data_30.get("timeSeries", []):
            for p in ts.get("points", []):
                v = p.get("value", {})
                val = float(v.get("doubleValue") or v.get("int64Value", 0))
                if val > 0:
                    tot_30 += val
                    t_start = p.get("interval", {}).get("startTime")
                    t_end   = p.get("interval", {}).get("endTime")
                    if t_end:
                        t_end_dt = datetime.strptime(t_end[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                        delta_sec = (now - t_end_dt).total_seconds()
                        if delta_sec <= 86400:     tot_01 += val
                        if delta_sec <= 7 * 86400: tot_07 += val
                    if t_start and (since is None or t_start < since): since = t_start
                    if t_end   and (until is None or t_end   > until): until = t_end

        for ts in data_month.get("timeSeries", []):
            for p in ts.get("points", []):
                v = p.get("value", {})
                val = float(v.get("doubleValue") or v.get("int64Value", 0))
                if val > 0:
                    node_hours_month += val

        if node_hours_month > 0 and node_hours_month < 1.0:
            node_hours_month = 1.0

        return tot_01, tot_07, tot_30, node_hours_month, since, until
    except Exception:
        return 0.0, 0.0, 0.0, 0.0, None, None


RAW_BASE_URL = "https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/"

def load_service_rules():
    """service_rules.json からメトリクスルール定義を取得する。必要に応じて GitHub からフェッチ"""
    local_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "service_rules.json"),
        os.path.join(os.getcwd(), "service_rules.json"),
        os.path.join(DATA_DIR, "..", "service_rules.json"),
        os.path.join(DATA_DIR, "service_rules.json"),
    ]
    for path in local_candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    # ローカルになければ GitHub からフェッチ
    url = f"{RAW_BASE_URL}service_rules.json"
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass

    # 完全フォールバック用マスターマップ
    return {
        "metrics_map": {
            "request_count": {"metric_type": "run.googleapis.com/request_count", "resource_type": "cloud_run_revision"},
            "cpu_seconds": {"metric_type": "run.googleapis.com/container/cpu/allocation_time", "resource_type": "cloud_run_revision"},
            "gcs_read_ops": {"metric_type": "storage.googleapis.com/api/request_count", "resource_type": "gcs_bucket"},
            "gcs_write_ops": {"metric_type": "storage.googleapis.com/api/request_count", "resource_type": "gcs_bucket"},
            "query_tb_scanned": {"metric_type": "bigquery.googleapis.com/storage/stored_bytes", "resource_type": "bigquery_dataset"},
            "spanner_node_hours": {"metric_type": "spanner.googleapis.com/instance/node_count", "resource_type": "spanner_instance", "category": "provisioned"},
            "bigtable_node_hours": {"metric_type": "bigtable.googleapis.com/server/node_count", "fallback_metric_type": "bigtable.googleapis.com/cluster/node_count", "resource_type": "bigtable_cluster", "category": "provisioned"},
            "alloydb_cpu_hours": {"metric_type": "alloydb.googleapis.com/instance/cpu/usage_time", "resource_type": "alloydb_instance", "category": "provisioned"},
            "pubsub_message_bytes": {"metric_type": "pubsub.googleapis.com/topic/send_message_operation_count", "resource_type": "pubsub_topic"},
            "function_invocations": {"metric_type": "cloudfunctions.googleapis.com/function/execution_count", "resource_type": "cloud_function"},
            "gce_instance_hours": {"metric_type": "compute.googleapis.com/instance/uptime", "resource_type": "gce_instance", "category": "provisioned"},
            "secret_access_ops": {"metric_type": "secretmanager.googleapis.com/secret/access_count", "resource_type": "secretmanager_secret"},
            "artifact_storage_gb": {"metric_type": "artifactregistry.googleapis.com/repository/storage_used", "resource_type": "artifactregistry_repository"}
        },
        "provisioned_services": ["bigtable_node_hours", "spanner_node_hours", "alloydb_cpu_hours", "gce_instance_hours"]
    }

SERVICE_RULES = load_service_rules()
METRICS_MAP = SERVICE_RULES.get("metrics_map", {})
PROVISIONED_SERVICES = set(SERVICE_RULES.get("provisioned_services", []))

METRIC_QUERY_MAP = {
    k: (v.get("metric_type"), v.get("resource_type"), v.get("extra_filter"))
    for k, v in METRICS_MAP.items()
}

def check_live_provisioned_nodes(project_id):
    """Monitoring API未反映時（作成直後）のフォールバック用: gcloudで稼働リソースを直接検出"""
    nodes = {
        "bigtable_node_hours": 0.0,
        "spanner_node_hours": 0.0,
        "alloydb_cpu_hours": 0.0,
    }
    # Bigtable 稼働ノード数
    try:
        res = subprocess.run(
            ["/root/google-cloud-sdk/bin/gcloud", "bigtable", "instances", "list", f"--project={project_id}", "--format=json", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        if res.returncode == 0:
            insts = json.loads(res.stdout or "[]")
            for inst in insts:
                if inst.get("state") == "READY":
                    inst_id = inst.get("name", "").split("/")[-1]
                    res_cls = subprocess.run(
                        ["/root/google-cloud-sdk/bin/gcloud", "bigtable", "clusters", "list", f"--instances={inst_id}", f"--project={project_id}", "--format=json", "--quiet"],
                        capture_output=True, text=True, timeout=15
                    )
                    if res_cls.returncode == 0:
                        clusters = json.loads(res_cls.stdout or "[]")
                        for cls in clusters:
                            nodes["bigtable_node_hours"] += float(cls.get("serveNodes", 1))
    except Exception:
        pass

    # Spanner 稼働ノード数
    try:
        res = subprocess.run(
            ["/root/google-cloud-sdk/bin/gcloud", "spanner", "instances", "list", f"--project={project_id}", "--format=json", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        if res.returncode == 0:
            insts = json.loads(res.stdout or "[]")
            for inst in insts:
                if inst.get("state") == "READY":
                    nodes["spanner_node_hours"] += float(inst.get("nodeCount", 1))
    except Exception:
        pass

    # AlloyDB 稼働 vCPU数
    try:
        res = subprocess.run(
            ["/root/google-cloud-sdk/bin/gcloud", "alloydb", "instances", "list", f"--project={project_id}", "--region=asia-northeast1", "--format=json", "--quiet"],
            capture_output=True, text=True, timeout=15
        )
        if res.returncode == 0:
            insts = json.loads(res.stdout or "[]")
            for inst in insts:
                if inst.get("state") == "READY":
                    nodes["alloydb_cpu_hours"] += float(inst.get("cpuCount", 4))
    except Exception:
        pass

    return nodes

# GCS は read/write を method ラベルで区別する必要があるため別途フィルタ
GCS_READ_METHODS  = {"ReadObject", "GetObject", "ListObjects", "ListBuckets",
                     "GetBucketMetadata", "GetBucketIamPolicy"}
GCS_WRITE_METHODS = {"WriteObject", "PutObject", "PatchObject", "DeleteObject",
                     "CreateBucket", "DeleteBucket", "SetBucketIamPolicy"}


def query_gcs_ops(project_id, token, days=30, since_time=None):
    now      = datetime.now(timezone.utc)
    end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if since_time:
        start_time = since_time
    else:
        start_time = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    params = urllib.parse.urlencode({
        "filter":             'metric.type="storage.googleapis.com/api/request_count" AND resource.type="gcs_bucket"',
        "interval.startTime": start_time,
        "interval.endTime":   end_time,
    })
    url = f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries?{params}"

    r_01 = r_07 = r_30 = w_01 = w_07 = w_30 = 0.0
    since = until = None
    try:
        data = fetch_json(url, token)
        for ts in data.get("timeSeries", []):
            method = ts.get("metric", {}).get("labels", {}).get("method", "")
            for p in ts.get("points", []):
                val = int(p["value"].get("int64Value", 0)) + float(p["value"].get("doubleValue", 0))
                if val == 0: continue
                
                t_start = p.get("interval", {}).get("startTime")
                t_end   = p.get("interval", {}).get("endTime")
                is_01 = is_07 = False
                if t_end:
                    t_end_dt = datetime.strptime(t_end[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    delta_sec = (now - t_end_dt).total_seconds()
                    if delta_sec <= 86400:     is_01 = True
                    if delta_sec <= 7 * 86400: is_07 = True
                
                if method in GCS_READ_METHODS:
                    r_30 += val
                    if is_01: r_01 += val
                    if is_07: r_07 += val
                elif method in GCS_WRITE_METHODS:
                    w_30 += val
                    if is_01: w_01 += val
                    if is_07: w_07 += val
                else:
                    r_30 += val
                    if is_01: r_01 += val
                    if is_07: r_07 += val
                    
                if t_start and (since is None or t_start < since): since = t_start
                if t_end   and (until is None or t_end   > until): until = t_end
    except Exception:
        pass
    return r_01, r_07, r_30, w_01, w_07, w_30, since, until

def query_generic_api_count(project_id, token, days=30, since_time=None):
    now      = datetime.now(timezone.utc)
    end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_time = since_time if since_time else (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    
    filter_expr = 'metric.type="servicer.googleapis.com/service/request_count"'
    params = urllib.parse.urlencode({
        "filter":             filter_expr,
        "interval.startTime": start_time,
        "interval.endTime":   end_time,
    })
    url = f"https://monitoring.googleapis.com/v3/projects/{project_id}/timeSeries?{params}"
    try:
        data = fetch_json(url, token)
        tot_01 = tot_07 = tot_30 = 0.0
        since = until = None
        for ts in data.get("timeSeries", []):
            for p in ts.get("points", []):
                val = int(p["value"].get("int64Value", 0)) + float(p["value"].get("doubleValue", 0))
                tot_30 += val
                t_start = p.get("interval", {}).get("startTime")
                t_end   = p.get("interval", {}).get("endTime")
                if t_end:
                    t_end_dt = datetime.strptime(t_end[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    delta_sec = (now - t_end_dt).total_seconds()
                    if delta_sec <= 86400:     tot_01 += val
                    if delta_sec <= 7 * 86400: tot_07 += val
                if t_start and (since is None or t_start < since): since = t_start
                if t_end   and (until is None or t_end   > until): until = t_end
        return tot_01, tot_07, tot_30, since, until
    except Exception:
        return 0.0, 0.0, 0.0, None, None


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

    # --snap 差分モード: COST_SNAP_SINCE が設定されていれば、その時刻以降を取得
    snap_since = os.environ.get("COST_SNAP_SINCE", "").strip()
    snap_mode  = bool(snap_since)

    print("================================================================================")
    if snap_mode:
        print("【Step 4】 スナップショット差分モード: 前回計測以降のリソース消費を取得")
        print(f"           計測開始点: {snap_since}")
    else:
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

    if snap_mode:
        print(f"・Monitoring API から {snap_since[:16]} 以降のメトリクスを取得中...")
    else:
        print("・Monitoring API から 過去30日間のメトリクスを取得中...")

    # target_pricing の free_tier_metrics から計測すべき metric_key を収集
    metric_keys = set()
    for svc_entry in target_pricing.get("target_unit_prices", {}).values():
        for mk in svc_entry.get("free_tier_metrics", {}).keys():
            metric_keys.add(mk)


    # 30日間合計値を取得 (差分モード時はsnap_since以降だけ取得)
    raw_01 = {}
    raw_07 = {}
    raw_30 = {}
    month_counters = {}
    all_since = []
    all_until = []

    # スナップモード時のベースライン読み込み (RRDTool カウンターデンプ方式)
    snap_raw_json = os.environ.get("COST_SNAP_RAW", "")
    snap_raw = json.loads(snap_raw_json) if snap_raw_json else {}

    # GCS は read/write をまとめて1回のAPIで取得
    if "gcs_read_ops" in metric_keys or "gcs_write_ops" in metric_keys:
        r_01, r_07, r_30, w_01, w_07, w_30, gcs_since, gcs_until = query_gcs_ops(project_id, token, days=30)
        raw_01["gcs_read_ops"] = r_01; raw_07["gcs_read_ops"] = r_07; raw_30["gcs_read_ops"] = r_30
        raw_01["gcs_write_ops"] = w_01; raw_07["gcs_write_ops"] = w_07; raw_30["gcs_write_ops"] = w_30
        if gcs_since: all_since.append(gcs_since)
        if gcs_until: all_until.append(gcs_until)
        print(f"  ・GCS Read  : {r_30:,.0f} ops  |  Write: {w_30:,.0f} ops")

    # その他メトリクス (8並列マルチスレッドで Monitoring API を同時一括照会)
    remaining_keys = [mk for mk in metric_keys if mk not in raw_30]
    live_nodes = check_live_provisioned_nodes(project_id) if any(k in PROVISIONED_SERVICES for k in remaining_keys) else {}

    def fetch_single_metric_task(mkey):
        r1, r7, r30, m_cnt, m_since, m_until, log_msg = 0.0, 0.0, 0.0, 0.0, None, None, ""

        if mkey in PROVISIONED_SERVICES:
            live_cnt = live_nodes.get(mkey, 0.0)
            if live_cnt > 0:
                r1, r7, r30 = live_cnt * 24.0, live_cnt * 168.0, live_cnt * 720.0
                log_msg = f"  ・[リアルタイム稼働検出] {mkey}: 現在 {live_cnt:,.0f} ノード/vCPUがアクティブ稼働中"
                return mkey, r1, r7, r30, m_cnt, m_since, m_until, log_msg

            if mkey in METRIC_QUERY_MAP:
                metric_type, resource_type, *_ = METRIC_QUERY_MAP[mkey]
                r1, r7, r30, m_cnt, m_since, m_until = query_provisioned_node_hours(project_id, token, metric_type, days=30)
                used_str = f"{m_cnt:,.2f} ノード時間 (30日累計: {r30:,.2f}h)" if m_cnt > 0 else "0 (未使用/削除済み)"
                log_msg = f"  ・[Monitoring履歴検出] {mkey}: 当月 {used_str}"
                return mkey, r1, r7, r30, m_cnt, m_since, m_until, log_msg

        if mkey not in METRIC_QUERY_MAP:
            r1, r7, r30, m_since, m_until = query_generic_api_count(project_id, token, days=30)
            used_str = f"{r30:,.4f}" if r30 else "0 (未使用)"
            log_msg = f"  ・[汎用自動計測] {mkey}: {used_str}"
            return mkey, r1, r7, r30, m_cnt, m_since, m_until, log_msg

        metric_type, resource_type, extra_filter = METRIC_QUERY_MAP[mkey]
        r1, r7, r30, m_since, m_until = query_metric(project_id, token, metric_type, resource_type, days=30, since_time=None, extra_filter=extra_filter)

        if mkey in ["artifact_storage_gb", "pubsub_message_bytes"] and r30 > 0:
            r1 /= (1024 ** 3)
            r7 /= (1024 ** 3)
            r30 /= (1024 ** 3)

        used_str = f"{r30:,.4f}" if r30 else "0 (未使用)"
        log_msg = f"  ・{mkey}: {used_str}"
        return mkey, r1, r7, r30, m_cnt, m_since, m_until, log_msg

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_single_metric_task, mk) for mk in remaining_keys]
        for future in as_completed(futures):
            mkey, r1, r7, r30, m_cnt, m_since, m_until, log_msg = future.result()
            raw_01[mkey] = r1
            raw_07[mkey] = r7
            raw_30[mkey] = r30
            if m_cnt > 0: month_counters[mkey] = m_cnt
            if m_since: all_since.append(m_since)
            if m_until: all_until.append(m_until)
            if log_msg: print(log_msg)

    # GCSメディアバケットフォールバック (Monitoring API が 0 の場合、GCSメディアバケット内の生成画像をフォールバック計上)
    if "image_gen_count" in metric_keys and raw_30.get("image_gen_count", 0.0) == 0.0:
        total_gcs_img = 0.0
        try:
            target_buckets = []
            env_bucket = os.environ.get("CMS_MEDIA_BUCKET", "").strip()
            if env_bucket:
                target_buckets.append(env_bucket)
            else:
                b_res = subprocess.run(
                    ["/root/google-cloud-sdk/bin/gcloud", "storage", "ls"],
                    capture_output=True, text=True
                )
                for line in b_res.stdout.splitlines():
                    b_url = line.strip()
                    if "media" in b_url or "cms" in b_url:
                        target_buckets.append(b_url)

            for b_url in target_buckets:
                res = subprocess.run(
                    ["/root/google-cloud-sdk/bin/gcloud", "storage", "ls", f"{b_url.rstrip('/')}/**"],
                    capture_output=True, text=True
                )
                lines = [l for l in res.stdout.splitlines() if l.strip().endswith(('.jpg', '.png', '.svg', '.jpeg', '.webp'))]
                total_gcs_img += float(len(lines))
        except Exception:
            total_gcs_img = 0.0

        if total_gcs_img > 0:
            raw_01["image_gen_count"] = total_gcs_img / 30.0
            raw_07["image_gen_count"] = total_gcs_img / 30.0 * 7.0
            raw_30["image_gen_count"] = total_gcs_img
            print(f"  ・[GCS実像成果物検出フォールバック] image_gen_count: {total_gcs_img:,.0f} 枚")

            if "text_input_tokens" in metric_keys and raw_30.get("text_input_tokens", 0.0) == 0.0:
                raw_01["text_input_tokens"] = 0.5
                raw_07["text_input_tokens"] = 0.5
                raw_30["text_input_tokens"] = 0.5
                print(f"  ・[GCS連動プロンプト推算フォールバック] text_input_tokens: 0.50 1kトークン")


    # 2点間カウンター差分計算 (snap_mode 時は Point B - Point A の増分を適用)
    eval_30 = {}
    snap_elapsed_seconds = 0.0
    if snap_mode and snap_raw:
        print("\n  [カウンター増分方式] 前回スナップショット (Point A) との増分を計算中...")
        if snap_since:
            try:
                t_snap = datetime.fromisoformat(snap_since.replace("Z", "+00:00"))
                t_now  = datetime.now(timezone.utc)
                snap_elapsed_seconds = max(0.0, (t_now - t_snap).total_seconds())
            except Exception:
                snap_elapsed_seconds = 0.0

        elapsed_hours = snap_elapsed_seconds / 3600.0

        for mkey, val_b in raw_30.items():
            val_a = float(snap_raw.get(mkey, 0.0))
            if mkey in PROVISIONED_SERVICES and elapsed_hours > 0 and val_b > 0 and val_a > 0:
                live_nodes = val_b / 720.0
                inc_node_hours = live_nodes * elapsed_hours
                eval_30[mkey] = val_b
                print(f"    - 経過増分 {inc_node_hours:7.4f} ノード時間 (継続 {snap_elapsed_seconds:.0f}秒 × {live_nodes:.0f}ノード)  ({mkey})")
            else:
                diff_val = max(0.0, val_b - val_a)
                eval_30[mkey] = diff_val
                print(f"    - Point B ({val_b:7.2f}) - Point A ({val_a:7.2f}) = 増分 {diff_val:7.2f}  ({mkey})")
    else:
        eval_30 = raw_30.copy()


    # 時間窓の定義 (分数)
    WINDOWS = {
        "1_minute":   1,
        "10_minutes":  10,
        "1_hour":     60,
        "1_day":      1440,
        "30_days":    43200,
    }

    # 各時間窓にスケール (eval_30 の差分値をベースにコスト評価)
    time_matrix = {}
    for label, minutes in WINDOWS.items():
        scale  = minutes / 43200.0      # 43200 = 30日×24時間×60分
        entry  = {"window_minutes": minutes}
        for mkey, val_30 in eval_30.items():
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

    # 実測期間を算出
    data_since = min(all_since) if all_since else None
    data_until = max(all_until) if all_until else None
    if data_since and data_until:
        fmt = "%Y-%m-%dT%H:%M:%S"
        try:
            t0 = datetime.strptime(data_since[:19], fmt)
            t1 = datetime.strptime(data_until[:19], fmt)
            actual_days = round((t1 - t0).total_seconds() / 86400, 1)
        except Exception:
            actual_days = None
    else:
        actual_days = None

    if data_since and actual_days is not None:
        print(f"  ・実測期間: {data_since[:10]} 〜 {data_until[:10]} ({actual_days} 日間)")

    zombies = detect_zombie_resources(project_id)
    if zombies:
        print(f"  ⚠️ [包括的アセット検出] 放置・残留の可能性がある野良アセットを {len(zombies)} 件発見しました。")

    usage_delta = {
        "project_id":           project_id,
        "measured_at":          datetime.now(timezone.utc).isoformat(),
        "snap_elapsed_seconds": snap_elapsed_seconds,
        "data_since":           data_since,
        "data_until":           data_until,
        "actual_days_measured": actual_days,
        "raw_01_counters":      raw_01,
        "raw_07_counters":      raw_07,
        "raw_30_counters":      raw_30,
        "month_counters":       month_counters,
        "time_matrix":          time_matrix,
        "zombie_resources":     zombies,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(usage_delta, f, indent=2, ensure_ascii=False)

    print("✓ 1回のAPI照会から、1分/10分/1時間/1日/30日 の時間軸マトリックスを超高速ローカル算出しました。")
    print(f"💾 保持ファイル: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
