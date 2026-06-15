from __future__ import annotations

import re
from typing import Literal

BotCategory = Literal["bot", "human", "unknown"]

BOT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"bot", re.IGNORECASE),
    re.compile(r"crawler", re.IGNORECASE),
    re.compile(r"spider", re.IGNORECASE),
    re.compile(r"slurp", re.IGNORECASE),
    re.compile(r"headless", re.IGNORECASE),
    re.compile(r"GPTBot", re.IGNORECASE),
    re.compile(r"Google-Extended", re.IGNORECASE),
    re.compile(r"CCBot", re.IGNORECASE),
    re.compile(r"ClaudeBot", re.IGNORECASE),
    re.compile(r"Bytespider", re.IGNORECASE),
    re.compile(r"facebookexternalhit", re.IGNORECASE),
    re.compile(r"bingpreview", re.IGNORECASE),
)

BOT_CATEGORY_LABELS: dict[BotCategory, str] = {
    "bot": "Bot",
    "human": "Human",
    "unknown": "Unknown",
}


def classify_user_agent(user_agent: str) -> BotCategory:
    normalized = user_agent.strip()
    if not normalized or normalized == "-":
        return "unknown"
    if any(pattern.search(normalized) for pattern in BOT_PATTERNS):
        return "bot"
    return "human"
