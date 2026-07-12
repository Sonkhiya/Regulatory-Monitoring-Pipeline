"""HTML parsing with boilerplate stripping and title/body extraction."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

logger = logging.getLogger(__name__)

# Default CSS selectors for boilerplate elements to strip
DEFAULT_STRIP_SELECTORS = [
    "nav",
    "footer",
    "script",
    "style",
    "header",
    "aside",
    '[role="navigation"]',
    '[role="banner"]',
    '[role="contentinfo"]',
    ".sidebar",
    ".nav",
    ".navigation",
    ".footer",
    ".header",
    ".menu",
    ".breadcrumb",
    ".social",
    ".share",
    ".related",
    ".recommended",
    ".advertisement",
    ".ads",
    "#sidebar",
    "#nav",
    "#navigation",
    "#footer",
    "#header",
]


class HTMLParser:
    """Extracts title and body text from HTML, stripping boilerplate."""

    def __init__(self, strip_selectors: list[str] | None = None) -> None:
        """
        Initialize HTML parser.

        Args:
            strip_selectors: CSS selectors for elements to remove before extraction.
                           Defaults to DEFAULT_STRIP_SELECTORS if None.
        """
        self.strip_selectors = (
            strip_selectors if strip_selectors is not None else DEFAULT_STRIP_SELECTORS
        )

    def parse(self, html: str, url: str = "") -> tuple[str, str]:
        """
        Parse HTML and extract title and body text.

        Args:
            html: Raw HTML string.
            url: Source URL (used as fallback title).

        Returns:
            Tuple of (title, body_text).
        """
        if not html or not html.strip():
            logger.debug("Empty HTML input, returning defaults")
            return "Untitled", ""

        soup = BeautifulSoup(html, "lxml")

        # Extract title
        title = self._extract_title(soup, url)

        # Strip boilerplate
        self._strip_boilerplate(soup)

        # Extract body text
        body_text = self._extract_body(soup)

        return title, body_text

    def parse_bytes(self, content_bytes: bytes, url: str) -> tuple[str, str]:
        """
        Parse HTML from bytes, detecting encoding.

        Args:
            content_bytes: Raw HTML bytes.
            url: Source URL.

        Returns:
            Tuple of (title, body_text).
        """
        # Let BeautifulSoup handle encoding detection
        html = content_bytes.decode("utf-8", errors="replace")
        return self.parse(html, url)

    def extract_text(self, element: Tag | BeautifulSoup) -> str:
        """
        Utility to get clean text from a BeautifulSoup node.

        Args:
            element: BeautifulSoup object or Tag node.

        Returns:
            Cleaned text content.
        """
        # Get text with some whitespace normalization
        text = element.get_text(separator=" ", strip=True)
        # Collapse multiple whitespace
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        """Extract page title from various sources in priority order."""
        # 1. <title> tag
        title_tag = soup.find("title")
        if title_tag and isinstance(title_tag, Tag):
            # title_tag.string can be NavigableString or None
            title_str = title_tag.string
            if title_str:
                title = str(title_str).strip()
                if title:
                    return title

        # 2. First <h1>
        h1 = soup.find("h1")
        if h1 and isinstance(h1, Tag):
            title = self.extract_text(h1)
            if title:
                return title

        # 3. Open Graph title
        og_title = soup.find("meta", property="og:title")
        if og_title and isinstance(og_title, Tag):
            content = og_title.get("content")
            if content:
                return str(content).strip()

        # 4. Twitter card title
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter_title and isinstance(twitter_title, Tag):
            content = twitter_title.get("content")
            if content:
                return str(content).strip()

        # 5. First heading (h2, h3)
        for heading in soup.find_all(["h2", "h3"]):
            if isinstance(heading, Tag):
                title = self.extract_text(heading)
                if title:
                    return title

        # 6. Fallback to URL path
        if url:
            path = urlparse(url).path
            if path:
                # Use last path segment
                last_segment = path.strip("/").split("/")[-1]
                if last_segment:
                    return last_segment.replace("-", " ").replace("_", " ").title()

        return "Untitled"

    def _strip_boilerplate(self, soup: BeautifulSoup) -> None:
        """Remove boilerplate elements from the soup in place."""
        for selector in self.strip_selectors:
            for element in soup.select(selector):
                if isinstance(element, Tag):
                    element.decompose()

        # Also remove common empty/div wrapper elements that are likely boilerplate
        for element in soup.find_all(["div", "section"]):
            if not isinstance(element, Tag):
                continue
            # Check if element has very little text content relative to its HTML size
            # or if it has classes/IDs suggesting it's layout chrome
            classes = element.get("class", [])
            elem_id = element.get("id", "")
            class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
            identifier = f"{class_str} {elem_id}".lower()

            # Skip if it looks like main content
            if any(
                keyword in identifier
                for keyword in [
                    "main",
                    "content",
                    "article",
                    "post",
                    "body",
                    "document",
                    "text",
                    "detail",
                    "notification",
                    "circular",
                    "press",
                ]
            ):
                continue

    def _extract_body(self, soup: BeautifulSoup) -> str:
        """
        Extract main body text from HTML.

        Priority order:
        1. <main> element
        2. <article> element
        3. Element with role="main"
        4. <body> (after stripping)
        """
        # Try semantic main content containers
        main_selectors = [
            "main",
            "article",
            '[role="main"]',
            ".main-content",
            ".content",
            ".article",
            ".post",
            ".document",
            "#main",
            "#content",
            "#article",
        ]

        for selector in main_selectors:
            element = soup.select_one(selector)
            if element and isinstance(element, Tag):
                text = self.extract_text(element)
                if text and len(text) > 50:  # Minimum viable content
                    return text

        # Fallback: body text after stripping
        body = soup.find("body")
        if body and isinstance(body, Tag):
            text = self.extract_text(body)
            if text:
                return text

        # Last resort: entire document
        text = self.extract_text(soup)
        if text:
            logger.warning(
                "Extracted body from full document (no semantic container found), length=%d",
                len(text),
            )
            return text

        return ""


def parse_html(
    html: str, url: str = "", strip_selectors: list[str] | None = None
) -> tuple[str, str]:
    """
    Convenience function for one-off HTML parsing.

    Args:
        html: Raw HTML string.
        url: Source URL for fallback title.
        strip_selectors: Optional custom strip selectors.

    Returns:
        Tuple of (title, body_text).
    """
    parser = HTMLParser(strip_selectors=strip_selectors)
    return parser.parse(html, url)
