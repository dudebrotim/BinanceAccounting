# Binance 每日資產記帳上傳 Google Sheet：實作計畫

## 問題與目標
建立一個每日可執行的記帳工具，從 Binance 擷取資產資料，並同時輸出：
- 各幣數量變化
- USDT/USD 估值變化

結果要持續追加到 Google Sheet，方便每天追蹤資產增減。

## 目前程式現況（已分析）
- `/Users/timothy/Documents/BinanceAccounting` 目前是空目錄（你已指定在此新建獨立專案）。
- `/Users/timothy/Documents/CryptoNewTrading/exchange` 可作為參考：
  - 已有 Binance API 整合與 balance query 寫法可借鑑。
- 目標新專案目前尚未具備：
  - Binance Spot/Funding/Futures 的統一聚合流程
  - 每日快照與日差計算
  - Google Sheets 寫入
  - 排程與部署文件

## 已確認需求（目前）
1. 記帳口徑：**同時記錄數量變化 + 估值變化**。
2. 資產範圍：**Spot + Funding + Futures**。
3. 實作位置：**`/Users/timothy/Documents/BinanceAccounting` 新專案**。
4. 排程時間：**Asia/Taipei 23:55**。
5. Sheet 配置：**單一工作表 `daily_assets`**。
6. 資料粒度：**每天一列（總資產摘要 + 主要指標）**。
7. Spreadsheet：**`198YSdo5NHKy0JhqEUEyM3TjMFQxbxRlS2ICpQJPaKFk`**。

## 實作策略
在 `BinanceAccounting` 建立單次執行 CLI（由 cron 每日觸發），拆成 5 層：
1. **Binance 擷取層**：分別抓 Spot、Funding、Futures 資產並正規化。
2. **估值層**：把各資產轉為 USDT/USD 估值（保留原始數量）。
3. **快照/差異層**：讀取前一日快照，計算今天與昨日差異（數量 + 估值）。
4. **輸出層**：append 到 Google Sheet（同時可選本地 CSV 備援輸出）。
5. **執行層**：CLI 參數、錯誤碼、日誌，供排程與告警串接。

## 專案結構（規劃）
- `src/binance_accounting/main.py`：主入口（單次執行）
- `src/binance_accounting/binance_client.py`：Binance API 封裝（Spot/Funding/Futures）
- `src/binance_accounting/valuation.py`：估值計算
- `src/binance_accounting/snapshot_store.py`：本地狀態儲存（JSON/SQLite）
- `src/binance_accounting/diff.py`：日差計算
- `src/binance_accounting/sheets_writer.py`：Google Sheet append
- `config/config.example.toml`：範例設定
- `README.md`：設定與排程說明
- `tests/...`：單元測試

## Todo（規劃）
1. **初始化新專案骨架**
   - 在 `BinanceAccounting` 建立 Python 專案（pyproject、src layout、tests）。
2. **實作 Binance 三帳戶資產聚合**
   - 串接 Spot/Funding/Futures 查詢，輸出統一資產模型。
3. **實作估值與日差計算**
   - 產出每幣與總資產的「今日值、昨日值、差值、變化率」。
4. **實作本地快照儲存**
   - 保存上次成功快照，支援首次執行（無前值）邏輯。
5. **實作 Google Sheet 上傳**
   - 以 service account append row，處理欄位對應與重試策略。
6. **補測試與文件**
   - 覆蓋關鍵邊界（新幣、清倉、缺價、API 失敗、Sheet 失敗）並補 README + cron 範例。

## 重要設計決策（預設）
- 執行模式：**單次執行 + cron**
- 寫入模式：**Google Sheet append-only**
- 輸出粒度：**1 天 1 列（summary row）**
- 比較基準：**前一次成功快照**
- 失敗策略：**任一步驟失敗即非 0 結束碼，不寫入假成功紀錄**
- 安全性：**API Key 與 Google 憑證路徑走環境變數，不進版控**

## 待確認
1. 欄位順序與主要指標清單（若未指定，預設：日期、總資產USD、日增減USD、日增減%、SpotUSD、FundingUSD、FuturesUSD、備註）。
