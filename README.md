# 📊 GCP Action Cost Profiler (`gcp-action-cost`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Google Cloud](https://img.shields.io/badge/Google%20Cloud-Supported-4285F4?logo=google-cloud&logoColor=white)](https://cloud.google.com/)

GCPの1円未満の微小コストや無料枠（Always Free）の消化率を、標準ライブラリのみで即座にリアルタイム算出・可視化するCLIツールです。

---

## 🚀 使い方

以下のコマンドをターミナルで実行するだけで、全サービスの無料枠消化率と概算コストが即座に表示されます：

```bash
python3 <(curl -s https://raw.githubusercontent.com/kuiswin/gcp-action-cost/main/calc_cost.py)
```

---

## 🔑 動作要件

- Python 3.x（標準ライブラリのみで動作）
- `gcloud` CLI がセットアップされていること

---

## ⚠️ 注意事項

本ツールが試算・表示する金額やコストは**あくまで概算の目安**です。  
Google Cloudの契約形態、割引、エディション、リージョン等の違いにより、実際の請求額とは差異が生じる場合があります。  
**最終的な正確な利用料金や請求実績は、必ずご自身で Google Cloud Console（お支払い / Billing 画面）をご確認ください。**

---

## 📜 ライセンス

[MIT License](LICENSE)
