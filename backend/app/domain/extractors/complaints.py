import re

PATTERNS = [
    r"\bno\s+answer\b", r"\bnobody\s+answered\b", r"\bno\s+one\s+answered\b",
    r"\bnever\s+(?:called|heard)\s+back\b", r"\bleft\s+(?:a\s+)?(?:two\s+)?voicemails?\b",
    r"\bcalled\s+\w+\s+times\b", r"\bcouldn'?t\s+(?:get|reach)\b",
    r"\bwent\s+to\s+voicemail\b", r"\bdidn'?t\s+(?:answer|call\s+back)\b",
]
_RE = re.compile("|".join(PATTERNS), re.IGNORECASE)


def count_missed_call_complaints(snippets: list[str]) -> tuple[int, list[str]]:
    """Keyword matching, deliberately not an LLM in v1. Precision must be
    measured against real reviews before deciding an LLM pass is warranted
    (spec section 14)."""
    quotes = [s for s in snippets if s and _RE.search(s)]
    return len(quotes), quotes
