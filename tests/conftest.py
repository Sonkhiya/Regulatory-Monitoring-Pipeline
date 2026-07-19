"""Shared pytest fixtures for the regmon test suite (Phase 1 + 2).

In-memory SQLite (``sqlite+aiosqlite:///:memory:``) is handled by the engine
factory itself, which swaps in a :class:`StaticPool` so every connection shares
one database — that lets ``init_db`` (DDL on a begin connection) and the later
store/audit-log sessions all see the same tables.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from regmon.config import Settings
from regmon.db.engine import create_async_engine, init_db, session_factory
from regmon.models import RawDocument
from regmon.models.documents import ParsedDocument
from regmon.normalize import NormalizerAgent
from regmon.parser import ParserAgent

MEMORY_URL = "sqlite+aiosqlite:///:memory:"

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---- Phase 1: Database fixtures ----


@pytest.fixture
def db_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointing at the in-memory SQLite URL."""
    monkeypatch.setenv("REGMON_DB_URL", MEMORY_URL)
    from regmon.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    return Settings(db_url=MEMORY_URL)


@pytest_asyncio.fixture
async def engine(db_settings: Settings) -> AsyncEngine:
    """A shared in-memory AsyncEngine with tables initialized."""
    eng = create_async_engine(db_settings)
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessions(engine: AsyncEngine) -> async_sessionmaker:
    """A session factory bound to the shared in-memory engine."""
    return session_factory(engine)


# ---- Phase 2: Crawler fixtures ----


@pytest.fixture
def recorded_responses() -> dict[str, bytes]:
    """Load all fixture files into a URL -> content mapping."""
    responses = {}

    # RBI fixtures
    rbi_base = "https://www.rbi.org.in"
    responses[f"{rbi_base}/Scripts/NotificationUser.aspx"] = (
        FIXTURES_DIR / "rbi" / "notifications_list_page1.html"
    ).read_bytes()
    responses[f"{rbi_base}/Scripts/NotificationUser.aspx?page=2"] = b""
    responses[f"{rbi_base}/Scripts/NotificationUser.aspx?page=3"] = b""

    responses[f"{rbi_base}/Scripts/NotificationUser.aspx?Id=12345&Mode=0"] = (
        FIXTURES_DIR / "rbi" / "notification_detail.html"
    ).read_bytes()
    responses[f"{rbi_base}/Scripts/NotificationUser.aspx?Id=12346&Mode=0"] = (
        FIXTURES_DIR / "rbi" / "notification_detail.html"
    ).read_bytes()
    responses[f"{rbi_base}/Scripts/NotificationUser.aspx?Id=12347&Mode=0"] = (
        FIXTURES_DIR / "rbi" / "notification_detail.html"
    ).read_bytes()

    responses[f"{rbi_base}/Scripts/BS_PressReleaseDisplay.aspx"] = (
        FIXTURES_DIR / "rbi" / "press_list_page1.html"
    ).read_bytes()
    responses[f"{rbi_base}/Scripts/BS_PressReleaseDisplay.aspx?page=2"] = b""
    responses[f"{rbi_base}/Scripts/BS_PressReleaseDisplay.aspx?page=3"] = b""

    responses[f"{rbi_base}/Scripts/BS_PressReleaseDisplay.aspx?prid=56789"] = (
        FIXTURES_DIR / "rbi" / "press_detail.html"
    ).read_bytes()
    responses[f"{rbi_base}/Scripts/BS_PressReleaseDisplay.aspx?prid=56790"] = (
        FIXTURES_DIR / "rbi" / "press_detail.html"
    ).read_bytes()
    responses[f"{rbi_base}/Scripts/BS_PressReleaseDisplay.aspx?prid=56791"] = (
        FIXTURES_DIR / "rbi" / "press_detail.html"
    ).read_bytes()

    # SEBI fixtures
    sebi_base = "https://www.sebi.gov.in"
    responses[f"{sebi_base}/legal/circulars.html"] = (
        FIXTURES_DIR / "sebi" / "circulars_list_page1.html"
    ).read_bytes()
    responses[f"{sebi_base}/legal/circulars.html?page=2"] = b""
    responses[f"{sebi_base}/legal/circulars.html?page=3"] = b""
    responses[f"{sebi_base}/legal/circulars.html?page=4"] = b""
    responses[f"{sebi_base}/legal/circulars.html?page=5"] = b""

    responses[f"{sebi_base}/legal/circulars/jan-2024/circular-1.html"] = (
        FIXTURES_DIR / "sebi" / "circular_detail.html"
    ).read_bytes()
    responses[f"{sebi_base}/legal/circulars/jan-2024/circular-2.html"] = (
        FIXTURES_DIR / "sebi" / "circular_detail.html"
    ).read_bytes()
    responses[f"{sebi_base}/legal/circulars/jan-2024/circular-3.html"] = (
        FIXTURES_DIR / "sebi" / "circular_detail.html"
    ).read_bytes()

    # FDA fixtures
    fda_base = "https://www.fda.gov"
    responses[f"{fda_base}/about-fda/fda-press-releases/press-releases-rss"] = (
        FIXTURES_DIR / "fda" / "press_releases_rss.xml"
    ).read_bytes()

    fr_base = "https://www.federalregister.gov"
    fr_api_url = (
        f"{fr_base}/api/v1/articles.json?"
        "conditions%5Bpublication_date%5D%5Bgte%5D=2024-01-01"
        "&conditions%5Bagencies%5D%5B%5D=food-and-drug-administration"
        "&order=newest&per_page=50"
    )
    responses[fr_api_url] = (FIXTURES_DIR / "fda" / "federal_register.json").read_bytes()

    responses[
        f"{fda_base}/news-events/press-announcements/"
        "fda-approves-new-treatment-alzheimers-disease"
    ] = (
        b"<html><body>FDA Approves New Treatment for Alzheimer's Disease " b"content</body></html>"
    )
    responses[
        f"{fda_base}/news-events/press-announcements/"
        "fda-issues-warning-letter-medical-device-company"
    ] = b"<html><body>FDA Issues Warning Letter content</body></html>"
    responses[
        f"{fda_base}/news-events/press-announcements/"
        "fda-updates-guidance-clinical-trial-diversity"
    ] = b"<html><body>FDA Updates Guidance content</body></html>"

    responses[
        f"{fr_base}/documents/2024/01/15/2024-00123/"
        "food-and-drug-administration-guidance-for-industry-clinical-trial-diversity"
    ] = b"<html><body>FR Guidance content</body></html>"
    responses[
        f"{fr_base}/documents/2024/01/12/2024-00122/"
        "food-and-drug-administration-rule-medical-device-classification"
    ] = b"<html><body>FR Rule content</body></html>"
    responses[
        f"{fr_base}/documents/2024/01/10/2024-00121/"
        "food-and-drug-administration-proposed-rule-food-traceability"
    ] = b"<html><body>FR Proposed Rule content</body></html>"

    # EU AI Act fixtures
    eu_base = "https://artificial-intelligence-act.com"
    responses[f"{eu_base}/news/"] = (
        FIXTURES_DIR / "eu_ai_act" / "newsroom_page1.html"
    ).read_bytes()
    responses[f"{eu_base}/news/page/2/"] = b""
    responses[f"{eu_base}/news/page/3/"] = b""

    responses[f"{eu_base}/news/article-1.html"] = (
        FIXTURES_DIR / "eu_ai_act" / "article_detail.html"
    ).read_bytes()
    responses[f"{eu_base}/news/article-2.html"] = (
        FIXTURES_DIR / "eu_ai_act" / "article_detail.html"
    ).read_bytes()
    responses[f"{eu_base}/news/article-3.html"] = (
        FIXTURES_DIR / "eu_ai_act" / "article_detail.html"
    ).read_bytes()

    # robots.txt for all hosts (allow all)
    hosts = [
        "www.rbi.org.in",
        "www.sebi.gov.in",
        "www.fda.gov",
        "www.federalregister.gov",
        "artificial-intelligence-act.com",
    ]
    for host in hosts:
        responses[f"https://{host}/robots.txt"] = b"User-agent: *\nAllow: /"

    return responses


