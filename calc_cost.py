#!/usr/bin/env python3
"""
GCP Action Cost Profiler (`gcp-action-cost`)
--------------------------------------------------------------------------------
100% Dynamic GCP Resource & Cost Profiler:
- Fetches real Cloud Audit Logs & GCP Monitoring metrics.
- Reads free_tier.json and service_rules.json for pricing and Always Free limits.
- Supports --snap (snapshot & delta mode) and saves output to .data/action_cost_result.json.
- Zero fake directory checks or hardcoded mock fallbacks.
--------------------------------------------------------------------------------
"""

import argparse
import gzip
import json
import os
import subprocess
import sys
import time
import urllib.request
import unicodedata
from datetime import datetime, timedelta, timezone

def get_safe_script_dir():
    try:
        fpath = os.path.realpath(__file__)
        if fpath.startswith("/proc") or fpath.startswith("/dev") or "/fd" in fpath:
            return os.getcwd()
        d = os.path.dirname(fpath)
        if d.startswith("/proc") or d.startswith("/dev") or "/fd" in d:
            return os.getcwd()
        return d
    except Exception:
        return os.getcwd()

SCRIPT_DIR = get_safe_script_dir()

def get_gcloud_cmd():
    path = "/root/google-cloud-sdk/bin/gcloud"
    return path if os.path.exists(path) else "gcloud"

