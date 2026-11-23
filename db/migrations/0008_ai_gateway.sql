-- AI 게이트웨이: 프롬프트 관리와 AI 호출 감사로그
--   prompt_template  자격 판단 지침·결과서 템플릿 등. 고치면 새 버전을 만들고 이전 버전은 남긴다
--   ai_call_log      LLM 호출마다 목적·프롬프트 버전·모델·입력 근거·출력·차단 사유를 남긴다
SET search_path = ax, public;

CREATE TABLE ax.prompt_template (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         text NOT NULL CHECK (code IN ('ELIGIBILITY_JUDGE', 'REPORT_DRAFT')),
    version      integer NOT NULL CHECK (version > 0),
    title        text NOT NULL,
    system_text  text NOT NULL CHECK (length(system_text) BETWEEN 1 AND 20000),
    guide_text   text NOT NULL DEFAULT '' CHECK (length(guide_text) <= 20000),
    is_active    boolean NOT NULL DEFAULT false,
    note         text,
    created_by   bigint REFERENCES ax.app_user(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (code, version)
);
CREATE UNIQUE INDEX prompt_template_active ON ax.prompt_template (code) WHERE is_active;

COMMENT ON TABLE ax.prompt_template IS
    '프롬프트 관리. system_text 는 역할·출력 형식, guide_text 는 담당 부서가 고치는 판단 지침·문장 규칙';

CREATE TABLE ax.ai_call_log (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purpose          text NOT NULL CHECK (purpose IN ('ELIGIBILITY_JUDGE', 'REPORT_DRAFT')),
    organization_id  bigint REFERENCES ax.organization(id) ON DELETE SET NULL,
    announcement_id  bigint REFERENCES ax.announcement(id) ON DELETE SET NULL,
    prompt_id        bigint REFERENCES ax.prompt_template(id),
    model            text,
    cache_key        text,
    input_refs       jsonb NOT NULL DEFAULT '{}'::jsonb,
    output           jsonb,
    status           text NOT NULL CHECK (status IN ('OK', 'PARTIAL', 'FALLBACK', 'CACHED')),
    blocked          jsonb NOT NULL DEFAULT '[]'::jsonb,
    error            text,
    latency_ms       integer,
    created_by       bigint REFERENCES ax.app_user(id),
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ai_call_log_recent ON ax.ai_call_log (created_at DESC);
CREATE INDEX ai_call_log_cache ON ax.ai_call_log (cache_key, created_at DESC) WHERE status IN ('OK', 'PARTIAL');

COMMENT ON TABLE ax.ai_call_log IS
    'AI 호출 감사로그. blocked 는 근거 인용 실패·계산 검증 불일치로 결과에서 뺀 판단 [{requirement_id, reason}]';

CREATE TRIGGER trg_prompt_template_audit AFTER INSERT OR DELETE OR UPDATE ON ax.prompt_template
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('id');

INSERT INTO ax.prompt_template (code, version, title, system_text, guide_text, is_active, note) VALUES
('ELIGIBILITY_JUDGE', 1, '자격 판단 지침',
$$너는 방산 지원사업 자격검토를 돕는 검토자다. 공고 요건마다 기업정보와 근거 자료를 대조해 충족 여부를 판단한다.
규칙:
- 근거 자료(공고 조항, 운영규정 조문)와 기업정보에 있는 내용만 쓴다. 없는 사실을 추정하지 않는다.
- 각 판단에는 근거 자료에서 그대로 복사한 인용문(quote)을 붙인다. 인용할 문장이 없으면 result 를 UNKNOWN 으로 한다.
- 기업정보에 값이 없으면 UNKNOWN 으로 하고, 무엇을 확인해야 하는지 question 에 적는다.
- 숫자 비교(업력, 매출, 인원, 등급 등)는 하지 말고 그대로 두어도 된다. 계산은 별도로 검증한다.
- 사업 목적 부합은 상담 내용과 사업 목적·개요를 비교해 FULL(일치), PARTIAL(일부), LOW(관련 낮음) 중 하나로 한다. 상담 내용이 없으면 null.
출력은 JSON 하나만:
{"requirements":[{"requirement_id":정수,"result":"MET|UNMET|UNKNOWN","reason":"한 문장","quote":"근거 인용","question":"확인 질문 또는 null"}],
 "purpose":{"level":"FULL|PARTIAL|LOW","reason":"한 문장"} 또는 null}$$,
$$- 신청자격: 기업규모·소재지·업종, 방산 참여·진출 여부
- 신청제한: 유사·중복 지원, 휴폐업·부도, 제재 이력. 같은 분야 지원 이력이 있으면 지원 연도와 사업명을 확인한다
- 판단 문장은 실무자가 읽는 짧은 문장으로 쓴다$$,
true, '기본 지침'),
('REPORT_DRAFT', 1, '상담결과서 템플릿',
$$너는 방산기업 상담결과서 초안을 다듬는 담당자 보조다. 주어진 항목별 초안 문장을 읽기 쉽게 고친다.
규칙:
- 초안에 있는 사실과 숫자만 쓴다. 새 숫자, 새 사업명, 새 판단을 만들지 않는다.
- 선정이나 지원을 약속하는 표현을 쓰지 않는다.
- 항목 key 는 그대로 두고 text 만 고친다. 빈 항목은 빈 문자열로 둔다.
출력은 JSON 하나만: {"sections":[{"key":"...","text":"..."}]}$$,
$$- 문장은 '~함', '~임' 으로 끝내는 보고서체
- 항목마다 3~6문장 이내
- 보완 요청 사항은 기업이 바로 준비할 수 있게 구체적으로$$,
true, '기본 템플릿');
