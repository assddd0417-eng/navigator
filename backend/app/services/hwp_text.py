"""공고 첨부(HWP·HWPX·PDF) 본문 텍스트 추출.

- HWP 5.0: OLE 파일. BodyText/SectionN 스트림을 (압축이면 raw deflate 로) 풀고 PARA_TEXT 레코드만 읽는다.
  표 안 글자도 PARA_TEXT 라 같이 나온다. 배포용(암호화) 문서는 ViewText 라 읽지 못한다 → UnsupportedFile.
- HWPX: zip 안 Contents/section*.xml 의 <hp:t> 글자를 문단 단위로 잇는다.
- PDF: pdfplumber 로 쪽마다.
그 밖의 형식(zip, xlsx, 이미지)은 UnsupportedFile.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from xml.etree import ElementTree

MAX_CHARS = 200_000
HWPTAG_PARA_TEXT = 67
# 8 글자(16바이트) 를 차지하는 확장·인라인 제어문자. 0, 10, 13, 24~31 은 1 글자.
_WIDE_CONTROLS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


class UnsupportedFile(Exception):
    pass


def detect_kind(name: str, data: bytes) -> str:
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "hwp"
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:2] == b"PK":
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext == "hwpx":
            return "hwpx"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if any(n.startswith("Contents/section") for n in z.namelist()):
                    return "hwpx"
        except zipfile.BadZipFile:
            pass
        return ext or "zip"
    return name.rsplit(".", 1)[-1].lower() if "." in name else "unknown"


def extract_text(name: str, data: bytes) -> str:
    kind = detect_kind(name, data)
    if kind == "hwp":
        text = _hwp5(data)
    elif kind == "hwpx":
        text = _hwpx(data)
    elif kind == "pdf":
        text = _pdf(data)
    else:
        raise UnsupportedFile(f"{kind} 형식은 읽지 않습니다")
    return _tidy(text)[:MAX_CHARS]


def _tidy(text: str) -> str:
    # HWP 는 UTF-16 코드 단위로 읽어 서로게이트 쌍이 갈라져 있다. 다시 붙이고 짝 없는 것은 버린다.
    text = text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace").replace("\x00", "")
    lines = [re.sub(r"[ \t 　]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def _hwp5(data: bytes) -> str:
    import olefile
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except OSError as e:
        raise UnsupportedFile(f"HWP 파일을 열 수 없습니다: {e}") from None
    with ole:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 0x04:
            raise UnsupportedFile("배포용(암호화) HWP 는 읽지 않습니다")
        compressed = bool(flags & 0x01)
        sections = sorted((e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText"
                           and e[1].startswith("Section")), key=lambda e: int(e[1][7:] or 0))
        parts = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            parts.append(_hwp_records(raw))
    return "\n".join(parts)


def _hwp_records(buf: bytes) -> str:
    out: list[str] = []
    pos, n = 0, len(buf)
    while pos + 4 <= n:
        head = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        tag, size = head & 0x3FF, (head >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        if tag == HWPTAG_PARA_TEXT:
            out.append(_para_text(buf[pos:pos + size]))
        pos += size
    return "\n".join(out)


def _para_text(rec: bytes) -> str:
    chars: list[str] = []
    i, n = 0, len(rec) // 2
    while i < n:
        c = struct.unpack_from("<H", rec, i * 2)[0]
        if c < 32:
            if c in _WIDE_CONTROLS:
                i += 8
                continue
            if c == 9:
                chars.append("\t")
            elif c in (10, 13):
                chars.append("\n")
            i += 1
            continue
        chars.append(chr(c))
        i += 1
    return "".join(chars)


def _hwpx(data: bytes) -> str:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UnsupportedFile(f"HWPX 파일을 열 수 없습니다: {e}") from None
    names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                   key=lambda n: int(re.findall(r"\d+", n)[-1]))
    paras: list[str] = []
    for name in names:
        root = ElementTree.fromstring(z.read(name))
        for p in root.iter():
            if not p.tag.endswith("}p"):
                continue
            # 표 안 문단은 자기 문단에서 다시 나오므로 이 문단 바로 아래 run 의 글자만
            text = "".join(t.text or "" for run in p if run.tag.endswith("}run")
                           for t in run if t.tag.endswith("}t"))
            paras.append(text)
    return "\n".join(paras)


def _pdf(data: bytes) -> str:
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((pg.dedupe_chars().extract_text() or "") for pg in pdf.pages)
    except Exception as e:  # noqa: BLE001  pdfminer 는 여러 종류의 예외를 낸다
        raise UnsupportedFile(f"PDF 를 읽을 수 없습니다: {type(e).__name__}") from None
