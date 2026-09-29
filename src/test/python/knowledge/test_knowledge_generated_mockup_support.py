from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterable
from dataclasses import replace
from functools import cache

from orchestwin.artifacts.bound_mockups import (
    BoundGeneratedMockup,
    create_bound_mockup,
    markup_requirement_codes,
)
from orchestwin.artifacts.design import DesignAlternative
from orchestwin.artifacts.design_packages import DesignExplorationPackage
from orchestwin.artifacts.generated_mockups import GeneratedMockup, create_generated_mockup
from orchestwin.knowledge.folder import (
    KnowledgeFolder,
    build_knowledge_folder,
    file_digests,
    folder_content_hash,
    json_text,
)
from orchestwin.knowledge.layout import KNOWLEDGE_MANIFEST, stage_document
from orchestwin.knowledge.sources import KnowledgeSources
from orchestwin.knowledge.stage_documents import stage_versions
from src.test.python.artifacts.test_design_package_extension import LARGE_SCREENS, large_markup
from src.test.python.artifacts.test_generated_mockup_support import (
    BASE_STYLES,
    DASHBOARD,
    FIXTURES,
    GUIDED_FORM,
    fixture_data,
    screen_payloads,
)

from .knowledge_fixtures import PUBLISHED_AT, REAL_PROJECT_ID, real_documents, sources_of

LARGE = "large"
MOCKUPS = (*FIXTURES, LARGE)
ASSERTIONS = (
    "Il pulsante principale resta in alto a destra.",
    "La tabella dei prestiti mostra sempre la data di scadenza.",
)
VERDICTS = (
    ("Utile, con riserve", "Trovo subito i prestiti in ritardo, ma vorrei filtrare per sede."),
    ("Chiaro e rapido", "Capisco in un attimo cosa devo fare e quale pulsante premere."),
)
REAL_FOLDER_CONTENT_HASH = "c36dc050923b5dea824d1ad3ddb6e637c3c0d91e72c4eb8d946d98bfbc3926d7"
REAL_DESIGN_SCHEMA_DIGEST = "0b879a46c8ade1169252577e7817b9d45277809f632c69f596163a94797bf1b0"


@cache
def real_versions() -> dict[str, object]:
    return stage_versions(real_documents())


def selected_alternative(package: DesignExplorationPackage) -> DesignAlternative:
    return next(
        alternative
        for alternative in package.alternatives
        if alternative.id == package.owner_selected_alternative_id
    )


def _token_names(alternative: DesignAlternative) -> tuple[str, ...]:
    assert alternative.visual_language is not None
    return tuple(name for name, _value in alternative.visual_language.tokens)


def _mockup(name: str, alternative: DesignAlternative) -> GeneratedMockup:
    if name == LARGE:
        return create_generated_mockup(
            design_alternative_id=alternative.id,
            title="Registro dei prestiti delle cinque sedi",
            styles=BASE_STYLES,
            screens=screen_payloads([large_markup(index) for index in range(1, LARGE_SCREENS + 1)]),
            token_names=_token_names(alternative),
        )
    data = fixture_data(name)
    return create_generated_mockup(
        design_alternative_id=alternative.id,
        title=data["title"],
        styles=data["styles"],
        screens=data["screens"],
        token_names=_token_names(alternative),
    )


def _bound(name: str, package: DesignExplorationPackage) -> BoundGeneratedMockup:
    mockup = _mockup(name, selected_alternative(package))
    specification = real_versions()["requirements"].specification
    identities = {item.code: item.id for item in specification.requirements}
    return create_bound_mockup(
        mockup=mockup,
        requirement_ids_by_code={
            code: identities[code] for code in markup_requirement_codes(mockup)
        },
    )


def _with_verdicts(
    package: DesignExplorationPackage, verdicts: Iterable[tuple[str, str]]
) -> DesignExplorationPackage:
    chosen = list(verdicts)
    critiques = tuple(
        replace(critique, verdict=chosen[index][0], quote=chosen[index][1])
        if index < len(chosen)
        else critique
        for index, critique in enumerate(package.critiques)
    )
    return replace(package, critiques=critiques)


@cache
def generated_package(
    name: str | None = DASHBOARD,
    *,
    assertions: tuple[str, ...] = ASSERTIONS,
    verdicts: tuple[tuple[str, str], ...] = VERDICTS,
) -> DesignExplorationPackage:
    package = real_versions()["design"].package
    if name is not None:
        bound = _bound(name, package)
        package = replace(package, prototype=bound.prototype(), generated_mockup=bound)
    return _with_verdicts(replace(package, owner_assertions=assertions), verdicts)


def generated_sources(name: str | None = DASHBOARD, **options) -> KnowledgeSources:
    versions = real_versions()
    package = generated_package(name, **options)
    design = replace(versions["design"], package=package, content_hash=package.content_hash)
    return sources_of({**versions, "design": design}, project_id=REAL_PROJECT_ID)


@cache
def generated_folder(name: str | None = DASHBOARD, **options) -> KnowledgeFolder:
    return build_knowledge_folder(
        generated_sources(name, **options), version_number=1, created_at=PUBLISHED_AT
    )


def design_snapshot(folder: KnowledgeFolder) -> dict[str, object]:
    return json.loads(folder.files[stage_document("design")])


def repacked(folder: KnowledgeFolder, design: dict[str, object]) -> dict[str, str]:
    files = {**folder.files, stage_document("design"): json_text(design)}
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["files"] = file_digests({path: files[path] for path in manifest["files"]})
    manifest["package"]["content_hash"] = folder_content_hash(files)
    files[KNOWLEDGE_MANIFEST] = json_text(manifest)
    return files


def archive_of(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name in sorted(files):
            target.writestr(name, files[name])
    return buffer.getvalue()


__all__ = [
    "ASSERTIONS",
    "DASHBOARD",
    "GUIDED_FORM",
    "LARGE",
    "MOCKUPS",
    "REAL_DESIGN_SCHEMA_DIGEST",
    "REAL_FOLDER_CONTENT_HASH",
    "VERDICTS",
    "archive_of",
    "design_snapshot",
    "generated_folder",
    "generated_package",
    "generated_sources",
    "real_versions",
    "repacked",
    "selected_alternative",
]
