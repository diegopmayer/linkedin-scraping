from __future__ import annotations

import hashlib
import re
import unicodedata

from selectolax.lexbor import LexborHTMLParser

_PUNCT = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ", "•": " ",
})
_BLOCK_TAGS = ("p", "li", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+|\n+|\s*[•·▪●]\s*")
MIN_QUOTE_CHARS = 12


def html_to_text(html: str) -> str:
    if not html:
        return ""
    tree = LexborHTMLParser(html)
    for tag in _BLOCK_TAGS:
        for node in tree.css(tag):
            node.insert_after("\n")
    body = tree.body if tree.body is not None else tree.root
    raw = body.text(separator=" ", strip=False) if body is not None else ""
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in raw.translate(_PUNCT).splitlines())
    return "\n".join(line for line in lines if line)


def normalise(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).translate(_PUNCT)
    return re.sub(r"\s+", " ", text).strip().lower()


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part and part.strip()]


def quote_in_text(quote: str, text: str) -> bool:
    needle = normalise(quote).strip(" .\"'")
    return len(needle) >= MIN_QUOTE_CHARS and needle in normalise(text)


def text_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()
