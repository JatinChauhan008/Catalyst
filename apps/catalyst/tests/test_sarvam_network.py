"""A Sarvam host that cannot be reached gives a clear error after a few retries."""

from __future__ import annotations

import pytest
import requests
from catalyst.dost.translate import SarvamTranslator
from catalyst.sarvam.client import SarvamApiError, SarvamDocAiClient, is_retryable
from PIL import Image

# The .invalid top-level domain never resolves (RFC 2606).
UNREACHABLE = "https://sarvam.invalid"


class _CountingSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def request(self, *args, **kwargs):  # type: ignore[override]
        self.calls += 1
        return super().request(*args, **kwargs)


def test_a_dns_failure_is_retried_then_reported_clearly() -> None:
    session = _CountingSession()
    client = SarvamDocAiClient(
        api_key="k", base_url=UNREACHABLE, network_retries=1, session=session
    )
    with pytest.raises(
        SarvamApiError, match=r"Cannot reach Sarvam \(sarvam\.invalid\)"
    ):
        client.digitise_pages([Image.new("RGB", (20, 20), "white")], language="hi-IN")
    assert session.calls == 2  # the job was never sent, so retrying is safe


def test_a_post_that_may_have_reached_the_server_is_not_repeated() -> None:
    # A read timeout means Sarvam may have created (and billed) the job.
    assert not is_retryable(requests.ReadTimeout(), "POST")
    assert is_retryable(requests.ReadTimeout(), "GET")


def test_an_unreachable_translation_service_leaves_the_translation_empty() -> None:
    translator = SarvamTranslator(api_key="k", base_url=UNREACHABLE, max_retries=0)
    [result] = translator.translate_all(["हिमाचल प्रदेश में वर्षा हुई।"], "hi-IN")
    assert (result.text, result.status) == ("", "failed")
    assert result.detail is not None and "Cannot reach Sarvam" in result.detail
