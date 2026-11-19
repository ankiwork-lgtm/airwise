"""Shared access to the static frontend files in public/."""

from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"

HTML = (PUBLIC / "index.html").read_text(encoding="utf-8")
CSS = (PUBLIC / "app.css").read_text(encoding="utf-8")
JS = (PUBLIC / "app.js").read_text(encoding="utf-8")

# Everything the browser loads for the page; used for sink and string checks.
FRONTEND_TEXT = HTML + "\n" + CSS + "\n" + JS
