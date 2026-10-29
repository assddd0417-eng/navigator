"""스모크 테스트용 PDF 픽스처 생성 (pip install reportlab).

    python scripts/fixtures/make_pdf_fixtures.py

- report_ko.pdf    : 한국어 3쪽 (2쪽은 텍스트 없는 그림 쪽 → 경고 대상)
- scanned.pdf      : 텍스트 레이어가 없는 2쪽 (스캔본 흉내 → 422 no_text_layer)
- encrypted.pdf    : 열람 암호가 걸린 PDF (→ 422 encrypted_pdf)
결과 파일은 저장소에 커밋되어 있어 스모크 실행에 reportlab 이 필요하지 않다.
"""
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent
FONT = "HYSMyeongJo-Medium"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

REPORT = [
    ["- 1 -", "4.3 미해결 기술 및 후속 연구 필요사항",
     "광대역 재밍 환경에서 주파수 도약 동기 유지 시간이 목표 10초 대비",
     "6초로 부족하여 후속 연구가 필요함.",
     "• 시험은 실내 전파차폐실과 야외 시험장에서 수행하였음"],
    [],
    ["5. 결론", "항재밍 데이터링크 모뎀의 국산화 가능성을 확인하였으며 체계 적용 시험이 남아 있음."],
]


def write(name: str, pages: list[list[str]], encrypt: str | None = None) -> None:
    c = canvas.Canvas(str(OUT / name), encrypt=encrypt, invariant=1)  # invariant: 재생성해도 같은 바이트
    for lines in pages:
        if not lines:
            c.rect(72, 300, 400, 300, fill=1)
        c.setFont(FONT, 11)
        for i, line in enumerate(lines):
            c.drawString(72, 780 - 18 * i, line)
        c.showPage()
    c.save()


write("report_ko.pdf", REPORT)
write("scanned.pdf", [[], []])
write("encrypted.pdf", REPORT[:1], encrypt="secret")
