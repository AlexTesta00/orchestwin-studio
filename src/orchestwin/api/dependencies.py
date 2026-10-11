from fastapi import HTTPException, Request


def app_service(attribute: str, detail: str | dict[str, str | None]):
    def dependency(request: Request):
        service = getattr(request.app.state, attribute, None)
        if service is None:
            raise HTTPException(503, detail=detail)
        return service

    return dependency
