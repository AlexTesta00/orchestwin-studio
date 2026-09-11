"""Regression test for Design provider User Twin observation ordering."""

from types import SimpleNamespace
from uuid import UUID

from orchestwin.projects import design_runtime


def test_user_modeling_input_canonicalizes_persisted_twin_observations() -> None:
    """Adapt domain-ordered User Twin observations to the Design provider contract."""
    role = SimpleNamespace(observation_key="user_twin.role")
    goals = SimpleNamespace(observation_key="user_twin.goals")
    persisted_observations = (role, goals)

    persisted_keys = tuple(observation.observation_key for observation in persisted_observations)
    assert persisted_keys != tuple(sorted(persisted_keys))

    user_modeling_version = SimpleNamespace(
        id=UUID("00000000-0000-4000-8000-000000094001"),
        version_number=1,
        content_hash="a" * 64,
        snapshot=SimpleNamespace(
            twin_versions=(
                SimpleNamespace(
                    twin_id=UUID("00000000-0000-4000-8000-000000094002"),
                    version_number=1,
                    content_hash="b" * 64,
                    profile=SimpleNamespace(
                        name="Novice end user Twin",
                        observations=persisted_observations,
                    ),
                ),
            ),
        ),
    )

    provider_input = design_runtime._user_modeling_input(user_modeling_version)

    provider_observations = provider_input.user_twins[0].observations
    provider_keys = tuple(observation.observation_key for observation in provider_observations)

    assert provider_keys == ("user_twin.goals", "user_twin.role")
    assert set(map(id, provider_observations)) == set(map(id, persisted_observations))
