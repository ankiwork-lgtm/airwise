"""Shared access to the static frontend files in public/."""

from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

PUBLIC = Path(__file__).resolve().parent.parent / "public"

HTML = (PUBLIC / "index.html").read_text(encoding="utf-8")
CSS = (PUBLIC / "app.css").read_text(encoding="utf-8")
JS = (PUBLIC / "app.js").read_text(encoding="utf-8")

# Everything the browser loads for the page; used for sink and string checks.
FRONTEND_TEXT = HTML + "\n" + CSS + "\n" + JS


class ParsedElement(NamedTuple):
    tag: str
    attrs: dict[str, str]


class HTMLDocument(HTMLParser):
    """Minimal stdlib html.parser helper for structural static tests."""

    def __init__(self, html: str = HTML) -> None:
        super().__init__()
        self.elements: list[ParsedElement] = []
        self.all_ids: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): v or "" for k, v in attrs}
        self.elements.append(ParsedElement(tag=tag.lower(), attrs=attr_dict))
        if "id" in attr_dict:
            self.all_ids.append(attr_dict["id"])

    def find_all(self, tag: str) -> list[ParsedElement]:
        return [el for el in self.elements if el.tag == tag.lower()]

    def find_by_id(self, elem_id: str) -> ParsedElement | None:
        for el in self.elements:
            if el.attrs.get("id") == elem_id:
                return el
        return None
