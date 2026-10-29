"""Turning Gmail API message payloads into plain text the parsers can search."""

import base64
import re

from bs4 import BeautifulSoup

_FORWARD_MARKERS = (
    "---------- Forwarded message ---------",
    "---------- Forwarded message ----------",
    "Begin forwarded message:",
)


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def normalize_text(text: str) -> str:
    """Collapse runs of spaces and drop blank lines so labels sit next to their values."""
    lines = (re.sub(r"[ \t\xa0​]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    return normalize_text(soup.get_text("\n"))


def extract_bodies(payload: dict) -> list[str]:
    """Walk a Gmail payload tree and return its text bodies.

    text/plain parts come first, then text/html parts converted to text. Both
    are returned because many receipts ship a stub plain part ("view this email
    in your browser") alongside the real HTML.
    """
    plain: list[str] = []
    html: list[str] = []

    def walk(node: dict) -> None:
        mime = node.get("mimeType", "")
        data = (node.get("body") or {}).get("data")
        if data:
            if mime == "text/plain":
                plain.append(normalize_text(_decode(data)))
            elif mime == "text/html":
                html.append(html_to_text(_decode(data)))
        for child in node.get("parts") or []:
            walk(child)

    walk(payload)
    return [body for body in plain + html if body]


def pdf_parts(payload: dict) -> list[dict]:
    """Every PDF attachment part in a Gmail payload tree."""
    found: list[dict] = []

    def walk(node: dict) -> None:
        filename = node.get("filename") or ""
        if filename.lower().endswith(".pdf") or node.get("mimeType") == "application/pdf":
            body = node.get("body") or {}
            if body.get("attachmentId") or body.get("data"):
                found.append(node)
        for child in node.get("parts") or []:
            walk(child)

    walk(payload)
    return found


def strip_forward_wrapper(body: str) -> str:
    """If body is a forwarded email, return only the original quoted content."""
    for marker in _FORWARD_MARKERS:
        idx = body.find(marker)
        if idx != -1:
            return body[idx + len(marker):]
    return body
