import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch, MagicMock
from app.push.alert_dispatch import dispatch_push_for_alert


@pytest.mark.asyncio
async def test_dispatch_sends_to_all_subscriptions():
    sub = MagicMock()
    sub.endpoint = "https://push.example.com/sub1"
    sub.p256dh_key = "key1"
    sub.auth_key = "auth1"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sub]

    class FakeSession:
        async def execute(self, *a, **kw):
            return mock_result

    @asynccontextmanager
    async def fake_session():
        yield FakeSession()

    mock_session_factory = MagicMock(side_effect=lambda: fake_session())

    with patch("app.push.alert_dispatch.webpush") as mock_wp:
        await dispatch_push_for_alert(
            session_factory=mock_session_factory,
            alert_id="test-id",
            label="BTC above 70k",
            trigger_value=70200,
            urgency="critical",
            vapid_private_key="test-key",
            vapid_claims_email="test@example.com",
        )
        mock_wp.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_skips_without_vapid_key():
    await dispatch_push_for_alert(
        session_factory=AsyncMock(),
        alert_id="test",
        label="test",
        trigger_value=0,
        urgency="normal",
        vapid_private_key="",
        vapid_claims_email="",
    )
    # Should return immediately without error
