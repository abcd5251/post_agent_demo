"""自動發文 pipeline 的所有設定。改完 commit + push，Render 會自動重新部署。

流程：
  1. generate（每天 GENERATE_TIME）：用 OpenAI web search + RSS 找 KEYWORDS 的最新資訊，
     依 COPY_STYLE_1/2/3 寫三種行銷文案，各產生一張圖，寫進 Google Sheet（status=PENDING）。
  2. 使用者在 Google Sheet 勾選 approved 欄位。
  3. publish（每天 PUBLISH_TIME）：把「已勾選、還沒排程」的列，用 Buffer 排程在該列的 post_time
     發到 PUBLISH_PLATFORMS。成功後 status=SCHEDULED；失敗保留原狀態，下次再重試。

所有時間都是 TIMEZONE 的時間，格式 "HH:MM"。
"""

TIMEZONE = "Asia/Taipei"

# ─── 排程時間 ────────────────────────────────────────────────
# Render 的 cron 每 15 分鐘叫醒程式一次，程式發現「現在已過這個時間、而且今天還沒跑過」才會執行，
# 所以實際執行時間最多會晚 15 分鐘。
GENERATE_TIME = "08:00"   # 每天產生文案 + 圖片的時間
PUBLISH_TIME = "15:00"    # 每天把已勾選的文案排程到 Buffer 的時間

# 同一天某個任務失敗時，最多重試幾次（避免 OpenAI 一直失敗一直扣錢）
MAX_ATTEMPTS_PER_DAY = 3

# ─── 搜尋 ────────────────────────────────────────────────────
KEYWORDS = ["AI Agent"]

# 只看最近幾小時內的新聞
NEWS_LOOKBACK_HOURS = 48

# RSS 來源。網址裡有 {keyword} 的，會對每個關鍵字各抓一次（自動 URL encode）；
# 沒有 {keyword} 的一般 RSS，會只保留標題或摘要含有任一關鍵字的文章。
RSS_FEEDS = [
    "https://news.google.com/rss/search?q={keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    "https://news.google.com/rss/search?q={keyword}&hl=en-US&gl=US&ceid=US:en",
]
RSS_MAX_ITEMS = 15   # 最多給模型幾則 RSS 文章

# 給 OpenAI web search 的指示。{keywords}、{lookback_hours} 會被替換
RESEARCH_PROMPT = """請用網路搜尋以下關鍵字最近 {lookback_hours} 小時內最重要的新聞與資訊：{keywords}

請整理成一份研究筆記（繁體中文）：
- 挑出最重要、最相關的 3~5 則，每則寫清楚：發生了什麼、關鍵數字、誰說的、日期
- 每則附上原始新聞網址
- 只寫查得到的事實，不確定的不要寫，不要自行推測"""

# ─── 行銷文案（三種版本）──────────────────────────────────────
# 每個版本會各產生一篇文案 + 一張圖，在 Google Sheet 各佔一列。
#   name              版本名稱（會寫進 Sheet 的 version 欄）
#   instructions      這個版本的風格、語氣、喜好、注意事項
#   image_style       這個版本配圖的視覺風格
#   post_day_offset   發文日期 = 產生文案當天 + 幾天
#   post_time         發文時間
# 注意：post_time 要晚於 PUBLISH_TIME，否則當天排程時時間已經過了。
COPY_STYLE_1 = {
    "name": "專業洞察",
    "instructions": """語氣專業、冷靜，像產業分析師。
- 開頭一句點出這則新聞為什麼重要
- 用 2~3 個重點條列說明影響
- 結尾提出一個讓讀者思考的問題
- 不用誇張形容詞，emoji 最多 1 個""",
    "image_style": "clean minimal corporate illustration, navy and white palette, abstract data and network motifs",
    "post_day_offset": 0,
    "post_time": "19:00",
}

COPY_STYLE_2 = {
    "name": "輕鬆有趣",
    "instructions": """語氣輕鬆、口語、有梗，像在跟朋友聊天。
- 開頭用一個生活化的比喻或情境吸引注意
- 用淺白的話解釋新聞重點，避免艱深術語
- 可以用 3~5 個 emoji
- 不要開政治、宗教、族群相關的玩笑""",
    "image_style": "playful colorful flat illustration, friendly cartoon robots, bright pastel colors",
    "post_day_offset": 1,
    "post_time": "12:00",
}

COPY_STYLE_3 = {
    "name": "行動導向",
    "instructions": """語氣積極、有號召力，重點放在「讀者可以怎麼做」。
- 開頭一句話說出讀者的痛點或機會
- 給 3 個具體可行的建議或應用方式
- 結尾有明確的行動呼籲（例如留言分享、收藏、追蹤）
- 不要誇大效果，不要保證結果""",
    "image_style": "bold modern poster style, vibrant gradient background, dynamic upward arrows and light trails",
    "post_day_offset": 1,
    "post_time": "20:00",
}

# 所有版本共用的寫文案指示。{style_name}、{style_instructions}、{research}、{rss} 會被替換
COPY_PROMPT = """你是社群行銷文案寫手。根據下面的研究筆記與 RSS 新聞，寫一篇 Facebook / Instagram 貼文。

【版本】{style_name}
【風格與注意事項】
{style_instructions}

【共同規則】
- 全文使用繁體中文（台灣用語）；專有名詞、產品名可保留英文
- 只能使用研究筆記與 RSS 裡的事實，不可以捏造數字、引言或事件
- 挑最相關的一則新聞當主軸，不要把所有新聞都塞進去
- 150~300 字
- 最後一行放 3~5 個 hashtag
- 不要使用 markdown 語法（不要 **粗體**、不要 [連結](網址)），不要放網址
- 只輸出貼文內容本身

【研究筆記】
{research}

【RSS 新聞】
{rss}"""

# ─── 圖片 ────────────────────────────────────────────────────
# 根據文案產生「圖片 prompt」的指示。{copy}、{image_style} 會被替換。
# 請模型用英文寫，是因為產圖模型用英文較穩定，也比較不會在圖上出現亂碼中文字。
IMAGE_PROMPT_TEMPLATE = """Write one image-generation prompt (in English, 2-4 sentences) for an
illustration that accompanies the social media post below.
- Visual style: {image_style}
- Capture the post's main idea with a simple, clear scene or metaphor
- Output only the prompt itself

Post:
{copy}"""

# 一定會加在每個圖片 prompt 最後的規則
IMAGE_PROMPT_SUFFIX = (
    "Absolutely no text, letters, numbers, captions or logos in the image. "
    "No recognizable real people or real brands."
)

# ─── OpenAI 模型 ─────────────────────────────────────────────
TEXT_MODEL = "gpt-5"          # 需支援 web_search 工具
IMAGE_MODEL = "gpt-image-1"
IMAGE_SIZE = "1024x1024"      # IG 需要 4:5 ~ 1.91:1，正方形最保險

# ─── 發佈 ────────────────────────────────────────────────────
PUBLISH_PLATFORMS = ["facebook", "instagram"]   # 可改成只留其中一個

# post_time 距離現在不到幾分鐘就不排程（時間已過或太趕），會在 Sheet 的 error 欄提示
MIN_LEAD_MINUTES = 10

# ─── Google Sheet ────────────────────────────────────────────
SHEET_TAB = "posts"      # 放文案的分頁（不存在會自動建立）
STATE_TAB = "_state"     # 記錄每天是否跑過（不存在會自動建立，不要手動改）

# ─── Cloudinary（放圖片，Buffer 只收公開網址）────────────────
CLOUDINARY_FOLDER = "autopost"
