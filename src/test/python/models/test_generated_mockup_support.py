from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

from pydantic import TypeAdapter, ValidationError

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.artifacts.design import (
    create_design_alternative,
    create_design_workflow,
    create_synthetic_design_critique,
)
from orchestwin.artifacts.design_packages import (
    DesignPackageVersion,
    create_design_concern,
    create_design_exploration_package,
    create_design_grounding,
)
from orchestwin.artifacts.visual_catalog import VisualChoices
from orchestwin.artifacts.visual_language import create_twin_fit, create_visual_language
from orchestwin.models.generated_mockup_drafts import (
    GeneratedMockupDraft,
    bind_generated_mockup,
)
from orchestwin.models.proposal_evidence import begin_model_generation, retain_provider_result
from orchestwin.models.proposal_generation import ProposalGenerationError, wire_value
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    create_structured_generation_request,
    create_structured_generation_success,
    create_structured_json_schema,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_usage_scenario,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EvidenceReference,
    EvidenceSourceKind,
    ObservationProvenance,
)
from src.test.python.models.test_hosted_support import SpendingEvidence, providers

FIXTURES = Path(__file__).resolve().parents[1] / "artifacts" / "fixtures" / "generated_mockups"
GUIDED = "library-registration"
DASHBOARD = "library-loans"
NAMESPACE = UUID("5e0c2b8a-1d4f-4c6e-9a7b-0f2d8c4e6a24")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000002401")
OWNER_ID = UUID("00000000-0000-4000-8000-000000002402")
STRANGER_ID = UUID("00000000-0000-4000-8000-000000002403")
REQUIREMENTS_VERSION_ID = UUID("00000000-0000-4000-8000-000000002404")
TWIN_ID = UUID("00000000-0000-4000-8000-000000002405")
GUIDED_ID = UUID("00000000-0000-4000-8000-000000002410")
DASHBOARD_ID = UUID("00000000-0000-4000-8000-000000002411")
CREATED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
TWIN_NAME = "Giulia, volontaria del banco prestiti"
APPROACH = (
    "Le schermate seguono il lavoro della volontaria al banco: vede subito i prestiti da "
    "controllare, completa una registrazione alla volta e riceve una conferma chiara."
)
ITALIAN = {
    "REQ-001": (
        "Registro dei prestiti",
        "Il sistema deve mostrare il registro dei prestiti in corso con il titolo del libro, il "
        "lettore e la data di scadenza.",
    ),
    "REQ-002": (
        "Promemoria ai lettori",
        "Il sistema deve permettere di inviare un promemoria al lettore che non ha restituito il "
        "libro entro la scadenza.",
    ),
    "REQ-003": (
        "Iscrizione dei lettori",
        "Il sistema deve permettere a un nuovo lettore di iscriversi online con i dati anagrafici "
        "e il consenso al trattamento.",
    ),
    "REQ-004": (
        "Verifica dei dati",
        "Il sistema deve segnalare i campi mancanti o scritti in un formato non valido prima "
        "della conferma.",
    ),
    "REQ-005": (
        "Conferma dell'operazione",
        "Il sistema deve mostrare una conferma che riepiloga l'operazione appena completata con "
        "i suoi dati.",
    ),
    "REQ-006": (
        "Accessibilità del banco",
        "Il sistema deve essere usabile da tastiera e leggibile su un tablet posato sul banco "
        "della biblioteca.",
    ),
    "REQ-007": (
        "Statistiche mensili",
        "Il sistema deve riassumere ogni mese il numero dei prestiti e delle restituzioni per la "
        "coordinatrice della biblioteca.",
    ),
}
ENGLISH = {
    "REQ-001": (
        "Loan register",
        "The system must show the register of the open loans with the title of the book, the "
        "reader and the due date.",
    ),
    "REQ-002": (
        "Reader reminders",
        "The system must let the desk send a reminder to the reader who has not returned the "
        "book by the due date.",
    ),
    "REQ-003": (
        "Reader registration",
        "The system must let a new reader register online with the personal data and the "
        "consent to the processing.",
    ),
    "REQ-004": (
        "Data checks",
        "The system must point out the missing fields and the fields that are written in an "
        "invalid format.",
    ),
    "REQ-005": (
        "Confirmation",
        "The system must show a confirmation that summarises the operation that has just been "
        "completed with its data.",
    ),
    "REQ-006": (
        "Desk accessibility",
        "The system must be usable from the keyboard and readable on a tablet that rests on the "
        "desk of the library.",
    ),
    "REQ-007": (
        "Monthly statistics",
        "The system must summarise every month the number of the loans and of the returns for "
        "the coordinator of the library.",
    ),
}
STORIES = {
    "it": (
        ("registrare un prestito al banco senza errori", "servire i lettori con la coda breve"),
        ("inviare un promemoria a chi è in ritardo", "recuperare i libri per gli altri lettori"),
    ),
    "en": (
        ("record a loan at the desk without mistakes", "serve the readers with a short queue"),
        ("send a reminder to the late readers", "recover the books for the other readers"),
    ),
}
CRITERIA = {
    "it": (
        "Il registro mostra per ogni prestito il titolo, il lettore e la data di scadenza.",
        "Il promemoria inviato compare nello storico del lettore con la data dell'invio.",
    ),
    "en": (
        "The register shows for every loan the title, the reader and the due date.",
        "The reminder that was sent appears in the history of the reader with its date.",
    ),
}


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE, name)


