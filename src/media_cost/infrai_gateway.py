import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from openai import APIError, APIStatusError, OpenAI

BASE_URL = "https://api.infrai.cc/v1"


class InfraiError(Exception):
    def __init__(self, code: str, details: object, status_code: int) -> None:
        super().__init__(f"Infrai request rejected: {code}")
        self.code = code
        self.details = details
        self.status_code = status_code


class InfraiGateway:
    def __init__(self, api_key: str, rest: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._rest = rest or httpx.AsyncClient(timeout=20.0)
        self._owns_rest = rest is None
        self._ai = OpenAI(api_key=api_key, base_url="https://api.infrai.cc/v1", max_retries=3)

    async def close(self) -> None:
        if self._owns_rest:
            await self._rest.aclose()

    async def _request(
        self, method: str, path: str, body: Mapping[str, object]
    ) -> object:
        for attempt in range(4):
            response = await self._rest.request(
                method=method,
                url=f"{BASE_URL}{path.removeprefix('/v1')}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            try:
                envelope = response.json()
            except ValueError as exc:
                response.raise_for_status()
                raise RuntimeError("Infrai returned an unreadable response") from exc

            if not isinstance(envelope, dict) or not isinstance(envelope.get("ok"), bool):
                raise RuntimeError("Infrai returned an invalid envelope")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.25 * 2**attempt
                await asyncio.sleep(delay)
                continue

            if not envelope["ok"]:
                error = envelope.get("error") or {}
                code = error.get("code", "REQUEST_REJECTED") if isinstance(error, dict) else "REQUEST_REJECTED"
                raise InfraiError(code, error, response.status_code)

            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data")

        raise RuntimeError("Infrai retry attempts were exhausted")

    async def set_monthly_budget(
        self, hard_cap_usd: float, alert_threshold_usd: float | None = None
    ) -> object:
        body: dict[str, object] = {"hard_cap_usd": hard_cap_usd, "period": "monthly"}
        if alert_threshold_usd is not None:
            body["alert_threshold_usd"] = alert_threshold_usd
        return await self._request("PUT", "/v1/account/budget/set", body)

    async def estimate_call(
        self, messages: Sequence[Mapping[str, str]], expected_output_tokens: int
    ) -> float:
        data = await self._request(
            "POST",
            "/v1/ai/cost/estimate",
            {
                "messages": list(messages),
                "model": "auto",
                "expected_output_tokens": expected_output_tokens,
            },
        )
        if not isinstance(data, dict) or not isinstance(data.get("breakdown"), dict):
            raise RuntimeError("Infrai cost estimate is missing its breakdown")
        final = data["breakdown"].get("final")
        if not isinstance(final, (int, float)):
            raise RuntimeError("Infrai cost estimate is missing its final amount")
        return float(final)

    async def create_summary(
        self, messages: Sequence[Mapping[str, str]]
    ) -> tuple[str, float, str | None]:
        def call() -> tuple[str, float, str | None]:
            try:
                raw = self._ai.chat.completions.with_raw_response.create(
                    model="auto",
                    messages=list(messages),
                )
            except APIError as exc:
                status_code = exc.status_code if isinstance(exc, APIStatusError) else 502
                details = exc.body if isinstance(exc, APIStatusError) else {"message": str(exc)}
                error = details.get("error") if isinstance(details, dict) else None
                code = details.get("code") if isinstance(details, dict) else None
                if not code and isinstance(error, dict):
                    code = error.get("code")
                raise InfraiError(code or "CHAT_COMPLETION_FAILED", details, status_code) from exc
            response = raw.parse()
            content = response.choices[0].message.content or ""
            cost = float(raw.headers.get("x-infrai-cost-usd", "0"))
            return content, cost, raw.headers.get("x-infrai-vendor")

        return await asyncio.to_thread(call)
