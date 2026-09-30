# AI 新聞 → 行銷文案 → Buffer 自動發文

每天兩個自動任務（部署在 Render Cron Job）：

| 任務 | 時間（`config.py`） | 做什麼 |
|---|---|---|
| `generate` | `GENERATE_TIME`（預設 08:00） | 用 OpenAI web search + RSS 找 `KEYWORDS` 的最新資訊 → 依 `COPY_STYLE_1/2/3` 寫三篇文案 → 各產生一張圖 → 寫進 Google Sheet（`status=PENDING`） |
| `publish` | `PUBLISH_TIME`（預設 15:00） | 讀 Google Sheet，把 **`approved` 已勾選**、還沒排程的列，用 Buffer 排程在該列 `post_time` 發到 FB / IG → 成功後 `status=SCHEDULED` |

所有可調參數都在 `config.py`：關鍵字、兩個任務的時間、三種文案風格、每種文案的發文日期時間、
圖片 prompt 模板、RSS 來源、要發的平台、OpenAI 模型。

## 專案結構

```
config.py            所有設定
main.py              入口：generate / publish / check
autopost/
  research.py        OpenAI web search + RSS
  content.py         寫文案、產生圖片 prompt、產圖、上傳 Cloudinary
  sheet.py           Google Sheet 讀寫
  buffer.py          Buffer GraphQL API
  jobs.py            兩個任務 + 每天只跑一次的時間判斷
render.yaml          Render 兩個 cron job
legacy/              之前的單次發文腳本（post.py 等），新流程不會用到
```

## 1. 取得 Google Sheet 寫入權限（Service Account）

1. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立（或選擇）一個專案。
2. **APIs & Services → Library**，搜尋並啟用 **Google Sheets API** 和 **Google Drive API**。
3. **APIs & Services → Credentials → Create credentials → Service account**，取個名字建立（角色可以不選）。
4. 點進剛建立的 service account → **Keys → Add key → Create new key → JSON**，會下載一個 JSON 檔。
   - 本機：把檔案改名成 `google-service-account.json` 放在專案根目錄（已在 `.gitignore`，不會被 commit）。
   - Render：把 JSON **整個內容**貼到環境變數 `GOOGLE_SERVICE_ACCOUNT_JSON`。
5. 建一個新的 Google Sheet，按右上角 **共用**，把 JSON 裡的 `client_email`
   （長得像 `xxx@yyy.iam.gserviceaccount.com`）加為 **編輯者**。
6. Sheet 網址 `https://docs.google.com/spreadsheets/d/<ID>/edit` 中間那段 `<ID>` 填到 `GOOGLE_SHEET_ID`。

分頁和欄位不用手動建立，第一次執行會自動建立 `posts` 與 `_state` 兩個分頁。

### Sheet 欄位

| 欄位 | 說明 |
|---|---|
| `version` | 文案版本（`COPY_STYLE_x["name"]`） |
| `copy` | 行銷文案，可以直接在 Sheet 裡修改，發文時用修改後的內容 |
| `image_preview` / `image_url` | 圖片預覽 / 公開網址 |
| `post_time` | 發文時間 `YYYY-MM-DD HH:MM`（台北時間），可以手動改 |
| `approved` | ☑ **使用者確認**：勾選才會被發佈 |
| `status` | `PENDING`（待審）→ `SCHEDULED`（已排程到 Buffer） |
| `buffer_facebook_id` / `buffer_instagram_id` | Buffer 貼文 ID |
| `error` | 最近一次失敗原因；失敗的列會保持原狀態，下次 publish 自動重試 |

`_state` 分頁記錄每個任務今天是否跑過，不要手動修改（刪掉某一列可以讓該任務今天重跑）。

## 2. Buffer API

1. 在 Buffer 連接 Facebook Page 和 Instagram（IG 必須是商業或創作者帳號）。
2. 到 Buffer 的 API 設定頁建立 Personal Access key，填到 `BUFFER_API_KEY`。
3. 執行 `python main.py check`，確認抓得到 FB / IG 頻道。同一平台有多個頻道時，
   把要用的 id 填到 `BUFFER_FACEBOOK_CHANNEL_ID` / `BUFFER_INSTAGRAM_CHANNEL_ID`。

**限制（注意）**

- API 請求上限：**每 15 分鐘 100 次、每 24 小時 500 次、每 30 天 10,000 次**，所有 key 和整合共用。
  本專案每次 publish 約用 `2 + 已勾選列數 × 平台數` 次（例如 3 篇 × 2 平台 ≈ 8 次），遠低於上限。
- **API key 有到期日**（建立時選的，例如一個月），到期後要重新產生並更新 Render 的環境變數，否則 publish 會失敗。
- Buffer 免費方案有頻道數量和「每個頻道排程佇列篇數」的上限（以 Buffer 方案頁面為準），
  佇列滿了建立貼文會失敗，錯誤會寫在 Sheet 的 `error` 欄。
- 圖片必須是公開網址（所以本專案先上傳到 Cloudinary）；IG 圖片比例需介於 4:5 ~ 1.91:1。
- 貼文只能排在未來的時間；`post_time` 已過（或距離現在不到 `MIN_LEAD_MINUTES`）的列會跳過並在 `error` 提示。

## 3. 本機執行 / 除錯

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # 填入金鑰

.venv/bin/python main.py check              # 檢查所有金鑰與連線
.venv/bin/python main.py generate --dry-run # 產生文案+圖片並印出，不寫入 Sheet（會花 OpenAI 費用）
.venv/bin/python main.py generate --force   # 立刻產生並寫入 Sheet
.venv/bin/python main.py publish --dry-run  # 只列出會排程哪些列，不呼叫 Buffer
.venv/bin/python main.py publish --force    # 立刻把已勾選的列排程到 Buffer（會真的發文）
```

不加 `--force` 時跟 Render 上的行為一樣：只有「已過設定時間、今天還沒成功跑過」才會執行。

## 4. 部署到 Render

1. Push 到 GitHub。
2. Render → **New → Blueprint** → 選這個 repo，會依 `render.yaml` 建立兩個 cron job：
   `autopost-generate`、`autopost-publish`。
3. 建立時填入環境變數（兩個 service 都要填）：`OPENAI_API_KEY`、`GOOGLE_SHEET_ID`、
   `GOOGLE_SERVICE_ACCOUNT_JSON`、`BUFFER_API_KEY`、`CLOUDINARY_*`。`BUFFER_*_CHANNEL_ID` 可留空。
4. 部署完就會自動開始跑。可在 Render 的 cron job 頁面按 **Trigger Run** 立刻測試一次、看 Logs。

**為什麼 cron 是每 15 分鐘？** Render 的 cron 排程寫在 `render.yaml`、而且是 UTC。為了讓時間只需要改
`config.py`，兩個 cron 每 15 分鐘叫醒一次程式，由程式判斷「現在是否已過設定時間、今天是否已跑過」。
沒到時間的那幾次幾秒鐘就結束。因此實際執行時間最多比設定晚 15 分鐘。

**費用**：Render Cron Job 沒有免費方案，每個 cron job service 最低 **US$1/月**（依實際執行秒數計費），
兩個約 US$2/月。另外 OpenAI 每天一次 generate（1 次 web search + 6 次文字呼叫 + 3 張圖，約 8 分鐘）會有少量費用。
