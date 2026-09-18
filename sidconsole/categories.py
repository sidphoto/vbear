"""Purpose categories, derived from skill descriptions by keyword.

This is automatic organisation, not an author claim, so every category carries
origin=derived and the matched keyword. The table is deliberately small and
visible so users can see exactly why a skill landed in a category.

Each category has:
  label   - shown in the UI
  query   - words a user might type (Chinese and English) to find it
  match   - lowercase substrings looked for in name/description/when_to_use
"""

from __future__ import annotations

import re

CATEGORIES = [
    {"id": "security", "label": "資安與防護",
     "query": ["資安", "安全", "滲透", "弱點", "漏洞", "防護", "攻擊", "駭", "security", "pentest"],
     "match": ["security", "pentest", "penetration", "vulnerab", "exploit", "firewall", "waf",
               "ddos", "threat", "attack", "資安", "滲透", "弱點"]},
    {"id": "quality", "label": "測試與審查",
     "query": ["測試", "審查", "檢查", "驗收", "除錯", "品質", "review", "test", "qa", "debug"],
     "match": ["test", " qa", "review", "verif", "audit", "lint", "debug", "quality",
               "checklist", "測試", "審查", "驗收", "稽核"]},
    {"id": "design", "label": "設計與介面",
     "query": ["設計", "介面", "品牌", "視覺", "配色", "圖示", "橫幅", "design", "ui", "ux", "logo"],
     "match": ["design", " ui", "ui/", "ux", "brand", "logo", "banner", "icon", "tailwind",
               "shadcn", "figma", "typography", "palette", "visual", "設計", "品牌"]},
    {"id": "frontend", "label": "網站與前端",
     "query": ["網站", "網頁", "前端", "頁面", "元件", "website", "frontend", "react", "next"],
     "match": ["next.js", "nextjs", "react", "frontend", "front-end", "website", "web app",
               "component", "vite", "app router", "網站", "前端"]},
    {"id": "backend", "label": "後端與部署",
     "query": ["部署", "後端", "伺服器", "上線", "資料庫", "api", "deploy", "backend", "server"],
     "match": ["deploy", "backend", " api", "server", "function", "database", "storage",
               "cache", "cdn", "ci/cd", "env", "domain", "infrastructure", "部署", "後端"]},
    {"id": "ai", "label": "AI 與代理",
     "query": ["ai", "代理", "agent", "模型", "提示詞", "llm", "mcp", "子代理", "機器人"],
     "match": ["agent", "llm", "ai sdk", "ai gateway", "model", "prompt", "mcp", "subagent",
               "claude", "gpt", "chatbot", "代理", "模型"]},
    {"id": "writing", "label": "寫作與內容",
     "query": ["寫作", "文案", "內容", "小說", "故事", "行銷", "社群", "writing", "content"],
     "match": ["writ", "content", "copy", "prose", "story", "novel", "fiction", "chapter",
               "article", "marketing", "social", "voice", "tone", "寫作", "小說", "文案"]},
    {"id": "media", "label": "影音與圖像",
     "query": ["影片", "影音", "音樂", "剪輯", "圖片", "縮圖", "youtube", "video", "image"],
     "match": ["video", "audio", "music", "youtube", "thumbnail", "ffmpeg", "image", "render",
               "tiktok", "photo", "影片", "剪輯", "音樂"]},
    {"id": "documents", "label": "文件與簡報",
     "query": ["文件", "簡報", "報告", "試算表", "pdf", "word", "excel", "ppt", "投影片"],
     "match": ["pdf", "docx", "xlsx", "pptx", "spreadsheet", "document", "slide",
               "presentation", "word ", "report", "文件", "簡報"]},
    {"id": "automation", "label": "流程與自動化",
     "query": ["自動化", "流程", "排程", "工作流", "交接", "派工", "workflow", "automation"],
     "match": ["workflow", "automat", "schedule", "cron", "loop", "pipeline", "orchestrat",
               "handoff", "routing", "自動化", "排程", "交接"]},
]


def categorize(name: str, description: str, when_to_use: str) -> list[dict]:
    text = f" {name} {description} {when_to_use} ".lower()
    text = re.sub(r"\s+", " ", text)
    out = []
    for cat in CATEGORIES:
        for kw in cat["match"]:
            if kw in text:
                out.append({"id": cat["id"], "label": cat["label"], "keyword": kw.strip(),
                            "origin": "derived"})
                break
    return out


def public_table() -> list[dict]:
    return [{"id": c["id"], "label": c["label"], "query": c["query"]} for c in CATEGORIES]
