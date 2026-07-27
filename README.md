# 📊 GCP Action Cost Profiler (`-gcp-action-cost`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Google Cloud](https://img.shields.io/badge/Google%20Cloud-Supported-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/)

GCPコンソール画面（請求画面）では丸められて **「￥0（または $0.00）」** と表示されてしまう1円未満の微小コストを、**GCP Service Usage API / Monitoring API (生消費データ)** と **Billing Catalog API (公式単価)** を組み合わせて、小数点第6桁までリアルタイム精密算出するオープンソースCLIツールです。

---

## 🌟 主な機能・特徴

1. **稼働サービスの自動検出 (`Active Services Discovery`)**
   プロジェクト内で有効化されており、実際にデータが存在するアクティブなGCPサービス（Cloud Run, Cloud Storage, Gemini API等）を全自動で一覧抽出します。

2. **「1回の所作（1操作）」あたりのコストプロファイリング**
   「Webページを1回閲覧したらいくらかかるか（約0.010円）」「記事を1回投稿したらいくらかかるか（約6.002円）」といった、システムの1アクションごとのリソース消費量と微小コストを可視化します。

3. **コンソール表示との対比 ＆ 無料枠（Always Free）自動検証**
   GCPコンソールでは消えてしまう隠れた定価と、Always Free（無料枠）が適用されて「本当の請求額が0円」になる理由を明確に提示します。

4. **外部ライブラリ不要（Zero Dependencies）**
   Python 3 標準ライブラリと `gcloud` のみで動作するため、追加の `pip install` は一切不要です。

---

## 🚀 クイックスタート (使い方)

### 1行で直接実行（推奨）

ターミナルで以下のコマンドを実行するだけで、現在のGCPプロジェクトのコストと1所作プロファイリングが出力されます：

```bash
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/-gcp-action-cost/main/calc_cost.py)
```

### Git クローンして実行

```bash
git clone https://github.com/kuiswin/-gcp-action-cost.git
cd -gcp-action-cost

# 現在の gcloud 設定プロジェクトをプロファイリング
python3 calc_cost.py

# 特定のプロジェクトIDを指定して実行
python3 calc_cost.py --project my-gcp-project-id
```

---

## 📊 出力フォーマット例

```text
================================================================================
📊 GCP Action Cost Profiler (-gcp-action-cost)
================================================================================
・対象プロジェクトID: qiita-app-170

【Step 1】 プロジェクト内で使用中のアクティブGCPサービス (自動検出)
  1. [✓ 稼働検出] Cloud Run
  2. [✓ 稼働検出] Cloud Storage

【Step 2】 Catalog API から照会した主要リソースの単価
  ・Cloud Run CPU       : 0.003720 円 / vCPU秒
  ・Cloud Run Requests  : 0.000062 円 / 回
  ・GCS Write (Class A) : 0.000775 円 / 回 (JSON/MD保存)
  ・GCS Read  (Class B) : 0.000062 円 / 回 (閲覧/配信)

【Step 3】 「1回の所作（操作）」あたりの精密リソース消費量 ＆ コスト
  [A. 記事閲覧 1回 (1 Page View)]
    ・Cloud Run 処理時間 : 0.010 vCPU秒 (0.010503円)
    ・GCS Read (JSON/MD) : 2 回 (0.000124円)
    👉 1閲覧あたりの合計コスト : 【 0.010689 円 】

  [B. 記事投稿 1回 (1 Post Creation + Gemini画像自動生成)]
    ・Cloud Run 処理時間 : 0.350 vCPU秒 (0.001302円)
    ・GCS Write (JSON/MD): 2 回 (0.001550円)
    ・Gemini AI画像生成  : 1 枚 (6.000000円)
    👉 1投稿あたりの合計コスト : 【 6.002914 円 】

【Step 4】 月間実績コスト（定価 vs 実際）
  ・過去30日間の合計リクエスト数 : 148 回
  ・過去30日間の合計CPU使用時間  : 417.85 vCPU秒
  ・月間インフラ定価 (割引前)    : 1.563571 円 (約 1.56 円)
  ・GCP Webコンソール表示        : 丸められて「￥0」と表示
  ・実際の月間請求金額          : Always Free無料枠適用により「完全0円」
================================================================================
```

---

## 📜 ライセンス

[MIT License](LICENSE)
