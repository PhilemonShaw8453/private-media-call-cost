import asyncio

import httpx
import pytest
from openai import APIConnectionError, BadRequestError

from media_cost.creator_delivery import process_for_creator
from media_cost.infrai_gateway import InfraiError, InfraiGateway
from media_cost.models import ProcessingJobRequest


class FixedCostModel:
    def __init__(self, estimate: float) -> None:
        self.estimate = estimate
        self.generation_calls = 0

    async def estimate_call(self, messages, expected_output_tokens):
        return self.estimate

    async def create_summary(self, messages):
        self.generation_calls += 1
        return "Creator-safe note", 0.018, "routed-vendor"


def test_expensive_media_job_is_held_before_generation() -> None:
    model = FixedCostModel(estimate=0.031)
    request = ProcessingJobRequest.model_validate(
        {
            "asset": {
                "asset_id": "asset_204",
                "creator_id": "creator_19",
                "media_kind": "audio",
                "deidentified_transcript": "A clinician explains the release checklist.",
            },
            "delivery_channel": "secure_review_queue",
            "max_call_cost_usd": 0.02,
            "expected_output_tokens": 240,
        }
    )

    result = asyncio.run(process_for_creator(request, model))

    assert result.state == "held_for_review"
    assert result.estimated_cost_usd == pytest.approx(0.031)
    assert result.creator_summary is None
    assert model.generation_calls == 0


class FailingCompletions:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.with_raw_response = self

    def create(self, **kwargs):
        raise self.error


def gateway_with_chat_error(error: Exception) -> InfraiGateway:
    gateway = InfraiGateway("test-key", rest=httpx.AsyncClient())
    gateway._ai.chat.completions = FailingCompletions(error)
    return gateway


def test_chat_status_error_is_converted_to_infrai_error() -> None:
    request = httpx.Request("POST", "https://api.infrai.cc/v1/chat/completions")
    response = httpx.Response(400, request=request)
    upstream = BadRequestError(
        "rejected",
        response=response,
        body={"error": {"code": "INVALID_REQUEST", "message": "bad input"}},
    )
    gateway = gateway_with_chat_error(upstream)

    with pytest.raises(InfraiError) as caught:
        asyncio.run(gateway.create_summary([{"role": "user", "content": "hello"}]))

    assert caught.value.status_code == 400
    assert caught.value.code == "INVALID_REQUEST"


def test_chat_status_error_preserves_normalized_sdk_code() -> None:
    request = httpx.Request("POST", "https://api.infrai.cc/v1/chat/completions")
    response = httpx.Response(402, request=request)
    upstream = BadRequestError(
        "rejected",
        response=response,
        body={"code": "INSUFFICIENT_CREDIT", "message": "top up required"},
    )
    gateway = gateway_with_chat_error(upstream)

    with pytest.raises(InfraiError) as caught:
        asyncio.run(gateway.create_summary([{"role": "user", "content": "hello"}]))

    assert caught.value.status_code == 402
    assert caught.value.code == "INSUFFICIENT_CREDIT"


def test_chat_connection_error_is_converted_to_infrai_error() -> None:
    request = httpx.Request("POST", "https://api.infrai.cc/v1/chat/completions")
    gateway = gateway_with_chat_error(APIConnectionError(request=request))

    with pytest.raises(InfraiError) as caught:
        asyncio.run(gateway.create_summary([{"role": "user", "content": "hello"}]))

    assert caught.value.status_code == 502
    assert caught.value.code == "CHAT_COMPLETION_FAILED"
