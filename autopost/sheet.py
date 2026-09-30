"""Google Sheet storage: the posts tab (one row per copy) and a small state tab."""

import json
import re
from pathlib import Path

import gspread
from gspread.utils import ValueRenderOption, rowcol_to_a1

import config
from .common import BASE_DIR, env

COLUMNS = [
    "id",               # 例如 2026-10-01-1
    "created_at",       # 產生時間
    "keywords",
    "version",          # 文案版本名稱（COPY_STYLE_x["name"]）
    "copy",             # 行銷文案（FB / IG 共用）
    "image_preview",    # =IMAGE() 預覽
    "image_url",        # 公開圖片網址（Buffer 用這個）
    "image_prompt",
    "sources",          # 參考來源網址
    "post_time",        # 發文時間 YYYY-MM-DD HH:MM（可手動修改）
    "approved",         # ☑ 使用者確認：勾選才會發
    "status",           # PENDING → SCHEDULED
    "buffer_facebook_id",
    "buffer_instagram_id",
    "scheduled_at",     # 成功排程到 Buffer 的時間
    "error",            # 最近一次失敗原因
]
STATE_COLUMNS = ["task", "last_success_date", "attempt_date", "attempts", "last_run_at", "message"]


def _credentials():
    """GOOGLE_SERVICE_ACCOUNT_JSON may hold the JSON itself (Render) or a path to the file (local)."""
    raw = env("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw.startswith("{"):
        return json.loads(raw)
    path = Path(raw)
    return json.loads((path if path.is_absolute() else BASE_DIR / path).read_text())


class Sheet:
    def __init__(self):
        client = gspread.service_account_from_dict(_credentials())
        self.book = client.open_by_key(env("GOOGLE_SHEET_ID"))
        self.posts = self._tab(config.SHEET_TAB, COLUMNS)
        self.state = self._tab(config.STATE_TAB, STATE_COLUMNS)

    def _tab(self, title, columns):
        try:
            ws = self.book.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.book.add_worksheet(title=title, rows=100, cols=len(columns))
        header = ws.row_values(1)
        if not header:
            ws.update([columns], "A1")
            ws.freeze(rows=1)
        elif header[:len(columns)] != columns:
            raise RuntimeError(f"sheet tab {title!r} header doesn't match; expected {columns}")
        return ws

    # ── posts ──
    def append_posts(self, posts):
        """Append dicts keyed by COLUMNS; adds the image preview and the approved checkbox."""
        rows = [[p.get(c, "") for c in COLUMNS] for p in posts]
        for row in rows:
            row[COLUMNS.index("approved")] = False
        result = self.posts.append_rows(rows, value_input_option="RAW", table_range="A1")
        # updatedRange looks like "posts!A5:P7"
        start = int(re.search(r"![A-Z]+(\d+)", result["updates"]["updatedRange"]).group(1))
        end = start + len(rows) - 1

        preview_col = COLUMNS.index("image_preview") + 1
        self.posts.batch_update(
            [{"range": rowcol_to_a1(start + i, preview_col),
              "values": [[f'=IMAGE("{p["image_url"]}")']]} for i, p in enumerate(posts)],
            value_input_option="USER_ENTERED")

        approved_col = COLUMNS.index("approved")
        self.book.batch_update({"requests": [{"setDataValidation": {
            "range": {"sheetId": self.posts.id, "startRowIndex": start - 1, "endRowIndex": end,
                      "startColumnIndex": approved_col, "endColumnIndex": approved_col + 1},
            "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True},
        }}]})
        return start, end

    def list_posts(self):
        """Return [(row_number, dict)] for every data row."""
        # Unformatted: checkboxes come back as True/False and hand-edited dates as serial
        # numbers, independent of the sheet's locale formatting.
        records = self.posts.get_all_records(
            expected_headers=COLUMNS, numericise_ignore=["all"],
            value_render_option=ValueRenderOption.unformatted)
        return [(i + 2, r) for i, r in enumerate(records)]

    def update_post(self, row_number, values):
        self.posts.batch_update(
            [{"range": rowcol_to_a1(row_number, COLUMNS.index(k) + 1), "values": [[v]]}
             for k, v in values.items()],
            value_input_option="RAW")

    # ── state ──
    def _state_rows(self):
        records = self.state.get_all_records(expected_headers=STATE_COLUMNS,
                                             numericise_ignore=["all"])
        return {r["task"]: (i + 2, r) for i, r in enumerate(records)}

    def get_state(self, task):
        found = self._state_rows().get(task)
        return found[1] if found else {c: "" for c in STATE_COLUMNS}

    def set_state(self, task, values):
        values = {**values, "task": task}
        found = self._state_rows().get(task)
        if found:
            row_number, current = found
            row = [values.get(c, current.get(c, "")) for c in STATE_COLUMNS]
            self.state.update([row], f"A{row_number}", value_input_option="RAW")
        else:
            self.state.append_rows([[values.get(c, "") for c in STATE_COLUMNS]],
                                   value_input_option="RAW", table_range="A1")
