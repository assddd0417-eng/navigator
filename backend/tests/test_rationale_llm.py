"""LLM 연계이유: 근거 검증·프롬프트·제공자 래퍼 (LLM 호출은 모두 가짜)."""
from types import SimpleNamespace

import anthropic
import pytest

from app.config import Settings
from app.services import rationale as rat
from app.services.llm import AnthropicClient, LLMError
from app.services.rationale import EvidenceSnippet, LLMRationaleWriter, RationaleRejected, validate_llm_text
from app.services.scoring import CardCandidate, CriterionScore, DemandContext, Performance

CARD = CardCandidate(card_id=1, title="항재밍 주파수 도약 데이터링크", project_id=1, project_dept_id=3,
                     program_type="CORE_TECH", trl=5, performances=[Performance("동기 유지 시간", value=6, unit="s")],
                     open_issues={7: "광대역 재밍 환경에서 동기 유지 시간 부족"})
DEMAND = DemandContext(1, "광대역 재밍 대응 정찰드론 데이터링크", 5, 7,
                       requirements=[Performance("동기 유지 시간", "GTE", 10, unit="s")])
SCORES = {"TECH": CriterionScore(0.8123, "cosine:OPEN_ISSUE↔TECH_NEED"),
          "PERFORMANCE": CriterionScore(0.6, "rule:metric_ratio", {"gaps": ["동기 유지 시간: 요구 10s, 달성 6s"]}),
          "TRL": CriterionScore(1.0, "rule:trl_range"), "ENVIRONMENT": CriterionScore(0.5, "neutral"),
          "PURPOSE": CriterionScore(0.5, "neutral")}
EVIDENCE = [EvidenceSnippet(11, 100, "항재밍 결과보고서 4.3 p.88",
                            "동기 유지 시간이 목표 10초 대비 6초로 부족하여 후속 연구가 필요함", "RAG", 0.71)]


class FakeLLM:
    name = "fake/test"

    def __init__(self, reply: str | Exception):
        self.reply, self.calls = reply, []

    async def complete(self, system, user):
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _write(reply):
    llm = FakeLLM(reply)
    coro = LLMRationaleWriter(llm).write("FOLLOW_UP", [CARD], DEMAND, SCORES, "미해결 기술 유사도 0.81 (기준 0.55)",
                                         "미해결 기술 후속 개발: 광대역 재밍 환경에서 동기 유지 시간 부족", EVIDENCE)
    return llm, coro


async def test_writer_grounded_text_cites_evidence_label():
    llm, coro = _write("수요가 요구하는 동기 유지 시간 10s 에 대해 이 성과는 6s 를 달성해 후속 개발이 필요하다 [E1]. "
                       "기술 유사도 0.81, TRL 적합도 1.00 이다.")
    res = await coro
    assert res.text.startswith("[후속형] ")
    assert "[근거: 항재밍 결과보고서 4.3 p.88]" in res.text and "[E1]" not in res.text
    assert res.document_ids == [100] and res.evidence_ids == [11]
    system, user = llm.calls[0]
    assert "지어내" in system or "추정하거나 덧붙이지 않는다" in system
    assert '<E1 source="항재밍 결과보고서 4.3 p.88"' in user and "동기 유지 시간: 요구 10s, 달성 6s" in user
    assert "운용환경 적합도 0.50 (neutral)" in user


async def test_writer_rejects_invented_number():
    _, coro = _write("동기 유지 시간을 12s 로 높이면 충족된다 [E1].")
    with pytest.raises(RationaleRejected, match="12"):
        await coro


async def test_writer_propagates_llm_error():
    _, coro = _write(LLMError("timeout"))
    with pytest.raises(LLMError):
        await coro


@pytest.mark.parametrize("text,err", [
    ("근거와 맞닿는다 [E2].", "없는 근거 번호"),
    ("근거 번호 없이 쓴 문장이다.", "근거 인용 없음"),
    ("가" * 1000 + " [E1]", "길이 초과"),
])
def test_validate_rejects(text, err):
    with pytest.raises(RationaleRejected, match=err):
        validate_llm_text(text, "<E1>원문</E1>", 1)


def test_validate_strips_label_and_normalizes_numbers():
    out = validate_llm_text("[후속형] 성능 적합도 0.6 이다 [E1].", "성능 적합도 0.60 <E1>x</E1>", 1)
    assert out == "성능 적합도 0.6 이다 [E1]."
    # 근거가 없으면 인용 없이도 통과
    assert validate_llm_text("TRL 5 성과다.", "TRL 5", 0) == "TRL 5 성과다."


# --- 제공자 래퍼 ---------------------------------------------------------------
class FakeMessages:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.kwargs = resp, exc, None

    async def create(self, **kw):
        self.kwargs = kw
        if self.exc:
            raise self.exc
        return self.resp


def _sdk(resp=None, exc=None):
    msgs = FakeMessages(resp, exc)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def _resp(text="문장", stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="thinking", thinking=""),
                                                      SimpleNamespace(type="text", text=text)])


async def test_anthropic_client_request_shape():
    sdk, msgs = _sdk(_resp(" 연계이유 "))
    c = AnthropicClient(Settings(llm_effort="low"), sdk_client=sdk)
    assert await c.complete("sys", "user") == "연계이유"
    assert c.name == "anthropic/claude-opus-5-5"
    kw = msgs.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["system"] == "sys"
    assert kw["output_config"] == {"effort": "low"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in kw and "temperature" not in kw

    sdk, msgs = _sdk(_resp())
    await AnthropicClient(Settings(llm_server_fallback=False), sdk_client=sdk).complete("s", "u")
    assert "fallbacks" not in msgs.kwargs


@pytest.mark.parametrize("sdk_args,match", [
    ({"resp": _resp(stop="refusal")}, "거절"),
    ({"resp": _resp(stop="max_tokens")}, "잘림"),
    ({"resp": _resp(text="  ")}, "빈 응답"),
    ({"exc": anthropic.AnthropicError("overloaded")}, "AnthropicError"),
])
async def test_anthropic_client_errors_become_llm_error(sdk_args, match):
    sdk, _ = _sdk(**sdk_args)
    with pytest.raises(LLMError, match=match):
        await AnthropicClient(Settings(), sdk_client=sdk).complete("s", "u")


async def test_anthropic_client_without_credentials_becomes_llm_error(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    c = AnthropicClient(Settings(llm_max_retries=0, llm_timeout_s=2))
    with pytest.raises(LLMError):
        await c.complete("s", "u")


def test_get_llm_writer_selection(monkeypatch):
    assert rat.get_llm_writer(Settings(rationale_generator="template")) is None
    # auto(기본): 키가 없으면 템플릿, 있으면 LLM
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert Settings.model_fields["rationale_generator"].default == "auto"
    monkeypatch.setattr(rat, "build_llm_client", lambda s: FakeLLM("x"))
    assert rat.get_llm_writer(Settings(rationale_generator="auto")) is None
    assert rat.get_llm_writer(Settings(rationale_generator="auto", anthropic_api_key="k")) is not None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert rat.get_llm_writer(Settings(rationale_generator="auto")) is not None
    monkeypatch.setattr(rat, "build_llm_client", lambda s: None)          # SDK 미설치·생성 실패
    assert rat.get_llm_writer(Settings(rationale_generator="llm")) is None
    monkeypatch.setattr(rat, "build_llm_client", lambda s: FakeLLM("x"))
    assert isinstance(rat.get_llm_writer(Settings(rationale_generator="LLM")), LLMRationaleWriter)
