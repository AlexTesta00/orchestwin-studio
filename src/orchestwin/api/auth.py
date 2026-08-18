"""HTTP authentication contracts for local accounts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

from orchestwin.identity.application import (
    AuthenticatedSession,
    AuthenticationResult,
    AuthenticationStatus,
    IdentityApplicationService,
)
from orchestwin.identity.domain import UserAccount

bearer_scheme = HTTPBearer(auto_error=False)


class AuthApiSettings(BaseSettings):
    """Immutable refresh-cookie configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="ORCHESTWIN_AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    refresh_cookie_name: str = "orchestwin_refresh"
    refresh_cookie_path: str = "/api/v1/auth"
    refresh_cookie_secure: bool = False
    refresh_cookie_same_site: Literal[
        "lax",
        "strict",
        "none",
    ] = "lax"
    refresh_cookie_max_age_seconds: int = Field(
        default=2592000,
        ge=60,
        le=31536000,
    )

    @field_validator(
        "refresh_cookie_name",
        "refresh_cookie_path",
    )
    @classmethod
    def validate_cookie_text(
        cls,
        value: str,
    ) -> str:
        """Require non-empty cookie identifiers."""
        normalized = value.strip()

        if not normalized:
            raise ValueError("refresh-cookie values must not be empty")

        return normalized

    @model_validator(mode="after")
    def validate_same_site_none(self) -> AuthApiSettings:
        """Require Secure when SameSite=None is configured."""
        if self.refresh_cookie_same_site == "none" and not self.refresh_cookie_secure:
            raise ValueError("SameSite=None requires a Secure cookie")

        return self


class RegisterRequest(BaseModel):
    """Local account registration request."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        min_length=3,
        max_length=320,
    )
    password: str = Field(
        min_length=15,
        max_length=1024,
        repr=False,
    )


class LoginRequest(BaseModel):
    """Local account login request."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        min_length=1,
        max_length=320,
    )
    password: str = Field(
        min_length=1,
        max_length=1024,
        repr=False,
    )


class UserResponse(BaseModel):
    """Safe account representation returned by the API."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_domain(
        cls,
        user: UserAccount,
    ) -> UserResponse:
        """Map an immutable domain account to an API response."""
        return cls(
            id=user.id,
            email=user.email.value,
            is_active=user.is_active,
            created_at=user.created_at,
        )


class AuthenticationResponse(BaseModel):
    """Access token and safe user representation."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserResponse


def identity_service_dependency(
    request: Request,
) -> IdentityApplicationService:
    """Return the configured identity application service."""
    service = request.app.state.identity_service

    if service is None:
        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail="identity_service_unavailable",
        )

    return service


async def current_user_dependency(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    service: Annotated[
        IdentityApplicationService,
        Depends(identity_service_dependency),
    ],
) -> UserAccount:
    """Resolve the authenticated user from a bearer token."""
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise unauthorized_exception()

    user = await service.current_user(credentials.credentials)

    if user is None:
        raise unauthorized_exception()

    return user


def unauthorized_exception() -> HTTPException:
    """Create one generic bearer authentication error."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid_authentication",
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )


def set_refresh_cookie(
    response: Response,
    *,
    token: str,
    settings: AuthApiSettings,
) -> None:
    """Set the opaque refresh token in an HttpOnly cookie."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=(settings.refresh_cookie_max_age_seconds),
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_same_site,
    )


def delete_refresh_cookie(
    response: Response,
    *,
    settings: AuthApiSettings,
) -> None:
    """Expire the configured refresh cookie."""
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_same_site,
    )


def authenticated_response(
    authenticated: AuthenticatedSession,
) -> AuthenticationResponse:
    """Map authenticated credentials into the public response."""
    return AuthenticationResponse(
        access_token=(authenticated.access_token.token),
        expires_at=(authenticated.access_token.expires_at),
        user=UserResponse.from_domain(authenticated.user),
    )


