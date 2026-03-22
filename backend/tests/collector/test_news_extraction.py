"""Test article text extraction at news ingest."""
from unittest.mock import patch, MagicMock

from app.collector.news import extract_article_text


def test_extract_article_text_returns_content():
    """Successful extraction returns article text."""
    html = "<html><body><article><p>Bitcoin surged to new highs today.</p></article></body></html>"
    with patch("app.collector.news.trafilatura.extract", return_value="Bitcoin surged to new highs today."):
        result = extract_article_text(html)
    assert result == "Bitcoin surged to new highs today."


def test_extract_article_text_returns_none_on_failure():
    """Failed extraction returns None."""
    with patch("app.collector.news.trafilatura.extract", return_value=None):
        result = extract_article_text("<html></html>")
    assert result is None


def test_extract_article_text_returns_none_on_empty():
    """Empty string extraction returns None."""
    with patch("app.collector.news.trafilatura.extract", return_value=""):
        result = extract_article_text("<html></html>")
    assert result is None


def test_extract_article_text_returns_none_on_exception():
    """Exception during extraction returns None."""
    with patch("app.collector.news.trafilatura.extract", side_effect=Exception("parse error")):
        result = extract_article_text("<html></html>")
    assert result is None
