from __future__ import annotations

import hashlib
import re
from typing import Iterable


def chunk_text(content: str, *, max_chars: int = 900) -> list[dict[str, object]]:
    text = (content or "").strip()
    if not text:
        return []
    blocks = _split_blocks(text)
    chunks: list[dict[str, object]] = []
    current_heading = ""
    buffer: list[str] = []
    chunk_index = 1
    for block in blocks:
        heading, body = block
        candidate = "\n".join(filter(None, [current_heading, *buffer, body])).strip()
        if heading:
            if buffer:
                chunks.append(_make_chunk(chunk_index, current_heading, "\n".join(buffer), max_chars))
                chunk_index += 1
                buffer = []
            current_heading = heading
            if body:
                buffer.append(body)
            continue
        if len(candidate) > max_chars and buffer:
            chunks.append(_make_chunk(chunk_index, current_heading, "\n".join(buffer), max_chars))
            chunk_index += 1
            buffer = [body] if body else []
        else:
            if body:
                buffer.append(body)
    if buffer:
        chunks.append(_make_chunk(chunk_index, current_heading, "\n".join(buffer), max_chars))
    return chunks


def _split_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_body:
                current_body.append("")
            continue
        heading_match = re.match(r"^(#{1,6}\s+.+)$", stripped)
        if heading_match:
            if current_heading or current_body:
                blocks.append((current_heading, "\n".join(current_body).strip()))
            current_heading = heading_match.group(1).lstrip("#").strip()
            current_body = []
            continue
        current_body.append(stripped)
    if current_heading or current_body:
        blocks.append((current_heading, "\n".join(current_body).strip()))
    return [(heading, body) for heading, body in blocks if heading or body]


def _make_chunk(index: int, heading: str, content: str, max_chars: int) -> dict[str, object]:
    normalized = " ".join((content or "").split())
    content = normalized[:max_chars]
    return {
        "chunk_index": index,
        "heading": heading or f"片段 {index}",
        "content": content,
        "token_estimate": max(1, len(content) // 4),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "metadata": {"heading": heading or "", "length": len(content)},
    }
