"""국방기술 동의어 사전으로 용어 차이 보정 (정의서 107, 제안서 위험요인 '부서별 데이터와 용어 차이').

같은 뜻의 말(동의어·약어·영한)을 한 묶음으로 보고, 글에 묶음의 어느 말이 나오면 나머지 말을
'관련 용어' 한 줄로 덧붙여 임베딩·검색한다. 그러면 'AESA 레이더'와 '능동위상배열 레이더'처럼
부서·시스템마다 다르게 쓴 성과와 수요가 서로 가까워진다.
- 넓은 말·좁은 말·관련어(BROADER·NARROWER·RELATED)는 뜻이 달라 덧붙이지 않는다 (엉뚱한 후보가 끌려오지 않게).
- 사전이 비어 있으면 글을 바꾸지 않는다 (기존 임베딩·측정 결과 그대로).
"""
import re
from dataclasses import dataclass

from psycopg import AsyncConnection

EQUIVALENT = ("SYNONYM", "ABBREVIATION", "EN_KO")
MARK = "관련 용어: "


@dataclass(frozen=True)
class Group:
    canonical: str
    terms: tuple[str, ...]   # canonical 포함, 긴 말 먼저


async def load_groups(conn: AsyncConnection) -> list[Group]:
    rows = await (await conn.execute(
        "SELECT canonical_term, synonym FROM ax.term_synonym WHERE is_active AND relation = ANY(%s) "
        "ORDER BY canonical_term, synonym", (list(EQUIVALENT),))).fetchall()
    by: dict[str, set[str]] = {}
    for r in rows:
        by.setdefault(r["canonical_term"], {r["canonical_term"]}).add(r["synonym"])
    return [Group(c, tuple(sorted(t, key=lambda x: (-len(x), x)))) for c, t in by.items()]


def _pattern(term: str) -> re.Pattern:
    esc = re.escape(term)
    # 영문·숫자 약어는 낱말 경계로만 (예: 'AI' 가 'MAIN' 안에서 잡히지 않게).
    if re.fullmatch(r"[A-Za-z0-9/\-\. ]+", term):
        return re.compile(rf"(?<![A-Za-z0-9]){esc}(?![A-Za-z0-9])", re.IGNORECASE)
    # 한글은 뒤에 조사가 붙으므로 앞쪽만 막는다. '대드론'(드론을 막는 것)이 '드론'으로 잡히면
    # 무인기 성과가 생존성 요구로 끌려온다 (2026-11-17 갭 측정에서 확인).
    return re.compile(rf"(?<![A-Za-z0-9가-힣]){esc}", re.IGNORECASE)


def matches(text: str, groups: list[Group]) -> list[tuple[Group, str]]:
    """글에 나온 묶음과 그 묶음에서 실제로 나온 말."""
    out = []
    for g in groups:
        for t in g.terms:
            if len(t) >= 2 and _pattern(t).search(text):
                out.append((g, t))
                break
    return out


def expand(text: str | None, groups: list[Group]) -> str | None:
    """글에 나온 묶음의 다른 말을 '관련 용어' 줄로 덧붙인다. 덧붙일 말이 없으면 글 그대로."""
    if not text or not groups:
        return text
    extra: list[str] = []
    for g, _ in matches(text, groups):
        for t in g.terms:
            if not _pattern(t).search(text) and t not in extra:
                extra.append(t)
    return f"{text}\n{MARK}{', '.join(extra)}" if extra else text
