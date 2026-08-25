from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from .exceptions import BrowserExtractionError
from .sanitizer import excerpt, normalize_whitespace
from .schemas import BrowserFieldSpec, HtmlDocument, HtmlNode


IGNORED_TAGS = {"script", "style", "noscript"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _HTMLDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document", {}, [])
        self.stack: list[HtmlNode] = [self.root]
        self.hidden_stack: list[bool] = [False]
        self.title_chunks: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_start(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_start(tag, attrs, self_closing=True)

    def _handle_start(self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool) -> None:
        hidden = self.hidden_stack[-1]
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        style = attr_map.get("style", "").lower()
        hidden = hidden or tag.lower() in IGNORED_TAGS or "hidden" in attr_map or "display:none" in style or "visibility:hidden" in style
        self.hidden_stack.append(hidden)
        if hidden:
            return
        node = HtmlNode(tag.lower(), attr_map, [])
        self.stack[-1].children.append(node)
        if tag.lower() == "title":
            self._in_title = True
        if not self_closing and tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        hidden = self.hidden_stack.pop() if self.hidden_stack else False
        if hidden:
            if tag.lower() == "title":
                self._in_title = False
            return
        while len(self.stack) > 1:
            node = self.stack.pop()
            if node.tag == tag.lower():
                break
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self.hidden_stack[-1]:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_chunks.append(text)
        self.stack[-1].children.append(text)


def parse_html_document(source: str) -> HtmlDocument:
    parser = _HTMLDocumentParser()
    parser.feed(source)
    parser.close()
    title = normalize_whitespace(" ".join(parser.title_chunks)) or None
    return HtmlDocument(root=parser.root, title=title)


def extract_visible_text(document: HtmlDocument, limit: int = 4000) -> str:
    body = find_first(document.root, "body")
    if body is None:
        body = document.root
    text = collect_text(body)
    return excerpt(text, limit=limit)


def extract_title(document: HtmlDocument) -> str | None:
    if document.title:
        return document.title
    title_node = find_first(document.root, "title")
    if not title_node:
        return None
    return excerpt(collect_text(title_node), limit=500) or None


def extract_structured_fields(document: HtmlDocument, source_text: str, content_type: str, payload: Any) -> dict[str, Any]:
    fields = parse_field_specs(payload)
    if not fields:
        return {}
    output: dict[str, Any] = {}
    json_data: Any = None
    html_source = content_type.lower().startswith("text/html") or "html" in content_type.lower()
    json_source = "json" in content_type.lower()
    if json_source:
        try:
            json_data = json.loads(source_text)
        except Exception as exc:
            raise BrowserExtractionError("JSON 内容解析失败", "PARSE_ERROR") from exc
    for field in fields:
        output[field.name] = extract_field(document, field, json_data=json_data, html_source=html_source, json_source=json_source)
    return output


def parse_field_specs(payload: Any) -> list[BrowserFieldSpec]:
    raw = []
    if isinstance(payload, dict):
        raw = payload.get("extract_fields") or payload.get("fields") or payload.get("selectors") or []
    elif isinstance(payload, list):
        raw = payload
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    specs: list[BrowserFieldSpec] = []
    for item in raw:
        try:
            specs.append(BrowserFieldSpec.from_value(item))
        except Exception:
            continue
    return specs


def extract_field(document: HtmlDocument, field: BrowserFieldSpec, *, json_data: Any, html_source: bool, json_source: bool) -> Any:
    kind = field.kind.lower()
    if field.json_path or kind == "json":
        if not json_source and json_data is None:
            return None
        return extract_json_path(json_data, field.json_path or field.selector or field.name)
    if kind == "title":
        return extract_title(document)
    if kind == "body":
        return extract_visible_text(document)
    if kind == "meta":
        selector = field.selector or "meta"
        nodes = select_nodes(document.root, selector)
        return extract_node_values(nodes, field.attribute or "content", field.multiple)
    selector = field.selector or field.name
    nodes = select_nodes(document.root, selector) if html_source else []
    if not nodes and not html_source:
        return None
    if field.attribute:
        return extract_node_values(nodes, field.attribute, field.multiple)
    values = [collect_text(node) for node in nodes]
    if field.multiple:
        return [excerpt(value, 1000) for value in values]
    return excerpt(values[0], 1000) if values else None


def extract_json_path(value: Any, path: str | None) -> Any:
    if value is None:
        return None
    if not path:
        return value
    current = value
    for token in path.split("."):
        token = token.strip()
        if not token:
            continue
        if isinstance(current, list) and token.isdigit():
            index = int(token)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        if isinstance(current, dict):
            current = current.get(token)
            continue
        return None
    if isinstance(current, (dict, list)):
        return current
    if isinstance(current, str):
        return excerpt(current, 1000)
    return current


def collect_text(node: HtmlNode) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, HtmlNode):
            if child.tag in IGNORED_TAGS:
                continue
            parts.append(collect_text(child))
        else:
            text = normalize_whitespace(str(child))
            if text:
                parts.append(text)
    return normalize_whitespace(" ".join(part for part in parts if part))


def extract_node_values(nodes: list[HtmlNode], attribute: str, multiple: bool) -> Any:
    values: list[Any] = []
    for node in nodes:
        if attribute == "text":
            values.append(excerpt(collect_text(node), 1000))
            continue
        value = node.attrs.get(attribute.lower())
        if value is not None:
            values.append(excerpt(str(value), 1000))
    if multiple:
        return values
    return values[0] if values else None


def select_nodes(root: HtmlNode, selector: str) -> list[HtmlNode]:
    selector = selector.strip()
    if not selector:
        return []
    parts = [part for part in selector.split() if part]
    if not parts:
        return []
    current: list[HtmlNode] = [root]
    for part in parts:
        matches: list[HtmlNode] = []
        for node in current:
            matches.extend(find_descendants(node, part))
        current = matches
    return current


def find_first(root: HtmlNode, selector: str) -> HtmlNode | None:
    nodes = select_nodes(root, selector)
    return nodes[0] if nodes else None


def find_descendants(node: HtmlNode, selector: str) -> list[HtmlNode]:
    matches: list[HtmlNode] = []
    for child in node.children:
        if isinstance(child, HtmlNode):
            if matches_simple_selector(child, selector):
                matches.append(child)
            matches.extend(find_descendants(child, selector))
    return matches


def matches_simple_selector(node: HtmlNode, selector: str) -> bool:
    tag, node_id, classes, attrs = parse_simple_selector(selector)
    if tag and node.tag != tag:
        return False
    if node_id and node.attrs.get("id") != node_id:
        return False
    if classes:
        node_classes = set(filter(None, re.split(r"\s+", node.attrs.get("class", "").strip())))
        if not all(cls in node_classes for cls in classes):
            return False
    for key, expected in attrs.items():
        if node.attrs.get(key) != expected:
            return False
    return True


def parse_simple_selector(selector: str) -> tuple[str | None, str | None, list[str], dict[str, str]]:
    tag = None
    node_id = None
    classes: list[str] = []
    attrs: dict[str, str] = {}
    remaining = selector.strip()
    attr_pattern = re.compile(r"\[([^\]=]+)(?:=([\"']?)(.*?)\2)?\]")
    for match in attr_pattern.finditer(remaining):
        attrs[match.group(1).strip().lower()] = match.group(3).strip()
    remaining = attr_pattern.sub("", remaining)
    if "#" in remaining:
        before, after = remaining.split("#", 1)
        remaining = before
        if "." in after:
            node_id, class_part = after.split(".", 1)
            classes.extend([part for part in class_part.split(".") if part])
        else:
            node_id = after
    if "." in remaining:
        before, *rest = remaining.split(".")
        if before:
            tag = before.lower()
        classes.extend([part for part in rest if part])
    elif remaining:
        tag = remaining.lower()
    return tag, node_id, classes, attrs
