-- =============================================================================
-- 0015: 조회 함수 및 뷰
--   - can_read_document : 보안등급·부서 권한 기반 원문 열람 판단
--   - search_chunks     : 권한 필터가 적용된 RAG 청크 검색
--   - match_cards       : 수요 패싯 ↔ 카드 패싯 유사도 후보 탐색
--   - KPI·검토 뷰       : 근거 연결률, 최종 검토율, Top-K 포함률, 시간 단축률, 검토 대기열
-- =============================================================================
SET search_path = ax, public;

-- ---------------------------------------------------------------------------
-- 원문 열람권한
--   (1) 사용자 clearance 등급 ≥ 문서 보안등급  AND
--   (2) 소관부서 미지정 / 본인 부서 소관 / 부서 열람권한 부여 / 문서 개별 허용 중 하나
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ax.can_read_document(p_user_id bigint, p_document_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1
        FROM ax.source_document d
        JOIN ax.code_security_level dl ON dl.code = d.security_code
        JOIN ax.app_user u             ON u.id = p_user_id AND u.is_active
        JOIN ax.code_security_level ul ON ul.code = u.clearance_code
        WHERE d.id = p_document_id
          AND ul.level_rank >= dl.level_rank
          AND (
                d.owner_dept_id IS NULL
             OR d.owner_dept_id = u.department_id
             OR EXISTS (SELECT 1 FROM ax.department_access_grant g
                        JOIN ax.code_security_level gl ON gl.code = g.max_security_code
                        WHERE g.target_dept_id = d.owner_dept_id
                          AND (g.grantee_user_id = u.id OR g.grantee_dept_id = u.department_id)
                          AND gl.level_rank >= dl.level_rank
                          AND g.valid_from <= now() AND (g.valid_to IS NULL OR g.valid_to > now()))
             OR EXISTS (SELECT 1 FROM ax.document_access_grant a
                        WHERE a.document_id = d.id AND a.grantee_user_id = u.id
                          AND (a.valid_to IS NULL OR a.valid_to > now()))
          )
    )
$$;

-- ---------------------------------------------------------------------------
-- RAG 청크 검색 (권한 필터 적용)
--   HNSW 는 인덱스 탐색 후 WHERE 필터를 적용하므로, 후보를 p_k * p_oversample 만큼
--   먼저 가져온 뒤 권한·문서유형으로 거른다. pgvector >= 0.8 사용 시
--   `SET hnsw.iterative_scan = relaxed_order` 로 대체 가능.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ax.search_chunks(
    p_query       vector(1024),
    p_user_id     bigint,
    p_k           integer DEFAULT 10,
    p_doc_types   text[]  DEFAULT NULL,
    p_project_id  bigint  DEFAULT NULL,
    p_oversample  integer DEFAULT 5
) RETURNS TABLE (
    chunk_id bigint, document_id bigint, document_title text, doc_type_code text,
    version_label text, section_no text, heading text,
    page_start integer, page_end integer, location jsonb, content text, similarity double precision
) LANGUAGE sql STABLE AS $$
    WITH ann AS (
        SELECT ce.chunk_id, ce.embedding <=> p_query AS dist
        FROM ax.chunk_embedding ce
        WHERE ce.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)
        ORDER BY ce.embedding <=> p_query
        LIMIT p_k * p_oversample
    )
    SELECT c.id, d.id, d.title, d.doc_type_code, d.version_label, s.section_no, s.heading,
           c.page_start, c.page_end, c.location, c.content, 1 - ann.dist
    FROM ann
    JOIN ax.document_chunk c   ON c.id = ann.chunk_id
    JOIN ax.source_document d  ON d.id = c.document_id
    LEFT JOIN ax.document_section s ON s.id = c.section_id
    WHERE d.is_latest
      AND (p_doc_types  IS NULL OR d.doc_type_code = ANY (p_doc_types))
      AND (p_project_id IS NULL OR d.project_id = p_project_id)
      AND ax.can_read_document(p_user_id, d.id)
    ORDER BY ann.dist
    LIMIT p_k
$$;