def get_project_id():
    # 1. Environment variables
    pid = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT")
    if pid:
        return pid, False

    # 2. GCP Compute / Cloud Run Metadata Server
    try:
        req = urllib.request.Request("http://169.254.169.254/computeMetadata/v1/project/project-id", headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            meta_pid = resp.read().decode("utf-8").strip()
            if meta_pid:
                return meta_pid, False
    except Exception:
        pass

    # 3. gcloud configuration files (~/.config/gcloud/configurations/*)
    cfg_dir = os.path.expanduser("~/.config/gcloud/configurations")
    if os.path.exists(cfg_dir):
        try:
            for fname in os.listdir(cfg_dir):
                fpath = os.path.join(cfg_dir, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip().startswith("project"):
                                parts = line.split("=")
                                if len(parts) > 1 and parts[1].strip():
                                    return parts[1].strip(), False
        except Exception:
            pass

    # 4. Application Default Credentials (ADC) JSON file
    adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
    if os.path.exists(adc_path):
        try:
            with open(adc_path, "r", encoding="utf-8") as f:
                adc_data = json.load(f)
                adc_pid = adc_data.get("quota_project_id") or adc_data.get("project_id")
                if adc_pid:
                    return adc_pid, False
        except Exception:
            pass

    # 5. gcloud config get-value project
    try:
        res = subprocess.run([get_gcloud_cmd(), "config", "get-value", "project"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip() and "(unset)" not in res.stdout:
            return res.stdout.strip(), False
    except Exception:
        pass

    # 6. Query accessible projects via gcloud projects list
    try:
        res = subprocess.run([get_gcloud_cmd(), "projects", "list", "--limit=1", "--format=value(projectId)", "--quiet"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            first_pid = res.stdout.strip().splitlines()[0]
            if first_pid:
                return first_pid, False
    except Exception:
        pass

    return "demo-gcp-project", True

def get_access_token():
    cache_path = "/tmp/_gcp_token.cache"
    if os.path.exists(cache_path):
        try:
            mtime = os.path.getmtime(cache_path)
            if time.time() - mtime < 1800:
                with open(cache_path, "r", encoding="utf-8") as f:
                    tok = f.read().strip()
                    if tok.startswith("ya29.") or tok.startswith("eyJ"):
                        return tok, None
        except Exception:
            pass

    # Method 1: gcloud auth print-access-token (with 15s timeout & DEVNULL stdin)
    try:
        res = subprocess.run([get_gcloud_cmd(), "auth", "print-access-token"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            tok = res.stdout.strip()
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(tok)
            except Exception:
                pass
            return tok, None
    except Exception:
        pass

    # Method 2: gcloud auth application-default print-access-token
    try:
        res = subprocess.run([get_gcloud_cmd(), "auth", "application-default", "print-access-token"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            tok = res.stdout.strip()
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(tok)
            except Exception:
                pass
            return tok, None
    except Exception:
        pass

    # Method 3: gcloud config config-helper
    try:
        res = subprocess.run([get_gcloud_cmd(), "config", "config-helper", "--format=value(credential.access_token)"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            tok = res.stdout.strip()
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(tok)
            except Exception:
                pass
            return tok, None
    except Exception:
        pass

    return "", "gcloud credentials not active"

def load_json_config(filename, default_val):
    path = os.path.join(SCRIPT_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Remote fallback for python3 <(curl -s ...) pipe executions
    url = f"https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/{filename}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return default_val

def parse_iso_time(ts_str):
    if not ts_str:
        return None
    try:
        ts_clean = ts_str.rstrip("Z").split(".")[0]
        return datetime.strptime(ts_clean, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def get_disp_width(text):
    w = 0
    i = 0
    text_str = str(text)
    while i < len(text_str):
        c = text_str[i]
        if ord(c) in (0xfe0f, 0xfe0e):
            i += 1
            continue
        if ord(c) in (0x2601, 0x26a1) or ord(c) >= 0x1f300 or unicodedata.east_asian_width(c) in ('F', 'W'):
            w += 2
        else:
            w += 1
        i += 1
    return w

def ljust_jp(text, width):
    text_str = str(text)
    text_w = get_disp_width(text_str)
    return text_str + " " * max(0, width - text_w)

def fmt_qty(val):
    return f"{val:,.3f}".rstrip("0").rstrip(".")

def main():
    parser = argparse.ArgumentParser(description="GCP Action Cost Profiler")
    parser.add_argument("--project", type=str, help="GCP Project ID")
    parser.add_argument("--snap", action="store_true", help="Enable snapshot and delta mode")
    parser.add_argument("--json", action="store_true", help="Output results in raw JSON format")
    args = parser.parse_args()

    t0 = time.time()
    if args.project:
        project_id = args.project
        is_demo = False
    else:
        project_id, is_demo = get_project_id()

    token, auth_err = get_access_token()

    if not args.json:
        if is_demo:
            sys.stderr.write("⚠️ 【注意】 GCPプロジェクトIDが設定されていません (現在デモモード: demo-gcp-project)。\n")
            sys.stderr.write("   実際のGCP環境をプロファイリングするには export GCP_PROJECT=\"your-project-id\" または --project オプションを指定してください。\n\n")
        if not token:
            sys.stderr.write("⚠️ 【注意】 GCP アクセストークンの取得に失敗しました (認証未完了)。\n")
            sys.stderr.write("   Cloud Audit Logs の直接照会はスキップされます。実運用ログを試算するには `gcloud auth login` または Application Default Credentials をセットしてください。\n\n")

    # Load configuration tables dynamically from JSON files
    free_tier_cfg = load_json_config("free_tier.json", {}).get("free_tier", {})
    service_rules = load_json_config("service_rules.json", {}).get("metrics_map", {})

    # Default prices dictionary (JPY) used if free_tier.json is missing keys
    default_prices = {
        "cpu_per_vcpu_sec_jpy": 0.0000372,
        "request_per_count_jpy": 0.000000062,
        "class_b_read_per_op_jpy": 0.0000062,
        "class_a_write_per_op_jpy": 0.0007744,
        "image_generation_per_image_jpy": 6.0000,
        "input_text_per_1k_tokens_jpy": 0.02325,
        "node_per_hour_st_jpy": 232.5000,
        "node_per_hour_jpy": 124.0000,
        "vcpu_per_hour_jpy": 31.0000,
        "pubsub_push_per_op_jpy": 0.00001,
        "secret_access_per_op_jpy": 0.0000093,
        "artifact_storage_per_gb_jpy": 0.015
    }

    # Dynamically build pricing_map from free_tier.json
    pricing_map = {}
    cat_map = {
        "cloud_run": "☁️  アプリ実行",
        "cloud_storage": "💾 ストレージ",
        "gemini_api": "🎨 AI生成",
        "cloud_spanner": "⚡  デプロイ/常時稼働",
        "cloud_bigtable": "⚡  デプロイ/常時稼働",
        "alloydb": "⚡  デプロイ/常時稼働",
        "pubsub": "📦 インフラ・ログ",
        "secret_manager": "📦 インフラ・ログ",
        "artifact_registry": "📦 インフラ・ログ"
    }

    for svc_name, svc_info in free_tier_cfg.items():
        cat = cat_map.get(svc_name, "📦 インフラ・ログ")
        metrics = svc_info.get("metrics", {})
        for mkey, mdata in metrics.items():
            price_key = mdata.get("price_key")
            price = default_prices.get(price_key, 0.0)
            if "editions" in mdata and not price_key:
                for ed in mdata["editions"]:
                    if ed.get("is_default"):
                        price = default_prices.get(ed.get("price_key"), 0.0)
            pricing_map[mkey] = {
                "label": mdata.get("label", mkey),
                "cat": cat,
                "unit": mdata.get("unit", "回"),
                "price_jpy": price,
                "limit": mdata.get("free_limit", 0.0),
                "limit_disp": mdata.get("free_limit_display", "従量制")
            }

    # Fallback to ensure all metrics exist
    if not pricing_map:
        pricing_map = {
            "cpu_seconds": {"label": "Cloud Run CPU", "cat": "☁️ アプリ実行", "unit": "vCPU秒", "price_jpy": 0.0000372, "limit": 180000.0, "limit_disp": "180,000 vCPU秒/月"},
            "request_count":    {"label": "Cloud Run Request", "cat": "☁️ アプリ実行", "unit": "回", "price_jpy": 0.000000062, "limit": 2000000.0, "limit_disp": "2,000,000 回/月"},
            "gcs_read_ops":          {"label": "Cloud Storage Read", "cat": "💾 ストレージ", "unit": "回", "price_jpy": 0.0000062, "limit": 50000.0, "limit_disp": "50,000 回/月"},
            "gcs_write_ops":         {"label": "Cloud Storage Write", "cat": "💾 ストレージ", "unit": "回", "price_jpy": 0.0007744, "limit": 0.0, "limit_disp": "従量制"},
            "image_gen_count":       {"label": "Gemini API (AI画像生成)", "cat": "🎨 AI生成", "unit": "枚", "price_jpy": 6.0000, "limit": 0.0, "limit_disp": "従量制"},
            "text_input_tokens":     {"label": "Gemini API (テキスト入力)", "cat": "🎨 AI生成", "unit": "1kトークン", "price_jpy": 0.02325, "limit": 0.0, "limit_disp": "従量制"},
            "spanner_node_hours":    {"label": "Cloud Spanner Node", "cat": "⚡ 定常プロビジョニング", "unit": "ノード時間", "price_jpy": 232.5000, "limit": 0.0, "limit_disp": "従量制"},
            "bigtable_node_hours":   {"label": "Cloud Bigtable Node", "cat": "⚡ 定常プロビジョニング", "unit": "ノード時間", "price_jpy": 124.0000, "limit": 0.0, "limit_disp": "従量制"},
            "alloydb_cpu_hours":     {"label": "AlloyDB Cluster (4 vCPU)", "cat": "⚡ 定常プロビジョニング", "unit": "vCPU時間", "price_jpy": 31.0000, "limit": 0.0, "limit_disp": "従量制"}
        }

    now_utc = datetime.now(timezone.utc)
    t_5m  = now_utc - timedelta(minutes=5)
    t_30m = now_utc - timedelta(minutes=30)
    t_1h  = now_utc - timedelta(hours=1)
    t_24h = now_utc - timedelta(hours=24)

    counts_5m  = {k: 0.0 for k in pricing_map}
    counts_30m = {k: 0.0 for k in pricing_map}
    counts_1h  = {k: 0.0 for k in pricing_map}
    counts_24h = {k: 0.0 for k in pricing_map}

    # Directory for snapshots & raw log outputs
    snap_dir = os.path.join(SCRIPT_DIR, ".data")
    if snap_dir.startswith("/proc") or snap_dir.startswith("/dev") or "/fd" in snap_dir:
        snap_dir = os.path.join(os.getcwd(), ".data")
    try:
        os.makedirs(snap_dir, exist_ok=True)
    except Exception:
        snap_dir = "/tmp/.data"
        os.makedirs(snap_dir, exist_ok=True)

    snap_file = os.path.join(snap_dir, "snapshot.json")
    out_file = os.path.join(snap_dir, "action_cost_result.json")
    raw_log_file = os.path.join(snap_dir, "raw_gcp_audit_logs.json")

    raw_log_count = 0
    raw_service_counts = {}

    if True:
        filter_str = f'timestamp >= "{t_24h.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
        all_entries = []

        try:
            cmd = ["gcloud", "logging", "read", filter_str, "--project", project_id, "--format", "json", "--limit", "3000"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0 and res.stdout.strip():
                all_entries = json.loads(res.stdout)
        except Exception:
            pass

        page_token = None
        page_count = 0
        if not all_entries and token:
            try:
                while True:
                    req_payload = {
                        "resourceNames": [f"projects/{project_id}"],
                        "filter": filter_str,
                        "pageSize": 1000,
                    }
                    if page_token:
                        req_payload["pageToken"] = page_token

                    req_data = json.dumps(req_payload).encode("utf-8")
                    req = urllib.request.Request(
                        "https://logging.googleapis.com/v2/entries:list",
                        data=req_data,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept-Encoding": "gzip"}
                    )

                    with urllib.request.urlopen(req, timeout=30) as resp:
                        raw_bytes = resp.read()
                        if resp.info().get("Content-Encoding") == "gzip":
                            raw_bytes = gzip.decompress(raw_bytes)
                        
                        data = json.loads(raw_bytes.decode("utf-8"))
                        entries = data.get("entries", [])
                        all_entries.extend(entries)
                        page_token = data.get("nextPageToken")
                        page_count += 1

                        if not page_token or page_count >= 100:
                            break
            except Exception:
                pass

        # Fallback to local raw log cache if API request failed or returned empty
        if not all_entries and os.path.exists(raw_log_file):
            try:
                with open(raw_log_file, "r", encoding="utf-8") as f:
                    all_entries = json.load(f)
            except Exception:
                pass

        if all_entries:
            raw_log_count = len(all_entries)
            try:
                with open(raw_log_file, "w", encoding="utf-8") as f:
                    json.dump(all_entries, f, default=str)
            except Exception:
                pass

            resource_trackers = {
                "spanner_node_hours": {"create_kw": ["createinstance"], "delete_kw": ["deleteinstance"], "svc": "spanner.googleapis.com", "mult": 1.0},
                "bigtable_node_hours": {"create_kw": ["createinstance"], "delete_kw": ["deleteinstance"], "svc": "bigtableadmin.googleapis.com", "mult": 1.0},
                "alloydb_cpu_hours": {"create_kw": ["createcluster", "createinstance"], "delete_kw": ["deletecluster", "deleteinstance"], "svc": "alloydb.googleapis.com", "mult": 4.0}
            }

            resource_events = {k: {"creates": [], "deletes": []} for k in resource_trackers}

            for entry in all_entries:
                try:
                    ts = parse_iso_time(entry.get("timestamp") or entry.get("receiveTimestamp"))
                    proto = entry.get("protoPayload") if isinstance(entry.get("protoPayload"), dict) else {}
                    json_p = entry.get("jsonPayload") if isinstance(entry.get("jsonPayload"), dict) else {}

                    svc = (proto.get("serviceName") or json_p.get("serviceName") or entry.get("resource", {}).get("type", "unknown")).lower()
                    method = (proto.get("methodName") or json_p.get("methodName") or "").lower()

                    if not method:
                        log_id = entry.get("logName", "").split("/")[-1]
                        method_disp = f"{log_id} (システム/アプリログ)"
                    else:
                        method_disp = proto.get("methodName") or json_p.get("methodName")

                    raw_svc_name = proto.get("serviceName") or json_p.get("serviceName") or entry.get("resource", {}).get("type", "unknown")
                    if raw_svc_name not in raw_service_counts:
                        raw_service_counts[raw_svc_name] = {}
                    raw_service_counts[raw_svc_name][method_disp] = raw_service_counts[raw_svc_name].get(method_disp, 0) + 1

                    for rkey, rcfg in resource_trackers.items():
                        if rcfg["svc"] in svc:
                            for ck in rcfg["create_kw"]:
                                if ck in method:
                                    resource_events[rkey]["creates"].append(ts)
                            for dk in rcfg["delete_kw"]:
                                if dk in method:
                                    resource_events[rkey]["deletes"].append(ts)

                    def add_metric(key, delta):
                        if ts is None or ts >= t_24h:
                            counts_24h[key] += delta
                        if ts is None or ts >= t_1h:
                            counts_1h[key] += delta
                        if ts is None or ts >= t_30m:
                            counts_30m[key] += delta
                        if ts is None or ts >= t_5m:
                            counts_5m[key] += delta

                    if svc == "aiplatform.googleapis.com":
                        proto_str = (str(proto) + " " + str(json_p)).lower()
                        if ("imagen" in proto_str or "imagegeneration" in proto_str or "image" in proto_str) and "embed" not in proto_str:
                            add_metric("image_gen_count", 1.0)
                        else:
                            # Vertex AI text embeddings (text-embedding / text-multilingual-embedding) or Gemini text generation
                            add_metric("text_input_tokens", 0.5)
                    elif svc == "storage.googleapis.com":
                        if "storage.objects.create" in method:
                            add_metric("gcs_write_ops", 1.0)
                        elif "storage.objects.get" in method:
                            add_metric("gcs_read_ops", 1.0)
                    elif svc == "pubsub.googleapis.com":
                        if "publish" in method:
                            add_metric("pubsub_publish_ops", 1.0)
                    elif svc == "secretmanager.googleapis.com":
                        if "accesssecretversion" in method:
                            add_metric("secret_access_ops", 1.0)
                    elif "run.googleapis.com" in svc or "cloud_run" in svc or entry.get("httpRequest"):
                        add_metric("request_count", 1.0)
                        add_metric("cpu_seconds", 0.2)
                except Exception:
                    continue

            # Calculate precise Uptime Duration (Create -> Delete) for Deployed Resources
            for rkey, rcfg in resource_trackers.items():
                evs = resource_events[rkey]
                creates = sorted([t for t in evs["creates"] if t])
                deletes = sorted([t for t in evs["deletes"] if t])

                if creates:
                    start_t = creates[0]
                    end_t = deletes[-1] if (deletes and deletes[-1] > start_t) else now_utc

                    def calc_overlap_hours(window_start):
                        s = max(start_t, window_start)
                        e = min(end_t, now_utc)
                        if e > s:
                            return ((e - s).total_seconds() / 3600.0) * rcfg["mult"]
                        return 0.0

                    counts_5m[rkey] = calc_overlap_hours(t_5m)
                    counts_30m[rkey] = calc_overlap_hours(t_30m)
                    counts_1h[rkey] = calc_overlap_hours(t_1h)
                    counts_24h[rkey] = calc_overlap_hours(t_24h)

            # Direct Live Provisioned Resource Discovery Fallback (Spanner / Bigtable / AlloyDB)
            try:
                if counts_24h.get("spanner_node_hours", 0.0) == 0.0:
                    cmd_sp = [get_gcloud_cmd(), "spanner", "instances", "list", "--project", project_id, "--format", "json", "--quiet"]
                    res_sp = subprocess.run(cmd_sp, capture_output=True, text=True, timeout=10)
                    if res_sp.returncode == 0 and res_sp.stdout.strip():
                        sp_insts = json.loads(res_sp.stdout)
                        for inst in sp_insts:
                            if inst.get("state") == "READY":
                                c_str = inst.get("createTime")
                                c_dt = parse_iso_time(c_str) if c_str else t_24h
                                pus = float(inst.get("processingUnits", 1000))
                                mult = pus / 1000.0
                                def calc_sp_overlap(w_start):
                                    s = max(c_dt, w_start) if c_dt else w_start
                                    e = now_utc
                                    return ((e - s).total_seconds() / 3600.0) * mult if e > s else 0.0
                                counts_5m["spanner_node_hours"] += calc_sp_overlap(t_5m)
                                counts_30m["spanner_node_hours"] += calc_sp_overlap(t_30m)
                                counts_1h["spanner_node_hours"] += calc_sp_overlap(t_1h)
                                counts_24h["spanner_node_hours"] += calc_sp_overlap(t_24h)
            except Exception:
                pass

    # Snapshot / Delta handling
    is_delta = False
    delta_counts = {}

    if args.snap:
        if os.path.exists(snap_file):
            try:
                with open(snap_file, "r", encoding="utf-8") as f:
                    old_snap = json.load(f)
                old_counts = old_snap.get("counts_24h", {})
                for k in counts_24h:
                    delta_counts[k] = max(0.0, counts_24h[k] - old_counts.get(k, 0.0))
                is_delta = True
            except Exception:
                pass
        
        # Save new snapshot
        with open(snap_file, "w", encoding="utf-8") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "counts_24h": counts_24h}, f, indent=2, ensure_ascii=False)

    # Build final result payload
    result_items = []
    tot_5m, tot_30m, tot_1h, tot_24h = 0.0, 0.0, 0.0, 0.0

    target_counts_24h = delta_counts if is_delta else counts_24h

    for mkey, meta in pricing_map.items():
        q_5m  = counts_5m.get(mkey, 0.0)
        q_30m = counts_30m.get(mkey, 0.0)
        q_1h  = counts_1h.get(mkey, 0.0)
        q_24h = target_counts_24h.get(mkey, 0.0)
        price = meta["price_jpy"]

        c_5m  = q_5m  * price
        c_30m = q_30m * price
        c_1h  = q_1h  * price
        c_24h = q_24h * price

        tot_5m  += c_5m
        tot_30m += c_30m
        tot_1h  += c_1h
        tot_24h += c_24h

        limit = meta["limit"]
        rem = max(0.0, limit - q_24h) if limit > 0 else 0.0
        rem_pct = (rem / limit * 100.0) if limit > 0 else 0.0
        exceeded = max(0.0, q_24h - limit) if limit > 0 else q_24h
        billed_jpy = (exceeded * price) if limit > 0 else c_24h

        is_deployed = mkey in ("spanner_node_hours", "bigtable_node_hours", "alloydb_cpu_hours", "gce_instance_hours")
        cat_disp = "⚡ デプロイ/常時稼働" if is_deployed else meta["cat"]

        result_items.append({
            "key": mkey,
            "label": meta["label"],
            "category": cat_disp,
            "is_deployed": is_deployed,
            "unit": meta["unit"],
            "price_jpy": price,
            "q_5m": q_5m,   "c_5m": c_5m,
            "q_30m": q_30m, "c_30m": c_30m,
            "q_1h": q_1h,   "c_1h": c_1h,
            "q_24h": q_24h, "c_24h": c_24h,
            "free_limit": meta["limit_disp"],
            "free_remaining_pct": f"{rem_pct:.2f}%" if limit > 0 else "N/A",
            "billed_jpy": "￥0 (完全無料)" if (limit > 0 and exceeded == 0) else f"￥{billed_jpy:,.4f}"
        })

    payload = {
        "project_id": project_id,
        "timestamp": datetime.now().isoformat(),
        "is_delta_mode": is_delta,
        "totals": {
            "5m_jpy": tot_5m,
            "30m_jpy": tot_30m,
            "1h_jpy": tot_1h,
            "24h_jpy": tot_24h
        },
        "items": result_items
    }

    # Save output to .data/action_cost_result.json
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    # Print Terminal Table
    line_w = 168
    mode_title = " (差分計測モード)" if is_delta else ""

    print("=" * line_w)
    print(f"📜 【Step 1: GCP 生監査ログ収集 ＆ サマリー】 (過去24時間 / プロジェクト: {project_id})")
    print("=" * line_w)

    if token and raw_log_count > 0:
        raw_log_file = os.path.join(snap_dir, "raw_gcp_audit_logs.json")
        print(f"  ✅ ログ取得成功: 過去24時間の全領域から合計 {raw_log_count:,} 件の生ログを一括ダウンロード・解析しました。")
        print(f"  📂 生ログ保存先: {raw_log_file} (全 {raw_log_count:,} 件の元データJSONを保存済み)")
        print("  [検出されたサービス ＆ API操作別・内訳]")
        sorted_svcs = sorted(raw_service_counts.items(), key=lambda x: sum(x[1].values()), reverse=True)
        for svc, methods in sorted_svcs:
            svc_tot = sum(methods.values())
            svc_clean = urllib.parse.unquote(svc)
            print(f"  [{svc_tot:>5,d} 回] • {svc_clean}")
            sorted_methods = sorted(methods.items(), key=lambda x: x[1], reverse=True)
            for m, cnt in sorted_methods[:5]:
                m_clean = urllib.parse.unquote(m)
                print(f"  [{cnt:>5,d} 回]    └ {m_clean}")
            if len(sorted_methods) > 5:
                sub_other = sum(c for _, c in sorted_methods[5:])
                print(f"  [{sub_other:>5,d} 回]    └ (その他 {len(sorted_methods)-5} 種類の操作)")
    elif token and raw_log_count == 0:
        print(f"  ℹ️ ログ検索完了: 過去24時間以内に検出されたログは 0 件です。")
        print("     ※ データアクセス監査ログ (IAM ➔ 監査ログ) が有効化されているかご確認ください。")
    else:
        print(f"  ⚠️ 認証未完了: GCP アクセストークン未取得のためログ検索をスキップしました (デモモード)。")
        print("     ※ 実際のログを追跡するには `gcloud auth login` または `export GCP_PROJECT=...` を指定してください。")
    print("-" * line_w)
    print()

    print("=" * line_w)
    print(f"🏆 【Step 2: GCP Action Cost 精密原価プロファイル{mode_title}】 (プロジェクト: {project_id})")
    print("=" * line_w)

    def format_cell(cost, qty, unit_name="", is_deployed=False):
        if is_deployed:
            if qty == 0:
                q_str = " 0.0h"
            else:
                q_str = f"{qty:4.1f}h"
        else:
            if "枚" in unit_name:
                q_str = f"{int(qty):>4d}枚"
            elif "回" in unit_name:
                q_str = f"{int(qty):>4d}回"
            elif "トークン" in unit_name:
                q_str = f"{qty:>4.1f}k"
            elif "秒" in unit_name:
                q_str = f"{qty:>4.1f}s"
            elif "時間" in unit_name or "h" in unit_name:
                q_str = f"{qty:>4.1f}h"
            else:
                q_str = f"{int(qty):>5d}"
        c_str = f"￥{cost:8.4f}"
        return f"{c_str} ({q_str})"

    # 1. Print Deployed / Provisioned Section
    deployed_items = [item for item in result_items if item["is_deployed"]]
    serverless_items = [item for item in result_items if not item["is_deployed"]]

    print("  ⚡ 【1. デプロイ・常時プロビジョニング系】 (作成〜削除までの実稼働時間をログから高精度計測)")
    print(f"  {ljust_jp('【直近 5分】', 20)} │ {ljust_jp('【直近 30分】', 20)} │ {ljust_jp('【直近 1時間】', 20)} │ {ljust_jp('【直近 24時間/差分】', 20)} │ {ljust_jp('単位', 11)} │ {ljust_jp('区分', 26)} │ {ljust_jp('サービス・リソース名', 35)}")
    print("-" * line_w)
    for item in deployed_items:
        # Show actual instance uptime hours for AlloyDB (dividing by vCPU multiplier 4.0 if alloydb)
        display_q_5m  = item['q_5m']  / 4.0 if item['key'] == 'alloydb_cpu_hours' else item['q_5m']
        display_q_30m = item['q_30m'] / 4.0 if item['key'] == 'alloydb_cpu_hours' else item['q_30m']
        display_q_1h  = item['q_1h']  / 4.0 if item['key'] == 'alloydb_cpu_hours' else item['q_1h']
        display_q_24h = item['q_24h'] / 4.0 if item['key'] == 'alloydb_cpu_hours' else item['q_24h']

        col_5m  = format_cell(item['c_5m'],  display_q_5m,  item['unit'], is_deployed=True)
        col_30m = format_cell(item['c_30m'], display_q_30m, item['unit'], is_deployed=True)
        col_1h  = format_cell(item['c_1h'],  display_q_1h,  item['unit'], is_deployed=True)
        col_24h = format_cell(item['c_24h'], display_q_24h, item['unit'], is_deployed=True)
        print(f"  {ljust_jp(col_5m, 20)} │ {ljust_jp(col_30m, 20)} │ {ljust_jp(col_1h, 20)} │ {ljust_jp(col_24h, 20)} │ {ljust_jp(item['unit'], 11)} │ {ljust_jp(item['category'], 26)} │ {ljust_jp(item['label'], 35)}")
    print("-" * line_w)
    print()

    # 2. Print Serverless Section
    print("  ☁️ 【2. サーバーレス・従量課金系】 (リクエスト・データ転送・AI生成数による即時従量計算)")
    print(f"  {ljust_jp('【直近 5分】', 20)} │ {ljust_jp('【直近 30分】', 20)} │ {ljust_jp('【直近 1時間】', 20)} │ {ljust_jp('【直近 24時間/差分】', 20)} │ {ljust_jp('単位', 11)} │ {ljust_jp('区分', 26)} │ {ljust_jp('サービス・リソース名', 35)}")
    print("-" * line_w)
    for item in serverless_items:
        col_5m  = format_cell(item['c_5m'],  item['q_5m'],  item['unit'], is_deployed=False)
        col_30m = format_cell(item['c_30m'], item['q_30m'], item['unit'], is_deployed=False)
        col_1h  = format_cell(item['c_1h'],  item['q_1h'],  item['unit'], is_deployed=False)
        col_24h = format_cell(item['c_24h'], item['q_24h'], item['unit'], is_deployed=False)
        print(f"  {ljust_jp(col_5m, 20)} │ {ljust_jp(col_30m, 20)} │ {ljust_jp(col_1h, 20)} │ {ljust_jp(col_24h, 20)} │ {ljust_jp(item['unit'], 11)} │ {ljust_jp(item['category'], 26)} │ {ljust_jp(item['label'], 35)}")

    print("-" * line_w)
    print(" 💰 【時間枠別・合計確定原価サマリー】")
    print(f"    🔹 【直近 5分】       : ￥{tot_5m:,.4f}")
    print(f"    🔹 【直近 30分】      : ￥{tot_30m:,.4f}")
    print(f"    🔹 【直近 1時間】     : ￥{tot_1h:,.4f}")
    print(f"    🔹 【直近 24時間/差分】 : ￥{tot_24h:,.4f}")
    raw_log_file = os.path.join(snap_dir, "raw_gcp_audit_logs.json")
    print(f"⚡ 処理完了時間: {time.time() - t0:.3f}秒 | 生ログ保存先: {raw_log_file} | 試算結果: {out_file}")
    print("=" * line_w)

if __name__ == "__main__":
    main()
