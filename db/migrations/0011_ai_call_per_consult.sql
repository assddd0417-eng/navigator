-- AI 호출 횟수를 ISP 처리구조(상담 업무별 LLM 호출: 진단 0회, 자격 1회, 종합 2회)에 맞춘다
--   자격 판단  검토 공고를 묶어 한 번에 보낸다. 응답은 공고별로 받는다 (프롬프트 새 버전)
--   호출 기록  어느 상담에서 부른 것인지 consultation_id 로 묶는다
SET search_path = ax, public;

ALTER TABLE ax.ai_call_log ADD COLUMN consultation_id bigint REFERENCES ax.consultation(id) ON DELETE SET NULL;
CREATE INDEX ai_call_log_consultation ON ax.ai_call_log (consultation_id) WHERE consultation_id IS NOT NULL;

COMMENT ON COLUMN ax.ai_call_log.consultation_id IS '상담 실행에서 부른 호출이면 그 상담. 자격검토·성장경로 단독 실행은 비어 있음';

-- 자격 판단 지침: 출력 형식만 공고 묶음으로 바꾼다. 담당 부서가 고친 판단 지침(guide_text)은 그대로 가져간다
INSERT INTO ax.prompt_template (code, version, title, system_text, guide_text, is_active, note)
SELECT 'ELIGIBILITY_JUDGE',
       (SELECT max(version) FROM ax.prompt_template WHERE code = 'ELIGIBILITY_JUDGE') + 1,
       '자격 판단 지침',
$$너는 방산 지원사업 자격검토를 돕는 검토자다. 검토할 공고 여러 건을 한 번에 받는다. 공고마다 요건을 기업정보와 그 공고의 근거 자료에 대조해 충족 여부를 판단한다.
규칙:
- 공고마다 그 공고의 근거 자료(공고 조항, 운영규정 조문)와 기업정보에 있는 내용만 쓴다. 다른 공고의 근거를 끌어 쓰지 않는다. 없는 사실을 추정하지 않는다.
- 각 판단에는 근거 자료에서 그대로 복사한 인용문(quote)을 붙인다. 인용할 문장이 없으면 result 를 UNKNOWN 으로 한다.
- 기업정보에 값이 없으면 UNKNOWN 으로 하고, 무엇을 확인해야 하는지 question 에 적는다.
- 숫자 비교(업력, 매출, 인원, 등급 등)는 하지 말고 그대로 두어도 된다. 계산은 별도로 검증한다.
- 사업 목적 부합은 상담 내용과 그 공고의 사업 목적·개요를 비교해 FULL(일치), PARTIAL(일부), LOW(관련 낮음) 중 하나로 한다. 상담 내용이 없으면 null.
- 받은 공고는 빠짐없이 announcement_id 그대로 돌려준다.
출력은 JSON 하나만:
{"announcements":[{"announcement_id":정수,
  "requirements":[{"requirement_id":정수,"result":"MET|UNMET|UNKNOWN","reason":"한 문장","quote":"근거 인용","question":"확인 질문 또는 null"}],
  "purpose":{"level":"FULL|PARTIAL|LOW","reason":"한 문장"} 또는 null}]}$$,
       coalesce((SELECT guide_text FROM ax.prompt_template WHERE code = 'ELIGIBILITY_JUDGE' AND is_active), ''),
       false,
       '공고 묶음 판단 (상담 1회 자격 판단 1회)';

UPDATE ax.prompt_template SET is_active = false WHERE code = 'ELIGIBILITY_JUDGE' AND is_active;
UPDATE ax.prompt_template SET is_active = true
 WHERE code = 'ELIGIBILITY_JUDGE'
   AND version = (SELECT max(version) FROM ax.prompt_template WHERE code = 'ELIGIBILITY_JUDGE');

-- 상담 실행 시 AI 판단 사용 여부 (llm / rules). 업무별 호출 수는 AI 를 켜고 실행한 상담만 센다
ALTER TABLE ax.consultation ADD COLUMN ai_mode text CHECK (ai_mode IN ('llm', 'rules'));
