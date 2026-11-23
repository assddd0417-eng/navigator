-- 지원사업 운영규정·지침: 조문 단위로 등록하고 자격 판단 근거로 검색한다
--   regulation          공통운영규정(COMMON) 또는 사업별 운영규정·지침(PROGRAM). 소관부서가 등록·확인한다
--   regulation_article  조문. checks 는 모든 공고에 공통으로 적용할 참여제한 항목, within_years 는 중복지원 제한 기간
SET search_path = ax, public;

CREATE TABLE ax.regulation (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title          text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    kind           text NOT NULL CHECK (kind IN ('COMMON', 'PROGRAM')),
    program_id     bigint REFERENCES ax.program(id) ON DELETE CASCADE,
    owner_dept_id  bigint REFERENCES ax.department(id),
    version_label  text,
    effective_on   date,
    source_url     text,
    is_active      boolean NOT NULL DEFAULT true,
    confirmed_at   timestamptz,
    confirmed_by   bigint REFERENCES ax.app_user(id),
    created_by     bigint REFERENCES ax.app_user(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'PROGRAM') = (program_id IS NOT NULL))
);
CREATE INDEX regulation_program ON ax.regulation (program_id) WHERE is_active;

COMMENT ON TABLE ax.regulation IS '지원사업 운영규정·지침. confirmed_at 은 소관부서가 내용을 확인한 시각 (판단기준 확인일)';

CREATE TABLE ax.regulation_article (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    regulation_id  bigint NOT NULL REFERENCES ax.regulation(id) ON DELETE CASCADE,
    sort_order     integer NOT NULL DEFAULT 0,
    article_no     text NOT NULL,
    title          text,
    body           text NOT NULL CHECK (length(body) BETWEEN 1 AND 20000),
    checks         text[] NOT NULL DEFAULT '{}'
                   CHECK (checks <@ ARRAY['TAX_DELINQUENT', 'INSOLVENT', 'RND_RESTRICTED', 'PROCUREMENT_SANCTIONED',
                                          'DUPLICATE']::text[]),
    within_years   smallint CHECK (within_years BETWEEN 1 AND 10),
    model_id       smallint REFERENCES ax.embedding_model(id),
    embedding      public.vector(1024),
    tsv            tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || body)) STORED,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX regulation_article_reg ON ax.regulation_article (regulation_id, sort_order);
CREATE INDEX regulation_article_tsv ON ax.regulation_article USING gin (tsv);
CREATE INDEX regulation_article_checks ON ax.regulation_article (regulation_id) WHERE checks <> '{}';

COMMENT ON COLUMN ax.regulation_article.checks IS
    '공통 참여제한 항목. 공고에 같은 항목이 없으면 자격검토에 필수요건으로 더한다';

CREATE TRIGGER trg_regulation_audit AFTER INSERT OR DELETE OR UPDATE ON ax.regulation
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('id');
CREATE TRIGGER trg_regulation_article_audit AFTER INSERT OR DELETE OR UPDATE OF article_no, title, body, checks,
    within_years ON ax.regulation_article
    FOR EACH ROW EXECUTE FUNCTION ax.audit_row('id');
