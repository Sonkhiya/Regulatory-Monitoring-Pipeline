"""Tests for metadata extractor."""

from __future__ import annotations

from regmon.models.enums import DocumentType, Jurisdiction
from regmon.parser.metadata import MetadataExtractor, extract_metadata


class TestMetadataExtractor:
    """Tests for MetadataExtractor class."""

    def test_rbi_date_extraction(self) -> None:
        """Test RBI date pattern extraction."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        # Text matches RBI reference patterns: First pattern won't match due to dot in dept,
        # second pattern matches DBR.WORD.No.NUM/NUM.NUM.NUM/YYYY-YY
        text = "RBI/2024-25/DBR.ABC.No.123/456.789.123/2024-25 Notification dated 15 Jan 2024"
        result = extractor.extract(text, "https://rbi.org.in")
        # Check date extraction
        assert result["published_date"] is not None
        # Check reference number extraction - second pattern matches
        assert result["reference_number"] == "DBR.ABC.No.123/456.789.123/2024-25"
        # Check document type
        assert result["document_type"] == DocumentType.NOTIFICATION

    def test_rbi_dd_mm_yyyy_date(self) -> None:
        """Test RBI date in dd/mm/yyyy format."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "RBI Notification dated 15/01/2024"
        result = extractor.extract(text, "https://rbi.org.in")
        assert result["published_date"] is not None

    def test_rbi_iso_date(self) -> None:
        """Test RBI ISO date format."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "RBI Notification dated 2024-01-15"
        result = extractor.extract(text, "https://rbi.org.in")
        assert result["published_date"] is not None

    def test_rbi_document_type_notification(self) -> None:
        """Test RBI notification document type detection."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "This is a notification from RBI"
        result = extractor.extract(text, "https://rbi.org.in")
        assert result["document_type"] == DocumentType.NOTIFICATION

    def test_rbi_document_type_circular(self) -> None:
        """Test RBI circular document type detection."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "This is a circular from RBI"
        result = extractor.extract(text, "https://rbi.org.in")
        assert (
            result["document_type"] == DocumentType.NOTIFICATION
        )  # circular maps to NOTIFICATION for RBI

    def test_rbi_document_type_master_direction(self) -> None:
        """Test RBI master direction document type detection."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "Master Direction on KYC"
        result = extractor.extract(text, "https://rbi.org.in")
        assert result["document_type"] == DocumentType.NOTIFICATION

    def test_rbi_document_type_press_release(self) -> None:
        """Test RBI press release document type detection."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "Press Release: RBI Monetary Policy"
        result = extractor.extract(text, "https://rbi.org.in")
        assert result["document_type"] == DocumentType.PRESS_RELEASE

    def test_sebi_date_extraction(self) -> None:
        """Test SEBI date pattern extraction."""
        extractor = MetadataExtractor(Jurisdiction.SEBI)
        text = "SEBI Circular dated 15 Jan 2024"
        result = extractor.extract(text, "https://sebi.gov.in")
        assert result["published_date"] is not None

    def test_sebi_reference_extraction(self) -> None:
        """Test SEBI reference number extraction."""
        extractor = MetadataExtractor(Jurisdiction.SEBI)
        # Pattern expects: SEBI/HO/DEPT/NUM/CIR/YEAR/NUM
        text = "SEBI/HO/MRD/123/CIR/2024/12 Circular"
        result = extractor.extract(text, "https://sebi.gov.in")
        assert result["reference_number"] == "SEBI/HO/MRD/123/CIR/2024/12"

    def test_sebi_document_type_circular(self) -> None:
        """Test SEBI circular document type detection."""
        extractor = MetadataExtractor(Jurisdiction.SEBI)
        text = "This is a circular from SEBI"
        result = extractor.extract(text, "https://sebi.gov.in")
        assert result["document_type"] == DocumentType.CIRCULAR

    def test_fda_date_extraction(self) -> None:
        """Test FDA date pattern extraction."""
        extractor = MetadataExtractor(Jurisdiction.FDA)
        text = "Published January 15, 2024 in Federal Register"
        result = extractor.extract(text, "https://federalregister.gov")
        assert result["published_date"] is not None

    def test_fda_reference_extraction(self) -> None:
        """Test FDA reference number extraction (FR Doc, RIN)."""
        extractor = MetadataExtractor(Jurisdiction.FDA)
        text = "FR Doc. 2024-00123 and RIN 2024-ABCD"
        result = extractor.extract(text, "https://federalregister.gov")
        assert (
            "FR Doc. 2024-00123" in result["reference_number"]
            or "RIN 2024-ABCD" in result["reference_number"]
        )

    def test_fda_document_type_regulation(self) -> None:
        """Test FDA regulation document type detection."""
        extractor = MetadataExtractor(Jurisdiction.FDA)
        text = "Final Rule published in Federal Register"
        result = extractor.extract(text, "https://federalregister.gov")
        assert result["document_type"] == DocumentType.REGULATION

    def test_fda_document_type_rss_item(self) -> None:
        """Test FDA RSS item document type detection."""
        extractor = MetadataExtractor(Jurisdiction.FDA)
        text = "Press Release: FDA approves new drug"
        result = extractor.extract(text, "https://fda.gov")
        assert result["document_type"] == DocumentType.RSS_ITEM

    def test_eu_ai_act_date_extraction(self) -> None:
        """Test EU AI Act date pattern extraction."""
        extractor = MetadataExtractor(Jurisdiction.EU_AI_ACT)
        text = "Article 5 dated 2024-03-13"
        result = extractor.extract(text, "https://eur-lex.europa.eu")
        assert result["published_date"] is not None

    def test_eu_ai_act_reference_extraction(self) -> None:
        """Test EU AI Act reference extraction (Article, Annex, Recital)."""
        extractor = MetadataExtractor(Jurisdiction.EU_AI_ACT)
        text = "Article 5 and Annex III and Recital 15"
        result = extractor.extract(text, "https://eur-lex.europa.eu")
        assert (
            "Article 5" in result["reference_number"]
            or "Annex III" in result["reference_number"]
            or "Recital 15" in result["reference_number"]
        )

    def test_eu_ai_act_document_type_regulation(self) -> None:
        """Test EU AI Act regulation document type detection."""
        extractor = MetadataExtractor(Jurisdiction.EU_AI_ACT)
        text = "Article 5 of the AI Regulation"
        result = extractor.extract(text, "https://eur-lex.europa.eu")
        assert result["document_type"] == DocumentType.REGULATION

    def test_eu_ai_act_document_type_news(self) -> None:
        """Test EU AI Act news document type detection."""
        extractor = MetadataExtractor(Jurisdiction.EU_AI_ACT)
        text = "Press release from European Commission"
        result = extractor.extract(text, "https://ec.europa.eu")
        assert result["document_type"] == DocumentType.NEWS

    def test_language_detection_english(self) -> None:
        """Test English language detection."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "The and of to in a is for on with as by that be this"
        result = extractor.extract(text, "https://example.com")
        assert result["language"] == "en"

    def test_reference_from_url_fallback(self) -> None:
        """Test reference number extraction from URL when text patterns fail."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "Some text without reference pattern"
        # URL pattern expects: RBI/YYYY-YY/DEPT/NUM (no dots in DEPT)
        url = "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345&RBI/2024-25/DBR/123"
        result = extractor.extract(text, url)
        assert result["reference_number"] == "RBI/2024-25/DBR/123"

    def test_empty_text(self) -> None:
        """Test extraction from empty text."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        result = extractor.extract("", "https://example.com")
        assert result["published_date"] is None
        assert result["reference_number"] is None
        assert result["document_type"] is None
        assert result["language"] == "en"


