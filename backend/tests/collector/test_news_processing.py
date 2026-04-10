"""Tests for news processing: budget enforcement removed (LLM scoring removed)."""
import pytest
from unittest.mock import MagicMock

from app.collector.news import NewsCollector


def test_collector_instantiation():
    """NewsCollector can be created without LLM params."""
    collector = NewsCollector(
        pairs=["BTC-USDT-SWAP"],
        db=MagicMock(),
        redis=MagicMock(),
        ws_manager=MagicMock(),
    )
    assert collector.pairs == ["BTC-USDT-SWAP"]
    assert collector._running is False
