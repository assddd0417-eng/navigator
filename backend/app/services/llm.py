"""LLM 제공자 클라이언트 (교체 가능).

생성기는 LLMClient 프로토콜만 알고, 제공자별 SDK 는 이 모듈 안에 가둔다.
다른 제공자(사내 LLM, vLLM 등)를 붙일 때는 complete() 를 구현한 클래스를 추가하고
build_llm_client 에 LLM_PROVIDER 값을 등록하면 된다.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.config import Settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """호출 실패·거절·응답 잘림 등. 호출 측은 템플릿 문장으로 대체한다."""


class LLMClient(Protocol):
    name: str  # 예: "anthropic/claude-opus-5-5" (match_run.params·rationale_meta 에 기록)

    async def complete(self, system: str, user: str) -> str: ...


class AnthropicClient:
    """Anthropic Claude Messages API (anthropic SDK, pip install ".[llm]")."""

    def __init__(self, settings: Settings, sdk_client=None):
        if sdk_client is None:
            import anthropic  # 선택 의존성: 템플릿만 쓸 때는 설치하지 않아도 된다

            kw: dict = {"timeout": settings.llm_timeout_s, "max_retries": settings.llm_max_retries}
            if settings.anthropic_api_key:
                kw["api_key"] = settings.anthropic_api_key  # 없으면 SDK 가 ANTHROPIC_API_KEY 등에서 찾는다
            sdk_client = anthropic.AsyncAnthropic(**kw)
        self._client = sdk_client
        self._s = settings
        self.name = f"anthropic/{settings.llm_model}"

    async def complete(self, system: str, user: str) -> str:
        import anthropic

        kw: dict = {}
        if self._s.llm_server_fallback:
            # 안전 분류기 거절 시 서버가 권장 모델로 재시도 (Claude API 전용 베타)
            kw = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            resp = await self._client.beta.messages.create(
                model=self._s.llm_model,
                max_tokens=self._s.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self._s.llm_effort},
                **kw,
            )
        # 인증 실패·429·5xx·타임아웃 모두 템플릿 대체 사유.
        # 자격증명이 전혀 없으면 SDK 가 요청 시점에 TypeError("Could not resolve authentication method") 를 낸다.
        except (anthropic.AnthropicError, TypeError) as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("모델이 요청을 거절함")
        if resp.stop_reason == "max_tokens":
            raise LLMError("응답이 max_tokens 에서 잘림")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise LLMError("빈 응답")
        return text


def build_llm_client(settings: Settings) -> LLMClient | None:
    """설정된 제공자의 클라이언트. 만들 수 없으면(SDK 미설치 등) None → 템플릿 사용."""
    provider = settings.llm_provider.lower()
    try:
        if provider == "anthropic":
            return AnthropicClient(settings)
    except Exception as e:  # noqa: BLE001 - 생성 실패는 템플릿으로 대체하고 원인만 남긴다
        log.warning("LLM 클라이언트(%s) 생성 실패, 템플릿 문장 사용: %s", provider, e)
        return None
    log.warning("알 수 없는 LLM_PROVIDER=%s, 템플릿 문장 사용", settings.llm_provider)
    return None
