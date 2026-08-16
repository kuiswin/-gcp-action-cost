# 📊 GCP Action Cost Profiler (`gcp-action-cost`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Google Cloud](https://img.shields.io/badge/Google%20Cloud-Supported-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/)

GCPの1円未満の微小コストや無料枠（Always Free）の消化率を、標準ライブラリのみで即座にリアルタイム算出・可視化するCLIツールです。

---

## 🚀 使い方

### 1. ワンコマンドで実行（インストール不要）

以下のコマンドをターミナルで実行するだけで、全サービスの無料枠消化率と概算コストが即座に表示されます：

```bash
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/gcp-action-cost/main/calc_cost.py)
```

---

### 2. 「1操作分」のビフォーアフター差分計測

「Webアクセス1回」「データ投稿1回」などの特定アクション前後で**2回叩くだけ**で、自動的に差分コストを計測します：

```bash
# 操作前（1回目）：スナップショット保存
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/gcp-action-cost/main/calc_cost.py)

# 〜〜 計測したい操作（API実行や画面操作）を実施 〜〜

# 操作後（2回目）：直前操作による「1操作分の増分コスト」を出力
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/gcp-action-cost/main/calc_cost.py)
```

---

### 3. ローカルで実行する場合

```bash
git clone https://github.com/kuiswin/gcp-action-cost.git
cd gcp-action-cost

# 通常実行
python3 calc_cost.py

# 差分スナップショット計測
python3 calc_cost.py --snap

# プロジェクトIDを直接指定
python3 calc_cost.py --project YOUR_PROJECT_ID
```

---

## 🔑 動作要件・前提

- Python 3.x（標準ライブラリのみで動くため追加の `pip install` は不要です）
- `gcloud` CLI がセットアップされていること
- 権限: `roles/billing.viewer`, `roles/logging.viewer`

---

## 📜 ライセンス

[MIT License](LICENSE)