@pytest_asyncio.fixture
async def mock_fetcher(recorded_responses: dict[str, bytes]):
    """httpx.AsyncClient with MockTransport returning recorded fixtures."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=recorded_responses.get(str(request.url), b""),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        yield client


@pytest.fixture
def mock_transport(recorded_responses: dict[str, bytes]):
    """httpx.MockTransport returning recorded fixtures (for AsyncFetcher injection)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        content = recorded_responses.get(url, b"")

        # Add ETag/Last-Modified for list pages
        headers = {"Content-Type": "text/html; charset=utf-8"}
        if "NotificationUser.aspx" in url and "Id=" not in url and "page=" not in url:
            headers["ETag"] = '"rbi-notifications-etag-123"'
            headers["Last-Modified"] = "Mon, 15 Jan 2024 12:00:00 GMT"
        elif "BS_PressReleaseDisplay.aspx" in url and "prid=" not in url and "page=" not in url:
            headers["ETag"] = '"rbi-press-etag-456"'
            headers["Last-Modified"] = "Mon, 15 Jan 2024 12:00:00 GMT"
        elif (
            "sebi.gov.in/legal/circulars.html" in url
            and "circular-" not in url
            and "page=" not in url
        ):
            headers["ETag"] = '"sebi-circulars-etag-789"'
            headers["Last-Modified"] = "Mon, 15 Jan 2024 12:00:00 GMT"
        elif "press-releases-rss" in url:
            headers["ETag"] = '"fda-rss-etag-111"'
            headers["Last-Modified"] = "Mon, 15 Jan 2024 14:30:00 GMT"
        elif "federalregister.gov/api" in url:
            headers["ETag"] = '"fr-api-etag-222"'
            headers["Last-Modified"] = "Mon, 15 Jan 2024 12:00:00 GMT"
        elif (
            "artificial-intelligence-act.com/news" in url
            and "article-" not in url
            and "page/" not in url
        ):
            headers["ETag"] = '"eu-news-etag-333"'
            headers["Last-Modified"] = "Mon, 15 Jan 2024 12:00:00 GMT"

        return httpx.Response(200, content=content, headers=headers)

    return httpx.MockTransport(_handler)


