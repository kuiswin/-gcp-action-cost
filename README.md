# 📊 GCP Action Cost Profiler (`gcp-action-cost`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Google Cloud](https://img.shields.io/badge/Google%20Cloud-Supported-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/)

GCPコンソール画面（請求画面）では丸められて **「￥0（または $0.00）」** と表示されてしまう1円未満の微小コストを、**GCP Service Usage API / Monitoring API (生消費データ)** と **Billing Catalog API (公式リアルタイム単価)** を組み合わせてリアルタイム精密算出するオープンソースCLIプロファイラーです。

任意のGCPプロジェクトでワンコマンド実行するだけで、有効化中のサービス・適用単価・無料枠（Always Free）消化率を全自動で動的にバインドし、美しい JSON 形式で出力します。

---

## ⚠️ 本ツールの核心：2つの重要前提（Must Read）

### 1. 🔍 「データアクセス監査ログ (Data Access Audit Logs)」の有効化
本ツールが API 呼び出し回数（Cloud Storage 読み書き、Pub/Sub メッセージ発行、Secret Manager 参照など）をリアルタイムに精密追跡するためには、GCPプロジェクト側で **データアクセス監査ログ（Data Access Audit Logs）** が有効化されている必要があります。

> **💡 監査ログの有効化手順 (Google Cloud コンソール):**
> 1. Google Cloud コンソールの **[IAM と管理] ➔ [監査ログ]** を開きます。
> 2. `Google Cloud Storage` / `Cloud Pub/Sub` / `Secret Manager` 等を選択します。
> 3. **「データの読み取り (Data Read)」** および **「データの書き込み (Data Write)」** にチェックを入れて保存します。
> 
> ※ 監査ログが無効化されている場合、一部の微小操作件数がログにカウントされず、プロファイリング結果に反映されない場合があります。

---

### 2. 🚨 サーバーレス型 vs 「常時起動型（マネージドDB等）」のコスト特性判定
本ツールは、GCPプロジェクト内の全アクティブサービスを自動スキャンし、サービスごとの課金モデル（サーバーレス vs 常時起動型）を自動識別して警告出力します。

| サービス種別 | 該当サービス例 | コスト特性 ＆ 本ツールのプロファイリング挙動 |
| :--- | :--- | :--- |
| **⚡ サーバーレス型** | Cloud Run, GCS, Pub/Sub, Vertex AI API | リクエストが無ければ自動で0台にスリープ（ゼロスケール）。アクセスが完全にゼロであれば **維持費はほぼ0円 (無料枠内)** と判定されます。 |
| **🔥 常時起動型 (注意!)** | Cloud Spanner, Cloud Bigtable, AlloyDB | サーバーレスではないため、**リクエストが一切無くても「起動したまま放置」しているだけでノード数やvCPU数に応じた固定課金（毎時数〜数十円）が発生し続けます。** 本ツールはインスタンスの存在と時間単価を検知し、放置リスクの警告を出力します。 |

---

## 🌟 主な機能・特徴

1. **100% 動的なサービス＆単価バインド (`Zero Hardcoding`)**
   プロジェクト内で有効化されているGCPサービス（Cloud Run, Cloud Storage, BigQuery, Gemini API / Vertex AI, Pub/Sub, Artifact Registry, Cloud Spanner, Bigtable, AlloyDB 等）を全自動検出。GCP Billing Catalog API から最新単価を取得し、Always Free（無料枠）上限との引き算明細を自動構築します。

2. **ビフォーアフター差分計測モード (`--snap`)**
   「Webページ閲覧1回」「データ投稿1回」「API呼び出し1回」などの特定アクションの前後に実行することで、**その「1操作」単体で発生したリソース消費量と微小コスト（例: 1リクエストあたり約0.004円）をピンポイント試算**します。

3. **構造化 JSON フォーマット出力**
   ターミナルでの文字幅ズレ（モノスペースフォントの桁ズレ問題）を排除し、他ツールやスクリプトでの二次利用・パースが容易な綺麗な JSON 形式で結果を出力・保存します。

4. **コンソール表示との対比 ＆ 無料枠（Always Free）残量可視化**
   GCPコンソールでは隠れてしまう定価の積算結果と、Always Free（無料枠）が適用されて「確定請求額が0円」になる残量率（%）を分かりやすく提示します。

5. **外部ライブラリ不要（Zero Dependencies）**
   Python 3 標準ライブラリと `gcloud` CLI のみで動作するため、追加の `pip install` は一切不要です。

---

## 🚀 クイックスタート (使い方)