def twin_reference() -> UserTwinVersionReference:
    return UserTwinVersionReference(
        twin_id=TWIN_ID, version_number=1, content_hash="a" * 64, name=TWIN_NAME
    )


def _context(kind: RequirementsContextKind, ordinal: int) -> RequirementsContextReference:
    return RequirementsContextReference(
        kind=kind, artifact_id=UUID(int=ordinal), version_number=1, content_hash=f"{ordinal:x}" * 64
    )


def requirements_version(language: str = "it") -> RequirementsSpecificationVersion:
    texts = ITALIAN if language == "it" else ENGLISH
    source = RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )
    requirements = [
        create_requirement(
            requirement_id=uid(code),
            code=code,
            title=title,
            statement=statement,
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            sources=(source,),
            user_twin_references=(twin_reference(),),
        )
        for code, (title, statement) in texts.items()
    ]
    stories = [
        create_user_story(
            story_id=uid(f"USR-00{index}"),
            code=f"USR-00{index}",
            user_twin_reference=twin_reference(),
            goal=goal,
            benefit=benefit,
            requirement_ids=(uid(f"REQ-00{index}"),),
        )
        for index, (goal, benefit) in enumerate(STORIES[language], start=1)
    ]
    criteria = [
        create_acceptance_criterion(
            criterion_id=uid(f"AC-00{index}"),
            code=f"AC-00{index}",
            statement=statement,
            verification_method=VerificationMethod.AUTOMATED_TEST,
            requirement_ids=(uid(f"REQ-00{index}"),),
            user_story_ids=(uid(f"USR-00{index}"),),
        )
        for index, statement in enumerate(CRITERIA[language], start=1)
    ]
    scenario = create_usage_scenario(
        scenario_id=uid("SCN-001"),
        code="SCN-001",
        title="Prestito al banco" if language == "it" else "Loan at the desk",
        actor=twin_reference(),
        preconditions=(),
        trigger="Un lettore porta un libro al banco."
        if language == "it"
        else "A reader brings a book to the desk.",
        steps=("Registra il prestito.",) if language == "it" else ("Record the loan.",),
        expected_outcome="Il prestito compare nel registro."
        if language == "it"
        else "The loan appears in the register.",
        requirement_ids=(uid("REQ-001"),),
        acceptance_criterion_ids=(uid("AC-001"),),
    )
    done = create_definition_of_done_item(
        item_id=uid("DOD-001"),
        code="DOD-001",
        statement="Tutti i test di accettazione passano."
        if language == "it"
        else "Every acceptance test passes.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        applicability=DefinitionOfDoneApplicability.REQUIRED,
        requirement_ids=(uid("REQ-001"),),
    )
    specification = create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=_context(RequirementsContextKind.PROJECT_BRIEF, 11),
        agent_team_reference=_context(RequirementsContextKind.AGENT_TEAM, 12),
        user_modeling_reference=_context(RequirementsContextKind.USER_MODELING, 13),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        user_twin_references=(twin_reference(),),
        requirements=requirements,
        user_stories=stories,
        acceptance_criteria=criteria,
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )
    return RequirementsSpecificationVersion(
        id=REQUIREMENTS_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def fixture_data(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def fixture_choices(name: str) -> VisualChoices:
    return VisualChoices.from_snapshot(fixture_data(name)["visual_choices"])


def draft_payload(name: str = GUIDED, **changes: object) -> dict[str, object]:
    data = fixture_data(name)
    payload = {
        "approach": APPROACH,
        "css": "\n".join(data["styles"]),
        "screens": [
            {
                "code": item["code"],
                "heading": item["title"],
                "kind": item["state"],
                "markup": (FIXTURES / item["markup"]).read_text(encoding="utf-8"),
            }
            for item in data["screens"]
        ],
    }
    payload.update(changes)
    return payload


def iteration_payload(name: str = GUIDED, **changes: object) -> dict[str, object]:
    payload = draft_payload(name)
    payload["changes"] = [
        "Il riepilogo finale mostra anche la sede in cui ritirare la tessera.",
        "Il pulsante principale del primo passo dice Continua con i contatti.",
    ]
    payload.update(changes)
    return payload


def with_markup(payload: dict[str, object], old: str, new: str) -> dict[str, object]:
    screens = [
        dict(screen, markup=screen["markup"].replace(old, new)) for screen in payload["screens"]
    ]
    return {**payload, "screens": screens}


def draft(name: str = GUIDED) -> GeneratedMockupDraft:
    return GeneratedMockupDraft.model_validate(draft_payload(name))


def alternative(name: str, alternative_id: UUID, code: str, requirement_codes) -> object:
    title = "Iscrizione guidata" if name == GUIDED else "Cruscotto dei prestiti"
    workflow = create_design_workflow(
        workflow_id=uid(f"FLOW-{code}"),
        code="FLOW-001",
        title="Registrare un prestito",
        steps=("Cerca il lettore.", "Scegli il libro.", "Conferma il prestito."),
        requirement_ids=(uid("REQ-001"),),
        user_story_ids=(uid("USR-001"),),
    )
    return create_design_alternative(
        alternative_id=alternative_id,
        code=code,
        approach=None,
        title=title,
        summary="Una direzione di progetto per il banco prestiti della biblioteca di quartiere.",
        rationale="La volontaria lavora in piedi al banco e deve completare ogni operazione.",
        requirement_ids=tuple(uid(item) for item in requirement_codes),
        user_story_ids=(uid("USR-001"),),
        acceptance_criterion_ids=(uid("AC-001"),),
        user_twin_references=(twin_reference(),),
        workflows=(workflow,),
        information_architecture=("Prestiti", "Lettori", "Promemoria"),
        accessibility_considerations=("Ogni campo ha un'etichetta sempre visibile.",),
        security_considerations=("I dati dei lettori restano nel sistema della biblioteca.",),
        advantages=("Operazioni rapide al banco.",),
        trade_offs=("Meno informazioni per volta.",),
        visual_language=create_visual_language(
            choices=fixture_choices(name),
            product_name="Biblioteca Sant'Ambrogio",
            rationale="Una lingua visiva calma e leggibile per il banco della biblioteca.",
            twin_fit=(
                create_twin_fit(
                    reference=twin_reference(),
                    statement="Testi grandi e azioni chiare per chi lavora al banco.",
                ),
            ),
        ),
    )


def critique(alternative_id: UUID, code: str, *, verdict: str | None = None, quote=None):
    provenance = ObservationProvenance.from_references(
        (
            EvidenceReference(
                source_kind=EvidenceSourceKind.MODEL_OUTPUT,
                source_id="scripted-design:1",
                source_version=1,
                content_hash="d" * 64,
                locator=f"critiques.{code}",
                summary="Critica sintetica del gemello.",
            ),
        )
    )
    return create_synthetic_design_critique(
        critique_id=uid(code),
        code=code,
        design_alternative_id=alternative_id,
        user_twin_reference=twin_reference(),
        strengths=("Il compito principale è subito visibile.",),
        concerns=("Il riepilogo finale potrebbe essere troppo lungo.",),
        suggested_changes=("Mostrare la sede di ritiro della tessera.",),
        provenance=provenance,
        confidence=ConfidenceScore(0.7),
        rationale="La critica deriva dal profilo della volontaria.",
        verdict=verdict,
        quote=quote,
    )


ALL_CODES = tuple(ITALIAN)
GUIDED_CODES = ALL_CODES[:6]


def package(language: str = "it", **changes):
    requirements = requirements_version(language)
    result = create_design_exploration_package(
        project_id=PROJECT_ID,
        grounding=create_design_grounding(requirements),
        alternatives=(
            alternative(GUIDED, GUIDED_ID, "DES-001", GUIDED_CODES),
            alternative(DASHBOARD, DASHBOARD_ID, "DES-002", ALL_CODES),
        ),
        critiques=(
            critique(
                GUIDED_ID,
                "CRQ-001",
                verdict="Chiaro e rassicurante",
                quote="Finalmente capisco a che punto sono dell'iscrizione.",
            ),
            critique(DASHBOARD_ID, "CRQ-002"),
        ),
        concerns=(
            create_design_concern(
                concern_id=uid("DRK-001"),
                code="DRK-001",
                summary="La volontaria perde il filo quando il registro è lungo.",
                mitigation="Mostrare in alto il numero dei prestiti da controllare oggi.",
                requirement_ids=(uid("REQ-001"),),
                design_alternative_ids=(DASHBOARD_ID,),
            ),
        ),
    )
    return replace(result, **changes) if changes else result


def version(package_value, number: int = 1) -> DesignPackageVersion:
    return DesignPackageVersion(
        id=uid(f"design-version-{number}"),
        project_id=PROJECT_ID,
        version_number=number,
        based_on_version_number=None if number == 1 else number - 1,
        package=package_value,
        content_hash=package_value.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT + timedelta(minutes=number),
    )


def applied_package(language: str = "it", name: str = GUIDED, assertions=()):
    base = package(language)
    chosen = next(item for item in base.alternatives if item.id == GUIDED_ID)
    binding = bind_generated_mockup(
        draft(name), alternative=chosen, requirements=requirements_version(language), language="it"
    )
    return replace(
        base,
        owner_selected_alternative_id=GUIDED_ID,
        prototype=binding.prototype,
        generated_mockup=binding.mockup,
        owner_assertions=tuple(assertions),
    )


class DesignVersions:
    def __init__(self, *packages):
        self.versions = [version(item, number) for number, item in enumerate(packages, start=1)]
        self.current_calls = 0

    def owned(self, owner_user_id, project_id):
        return owner_user_id == OWNER_ID and project_id == PROJECT_ID

    async def current(self, *, owner_user_id, project_id):
        self.current_calls += 1
        return self.versions[-1] if self.owned(owner_user_id, project_id) else None

    async def history(self, *, owner_user_id, project_id):
        return tuple(self.versions) if self.owned(owner_user_id, project_id) else ()

    def apply(self, package_value):
        self.versions.append(version(package_value, len(self.versions) + 1))
        return self.versions[-1]


class RequirementsQuery:
    def __init__(self, value=None):
        self.value = requirements_version() if value is None else value

    async def current(self, *, owner_user_id, project_id):
        return self.value if owner_user_id == OWNER_ID and project_id == PROJECT_ID else None


class MemoryMockupStore(SpendingEvidence):
    def __init__(self, **options):
        super().__init__(**options)
        self.order = []
        self.times = {}

    async def begin(self, *, request, **scope):
        await super().begin(request=request, **scope)
        self.order.append(request.request_id)
        self.times[request.request_id] = CREATED_AT + timedelta(seconds=len(self.order))

    def context(self, generation_id):
        request, _scope = self.requests[generation_id]
        return json.loads(request.input_payload_json)["context"]

    def owned(self, generation_id, owner_user_id, project_id):
        _request, scope = self.requests[generation_id]
        return scope["owner_user_id"] == owner_user_id and scope["project_id"] == project_id

    def kinds(self, generation_id):
        return [kind for kind, _payload, _raw in self.events[generation_id]]

    def payload(self, generation_id, kind):
        return next(
            (payload for item, payload, _raw in self.events[generation_id] if item == kind), None
        )

    async def latest_design_mockup(
        self, *, owner_user_id, project_id, design_content_hashes, alternative_id, purposes
    ):
        newest = None
        for generation_id in self.order:
            if not self.owned(generation_id, owner_user_id, project_id):
                continue
            context = self.context(generation_id)
            accepted = self.payload(generation_id, "ADAPTER_ACCEPTED")
            if (
                accepted is not None
                and context.get("purpose") in purposes
                and context.get("design_content_hash") in tuple(design_content_hashes)
                and context.get("alternative", {}).get("id") == str(alternative_id)
            ):
                newest = accepted["result"]
        return newest

    async def design_iteration_generations(self, *, owner_user_id, project_id, limit=200):
        records = []
        for generation_id in reversed(self.order):
            context = self.context(generation_id)
            if (
                not self.owned(generation_id, owner_user_id, project_id)
                or context.get("purpose") != "DESIGN_ITERATION"
            ):
                continue
            records.append(
                {
                    "generation_id": str(generation_id),
                    "recorded_at": self.times[generation_id].isoformat(),
                    "context": context,
                    "events": {kind: payload for kind, payload, _raw in self.events[generation_id]},
                }
            )
        return records[:limit]


def answer(payload, *, cost=410_000):
    return ("ANSWER", payload, cost)


def failure(code, *, retryable, cost=None, message="The hosted model provider failed."):
    return ("FAILURE", (StructuredGenerationFailureCode(code), retryable, message), cost)


def refusal(code):
    return ("BEFORE", code, None)


class ScriptedMockupGenerator:
    def __init__(self, *outcomes, entry="design", budget=None):
        self.configuration = providers().hosted_model(entry)
        self.budget = budget
        self.outcomes = list(outcomes)
        self.calls = []
        self.requests = []

    @property
    def provider_id(self):
        return "scripted-mockups"

    @property
    def port(self):
        return None

    def route(self, task, purpose=None):
        return self

    async def generate(
        self,
        *,
        task,
        context,
        output_type,
        instruction,
        max_output_tokens=None,
        temperature=None,
        retry_schema_errors=True,
        retry_transient_failures=True,
    ):
        self.calls.append(
            {
                "task": task,
                "context": context,
                "output_type": output_type,
                "instruction": instruction,
                "max_output_tokens": max_output_tokens,
                "retry_schema_errors": retry_schema_errors,
            }
        )
        kind, value, cost = self.outcomes.pop(0)
        schema_payload = TypeAdapter(output_type).json_schema()
        schema = create_structured_json_schema(
            schema_id="proposal-design-scripted", version_number=1, schema_payload=schema_payload
        )
        request = create_structured_generation_request(
            request_id=uuid4(),
            task_id=f"proposal-{task}-v1",
            expected_identity=self.configuration.identity,
            output_schema=schema,
            system_instruction=instruction,
            input_payload={"context": wire_value(context), "output_schema": schema_payload},
            allowed_evidence_refs=(),
            prompt_version_ref="proposal-design-scripted",
            temperature=1.0,
            max_output_tokens=max_output_tokens,
            timeout_seconds=1200,
        )
        self.requests.append(request)
        if kind == "BEFORE":
            raise ProposalGenerationError(value, request=request)
        await begin_model_generation(request)
        usage = StructuredGenerationUsage(
            input_tokens=12_000, output_tokens=18_000, latency_milliseconds=180_000
        )
        if cost is not None:
            usage = replace(usage, cost_microusd=cost)
        if kind == "FAILURE":
            code, retryable, message = value
            result = failed_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
                code=code,
                message=message,
                retryable=retryable,
                usage=usage if cost is not None else None,
            )
            await retain_provider_result(result)
            raise ProposalGenerationError(code.value, request=request, result=result)
        success = create_structured_generation_success(
            payload=value,
            actual_identity=self.configuration.identity,
            usage=usage,
            finish_reason=StructuredGenerationFinishReason.STOP,
            provider_request_id="msg_scripted",
        )
        result = successful_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED, success=success
        )
        await retain_provider_result(result)
        try:
            return TypeAdapter(output_type).validate_python(value)
        except ValidationError as error:
            raise ProposalGenerationError(
                "INVALID_PROVIDER_OUTPUT", request=request, result=result
            ) from error


def runtime(generator=None, store=None, versions=None, requirements=None, real=True):
    store = MemoryMockupStore() if store is None else store
    return SimpleNamespace(
        proposal_evidence_store=store,
        real_model_runtime=SimpleNamespace(
            design=SimpleNamespace(proposal_port=SimpleNamespace(generator=generator))
        )
        if real
        else None,
        design_query_service=DesignVersions(package()) if versions is None else versions,
        requirements_query_service=RequirementsQuery(requirements),
        database_runtime=None,
    )
