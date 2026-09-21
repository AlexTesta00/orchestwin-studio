"""Public validation errors without echoing passwords or request bodies."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def request_validation_error(request: Request, error: RequestValidationError):
    errors = error.errors()
    path = request.url.path
    code = "invalid_request"
    if path.endswith("/auth/register"):
        code = "invalid_registration"
        for issue in errors:
            if issue["loc"] == ("body", "password"):
                code = {
                    "string_too_short": "password_too_short",
                    "string_too_long": "password_too_long",
                }.get(issue["type"], "invalid_registration")
                break
    elif path.endswith("/auth/login"):
        code = "invalid_authentication"
    return JSONResponse(
        status_code=422,
        content={
            "detail": code,
            "errors": [{"loc": list(issue["loc"]), "type": issue["type"]} for issue in errors],
        },
    )
