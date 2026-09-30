"""發文設定：要改發文時間 / 內容，只要改這個檔案，commit + push 後 Render 會自動重新部署。"""

# 發文時間（依 TIMEZONE 解讀），格式 "YYYY-MM-DD HH:MM"
POST_TIME = "2026-09-30 09:05"
TIMEZONE = "Asia/Taipei"

# 程式啟動後會等到 POST_TIME 發一次文，然後就結束。
# 如果程式比 POST_TIME 晚啟動（例如部署太晚、Render 重啟），只要還在這幾分鐘內就立刻補發；
# 超過就不發。已經發過相同內容的平台會自動略過，不會重複發。
WINDOW_MINUTES = 30

# 要發到哪些平台
POST_TO_FACEBOOK = True
POST_TO_INSTAGRAM = True

# 發文內容（相對於專案根目錄）
TEXT_FILE = "assets/text.txt"
IMAGE_FILE = "assets/image.png"
