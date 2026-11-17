-- 국방기술 용어 사전 시작본 (선택). 여러 번 실행해도 안전 (이미 있는 짝은 건너뜀).
-- 넣은 뒤 화면 '용어 사전'에서 '추천 매칭에 적용'을 누르거나 POST /synonyms/apply 를 불러야 임베딩에 반영된다.
-- 출처는 일반 국방·공학 용어 표기이며, 부서 용어집을 받으면 엑셀 올리기로 보강한다.
-- CI·테스트 시드에는 넣지 않는다 (적중률 측정 기준 데이터를 바꾸지 않기 위해).
INSERT INTO ax.term_synonym (canonical_term, synonym, relation, domain, source_note) VALUES
  ('능동위상배열 레이더', 'AESA 레이더', 'ABBREVIATION', '레이더', '시작본'),
  ('능동위상배열 레이더', 'AESA', 'ABBREVIATION', '레이더', '시작본'),
  ('위상배열 안테나', 'phased array antenna', 'EN_KO', '통신·레이더', '시작본'),
  ('합성개구레이더', 'SAR', 'ABBREVIATION', '감시정찰', '시작본'),
  ('전자광학/적외선', 'EO/IR', 'ABBREVIATION', '감시정찰', '시작본'),
  ('전자광학/적외선', '전자광학 적외선', 'SYNONYM', '감시정찰', '시작본'),
  ('적외선 탐색추적장비', 'IRST', 'ABBREVIATION', '감시정찰', '시작본'),
  ('무인항공기', 'UAV', 'EN_KO', '무인체계', '시작본'),
  ('무인항공기', '무인기', 'SYNONYM', '무인체계', '시작본'),
  ('무인항공기', '드론', 'SYNONYM', '무인체계', '시작본'),
  ('무인지상차량', 'UGV', 'EN_KO', '무인체계', '시작본'),
  ('무인수상정', 'USV', 'EN_KO', '무인체계', '시작본'),
  ('무인잠수정', 'UUV', 'EN_KO', '무인체계', '시작본'),
  ('항재밍', 'anti-jamming', 'EN_KO', '통신', '시작본'),
  ('항재밍', '재밍 방지', 'SYNONYM', '통신', '시작본'),
  ('전자전', 'EW', 'ABBREVIATION', '전자전', '시작본'),
  ('위성항법', 'GNSS', 'ABBREVIATION', '항법', '시작본'),
  ('위성항법', 'GPS', 'RELATED', '항법', '시작본'),
  ('관성항법장치', 'INS', 'ABBREVIATION', '항법', '시작본'),
  ('지휘통제', 'C2', 'ABBREVIATION', '지휘통제', '시작본'),
  ('지휘통제통신컴퓨터정보', 'C4I', 'ABBREVIATION', '지휘통제', '시작본'),
  ('인공지능', 'AI', 'ABBREVIATION', 'AI', '시작본'),
  ('표적 자동탐지', 'ATR', 'ABBREVIATION', 'AI', '시작본'),
  ('표적 자동탐지', '자동표적인식', 'SYNONYM', 'AI', '시작본'),
  ('질화갈륨', 'GaN', 'EN_KO', '소자', '시작본'),
  ('송수신 모듈', 'TRM', 'ABBREVIATION', '레이더', '시작본'),
  ('송수신 모듈', 'T/R 모듈', 'SYNONYM', '레이더', '시작본'),
  ('열관리', 'thermal management', 'EN_KO', '전원·열', '시작본'),
  ('리튬이온 배터리', '리튬 이차전지', 'SYNONYM', '전원·열', '시작본'),
  ('부품 국산화', '국산화 개발', 'SYNONYM', '정책', '시작본'),
  ('기술성숙도', 'TRL', 'ABBREVIATION', '정책', '시작본'),
  ('레이더', '능동위상배열 레이더', 'NARROWER', '레이더', '시작본')
ON CONFLICT (canonical_term, synonym) DO NOTHING;
