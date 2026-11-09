"""사업자등록번호 형식·검증번호 검사 (진위확인은 external/nts.py)."""
import re

_WEIGHTS = (1, 3, 7, 1, 3, 7, 1, 3, 5)


class InvalidBizNo(ValueError):
    pass


def normalize(raw: str) -> str:
    digits = re.sub(r"[\s-]", "", raw or "")
    if not re.fullmatch(r"\d{10}", digits):
        raise InvalidBizNo("사업자번호는 숫자 10자리입니다 (예: 123-45-67890)")
    if not checksum_ok(digits):
        raise InvalidBizNo("사업자번호 형식이 올바르지 않습니다 (검증번호 불일치)")
    return digits


def checksum_ok(digits: str) -> bool:
    d = [int(c) for c in digits]
    total = sum(a * b for a, b in zip(d[:9], _WEIGHTS)) + (d[8] * 5) // 10
    return (10 - total % 10) % 10 == d[9]


def format_bizno(digits: str) -> str:
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
