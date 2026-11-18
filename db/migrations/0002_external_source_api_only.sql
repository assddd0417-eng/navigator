-- 외부 수집은 실제 API 로 연결되는 출처만 쓴다.
-- 연결 부품이 없는 출처(NICE·KED·NTIS·인증서 업로드)와 API 없이 홈페이지를 읽는 국기원 공지사항은 끈다.
-- 행은 지우지 않는다 (기존 수집 기록·출처 표시가 이 행을 가리킴). 다시 쓰려면 is_active = true.
UPDATE ax.external_source
   SET is_active = false, updated_at = now()
 WHERE code IN ('NICE', 'KED', 'NTIS', 'CERT_DOC', 'KRIT');