-- ---------------------------------------------------------------------------
-- 수요 → 성과카드 후보 탐색 (패싯 간 코사인 유사도)
--   예) 후속형: match_cards(수요ID, 'TECH_NEED', 'OPEN_ISSUE')
--       전환형: match_cards(수요ID, 'TECH_NEED', 'PRINCIPLE')
--   패싯 값을 리터럴로 넣은 동적 SQL 을 사용해 부분 HNSW 인덱스가 선택되도록 한다.
--   카드에 같은 패싯 임베딩이 여러 개(예: 미해결 항목별)면 최대 유사도를 사용.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ax.match_cards(
    p_demand_id    bigint,
    p_demand_facet text,
    p_card_facet   text,
    p_k            integer DEFAULT 20,
    p_published_only boolean DEFAULT true,
    p_oversample   integer DEFAULT 4
) RETURNS TABLE (card_id bigint, similarity double precision, matched_source_table text, matched_source_id bigint)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY EXECUTE format($q$
        WITH q AS (
            SELECT de.embedding
            FROM ax.demand_embedding de
            WHERE de.demand_id = %1$s AND de.facet = %2$L
              AND de.model_id = (SELECT id FROM ax.embedding_model WHERE is_active)
        ), hits AS (
            SELECT h.card_id, h.source_table, h.source_id, 1 - h.dist AS sim
            FROM q
            CROSS JOIN LATERAL (
                SELECT ce.card_id, ce.source_table, ce.source_id, ce.embedding <=> q.embedding AS dist
                FROM ax.card_embedding ce
                WHERE ce.facet = %3$L
                ORDER BY ce.embedding <=> q.embedding
                LIMIT %4$s
            ) h
        ), best AS (
            SELECT DISTINCT ON (hits.card_id) hits.card_id, hits.sim, hits.source_table, hits.source_id
            FROM hits
            ORDER BY hits.card_id, hits.sim DESC
        )
        SELECT b.card_id, b.sim, b.source_table, b.source_id
        FROM best b
        JOIN ax.achievement_card ac ON ac.id = b.card_id
        WHERE (NOT %5$L::boolean OR ac.status = 'PUBLISHED')
        ORDER BY b.sim DESC
        LIMIT %6$s
    $q$, p_demand_id, p_demand_facet, p_card_facet, p_k * p_oversample, p_published_only, p_k);
END $$;

-- ---------------------------------------------------------------------------
-- 뷰
-- ---------------------------------------------------------------------------

-- 추천 개요 (검토표·API 목록 화면용)
CREATE OR REPLACE VIEW ax.v_recommendation_overview AS
SELECT r.id                       AS recommendation_id,
       r.match_run_id,
       r.rank,
       r.total_score,
       r.linkage_type_code,
       lt.name_ko                 AS linkage_type_name,
       r.final_linkage_type_code,
       r.status,
       r.final_decision_code,
       r.is_excluded,
       r.demand_id,
       pd.title                   AS demand_title,
       r.target_program_id,
       pg.name                    AS target_program_name,
       r.rationale,
       r.development_needs,
       (SELECT jsonb_agg(jsonb_build_object('card_id', ac.id, 'card_no', ac.card_no, 'title', ac.title,
                                            'project_no', p.project_no, 'role', rsc.role) ORDER BY rsc.role, ac.id)
          FROM ax.recommendation_source_card rsc
          JOIN ax.achievement_card ac ON ac.id = rsc.card_id
          JOIN ax.project p ON p.id = ac.project_id
         WHERE rsc.recommendation_id = r.id)                         AS source_cards,
       (SELECT jsonb_object_agg(rs.criterion, rs.score)
          FROM ax.recommendation_score rs WHERE rs.recommendation_id = r.id) AS scores,
       (SELECT d.name FROM ax.recommendation_department rd JOIN ax.department d ON d.id = rd.department_id
         WHERE rd.recommendation_id = r.id AND rd.role = 'OWNER')    AS owner_department,
       (SELECT count(*) FROM ax.recommendation_evidence re WHERE re.recommendation_id = r.id) AS evidence_count,
       (SELECT count(*) FROM ax.confirmation_item ci
         WHERE ci.recommendation_id = r.id AND ci.status = 'OPEN')   AS open_confirmations,
       r.created_at
FROM ax.recommendation r
JOIN ax.code_linkage_type lt ON lt.code = r.linkage_type_code
LEFT JOIN ax.planning_demand pd ON pd.id = r.demand_id
LEFT JOIN ax.program pg ON pg.id = r.target_program_id;

-- 근거 연결 상세 (출처 문서·조항·페이지·청크)
CREATE OR REPLACE VIEW ax.v_recommendation_evidence AS
SELECT re.recommendation_id, re.side, re.role, re.criterion, re.relevance_score, re.explanation,
       e.id AS evidence_id, e.quote, e.page_start, e.page_end, e.location,
       d.id AS document_id, d.title AS document_title, d.doc_type_code, d.version_label, d.authored_at,
       s.section_no, s.heading AS section_heading, e.chunk_id
FROM ax.recommendation_evidence re
JOIN ax.evidence e ON e.id = re.evidence_id
JOIN ax.source_document d ON d.id = e.document_id
LEFT JOIN ax.document_section s ON s.id = e.section_id;

-- 검토 대기열
CREATE OR REPLACE VIEW ax.v_review_queue AS
SELECT ra.id AS assignment_id, ra.review_role, ra.assignee_user_id, ra.assignee_dept_id,
       ra.status AS assignment_status, ra.assigned_at, ra.due_at,
       (ra.due_at IS NOT NULL AND ra.due_at < now()) AS is_overdue,
       o.recommendation_id, o.linkage_type_name, o.total_score, o.demand_title, o.source_cards,
       o.evidence_count, o.open_confirmations, o.status AS recommendation_status