class TestExtractMetadataConvenience:
    """Tests for extract_metadata convenience function."""

    def test_extract_metadata_function(self) -> None:
        """Test extract_metadata convenience function."""
        text = "RBI/2024-25/DBR/123 Notification dated 15 Jan 2024"
        result = extract_metadata(text, "https://rbi.org.in", Jurisdiction.RBI)
        assert result["published_date"] is not None
        assert result["reference_number"] is not None
        assert result["document_type"] == DocumentType.NOTIFICATION


class TestFallbackPatterns:
    """Test jurisdiction-specific fallback patterns."""

    def test_rbi_fallback_keywords(self) -> None:
        """Test RBI fallback keywords for document type."""
        extractor = MetadataExtractor(Jurisdiction.RBI)
        text = "Master Circular on KYC norms"
        result = extractor.extract(text, "https://rbi.org.in")
        assert result["document_type"] == DocumentType.NOTIFICATION

    def test_sebi_defaults_to_circular(self) -> None:
        """Test SEBI defaults to CIRCULAR."""
        extractor = MetadataExtractor(Jurisdiction.SEBI)
        text = "Generic SEBI document"
        result = extractor.extract(text, "https://sebi.gov.in")
        assert result["document_type"] == DocumentType.CIRCULAR

    def test_fda_defaults_to_rss_item(self) -> None:
        """Test FDA defaults to RSS_ITEM when not a regulation."""
        extractor = MetadataExtractor(Jurisdiction.FDA)
        text = "Press announcement from FDA"
        result = extractor.extract(text, "https://fda.gov")
        assert result["document_type"] == DocumentType.RSS_ITEM

    def test_eu_ai_act_defaults_to_news(self) -> None:
        """Test EU AI Act defaults to NEWS when not regulation."""
        extractor = MetadataExtractor(Jurisdiction.EU_AI_ACT)
        text = "Speech by Commissioner"
        result = extractor.extract(text, "https://ec.europa.eu")
        assert result["document_type"] == DocumentType.NEWS
