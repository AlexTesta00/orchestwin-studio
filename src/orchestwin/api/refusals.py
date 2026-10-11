from enum import Enum

from fastapi import HTTPException


def refusal(status_code: int, code: str, **extra: object) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, **extra})


def conflict(code: str, *, proposal_issue: Enum | None = None) -> HTTPException:
    extra = {} if proposal_issue is None else {"proposal_issue": proposal_issue.value}
    return refusal(409, code, **extra)