def require_authenticated(
    result: AuthenticationResult,
) -> AuthenticatedSession:
    """Return credentials from a successful result."""
    if result.authenticated is None:
        raise RuntimeError("authenticated result did not contain credentials")

    return result.authenticated


def invalid_refresh_response(
    *,
    detail: str,
    settings: AuthApiSettings,
) -> JSONResponse:
    """Return an authentication error while deleting refresh state."""
    response = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "detail": detail,
        },
    )

    delete_refresh_cookie(
        response,
        settings=settings,
    )

    return response


def create_auth_router(
    settings: AuthApiSettings,
) -> APIRouter:
    """Create the local authentication router."""
    router = APIRouter(
        prefix="/auth",
        tags=["authentication"],
    )

    @router.post(
        "/register",
        response_model=AuthenticationResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Register a local account",
        operation_id="registerLocalAccount",
    )
    async def register(
        payload: RegisterRequest,
        response: Response,
        service: Annotated[
            IdentityApplicationService,
            Depends(identity_service_dependency),
        ],
    ) -> AuthenticationResponse:
        result = await service.register(
            email=payload.email,
            password=payload.password,
        )

        if result.status is AuthenticationStatus.EMAIL_ALREADY_REGISTERED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="email_already_registered",
            )

        if result.status is AuthenticationStatus.INVALID_REGISTRATION:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_registration",
            )

        authenticated = require_authenticated(result)

        set_refresh_cookie(
            response,
            token=authenticated.refresh_token.token,
            settings=settings,
        )

        return authenticated_response(authenticated)

    @router.post(
        "/login",
        response_model=AuthenticationResponse,
        summary="Log in with local credentials",
        operation_id="loginLocalAccount",
    )
    async def login(
        payload: LoginRequest,
        response: Response,
        service: Annotated[
            IdentityApplicationService,
            Depends(identity_service_dependency),
        ],
    ) -> AuthenticationResponse:
        result = await service.login(
            email=payload.email,
            password=payload.password,
        )

        if result.status is not AuthenticationStatus.AUTHENTICATED:
            raise unauthorized_exception()

        authenticated = require_authenticated(result)

        set_refresh_cookie(
            response,
            token=authenticated.refresh_token.token,
            settings=settings,
        )

        return authenticated_response(authenticated)

    @router.post(
        "/refresh",
        response_model=AuthenticationResponse,
        summary="Rotate the refresh session",
        operation_id="refreshLocalSession",
    )
    async def refresh(
        request: Request,
        response: Response,
        service: Annotated[
            IdentityApplicationService,
            Depends(identity_service_dependency),
        ],
    ) -> AuthenticationResponse | JSONResponse:
        raw_token = request.cookies.get(
            settings.refresh_cookie_name,
            "",
        )
        result = await service.refresh(raw_token)

        if result.status is not AuthenticationStatus.AUTHENTICATED:
            return invalid_refresh_response(
                detail=result.status.value,
                settings=settings,
            )

        authenticated = require_authenticated(result)

        set_refresh_cookie(
            response,
            token=authenticated.refresh_token.token,
            settings=settings,
        )

        return authenticated_response(authenticated)

    @router.post(
        "/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Log out the current refresh session",
        operation_id="logoutLocalSession",
    )
    async def logout(
        request: Request,
        response: Response,
        service: Annotated[
            IdentityApplicationService,
            Depends(identity_service_dependency),
        ],
    ) -> None:
        raw_token = request.cookies.get(
            settings.refresh_cookie_name,
            "",
        )

        if raw_token:
            await service.logout(raw_token)

        delete_refresh_cookie(
            response,
            settings=settings,
        )

    @router.get(
        "/me",
        response_model=UserResponse,
        summary="Return the current local account",
        operation_id="getCurrentLocalAccount",
    )
    async def me(
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
    ) -> UserResponse:
        return UserResponse.from_domain(user)

    return router
