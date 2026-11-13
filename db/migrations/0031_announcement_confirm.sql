-- 0031: 공고 요건 확인
--   announcement: 담당자가 자격요건을 확인한 시각·사람. 수집·업로드한 공고는 확인 전까지 작성중
--   v_announcement: 0030 에서 늘어난 칸(posted_on, series_key, body_text)과 확인 여부를 함께 보이게 다시 만든다
SET search_path = ax, public;

ALTER TABLE ax.announcement
    ADD COLUMN requirements_confirmed_at timestamptz,
    ADD COLUMN requirements_confirmed_by bigint REFERENCES ax.app_user(id);

DROP VIEW ax.v_announcement;
CREATE VIEW ax.v_announcement AS
SELECT a.*,
       CASE WHEN a.status <> 'PUBLISHED'                                  THEN a.status
            WHEN a.receipt_end IS NOT NULL AND a.receipt_end < current_date  THEN 'CLOSED'
            WHEN a.receipt_start IS NOT NULL AND a.receipt_start > current_date THEN 'UPCOMING'
            ELSE 'OPEN' END AS receipt_state,
       p.program_code, p.name AS program_name,
       (SELECT count(*) FROM ax.announcement_requirement r WHERE r.announcement_id = a.id)                    AS requirement_count,
       (SELECT count(*) FROM ax.announcement_requirement r WHERE r.announcement_id = a.id AND r.is_mandatory) AS mandatory_count,
       (SELECT count(*) FROM ax.announcement_tech_need t WHERE t.announcement_id = a.id)                      AS tech_need_count,
       (SELECT count(*) FROM ax.announcement_attachment t WHERE t.announcement_id = a.id)                     AS attachment_count
  FROM ax.announcement a
  LEFT JOIN ax.program p ON p.id = a.program_id;
