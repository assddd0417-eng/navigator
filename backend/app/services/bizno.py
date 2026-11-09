"""사업자등록번호 형식 검사.

국세청 체크섬: 앞 9자리에 가중치 1,3,7,1,3,7,1,3,5 를 곱해 더하고,
9번째 자리×5 의 십의 자리를 더한 뒤 (10 - 합 % 10) % 10 이 마지막 자리와 같아야 한다.
형식 검사는 진위확인이 아니다. 실제 등록 여부·대표자 일치는 국세청 진위확인(services.external.nts)이 본다.
"""
import re

_WEIGHTS = (1, 3, 7, 1, 3, 7, 1, 3, 5)


class InvalidBizNo(ValueError):
    pass


def normalize(raw: str) -> str:
    """하이픈·공백을 지우고 숫자 10자리로. 형식이 틀리면 InvalidBizNo."""
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
