# 台北 Amex FHR / THC 房價追蹤

每天由 GitHub Actions（`.github/workflows/taipei-hotels.yml`）執行 `track.py`：

1. 從 [Open Hotel Data](https://github.com/kevchentw/open-hotel-data) 下載飯店清單，篩出台北的 FHR / THC 飯店。
2. 用 [Xotelo](https://xotelo.com/)（Open Hotel Data 也用它）查 2026/11/20 入住到 2027/1/18 退房之間「每一晚」的最低房價（含稅、1 晚）。
3. 跟上次的快照 `data/latest.json` 比對，找出價格變動 ≥ 5% 的晚上、最便宜的日期，以及清單有沒有新增或移除飯店。
4. 用 Gmail 寄摘要給你，再把新的快照 commit 回 repo。

## 設定 Gmail

在 repo 的 **Settings → Secrets and variables → Actions** 新增：

| Secret | 內容 |
| --- | --- |
| `GMAIL_USER` | 寄件的 Gmail 地址 |
| `GMAIL_APP_PASSWORD` | Gmail「應用程式密碼」（Google 帳戶 → 安全性 → 兩步驟驗證 → 應用程式密碼），不是一般登入密碼 |
| `MAIL_TO` | （選填）收件人，預設寄給 `GMAIL_USER`，多人用逗號分隔 |

沒設定的話一樣會跑，只是不寄信，摘要會出現在 Actions 執行頁面的 Summary。

## 注意

- 排程（schedule）只會在 repo 的預設分支（main）上觸發，要先把這個分支合併進 main。
- 價格是 OTA 的公開房價（TripAdvisor / Xotelo），不是 Amex Travel 上的 FHR 價格，FHR 價格通常差不多或略高，但含早餐、升等、$100 額度等福利。
- Open Hotel Data 的清單最後更新於 2026/4，Amex 之後新加入的飯店可能不會出現。
- 區間、城市、幣別、變動門檻可在 workflow 的 `env` 調整；本機測試可用 `DRY_RUN=1 python taipei_hotels/track.py`（不寄信、不寫檔）。
