import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.discovery.detector import generate_slug_variants, detect_ats

def test_slug_variants_simple():
    variants = generate_slug_variants("Stripe")
    assert "stripe" in variants

def test_slug_variants_with_space():
    variants = generate_slug_variants("Open AI")
    assert "open-ai" in variants
    assert "openai" in variants
    assert "open_ai" in variants

def test_slug_variants_strips_legal_suffix():
    variants = generate_slug_variants("Acme Corp")
    assert "acme" in variants

def test_slug_variants_strips_punctuation():
    variants = generate_slug_variants("Stripe, Inc.")
    assert "stripe" in variants

async def test_detect_ats_finds_greenhouse():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200 if "boards-api.greenhouse.io" in url and "/stripe" in url else 404
        return r
    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client
        result = await detect_ats("Stripe")
    assert result is not None
    ats_type, board_token = result
    assert ats_type == "greenhouse"
    assert board_token == "stripe"

async def test_detect_ats_returns_none_when_not_found():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 404
        return r
    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client
    with patch("pipeline.discovery.detector.probe_workday", return_value=None):
        result = await detect_ats("UnknownCorp XYZ")
    assert result is None

async def test_detect_ats_uses_slug_override():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200 if "api.lever.co" in url and "/lever-slug" in url else 404
        return r
    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client
        result = await detect_ats("Some Company", slug_override="lever-slug")
    assert result is not None
    assert result[0] == "lever"
    assert result[1] == "lever-slug"

async def test_detect_ats_finds_workday():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        # Return 404 for all HTTP-based ATS systems
        r.status_code = 404
        return r

    async def async_return(slug):
        if slug == "stripe":
            return ("workday", "stripe.wd5/ExternalCareerSite")
        return None

    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client
        with patch("pipeline.discovery.detector.probe_workday", side_effect=async_return):
            result = await detect_ats("Stripe")

    assert result is not None
    assert result[0] == "workday"
    assert result[1] == "stripe.wd5/ExternalCareerSite"
