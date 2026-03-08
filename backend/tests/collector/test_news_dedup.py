"""Tests for news dedup logic: URL exact-match and fuzzy headline matching."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.collector.news import (
    normalize_headline,
    fingerprint_headline,
    is_relevant,
    extract_affected_pairs,
    is_url_duplicate,
    is_headline_duplicate,
)


# --- normalize_headline ---

def test_normalize_strips_punctuation():
    assert normalize_headline("Fed Holds Rates!") == "fed holds rates"


def test_normalize_collapses_whitespace():
    assert normalize_headline("  BTC   surges  ") == "btc surges"


# --- fingerprint_headline ---

def test_fingerprint_deterministic():
    a = fingerprint_headline("Fed cuts rates")
    b = fingerprint_headline("Fed cuts rates")
    assert a == b


def test_fingerprint_ignores_case_and_punctuation():
    a = fingerprint_headline("Fed Cuts Rates!")
    b = fingerprint_headline("fed cuts rates")
    assert a == b


# --- is_relevant ---

def test_relevant_pair_mention():
    assert is_relevant("BTC hits new highs", ["BTC-USDT-SWAP"], [])


def test_relevant_keyword_match():
    assert is_relevant("Fed raises interest rate", [], ["interest rate"])


def test_not_relevant():
    assert not is_relevant("Weather forecast today", ["BTC-USDT-SWAP"], ["Fed"])


def test_relevant_case_insensitive():
    assert is_relevant("btc price analysis", ["BTC-USDT-SWAP"], [])


# --- extract_affected_pairs ---

def test_extract_specific_pair():
    result = extract_affected_pairs("BTC surges past 100k", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"], [])
    assert result == ["BTC"]


def test_extract_multiple_pairs():
    result = extract_affected_pairs("BTC and ETH rally", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"], [])
    assert "BTC" in result and "ETH" in result


def test_extract_macro_returns_all():
    result = extract_affected_pairs("Fed raises interest rate", ["BTC-USDT-SWAP"], ["interest rate"])
    assert result == ["ALL"]


# --- is_url_duplicate ---

@pytest.mark.asyncio
async def test_url_duplicate_found():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = 1  # found
    session.execute = AsyncMock(return_value=mock_result)

    assert await is_url_duplicate(session, "https://example.com/article") is True


@pytest.mark.asyncio
async def test_url_duplicate_not_found():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    assert await is_url_duplicate(session, "https://example.com/new-article") is False


# --- is_headline_duplicate (fuzzy) ---

@pytest.mark.asyncio
async def test_fuzzy_duplicate_above_threshold():
    """Headlines with >85% similarity should be flagged as duplicate."""
    session = AsyncMock()
    mock_result = MagicMock()
    # Very similar headline already in DB
    mock_result.all.return_value = [("Fed holds rates steady, signals cuts in Q3",)]
    session.execute = AsyncMock(return_value=mock_result)

    # Almost identical headline
    is_dup = await is_headline_duplicate(session, "Fed holds rates steady, signals cuts in Q3 2026")
    assert is_dup is True


@pytest.mark.asyncio
async def test_fuzzy_not_duplicate_below_threshold():
    """Headlines with <85% similarity should NOT be flagged."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [("Fed holds rates steady, signals cuts in Q3",)]
    session.execute = AsyncMock(return_value=mock_result)

    # Completely different headline
    is_dup = await is_headline_duplicate(session, "Bitcoin mining difficulty reaches all time high")
    assert is_dup is False


@pytest.mark.asyncio
async def test_fuzzy_84_pct_keeps():
    """Similarity at 84% should keep (not flag as duplicate)."""
    session = AsyncMock()
    mock_result = MagicMock()
    # Craft a headline that's different enough (~84%)
    mock_result.all.return_value = [("Federal Reserve maintains interest rates unchanged",)]
    session.execute = AsyncMock(return_value=mock_result)

    # Different enough headline
    is_dup = await is_headline_duplicate(session, "ECB maintains interest rates unchanged")
    assert is_dup is False


@pytest.mark.asyncio
async def test_fuzzy_empty_db():
    """No recent headlines — nothing to match against."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    is_dup = await is_headline_duplicate(session, "Any headline at all")
    assert is_dup is False
