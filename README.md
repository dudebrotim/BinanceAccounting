# Binance Accounting

每日自動從 Binance 擷取 Spot / Funding / Futures / Simple Earn 資產，計算數量與 USD 估值變化，並追加寫入 Google Sheet。

## 專案結構

```
BinanceAccounting/
├── config/
│   └── config.example.toml   # 設定範例（複製為 config.toml 使用）
├── data/                      # 每日快照 JSON（自動產生，已 gitignore）
├── src/binance_accounting/
│   ├── main.py                # CLI 入口，串接所有流程
│   ├── binance_client.py      # Binance REST API 封裝（Spot/Funding/Futures/Simple Earn）
│   ├── valuation.py           # 各幣 → USD 估值（支援 USDT/USDC/BTC/ETH 路由）
│   ├── snapshot_store.py      # 本地 JSON 快照存取
│   ├── diff.py                # 與前一日快照比較，產出數量 + USD 差異
│   └── sheets_writer.py       # Google Sheet append 寫入
├── tests/
├── pyproject.toml
├── .env.example
└── .gitignore
```

## 執行流程

```
Binance API ─→ 資產擷取 ─→ USD 估值 ─→ 本地快照 ─→ 日差計算 ─→ Google Sheet
 (Spot/Funding/Futures/Earn) (市價轉換)    (JSON)     (qty + USD)    (append row)
```

## 環境需求

- Python >= 3.11
- Binance API Key（需啟用 Read 權限）
- Google Service Account JSON（需有目標 Spreadsheet 的編輯權限）

## 安裝

```bash
git clone <repo-url>
cd BinanceAccounting

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 設定

### 1. 複製設定檔

```bash
cp config/config.example.toml config/config.toml
```

編輯 `config/config.toml`，填入 Binance API Key 和 Google Sheet 相關資訊：

```toml
[binance]
api_key = "your_api_key"
secret_key = "your_secret_key"

[google]
service_account_path = "credentials/service_account.json"
spreadsheet_id = "your_spreadsheet_id"
worksheet_name = "daily_assets"  # base name
worksheet_mode = "weekly"        # weekly | fixed
template_worksheet = "2024/09/27 - 2024/10/03"  # 新分頁套用樣板（顏色/格式/公式）

[snapshot]
data_dir = "data"

[settings]
timezone = "Asia/Taipei"
tracked_coins = []        # 留空 = 自動涵蓋當日全部幣種
min_usd_value = 0.0       # 保留灰塵資產
```

### 2. 設定環境變數（可選，優先於 config）

```bash
export BINANCE_API_KEY=xxx
export BINANCE_SECRET_KEY=xxx
export GOOGLE_SERVICE_ACCOUNT_PATH=credentials/service_account.json
```

或複製 `.env.example` → `.env` 後搭配 `source .env` 使用。

### 3. Google Service Account 設定

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 建立 Service Account
2. 啟用 Google Sheets API
3. 下載 JSON 金鑰檔放到 `credentials/service_account.json`
4. 在目標 Google Sheet 中，將 Service Account 的 email 加為**編輯者**

## 使用方式

```bash
source .venv/bin/activate

# 測試模式：擷取資產並顯示摘要，不寫入 Sheet
python -m binance_accounting --dry-run

# 正式執行：擷取 + 寫入 Google Sheet
python -m binance_accounting

# 指定設定檔
python -m binance_accounting -c /path/to/config.toml

# 顯示詳細 log
python -m binance_accounting -v
```

## Google Sheet 輸出格式

預設會按週自動建立分頁（週一到週日），例如：

- `daily_assets_20260504_20260510`
- `daily_assets_20260511_20260517`

新分頁會建立在 Google Sheet 的最左邊。  
每次執行會更新「類似 CryptoAccount.csv」的週表格式：

| 區塊 | 說明 |
|------|------|
| Header（第 1 列） | `Token / Fixed Rate / Spot Rate / (空欄) / Prev Qty / (CEX/DEX) / 週一~週日 / Weekly / Spot Value Diff` |
| Section Rows（第 2 列起） | 區分 `Token / Margin / Staking / Chain/Cex / Loan / Short without profit / Limit Order (Recovery)` |
| Data Rows | 目前自動資料會寫在 `Token`（一般幣）與 `Staking`（`LD*` 理財代幣） |

- `tracked_coins` 留空時，自動涵蓋當日所有幣種
- 若要維持單一固定分頁，將 `worksheet_mode` 改為 `fixed`
- `template_worksheet` 可指定要複製的舊分頁樣板（新分頁建立時會複製顏色與格式）
- `BNB`、`USDT` 會做特別底色標註

## 排程（Cron）

每日台北時間 23:55 自動執行：

```bash
crontab -e
```

```cron
55 23 * * * cd /Users/timothy/Documents/BinanceAccounting && .venv/bin/python -m binance_accounting >> data/cron.log 2>&1
```

## 本地快照

每次執行會在 `data/` 目錄下產生當日 JSON 快照（如 `2026-04-16.json`），包含：

- 總資產 USD
- 各帳戶（Spot/Funding/Futures/Earn）小計
- 每幣的數量、USD 估值、價格、帳戶分布

快照用於次日比較計算差異，首次執行時無前日資料，差異欄位會顯示 `N/A (first)`。
