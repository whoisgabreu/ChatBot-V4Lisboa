from __future__ import annotations


def split_message(text: str, limit: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if limit <= 0 or len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        candidates = [
            window.rfind("\n\n"),
            window.rfind("\n"),
            window.rfind(". "),
            window.rfind("! "),
            window.rfind("? "),
            window.rfind(" "),
        ]
        split_at = max(candidates)
        if split_at < limit // 2:
            split_at = limit
        chunk = remaining[:split_at].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks
