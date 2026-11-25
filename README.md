# YTD Atlas

開啟 index.html，選擇資產並勾選年份，即可在同一張圖比較每日 YTD ROI。

## 資料與更新

執行 python3 refresh.py（Python 3.10 以上）更新 HTML 內嵌收盤價。網站採 Yahoo Finance 日線、GoldPrice.com 黃金現貨日線（早期倫敦定盤，後續 Metals.dev。CC BY 4.0，https://www.goldprice.com/gold-price-history），以及 Coin Metrics 的 BTC 2010–2014 序列（CC BY-NC 4.0）。每年的分母為上一年底最後一筆收盤價。

## GitHub Pages

提交本資料夾至 GitHub repository。在 Settings → Pages 選擇 Deploy from a branch，使用 main 分支的根目錄。
