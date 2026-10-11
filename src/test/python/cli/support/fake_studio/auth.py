from __future__ import annotations

import email.utils
from collections.abc import Mapping, Sequence
from datetime import timedelta
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    all_agent_catalog_entries,
)
from orchestwin.identity.domain import InvalidEmailAddress, NormalizedEmail
from orchestwin.identity.passwords import (
    PasswordPolicy,
    PasswordPolicyError,
    PasswordPolicyViolation,
)
from orchestwin.models.proposal_tasks import TASKS as PROPOSAL_TASKS

from .common import _stamp
from .fields import _Fields
from .values import (
    ACCOUNTS,
    LOCAL_OWNER,
    MODEL,
    _AccessToken,
    _Account,
    _Answer,
    _Invalid,
    _RefreshSession,
    _Refusal,
)

if TYPE_CHECKING:
    from .fields import _Call


ACCESS_SECONDS = 86_400
REFRESH_SECONDS = 2_592_000
COOKIE_NAME = "orchestwin_refresh"
COOKIE_PATH = "/api/v1/auth"
PER_GENERATION_MICROUSD = 2_000_000
READINESS_PROVIDER = "anthropic"
READINESS_MODEL_ENTRY = "general"
READINESS_KEY_ENV = "ORCHESTWIN_ANTHROPIC_API_KEY"
READINESS_REVISION = "0062_hosted_model_providers"
READINESS_CONTEXT_WINDOW = 200_000
READINESS_MAX_OUTPUT = 64_000
REGISTRATION_LENGTH_VIOLATIONS = {
    "string_too_short": PasswordPolicyViolation.TOO_SHORT,
    "string_too_long": PasswordPolicyViolation.TOO_LONG,
}
LOCAL_MODE = "local_mode"


