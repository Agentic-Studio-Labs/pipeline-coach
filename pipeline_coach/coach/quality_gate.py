from __future__ import annotations

import re
import string

_ACTION_VERBS = {
    "schedule",
    "call",
    "email",
    "update",
    "set",
    "add",
    "review",
    "confirm",
    "check",
    "follow",
    "send",
    "ask",
    "reach",
    "arrange",
    "book",
    "create",
    "discuss",
    "escalate",
    "identify",
    "log",
    "move",
    "push",
    "remove",
    "request",
    "share",
    "verify",
    "contact",
    "prioritize",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _is_restatement(action: str, issues_text: str) -> bool:
    norm_action = _normalize(action)
    for line in issues_text.splitlines():
        candidate = _normalize(line.lstrip("- ").strip())
        if not candidate:
            continue
        if norm_action == candidate:
            return True
        action_words = set(norm_action.split())
        candidate_words = set(candidate.split())
        smaller = min(len(action_words), len(candidate_words))
        if smaller == 0:
            continue
        overlap = len(action_words & candidate_words) / smaller
        if overlap > 0.8:
            return True
    return False


def _has_action_verb(action: str) -> bool:
    words = action.split()[:3]
    for word in words:
        cleaned = word.strip(string.punctuation).lower()
        if cleaned in _ACTION_VERBS:
            return True
    return False


def validate_action(action: str | None, *, issues_text: str) -> bool:
    if not action or not action.strip():
        return False
    if _is_restatement(action, issues_text):
        return False
    if not _has_action_verb(action):
        return False
    return True