# ---- Phase 2b: Parser fixtures ----


@pytest.fixture
def parser_agent() -> ParserAgent:
    """ParserAgent instance for testing."""
    return ParserAgent()


@pytest_asyncio.fixture
async def sample_raw_documents() -> list[RawDocument]:
    """Sample RawDocument objects for parser testing."""
    from datetime import datetime

    return [
        RawDocument(
            url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345",
            content_bytes=b"<html><body><h1>RBI Notification</h1><p>Test content</p></body></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_name="rbi_notifications",
        ),
        RawDocument(
            url="https://www.sebi.gov.in/legal/circulars/jan-2024/circular-1.html",
            content_bytes=b"<html><body><h1>SEBI Circular</h1><p>Test content</p></body></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_name="sebi_circulars",
        ),
        RawDocument(
            url="https://www.fda.gov/news-events/press-announcements/test",
            content_bytes=(
                b"<html><body><h1>FDA Press Release</h1><p>Test content</p></body></html>"
            ),
            headers={"Content-Type": "text/html; charset=utf-8"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_name="fda_press_releases",
        ),
    ]


@pytest.fixture
def parser_fixtures() -> dict[str, bytes]:
    """Load all parser test fixtures into a URL -> content mapping."""
    from pathlib import Path

    fixtures = {}
    fixtures_dir = Path(__file__).parent / "fixtures" / "parser"

    # Map fixture files to test URLs
    fixture_mapping = {
        "rbi_notification.html": "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345",
        "sebi_circular.html": "https://www.sebi.gov.in/legal/circulars/jan-2024/circular-1.html",
        "fda_press_release.html": "https://www.fda.gov/news-events/press-announcements/test",
        "eu_ai_act_article.html": "https://artificial-intelligence-act.com/news/article-1.html",
        "sample.pdf": "https://example.com/sample.pdf",
        "scanned.pdf": "https://example.com/scanned.pdf",
    }

    for filename, url in fixture_mapping.items():
        path = fixtures_dir / filename
        if path.exists():
            fixtures[url] = path.read_bytes()

    return fixtures


# ---- Phase 2b: Normalizer fixtures ----


@pytest.fixture
def normalizer_agent() -> NormalizerAgent:
    """NormalizerAgent instance for testing."""
    return NormalizerAgent()


@pytest.fixture
def sample_parsed_documents() -> list[ParsedDocument]:
    """Sample ParsedDocument objects for normalizer testing."""
    from datetime import datetime

    return [
        ParsedDocument(
            doc_id="doc1",
            url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345",
            title="RBI Notification",
            body_text=(
                "The Reserve Bank of India has issued a notification regarding "
                "updated KYC norms for all scheduled commercial banks. Key changes "
                "include enhanced due diligence for high-risk customers and "
                "mandatory Aadhaar verification."
            ),
            published_date=datetime(2024, 1, 15, 12, 0, 0),
            reference_number="RBI/2024-25/DBR.AML.BC.No.23/14.01.001/2024-25",
            document_type=None,
            lang=None,
        ),
        ParsedDocument(
            doc_id="doc2",
            url="https://www.sebi.gov.in/legal/circulars/jan-2024/circular-1.html",
            title="SEBI Circular",
            body_text=(
                "SEBI has issued a circular regarding margin requirements for "
                "derivatives trading. The circular specifies new margin computation "
                "methodology for equity and commodity derivatives."
            ),
            published_date=datetime(2024, 1, 10, 12, 0, 0),
            reference_number="SEBI/HO/MRD/MRD-PoD-1/P/CIR/2024/15",
            document_type=None,
            lang=None,
        ),
        ParsedDocument(
            doc_id="doc3",
            url="https://www.fda.gov/news-events/press-announcements/test",
            title="FDA Press Release",
            body_text=(
                "FDA has approved a new treatment for Alzheimer's disease. "
                "This is a significant advancement in the treatment of this condition."
            ),
            published_date=datetime(2024, 1, 12, 12, 0, 0),
            reference_number=None,
            document_type=None,
            lang=None,
        ),
        ParsedDocument(
            doc_id="doc4",
            url="https://example.com/mojibake",
            title="Mojibake Test",
            body_text='The bank said "We will comply" and the cost is â€œ100â€.',
            published_date=None,
            reference_number=None,
            document_type=None,
            lang=None,
        ),
    ]
