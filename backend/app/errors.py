"""DB 예외 → HTTP 응답 매핑.

검토 진입 가드, 최종판정 권한, 추가 전용 보호 같은 업무 규칙은 DB 트리거가 강제한다.
트리거의 한국어 메시지를 그대로 detail 로 돌려준다.
"""
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from psycopg import errors as pg


class NotFound(HTTPException):
    def __init__(self, what: str, key: object):
        super().__init__(status.HTTP_404_NOT_FOUND, f"{what} {key} 을(를) 찾을 수 없습니다")


class Conflict(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status.HTTP_409_CONFLICT, detail)


_MAP: list[tuple[type[Exception], int, str]] = [
    (pg.CheckViolation, status.HTTP_422_UNPROCESSABLE_CONTENT, "check_violation"),
    (pg.InsufficientPrivilege, status.HTTP_403_FORBIDDEN, "insufficient_privilege"),
    (pg.UniqueViolation, status.HTTP_409_CONFLICT, "unique_violation"),
    (pg.ForeignKeyViolation, status.HTTP_422_UNPROCESSABLE_CONTENT, "foreign_key_violation"),
    (pg.NotNullViolation, status.HTTP_422_UNPROCESSABLE_CONTENT, "not_null_violation"),
    (pg.InvalidTextRepresentation, status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_input"),
]


def install_error_handlers(app: FastAPI) -> None:
    for exc_type, code, kind in _MAP:
        def handler(request: Request, exc: Exception, code: int = code, kind: str = kind) -> JSONResponse:
            diag = getattr(exc, "diag", None)
            detail = (diag.message_primary if diag and diag.message_primary else str(exc))
            body = {"detail": detail, "kind": kind}
            if diag and diag.constraint_name:
                body["constraint"] = diag.constraint_name
            return JSONResponse(body, status_code=code, headers={"X-Request-Id": request.state.request_id})

        app.add_exception_handler(exc_type, handler)
