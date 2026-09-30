"""post_openai.py 的設定：要改搜尋主題 / 發文時間 / 模型，只要改這個檔案。"""

# 要搜尋新聞的主題
TOPIC = "蔣萬安"

# 發文時間（依 TIMEZONE 解讀），格式 "YYYY-MM-DD HH:MM"
POST_TIME = "2026-09-30 13:27"
TIMEZONE = "Asia/Taipei"

# 程式比 POST_TIME 晚啟動時，這幾分鐘內仍會立刻補發；超過就不發
WINDOW_MINUTES = 30

# 要發到哪些平台
POST_TO_FACEBOOK = True
POST_TO_INSTAGRAM = True

# OpenAI 模型
TEXT_MODEL = "gpt-5"          # 需支援 web_search 工具
IMAGE_MODEL = "gpt-image-1"
IMAGE_SIZE = "1024x1024"      # IG 需要 4:5 ~ 1.91:1，正方形最保險

# 加在貼文最後的 hashtag。第一個 hashtag 也用來判斷「這篇是否已經發過」，避免重啟後重複發文
HASHTAGS = ["#蔣萬安新聞摘要", "#台北市", "#新聞"]

# 給模型的指示。{topic} 會被換成 TOPIC
SUMMARY_PROMPT = """請用網路搜尋「{topic}」最近 24~48 小時內的最新新聞，挑出 3 則最重要的，
用繁體中文寫成一篇社群貼文：
- 第一行是吸引人的標題（可加 1 個 emoji）
- 每則新聞 1~2 句重點摘要，用「・」開頭
- 保持中立、只陳述事實，不要加入個人評論或政治立場
- 最後一行寫「資料來源：」加上媒體的中文名稱（不要放網址）
- 全文 400 字以內，不要加 hashtag
- 全文（包含標題、摘要、媒體名稱）一律只用繁體中文，不要出現任何英文；即使參考的是英文報導，
  也要翻譯成中文，英文媒體請寫中文名稱（例如 Taipei Times 寫「台北時報」、NOWnews 寫「今日新聞」）
只輸出貼文內容本身。"""

# 產生的貼文只要還有英文單字，就會再請模型翻成繁體中文
TRANSLATE_PROMPT = """請把以下社群貼文中的所有英文翻譯成繁體中文（台灣用語），媒體名稱改用中文名稱，
保留原本的排版與 emoji，只輸出修改後的貼文：

{text}"""

# 產生圖片分兩步：先請 TEXT_MODEL 根據摘要寫一段英文畫面描述（{summary} 會被換成摘要），
# 再把描述套進 IMAGE_PROMPT（{scene}）給 IMAGE_MODEL。
# 用英文、且不把中文摘要直接丟給產圖模型，是為了避免圖上出現亂碼中文字。
# 為避免誤導，圖片不畫真實人物的臉或肖像。
IMAGE_SCENE_PROMPT = """Read this Taipei city news summary and describe, in English and in at most
two sentences, one simple visual scene that illustrates its overall theme.
Do not describe any real person, faces, text, signs, numbers or logos.

{summary}"""

IMAGE_PROMPT = """Clean flat vector illustration for a social media post, bright friendly colors,
Taipei city landmarks (Taipei 101, MRT trains, parks) in the background.
Scene: {scene}
Absolutely no text, letters, numbers, captions, signs or logos anywhere in the image.
No recognizable real people; any people are small, generic and faceless."""

# 貼文最後加的 AI 生成聲明
DISCLAIMER = "（本文由 AI 搜尋新聞後自動整理，圖片為 AI 生成示意圖）"