class _AuthRoutes:
    def _route_health(self, call: _Call) -> _Answer:
        return _Answer(200, {"status": "ok"})

    def _route_access_mode(self, call: _Call) -> _Answer:
        return _Answer(
            200,
            {"access_mode": self.access_mode, "registration_open": self.access_mode == ACCOUNTS},
        )

    def _route_login(self, call: _Call) -> _Answer:
        if self.access_mode == LOCAL_OWNER:
            raise _Refusal(404, LOCAL_MODE)
        fields = _Fields(call.json(), ("email", "password"))
        email = fields.text("email", minimum=1, maximum=320)
        password = fields.text("password", minimum=1, maximum=1024)
        fields.check()
        account = self._accounts.get(_email_key(email or "") or "")
        if account is None or account.password != password:
            raise _Refusal(401, "invalid_authentication", {"WWW-Authenticate": "Bearer"})
        return self._signed_in(account, self._refresh_session(account, self._new_id()))

    def _route_register(self, call: _Call) -> _Answer:
        if self.access_mode == LOCAL_OWNER:
            raise _Refusal(404, LOCAL_MODE)
        try:
            fields = _Fields(call.json(), ("email", "password"))
            email = fields.text("email", minimum=3, maximum=320)
            password = fields.text("password", minimum=8, maximum=1024)
            fields.check()
        except _Invalid as invalid:
            return _Answer(
                422, {"detail": _registration_code(invalid.errors), "errors": invalid.errors}
            )
        key = _email_key(email or "")
        if key is None:
            raise _Refusal(422, "invalid_registration")
        try:
            PasswordPolicy().validate(password or "")
        except PasswordPolicyError as error:
            raise _Refusal(422, _password_code(error.violation)) from error
        if key in self._accounts:
            raise _Refusal(409, "email_already_registered")
        account = _Account(self._new_id(), key, password or "", self._now())
        self._accounts[key] = account
        self._accounts_by_id[account.id] = account
        answer = self._signed_in(account, self._refresh_session(account, self._new_id()))
        answer.status = 201
        return answer

    def _route_refresh(self, call: _Call) -> _Answer:
        token = call.cookie(COOKIE_NAME)
        session = self._sessions.get(token) if token else None
        refusal = self._refresh_refusal(session)
        if refusal is not None:
            if self.access_mode == LOCAL_OWNER:
                owner = self._local_owner()
                return self._signed_in(owner, self._refresh_session(owner, self._new_id()))
            return self._refused_refresh(refusal)
        assert session is not None
        account = self._accounts_by_id[session.account]
        replacement = self._refresh_session(account, session.family)
        session.rotated = True
        return self._signed_in(account, replacement)

    def _refresh_refusal(self, session: _RefreshSession | None) -> str | None:
        if session is None:
            return "invalid_refresh_token"
        if session.rotated or session.revoked:
            for other in self._sessions.values():
                if other.family == session.family:
                    other.revoked = True
            return "refresh_token_reuse_detected"
        if session.expires_at <= self._now():
            session.revoked = True
            return "expired_refresh_token"
        return None

    def _route_logout(self, call: _Call) -> _Answer:
        token = call.cookie(COOKIE_NAME)
        session = self._sessions.get(token) if token else None
        if session is not None and not session.rotated and not session.revoked:
            session.revoked = True
        return _Answer(204, headers={"Set-Cookie": self._cleared_cookie()})

    def _route_me(self, call: _Call) -> _Answer:
        return _Answer(200, _user_payload(call.account))

    def _refresh_session(self, account: _Account, family: str) -> _RefreshSession:
        self._tokens += 1
        session = _RefreshSession(
            token=f"fake-refresh-not-real-{self._tokens:06d}",
            account=account.id,
            family=family,
            expires_at=self._now() + timedelta(seconds=REFRESH_SECONDS),
        )
        self._sessions[session.token] = session
        return session

    def _signed_in(self, account: _Account, session: _RefreshSession) -> _Answer:
        self._tokens += 1
        token = f"fake-access-not-real-{self._tokens:06d}"
        expires_at = self._now() + timedelta(seconds=ACCESS_SECONDS)
        self._access[token] = _AccessToken(account.id, expires_at)
        cookie: SimpleCookie = SimpleCookie()
        cookie[COOKIE_NAME] = session.token
        morsel = cookie[COOKIE_NAME]
        morsel["max-age"] = REFRESH_SECONDS
        morsel["path"] = COOKIE_PATH
        morsel["httponly"] = True
        morsel["samesite"] = "lax"
        return _Answer(
            200,
            {
                "access_token": token,
                "token_type": "bearer",
                "expires_at": _stamp(expires_at),
                "user": _user_payload(account),
            },
            headers={"Set-Cookie": morsel.OutputString()},
        )

    def _refused_refresh(self, detail: str) -> _Answer:
        return _Answer(401, {"detail": detail}, headers={"Set-Cookie": self._cleared_cookie()})

    def _cleared_cookie(self) -> str:
        cookie: SimpleCookie = SimpleCookie()
        cookie[COOKIE_NAME] = ""
        morsel = cookie[COOKIE_NAME]
        morsel["expires"] = email.utils.format_datetime(self._now(), usegmt=True)
        morsel["max-age"] = 0
        morsel["path"] = COOKIE_PATH
        morsel["httponly"] = True
        morsel["samesite"] = "lax"
        return morsel.OutputString()

    def _route_budget(self, call: _Call) -> _Answer:
        if not self.hosted:
            raise _Refusal(503, {"code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED"})
        if self._budget is None:
            raise _Refusal(503, {"code": "GENERATION_BUDGET_NOT_CONFIGURED"})
        document: dict[str, object] = {
            "currency": "USD",
            "per_generation_microusd": min(PER_GENERATION_MICROUSD, self._budget),
            "per_project_microusd": self._budget,
            "total_microusd": self._budget,
            "spent_total_microusd": self._spent,
            "remaining_total_microusd": max(self._budget - self._spent, 0),
            "period_start": None,
        }
        if self.billing is not None:
            document["billing"] = self.billing
        return _Answer(200, document)

    def _route_readiness(self, call: _Call) -> _Answer:
        if not self.hosted:
            return _Answer(
                503,
                {
                    "mode": "DEVELOPMENT_FIXTURES",
                    "ready": False,
                    "code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED",
                },
            )
        served = {
            "model_entry": READINESS_MODEL_ENTRY,
            "provider_kind": "ANTHROPIC_HOSTED",
            "model": MODEL,
        }
        return _Answer(
            200,
            {
                "mode": "REAL_REQUIRED",
                "manifest_schema_version": 2,
                "ready": True,
                "components": {
                    f"provider:{READINESS_PROVIDER}": {
                        "ready": True,
                        "kind": "ANTHROPIC_HOSTED",
                        "api_key_env": READINESS_KEY_ENV,
                        "api_key_present": True,
                        "api_key_source": "PROCESS",
                        "models": {
                            READINESS_MODEL_ENTRY: {
                                "model": MODEL,
                                "declared_context_window_tokens": READINESS_CONTEXT_WINDOW,
                                "declared_max_output_tokens": READINESS_MAX_OUTPUT,
                                "ready": True,
                            }
                        },
                    },
                    "database": {
                        "ready": True,
                        "observation": {
                            "revision": READINESS_REVISION,
                            "proposal_evidence_schema_available": True,
                        },
                    },
                },
                "proposal_tasks": sorted(PROPOSAL_TASKS),
                "routes": {
                    "tasks": {task: dict(served) for task in sorted(PROPOSAL_TASKS)},
                    "purposes": {},
                },
                "budget": None if self._budget is None else self._route_budget(call).body,
                "evaluator_configured": False,
                "generation_performed": False,
                "semantic_quality_qualified": False,
                "formal_campaign_ready": False,
            },
        )

    def _route_agent_catalog(self, call: _Call) -> _Answer:
        return _Answer(
            200,
            {
                "catalog_version": AGENT_CATALOG_VERSION,
                "content_hash": AGENT_CATALOG_CONTENT_HASH,
                "agents": [
                    {
                        "agent_id": entry.agent_id.value,
                        "catalog_version": entry.catalog_version,
                        "kind": entry.kind.value,
                        "selection_policy": entry.selection_policy.value,
                        "capabilities": [capability.value for capability in entry.capabilities],
                        "supported_project_modes": sorted(
                            mode.value for mode in entry.supported_project_modes
                        ),
                        "name_key": entry.name_key,
                        "description_key": entry.description_key,
                        "is_always_present": entry.is_always_present,
                    }
                    for entry in all_agent_catalog_entries()
                ],
            },
        )


def _email_key(email: str) -> str | None:
    try:
        return NormalizedEmail.parse(email).value
    except InvalidEmailAddress:
        return None


def _password_code(violation: PasswordPolicyViolation) -> str:
    return f"password_{violation.value}"


def _registration_code(errors: Sequence[Mapping[str, object]]) -> str:
    for issue in errors:
        if issue["loc"] == ["body", "password"]:
            violation = REGISTRATION_LENGTH_VIOLATIONS.get(str(issue["type"]))
            return "invalid_registration" if violation is None else _password_code(violation)
    return "invalid_registration"


def _user_payload(account: _Account) -> dict[str, object]:
    return {
        "id": account.id,
        "email": account.email,
        "is_active": True,
        "created_at": _stamp(account.created_at),
        "guidance_mode": None,
    }
