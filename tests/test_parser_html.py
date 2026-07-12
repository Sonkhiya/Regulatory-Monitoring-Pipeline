"""Tests for HTML parser."""

from __future__ import annotations

from pathlib import Path

from regmon.parser.html_parser import HTMLParser, parse_html

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "parser"


class TestHTMLParser:
    """Tests for HTMLParser class."""

    def test_parse_empty_html(self) -> None:
        """Test parsing empty HTML."""
        parser = HTMLParser()
        title, body = parser.parse("", "https://example.com")
        assert title == "Untitled"
        assert body == ""

    def test_parse_bytes(self) -> None:
        """Test parsing HTML from bytes."""
        parser = HTMLParser()
        html_bytes = b"<html><head><title>Test</title></head><body>Content</body></html>"
        title, body = parser.parse_bytes(html_bytes, "https://example.com")
        assert title == "Test"
        assert "Content" in body

    def test_parse_bytes_utf8_encoding(self) -> None:
        """Test parsing UTF-8 encoded bytes."""
        parser = HTMLParser()
        html_bytes = "é à ü".encode()
        html_bytes = b"<html><body>" + html_bytes + b"</body></html>"
        _title, body = parser.parse_bytes(html_bytes, "https://example.com")
        assert "é" in body or "à" in body or "ü" in body

    def test_extract_title_from_title_tag(self) -> None:
        """Test title extraction from <title> tag."""
        parser = HTMLParser()
        html = "<html><head><title>Test Title</title></head><body>Body</body></html>"
        title, _ = parser.parse(html, "https://example.com")
        assert title == "Test Title"

    def test_extract_title_from_h1(self) -> None:
        """Test title extraction from first <h1> when no title tag."""
        parser = HTMLParser()
        html = "<html><body><h1>H1 Title</h1><p>Body</p></body></html>"
        title, _ = parser.parse(html, "https://example.com")
        assert title == "H1 Title"

    def test_extract_title_from_og_title(self) -> None:
        """Test title extraction from og:title meta tag."""
        parser = HTMLParser()
        html = (
            '<html><head><meta property="og:title" content="OG Title">'
            "</head><body>Body</body></html>"
        )
        title, _ = parser.parse(html, "https://example.com")
        assert title == "OG Title"

    def test_extract_title_from_twitter_title(self) -> None:
        """Test title extraction from twitter:title meta tag."""
        parser = HTMLParser()
        html = (
            '<html><head><meta name="twitter:title" content="Twitter Title">'
            "</head><body>Body</body></html>"
        )
        title, _ = parser.parse(html, "https://example.com")
        assert title == "Twitter Title"

    def test_extract_title_from_h2(self) -> None:
        """Test title extraction from h2 when no h1."""
        parser = HTMLParser()
        html = "<html><body><h2>H2 Title</h2><p>Body</p></body></html>"
        title, _ = parser.parse(html, "https://example.com")
        assert title == "H2 Title"

    def test_extract_title_from_url_fallback(self) -> None:
        """Test title fallback to URL path."""
        parser = HTMLParser()
        html = "<html><body><p>No title here</p></body></html>"
        title, _ = parser.parse(html, "https://example.com/path/to/document-title")
        assert "Document Title" in title or "document-title" in title

    def test_extract_title_untitled_fallback(self) -> None:
        """Test title fallback to 'Untitled' when no URL."""
        parser = HTMLParser()
        html = "<html><body><p>No title</p></body></html>"
        title, _ = parser.parse(html, "")
        assert title == "Untitled"

    def test_strip_boilerplate_elements(self) -> None:
        """Test boilerplate elements are stripped."""
        parser = HTMLParser()
        html = """
        <html>
            <body>
                <nav>Navigation</nav>
                <header>Header</header>
                <main>Main content</main>
                <footer>Footer</footer>
                <script>alert('xss')</script>
                <style>body { color: red; }</style>
            </body>
        </html>
        """
        _, body = parser.parse(html, "https://example.com")
        assert "Navigation" not in body
        assert "Header" not in body
        assert "Footer" not in body
        assert "alert" not in body
        assert "color: red" not in body
        assert "Main content" in body

    def test_custom_strip_selectors(self) -> None:
        """Test custom strip selectors override defaults."""
        parser = HTMLParser(strip_selectors=[".custom-boilerplate"])
        html = """
        <html>
            <body>
                <div class="custom-boilerplate">Remove me</div>
                <main>Keep me</main>
            </body>
        </html>
        """
        _, body = parser.parse(html, "https://example.com")
        assert "Remove me" not in body
        assert "Keep me" in body

    def test_extract_body_from_main(self) -> None:
        """Test body extraction from <main> element."""
        parser = HTMLParser()
        html = (
            "<html><body><nav>Nav</nav><main>Main content here</main>"
            "<footer>Footer</footer></body></html>"
        )
        _, body = parser.parse(html, "https://example.com")
        assert "Main content here" in body
        assert "Nav" not in body
        assert "Footer" not in body

    def test_extract_body_from_article(self) -> None:
        """Test body extraction from <article> element."""
        parser = HTMLParser()
        html = "<html><body><article>Article content</article></body></html>"
        _, body = parser.parse(html, "https://example.com")
        assert "Article content" in body

    def test_extract_body_from_role_main(self) -> None:
        """Test body extraction from element with role=main."""
        parser = HTMLParser()
        html = '<html><body><div role="main">Role main content</div></body></html>'
        _, body = parser.parse(html, "https://example.com")
        assert "Role main content" in body

    def test_extract_body_fallback_to_body(self) -> None:
        """Test body extraction falls back to <body> after stripping."""
        parser = HTMLParser()
        html = "<html><body><p>Body content</p></body></html>"
        _, body = parser.parse(html, "https://example.com")
        assert "Body content" in body

    def test_extract_body_last_resort_full_document(self) -> None:
        """Test last resort extraction from full document."""
        parser = HTMLParser()
        html = "<html><p>Direct content</p></html>"
        _, body = parser.parse(html, "https://example.com")
        assert "Direct content" in body

    def test_extract_text_normalization(self) -> None:
        """Test text normalization (whitespace collapsing)."""
        parser = HTMLParser()
        html = "<html><body><p>  Multiple    spaces   and\nnewlines\t</p></body></html>"
        _, body = parser.parse(html, "https://example.com")
        assert "Multiple spaces and newlines" in body

    def test_rbi_notification_fixture(self) -> None:
        """Test parsing RBI notification HTML fixture."""
        fixture_path = FIXTURES_DIR / "rbi_notification.html"
        if fixture_path.exists():
            html = fixture_path.read_text(encoding="utf-8")
            parser = HTMLParser()
            title, body = parser.parse(html, "https://rbi.org.in/notification.html")
            assert "Master Direction" in title or "Investment Portfolio" in title
            assert "DBR.No.BP.BC.45" in body
            assert "15 January 2024" in body
            assert "Classification" in body

    def test_preserves_main_content(self) -> None:
        """Test main content is preserved while boilerplate removed."""
        parser = HTMLParser()
        html = """
        <html>
            <body>
                <div class="sidebar">Sidebar</div>
                <div class="content">
                    <h1>Main Article</h1>
                    <p>Important content here</p>
                </div>
                <div class="footer">Footer</div>
            </body>
        </html>
        """
        _, body = parser.parse(html, "https://example.com")
        assert "Main Article" in body
        assert "Important content" in body

    def test_minimum_content_threshold(self) -> None:
        """Test minimum content threshold for main container selection."""
        parser = HTMLParser()
        html = """
        <html>
            <body>
                <main><p>X</p></main>  <!-- Too short -->
                <article>
                    <p>
                        This is a longer article with sufficient content to be selected
                    </p>
                </article>
            </body>
        </html>
        """
        _, body = parser.parse(html, "https://example.com")
        # Should pick article over main due to minimum length
        assert "longer article" in body


class TestParseHtmlConvenience:
    """Tests for parse_html convenience function."""

    def test_parse_html_function(self) -> None:
        """Test parse_html convenience function."""
        html = "<html><head><title>Test</title></head><body>Content</body></html>"
        title, body = parse_html(html, "https://example.com")
        assert title == "Test"
        assert "Content" in body

    def test_parse_html_with_custom_selectors(self) -> None:
        """Test parse_html with custom strip selectors."""
        html = "<html><body><div class='custom'>Remove</div><p>Keep</p></body></html>"
        _title, body = parse_html(html, "https://example.com", strip_selectors=[".custom"])
        assert "Remove" not in body
        assert "Keep" in body