FROM ax.review_assignment ra
JOIN ax.v_recommendation_overview o ON o.recommendation_id = ra.recommendation_id
WHERE ra.status IN ('PENDING','IN_PROGRESS');

-- KPI: 추천결과 원문 근거 연결률 (목표 100%) / 최종 검토율 (목표 100%)
CREATE OR REPLACE VIEW ax.v_kpi_recommendation AS
SELECT r.match_run_id,
       count(*)                                                            AS recommendations,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ax.recommendation_evidence re
                                      WHERE re.recommendation_id = r.id))  AS with_evidence,
       round(100.0 * count(*) FILTER (WHERE EXISTS (SELECT 1 FROM ax.recommendation_evidence re
                                      WHERE re.recommendation_id = r.id)) / NULLIF(count(*), 0), 1)
                                                                           AS evidence_coverage_pct,
       count(*) FILTER (WHERE r.final_decision_code IS NOT NULL)           AS finally_reviewed,
       round(100.0 * count(*) FILTER (WHERE r.final_decision_code IS NOT NULL) / NULLIF(count(*), 0), 1)
                                                                           AS final_review_pct,
       count(*) FILTER (WHERE r.final_decision_code = 'ADOPT')             AS adopted
FROM ax.recommendation r
WHERE NOT r.is_excluded AND r.status <> 'WITHDRAWN'
GROUP BY r.match_run_id;

-- KPI: 전문가 주요 후보의 상위 K 포함 여부 (목표 포함률 ≥ 80%)
CREATE OR REPLACE VIEW ax.v_eval_topk_hits AS
SELECT er.id AS eval_run_id, er.top_k, gt.case_id, gt.id AS ground_truth_id, gt.importance,
       gt.linkage_type_code AS expected_linkage_type,
       hit.rank AS hit_rank,
       hit.linkage_type_code AS predicted_linkage_type,
       (hit.rank IS NOT NULL AND hit.rank <= er.top_k) AS is_hit
FROM ax.eval_run er
JOIN ax.eval_run_case erc ON erc.eval_run_id = er.id
JOIN ax.eval_ground_truth gt ON gt.case_id = erc.case_id
LEFT JOIN LATERAL (
    SELECT min(r.rank) AS rank, (array_agg(r.linkage_type_code ORDER BY r.rank))[1] AS linkage_type_code
    FROM ax.recommendation r
    WHERE r.match_run_id = erc.match_run_id
      AND NOT r.is_excluded
      AND (   (gt.expected_card_id    IS NOT NULL AND EXISTS (
                 SELECT 1 FROM ax.recommendation_source_card s
                 WHERE s.recommendation_id = r.id AND s.card_id = gt.expected_card_id))
           OR (gt.expected_demand_id  IS NOT NULL AND r.demand_id         = gt.expected_demand_id)
           OR (gt.expected_program_id IS NOT NULL AND r.target_program_id = gt.expected_program_id)
           OR (gt.expected_project_id IS NOT NULL AND r.target_project_id = gt.expected_project_id))
) hit ON true;

CREATE OR REPLACE VIEW ax.v_kpi_eval AS
SELECT h.eval_run_id, h.top_k,
       count(*) FILTER (WHERE h.importance = 'MAJOR')                      AS major_candidates,
       count(*) FILTER (WHERE h.importance = 'MAJOR' AND h.is_hit)         AS major_hits,
       round(100.0 * count(*) FILTER (WHERE h.importance = 'MAJOR' AND h.is_hit)
             / NULLIF(count(*) FILTER (WHERE h.importance = 'MAJOR'), 0), 1) AS major_topk_recall_pct,
       round(100.0 * count(*) FILTER (WHERE h.is_hit AND h.predicted_linkage_type = h.expected_linkage_type)
             / NULLIF(count(*) FILTER (WHERE h.is_hit AND h.expected_linkage_type IS NOT NULL), 0), 1)
                                                                           AS linkage_type_accuracy_pct
FROM ax.v_eval_topk_hits h
GROUP BY h.eval_run_id, h.top_k;

-- KPI: 업무시간 단축률 (조사 70%, 검토자료 60% 목표)
CREATE OR REPLACE VIEW ax.v_kpi_work_time AS
SELECT task_type,
       avg(minutes) FILTER (WHERE method = 'MANUAL') AS avg_manual_min,
       avg(minutes) FILTER (WHERE method = 'AX')     AS avg_ax_min,
       round(100.0 * (1 - avg(minutes) FILTER (WHERE method = 'AX')
                          / NULLIF(avg(minutes) FILTER (WHERE method = 'MANUAL'), 0)), 1) AS reduction_pct
FROM ax.work_time_measurement
GROUP BY task_type;