### 1. 全自動プロファイリング (通常実行 / 過去30日モード)

ターミナルで以下の1行を実行するだけで、現在のGCPプロジェクトの全アクティブサービス検出・単価マッピング・無料枠消化率が自動算出されます：

```bash
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/calc_cost.py)
```

---

### 2. 「1操作」ビフォーアフター差分計測モード (自動差分判定)

特定の処理や操作（APIコール、画面操作等）単体でかかった増分コストを計測したい場合、**操作前後にまったく同じコマンドを実行するだけ**で自動的に差分モードで動作します：

```bash
# 【Step 1】 操作前（1回目実行）：現在のベースライン利用状態を自動スナップショット保存
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/calc_cost.py)

# 【Step 2】 計測したい操作（Webアクセス、API実行、投稿など）を実施
# （※ Logging / Monitoring API へのデータ反映のため 1〜2分間 待ちます）

# 【Step 3】 操作後（2回目実行）：直前スナップ以降の「1操作分の差分コスト」をピンポイント出力！
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/calc_cost.py)
```

---

### 3. Git クローンしてローカル実行

```bash
git clone https://github.com/kuiswin/-gcp-action-cost.git
cd -gcp-action-cost

# 現在の gcloud 設定プロジェクトをプロファイリング
python3 calc_cost.py

# 差分計測モード (操作前後に2回叩くだけで自動判定 / --snap オプション指定も可能)
python3 calc_cost.py --snap

# 特定の GCP プロジェクト ID を指定して実行
python3 calc_cost.py --project my-gcp-project-id
```

---

## 📊 出力フォーマット例 (JSON)

### 表①: 無料枠 (Always Free) 引き算明細 (過去30日間)

```json
[
  {
    "リソース": "Cloud Run Request",
    "30日消費量": "148 回",
    "無料枠上限": "2,000,000 回/月",
    "無料枠残量": "1,999,852 回",
    "残量率": "99.99%",
    "超過消費量": "0 回",
    "確定請求": "￥0 (完全無料)"
  },
  {
    "リソース": "Cloud Run CPU",
    "30日消費量": "417.85 vCPU秒",
    "無料枠上限": "180,000 vCPU秒/月",
    "無料枠残量": "179,582.15 vCPU秒",
    "残量率": "99.77%",
    "超過消費量": "0 vCPU秒",
    "確定請求": "￥0 (完全無料)"
  },
  {
    "リソース": "Cloud Storage Read",
    "30日消費量": "296 回",
    "無料枠上限": "50,000 回/月",
    "無料枠残量": "49,704 回",
    "残量率": "99.41%",
    "超過消費量": "0 回",
    "確定請求": "￥0 (完全無料)"
  }
]
```

### 表②: 時間軸 ＆ ビフォーアフター差分計測結果 (`--snap` 実行時)

```json
{
  "30 days": {
    "明細": [
      {
        "サービス": "Cloud Run CPU",
        "消費量": "21.02 vCPU秒",
        "単価": "0.003720 円/vCPU秒",
        "掛け算結果": "0.081914 円"
      },
      {
        "サービス": "Cloud Run Request",
        "消費量": "20 回",
        "単価": "0.000062 円/回",
        "掛け算結果": "0.001240 円"
      }
    ],
    "小計": "0.083154 円",
    "確定請求額": "￥0 (無料枠内)"
  }
}
```

---

## 🔑 必須権限 (Prerequisites)

本ツールで正確なGCP公式請求情報およびログの差分計測を行うためには、実行環境（または認証されたユーザー/サービスアカウント）に以下の権限が必要です。
* `roles/billing.viewer` (課金閲覧者)
* `roles/logging.viewer` (ログ閲覧者)

---

## ⚠️ 仕様と制限事項 (Limitations)

* **単価の前提**: 本ツールは、各サービスの**標準単価（Standardエディション / 基準リージョン等）**をベースに概算コストを動的算出します。Cloud Spannerの `Enterprise Plus` など上位エディションや、特定リージョン専用の高額リソースを利用している場合、実際のGCPコンソール上の請求額とは乖離が生じる場合があります。
* **リアルタイム性**: Cloud Monitoring / Logging API のメトリクス集計の仕様上、直近数分〜数十分のリソース消費データの反映にタイムラグが生じる場合があります。
* **ストレージ容量の換算**: Artifact Registry や Cloud Pub/Sub などのバイト単位メトリクスは、ツール内部で自動的に GB (ギガバイト) に換算して計算・表示されます。

---

## 📜 ライセンス

[MIT License](LICENSE)
