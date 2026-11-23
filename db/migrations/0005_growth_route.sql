-- 맞춤형 성장경로 (D-ROUTE): 지원사업 연계관계 기준표
--   growth_stage   성장단계 (방산진입 > 기술개발 > 양산·수출)와 단계 목표
--   program_route  사업별 성장단계, 다음 연계사업, 진입조건(D-STATE 영역 최소 점수), 준비과제, 예상 산출물
SET search_path = ax, public;

CREATE TABLE ax.growth_stage (
    code        text PRIMARY KEY,
    name_ko     text NOT NULL,
    goal        text NOT NULL,
    areas       text[] NOT NULL DEFAULT '{}',
    sort_order  smallint NOT NULL
);

COMMENT ON TABLE ax.growth_stage IS '성장단계. 기업 상태유형으로 현재 단계를 정하고 다음 단계로 경로를 잇는다';

INSERT INTO ax.growth_stage (code, name_ko, goal, areas, sort_order) VALUES
  ('ENTRY',    '방산진입 단계', '방산 수요 확보와 진입 기반 마련',   '{DEFENSE,QUALITY}',      1),
  ('TECH_DEV', '기술개발 단계', '보유기술의 군 수요 기반 사업화',     '{TECH,BUSINESS}',        2),
  ('SCALE',    '양산·수출 단계', '양산 실적 기반 해외시장 진출',      '{PRODUCTION,EXPORT}',    3);

CREATE TABLE ax.program_route (
    program_id        bigint PRIMARY KEY REFERENCES ax.program(id) ON DELETE CASCADE,
    stage_code        text NOT NULL REFERENCES ax.growth_stage(code),
    next_program_ids  bigint[] NOT NULL DEFAULT '{}',
    entry_condition   text,
    entry_min_scores  jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(entry_min_scores) = 'object'),
    prep_tasks        text[] NOT NULL DEFAULT '{}',
    expected_output   text,
    repeatable        boolean NOT NULL DEFAULT false,
    sort_order        smallint NOT NULL DEFAULT 0,
    updated_by        bigint REFERENCES ax.app_user(id),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE ax.program_route IS
    '지원사업 연계관계. entry_min_scores 예 {"DEFENSE":40}. repeatable=false 면 이미 수혜한 사업은 다시 추천하지 않음';

CREATE TRIGGER trg_program_route_audit AFTER INSERT OR DELETE OR UPDATE ON ax.program_route
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('program_id');
