"""Frozen final-thesis training campaign for the shared User Twin evaluator.

This module converts the successful Sprint-11 feasibility evidence into one bounded,
reproducible training decision. It selects the exact Qwen base model for final thesis
fine-tuning, NOT the eight-step smoke adapter, and defines a broad bilingual synthetic
curriculum whose examples remain explicit design hypotheses rather than real-user evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.training.dataset_examples import (
    DatasetArtifactSnapshot,
    DatasetEvidenceKind,
    DatasetEvidenceReference,
    DatasetExampleSourceKind,
    DatasetLanguage,
    DatasetUseRestriction,
    DatasetUserTwinReference,
    DatasetVersionedArtifactReference,
    EvaluatorDatasetExample,
    create_evaluator_dataset_example,
)
from orchestwin.training.splitting import (
    DatasetSplit,
    DatasetSplitPolicy,
    split_dataset_examples,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

CAMPAIGN_POLICY_ID: Final = "orchestwin-thesis-user-twin-evaluator-v1"
SELECTION_DECISION_ID: Final = "qwen3-4b-instruct-2507-final-thesis-base-v1"

SELECTED_CANDIDATE_ID: Final = "model-candidate-qwen3-4b-instruct-2507"
BASE_MODEL_REPOSITORY: Final = "Qwen/Qwen3-4B-Instruct-2507"
BASE_MODEL_REVISION: Final = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
TOKENIZER_REPOSITORY: Final = BASE_MODEL_REPOSITORY
TOKENIZER_REVISION: Final = BASE_MODEL_REVISION

PROJECT_VARIANT_COUNT: Final = 500
LANGUAGES: Final = (DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN)
TARGET_TOTAL_EXAMPLES: Final = 24_000
MINIMUM_TRAIN_EXAMPLES: Final = 18_000
MINIMUM_VALIDATION_EXAMPLES: Final = 1_500
MINIMUM_INTERNAL_TEST_EXAMPLES: Final = 1_500
TARGET_ABSTENTION_FRACTION: Final = 0.25

CAMPAIGN_SEED: Final = 20260905
DATASET_NAMESPACE: Final = UUID("4e7aa119-5ed2-47b6-9f0f-2ae90c3def59")
SPLIT_POLICY: Final = DatasetSplitPolicy(
    policy_id="thesis-project-scenario-grouped-split",
    version_number=1,
    seed=20260905,
    train_percent=80,
    validation_percent=10,
    internal_test_percent=10,
)

# Evidence that supports selection of the BASE for the thesis campaign.
# None of these hashes authorizes redistribution or claims empirical user validity.
S59_EVIDENCE_ARCHIVE_SHA256: Final = (
    "04d862306e06f9fee96a3a4848afae939b305955a5a502bc0c99b4f2e70eb19b"
)
S60_EVIDENCE_ARCHIVE_SHA256: Final = (
    "22fe177aa488417809a9a752d966b3edf83a3c5e630562bdeb226e98eaa98432"
)
S61_EVIDENCE_ARCHIVE_SHA256: Final = (
    "45974397663b8c166a46bf238cdc1ba0884a6b663a93b68bceabe4e7dae05a11"
)
S62_EVIDENCE_ARCHIVE_SHA256: Final = (
    "1f9da4019246400894b245b8feb17c89bae16ee209439ff42b8595e85ed3ba14"
)


class CampaignPlatform(StrEnum):
    WEB = "WEB"
    JVM = "JVM"
    MOBILE = "MOBILE"
    CROSS_PLATFORM = "CROSS_PLATFORM"


class CampaignRisk(StrEnum):
    ACCESSIBILITY = "ACCESSIBILITY"
    TRUST = "TRUST"
    COGNITIVE_LOAD = "COGNITIVE_LOAD"
    ERROR_RECOVERY = "ERROR_RECOVERY"
    TIME_PRESSURE = "TIME_PRESSURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    STAKEHOLDER_CONFLICT = "STAKEHOLDER_CONFLICT"


@dataclass(frozen=True, slots=True)
class ThesisScenarioFamily:
    family_id: str
    domain: str
    role: str
    platform: CampaignPlatform
    risk: CampaignRisk
    criterion: SyntheticFindingCriterion
    severity: SyntheticFindingSeverity
    abstain: bool
    task_en: str
    task_it: str


# 24 deliberately different software contexts. Six are abstention-heavy (=25%).
FAMILIES: Final = (
    ThesisScenarioFamily(
        "ecommerce-checkout-accessibility",
        "ecommerce",
        "occasional-shopper",
        CampaignPlatform.WEB,
        CampaignRisk.ACCESSIBILITY,
        SyntheticFindingCriterion.ACCESSIBILITY,
        SyntheticFindingSeverity.MAJOR,
        False,
        "complete checkout without losing cart state",
        "completare il checkout senza perdere lo stato del carrello",
    ),
    ThesisScenarioFamily(
        "healthcare-admin-appointment-recovery",
        "healthcare-administration",
        "front-desk-operator",
        CampaignPlatform.WEB,
        CampaignRisk.ERROR_RECOVERY,
        SyntheticFindingCriterion.ACTIONABILITY,
        SyntheticFindingSeverity.MODERATE,
        False,
        "recover from an invalid appointment entry",
        "recuperare da un inserimento appuntamento non valido",
    ),
    ThesisScenarioFamily(
        "education-course-navigation",
        "education",
        "student",
        CampaignPlatform.WEB,
        CampaignRisk.COGNITIVE_LOAD,
        SyntheticFindingCriterion.COMPREHENSIBILITY,
        SyntheticFindingSeverity.MODERATE,
        False,
        "locate the next required learning activity",
        "individuare la prossima attività didattica richiesta",
    ),
    ThesisScenarioFamily(
        "banking-transfer-trust",
        "banking-interface",
        "retail-banking-customer",
        CampaignPlatform.MOBILE,
        CampaignRisk.TRUST,
        SyntheticFindingCriterion.TRUST,
        SyntheticFindingSeverity.CRITICAL,
        False,
        "review and confirm a money-transfer summary",
        "controllare e confermare il riepilogo di un trasferimento",
    ),
    ThesisScenarioFamily(
        "public-service-form-accessibility",
        "public-service",
        "citizen",
        CampaignPlatform.WEB,
        CampaignRisk.ACCESSIBILITY,
        SyntheticFindingCriterion.ACCESSIBILITY,
        SyntheticFindingSeverity.MAJOR,
        False,
        "submit a public-service form using keyboard navigation",
        "inviare un modulo di servizio pubblico usando la tastiera",
    ),
    ThesisScenarioFamily(
        "logistics-dispatch-time-pressure",
        "logistics",
        "dispatcher",
        CampaignPlatform.JVM,
        CampaignRisk.TIME_PRESSURE,
        SyntheticFindingCriterion.COGNITIVE_LOAD,
        SyntheticFindingSeverity.MAJOR,
        False,
        "reroute an urgent delivery after a deterministic failure",
        "riassegnare una consegna urgente dopo un errore deterministico",
    ),
    ThesisScenarioFamily(
        "developer-tooling-build-failure",
        "developer-tooling",
        "software-developer",
        CampaignPlatform.JVM,
        CampaignRisk.ERROR_RECOVERY,
        SyntheticFindingCriterion.ACTIONABILITY,
        SyntheticFindingSeverity.MAJOR,
        False,
        "diagnose and recover from a reproducible build failure",
        "diagnosticare e recuperare da un errore di build riproducibile",
    ),
    ThesisScenarioFamily(
        "hospitality-reservation-conflict",
        "hospitality",
        "reservation-agent",
        CampaignPlatform.WEB,
        CampaignRisk.STAKEHOLDER_CONFLICT,
        SyntheticFindingCriterion.TASK_ALIGNMENT,
        SyntheticFindingSeverity.MODERATE,
        False,
        "resolve a reservation change with conflicting stakeholder priorities",
        "risolvere una modifica di prenotazione con priorità contrastanti",
    ),
    ThesisScenarioFamily(
        "travel-itinerary-insufficient-evidence",
        "travel",
        "traveler",
        CampaignPlatform.MOBILE,
        CampaignRisk.INSUFFICIENT_EVIDENCE,
        SyntheticFindingCriterion.USEFULNESS,
        SyntheticFindingSeverity.OBSERVATION,
        True,
        "evaluate an itinerary recommendation with missing traveler constraints",
        "valutare un itinerario con vincoli del viaggiatore mancanti",
    ),
    ThesisScenarioFamily(
        "hr-onboarding-contradictory-evidence",
        "human-resources",
        "new-employee",
        CampaignPlatform.WEB,
        CampaignRisk.CONTRADICTORY_EVIDENCE,
        SyntheticFindingCriterion.COMPREHENSIBILITY,
        SyntheticFindingSeverity.OBSERVATION,
        True,
        "evaluate onboarding guidance whose approved sources disagree",
        "valutare indicazioni di onboarding con fonti approvate discordanti",
    ),
    ThesisScenarioFamily(
        "crm-priority-trust",
        "crm",
        "account-manager",
        CampaignPlatform.WEB,
        CampaignRisk.TRUST,
        SyntheticFindingCriterion.TRUST,
        SyntheticFindingSeverity.MODERATE,
        False,
        "review an automatically prioritized customer follow-up",
        "controllare una priorità automatica di ricontatto cliente",
    ),
    ThesisScenarioFamily(
        "manufacturing-alarm-time-pressure",
        "manufacturing",
        "plant-operator",
        CampaignPlatform.JVM,
        CampaignRisk.TIME_PRESSURE,
        SyntheticFindingCriterion.ACTIONABILITY,
        SyntheticFindingSeverity.CRITICAL,
        False,
        "interpret and act on an urgent machine-state alarm",
        "interpretare e gestire un allarme urgente sullo stato macchina",
    ),
    ThesisScenarioFamily(
        "media-publishing-cognitive-load",
        "media-publishing",
        "content-editor",
        CampaignPlatform.WEB,
        CampaignRisk.COGNITIVE_LOAD,
        SyntheticFindingCriterion.COGNITIVE_LOAD,
        SyntheticFindingSeverity.MINOR,
        False,
        "publish a corrected article under a multi-step workflow",
        "pubblicare un articolo corretto in un flusso a più passaggi",
    ),
    ThesisScenarioFamily(
        "security-dashboard-insufficient-evidence",
        "security-operations",
        "security-analyst",
        CampaignPlatform.WEB,
        CampaignRisk.INSUFFICIENT_EVIDENCE,
        SyntheticFindingCriterion.TRUST,
        SyntheticFindingSeverity.OBSERVATION,
        True,
        "evaluate an alert explanation without enough provenance",
        "valutare la spiegazione di un alert senza provenienza sufficiente",
    ),
    ThesisScenarioFamily(
        "analytics-filter-recovery",
        "analytics",
        "business-analyst",
        CampaignPlatform.WEB,
        CampaignRisk.ERROR_RECOVERY,
        SyntheticFindingCriterion.USEFULNESS,
        SyntheticFindingSeverity.MODERATE,
        False,
        "recover a dashboard after an invalid filter combination",
        "recuperare una dashboard dopo una combinazione filtri non valida",
    ),
    ThesisScenarioFamily(
        "legal-case-contradictory-evidence",
        "legal-case-management",
        "case-worker",
        CampaignPlatform.WEB,
        CampaignRisk.CONTRADICTORY_EVIDENCE,
        SyntheticFindingCriterion.TRUST,
        SyntheticFindingSeverity.OBSERVATION,
        True,
        "evaluate workflow advice backed by mutually inconsistent records",
        "valutare indicazioni di flusso supportate da record incoerenti",
    ),
    ThesisScenarioFamily(
        "nonprofit-donation-accessibility",
        "nonprofit",
        "donor",
        CampaignPlatform.WEB,
        CampaignRisk.ACCESSIBILITY,
        SyntheticFindingCriterion.ACCESSIBILITY,
        SyntheticFindingSeverity.MODERATE,
        False,
        "complete a donation flow with assistive technology",
        "completare una donazione con tecnologia assistiva",
    ),
    ThesisScenarioFamily(
        "energy-monitoring-trust",
        "energy-monitoring",
        "facility-manager",
        CampaignPlatform.CROSS_PLATFORM,
        CampaignRisk.TRUST,
        SyntheticFindingCriterion.TRUST,
        SyntheticFindingSeverity.MAJOR,
        False,
        "interpret an energy anomaly recommendation and its uncertainty",
        "interpretare una raccomandazione su un'anomalia energetica e la sua incertezza",
    ),
    ThesisScenarioFamily(
        "retail-pos-stakeholder-conflict",
        "retail-pos",
        "store-associate",
        CampaignPlatform.CROSS_PLATFORM,
        CampaignRisk.STAKEHOLDER_CONFLICT,
        SyntheticFindingCriterion.TASK_ALIGNMENT,
        SyntheticFindingSeverity.MODERATE,
        False,
        "complete a return while policy and speed priorities conflict",
        "completare un reso mentre regole e velocità sono in conflitto",
    ),
    ThesisScenarioFamily(
        "project-management-insufficient-evidence",
        "project-management",
        "project-coordinator",
        CampaignPlatform.WEB,
        CampaignRisk.INSUFFICIENT_EVIDENCE,
        SyntheticFindingCriterion.USEFULNESS,
        SyntheticFindingSeverity.OBSERVATION,
        True,
        "evaluate a schedule recommendation without stakeholder availability",
        "valutare una pianificazione senza disponibilità degli stakeholder",
    ),
    ThesisScenarioFamily(
        "collaboration-notification-load",
        "collaboration",
        "knowledge-worker",
        CampaignPlatform.CROSS_PLATFORM,
        CampaignRisk.COGNITIVE_LOAD,
        SyntheticFindingCriterion.COGNITIVE_LOAD,
        SyntheticFindingSeverity.MINOR,
        False,
        "triage high-volume collaboration notifications",
        "gestire un alto volume di notifiche collaborative",
    ),
    ThesisScenarioFamily(
        "insurance-claim-contradictory-evidence",
        "insurance-claims",
        "claims-handler",
        CampaignPlatform.WEB,
        CampaignRisk.CONTRADICTORY_EVIDENCE,
        SyntheticFindingCriterion.TRUST,
        SyntheticFindingSeverity.OBSERVATION,
        True,
        "evaluate a claim workflow when supporting records conflict",
        "valutare un flusso di sinistro quando i record sono in conflitto",
    ),
    ThesisScenarioFamily(
        "mobility-route-accessibility",
        "urban-mobility",
        "commuter",
        CampaignPlatform.MOBILE,
        CampaignRisk.ACCESSIBILITY,
        SyntheticFindingCriterion.ACCESSIBILITY,
        SyntheticFindingSeverity.MAJOR,
        False,
        "compare route alternatives under mobility accessibility constraints",
        "confrontare percorsi con vincoli di accessibilità alla mobilità",
    ),
    ThesisScenarioFamily(
        "brownfield-admin-recovery",
        "brownfield-enterprise",
        "system-maintainer",
        CampaignPlatform.CROSS_PLATFORM,
        CampaignRisk.ERROR_RECOVERY,
        SyntheticFindingCriterion.ACTIONABILITY,
        SyntheticFindingSeverity.MAJOR,
        False,
        "recover an incomplete legacy administration workflow",
        "recuperare un flusso amministrativo legacy incompleto",
    ),
)

EXPERIENCE_LEVELS: Final = (
    "novice",
    "occasional",
    "intermediate",
    "experienced",
    "expert",
)
CONTEXTS_EN: Final = (
    "during routine work",
    "while interrupted",
    "under moderate time pressure",
    "during a handoff",
    "after a previous failed attempt",
    "on a small screen",
    "with incomplete contextual memory",
    "while comparing two alternatives",
    "during peak workload",
    "while collaborating remotely",
)
CONTEXTS_IT: Final = (
    "durante il lavoro ordinario",
    "mentre viene interrotto",
    "con moderata pressione temporale",
    "durante un passaggio di consegne",
    "dopo un tentativo precedente fallito",
    "su uno schermo piccolo",
    "con memoria contestuale incompleta",
    "mentre confronta due alternative",
    "durante un picco di lavoro",
    "collaborando da remoto",
)
CONSTRAINTS_EN: Final = (
    "must preserve entered data",
    "must avoid hidden irreversible actions",
    "needs visible uncertainty",
    "needs keyboard-operable controls",
    "must recover without restarting",
    "needs concise next-step guidance",
    "must distinguish facts from assumptions",
    "needs traceable evidence references",
)
CONSTRAINTS_IT: Final = (
    "deve preservare i dati inseriti",
    "deve evitare azioni irreversibili nascoste",
    "richiede incertezza visibile",
    "richiede controlli utilizzabili da tastiera",
    "deve recuperare senza ricominciare",
    "richiede indicazioni concise sul passo successivo",
    "deve distinguere fatti e assunzioni",
    "richiede riferimenti alle evidenze tracciabili",
)
ARTIFACT_STATES_EN: Final = (
    "a wireframe with incomplete error states",
    "a workflow specification with explicit happy-path steps",
    "a prototype containing a recoverable validation error",
    "an existing brownfield screen with legacy terminology",
    "a dashboard with dense prioritization cues",
    "a form with partial accessibility annotations",
    "a mobile flow with constrained screen space",
    "a cross-platform interaction contract",
)
ARTIFACT_STATES_IT: Final = (
    "un wireframe con stati di errore incompleti",
    "una specifica di flusso con percorso principale esplicito",
    "un prototipo con errore di validazione recuperabile",
    "una schermata brownfield con terminologia legacy",
    "una dashboard con molti segnali di priorità",
    "un modulo con annotazioni di accessibilità parziali",
    "un flusso mobile con spazio schermo limitato",
    "un contratto di interazione cross-platform",
)


def selection_decision_snapshot() -> dict[str, object]:
    """Owner-approved BASE selection for the final thesis fine-tuning campaign."""
    snapshot = {
        "decision_id": SELECTION_DECISION_ID,
        "status": "OWNER_APPROVED_FOR_FINAL_THESIS_TRAINING",
        "candidate_id": SELECTED_CANDIDATE_ID,
        "base_model_repository": BASE_MODEL_REPOSITORY,
        "base_model_revision": BASE_MODEL_REVISION,
        "tokenizer_repository": TOKENIZER_REPOSITORY,
        "tokenizer_revision": TOKENIZER_REVISION,
        "base_selected_for_training": True,
        "smoke_adapter_selected_as_final": False,
        "smoke_adapter_quality_improvement_claimed": False,
        "local_openai_compatible_smoke_serving_observed": True,
        "vllm_serving_observed": False,
        "redistribution_authorized": False,
        "empirical_user_validation_claimed": False,
        "evidence_archive_sha256": {
            "s59_training": S59_EVIDENCE_ARCHIVE_SHA256,
            "s60_recovery": S60_EVIDENCE_ARCHIVE_SHA256,
            "s61_paired_ablation": S61_EVIDENCE_ARCHIVE_SHA256,
            "s62_local_serving": S62_EVIDENCE_ARCHIVE_SHA256,
        },
        "rationale": (
            "Qwen3-4B-Instruct-2507 is the only candidate that passed the bounded local "
            "QLoRA execution/recovery path and exact-identity local serving probe. The "
            "eight-step smoke adapter did not show an overall quality improvement and is "
            "therefore discarded as a final artifact. The base is selected only as the "
            "foundation for the much larger thesis training campaign."
        ),
    }
    return {**snapshot, "content_hash": snapshot_content_hash(snapshot)}


def final_qlora_policy_snapshot() -> dict[str, object]:
    """Hardware-aware final policy; dataset hashes are bound after materialization."""
    snapshot = {
        "policy_id": "qwen3-4b-thesis-qlora-v1",
        "candidate_id": SELECTED_CANDIDATE_ID,
        "base_model_repository": BASE_MODEL_REPOSITORY,
        "base_model_revision": BASE_MODEL_REVISION,
        "tokenizer_repository": TOKENIZER_REPOSITORY,
        "tokenizer_revision": TOKENIZER_REVISION,
        "quantization": {
            "load_in_4bit": True,
            "quantization_type": "nf4",
            "double_quantization": True,
            "compute_dtype": "bfloat16",
        },
        "lora": {
            "rank": 16,
            "alpha": 32,
            "dropout": 0.0,
            "target_modules": [
                "down_proj",
                "gate_proj",
                "k_proj",
                "o_proj",
                "q_proj",
                "up_proj",
                "v_proj",
            ],
            "bias": "none",
            "use_rslora": False,
        },
        "optimization": {
            "max_sequence_length": 1536,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 4,
            "learning_rate": 0.0001,
            "weight_decay": 0.01,
            "warmup_ratio": 0.03,
            "num_train_epochs": 1.0,
            "optimizer": "adamw_8bit",
            "scheduler": "linear",
            "precision": "bf16",
            "gradient_checkpointing": True,
            "gradient_clip_norm": 1.0,
            "logging_steps": 10,
        },
        "checkpoints": {
            "save_steps": 1000,
            "evaluation_steps": 1000,
            "save_total_limit": 3,
            "load_best_model_at_end": True,
            "metric_for_best_model": "eval_loss",
            "greater_is_better": False,
        },
        "seed": CAMPAIGN_SEED,
        "single_gpu_only": True,
        "expected_gpu_class": "RTX-4060-8GB",
        "authorization_required_before_training": True,
    }
    return {**snapshot, "content_hash": snapshot_content_hash(snapshot)}


def campaign_snapshot() -> dict[str, object]:
    snapshot = {
        "policy_id": CAMPAIGN_POLICY_ID,
        "project_variant_count": PROJECT_VARIANT_COUNT,
        "scenario_family_count": len(FAMILIES),
        "languages": [language.value for language in LANGUAGES],
        "target_total_examples": TARGET_TOTAL_EXAMPLES,
        "minimum_train_examples": MINIMUM_TRAIN_EXAMPLES,
        "minimum_validation_examples": MINIMUM_VALIDATION_EXAMPLES,
        "minimum_internal_test_examples": MINIMUM_INTERNAL_TEST_EXAMPLES,
        "target_abstention_fraction": TARGET_ABSTENTION_FRACTION,
        "split_policy": SPLIT_POLICY.to_snapshot(),
        "family_ids": [family.family_id for family in FAMILIES],
        "domains": sorted({family.domain for family in FAMILIES}),
        "roles": sorted({family.role for family in FAMILIES}),
        "platforms": sorted({family.platform.value for family in FAMILIES}),
        "risks": sorted({family.risk.value for family in FAMILIES}),
        "criteria": sorted({family.criterion.value for family in FAMILIES}),
        "severities": sorted({family.severity.value for family in FAMILIES}),
        "selection_decision": selection_decision_snapshot(),
        "qlora_policy": final_qlora_policy_snapshot(),
        "methodological_notice": (
            "This curriculum is synthetic supervised material for a shared User Twin "
            "evaluator. It teaches structured output, provenance, role discipline, "
            "abstention and epistemic boundaries. It is not empirical evidence about real "
            "target users and does not make the model a replica of any person."
        ),
    }
    return {**snapshot, "content_hash": snapshot_content_hash(snapshot)}


def expected_example_count() -> int:
    return PROJECT_VARIANT_COUNT * len(FAMILIES) * len(LANGUAGES)


def _language_text(
    language: DatasetLanguage,
    english: str,
    italian: str,
) -> str:
    return english if language is DatasetLanguage.ENGLISH else italian


def _deterministic_uuid(kind: str, project_index: int, family_id: str) -> UUID:
    return uuid5(DATASET_NAMESPACE, f"{kind}:{project_index}:{family_id}")


def build_example(
    *,
    ordinal: int,
    project_index: int,
    family: ThesisScenarioFamily,
    language: DatasetLanguage,
) -> EvaluatorDatasetExample:
    """Build one validated content-addressed synthetic curriculum example."""
    project_id = _deterministic_uuid("project", project_index, "shared")
    brief_id = _deterministic_uuid("brief", project_index, family.family_id)
    twin_id = _deterministic_uuid("twin", project_index, family.family_id)
    artifact_id = _deterministic_uuid("artifact", project_index, family.family_id)

    experience = EXPERIENCE_LEVELS[project_index % len(EXPERIENCE_LEVELS)]
    context = _language_text(
        language,
        CONTEXTS_EN[project_index % len(CONTEXTS_EN)],
        CONTEXTS_IT[project_index % len(CONTEXTS_IT)],
    )
    constraint = _language_text(
        language,
        CONSTRAINTS_EN[(project_index + ordinal) % len(CONSTRAINTS_EN)],
        CONSTRAINTS_IT[(project_index + ordinal) % len(CONSTRAINTS_IT)],
    )
    artifact_state = _language_text(
        language,
        ARTIFACT_STATES_EN[(project_index * 3 + ordinal) % len(ARTIFACT_STATES_EN)],
        ARTIFACT_STATES_IT[(project_index * 3 + ordinal) % len(ARTIFACT_STATES_IT)],
    )
    target_task = _language_text(language, family.task_en, family.task_it)

    brief_summary = _language_text(
        language,
        (
            f"A {family.domain} product supports a {experience} {family.role}; "
            f"the primary task is to {target_task}."
        ),
        (
            f"Un prodotto nel dominio {family.domain} supporta un utente {family.role} "
            f"con esperienza {experience}; il compito principale è {target_task}."
        ),
    )
    scenario = _language_text(
        language,
        (
            f"The {family.role} must {target_task} {context}. The interaction {constraint}. "
            f"The review focuses on {family.risk.value.casefold().replace('_', ' ')}."
        ),
        (
            f"L'utente {family.role} deve {target_task} {context}. L'interazione {constraint}. "
            f"La revisione riguarda {family.risk.value.casefold().replace('_', ' ')}."
        ),
    )
    artifact_description = _language_text(
        language,
        f"The candidate artifact is {artifact_state}.",
        f"L'artefatto candidato è {artifact_state}.",
    )

    brief_hash = snapshot_content_hash(
        {"project_id": str(project_id), "family": family.family_id, "summary": brief_summary}
    )
    twin_profile = {
        "synthetic_profile": True,
        "role": family.role,
        "experience_level": experience,
        "domain": family.domain,
        "platform": family.platform.value,
        "goal": target_task,
        "constraint": constraint,
        "project_variant": project_index,
        "methodological_status": "DESIGN_HYPOTHESIS_NOT_REAL_USER",
    }
    twin_hash = snapshot_content_hash(twin_profile)
    artifact_hash = snapshot_content_hash(
        {
            "artifact_id": str(artifact_id),
            "family": family.family_id,
            "description": artifact_description,
        }
    )

    brief_reference = DatasetVersionedArtifactReference(
        artifact_id=brief_id,
        version_number=1,
        content_hash=brief_hash,
    )
    twin_reference = DatasetUserTwinReference(
        twin_id=twin_id,
        version_number=1,
        content_hash=twin_hash,
        lifecycle_status=UserTwinLifecycleStatus.PROTO_UT,
    )
    artifact = DatasetArtifactSnapshot(
        reference=DatasetVersionedArtifactReference(
            artifact_id=artifact_id,
            version_number=1,
            content_hash=artifact_hash,
        ),
        media_type="application/vnd.orchestwin.synthetic-artifact+json",
        description=artifact_description,
    )

    evidence_1_hash = snapshot_content_hash({"brief": brief_summary, "constraint": constraint})
    evidence_2_hash = snapshot_content_hash(
        {"artifact": artifact_description, "risk": family.risk.value}
    )
    evidence = (
        DatasetEvidenceReference(
            reference_id="EVID-001",
            kind=DatasetEvidenceKind.PROJECT_BRIEF,
            source_id=str(brief_id),
            source_version=1,
            content_hash=evidence_1_hash,
            locator="project-brief",
        ),
        DatasetEvidenceReference(
            reference_id="EVID-002",
            kind=DatasetEvidenceKind.PROJECT_ARTIFACT,
            source_id=str(artifact_id),
            source_version=1,
            content_hash=evidence_2_hash,
            locator="candidate-artifact",
        ),
    )

    if family.abstain:
        findings = ()
        gaps = (
            _language_text(
                language,
                "The available evidence is insufficient or contradictory for a defensible finding.",
                "Le evidenze disponibili sono insufficienti o contraddittorie per un finding difendibile.",
            ),
        )
        overall_summary = _language_text(
            language,
            "Abstain from a substantive finding until the identified evidence gap is resolved.",
            "Astenersi da un finding sostanziale finché il gap di evidenza non viene risolto.",
        )
    else:
        finding = create_synthetic_finding(
            finding_id="UTF-000001",
            twin_id=twin_id,
            twin_version=1,
            artifact_id=artifact_id,
            artifact_version=1,
            location="primary-task",
            summary=_language_text(
                language,
                f"The artifact may hinder the {family.role} during the primary task.",
                f"L'artefatto può ostacolare l'utente {family.role} durante il compito principale.",
            ),
            rationale=_language_text(
                language,
                (
                    f"The observed {family.risk.value.casefold().replace('_', ' ')} concern "
                    f"is grounded in EVID-001 and EVID-002, but remains simulated feedback."
                ),
                (
                    f"La criticità relativa a {family.risk.value.casefold().replace('_', ' ')} "
                    f"è supportata da EVID-001 ed EVID-002, ma resta feedback simulato."
                ),
            ),
            criterion=family.criterion,
            severity=family.severity,
            epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            evidence_refs=("EVID-001", "EVID-002"),
            confidence=0.72,
            recommended_action=_language_text(
                language,
                f"Revise the interaction to support the stated constraint: {constraint}.",
                f"Rivedere l'interazione per supportare il vincolo dichiarato: {constraint}.",
            ),
            requires_human_validation=True,
            model_config_ref="researcher-template-synthesis-v1",
            prompt_version_ref="ut-evaluator-thesis-curriculum-v1",
        )
        findings = (finding,)
        gaps = ()
        overall_summary = _language_text(
            language,
            "The synthetic review identifies one evidence-grounded design hypothesis.",
            "La revisione sintetica identifica una ipotesi di design fondata sulle evidenze.",
        )

    return create_evaluator_dataset_example(
        example_id=f"UTE-{ordinal:06d}",
        project_id=project_id,
        scenario_family_id=family.family_id,
        language=language,
        source_kind=DatasetExampleSourceKind.SYNTHETIC_GENERATED,
        use_restriction=DatasetUseRestriction.NONE,
        project_brief_reference=brief_reference,
        project_brief_summary=brief_summary,
        user_twin_reference=twin_reference,
        user_twin_profile=twin_profile,
        scenario=scenario,
        target_task=target_task,
        artifact=artifact,
        evidence=evidence,
        rubric_id="user-twin-evaluator-thesis-rubric",
        rubric_version=1,
        rubric_criteria=tuple(SyntheticFindingCriterion),
        output_schema_ref="user-twin-evaluator-benchmark-output-v1",
        overall_summary=overall_summary,
        findings=findings,
        evidence_gaps=gaps,
        abstained=family.abstain,
        generation_ref=CAMPAIGN_POLICY_ID,
    )


def iter_campaign_examples():
    ordinal = 0
    for project_index in range(1, PROJECT_VARIANT_COUNT + 1):
        for family in FAMILIES:
            for language in LANGUAGES:
                ordinal += 1
                yield build_example(
                    ordinal=ordinal,
                    project_index=project_index,
                    family=family,
                    language=language,
                )


def build_campaign_dataset() -> tuple[tuple[EvaluatorDatasetExample, ...], object]:
    examples = tuple(iter_campaign_examples())
    split = split_dataset_examples(examples, policy=SPLIT_POLICY)
    return examples, split


def validate_campaign_dataset(
    examples: tuple[EvaluatorDatasetExample, ...],
    split,
) -> dict[str, object]:
    """Publication/training gate for the final synthetic curriculum."""
    if len(examples) != TARGET_TOTAL_EXAMPLES:
        raise ValueError("final thesis dataset total does not match the frozen campaign")
    if len({example.example_id for example in examples}) != len(examples):
        raise ValueError("final thesis dataset contains duplicate example IDs")
    if len({example.content_hash for example in examples}) != len(examples):
        raise ValueError("final thesis dataset contains duplicate content hashes")
    if not split.publishable:
        raise ValueError("final thesis dataset has publication-blocking leakage")

    counts = {key: len(split.examples_for(key)) for key in DatasetSplit}
    if counts[DatasetSplit.TRAIN] < MINIMUM_TRAIN_EXAMPLES:
        raise ValueError("training split is smaller than the thesis minimum")
    if counts[DatasetSplit.VALIDATION] < MINIMUM_VALIDATION_EXAMPLES:
        raise ValueError("validation split is smaller than the thesis minimum")
    if counts[DatasetSplit.INTERNAL_TEST] < MINIMUM_INTERNAL_TEST_EXAMPLES:
        raise ValueError("internal test split is smaller than the thesis minimum")

    language_counts = {
        language.value: sum(example.language is language for example in examples)
        for language in LANGUAGES
    }
    if set(language_counts.values()) != {TARGET_TOTAL_EXAMPLES // 2}:
        raise ValueError("final thesis dataset is not exactly bilingual-balanced")

    abstained = sum(example.expected_output.abstained for example in examples)
    if abstained / len(examples) != TARGET_ABSTENTION_FRACTION:
        raise ValueError("final thesis dataset abstention balance changed")

    domains = {family.domain for family in FAMILIES}
    roles = {family.role for family in FAMILIES}
    criteria = {family.criterion for family in FAMILIES}
    severities = {family.severity for family in FAMILIES}
    risks = {family.risk for family in FAMILIES}
    platforms = {family.platform for family in FAMILIES}
    if len(domains) < 20 or len(roles) < 20:
        raise ValueError("final thesis dataset lacks domain/role breadth")
    if criteria != set(SyntheticFindingCriterion):
        raise ValueError("final thesis dataset does not cover every UCD criterion")
    if severities != set(SyntheticFindingSeverity):
        raise ValueError("final thesis dataset does not cover every severity")
    if risks != set(CampaignRisk) or platforms != set(CampaignPlatform):
        raise ValueError("final thesis dataset does not cover the frozen risk/platform matrix")

    result = {
        "policy_id": CAMPAIGN_POLICY_ID,
        "total_examples": len(examples),
        "split_counts": {split_key.value: value for split_key, value in counts.items()},
        "language_counts": language_counts,
        "abstained_examples": abstained,
        "abstention_fraction": abstained / len(examples),
        "domain_count": len(domains),
        "role_count": len(roles),
        "scenario_family_count": len(FAMILIES),
        "project_variant_count": PROJECT_VARIANT_COUNT,
        "leakage_issue_count": len(split.leakage_issues),
        "publishable": split.publishable,
        "selection_decision_content_hash": selection_decision_snapshot()["content_hash"],
        "qlora_policy_content_hash": final_qlora_policy_snapshot()["content_hash"],
        "campaign_content_hash": campaign_snapshot()["content_hash"],
        "methodological_status": "SYNTHETIC_DESIGN_HYPOTHESES_NOT_EMPIRICAL_USER_DATA",
    }
    return {**result, "content_hash": snapshot_content_hash(result)}
