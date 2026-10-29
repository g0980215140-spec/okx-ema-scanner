# OKX EMA Scanner

公開版 OKX USDT 永續合約 EMA 掃描網站。使用 OKX 公開 API，不需要 API key，也不會下單。

## 功能
- 掃描 OKX live USDT 結算永續合約。
- 1H / 4H EMA20、EMA50、EMA200 糾纏排行榜。
- EMA20 / EMA50 距離縮小、可能金叉/死叉、已金叉/死叉狀態。
- 1H + 4H 共振清單。
- 以已收盤 K 線計算；每 5 分鐘背景更新。

## 部署到 Render（瀏覽器操作）
1. 在 GitHub 建立新的 repository，例如 `okx-ema-scanner`。
2. 將這個資料夾內所有檔案上傳到 repository 根目錄，保留 `templates` 和 `static` 資料夾結構。
3. 登入 Render，選 **New + → Blueprint**，連接 GitHub 並選擇此 repository。
4. Render 會讀取 `render.yaml`；確認建立服務。
5. 等待 build/deploy 完成，打開 Render 顯示的 `onrender.com` 網址。

若 Blueprint 選項不可用：選 **New + → Web Service**，連接 repository，設定：
- Runtime: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --workers 1 --threads 8 --timeout 120`

## 訊號定義
- 糾纏分數：以 EMA20/50/200 的最大值與最小值差距相對於現價計算；越集中分數越高。
- 碰頭分數：以 EMA20/50 距離計算，若最近三次距離持續縮小會加分。
- 可能金叉/死叉只是根據距離收斂推算，不保證交叉或價格方向。
- 共振：1H 和 4H 同時滿足糾纏（差距不超過 1%）或兩週期 EMA20/50 都持續收斂。

## 限制
- 第一次掃描全部交易對可能需要數分鐘；免費服務休眠後第一次打開也可能等待啟動和掃描。
- OKX API 限速或部分交易對資料不足時，個別幣種可能暫時缺失；頁面會顯示部分錯誤提示。
- 本工具僅供市場研究，不是買賣建議，不會自動交易。
