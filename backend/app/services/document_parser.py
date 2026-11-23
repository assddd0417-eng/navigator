"""업로드 파일(PDF·텍스트) → 텍스트 추출 → RAG 청크.

- PDF 는 pdfplumber(pdfminer.six) 로 쪽마다 텍스트를 뽑는다. pypdf 는 한국어 PDF 에서
  어절 사이 공백을 자주 잃어("정보가부서·사업트랙별로분산") 검색·임베딩 품질이 떨어져 쓰지 않는다.
- 청크는 쪽 경계를 넘지 않는다 → 모든 청크가 정확한 출처 쪽(page_start=page_end)을 가진다.
  쪽 안에서는 줄을 문단으로 묶고(글머리표·문장 끝 기준), 문단을 chunk_max_chars 이내로 채워 담는다.
- 텍스트 레이어가 없는 쪽(스캔본)은 OCR 하지 않는다. 전부 비면 422, 일부만 비면 경고로 알린다.
- 암호가 걸린 PDF·손상 파일·지원하지 않는 형식은 ParseError(422/415) 로 명확히 거부한다.

CPU 를 쓰는 동기 함수이므로 라우터에서 스레드풀로 호출한다.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import PurePath

PARSER_NAME = "pdfplumber"

# 쪽에 이보다 적은 글자(공백 제외)만 있으면 "텍스트 없음"으로 본다 (스캔본·이미지 쪽)
MIN_PAGE_CHARS = 20

_PAGE_NUMBER = re.compile(r"^[\s\-–—(]*\d{1,4}(\s*/\s*\d{1,4})?[\s\-–—)]*$")
_BULLET = re.compile(r"^\s*([•·∙○●◦▪▫■□◆◇▶▷►※\-–*]|\(?\d{1,2}[.)]\s|\(?[가-하][.)]\s|[①-⑳]|ㅇ\s|\d+(\.\d+)+\.?\s)")
_SENTENCE_END = re.compile(r"([.!?。:]|(다|함|음|임|됨|요))[\"'”’)\]]*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+")


class ParseError(Exception):
    """업로드 파일을 처리할 수 없음. kind 는 프론트·스모크가 구분하는 오류 코드."""

    def __init__(self, kind: str, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.status_code = status_code


@dataclass
class ParsedChunk:
    content: str
    page_start: int | None
    page_end: int | None
    location: dict


@dataclass
class ParsedDocument:
    filename: str
    file_type: str                     # "pdf" | "text"
    parser: str
    file_sha256: str
    page_count: int | None
    pages_without_text: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    chunks: list[ParsedChunk] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(c.content) for c in self.chunks)


def parse_upload(data: bytes, filename: str, *, max_pages: int, chunk_max_chars: int) -> ParsedDocument:
    """파일 내용으로 형식을 판별해 파싱한다 (확장자보다 PDF 시그니처 우선)."""
    if not data:
        raise ParseError("empty_file", "빈 파일입니다")
    ext = PurePath(filename or "").suffix.lower()
    digest = hashlib.sha256(data).hexdigest()
    if b"%PDF-" in data[:1024]:  # 앞에 쓰레기 바이트가 붙은 PDF 도 허용 (pdfminer 와 같은 기준)
        return _parse_pdf(data, filename, digest, max_pages, chunk_max_chars)
    if ext == ".pdf":
        raise ParseError("corrupt_pdf", "PDF 파일이 아니거나 손상되었습니다 (PDF 시그니처 없음)")
    if ext in (".txt", ".md", ".text", ""):
        return _parse_text(data, filename, digest, chunk_max_chars)
    raise ParseError("unsupported_type", f"지원하지 않는 파일 형식입니다 ({ext}). PDF·TXT·MD 만 올릴 수 있습니다", 415)


# ---- PDF --------------------------------------------------------------------
def _parse_pdf(data: bytes, filename: str, digest: str, max_pages: int, chunk_max_chars: int) -> ParsedDocument:
    import pdfplumber
    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    doc = ParsedDocument(filename, "pdf", PARSER_NAME, digest, None)
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            doc.page_count = len(pdf.pages)
            if doc.page_count == 0:
                raise ParseError("corrupt_pdf", "PDF 에 쪽이 없습니다")
            if doc.page_count > max_pages:
                raise ParseError("too_many_pages", f"쪽 수({doc.page_count})가 최대 {max_pages}쪽을 넘습니다", 413)
            for page in pdf.pages:
                text = page.extract_text() or ""
                page.close()  # 쪽 단위 캐시 해제 (큰 문서 메모리)
                lines = _clean_lines(text)
                if sum(len(l.replace(" ", "")) for l in lines) < MIN_PAGE_CHARS:
                    doc.pages_without_text.append(page.page_number)
                    continue
                for i, content in enumerate(_pack(_paragraphs(lines), chunk_max_chars)):
                    doc.chunks.append(ParsedChunk(content, page.page_number, page.page_number,
                                                  {"page": page.page_number, "chunk_in_page": i, "parser": PARSER_NAME}))
    except ParseError:
        raise
    except PdfminerException as e:
        cause = e.args[0] if e.args else e
        if isinstance(cause, (PDFPasswordIncorrect, PDFEncryptionError)):
            raise ParseError("encrypted_pdf", "암호가 걸린 PDF 입니다. 암호를 해제한 파일을 올려 주세요") from e
        raise ParseError("corrupt_pdf", f"PDF 를 읽을 수 없습니다 (손상된 파일): {cause}") from e
    except Exception as e:  # pdfminer 는 손상 유형별로 다양한 예외를 낸다
        raise ParseError("corrupt_pdf", f"PDF 를 읽을 수 없습니다 (손상된 파일): {type(e).__name__}") from e

    if not doc.chunks:
        raise ParseError("no_text_layer",
                         f"PDF {doc.page_count}쪽 모두에서 텍스트를 찾지 못했습니다. 스캔 이미지 PDF 로 보이며, "
                         "OCR 은 지원하지 않습니다. 텍스트가 포함된 PDF 를 올려 주세요")
    if doc.pages_without_text:
        doc.warnings.append(
            f"텍스트가 없는 쪽 {len(doc.pages_without_text)}개는 제외했습니다 (스캔·이미지 쪽, OCR 미지원): "
            f"{_page_ranges(doc.pages_without_text)}쪽")
    return doc


def _clean_lines(text: str) -> list[str]:
    # 일부 PDF(한글 편집기 출력)는 띄어쓰기를 '‧'(U+2027)로 내보낸다 → 공백으로
    text = text.replace("\u2027", " ")
    lines = [re.sub(r"[ \t 　]+", " ", l).strip() for l in text.replace("\x00", "").splitlines()]
    lines = [l for l in lines if l]
    # 머리·꼬리의 쪽 번호 줄("- 3 -", "3 / 120") 제거
    while lines and _PAGE_NUMBER.match(lines[0]):
        lines.pop(0)
    while lines and _PAGE_NUMBER.match(lines[-1]):
        lines.pop()
    return lines


def _paragraphs(lines: list[str]) -> list[str]:
    """PDF 줄바꿈은 시각적 줄바꿈이다 → 글머리표로 시작하거나 앞 줄이 문장으로 끝날 때만 문단을 끊는다."""
    paras: list[str] = []
    cur: list[str] = []
    for line in lines:
        if cur and (_BULLET.match(line) or _SENTENCE_END.search(cur[-1])):
            paras.append(" ".join(cur))
            cur = []
        cur.append(line)
    if cur:
        paras.append(" ".join(cur))
    return paras


# ---- 텍스트 ------------------------------------------------------------------
def _parse_text(data: bytes, filename: str, digest: str, chunk_max_chars: int) -> ParsedDocument:
    for enc in ("utf-8-sig", "cp949"):  # 공공기관 한글 텍스트 파일은 CP949(EUC-KR) 인 경우가 많다
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError("invalid_encoding", "텍스트 인코딩을 알 수 없습니다 (UTF-8·CP949 만 지원)")
    if "\x00" in text:
        raise ParseError("unsupported_type", "텍스트 파일이 아닙니다 (이진 파일)", 415)
    paras = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n"))]
    chunks = _pack([p for p in paras if p], chunk_max_chars)
    if not chunks:
        raise ParseError("empty_file", "본문 텍스트가 없습니다")
    doc = ParsedDocument(filename, "text", "text", digest, None)
    doc.chunks = [ParsedChunk(c, None, None, {"paragraph_group": i, "parser": "text"}) for i, c in enumerate(chunks)]
    return doc


# ---- 공통 --------------------------------------------------------------------
def _pack(paras: list[str], max_chars: int) -> list[str]:
    """문단을 순서대로 max_chars 이내 청크로 채운다. 긴 문단은 문장 → 글자 단위로 자른다."""
    pieces: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            pieces.append(p)
            continue
        for s in _SENTENCE_SPLIT.split(p):
            pieces.extend(s[i:i + max_chars] for i in range(0, len(s), max_chars))
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + 1 + len(piece) > max_chars:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{piece}" if cur else piece
    if cur:
        chunks.append(cur)
    return chunks


def _page_ranges(pages: list[int]) -> str:
    out: list[str] = []
    start = prev = pages[0]
    for p in pages[1:] + [None]:
        if p is not None and p == prev + 1:
            prev = p
            continue
        out.append(str(start) if start == prev else f"{start}–{prev}")
        if p is not None:
            start = prev = p
    return ", ".join(out)
