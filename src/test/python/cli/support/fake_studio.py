from __future__ import annotations

import asyncio
import contextlib
import copy
import email.parser
import email.policy
import email.utils
import hashlib
import html
import itertools
import json
import math
import re
import socketserver
import threading
import traceback
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import MappingProxyType
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.agents.persistence.repositories import proposal_from_snapshot
from orchestwin.agents.perspectives import perspective_views
from orchestwin.agents.realignment import reanchored_team, team_selection_can_realign
from orchestwin.agents.selection_rules import (
    DeterministicTeamConstraints,
    RuleEvidence,
    TeamRoleConstraint,
    TeamRoleConstraintKind,
    TeamSelectionIssue,
    TeamSelectionIssueCode,
    TeamSelectionReason,
    TeamSelectionReasonCode,
    determine_team_constraints,
)
from orchestwin.agents.team_gate import OWNER_CHOICE_STATEMENT
from orchestwin.api.requirements import (
    RequirementsSpecificationDiffPayload,
    RequirementsSpecificationPayload,
)
from orchestwin.api.research_evidence import EvidenceBody
from orchestwin.artifacts.bound_mockups import create_bound_mockup, markup_requirement_codes
from orchestwin.artifacts.design_evaluation import (
    ANCHOR_LABEL_LENGTH,
    MATCH_SIMILARITY,
    anchor_finding,
    finding_similarity,
    synthetic_finding_from_snapshot,
)
from orchestwin.artifacts.generated_mockup_document import MockupPin, mockup_document
from orchestwin.artifacts.generated_mockup_review import (
    MockupIssueSeverity,
    review_generated_mockup,
)
from orchestwin.artifacts.generated_mockup_structure import nodes_text
from orchestwin.artifacts.generated_mockup_styles import FORBIDDEN_CHARACTERS
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockup,
    create_generated_mockup,
    generated_mockup_from_snapshot,
    screen_trees,
)
from orchestwin.artifacts.visual_catalog import MODES, VisualChoices
from orchestwin.artifacts.visual_language import TwinFit, create_visual_language
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.identity.domain import InvalidEmailAddress, NormalizedEmail
from orchestwin.identity.passwords import (
    PasswordPolicy,
    PasswordPolicyError,
    PasswordPolicyViolation,
)
from orchestwin.knowledge.archive import (
    MAX_ARCHIVE_SIZE,
    KnowledgeArchiveError,
    read_verified_folder,
)
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.sources import KnowledgeSources
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.state import (
    APPLICATION_KINDS,
    BROWSER_NAMES,
    DECISIONS,
    FILE_KINDS,
    INTERACTIVE_ROLES,
    MAX_ADDRESS_LENGTH,
    MAX_AUTHOR_LENGTH,
    MAX_BASIS_LENGTH,
    MAX_BROWSER_VERSION_LENGTH,
    MAX_BROWSERS,
    MAX_CRITERIA_PER_PATH,
    MAX_DIFF_LENGTH,
    MAX_EARLIER_PATHS,
    MAX_EXPECTED_TEXT_LENGTH,
    MAX_FILES,
    MAX_FINDINGS,
    MAX_FOLDER_TEST_RUNS,
    MAX_LEARNED_OBSERVATIONS,
    MAX_MESSAGE_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_OBSERVATION_LENGTH,
    MAX_PAGE_TEXT_LENGTH,
    MAX_PATH_HEADING_LENGTH,
    MAX_PATH_LENGTH,
    MAX_REASON_LENGTH,
    MAX_RESULTS,
    MAX_SCREENSHOT_PATH_LENGTH,
    MAX_SNAPSHOT_ELEMENTS,
    MAX_SNAPSHOT_OPTIONS,
    MAX_STEP_DETAIL_LENGTH,
    MAX_STEP_VALUE_LENGTH,
    MAX_STEPS,
    MAX_TARGET_NAME_LENGTH,
    MAX_TASK_LENGTH,
    MAX_TASK_NOTE_LENGTH,
    MAX_TASKS,
    MAX_UPDATE_CHANGES,
    MAX_UPDATE_OBSERVATIONS,
    MAX_UPDATE_TESTS,
    OBSERVATION_CODE_PREFIX,
    PATH_STATUSES,
    STEP_STATUSES,
    TASK_STATUSES,
    TEST_ACTIONS,
    TEST_EXPECTATIONS,
    TEST_KEYS,
    TEST_ROLES,
    UPDATE_DECISIONS,
    ProjectStateSources,
    review_is_stale,
)
from orchestwin.models.evidence_update import (
    EvidenceUpdateOutput,
    bind_evidence_update,
    evidence_update_context,
)
from orchestwin.models.fake_design import (
    _ALTERNATIVE_TEMPLATES,
    FAKE_DESIGN_PROVIDER_ID,
    FAKE_DESIGN_PROVIDER_VERSION,
)
from orchestwin.models.fake_team_proposals import FakeDeterministicTeamProposalAdapter
from orchestwin.models.output_language import dominant_language
from orchestwin.models.proposal_tasks import TASKS as PROPOSAL_TASKS
from orchestwin.projects.brief_dialogue import (
    ACTIVE_STATUSES,
    ESSENTIAL_FIELDS,
    MAX_ANSWER_CHARACTERS,
    MAX_ANSWER_ITEMS,
    MAX_DIALOGUE_QUESTIONS,
    MAX_STATEMENT_CHARACTERS,
    BriefDialogue,
    BriefDialogueStatus,
    BriefDialogueTurn,
    DialogueAnswer,
    DialogueAnswerKind,
    normalized_block,
)
from orchestwin.projects.briefs import (
    LIST_FIELDS,
    BriefField,
    ProjectBrief,
    create_project_brief,
)
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
    accept_brief_assumption,
    create_brief_assumption,
    reject_brief_assumption,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.evidence_application import (
    apply_evidence_change,
    evidence_profile,
    withdrawn_observation,
)
from orchestwin.projects.progress import (
    CURRENT_CATALOG,
    ArtifactVersion,
    CatalogVersion,
    GateState,
    ProjectProgressFacts,
    ProjectStage,
    TeamState,
    UserTwinsState,
    project_progress,
)
from orchestwin.projects.requirements_revisions import propose_requirements_diff
from orchestwin.projects.research_evidence import (
    EvidenceChange,
    EvidenceStatus,
    EvidenceVersion,
    ResearchEvidenceError,
    evidence_content_hash,
    normalize_evidence_text,
)
from orchestwin.projects.sections import (
    BriefFacts,
    DesignFacts,
    FolderFacts,
    ProjectSections,
    RequirementsFacts,
    SectionBlock,
    SectionFacts,
    SectionState,
    TeamFacts,
    UserTwinsFacts,
    project_sections,
    requirements_actor_codes,
)
from orchestwin.twins.archetypes import ArchetypeFailure, ArchetypeService
from orchestwin.twins.conversations import (
    MAX_QUESTION_CHARACTERS,
    MAX_TURNS_PER_CONVERSATION,
    TwinConversation,
    TwinConversationTurn,
    TwinInsight,
    TwinInsightKind,
    normalized_text,
)
from orchestwin.twins.epistemics import EvidenceSourceKind
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.persistence.snapshots import (
    persona_profile_from_snapshot,
    user_twin_profile_from_snapshot,
)
from orchestwin.twins.personas import PersonaProfileVersion
from orchestwin.twins.representation import ArchetypeInput, archetype_payload, twin_view
from orchestwin.twins.user_twins import (
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_user_modeling_snapshot,
)
from orchestwin.workflow.gates import (
    DEFAULT_GATE_ITERATION_LIMIT,
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    next_human_gate_iteration,
    transition_human_gate,
)

PREFIX = "/api/v1"
EPOCH = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
ACCESS_SECONDS = 86_400
REFRESH_SECONDS = 2_592_000
COOKIE_NAME = "orchestwin_refresh"
COOKIE_PATH = "/api/v1/auth"
MODEL = "fake-model-not-real"
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
MAX_RUNNING_JOBS = 4
MAX_TWINS = 8
MAX_ITERATION_REQUEST = 1000
MAX_NEW_ASSERTIONS = 5
MAX_OWNER_ASSERTIONS = 20
MAX_OWNER_ASSERTION = 300
MAX_CHANGE_REQUEST = 2000
MAX_SOURCE_NAME = 200
MAX_PROJECT_NAME = 120
LANGUAGES = ("it", "en")
STAGES = ("brief", "team", "twins", "requirements", "design")
PROJECT_MODES = ("GREENFIELD_GENERATION", "BROWNFIELD_ASSESSMENT")
JOB_STATUSES = ("RUNNING", "SUCCEEDED", "REJECTED", "FAILED")
BILLINGS = ("SUBSCRIPTION", "API", "MIXED")
REQUEST_OPERATIONS = (
    "PERSONA_PROPOSAL",
    "USER_TWIN_GENERATION",
    "REQUIREMENTS_PROPOSAL",
    "REQUIREMENTS_CHANGE",
    "DESIGN_PROPOSAL",
    "DESIGN_REGENERATION",
    "DESIGN_EVALUATION",
    "CODE_CHANGE_REVIEW",
    "TEST_PLAN",
    "TEST_REVIEW",
    "TWIN_UPDATE",
)
OPERATIONS = ("MOCKUP", "ITERATION", *REQUEST_OPERATIONS)
GATE_ACTIONS = ("SUBMIT", "APPROVE", "REJECT", "REQUEST_REVISION", "PAUSE", "RESUME", "CANCEL")
DECISION_ACTIONS = GATE_ACTIONS[1:]
COSTS = {
    "BRIEF_QUESTION": 12_000,
    "BRIEF_SYNTHESIS": 30_000,
    "TEAM_PROPOSAL": 25_000,
    "PERSONA_PROPOSAL": 50_000,
    "USER_TWIN_GENERATION": 150_000,
    "TWIN_CHAT": 30_000,
    "REQUIREMENTS_PROPOSAL": 280_000,
    "REQUIREMENTS_CHANGE": 300_000,
    "DESIGN_PROPOSAL": 450_000,
    "DESIGN_REGENERATION": 450_000,
    "MOCKUP": 1_450_000,
    "ITERATION": 1_100_000,
    "DESIGN_EVALUATION": 165_000,
    "CODE_CHANGE_REVIEW": 200_000,
    "CODE_ALIGNMENT": 250_000,
    "TEST_PLAN": 200_000,
    "TEST_REVIEW": 150_000,
    "TWIN_UPDATE": 150_000,
}
TASKS = {
    "BRIEF_QUESTION": "brief",
    "BRIEF_SYNTHESIS": "brief",
    "TEAM_PROPOSAL": "team",
    "PERSONA_PROPOSAL": "user_modeling",
    "USER_TWIN_GENERATION": "user_modeling",
    "TWIN_CHAT": "user_modeling",
    "REQUIREMENTS_PROPOSAL": "requirements",
    "REQUIREMENTS_CHANGE": "requirements",
    "DESIGN_PROPOSAL": "design",
    "DESIGN_REGENERATION": "design",
    "MOCKUP": "design",
    "ITERATION": "design",
    "DESIGN_EVALUATION": "twin_review",
    "CODE_CHANGE_REVIEW": "user-twin-evaluation",
    "CODE_ALIGNMENT": "user-twin-evaluation",
    "TEST_PLAN": "requirements",
    "TEST_REVIEW": "user-twin-evaluation",
    "TWIN_UPDATE": "user-twin-evaluation",
}
PURPOSES = {
    "BRIEF_QUESTION": "BRIEF_QUESTION",
    "BRIEF_SYNTHESIS": "BRIEF_SYNTHESIS",
    "TEAM_PROPOSAL": "TEAM_PROPOSAL",
    "PERSONA_PROPOSAL": "PERSONA_PROPOSAL",
    "USER_TWIN_GENERATION": "USER_TWIN_GENERATION",
    "TWIN_CHAT": "TWIN_CHAT",
    "REQUIREMENTS_PROPOSAL": "REQUIREMENTS_PROPOSAL",
    "REQUIREMENTS_CHANGE": "REQUIREMENTS_CHANGE",
    "DESIGN_PROPOSAL": "DESIGN_ALTERNATIVES_HOSTED",
    "DESIGN_REGENERATION": "DESIGN_ALTERNATIVES_HOSTED",
    "MOCKUP": "DESIGN_MOCKUP_HTML",
    "ITERATION": "DESIGN_ITERATION",
    "DESIGN_EVALUATION": "DESIGN_TWIN_REVIEW",
    "CODE_CHANGE_REVIEW": "CODE_CHANGE_REVIEW",
    "CODE_ALIGNMENT": "CODE_ALIGNMENT",
    "TEST_PLAN": "TEST_PLAN",
    "TEST_REVIEW": "TEST_REVIEW",
    "TWIN_UPDATE": "TWIN_UPDATE",
}
GATE_TYPES = {
    "brief": HumanGateType.PROJECT_BRIEF,
    "team": HumanGateType.AGENT_TEAM,
    "twins": HumanGateType.USER_MODELING,
    "requirements": HumanGateType.REQUIREMENTS,
    "design": HumanGateType.DESIGN,
}
NEW_ARTIFACT_REQUIRED = {
    "brief": "NEW_BRIEF_REQUIRED",
    "team": "NEW_PROPOSAL_REQUIRED",
    "twins": "NEW_SNAPSHOT_REQUIRED",
    "requirements": "NEW_SPECIFICATION_REQUIRED",
    "design": "NEW_PACKAGE_REQUIRED",
}
APPROVAL_CODES = (
    ("brief", "BRIEF_APPROVAL_REQUIRED"),
    ("team", "TEAM_APPROVAL_REQUIRED"),
    ("twins", "USER_MODELING_APPROVAL_REQUIRED"),
    ("requirements", "REQUIREMENTS_APPROVAL_REQUIRED"),
    ("design", "DESIGN_APPROVAL_REQUIRED"),
)
FEEDBACK_KEYS = (
    "reviews",
    "findings",
    "decisions",
    "discussions",
    "insights",
    "change_reviews",
    "test_runs",
    "learned_observations",
)
STATE_KEYS = ("changes", "pending_changes", "stale_reviews", "aligned_commit", "open_tasks")
AGENT_ORDER = tuple(entry.agent_id.value for entry in all_agent_catalog_entries())
ALWAYS_PRESENT = frozenset(
    entry.agent_id.value for entry in all_agent_catalog_entries() if entry.is_always_present
)
SUGGESTED_SPECIALISTS = ("FRONTEND_ENGINEER",)
DESIGNER = "UX_UI_DESIGNER"
DETERMINISTIC_TEAM_PROVIDER = FakeDeterministicTeamProposalAdapter.PROVIDER_ID
HOSTED_TEAM_PROVIDER = "fake-team-proposer"
RULE_KEYS = ("constraints_content_hash", "role_constraints", "constraint_issues")
TEAM_CONTENT_KEYS = (
    "schema_version",
    "provider_kind",
    "provider_id",
    "provider_version",
    "project_mode",
    "brief_version_id",
    "brief_version_number",
    "brief_content_hash",
    "catalog_version",
    "catalog_content_hash",
    "constraints_content_hash",
)
ANCHOR_KINDS = {
    "action": ("SCR-001", ("LINK", "BUTTON"), True),
    "result": ("SCR-002", ("STATUS", "TEXT", "LIST", "CARD"), False),
    "title": ("SCR-002", ("HEADING",), False),
}
PIN_LABEL_LENGTH = 120
DOCUMENT_LANGUAGE = "en"
REVIEW_LANGUAGE = "und"
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
ENTRY_SCREEN_PATTERN = re.compile(r"SCR-[0-9]{3}")
LEADING_SCREEN = re.compile(r"(SCR-[0-9]{3,6})(?![0-9])")
LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,7}")
TEMPLATE_PARAMETER = re.compile(r"\{([a-z_]+)\}")
COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")
REQUIREMENT_CODE = re.compile(r"\bREQ-[0-9]{3,6}\b")
LOCALE_PATTERN = re.compile(r"[a-z]{2,3}(-[A-Z]{2})?")
MAX_LOCALE_LENGTH = 20
DEFAULT_LOCALE = "it-IT"
LAX_BOOLEANS = {
    "0": False,
    "off": False,
    "f": False,
    "false": False,
    "n": False,
    "no": False,
    "1": True,
    "on": True,
    "t": True,
    "true": True,
    "y": True,
    "yes": True,
}
ALIGNMENT_WORDS = (
    ("CODE_DRIFT", ("drift",)),
    ("DESIGN_OUTDATED", ("design",)),
    ("REQUIREMENTS_OUTDATED", ("requisit", "requirement")),
)
SECTION_STAGES = {
    "BRIEF": "brief",
    "TEAM": "team",
    "USER_TWINS": "twins",
    "REQUIREMENTS": "requirements",
    "DESIGN": "design",
}
FOLDER_SECTIONS = {stage: ProjectStage(key) for key, stage in SECTION_STAGES.items()}
DESIGN_ALIGNMENT_STATES = frozenset(
    {SectionState.FINE, SectionState.UPDATE_AVAILABLE, SectionState.TO_UPDATE}
)
GESTURE_ISSUES = {
    "USER_TWIN_REVISION_PENDING": "REVISION_PENDING",
    "REQUIREMENTS_REVISION_PENDING": "REVISION_PENDING",
    "DESIGN_REVISION_PENDING": "REVISION_PENDING",
    "BRIEF_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
    "TEAM_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
    "USER_TWINS_REQUIRED": "UPSTREAM_NOT_READY",
    "USER_TWINS_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
    "REQUIREMENTS_APPROVAL_REQUIRED": "UPSTREAM_NOT_READY",
}
ALIGNMENT_REASON = "Aligned to the current upstream versions with unchanged content."
SPECIFICATION_ITEMS = ("requirements", "user_stories", "acceptance_criteria")
CITED_KEYS = ("requirement_ids", "user_story_ids", "acceptance_criterion_ids")
FIRST_LINE_LENGTH = 120
LIST_LIMIT = 20
CRITERION_LENGTH = 20
MAX_RAW_TEXT_LENGTH = 100_000
MAX_REPLANS = 5
MAX_REQUESTED_CRITERIA = 200
MAX_PATH_SECONDS = 86_400
MAX_SNAPSHOT_URL_LENGTH = 2000
MAX_SNAPSHOT_TITLE_LENGTH = 300
CUT_MARK = "…"
PATH_CODE = re.compile(r"TP-[0-9]{3,6}")
CRITERION_CODE = re.compile(r"AC-[0-9]{3,6}")
CRITERION_REQUEST = re.compile(r"[A-Za-z0-9-]+")
ELEMENT_STATES = ("checked", "disabled")
FAILING_STATUSES = ("FAILED", "BLOCKED")
TARGET_ACTIONS = ("CLICK", "TYPE", "SELECT")
VALUE_ACTIONS = ("OPEN", "TYPE", "SELECT", "PRESS")
ACTION_ROLES = {
    "CLICK": (*INTERACTIVE_ROLES, "text", "image", "listitem", "cell", "heading"),
    "TYPE": ("textbox", "spinbutton", "combobox", "slider"),
    "SELECT": ("combobox",),
}
TARGET_EXPECTATIONS = ("ELEMENT_VISIBLE", "ELEMENT_ABSENT", "VALUE_IS")
TEXT_EXPECTATIONS = ("TEXT_VISIBLE", "TEXT_ABSENT", "VALUE_IS", "URL_CONTAINS", "TITLE_CONTAINS")
SUMMARY_KEYS = ("passed", "failed", "blocked", "not_covered", "not_run")
MANUAL_WORD = "manual"
HEADING_LENGTH = 60
CHECK_WORDS = 3
TITLE_WORD = "a"
TARGET_FIELDS = ("role", "name")
EXPECTATION_FIELDS = ("kind", "target", "text")
STEP_FIELDS = ("action", "target", "value", "expect")
PATH_FIELDS = ("code", "heading", "criteria", "steps")
EARLIER_FIELDS = (*PATH_FIELDS, "blocked_step", "detail", "snapshot")
APPLICATION_FIELDS = ("kind", "address")
SNAPSHOT_FIELDS = ("url", "title", "text", "hidden_text", "elements")
ELEMENT_FIELDS = ("index", "role", "name", "value", "state", "options")
PLAN_FIELDS = ("locale", "application", "snapshot", "criteria", "earlier")
RUN_FIELDS = (
    "plan_id",
    "replan_ids",
    "started_at",
    "finished_at",
    "application",
    "browsers",
    "results",
    "not_covered",
)
BROWSER_FIELDS = ("name", "version")
RESULT_FIELDS = ("path", "browser", "status", "seconds", "steps", "page_text")
STEP_RESULT_FIELDS = ("index", "status", "detail", "url", "title", "screenshot")
NOT_COVERED_FIELDS = ("criterion", "reason")
TASK_CODE = re.compile(r"TSK-[0-9]{3,6}", re.IGNORECASE)
OBSERVATION_CODE = re.compile(r"OBS-[0-9]{3,6}", re.IGNORECASE)
REQUIREMENT_REFERENCE = re.compile(r"REQ-[0-9]{3,6}")
SCREEN_REFERENCE = re.compile(r"SCR-[0-9]{3,6}")
TASK_FILTERS = ("open", "all")
TASK_FIELDS = ("tasks",)
TASK_ITEM_FIELDS = ("text", "source")
SOURCE_FIELDS = {
    "OWNER": ("kind",),
    "TEST_RUN": ("kind", "test_run_id", "twin_id", "finding"),
    "CODE_CHANGE": ("kind", "commit", "twin_id", "finding"),
}
FINDING_FIELDS = ("twin_id", "finding")
TASK_STATUS_FIELDS = ("status", "note")
DECISION_FIELDS = ("kind", "note", "tasks", "findings")
CLOSED_STATUSES = ("DONE", "DROPPED")
UPDATE_FIELDS = ("locale", "evidence_id", "evidence_version")
UPDATE_DECISION_FIELDS = ("decision", "kept", "reason")
KEPT_FIELDS = ("index", "statement")
OBSERVATION_FIELDS = ("statement", "about")
ABOUT_FIELDS = ("requirement", "screen")
RETIRE_FIELDS = ("reason",)
SEED_FILE = {"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}
SEED_DIFF = "diff --git a/src/app.js b/src/app.js\n+// REQ-003 splits the bill\n"
SEED_AUTHOR = "Test Author"
SEED_ADDRESS = "dist"
SEED_BROWSER = {"name": "chrome", "version": "151.0.7922.76"}
SEED_PAGE = "http://127.0.0.1:41234/"
PROPOSED_OBSERVATIONS = 2
MAX_OBSERVATION_NUMBER = 999_999
UNKNOWN_INDEX = "the proposal has no observation at this index"
LEARNING_TEXTS = {
    "it": {
        "tests": "Un rilievo sulla verifica dei criteri.",
        "commit": "Un rilievo sul commit {commit}.",
        "learned": "Dalle ultime critiche ho imparato {count} cose sul mio gruppo.",
        "nothing": "Le ultime critiche non mi insegnano nulla di nuovo.",
    },
    "en": {
        "tests": "A finding on the acceptance tests.",
        "commit": "A finding on the commit {commit}.",
        "learned": "From the latest critiques I learned {count} things about my group.",
        "nothing": "The latest critiques teach me nothing new.",
    },
}
SEED_TEXTS = {
    "it": {
        "message": "Aggiunge la divisione del conto",
        "owner_task": "Scrivere il testo di aiuto della pagina.",
        "verdict_task": "Coprire il calcolo della mancia con un test automatico.",
        "goal": "Ricordare la percentuale scelta l'ultima volta",
        "requirement": "Il sistema permette di arrotondare la mancia all'euro.",
        "assertion": "Il totale resta visibile in ogni schermata.",
        "observations": (
            (
                "Chi paga al tavolo legge le cifre da lontano, spesso con poca luce.",
                "Un rilievo ripetuto sui commit e sui test.",
            ),
            (
                "Chi divide il conto vuole vedere subito la quota di ciascuno.",
                "Un rilievo sulla verifica dei criteri.",
            ),
        ),
    },
    "en": {
        "message": "Add the split of the bill",
        "owner_task": "Write the help text of the page.",
        "verdict_task": "Cover the tip calculation with an automated test.",
        "goal": "Remember the percentage chosen last time",
        "requirement": "The system lets people round the tip to the euro.",
        "assertion": "The total stays visible on every screen.",
        "observations": (
            (
                "People who pay at the table read the digits from a distance, often in dim light.",
                "A finding repeated on the commits and the tests.",
            ),
            (
                "People who split the bill want to see each share at once.",
                "A finding on the acceptance tests.",
            ),
        ),
    },
}
DISCLAIMER = (
    "This is simulated feedback based on the available profile, evidence, and project "
    "artifacts. It is a design hypothesis and not empirical evidence of real-user behavior."
)
EVALUATOR = {
    "evaluator_id": "fake-twin-reviewer",
    "evaluator_version": "1",
    "model_config_ref": MODEL,
    "prompt_version_ref": "fake-twin-review-v1",
}
DESIGN_OPEN_QUESTIONS = (
    "Which proposed direction should the owner select for declarative prototyping?",
    "Which trade-offs require validation with target users before implementation?",
)
DESIGN_TRUST_CONCERN = (
    "The proposal does not establish how real users will interpret or trust this design."
)
DESIGN_CRITIQUE_RATIONALE = (
    "This deterministic critique translates approved User Twin observations into a design "
    "hypothesis. It is simulated feedback, not empirical evidence."
)
WORKFLOW_STEPS = {
    "GUIDED_WORKFLOW": (
        "Open the guided sequence for {code}.",
        "Collect only the information required by the current step.",
        "Review linked requirements before confirming the outcome.",
    ),
    "DASHBOARD_FIRST": (
        "Review current status and priorities in the operational overview.",
        "Open the contextual action panel for {code}.",
        "Complete the linked actions while preserving overview context.",
        "Return to the overview with updated status and feedback.",
    ),
    "TASK_FOCUSED": (
        "Open the focused workspace for {code}.",
        "Complete the information required by the linked requirements.",
        "Resolve inline validation feedback in the same workspace.",
        "Confirm the expected outcome and review the completion summary.",
    ),
}

QUESTIONS = {
    "it": {
        "description": "Come descriveresti il prodotto in una frase?",
        "problem": "Quale problema risolve il progetto?",
        "target_users": "Chi userà il prodotto?",
        "goals": "Quali risultati vuoi ottenere?",
        "functional_requirements": "Che cosa deve permettere di fare il prodotto?",
    },
    "en": {
        "description": "How would you describe the product in one sentence?",
        "problem": "Which problem does the project solve?",
        "target_users": "Who will use the product?",
        "goals": "Which results do you want to reach?",
        "functional_requirements": "What must the product let people do?",
    },
}
DIALOGUE_FIELDS = ("description", "problem", "target_users", "goals", "functional_requirements")
PROPOSED_FIELDS = ("non_functional_requirements", "definition_of_done")
ESSENTIAL = frozenset(item.value for item in ESSENTIAL_FIELDS)
EXTRA_QUESTIONS = {
    "it": {
        "domain": "In quale ambito lavorerà il prodotto?",
        "technical_constraints": "Ci sono vincoli tecnici da rispettare?",
        "temporal_constraints": "Entro quando deve essere pronto?",
        "budget": "Quale budget hai a disposizione?",
        "non_functional_requirements": "Quali qualità deve avere il prodotto, per esempio "
        "velocità o sicurezza?",
        "risks": "Quali rischi vedi?",
        "stakeholders": "Chi altro è coinvolto nel progetto?",
        "available_artifacts": "Hai già materiale da condividere?",
        "definition_of_done": "Quando considererai il lavoro finito?",
    },
    "en": {
        "domain": "In which domain will the product work?",
        "technical_constraints": "Are there technical constraints to respect?",
        "temporal_constraints": "By when must it be ready?",
        "budget": "Which budget is available?",
        "non_functional_requirements": "Which qualities must the product have, for example "
        "speed or security?",
        "risks": "Which risks do you see?",
        "stakeholders": "Who else is involved in the project?",
        "available_artifacts": "Do you already have material to share?",
        "definition_of_done": "When will you consider the work done?",
    },
}
ASSUMPTIONS = {
    "it": {
        "problem": "Al tavolo serve sapere in fretta quanto lasciare di mancia.",
        "target_users": "Chi paga il conto a fine cena.",
        "goals": "Calcolare la mancia in pochi secondi.",
        "functional_requirements": "Inserire l'importo e vedere subito la mancia.",
        "non_functional_requirements": "La pagina si apre in meno di due secondi da telefono.",
        "definition_of_done": "Il calcolo è verificato con tre conti reali.",
    },
    "en": {
        "problem": "At the table people need to know quickly how much to tip.",
        "target_users": "Whoever pays the bill after dinner.",
        "goals": "Work out the tip in a few seconds.",
        "functional_requirements": "Enter the amount and see the tip at once.",
        "non_functional_requirements": "The page opens in less than two seconds on a phone.",
        "definition_of_done": "The calculation is checked against three real bills.",
    },
}
SEED_BRIEF = {
    "it": {
        "description": "Una pagina web che calcola la mancia e divide il conto tra i commensali.",
        "problem": "Al tavolo nessuno sa quanto lasciare di mancia e dividere il conto è lento.",
        "goals": ("Calcolare la mancia in pochi secondi", "Dividere il conto in parti uguali"),
        "functional_requirements": (
            "Inserire l'importo del conto",
            "Scegliere la percentuale di mancia",
            "Vedere la quota di ogni persona",
        ),
        "domain": "Ristorazione",
    },
    "en": {
        "description": "A web page that works out the tip and splits the bill among diners.",
        "problem": "At the table nobody knows how much to tip and splitting the bill is slow.",
        "goals": ("Work out the tip in a few seconds", "Split the bill in equal shares"),
        "functional_requirements": (
            "Enter the amount of the bill",
            "Choose the tip percentage",
            "See the share of each person",
        ),
        "domain": "Restaurants",
    },
}
PERSONAS = {
    "it": (
        "Cameriere del turno serale",
        "Titolare della pizzeria",
        "Cliente abituale",
        "Cassiera del bar",
        "Turista in vacanza",
        "Studente fuori sede",
        "Responsabile di sala",
        "Contabile del locale",
    ),
    "en": (
        "Evening shift waiter",
        "Pizzeria owner",
        "Regular customer",
        "Bar cashier",
        "Tourist on holiday",
        "Student living away from home",
        "Dining room manager",
        "Restaurant accountant",
    ),
}
PROFILE = {
    "it": {
        "summary": "{name} usa il calcolo della mancia a fine pasto.",
        "goals": ("Chiudere il conto in fretta", "Evitare errori di calcolo"),
        "context": "Al tavolo, dal telefono, spesso con poca luce.",
        "expertise": ("Conti del ristorante",),
        "tasks": ("Calcolare la mancia", "Dividere il conto"),
        "needs": ("Quota per persona",),
        "frustrations": ("Conti a mente sbagliati",),
        "pain_points": ("Attesa alla cassa",),
        "literacy": "Usa il telefono ogni giorno.",
        "assumptions": ("Paga spesso con la carta",),
    },
    "en": {
        "summary": "{name} works out the tip at the end of a meal.",
        "goals": ("Settle the bill quickly", "Avoid calculation mistakes"),
        "context": "At the table, on a phone, often in dim light.",
        "expertise": ("Restaurant bills",),
        "tasks": ("Work out the tip", "Split the bill"),
        "needs": ("Share per person",),
        "frustrations": ("Wrong mental maths",),
        "pain_points": ("Waiting at the till",),
        "literacy": "Uses a phone every day.",
        "assumptions": ("Often pays by card",),
    },
}
TEAM_TEXTS = {
    "it": "Serve per costruire la pagina web del calcolo.",
    "en": "Needed to build the web page of the calculation.",
}
REQUIREMENTS = {
    "it": (
        (
            "FUNCTIONAL",
            "MUST",
            "Inserimento dell'importo",
            "Il sistema permette di inserire l'importo del conto in euro.",
        ),
        (
            "FUNCTIONAL",
            "MUST",
            "Scelta della mancia",
            "Il sistema permette di scegliere la mancia tra 5, 10 e 15 per cento.",
        ),
        (
            "FUNCTIONAL",
            "SHOULD",
            "Divisione del conto",
            "Il sistema mostra la quota di ciascun commensale.",
        ),
        (
            "NON_FUNCTIONAL",
            "MUST",
            "Risposta immediata",
            "Il risultato compare in meno di un secondo.",
        ),
    ),
    "en": (
        ("FUNCTIONAL", "MUST", "Amount entry", "The system lets people enter the bill in euros."),
        (
            "FUNCTIONAL",
            "MUST",
            "Tip choice",
            "The system lets people choose a tip of 5, 10 or 15 percent.",
        ),
        ("FUNCTIONAL", "SHOULD", "Bill split", "The system shows the share of each diner."),
        ("NON_FUNCTIONAL", "MUST", "Immediate answer", "The result appears in under a second."),
    ),
}
STORY = {
    "it": ("calcolare la mancia senza fare conti a mente", "chiudere il conto in fretta"),
    "en": ("work out the tip without mental maths", "settle the bill quickly"),
}
CRITERIA = {
    "it": (
        "Con 30 euro e il 15 per cento la mancia è di 4,50 euro.",
        "L'elenco delle percentuali mostra 5, 10 e 15.",
        "Con 3 persone ogni quota è un terzo del totale.",
        "Il risultato compare entro un secondo.",
    ),
    "en": (
        "With 30 euros and 15 percent the tip is 4.50 euros.",
        "The list of percentages shows 5, 10 and 15.",
        "With 3 people each share is a third of the total.",
        "The result appears within one second.",
    ),
}
SCENARIO = {
    "it": (
        "Mancia a fine cena",
        ("Il conto è arrivato al tavolo",),
        "Il cliente apre la pagina",
        ("Inserisce l'importo", "Sceglie il 10 per cento", "Legge la mancia"),
        "Sa quanto lasciare in pochi secondi",
    ),
    "en": (
        "Tip after dinner",
        ("The bill has reached the table",),
        "The customer opens the page",
        ("Enters the amount", "Chooses 10 percent", "Reads the tip"),
        "Knows how much to leave within seconds",
    ),
}
RISK = {
    "it": ("Arrotondamenti diversi da quelli della cassa", "Mostrare gli importi con due decimali"),
    "en": ("Rounding differs from the till", "Show amounts with two decimals"),
}
DONE = {
    "it": (
        "Tutti i criteri di accettazione sono verificati",
        "La pagina funziona su telefono e computer",
    ),
    "en": ("Every acceptance criterion is verified", "The page works on phone and computer"),
}
OWNER_CHANGE = {"it": "Richiesta del titolare", "en": "Owner request"}
ALTERNATIVES = {
    "it": (
        {
            "code": "DES-001",
            "approach": "GUIDED_WORKFLOW",
            "title": "Calcolo guidato",
            "summary": "Due passi: prima l'importo, poi il risultato.",
            "rationale": "Chi è al tavolo segue un passo alla volta senza distrazioni.",
            "product_name": "Mancia facile",
            "archetype": "GUIDED_STEPS",
            "hue": "TEAL",
            "mode": "LIGHT",
            "tone": "WARM",
        },
        {
            "code": "DES-002",
            "approach": "TASK_FOCUSED",
            "title": "Scheda unica",
            "summary": "Importo, mancia e quote nella stessa scheda.",
            "rationale": "Chi ha fretta vede tutto il calcolo in un colpo d'occhio.",
            "product_name": "Conto chiaro",
            "archetype": "SINGLE_CARD",
            "hue": "COBALT",
            "mode": "DARK",
            "tone": "ESSENTIAL",
        },
    ),
    "en": (
        {
            "code": "DES-001",
            "approach": "GUIDED_WORKFLOW",
            "title": "Guided calculation",
            "summary": "Two steps: first the amount, then the result.",
            "rationale": "People at the table follow one step at a time without distractions.",
            "product_name": "Easy tip",
            "archetype": "GUIDED_STEPS",
            "hue": "TEAL",
            "mode": "LIGHT",
            "tone": "WARM",
        },
        {
            "code": "DES-002",
            "approach": "TASK_FOCUSED",
            "title": "Single card",
            "summary": "Amount, tip and shares on the same card.",
            "rationale": "People in a hurry see the whole calculation at a glance.",
            "product_name": "Clear bill",
            "archetype": "SINGLE_CARD",
            "hue": "COBALT",
            "mode": "DARK",
            "tone": "ESSENTIAL",
        },
    ),
}
DESIGN_TEXTS = {
    "it": {
        "workflow": (
            "Calcolare la mancia",
            ("Inserire l'importo", "Scegliere la percentuale", "Leggere il risultato"),
        ),
        "architecture": ("Calcolo", "Risultato"),
        "accessibility": ("Cifre grandi e contrasto alto",),
        "security": ("Nessun dato personale salvato",),
        "advantages": ("Pochi passi al tavolo",),
        "trade_offs": ("Meno spazio per i dettagli",),
        "assumptions": ("Il cliente ha il telefono in mano",),
        "questions": ("Serve arrotondare la mancia all'euro?",),
        "concern": (
            "I numeri piccoli sono difficili da leggere al buio.",
            "Usare cifre grandi e un buon contrasto.",
        ),
        "fit": "{name} trova subito il totale.",
        "strength": "Il percorso è chiaro.",
        "suggestion": "Aggiungere la divisione del conto.",
        "rationale": "Critica simulata a partire dal profilo del twin.",
    },
    "en": {
        "workflow": (
            "Work out the tip",
            ("Enter the amount", "Choose the percentage", "Read the result"),
        ),
        "architecture": ("Calculation", "Result"),
        "accessibility": ("Large digits and high contrast",),
        "security": ("No personal data stored",),
        "advantages": ("Few steps at the table",),
        "trade_offs": ("Less room for details",),
        "assumptions": ("The customer holds a phone",),
        "questions": ("Should the tip be rounded to the euro?",),
        "concern": (
            "Small numbers are hard to read in the dark.",
            "Use large digits and good contrast.",
        ),
        "fit": "{name} finds the total at once.",
        "strength": "The path is clear.",
        "suggestion": "Add the bill split.",
        "rationale": "Simulated critique based on the twin profile.",
    },
}
CRITIQUES = {
    "it": {
        "DES-001": (
            ("Chiaro al tavolo", "Vedo subito dove inserire l'importo."),
            ("Utile, con riserve", "Mi serve anche dividere il conto."),
        ),
        "DES-002": (
            ("Tutto a portata di mano", "Una sola scheda mi basta."),
            ("Troppo scuro", "Con il tema scuro leggo male i numeri."),
        ),
    },
    "en": {
        "DES-001": (
            ("Clear at the table", "I see at once where to type the amount."),
            ("Useful, with doubts", "I also need to split the bill."),
        ),
        "DES-002": (
            ("Everything at hand", "One card is enough for me."),
            ("Too dark", "With the dark theme I misread the numbers."),
        ),
    },
}
MOCKUP_STYLES = (
    ".page{display:grid;gap:16px;max-width:560px;margin:0 auto;padding:var(--vl-space)}"
    ".card{display:grid;gap:12px;padding:24px;background:var(--vl-color-surface);"
    "border:var(--vl-border-width) solid var(--vl-color-border);"
    "border-radius:var(--vl-radius-panel)}"
    "h1{margin:0;font-family:var(--vl-font-heading);font-size:var(--vl-size-display)}"
    ".lead{margin:0;color:var(--vl-color-text-muted)}"
    "input,select{min-height:var(--vl-control-height);padding:0 12px;"
    "border:1px solid var(--vl-color-text-muted);border-radius:var(--vl-radius-control)}"
    ".button{display:inline-flex;align-items:center;justify-content:center;"
    "min-height:var(--vl-control-height);padding:0 20px;border-radius:var(--vl-radius-control);"
    "background:var(--vl-color-primary);color:var(--vl-color-on-primary);font-weight:700;"
    "text-decoration:none}"
    ".result{margin:0;padding:16px;border-radius:var(--vl-radius-control);"
    "background:var(--vl-color-success-soft);color:var(--vl-color-success);font-weight:700}"
    ".shares{margin:0;padding-left:20px}"
    "@media (max-width:600px){.page{padding:var(--vl-gap)}}"
)
SCREENS = {
    "it": {
        "DES-001": (
            (
                "SCR-001",
                "Importo del conto",
                "DEFAULT",
                "Quanto hai speso?",
                '<main class="page" data-req="REQ-001 REQ-002"><h1>{heading}</h1>'
                '<p class="lead">Scrivi l\'importo del conto e scegli la mancia.</p>'
                '<form class="card" aria-label="Calcolo della mancia">'
                '<label for="amount">Importo del conto</label>'
                '<input id="amount" name="amount" type="text" value="30,00" required>'
                '<label for="tip">Percentuale di mancia</label>'
                '<select id="tip" name="tip" required><option>5%</option>'
                "<option selected>10%</option><option>15%</option></select>"
                '<p class="lead">Di solito la mancia va dal 5% al 10% del conto.</p>'
                '<a class="button" href="#SCR-002">Calcola</a></form></main>',
            ),
            (
                "SCR-002",
                "Risultato",
                "SUCCESS",
                "Ecco la mancia",
                '<main class="page" data-req="REQ-003 REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Esempio: mancia di 3,00 euro su 30,00 euro.</p>'
                '<ul class="shares"><li>Totale da pagare: 33,00 euro</li>'
                "<li>Mancia arrotondata: 3,00 euro</li></ul>"
                '<p class="lead">Il totale compare subito, senza conti a mente.</p>'
                '<a class="button" href="#SCR-001">Nuovo calcolo</a></main>',
            ),
        ),
        "DES-002": (
            (
                "SCR-001",
                "Calcolo mancia",
                "DEFAULT",
                "Calcolo mancia",
                '<main class="card" data-req="REQ-001 REQ-002 REQ-003"><h1>{heading}</h1>'
                '<p class="lead">Inserisci il conto, la mancia e quante persone dividono '
                "la spesa.</p>"
                '<form aria-label="Conto e mancia">'
                '<label for="amount">Importo</label>'
                '<input id="amount" name="amount" type="text" value="34,50" required>'
                '<label for="tip">Mancia</label>'
                '<select id="tip" name="tip"><option>5%</option><option selected>10%</option>'
                "<option>15%</option></select>"
                '<label for="people">Persone al tavolo</label>'
                '<input id="people" name="people" type="text" value="3">'
                '<a class="button" href="#SCR-002">Dividi il conto</a></form>'
                '<ul class="shares"><li>Ultimo conto: 41,20 euro in 4 persone</li></ul></main>',
            ),
            (
                "SCR-002",
                "Conto diviso",
                "SUCCESS",
                "Quota per persona",
                '<main class="card" data-req="REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Esempio: 3 persone, 12,65 euro a testa.</p>'
                '<ul class="shares"><li>Anna: 12,65 euro</li><li>Luca: 12,65 euro</li>'
                "<li>Sara: 12,65 euro</li></ul>"
                '<p class="lead">Ognuno paga la stessa quota, mancia compresa.</p>'
                '<a class="button" href="#SCR-001">Torna al calcolo</a></main>',
            ),
        ),
    },
    "en": {
        "DES-001": (
            (
                "SCR-001",
                "Bill amount",
                "DEFAULT",
                "How much did you spend?",
                '<main class="page" data-req="REQ-001 REQ-002"><h1>{heading}</h1>'
                '<p class="lead">Type the amount of the bill and choose the tip.</p>'
                '<form class="card" aria-label="Tip calculation">'
                '<label for="amount">Bill amount</label>'
                '<input id="amount" name="amount" type="text" value="30.00" required>'
                '<label for="tip">Tip percentage</label>'
                '<select id="tip" name="tip" required><option>5%</option>'
                "<option selected>10%</option><option>15%</option></select>"
                '<p class="lead">In most restaurants a tip ranges from 5% to 10% of the bill.</p>'
                '<a class="button" href="#SCR-002">Calculate</a></form></main>',
            ),
            (
                "SCR-002",
                "Result",
                "SUCCESS",
                "Here is the tip",
                '<main class="page" data-req="REQ-003 REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Example: a tip of 3.00 euros on 30.00 euros.</p>'
                '<ul class="shares"><li>Total to pay: 33.00 euros</li>'
                "<li>Rounded tip: 3.00 euros</li></ul>"
                '<p class="lead">The total appears at once, without mental maths.</p>'
                '<a class="button" href="#SCR-001">New calculation</a></main>',
            ),
        ),
        "DES-002": (
            (
                "SCR-001",
                "Tip calculator",
                "DEFAULT",
                "Tip calculator",
                '<main class="card" data-req="REQ-001 REQ-002 REQ-003"><h1>{heading}</h1>'
                '<p class="lead">Enter the bill, choose the tip and say how many people share '
                "the cost.</p>"
                '<form aria-label="Bill and tip">'
                '<label for="amount">Amount</label>'
                '<input id="amount" name="amount" type="text" value="34.50" required>'
                '<label for="tip">Tip</label>'
                '<select id="tip" name="tip"><option>5%</option><option selected>10%</option>'
                "<option>15%</option></select>"
                '<label for="people">People at the table</label>'
                '<input id="people" name="people" type="text" value="3">'
                '<a class="button" href="#SCR-002">Split the bill</a></form>'
                '<ul class="shares"><li>Last bill: 41.20 euros for 4 people</li></ul></main>',
            ),
            (
                "SCR-002",
                "Split bill",
                "SUCCESS",
                "Share per person",
                '<main class="card" data-req="REQ-004"><h1>{heading}</h1>'
                '<p class="result" role="status">Example: 3 people, 12.65 euros each.</p>'
                '<ul class="shares"><li>Anna: 12.65 euros</li><li>Luca: 12.65 euros</li>'
                "<li>Sara: 12.65 euros</li></ul>"
                '<p class="lead">Everyone pays the same share, tip included.</p>'
                '<a class="button" href="#SCR-001">Back to the calculation</a></main>',
            ),
        ),
    },
}
ITERATED_HEADING = {"it": "Calcola la mancia in un tocco", "en": "Work out the tip in one tap"}
ITERATION_CHANGES = {
    "it": (
        "Il titolo della prima schermata invita a calcolare subito",
        "Il pulsante principale è più grande",
    ),
    "en": (
        "The first screen title invites an immediate calculation",
        "The main button is larger",
    ),
}
APPROACHES = {
    "it": ("Schermate essenziali con esempi realistici.", "Modifica limitata a quanto richiesto."),
    "en": ("Essential screens with realistic examples.", "Change limited to what was asked."),
}
REJECTION = {"it": "la schermata non supera il controllo", "en": "the screen fails the check"}
FINDINGS = {
    "it": {
        "first": (
            (
                (
                    "action",
                    "Il pulsante principale è in fondo: al tavolo lo cerco ogni volta.",
                    "major",
                    "actionability",
                ),
                (
                    "result",
                    "Il risultato è scritto piccolo sul telefono.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "Non vedo come dividere il conto tra più persone.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "later": (
            (
                (
                    "result",
                    "Il risultato è ancora un po' piccolo sul telefono.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "Non vedo come dividere il conto tra più persone.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "other": (
            "title",
            "Il titolo del risultato è chiaro.",
            "observation",
            "comprehensibility",
        ),
        "rationale": "Il profilo del twin usa il telefono al tavolo.",
        "action": "Rendere l'azione principale più visibile.",
        "summary": "Revisione simulata di {name}.",
        "scenario": (
            "Revisione del design",
            "Valutare il mockup scelto al tavolo",
            "Il twin capisce come calcolare la mancia",
        ),
    },
    "en": {
        "first": (
            (
                (
                    "action",
                    "The main button is at the bottom: at the table I look for it every time.",
                    "major",
                    "actionability",
                ),
                (
                    "result",
                    "The result is written small on the phone.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "I cannot see how to split the bill among several people.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "later": (
            (
                (
                    "result",
                    "The result is still a little small on the phone.",
                    "minor",
                    "comprehensibility",
                ),
            ),
            (
                (
                    "SCR-001",
                    "I cannot see how to split the bill among several people.",
                    "moderate",
                    "task_alignment",
                ),
            ),
        ),
        "other": (
            "title",
            "The title of the result is clear.",
            "observation",
            "comprehensibility",
        ),
        "rationale": "The twin profile uses a phone at the table.",
        "action": "Make the main action more visible.",
        "summary": "Simulated review by {name}.",
        "scenario": (
            "Design review",
            "Assess the chosen mockup at the table",
            "The twin understands how to work out the tip",
        ),
    },
}
CHAT = {
    "it": (
        "Sono {name}: mi serve vedere subito quanto lasciare di mancia, senza fare conti.",
        "Vedere subito l'importo della mancia",
    ),
    "en": (
        "I am {name}: I need to see at once how much to tip, without doing the maths.",
        "See the tip amount at once",
    ),
}
CHANGE_CRITIQUES = {
    "it": {
        "CONCERN": "Per «{goal}» la modifica «{line}» mi lascia qualche dubbio: ecco dove.",
        "FINE": "Per «{goal}» la modifica «{line}» mi va bene.",
        "requirement": (
            "Nella pagina non ritrovo ancora quello che chiede il requisito {code}.",
            "Mostrare nella pagina quello che chiede il requisito {code}.",
        ),
        "screen": (
            "Nella schermata {code} le cifre restano piccole sul telefono.",
            "Ingrandire le cifre della schermata {code}.",
        ),
        "check": (
            "La modifica non cambia come uso la schermata {screen}, ma il requisito {code} "
            "va provato.",
            "Provare il requisito {code} sulla schermata {screen}.",
        ),
    },
    "en": {
        "CONCERN": "For “{goal}” the change “{line}” leaves me some doubts: here is where.",
        "FINE": "For “{goal}” the change “{line}” works for me.",
        "requirement": (
            "On the page I still cannot find what requirement {code} asks for.",
            "Show on the page what requirement {code} asks for.",
        ),
        "screen": (
            "On screen {code} the digits stay small on the phone.",
            "Make the digits of screen {code} larger.",
        ),
        "check": (
            "The change does not alter how I use screen {screen}, but requirement {code} "
            "needs a test.",
            "Try requirement {code} on screen {screen}.",
        ),
    },
}
CHANGE_VERDICTS = {
    "it": {
        "ALIGNED": "La modifica «{line}» segue i requisiti e il design approvati.",
        "CODE_DRIFT": "La modifica «{line}» si allontana dai requisiti o dal design approvati: "
        "va corretto il codice.",
        "DESIGN_OUTDATED": "La modifica «{line}» è un'evoluzione legittima: il design va "
        "aggiornato con una nuova versione.",
        "REQUIREMENTS_OUTDATED": "La modifica «{line}» è un'evoluzione legittima: i requisiti "
        "vanno aggiornati con una nuova versione.",
        "design_request": "Aggiornare il design perché descriva quello che la modifica «{line}» "
        "ha introdotto nella schermata {screen}.",
        "requirements_request": "Aggiornare i requisiti perché descrivano quello che la modifica "
        "«{line}» ha introdotto, a partire dal requisito {code}.",
        "tasks": (
            "Riportare il codice in linea con la schermata {screen} del design approvato.",
            "Coprire il requisito {code} con un test automatico.",
        ),
    },
    "en": {
        "ALIGNED": "The change “{line}” follows the approved requirements and design.",
        "CODE_DRIFT": "The change “{line}” departs from the approved requirements or design: "
        "the code should change.",
        "DESIGN_OUTDATED": "The change “{line}” is a legitimate evolution: the design should get "
        "a new version.",
        "REQUIREMENTS_OUTDATED": "The change “{line}” is a legitimate evolution: the "
        "requirements should get a new version.",
        "design_request": "Update the design so that it describes what the change “{line}” "
        "introduced on screen {screen}.",
        "requirements_request": "Update the requirements so that they describe what the change "
        "“{line}” introduced, starting from requirement {code}.",
        "tasks": (
            "Bring the code back in line with screen {screen} of the approved design.",
            "Cover requirement {code} with an automated test.",
        ),
    },
}
NOT_COVERED_REASON = {"it": "Richiede una verifica manuale", "en": "Needs a manual check"}
TEST_CRITIQUES = {
    "it": {
        "CONCERN": "Per «{goal}» i test sull'applicazione ({numbers}) mi lasciano qualche dubbio: "
        "ecco dove.",
        "FINE": "Per «{goal}» i test sull'applicazione ({numbers}) mi vanno bene.",
        "numbers": "{passed} criteri superati, {failed} falliti, {blocked} bloccati, "
        "{not_covered} non coperti, {not_run} non eseguiti",
        "concern": (
            "Il criterio {code} non mi assicura che l'applicazione faccia quello che mi serve.",
            "Correggere l'applicazione dove si ferma il percorso del criterio {code}.",
        ),
        "check": (
            "Il criterio {code} va provato anche su un telefono.",
            "Ripetere il percorso del criterio {code} su uno schermo piccolo.",
        ),
    },
    "en": {
        "CONCERN": "For “{goal}” the tests on the application ({numbers}) leave me some doubts: "
        "here is where.",
        "FINE": "For “{goal}” the tests on the application ({numbers}) work for me.",
        "numbers": "{passed} criteria passed, {failed} failed, {blocked} blocked, "
        "{not_covered} not covered, {not_run} not run",
        "concern": (
            "Criterion {code} does not assure me that the application does what I need.",
            "Fix the application where the path of criterion {code} stops.",
        ),
        "check": (
            "Criterion {code} should be tried on a phone too.",
            "Repeat the path of criterion {code} on a small screen.",
        ),
    },
}


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    method: str
    path: str
    query: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    template: str
    action: str
    authenticated: bool = True


ROUTES: tuple[Route, ...] = (
    Route("GET", "/health", "health", authenticated=False),
    Route("POST", "/auth/login", "login", authenticated=False),
    Route("POST", "/auth/register", "register", authenticated=False),
    Route("POST", "/auth/refresh", "refresh", authenticated=False),
    Route("POST", "/auth/logout", "logout", authenticated=False),
    Route("GET", "/auth/me", "me"),
    Route("GET", "/model-runtime/budget", "budget"),
    Route("GET", "/model-runtime/readiness", "readiness"),
    Route("GET", "/agent-catalog", "agent_catalog"),
    Route("POST", "/project-imports", "import_project"),
    Route("GET", "/projects", "list_projects"),
    Route("POST", "/projects", "create_project"),
    Route("GET", "/projects/{project_id}", "get_project"),
    Route("PATCH", "/projects/{project_id}", "rename_project"),
    Route("GET", "/projects/{project_id}/sections", "sections"),
    Route("GET", "/projects/{project_id}/workflow-inputs", "workflow_inputs"),
    Route("GET", "/projects/{project_id}/provided-prototypes/state", "provided_state"),
    Route("GET", "/projects/{project_id}/provided-prototypes/current", "provided_current"),
    Route("GET", "/projects/{project_id}/provided-prototypes/gate/current", "provided_gate"),
    Route(
        "GET",
        "/projects/{project_id}/provided-prototypes/{prototype_id}/document",
        "provided_document",
    ),
    Route("POST", "/projects/{project_id}/sections/alignment", "align_sections"),
    Route("GET", "/projects/{project_id}/brief-versions", "brief_history"),
    Route("POST", "/projects/{project_id}/brief-versions", "create_brief"),
    Route("GET", "/projects/{project_id}/brief-versions/current", "current_brief"),
    Route("GET", "/projects/{project_id}/brief-versions/{version_number}", "brief_version"),
    Route("GET", "/projects/{project_id}/brief-dialogue", "dialogue_current"),
    Route("POST", "/projects/{project_id}/brief-dialogue", "dialogue_start"),
    Route("POST", "/projects/{project_id}/brief-dialogue/answers", "dialogue_answer"),
    Route("POST", "/projects/{project_id}/brief-dialogue/questions", "dialogue_question"),
    Route("POST", "/projects/{project_id}/brief-dialogue/synthesis", "dialogue_synthesis"),
    Route("POST", "/projects/{project_id}/brief-dialogue/close", "dialogue_close"),
    Route("GET", "/projects/{project_id}/brief-assumptions", "assumptions"),
    Route("POST", "/projects/{project_id}/brief-assumptions/accept-all", "accept_all"),
    Route(
        "POST",
        "/projects/{project_id}/brief-assumptions/{assumption_id}/accept",
        "accept_assumption",
    ),
    Route(
        "POST",
        "/projects/{project_id}/brief-assumptions/{assumption_id}/reject",
        "reject_assumption",
    ),
    Route("POST", "/projects/{project_id}/gates/project-brief/submit", "brief_gate_submit"),
    Route("GET", "/projects/{project_id}/gates/project-brief/current", "brief_gate_current"),
    Route("POST", "/projects/{project_id}/gates/project-brief/decisions", "brief_gate_decision"),
    Route(
        "GET", "/projects/{project_id}/gates/project-brief/{gate_id}/events", "brief_gate_events"
    ),
    Route("POST", "/projects/{project_id}/team-proposals", "team_proposal"),
    Route("GET", "/projects/{project_id}/team-proposals", "team_history"),
    Route("GET", "/projects/{project_id}/team-proposals/current", "team_current"),
    Route("PATCH", "/projects/{project_id}/team-proposals/current", "team_edit"),
    Route("GET", "/projects/{project_id}/readiness", "team_readiness"),
    Route("GET", "/projects/{project_id}/team/context-alignment", "team_alignment"),
    Route("POST", "/projects/{project_id}/team/context-alignment", "realign_team"),
    Route("POST", "/projects/{project_id}/gates/agent-team/submit", "team_gate_submit"),
    Route("GET", "/projects/{project_id}/gates/agent-team/current", "team_gate_current"),
    Route("POST", "/projects/{project_id}/gates/agent-team/decisions", "team_gate_decision"),
    Route("GET", "/projects/{project_id}/gates/agent-team/{gate_id}/events", "team_gate_events"),
    Route("GET", "/projects/{project_id}/user-modeling/personas", "personas"),
    Route("GET", "/projects/{project_id}/user-modeling/archetypes", "archetypes"),
    Route("POST", "/projects/{project_id}/user-modeling/archetypes", "archetype_create"),
    Route(
        "PATCH", "/projects/{project_id}/user-modeling/archetypes/{persona_id}", "archetype_edit"
    ),
    Route(
        "DELETE",
        "/projects/{project_id}/user-modeling/archetypes/{persona_id}",
        "archetype_archive",
    ),
    Route("POST", "/projects/{project_id}/user-modeling/personas/proposals", "persona_proposals"),
    Route(
        "POST",
        "/projects/{project_id}/user-modeling/personas/{persona_id}/decision",
        "persona_decision",
    ),
    Route("POST", "/projects/{project_id}/user-modeling/snapshots/generate", "twins_generate"),
    Route("GET", "/projects/{project_id}/user-modeling/snapshots/current", "snapshot_current"),
    Route("GET", "/projects/{project_id}/user-modeling/snapshots", "snapshot_history"),
    Route("GET", "/projects/{project_id}/user-modeling/readiness", "modeling_readiness"),
    Route("POST", "/projects/{project_id}/user-modeling/gate/submit", "twins_gate_submit"),
    Route("POST", "/projects/{project_id}/user-modeling/gate/decision", "twins_gate_decision"),
    Route("GET", "/projects/{project_id}/user-modeling/gate", "twins_gate_current"),
    Route("GET", "/projects/{project_id}/user-modeling/gate/events", "twins_gate_events"),
    Route("GET", "/projects/{project_id}/user-modeling/context-alignment", "twins_alignment"),
    Route("POST", "/projects/{project_id}/user-modeling/context-alignment", "realign_twins"),
    Route("GET", "/projects/{project_id}/user-twins/{twin_id}/conversation", "conversation"),
    Route(
        "POST",
        "/projects/{project_id}/user-twins/{twin_id}/conversation/turns",
        "conversation_turn",
    ),
    Route("POST", "/projects/{project_id}/requirements/proposals", "requirements_proposal"),
    Route("GET", "/projects/{project_id}/requirements/current", "requirements_current"),
    Route("GET", "/projects/{project_id}/requirements", "requirements_history"),
    Route("GET", "/projects/{project_id}/requirements/readiness", "requirements_readiness"),
    Route("POST", "/projects/{project_id}/requirements/change-requests", "requirements_change"),
    Route("GET", "/projects/{project_id}/requirements/revisions", "requirements_revisions"),
    Route(
        "GET", "/projects/{project_id}/requirements/revisions/{diff_id}", "requirements_revision"
    ),
    Route(
        "POST",
        "/projects/{project_id}/requirements/revisions/{diff_id}/decision",
        "requirements_revision_decision",
    ),
    Route("POST", "/projects/{project_id}/requirements/gate/submit", "requirements_gate_submit"),
    Route(
        "POST", "/projects/{project_id}/requirements/gate/decision", "requirements_gate_decision"
    ),
    Route("GET", "/projects/{project_id}/requirements/gate", "requirements_gate_current"),
    Route("GET", "/projects/{project_id}/requirements/gate/events", "requirements_gate_events"),
    Route("GET", "/projects/{project_id}/requirements/twin-alignment", "requirements_alignment"),
    Route("POST", "/projects/{project_id}/requirements/twin-alignment", "realign_requirements"),
    Route("POST", "/projects/{project_id}/design/proposals", "design_proposal"),
    Route("POST", "/projects/{project_id}/design/regenerations", "design_regeneration"),
    Route("GET", "/projects/{project_id}/design/current", "design_current"),
    Route("GET", "/projects/{project_id}/design", "design_history"),
    Route("GET", "/projects/{project_id}/design/readiness", "design_readiness"),
    Route("POST", "/projects/{project_id}/design/revisions", "design_revision"),
    Route("GET", "/projects/{project_id}/design/revisions", "design_revisions"),
    Route("GET", "/projects/{project_id}/design/revisions/{diff_id}", "design_revision_view"),
    Route(
        "POST",
        "/projects/{project_id}/design/revisions/{diff_id}/decision",
        "design_revision_decision",
    ),
    Route("POST", "/projects/{project_id}/design/gate/submit", "design_gate_submit"),
    Route("POST", "/projects/{project_id}/design/gate/decision", "design_gate_decision"),
    Route("GET", "/projects/{project_id}/design/gate", "design_gate_current"),
    Route("GET", "/projects/{project_id}/design/gate/events", "design_gate_events"),
    Route("GET", "/projects/{project_id}/design/requirements-alignment", "design_alignment"),
    Route("POST", "/projects/{project_id}/design/requirements-alignment", "realign_design"),
    Route("POST", "/projects/{project_id}/design/mockups", "mockup_generate"),
    Route("GET", "/projects/{project_id}/design/mockups", "mockup_latest"),
    Route("GET", "/projects/{project_id}/design/mockups/capabilities", "mockup_capabilities"),
    Route("POST", "/projects/{project_id}/design/mockups/jobs", "mockup_job"),
    Route("GET", "/projects/{project_id}/design/mockups/jobs/{job_id}", "mockup_job_view"),
    Route("GET", "/projects/{project_id}/design/mockups/document", "mockup_document"),
    Route("POST", "/projects/{project_id}/design/iterations/jobs", "iteration_job"),
    Route("GET", "/projects/{project_id}/design/iterations/jobs/{job_id}", "iteration_job_view"),
    Route("GET", "/projects/{project_id}/design/iterations", "iterations"),
    Route("POST", "/projects/{project_id}/design/evaluations", "evaluation"),
    Route("GET", "/projects/{project_id}/design/evaluations", "evaluations"),
    Route("GET", "/projects/{project_id}/design/evaluations/comparison", "comparison"),
    Route("GET", "/projects/{project_id}/design/evaluations/{run_id}/pins", "review_pins"),
    Route("GET", "/projects/{project_id}/design/evaluations/{run_id}/document", "review_document"),
    Route("GET", "/projects/{project_id}/generation-jobs", "jobs"),
    Route("GET", "/projects/{project_id}/generation-jobs/{job_id}", "job"),
    Route("POST", "/projects/{project_id}/knowledge-packages", "publish"),
    Route("GET", "/projects/{project_id}/knowledge-packages", "package_history"),
    Route(
        "GET",
        "/projects/{project_id}/knowledge-packages/{version_number}/archive",
        "package_archive",
    ),
    Route("GET", "/projects/{project_id}/import", "import_origin"),
    Route("GET", "/projects/{project_id}/model-usage", "usage"),
    Route("GET", "/projects/{project_id}/alignment", "alignment"),
    Route("POST", "/projects/{project_id}/code-changes", "record_change"),
    Route("GET", "/projects/{project_id}/code-changes", "changes"),
    Route("GET", "/projects/{project_id}/code-changes/{commit}", "change"),
    Route("POST", "/projects/{project_id}/code-changes/{commit}/reviews", "review_change"),
    Route("GET", "/projects/{project_id}/code-changes/{commit}/reviews", "change_reviews"),
    Route("POST", "/projects/{project_id}/code-changes/{commit}/decision", "decide_change"),
    Route("GET", "/projects/{project_id}/acceptance-tests", "acceptance_tests"),
    Route("POST", "/projects/{project_id}/test-plans", "plan_tests"),
    Route("GET", "/projects/{project_id}/test-plans", "test_plans"),
    Route("GET", "/projects/{project_id}/test-plans/{plan_id}", "test_plan"),
    Route("POST", "/projects/{project_id}/test-runs", "record_test_run"),
    Route("GET", "/projects/{project_id}/test-runs", "test_runs"),
    Route("GET", "/projects/{project_id}/test-runs/{run_id}", "test_run"),
    Route("POST", "/projects/{project_id}/test-runs/{run_id}/reviews", "review_test_run"),
    Route("GET", "/projects/{project_id}/test-runs/{run_id}/reviews", "test_run_reviews"),
    Route("GET", "/projects/{project_id}/code-tasks", "code_tasks"),
    Route("POST", "/projects/{project_id}/code-tasks", "create_tasks"),
    Route("POST", "/projects/{project_id}/code-tasks/{code}/status", "task_status"),
    Route("GET", "/projects/{project_id}/twin-learning", "twin_learning"),
    Route("GET", "/projects/{project_id}/artifacts/why", "why"),
    Route("GET", "/projects/{project_id}/validation", "validation"),
    Route("GET", "/projects/{project_id}/validation/walkthrough", "validation_walkthrough"),
    Route("GET", "/projects/{project_id}/artifacts/why/document", "why_document"),
    Route("GET", "/projects/{project_id}/evidence", "evidence_list"),
    Route("POST", "/projects/{project_id}/evidence", "evidence_add"),
    Route("GET", "/projects/{project_id}/evidence/{evidence_id}", "evidence_show"),
    Route("POST", "/projects/{project_id}/evidence/{evidence_id}/versions", "evidence_revise"),
    Route("POST", "/projects/{project_id}/evidence/{evidence_id}/retire", "evidence_retire"),
    Route("DELETE", "/projects/{project_id}/evidence/{evidence_id}/text", "evidence_delete"),
    Route("PUT", "/projects/{project_id}/evidence/{evidence_id}/text", "evidence_associate"),
    Route("POST", "/projects/{project_id}/user-twins/{twin_id}/updates", "propose_update"),
    Route("GET", "/projects/{project_id}/twin-updates/{update_id}", "twin_update"),
    Route("POST", "/projects/{project_id}/twin-updates/{update_id}/decision", "decide_update"),
    Route("POST", "/projects/{project_id}/user-twins/{twin_id}/observations", "learn"),
    Route(
        "POST",
        "/projects/{project_id}/user-twins/{twin_id}/observations/{code}/retire",
        "retire_observation",
    ),
)


def route_table() -> tuple[tuple[str, str], ...]:
    return tuple((route.method, PREFIX + route.template) for route in ROUTES)


class _Refusal(Exception):
    def __init__(
        self, status: int, detail: object, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(status)
        self.status = status
        self.detail = detail
        self.headers = dict(headers or {})


class _Invalid(Exception):
    def __init__(self, errors: list[dict[str, object]]) -> None:
        super().__init__("invalid_request")
        self.errors = errors


class _JobFailure(Exception):
    def __init__(
        self,
        code: str,
        *,
        rejected: bool = False,
        reasons: Sequence[Mapping[str, object]] = (),
    ) -> None:
        super().__init__(code)
        self.code = code
        self.rejected = rejected
        self.reasons = [dict(reason) for reason in reasons]


class _Sentinel:
    pass


NO_BODY = _Sentinel()
NOT_JSON = _Sentinel()


@dataclass(slots=True)
class _Answer:
    status: int
    body: object = None
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None
    content_type: str = "application/json"

    def content(self) -> bytes:
        if self.raw is not None:
            return self.raw
        if self.status == 204:
            return b""
        return json.dumps(
            self.body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")


@dataclass(slots=True)
class _Account:
    id: str
    email: str
    password: str = field(repr=False)
    created_at: datetime


@dataclass(slots=True)
class _AccessToken:
    account: str
    expires_at: datetime


@dataclass(slots=True)
class _RefreshSession:
    token: str = field(repr=False)
    account: str
    family: str
    expires_at: datetime
    rotated: bool = False
    revoked: bool = False


@dataclass(slots=True)
class _FailureRule:
    method: str
    pattern: re.Pattern[str]
    status: int
    body: object
    headers: dict[str, str]
    remaining: int


@dataclass(slots=True)
class _JobRule:
    code: str
    status: int
    rejected: bool


@dataclass(slots=True)
class _Job:
    id: str
    owner: str
    project_id: str
    kind: str
    operation: str
    key: str
    alternative_id: str | None
    started_at: datetime
    work: Callable[[_Job], object]
    status: str = "RUNNING"
    stage: str | None = "GENERATING"
    attempt: int = 1
    finished_at: datetime | None = None
    result: object = None
    failure: object = None
    response: object = None
    polls: int = 0
    lost: bool = False

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (self.owner, self.project_id, self.kind, self.key)

    def payload(self) -> dict[str, object]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "operation": self.operation,
            "status": self.status,
            "stage": self.stage,
            "attempt": self.attempt,
            "started_at": _iso(self.started_at),
            "finished_at": None if self.finished_at is None else _iso(self.finished_at),
            "alternative_id": self.alternative_id,
            "result": self.result,
            "failure": self.failure,
            "response": self.response,
        }


@dataclass(slots=True)
class _BriefVersion:
    payload: dict[str, object]
    brief: ProjectBrief

    @property
    def id(self) -> str:
        return str(self.payload["id"])

    @property
    def number(self) -> int:
        return int(self.payload["version_number"])

    @property
    def content_hash(self) -> str:
        return str(self.payload["content_hash"])


@dataclass(slots=True)
class _Call:
    method: str
    path: str
    user: _Account | None
    params: dict[str, str]
    query: dict[str, list[str]]
    headers: dict[str, str]
    raw: bytes
    prefer_async: bool

    @property
    def project_id(self) -> str:
        return self.params["project_id"]

    @property
    def account(self) -> _Account:
        if self.user is None:
            raise _Refusal(401, "invalid_authentication", {"WWW-Authenticate": "Bearer"})
        return self.user

    def json(self) -> object:
        if not self.raw:
            return NO_BODY
        content_type = self.headers.get("content-type")
        if content_type is not None and not _json_media_type(content_type):
            return NOT_JSON
        try:
            return json.loads(self.raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise _Invalid([_error(("body", 0), "json_invalid")]) from error

    def value(self, name: str) -> str | None:
        values = self.query.get(name)
        return values[0] if values else None

    def cookie(self, name: str) -> str:
        header = self.headers.get("cookie")
        if not header:
            return ""
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(header)
        except CookieError:
            return ""
        morsel = jar.get(name)
        return "" if morsel is None else morsel.value


class _Fields:
    def __init__(
        self,
        body: object,
        allowed: Sequence[str],
        *,
        optional: bool = False,
        location: Sequence[object] = ("body",),
    ) -> None:
        self.errors: list[dict[str, object]] = []
        self.absent = False
        self.location = tuple(location)
        if body is NO_BODY or body is None:
            self.absent = True
            if not optional:
                self.errors.append(_error(self.location, "missing"))
            body = {}
        elif body is NOT_JSON or not isinstance(body, dict):
            self.absent = True
            self.errors.append(_error(self.location, "model_attributes_type"))
            body = {}
        self.body: dict[str, object] = body
        self.errors.extend(
            _error((*self.location, name), "extra_forbidden")
            for name in body
            if name not in allowed
        )

    def _get(self, name: str, required: bool) -> tuple[bool, object]:
        if self.absent or name not in self.body:
            if required and not self.absent:
                self.errors.append(_error((*self.location, name), "missing"))
            return False, None
        return True, self.body[name]

    def _fail(self, name: str, kind: str) -> None:
        self.errors.append(_error((*self.location, name), kind))

    def text(
        self,
        name: str,
        *,
        required: bool = True,
        minimum: int = 0,
        maximum: int | None = None,
        nullable: bool = False,
        default: str | None = None,
    ) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return default
        if value is None and nullable:
            return None
        if not isinstance(value, str):
            self._fail(name, "string_type")
            return default
        if len(value) < minimum:
            self._fail(name, "string_too_short")
            return default
        if maximum is not None and len(value) > maximum:
            self._fail(name, "string_too_long")
            return default
        return value

    def choice(
        self,
        name: str,
        options: Sequence[str],
        *,
        required: bool = True,
        nullable: bool = False,
        literal: bool = False,
    ) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return None
        if value is None and nullable:
            return None
        if not isinstance(value, str) or value not in options:
            self._fail(name, "literal_error" if literal else "enum")
            return None
        return value

    def integer(
        self,
        name: str,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
        required: bool = True,
    ) -> int | None:
        present, value = self._get(name, required)
        if not present:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self._fail(name, "int_type")
            return None
        if minimum is not None and value < minimum:
            self._fail(name, "greater_than_equal")
            return None
        if maximum is not None and value > maximum:
            self._fail(name, "less_than_equal")
            return None
        return value

    def whole(self, name: str, *, minimum: int | None = None) -> int | None:
        present, value = self._get(name, True)
        if not present:
            return None
        kind, number = _lax_integer(value)
        if kind is not None:
            self._fail(name, kind)
            return None
        if minimum is not None and number < minimum:
            self._fail(name, "greater_than_equal")
            return None
        return number

    def texts(
        self,
        name: str,
        *,
        required: bool = False,
        nullable: bool = True,
        minimum_items: int = 0,
        maximum_items: int | None = None,
        default: list[str] | None = None,
        item_minimum: int = 0,
        item_maximum: int | None = None,
        item_pattern: re.Pattern[str] | None = None,
    ) -> list[str] | None:
        present, value = self._get(name, required)
        if not present:
            return default
        if value is None and nullable:
            return None
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return default
        if len(value) < minimum_items:
            self._fail(name, "too_short")
            return default
        if maximum_items is not None and len(value) > maximum_items:
            self._fail(name, "too_long")
            return default
        checked = [
            (index, _text_error(item, item_minimum, item_maximum, item_pattern))
            for index, item in enumerate(value)
        ]
        wrong = [(index, kind) for index, kind in checked if kind is not None]
        self.errors.extend(_error((*self.location, name, index), kind) for index, kind in wrong)
        return default if wrong else list(value)

    def identifier(self, name: str, *, required: bool = True, nullable: bool = False) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return None
        if value is None and nullable:
            return None
        if not isinstance(value, str):
            self._fail(name, "uuid_type")
            return None
        try:
            return str(UUID(value))
        except ValueError:
            self._fail(name, "uuid_parsing")
            return None

    def digest(self, name: str) -> str | None:
        value = self.text(name)
        if value is not None and HASH_PATTERN.fullmatch(value) is None:
            self._fail(name, "string_pattern_mismatch")
            return None
        return value

    def value(self, name: str, *, required: bool = True) -> object:
        present, value = self._get(name, required)
        return value if present else None

    def pattern(
        self,
        name: str,
        expression: re.Pattern[str],
        *,
        required: bool = True,
        nullable: bool = False,
        minimum: int = 0,
        maximum: int | None = None,
        default: str | None = None,
    ) -> str | None:
        present, value = self._get(name, required)
        if not present:
            return default
        if value is None and nullable:
            return None
        kind = _text_error(value, minimum, maximum)
        if kind is None and expression.fullmatch(str(value)) is None:
            kind = "string_pattern_mismatch"
        if kind is not None:
            self._fail(name, kind)
            return default
        return str(value)

    def normalized(
        self, name: str, value: object, normalizer: Callable[[object], object]
    ) -> object:
        try:
            return normalizer(value)
        except ValueError:
            self._fail(name, "value_error")
            return None

    def moment(self, name: str) -> datetime | None:
        present, value = self._get(name, True)
        if not present:
            return None
        if not isinstance(value, str):
            self._fail(name, "datetime_type")
            return None
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            self._fail(name, "datetime_from_date_parsing")
            return None
        if moment.tzinfo is None or moment.utcoffset() is None:
            self._fail(name, "timezone_aware")
            return None
        return moment

    def flag(self, name: str, *, default: bool = False) -> bool:
        present, value = self._get(name, False)
        if not present:
            return default
        parsed = _lax_boolean(value)
        if parsed is None:
            self._fail(
                name, "bool_parsing" if isinstance(value, str | int | float) else "bool_type"
            )
            return default
        return parsed

    def changed_files(self, name: str) -> list[dict[str, object]]:
        present, value = self._get(name, False)
        if not present:
            return []
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return []
        if len(value) > MAX_FILES:
            self._fail(name, "too_long")
            return []
        files = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                self.errors.append(_error((*self.location, name, index), "model_attributes_type"))
                continue
            nested = _Fields(
                item, ("path", "kind", "added", "removed"), location=(*self.location, name, index)
            )
            path = nested.text("path", minimum=1, maximum=MAX_PATH_LENGTH)
            if path is not None:
                path = nested.normalized("path", path, _changed_path)
            kind = nested.choice("kind", FILE_KINDS)
            added = nested.integer("added", minimum=0)
            removed = nested.integer("removed", minimum=0)
            self.errors.extend(nested.errors)
            files.append({"path": path, "kind": kind, "added": added, "removed": removed})
        return files

    def number(
        self, name: str, *, minimum: float | None = None, maximum: float | None = None
    ) -> int | float | None:
        present, value = self._get(name, True)
        if not present:
            return None
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                self._fail(name, "float_parsing")
                return None
        if not isinstance(value, int | float):
            self._fail(name, "float_type")
            return None
        if not math.isfinite(value):
            self._fail(name, "finite_number")
            return None
        if minimum is not None and value < minimum:
            self._fail(name, "greater_than_equal")
            return None
        if maximum is not None and value > maximum:
            self._fail(name, "less_than_equal")
            return None
        return value

    def identifiers(self, name: str, *, maximum_items: int | None = None) -> list[str]:
        present, value = self._get(name, False)
        if not present:
            return []
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return []
        if maximum_items is not None and len(value) > maximum_items:
            self._fail(name, "too_long")
            return []
        found = []
        for index, item in enumerate(value):
            location = (*self.location, name, index)
            if not isinstance(item, str):
                self.errors.append(_error(location, "uuid_type"))
                continue
            try:
                found.append(str(UUID(item)))
            except ValueError:
                self.errors.append(_error(location, "uuid_parsing"))
        return found

    def child(
        self,
        name: str,
        allowed: Sequence[str],
        *,
        required: bool = True,
        nullable: bool = False,
    ) -> _Fields | None:
        present, value = self._get(name, required)
        if not present or (value is None and nullable):
            return None
        if not isinstance(value, dict):
            self._fail(name, "model_attributes_type")
            return None
        return _Fields(value, allowed, location=(*self.location, name))

    def children(
        self,
        name: str,
        allowed: Sequence[str],
        *,
        required: bool = True,
        nullable: bool = False,
        minimum_items: int = 0,
        maximum_items: int | None = None,
    ) -> list[_Fields] | None:
        present, value = self._get(name, required)
        if not present or (value is None and nullable):
            return None
        if not isinstance(value, list):
            self._fail(name, "list_type")
            return []
        if len(value) < minimum_items:
            self._fail(name, "too_short")
            return []
        if maximum_items is not None and len(value) > maximum_items:
            self._fail(name, "too_long")
            return []
        found = []
        for index, item in enumerate(value):
            location = (*self.location, name, index)
            if not isinstance(item, dict):
                self.errors.append(_error(location, "model_attributes_type"))
                continue
            found.append(_Fields(item, allowed, location=location))
        return found

    def adopt(self, child: _Fields) -> None:
        self.errors.extend(child.errors)

    def check(self) -> None:
        if self.errors:
            raise _Invalid(self.errors)


class FakeProject:
    def __init__(
        self,
        studio: FakeStudio,
        account: _Account,
        project_id: str,
        name: str,
        mode: str,
        created_at: datetime,
    ) -> None:
        self._studio = studio
        self.account = account
        self.id = project_id
        self.name = name
        self.mode = mode
        self.created_at = created_at
        self.updated_at = created_at
        self.briefs: list[_BriefVersion] = []
        self.dialogues: list[BriefDialogue] = []
        self.assumptions: list[BriefAssumption] = []
        self.gates: dict[str, HumanGate] = {}
        self.gate_events: dict[str, list[HumanGateEvent]] = {}
        self.teams: list[dict[str, object]] = []
        self.personas: dict[str, list[dict[str, object]]] = {}
        self.snapshots: list[dict[str, object]] = []
        self.twins: dict[str, list[dict[str, object]]] = {}
        self.conversations: dict[str, TwinConversation] = {}
        self.requirements: list[dict[str, object]] = []
        self.requirement_diffs: list[dict[str, object]] = []
        self.designs: list[dict[str, object]] = []
        self.design_diffs: list[dict[str, object]] = []
        self.mockups: dict[str, dict[str, object]] = {}
        self.iterations: list[dict[str, object]] = []
        self.runs: list[dict[str, object]] = []
        self.finding_decisions: list[dict[str, object]] = []
        self.packages: list[dict[str, object]] = []
        self.folders: list[dict[str, ArtifactVersion]] = []
        self.gestures: list[dict[str, object]] = []
        self.archives: dict[int, bytes] = {}
        self.fingerprint: tuple[str, ...] | None = None
        self.usage: list[dict[str, object]] = []
        self.origin: dict[str, object] | None = None
        self.variant = 0
        self.code_changes: list[dict[str, object]] = []
        self.change_runs: list[dict[str, object]] = []
        self.code_tasks: list[dict[str, object]] = []
        self.decision_count = 0
        self.acceptance_plans: list[dict[str, object]] = []
        self.acceptance_plan_requests: list[dict[str, object]] = []
        self.acceptance_runs: list[dict[str, object]] = []
        self.acceptance_reviews: list[dict[str, object]] = []
        self.critique_contexts: list[dict[str, object]] = []
        self.learned: list[dict[str, object]] = []
        self.development: dict[str, int] = {}
        self.updates: list[dict[str, object]] = []
        self.evidence_versions: list[dict[str, object]] = []
        self.evidence_texts: dict[tuple[str, int], str] = {}
        self.evidence_changes: list[dict[str, object]] = []
        self.validation_hypotheses: list[dict[str, object]] = []
        self.validation_outcomes: list[dict[str, object]] = []
        self.workflow_decisions: list[dict[str, object]] = []
        self.provided_prototypes: list[dict[str, object]] = []
        self.provided_gate: dict[str, object] | None = None
        self.provided_context_current = True

    @property
    def owner(self) -> str:
        return self.account.email

    @property
    def brief(self) -> _BriefVersion | None:
        return self.briefs[-1] if self.briefs else None

    @property
    def team(self) -> dict[str, object] | None:
        return self.teams[-1] if self.teams else None

    @property
    def snapshot(self) -> dict[str, object] | None:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def specification(self) -> dict[str, object] | None:
        return self.requirements[-1] if self.requirements else None

    @property
    def design(self) -> dict[str, object] | None:
        return self.designs[-1] if self.designs else None

    def artifact(self, stage: str) -> dict[str, object] | None:
        if stage == "brief":
            return None if self.brief is None else self.brief.payload
        return {
            "team": self.team,
            "twins": self.snapshot,
            "requirements": self.specification,
            "design": self.design,
        }[_stage(stage)]

    @property
    def stage(self) -> str:
        with self._studio._lock:
            return self._studio._progress(self)[0]

    @property
    def next_action(self) -> str:
        with self._studio._lock:
            return self._studio._progress(self)[1]

    @property
    def spent_microusd(self) -> int:
        with self._studio._lock:
            return sum(int(item["cost_microusd"] or 0) for item in self.usage)

    def approved(self, stage: str) -> bool:
        with self._studio._lock:
            return self._studio._approvals(self)[_stage(stage)]

    def current(self, stage: str) -> dict[str, object] | None:
        with self._studio._lock:
            artifact = self.artifact(stage)
            if artifact is not None and _stage(stage) == "twins":
                return self._studio._readable_snapshot(artifact)
            return None if artifact is None else _copy(artifact)

    def gate(self, stage: str) -> dict[str, object] | None:
        with self._studio._lock:
            gate = self.gates.get(_stage(stage))
            return None if gate is None else _gate_payload(gate)

    def jobs(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return [
                job.payload()
                for job in self._studio._jobs.values()
                if job.project_id == self.id and not job.lost
            ]

    def knowledge_versions(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.packages)

    def mark_knowledge_changed(self) -> None:
        with self._studio._lock:
            self.fingerprint = None

    def changes(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return [self._studio._change_payload(self, record) for record in self.code_changes]

    def change_reviews(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.change_runs)

    def tasks(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.code_tasks)

    def aligned(self) -> dict[str, object] | None:
        with self._studio._lock:
            return self._studio._aligned(self)

    def test_plans(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.acceptance_plans)

    def plan_requests(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.acceptance_plan_requests)

    def test_runs(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return [self._studio._test_run_payload(self, record) for record in self.acceptance_runs]

    def test_reviews(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.acceptance_reviews)

    def rewrite_criterion(self, code: str, statement: str) -> None:
        with self._studio._lock:
            specification = self.specification
            if specification is None:
                raise ValueError("the project has no requirements yet")
            for item in specification["specification"]["acceptance_criteria"]:
                if item["code"] == code:
                    item["statement"] = statement
                    return
            raise ValueError(f"the requirements have no acceptance criterion {code}")

    def twin_learning(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return self._studio._learning_entries(self)

    def twin_updates(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.updates)

    def earlier_findings(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.critique_contexts)

    def seed_change(
        self, message: str | None = None, *, commit: str | None = None, reviewed: bool = True
    ) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_change(self, message, commit, reviewed)

    def seed_test_run(self, *, failed: bool = True, reviewed: bool = True) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_test_run(self, failed=failed, reviewed=reviewed)

    def seed_version(self, stage: str) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_version(self, stage)

    def add_tasks(self, items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        with self._studio._lock:
            return self._studio._seeded(lambda: self._studio._add_tasks(self, items))

    def seed_tasks(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return self._studio._seeded(lambda: self._studio._seed_tasks(self))

    def set_task_status(self, code: str, status: str, note: str | None = None) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seeded(
                lambda: self._studio._changed_task(self, code, {"status": status, "note": note})
            )

    def seed_learning(
        self,
        twin: int | str = 0,
        statements: Sequence[str] | None = None,
        *,
        source: str = "TWIN_CRITIQUE",
    ) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_learning(self, twin, statements, source)

    def seed_update(
        self,
        twin: int | str = 0,
        observations: Sequence[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_update(self, twin, observations)

    def sections(self) -> dict[str, object]:
        with self._studio._lock:
            return _copy(self._studio._sections(self))

    def alignments(self) -> list[dict[str, object]]:
        with self._studio._lock:
            return _copy(self.gestures)

    def seed_perspective_change(self, agent_id: str) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_perspective_change(self, agent_id)

    def seed_requirements_change(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_requirements_change(self)

    def seed_brief_change(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_brief_change(self)

    def seed_requirement_removed(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_requirement_removed(self)

    def seed_design_revision(self) -> dict[str, object]:
        with self._studio._lock:
            return self._studio._seed_design_revision(self)


class FakeStudio:
    def __init__(
        self,
        *,
        language: str = "it",
        twins: int = 2,
        hosted: bool = True,
        budget_usd: float | None = 60.0,
        spent_usd: float = 0.0,
        billing: str | None = None,
        job_polls: int = 2,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if language not in LANGUAGES:
            raise ValueError("language must be it or en")
        if isinstance(twins, bool) or not isinstance(twins, int) or not 1 <= twins <= MAX_TWINS:
            raise ValueError(f"twins must be between 1 and {MAX_TWINS}")
        if isinstance(job_polls, bool) or not isinstance(job_polls, int) or job_polls < 0:
            raise ValueError("job_polls must be a non-negative integer")
        if budget_usd is not None and budget_usd <= 0:
            raise ValueError("budget_usd must be positive or None")
        if spent_usd < 0:
            raise ValueError("spent_usd must not be negative")
        if billing is not None and billing not in BILLINGS:
            raise ValueError("billing must be SUBSCRIPTION, API, MIXED or None")
        self.language = language
        self.twins = twins
        self.hosted = hosted
        self.billing = billing
        self.job_polls = job_polls
        self.requests: list[RecordedRequest] = []
        self.errors: list[str] = []
        self._budget = None if budget_usd is None else round(budget_usd * 1_000_000)
        self._spent = round(spent_usd * 1_000_000)
        self._clock = now
        self._moment = EPOCH if now is None else datetime.min.replace(tzinfo=UTC)
        self._counter = 0
        self._tokens = 0
        self._lock = threading.RLock()
        self._accounts: dict[str, _Account] = {}
        self._accounts_by_id: dict[str, _Account] = {}
        self._access: dict[str, _AccessToken] = {}
        self._sessions: dict[str, _RefreshSession] = {}
        self._projects: dict[str, FakeProject] = {}
        self._jobs: dict[str, _Job] = {}
        self._failures: list[_FailureRule] = []
        self._job_rules: dict[str, list[_JobRule]] = {}
        self._lost: dict[str, int] = {}
        self._extra_fields: list[str] = []
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._routes = tuple((route, _compile(route.template)) for route in ROUTES)

    @property
    def address(self) -> str:
        if self._server is None:
            raise RuntimeError("the fake studio is not running")
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def spent_microusd(self) -> int:
        with self._lock:
            return self._spent

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def __enter__(self) -> FakeStudio:
        if self._server is not None:
            raise RuntimeError("the fake studio is already running")
        server = _Server(self)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.02},
            name="fake-studio",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None or thread is None:
            return
        try:
            server.shutdown()
        finally:
            server.server_close()
            thread.join()

    def now(self) -> datetime:
        with self._lock:
            return self._now()

    def add_account(self, email: str, password: str) -> None:
        key = _registered_email(email)
        if not password:
            raise ValueError("password must not be empty")
        with self._lock:
            if key in self._accounts:
                raise ValueError("the account already exists")
            account = _Account(self._new_id(), key, password, self._now())
            self._accounts[key] = account
            self._accounts_by_id[account.id] = account

    def ask_after_essentials(self, *fields: str) -> None:
        if not fields:
            raise ValueError("name at least one field of the brief")
        for name in fields:
            if name in ESSENTIAL:
                raise ValueError(f"{name} is an essential field of the brief")
            if name not in EXTRA_QUESTIONS[self.language]:
                raise ValueError(f"{name} is not a field that the fake can ask")
        with self._lock:
            self._extra_fields.extend(name for name in fields if name not in self._extra_fields)

    def fail_next(
        self,
        method: str,
        path_pattern: str,
        *,
        status: int,
        body: object,
        times: int = 1,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not 100 <= status <= 599:
            raise ValueError("status must be an HTTP status")
        if times < 1:
            raise ValueError("times must be positive")
        pattern = re.compile(TEMPLATE_PARAMETER.sub("[^/]+", path_pattern))
        with self._lock:
            self._failures.append(
                _FailureRule(method.upper(), pattern, status, body, dict(headers or {}), times)
            )

    def fail_job(
        self, operation: str, *, code: str, status: int = 503, rejected: bool = False
    ) -> None:
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation {operation}")
        with self._lock:
            self._job_rules.setdefault(operation, []).append(_JobRule(code, status, rejected))

    def lose_job(self, operation: str) -> None:
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation {operation}")
        with self._lock:
            self._lost[operation] = self._lost.get(operation, 0) + 1

    def expire_access_tokens(self) -> None:
        with self._lock:
            self._access.clear()

    def project(self, project_id: str) -> FakeProject:
        with self._lock:
            return self._projects[str(UUID(project_id))]

    def seed_project(
        self,
        *,
        owner: str,
        name: str,
        through: str,
        team_without: Sequence[str] = (),
        requirements_schema_version: int = 2,
    ) -> FakeProject:
        if type(requirements_schema_version) is not int or requirements_schema_version not in (
            1,
            2,
        ):
            raise ValueError("requirements_schema_version must be 1 or 2")
        if isinstance(team_without, str):
            raise ValueError("team_without must be a sequence of agent identifiers")
        dropped = tuple(dict.fromkeys(team_without))
        unknown = [agent for agent in dropped if agent not in AGENT_ORDER]
        if unknown:
            raise ValueError(f"unknown agents: {', '.join(unknown)}")
        fixed = [agent for agent in dropped if agent in ALWAYS_PRESENT]
        if fixed:
            raise ValueError(f"agents always present in every team: {', '.join(fixed)}")
        with self._lock:
            account = self._accounts.get(_email_key(owner) or "")
            if account is None:
                raise ValueError("the owner has no account")
            if through not in STAGES:
                raise ValueError(f"through must be one of {', '.join(STAGES)}")
            if dropped and through == "brief":
                raise ValueError("team_without needs a seed through the team or a later step")
            if DESIGNER in dropped and through == "design":
                raise ValueError("a team without the UX/UI designer never reaches the design")
            normalized = " ".join(name.split())
            if not 1 <= len(normalized) <= MAX_PROJECT_NAME:
                raise ValueError("the project name is not valid")
            project = self._new_project(account, normalized, PROJECT_MODES[0])
            self._seed(
                project,
                through,
                approve=True,
                dropped=dropped,
                requirements_schema_version=requirements_schema_version,
            )
            return project

    def sections(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).sections()

    def alignments(self, project_id: str) -> list[dict[str, object]]:
        return self.project(project_id).alignments()

    def seed_perspective_change(self, project_id: str, agent_id: str) -> dict[str, object]:
        return self.project(project_id).seed_perspective_change(agent_id)

    def seed_requirements_change(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_requirements_change()

    def seed_brief_change(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_brief_change()

    def seed_requirement_removed(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_requirement_removed()

    def seed_design_revision(self, project_id: str) -> dict[str, object]:
        return self.project(project_id).seed_design_revision()

    def _now(self) -> datetime:
        if self._clock is None:
            moment = self._moment
            self._moment = moment + timedelta(seconds=1)
            return moment
        moment = self._clock()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("the clock of the fake studio must be timezone-aware")
        moment = max(moment.astimezone(UTC), self._moment)
        self._moment = moment
        return moment

    def _new_id(self) -> str:
        self._counter += 1
        digest = hashlib.sha256(f"orchestwin-fake-studio:{self._counter}".encode()).digest()
        return str(UUID(bytes=digest[:16], version=4))

    def _handle(self, method: str, target: str, headers: dict[str, str], raw: bytes) -> _Answer:
        with self._lock:
            parts = urlsplit(target)
            self.requests.append(
                RecordedRequest(
                    method, parts.path, parts.query, MappingProxyType(dict(headers)), raw
                )
            )
            try:
                return self._dispatch(method, parts.path, parts.query, headers, raw)
            except Exception:
                self.errors.append(traceback.format_exc())
                return _Answer(
                    500,
                    raw=b"Internal Server Error",
                    content_type="text/plain; charset=utf-8",
                )

    def _record_error(self, text: str) -> None:
        with self._lock:
            self.errors.append(text)

    def _dispatch(
        self, method: str, path: str, query: str, headers: dict[str, str], raw: bytes
    ) -> _Answer:
        relative = path[len(PREFIX) :] if path.startswith(PREFIX + "/") else None
        failure = self._failure(method, path, relative)
        if failure is not None:
            return failure
        if relative is None:
            return _Answer(404, {"detail": "Not Found"})
        matched: tuple[Route, dict[str, str]] | None = None
        allowed: list[str] = []
        for route, pattern in self._routes:
            found = pattern.fullmatch(relative)
            if found is None:
                continue
            if route.method == method:
                matched = (route, found.groupdict())
                break
            allowed.append(route.method)
        if matched is None:
            if allowed:
                return _Answer(
                    405, {"detail": "Method Not Allowed"}, headers={"Allow": ", ".join(allowed)}
                )
            return _Answer(404, {"detail": "Not Found"})
        route, parameters = matched
        user = None
        if route.authenticated:
            user = self._bearer(headers.get("authorization"))
            if user is None:
                return _Answer(
                    401,
                    {"detail": "invalid_authentication"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        call = _Call(
            method=method,
            path=relative,
            user=user,
            params={},
            query=parse_qs(query, keep_blank_values=True),
            headers=headers,
            raw=raw,
            prefer_async=_prefers_async(headers.get("prefer")),
        )
        try:
            call.params = _path_parameters(parameters)
            self._provided_guard(call, route.action)
            return getattr(self, f"_route_{route.action}")(call)
        except _Invalid as invalid:
            detail = "invalid_authentication" if relative == "/auth/login" else "invalid_request"
            return _Answer(422, {"detail": detail, "errors": invalid.errors})
        except _Refusal as refusal:
            return _Answer(refusal.status, {"detail": refusal.detail}, headers=refusal.headers)

    def _failure(self, method: str, path: str, relative: str | None) -> _Answer | None:
        for rule in self._failures:
            if rule.remaining < 1 or rule.method != method:
                continue
            if rule.pattern.fullmatch(path) is None and (
                relative is None or rule.pattern.fullmatch(relative) is None
            ):
                continue
            rule.remaining -= 1
            if isinstance(rule.body, bytes):
                return _Answer(
                    rule.status,
                    raw=rule.body,
                    headers=dict(rule.headers),
                    content_type="text/plain; charset=utf-8",
                )
            return _Answer(rule.status, rule.body, headers=dict(rule.headers))
        return None

    def _bearer(self, header: str | None) -> _Account | None:
        if not header:
            return None
        scheme, _, token = header.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            return None
        access = self._access.get(token)
        if access is None or access.expires_at <= self._now():
            return None
        return self._accounts_by_id.get(access.account)

    def _owned(self, call: _Call) -> FakeProject | None:
        project = self._projects.get(call.project_id)
        if project is None or project.account.id != call.account.id:
            return None
        return project

    def _new_project(self, account: _Account, name: str, mode: str) -> FakeProject:
        project = FakeProject(self, account, self._new_id(), name, mode, self._now())
        self._projects[project.id] = project
        return project

    def _record(self, project: FakeProject | None, operation: str) -> str:
        identifier = self._new_id()
        if not self.hosted:
            return identifier
        cost = COSTS[operation]
        if self._budget is not None and self._spent + cost > self._budget:
            raise _Refusal(402, {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"})
        self._spent += cost
        if project is not None:
            project.usage.insert(
                0,
                {
                    "generation_id": identifier,
                    "recorded_at": _iso(self._now()),
                    "task": TASKS[operation],
                    "purpose": PURPOSES[operation],
                    "provider_kind": "ANTHROPIC_HOSTED",
                    "model": MODEL,
                    "status": "SUCCEEDED",
                    "failure_code": None,
                    "input_tokens": cost // 10,
                    "output_tokens": cost // 50,
                    "reasoning_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                    "cost_microusd": cost,
                    "latency_milliseconds": 1000 + cost // 1000,
                },
            )
        return identifier

    def _require_budget(self, project: FakeProject | None) -> None:
        if not self.hosted or self._budget is None:
            return
        spent = 0 if project is None else sum(int(item["cost_microusd"]) for item in project.usage)
        if self._spent >= self._budget or spent >= self._budget:
            raise _Refusal(402, {"code": "GENERATION_BUDGET_EXCEEDED"})

    def _later(
        self,
        call: _Call,
        operation: str,
        body: Mapping[str, object],
        work: Callable[[], _Answer],
    ) -> _Answer:
        if not call.prefer_async:
            return work()
        parameters = [
            f"{name}={value}" for name, value in sorted(call.params.items()) if name != "project_id"
        ]
        key = ":".join((operation, *parameters, _digest(dict(body))))
        job = self._start_job(
            call,
            kind="REQUEST",
            operation=operation,
            key=key,
            alternative_id=None,
            work=lambda _job: work(),
        )
        return _Answer(202, job.payload(), headers={"Preference-Applied": "respond-async"})

    def _start_job(
        self,
        call: _Call,
        *,
        kind: str,
        operation: str,
        key: str,
        alternative_id: str | None,
        work: Callable[[_Job], object],
    ) -> _Job:
        owner = call.account.id
        wanted = (owner, call.project_id, kind, key)
        for job in self._jobs.values():
            if job.status == "RUNNING" and not job.lost and job.identity == wanted:
                return job
        running = sum(
            1
            for job in self._jobs.values()
            if job.status == "RUNNING" and not job.lost and job.owner == owner
        )
        if running >= MAX_RUNNING_JOBS:
            raise _Refusal(429, {"code": "TOO_MANY_GENERATIONS"})
        job = _Job(
            id=self._new_id(),
            owner=owner,
            project_id=call.project_id,
            kind=kind,
            operation=operation,
            key=key,
            alternative_id=alternative_id,
            started_at=self._now(),
            work=work,
        )
        self._jobs[job.id] = job
        return job

    def _read_job(self, call: _Call, kind: str | None) -> _Answer:
        job = self._jobs.get(call.params["job_id"])
        if (
            job is None
            or job.lost
            or job.owner != call.account.id
            or job.project_id != call.project_id
            or (kind is not None and job.kind != kind)
        ):
            raise _Refusal(404, {"code": "GENERATION_JOB_NOT_FOUND"})
        if self._lost.get(job.operation, 0) > 0:
            self._lost[job.operation] -= 1
            job.lost = True
            raise _Refusal(404, {"code": "GENERATION_JOB_NOT_FOUND"})
        if job.status == "RUNNING":
            job.polls += 1
            if job.polls > self.job_polls:
                self._finish(job)
            elif job.kind != "REQUEST" and job.polls * 2 > self.job_polls:
                job.stage = "VALIDATING"
        return _Answer(200, job.payload())

    def _finish(self, job: _Job) -> None:
        rules = self._job_rules.get(job.operation)
        project = self._projects.get(job.project_id)
        if rules:
            rule = rules.pop(0)
            if job.kind == "REQUEST":
                job.status = "FAILED"
                job.response = {
                    "status_code": rule.status,
                    "body": {"detail": {"code": rule.code, "stage": "MODEL_PROPOSAL"}},
                }
            else:
                if rule.rejected and project is not None:
                    with contextlib.suppress(_Refusal):
                        self._record(project, job.operation)
                self._fail_job(job, rule.code, rule.rejected)
        elif job.kind == "REQUEST":
            answer = self._request_answer(lambda: job.work(job))
            job.response = {"status_code": answer.status, "body": answer.body}
            job.status = "SUCCEEDED" if answer.status < 400 else "FAILED"
        else:
            try:
                job.result = job.work(job)
                job.status = "SUCCEEDED"
            except _JobFailure as failure:
                self._fail_job(job, failure.code, failure.rejected, failure.reasons)
        job.stage = None
        job.finished_at = self._now()

    def _fail_job(
        self,
        job: _Job,
        code: str,
        rejected: bool,
        reasons: Sequence[Mapping[str, object]] = (),
    ) -> None:
        details = [dict(reason) for reason in reasons]
        if rejected and not details:
            details = [{"code": code, "screen_code": "SCR-001", "detail": REJECTION[self.language]}]
        job.status = "REJECTED" if rejected else "FAILED"
        job.failure = {"code": code, "reasons": details}
        if rejected:
            job.attempt = 2
        if job.operation == "ITERATION":
            project = self._projects.get(job.project_id)
            if project is not None:
                for record in project.iterations:
                    if record["job_id"] == job.id:
                        record["failed"] = job.status

    def _request_answer(self, work: Callable[[], object]) -> _Answer:
        try:
            answer = work()
        except _Refusal as refusal:
            return _Answer(refusal.status, {"detail": refusal.detail})
        except _Invalid as invalid:
            return _Answer(422, {"detail": "invalid_request", "errors": invalid.errors})
        except Exception:
            self.errors.append(traceback.format_exc())
            return _Answer(500, "Internal Server Error")
        if not isinstance(answer, _Answer):
            raise TypeError("a request job must answer")
        return answer

    def _progress(self, project: FakeProject) -> tuple[str, str]:
        progress = project_progress(self._facts(project), sections=self._project_sections(project))
        return progress.current_stage.value, progress.next_action.value

    def _facts(self, project: FakeProject) -> ProjectProgressFacts:
        team = project.team
        snapshot = project.snapshot
        return ProjectProgressFacts(
            brief=_version(project.artifact("brief")),
            brief_gate=_gate_state(project.gates.get("brief")),
            team=None
            if team is None
            else TeamState(
                artifact=_artifact_version(team),
                brief=ArtifactVersion(
                    UUID(str(team["brief_version_id"])),
                    int(team["brief_version_number"]),
                    str(team["brief_content_hash"]),
                ),
                catalog=CatalogVersion(
                    int(team["catalog_version"]), str(team["catalog_content_hash"])
                ),
            ),
            team_gate=_gate_state(project.gates.get("team")),
            user_twins=None
            if snapshot is None
            else UserTwinsState(
                artifact=_artifact_version(snapshot),
                brief=_reference_version(snapshot["snapshot"]["project_brief_reference"]),
                team=_reference_version(snapshot["snapshot"]["agent_team_reference"]),
                catalog=CatalogVersion(
                    int(snapshot["snapshot"]["catalog_version"]),
                    str(snapshot["snapshot"]["catalog_content_hash"]),
                ),
            ),
            user_twins_gate=_gate_state(project.gates.get("twins")),
            requirements=_version(project.specification),
            requirements_gate=_gate_state(project.gates.get("requirements")),
            design=_version(project.design),
            design_gate=_gate_state(project.gates.get("design")),
        )

    def _approvals(self, project: FakeProject | None) -> dict[str, bool]:
        if project is None:
            return dict.fromkeys(STAGES, False)
        facts = self._facts(project)
        brief = _approves(facts.brief_gate, facts.brief)
        team_state = facts.team
        twins_state = facts.user_twins
        team = (
            brief
            and team_state is not None
            and team_state.brief == facts.brief
            and _approves(facts.team_gate, team_state.artifact)
        )
        twins = (
            brief
            and team_state is not None
            and twins_state is not None
            and _approves(facts.team_gate, team_state.artifact)
            and team_state.catalog == CURRENT_CATALOG
            and twins_state.brief == facts.brief
            and twins_state.team == team_state.artifact
            and twins_state.catalog == team_state.catalog
            and _approves(facts.user_twins_gate, twins_state.artifact)
            and self._archetypes_current(project, project.snapshot)
        )
        return {
            "brief": brief,
            "team": bool(team),
            "twins": bool(twins),
            "requirements": _approves(facts.requirements_gate, facts.requirements),
            "design": _approves(facts.design_gate, facts.design),
        }

    def _reference(self, project: FakeProject, stage: str) -> GateArtifactReference | None:
        artifact = project.artifact(stage)
        if artifact is None:
            return None
        return GateArtifactReference(
            project_id=UUID(project.id),
            gate_type=GATE_TYPES[stage],
            artifact_id=UUID(str(artifact["id"])),
            version=int(artifact["version_number"]),
            content_hash=str(artifact["content_hash"]),
        )

    def _save_gate(self, project: FakeProject, stage: str, gate: HumanGate, event: HumanGateEvent):
        project.gates[stage] = gate
        project.gate_events.setdefault(str(gate.id), []).append(event)

    def _submit_gate(
        self, project: FakeProject, stage: str, reference: GateArtifactReference
    ) -> tuple[str, HumanGate | None, list[HumanGateEvent], str | None]:
        moment = self._now()
        owner = UUID(project.account.id)
        latest = project.gates.get(stage)
        if latest is not None and latest.artifact == reference:
            if latest.status is HumanGateStatus.PENDING_APPROVAL:
                return "ALREADY_PENDING", latest, [], None
            if latest.status is HumanGateStatus.APPROVED:
                return "ALREADY_APPROVED", latest, [], None
            if latest.status is HumanGateStatus.DRAFT:
                result = transition_human_gate(
                    latest,
                    action=HumanGateAction.SUBMIT,
                    actor_user_id=owner,
                    occurred_at=moment,
                    event_id=UUID(self._new_id()),
                )
                if result.status is not HumanGateTransitionStatus.APPLIED or result.event is None:
                    return "TRANSITION_REJECTED", latest, [], _issue(result.issue)
                self._save_gate(project, stage, result.gate, result.event)
                return "SUBMITTED", result.gate, [result.event], None
            if latest.status in {
                HumanGateStatus.PAUSED,
                HumanGateStatus.CANCELLED,
                HumanGateStatus.PAUSED_NEEDS_HUMAN,
            }:
                return "GATE_BLOCKED", latest, [], None
            return NEW_ARTIFACT_REQUIRED[stage], latest, [], None
        events: list[HumanGateEvent] = []
        if latest is not None:
            if latest.status in {HumanGateStatus.CANCELLED, HumanGateStatus.PAUSED_NEEDS_HUMAN}:
                return "GATE_BLOCKED", latest, [], None
            if latest.status is not HumanGateStatus.STALE:
                stale = mark_human_gate_stale(
                    latest,
                    current_artifact=reference,
                    occurred_at=moment,
                    event_id=UUID(self._new_id()),
                )
                if stale.status is HumanGateTransitionStatus.REJECTED:
                    return "TRANSITION_REJECTED", latest, [], _issue(stale.issue)
                if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                    self._save_gate(project, stage, stale.gate, stale.event)
                    events.append(stale.event)
                    latest = stale.gate
            budget = next_human_gate_iteration(latest, project.gate_events.get(str(latest.id), ()))
            if budget is None:
                return "ITERATION_LIMIT_REACHED", latest, events, None
            iteration, limit = budget
        else:
            iteration, limit = 1, DEFAULT_GATE_ITERATION_LIMIT
        draft = create_human_gate(
            gate_id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=owner,
            gate_type=GATE_TYPES[stage],
            artifact=reference,
            iteration=iteration,
            max_iterations=limit,
            created_at=moment,
        )
        submitted = transition_human_gate(
            draft,
            action=HumanGateAction.SUBMIT,
            actor_user_id=owner,
            occurred_at=moment,
            event_id=UUID(self._new_id()),
        )
        if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
            return "TRANSITION_REJECTED", draft, events, _issue(submitted.issue)
        self._save_gate(project, stage, submitted.gate, submitted.event)
        return "SUBMITTED", submitted.gate, [*events, submitted.event], None

    def _decide_gate(
        self,
        project: FakeProject,
        stage: str,
        reference: GateArtifactReference,
        action: str,
        reason: str | None,
    ) -> tuple[str, HumanGate | None, HumanGateEvent | None, str | None]:
        gate = project.gates.get(stage)
        if gate is None:
            return "GATE_NOT_FOUND", None, None, None
        if action == "SUBMIT":
            return "REJECTED", gate, None, "INVALID_TRANSITION"
        moment = self._now()
        if gate.artifact != reference:
            stale = mark_human_gate_stale(
                gate, current_artifact=reference, occurred_at=moment, event_id=UUID(self._new_id())
            )
            if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                self._save_gate(project, stage, stale.gate, stale.event)
                return "ARTIFACT_STALE", stale.gate, stale.event, None
            if stale.status is HumanGateTransitionStatus.NO_CHANGE:
                return "ARTIFACT_STALE", gate, None, None
            return "REJECTED", gate, None, _issue(stale.issue)
        result = transition_human_gate(
            gate,
            action=HumanGateAction(action),
            actor_user_id=UUID(project.account.id),
            occurred_at=moment,
            reason=reason,
            event_id=UUID(self._new_id()),
        )
        if result.status is not HumanGateTransitionStatus.APPLIED or result.event is None:
            return "REJECTED", gate, None, _issue(result.issue)
        self._save_gate(project, stage, result.gate, result.event)
        return "APPLIED", result.gate, result.event, None

    def _approve(self, project: FakeProject, stage: str) -> None:
        reference = self._reference(project, stage)
        if reference is None:
            raise RuntimeError(f"nothing to approve at {stage}")
        self._submit_gate(project, stage, reference)
        status, _, _, issue = self._decide_gate(project, stage, reference, "APPROVE", None)
        if status != "APPLIED":
            raise RuntimeError(f"the seed could not approve {stage}: {status} {issue}")

    def _approval_issue(self, project: FakeProject, stage: str, reason: str | None) -> str | None:
        reference = self._require_reference(project, stage)
        submitted, _, _, problem = self._submit_gate(project, stage, reference)
        if submitted not in ("SUBMITTED", "ALREADY_PENDING"):
            return problem or submitted
        status, _, _, issue = self._decide_gate(project, stage, reference, "APPROVE", reason)
        return None if status == "APPLIED" else issue or status

    def _seed_approval(self, project: FakeProject, stage: str) -> None:
        issue = self._approval_issue(project, stage, None)
        if issue is not None:
            raise ValueError(f"the fake studio refuses to approve {stage}: {issue}")

    def _gate_approved(self, project: FakeProject, stage: str) -> bool:
        artifact = project.artifact(stage)
        return artifact is not None and _approves(
            _gate_state(project.gates.get(stage)), _artifact_version(artifact)
        )

    def _gate_events(self, project: FakeProject | None, stage: str, gate_id: str) -> list:
        if project is None:
            return []
        gate = project.gates.get(stage)
        known = {str(gate.id)} if gate is not None else set()
        known.update(
            identifier
            for identifier, events in project.gate_events.items()
            if events and events[0].artifact.gate_type is GATE_TYPES[stage]
        )
        if gate_id not in known:
            return []
        return [_event_payload(event) for event in project.gate_events.get(gate_id, [])]

    def _route_health(self, call: _Call) -> _Answer:
        return _Answer(200, {"status": "ok"})

    def _route_login(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("email", "password"))
        email = fields.text("email", minimum=1, maximum=320)
        password = fields.text("password", minimum=1, maximum=1024)
        fields.check()
        account = self._accounts.get(_email_key(email or "") or "")
        if account is None or account.password != password:
            raise _Refusal(401, "invalid_authentication", {"WWW-Authenticate": "Bearer"})
        return self._signed_in(account, self._refresh_session(account, self._new_id()))

    def _route_register(self, call: _Call) -> _Answer:
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
        if session is None:
            return self._refused_refresh("invalid_refresh_token")
        if session.rotated or session.revoked:
            for other in self._sessions.values():
                if other.family == session.family:
                    other.revoked = True
            return self._refused_refresh("refresh_token_reuse_detected")
        if session.expires_at <= self._now():
            session.revoked = True
            return self._refused_refresh("expired_refresh_token")
        account = self._accounts_by_id[session.account]
        replacement = self._refresh_session(account, session.family)
        session.rotated = True
        return self._signed_in(account, replacement)

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

    def _project_payload(self, project: FakeProject) -> dict[str, object]:
        stage, action = self._progress(project)
        return {
            "id": project.id,
            "display_name": project.name,
            "mode": project.mode,
            "current_brief_version": len(project.briefs),
            "is_archived": False,
            "created_at": _stamp(project.created_at),
            "updated_at": _stamp(project.updated_at),
            "current_stage": stage,
            "next_action": action,
        }

    def _route_list_projects(self, call: _Call) -> _Answer:
        owned = [
            project for project in self._projects.values() if project.account.id == call.account.id
        ]
        owned.sort(key=lambda project: (-project.created_at.timestamp(), project.id))
        return _Answer(200, [self._project_payload(project) for project in owned])

    def _route_create_project(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("display_name", "mode"))
        name = fields.text("display_name", minimum=1, maximum=MAX_PROJECT_NAME)
        mode = fields.choice("mode", PROJECT_MODES)
        fields.check()
        normalized = " ".join((name or "").split())
        if not normalized:
            raise _Refusal(422, "invalid_project")
        project = self._new_project(call.account, normalized, mode or PROJECT_MODES[0])
        return _Answer(201, self._project_payload(project))

    def _route_get_project(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        return _Answer(200, self._project_payload(project))

    def seed_workflow_inputs(
        self, project, *, decisions=(), prototypes=(), gate=None, context_current=True
    ):
        from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
        from orchestwin.workflow_inputs import workflow_records

        envelope = workflow_records(project.id, decisions=decisions, prototypes=prototypes)
        for item in envelope["prototypes"]:
            provided_prototype_from_snapshot(item)
        project.workflow_decisions = copy.deepcopy(envelope["decisions"])
        project.provided_prototypes = copy.deepcopy(envelope["prototypes"])
        project.provided_gate = copy.deepcopy(gate)
        project.provided_context_current = context_current

    def _workflow_inputs(self, project):
        from orchestwin.workflow_inputs import workflow_records

        return workflow_records(project.id, project.workflow_decisions, project.provided_prototypes)

    def _provided_guard(self, call, action):
        from orchestwin.workflow_inputs import (
            PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE,
            PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE,
            PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE,
            PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE,
        )

        if "project_id" not in call.params:
            return
        project = self._owned(call)
        if project is None or not project.provided_prototypes:
            return
        code = None
        if action == "validation_walkthrough":
            code = PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE
        elif call.method != "GET" and "/design/" in call.path:
            if action == "evaluation":
                code = PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE
            elif action.startswith("design_revision"):
                code = PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE
            else:
                code = PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE
        if code is not None:
            raise _Refusal(409, {"code": code})

    def _route_workflow_inputs(self, call):
        return _Answer(200, self._workflow_inputs(self._code_project(call)))

    def _route_provided_state(self, call):
        project = self._code_project(call)
        if not project.provided_prototypes:
            return _Answer(
                200,
                {
                    "source": "EXPLORATION" if project.design else "NONE",
                    "approved": False,
                    "context_current": True,
                    "limits": [],
                },
            )
        return _Answer(
            200,
            {
                "source": "PROVIDED_PROTOTYPE",
                "prototype": copy.deepcopy(project.provided_prototypes[-1]),
                "gate": copy.deepcopy(project.provided_gate),
                "approved": bool(
                    project.provided_gate and project.provided_gate.get("status") == "APPROVED"
                ),
                "context_current": project.provided_context_current,
                "limits": self._workflow_inputs(project)["limits"],
            },
        )

    def _route_provided_current(self, call):
        project = self._code_project(call)
        if not project.provided_prototypes:
            raise _Refusal(404, {"code": "PROVIDED_PROTOTYPE_NOT_FOUND"})
        return _Answer(200, copy.deepcopy(project.provided_prototypes[-1]))

    def _route_provided_gate(self, call):
        project = self._code_project(call)
        if project.provided_gate is None:
            raise _Refusal(404, {"code": "PROVIDED_PROTOTYPE_GATE_NOT_FOUND"})
        return _Answer(200, copy.deepcopy(project.provided_gate))

    def _route_provided_document(self, call):
        from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
        from orchestwin.artifacts.visual_catalog import resolve_visual_tokens

        project = self._code_project(call)
        snapshot = next(
            (
                item
                for item in reversed(project.provided_prototypes)
                if item["id"] == call.params["prototype_id"]
            ),
            None,
        )
        if snapshot is None:
            raise _Refusal(404, {"code": "PROVIDED_PROTOTYPE_NOT_FOUND"})
        prototype = provided_prototype_from_snapshot(snapshot)
        document = mockup_document(
            prototype.mockup.mockup,
            tokens=resolve_visual_tokens(VisualChoices.from_snapshot(prototype.visual_choices)),
            language="en",
            entry_screen=call.query.get("entry_screen", ["SCR-001"])[0],
        )
        return _Answer(200, {"html": document, "title": prototype.title})

    def _route_rename_project(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("display_name",))
        name = fields.text("display_name", minimum=1, maximum=MAX_PROJECT_NAME)
        fields.check()
        normalized = " ".join((name or "").split())
        if not normalized:
            raise _Refusal(422, "invalid_project")
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        project.name = normalized
        project.updated_at = self._now()
        return _Answer(200, self._project_payload(project))

    def _append_brief(
        self, project: FakeProject, brief: ProjectBrief, account: _Account
    ) -> _BriefVersion:
        body: dict[str, object] = {}
        for item in BriefField:
            value = brief.value_for(item)
            body[item.value] = list(value) if isinstance(value, tuple) else value
        body["provided_fields"] = sorted(item.value for item in brief.provided_fields)
        body["unknown_fields"] = sorted(item.value for item in brief.unknown_fields)
        body["missing_fields"] = sorted(item.value for item in brief.missing_fields)
        version = _BriefVersion(
            {
                "id": self._new_id(),
                "project_id": project.id,
                "version_number": len(project.briefs) + 1,
                "schema_version": brief.SCHEMA_VERSION,
                "content_hash": brief.content_hash,
                "created_by_user_id": account.id,
                "created_at": _stamp(self._now()),
                "brief": body,
            },
            brief,
        )
        project.briefs.append(version)
        project.updated_at = self._now()
        return version

    def _route_brief_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        return _Answer(200, [version.payload for version in project.briefs])

    def _route_create_brief(self, call: _Call) -> _Answer:
        text_fields = [item.value for item in BriefField if item not in LIST_FIELDS]
        list_fields = [item.value for item in BriefField if item in LIST_FIELDS]
        fields = _Fields(call.json(), (*text_fields, *list_fields, "unknown_fields"))
        values: dict[str, object] = {}
        for name in text_fields:
            values[name] = fields.text(name, required=False, nullable=True)
        for name in list_fields:
            values[name] = fields.texts(name)
        unknown = fields.texts("unknown_fields", nullable=False, default=[]) or []
        known = {item.value for item in BriefField}
        for index, name in enumerate(unknown):
            if name not in known:
                fields.errors.append(_error(("body", "unknown_fields", index), "enum"))
        fields.check()
        if any(values.get(name) not in (None, "", []) for name in unknown):
            raise _Invalid([_error(("body",), "value_error")])
        try:
            brief = create_project_brief(
                **values, unknown_fields={BriefField(name) for name in unknown}
            )
        except (TypeError, ValueError) as error:
            raise _Refusal(422, "invalid_project_brief") from error
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        current = project.brief
        if current is not None and current.content_hash == brief.content_hash:
            return _Answer(200, current.payload)
        return _Answer(201, self._append_brief(project, brief, call.account).payload)

    def _route_current_brief(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_not_found")
        return _Answer(200, project.brief.payload)

    def _route_brief_version(self, call: _Call) -> _Answer:
        number = int(call.params["version_number"])
        project = self._owned(call)
        if project is None or not 1 <= number <= len(project.briefs):
            raise _Refusal(404, "project_not_found")
        return _Answer(200, project.briefs[number - 1].payload)

    def _require_dialogue_model(self) -> None:
        if not self.hosted:
            raise _Refusal(503, {"code": "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED"})

    def _dialogue_answer(
        self,
        status_code: int,
        outcome: str,
        dialogue: BriefDialogue,
        version: _BriefVersion | None,
        assumptions: Sequence[BriefAssumption] = (),
    ) -> _Answer:
        brief = None if version is None else version.brief
        return _Answer(
            status_code,
            {
                "status": outcome,
                "snapshot": dialogue.to_snapshot(),
                "progress": {
                    "questions_asked": dialogue.question_count,
                    "question_limit": MAX_DIALOGUE_QUESTIONS,
                    "open_fields": []
                    if brief is None
                    else [item.value for item in dialogue.open_fields(brief)],
                    "open_essential_fields": []
                    if brief is None
                    else [item.value for item in dialogue.open_essential_fields(brief)],
                },
                "brief_version": None if version is None else version.payload,
                "assumptions": [_assumption_payload(item) for item in assumptions],
            },
        )

    def _active_dialogue(
        self, call: _Call, expected: int
    ) -> tuple[FakeProject, _BriefVersion, BriefDialogue]:
        project = self._owned(call)
        dialogue = project.dialogues[-1] if project is not None and project.dialogues else None
        if project is None or dialogue is None:
            raise _Refusal(404, {"code": "BRIEF_DIALOGUE_NOT_FOUND"})
        version = project.brief
        if (
            dialogue.status not in ACTIVE_STATUSES
            or version is None
            or expected != dialogue.question_count
        ):
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_CHANGED"})
        return project, version, dialogue

    def _ask(
        self,
        project: FakeProject,
        dialogue: BriefDialogue,
        version: _BriefVersion,
        outcome: str,
    ) -> _Answer:
        open_fields = {item.value for item in dialogue.open_fields(version.brief)}
        name = next((item for item in DIALOGUE_FIELDS if item in open_fields), None)
        if name is None:
            name = next((item for item in self._extra_fields if item in open_fields), None)
        if dialogue.questions_remaining <= 0 or name is None:
            ready = dialogue.as_ready()
            project.dialogues[-1] = ready
            return self._dialogue_answer(201, "BRIEF_DIALOGUE_READY", ready, version)
        generation = self._record(project, "BRIEF_QUESTION")
        turn = BriefDialogueTurn(
            id=UUID(self._new_id()),
            dialogue_id=dialogue.id,
            ordinal=dialogue.question_count + 1,
            field=BriefField(name),
            question={**QUESTIONS[self.language], **EXTRA_QUESTIONS[self.language]}[name],
            model_generation_id=UUID(generation),
            asked_at=self._now(),
        )
        asked = dialogue.with_question(turn)
        project.dialogues[-1] = asked
        return self._dialogue_answer(201, outcome, asked, version)

    def _route_dialogue_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or not project.dialogues:
            raise _Refusal(404, {"code": "BRIEF_DIALOGUE_NOT_FOUND"})
        return self._dialogue_answer(
            200, "BRIEF_DIALOGUE_CURRENT", project.dialogues[-1], project.brief
        )

    def _route_dialogue_start(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("statement",))
        statement = fields.text("statement", minimum=1, maximum=MAX_STATEMENT_CHARACTERS)
        fields.check()
        self._require_dialogue_model()
        try:
            statement = normalized_block(statement, maximum=MAX_STATEMENT_CHARACTERS)
        except ValueError as error:
            raise _Refusal(422, {"code": "BRIEF_STATEMENT_INVALID"}) from error
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        latest = project.dialogues[-1] if project.dialogues else None
        if latest is not None and latest.status in ACTIVE_STATUSES:
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_ACTIVE"})
        version = project.brief
        if version is None:
            version = self._append_brief(
                project, create_project_brief(description=statement), call.account
            )
        dialogue = BriefDialogue(
            id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=UUID(call.account.id),
            source_brief_version_number=version.number,
            statement=statement,
            status=BriefDialogueStatus.OPEN,
            created_at=self._now(),
        )
        project.dialogues.append(dialogue)
        return self._ask(project, dialogue, version, "BRIEF_DIALOGUE_STARTED")

    def _route_dialogue_answer(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count", "kind", "text", "items"))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        kind = fields.choice("kind", ("TEXT", "ITEM_LIST", "UNKNOWN"), literal=True)
        text = fields.text("text", required=False, nullable=True, maximum=MAX_ANSWER_CHARACTERS)
        items = fields.texts("items", maximum_items=MAX_ANSWER_ITEMS)
        fields.check()
        self._require_dialogue_model()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        if dialogue.status is not BriefDialogueStatus.OPEN or dialogue.pending_turn is None:
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_CHANGED"})
        try:
            if kind == "TEXT":
                answer = DialogueAnswer.text_answer(text)
            elif kind == "ITEM_LIST":
                answer = DialogueAnswer.item_list(items if items is not None else [])
            else:
                answer = DialogueAnswer.unknown()
            answered = dialogue.with_answer(answer, answered_at=self._now())
        except ValueError as error:
            raise _Refusal(422, {"code": "BRIEF_ANSWER_INVALID"}) from error
        project.dialogues[-1] = answered
        return self._ask(project, answered, version, "BRIEF_QUESTION_ASKED")

    def _route_dialogue_question(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count",))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        fields.check()
        self._require_dialogue_model()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        if dialogue.status is not BriefDialogueStatus.OPEN or dialogue.pending_turn is not None:
            raise _Refusal(409, {"code": "BRIEF_DIALOGUE_CHANGED"})
        return self._ask(project, dialogue, version, "BRIEF_QUESTION_ASKED")

    def _route_dialogue_synthesis(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count",))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        fields.check()
        self._require_dialogue_model()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        generation = self._record(project, "BRIEF_SYNTHESIS")
        brief, proposals = self._synthesized(project, version.brief, dialogue)
        if brief.content_hash == version.content_hash:
            raise _Refusal(409, {"code": "BRIEF_SYNTHESIS_UNCHANGED"})
        created = self._append_brief(project, brief, call.account)
        moment = self._now()
        recorded = [
            create_brief_assumption(
                assumption_id=UUID(self._new_id()),
                project_id=UUID(project.id),
                brief_version_number=created.number,
                field=item,
                statement=statement,
                source=BriefAssumptionSource.MODEL_PROPOSED,
                created_by_user_id=UUID(call.account.id),
                created_at=moment,
            )
            for item, statement in proposals
        ]
        project.assumptions.extend(recorded)
        synthesized = dialogue.as_synthesized(
            resulting_brief_version_number=created.number,
            synthesis_generation_id=UUID(generation),
            completed_at=moment,
        )
        project.dialogues[-1] = synthesized
        return self._dialogue_answer(201, "BRIEF_SYNTHESIZED", synthesized, created, recorded)

    def _route_dialogue_close(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("expected_turn_count",))
        expected = fields.integer("expected_turn_count", minimum=0, maximum=MAX_DIALOGUE_QUESTIONS)
        fields.check()
        project, version, dialogue = self._active_dialogue(call, int(expected or 0))
        closed = dialogue.as_closed(completed_at=self._now())
        project.dialogues[-1] = closed
        return self._dialogue_answer(200, "BRIEF_DIALOGUE_CLOSED", closed, version)

    def _synthesized(
        self, project: FakeProject, brief: ProjectBrief, dialogue: BriefDialogue
    ) -> tuple[ProjectBrief, list[tuple[BriefField, str]]]:
        answers = {
            turn.field: turn.answer
            for turn in dialogue.answered_turns
            if turn.field is not None and turn.answer is not None
        }
        texts = ASSUMPTIONS[self.language]
        values: dict[str, object] = {}
        unknown: set[BriefField] = set()
        proposals: list[tuple[BriefField, str]] = []
        for item in BriefField:
            current = brief.value_for(item)
            answer = answers.get(item)
            if item is BriefField.NAME:
                values[item.value] = current if current is not None else project.name
            elif answer is not None and answer.kind is DialogueAnswerKind.UNKNOWN:
                if current is not None:
                    values[item.value] = current
                else:
                    unknown.add(item)
                    if item.value in texts:
                        proposals.append((item, texts[item.value]))
            elif answer is not None and answer.kind is DialogueAnswerKind.TEXT:
                values[item.value] = answer.text
            elif answer is not None and answer.kind is DialogueAnswerKind.ITEM_LIST:
                values[item.value] = answer.items
            elif current is not None:
                values[item.value] = current
            else:
                unknown.add(item)
                if item.value in PROPOSED_FIELDS:
                    proposals.append((item, texts[item.value]))
        synthesized = create_project_brief(**values, unknown_fields=unknown)
        missing = synthesized.missing_fields
        if missing:
            synthesized = create_project_brief(**values, unknown_fields=unknown | missing)
        return synthesized, proposals

    def _route_assumptions(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            return _Answer(200, [])
        return _Answer(200, [_assumption_payload(item) for item in project.assumptions])

    def _find_assumption(
        self, project: FakeProject | None, identifier: str
    ) -> tuple[int, BriefAssumption] | None:
        if project is None:
            return None
        for index, item in enumerate(project.assumptions):
            if str(item.id) == identifier:
                return index, item
        return None

    def _route_accept_assumption(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",))
        reason = fields.text("reason", required=False, nullable=True, maximum=2000)
        fields.check()
        reason = _decision_reason(reason)
        project = self._owned(call)
        found = self._find_assumption(project, call.params["assumption_id"])
        if project is None or project.brief is None or found is None:
            raise _Refusal(404, "brief_assumption_not_found")
        index, assumption = found
        current = project.brief
        if assumption.status is not BriefAssumptionStatus.PROPOSED:
            return _Answer(
                409,
                {
                    "status": "ASSUMPTION_NOT_PROPOSED",
                    "assumption": _assumption_payload(assumption),
                    "brief_version": None,
                },
            )
        if assumption.field in current.brief.provided_fields:
            return _Answer(
                409,
                {
                    "status": "FIELD_ALREADY_PROVIDED",
                    "assumption": _assumption_payload(assumption),
                    "brief_version": None,
                },
            )
        accepted = accept_brief_assumption(
            assumption,
            decided_by_user_id=UUID(call.account.id),
            decided_at=self._now(),
            reason=reason,
        )
        project.assumptions[index] = accepted
        version = self._append_brief(
            project, _with_assumption(current.brief, accepted), call.account
        )
        return _Answer(
            200,
            {
                "status": "ACCEPTED",
                "assumption": _assumption_payload(accepted),
                "brief_version": version.payload,
            },
        )

    def _route_reject_assumption(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",))
        reason = fields.text("reason", minimum=1, maximum=2000)
        fields.check()
        normalized = _decision_reason(reason)
        if normalized is None:
            raise _Invalid([_error(("body", "reason"), "value_error")])
        project = self._owned(call)
        found = self._find_assumption(project, call.params["assumption_id"])
        if project is None or found is None:
            raise _Refusal(404, "brief_assumption_not_found")
        index, assumption = found
        if assumption.status is not BriefAssumptionStatus.PROPOSED:
            return _Answer(
                409,
                {
                    "status": "ASSUMPTION_NOT_PROPOSED",
                    "assumption": _assumption_payload(assumption),
                    "brief_version": None,
                },
            )
        rejected = reject_brief_assumption(
            assumption,
            decided_by_user_id=UUID(call.account.id),
            reason=normalized,
            decided_at=self._now(),
        )
        project.assumptions[index] = rejected
        return _Answer(
            200,
            {
                "status": "REJECTED",
                "assumption": _assumption_payload(rejected),
                "brief_version": None,
            },
        )

    def _route_accept_all(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",), optional=True)
        reason = fields.text("reason", required=False, nullable=True, maximum=2000)
        fields.check()
        reason = _decision_reason(reason)
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_brief_not_found")
        current = project.brief
        proposed = sorted(
            (
                (index, item)
                for index, item in enumerate(project.assumptions)
                if item.status is BriefAssumptionStatus.PROPOSED
            ),
            key=lambda pair: (pair[1].created_at, pair[1].field.value),
        )
        provided = current.brief.provided_fields
        updated = current.brief
        selected: list[tuple[int, BriefAssumption]] = []
        skipped: list[BriefAssumption] = []
        for index, item in proposed:
            if item.field in provided or (
                item.field not in LIST_FIELDS and item.field in updated.provided_fields
            ):
                skipped.append(item)
                continue
            updated = _with_assumption(updated, item)
            selected.append((index, item))
        if not selected:
            return _Answer(
                409,
                {
                    "status": "NOTHING_TO_ACCEPT",
                    "accepted": [],
                    "skipped": [_assumption_payload(item) for item in skipped],
                    "brief_version": None,
                },
            )
        moment = self._now()
        accepted = []
        for index, item in selected:
            decided = accept_brief_assumption(
                item, decided_by_user_id=UUID(call.account.id), decided_at=moment, reason=reason
            )
            project.assumptions[index] = decided
            accepted.append(decided)
        version = self._append_brief(project, updated, call.account)
        return _Answer(
            200,
            {
                "status": "ACCEPTED",
                "accepted": [_assumption_payload(item) for item in accepted],
                "skipped": [_assumption_payload(item) for item in skipped],
                "brief_version": version.payload,
            },
        )

    def _route_brief_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_brief_not_found")
        missing = sorted(item.value for item in project.brief.brief.missing_fields)
        if missing:
            return _Answer(
                409,
                {
                    "status": "BRIEF_INCOMPLETE",
                    "gate": None,
                    "events": [],
                    "missing_fields": missing,
                    "issue": None,
                },
            )
        status, gate, events, issue = self._submit_gate(
            project, "brief", self._require_reference(project, "brief")
        )
        return _Answer(
            _submission_status(status),
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "missing_fields": [],
                "issue": issue,
            },
        )

    def _route_brief_gate_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("brief")
        if gate is None:
            raise _Refusal(404, "project_brief_gate_not_found")
        return _Answer(200, _gate_payload(gate))

    def _route_brief_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, DECISION_ACTIONS, literal=True, maximum=2000)
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "project_brief_gate_not_found")
        status, gate, event, issue = self._decide_gate(
            project, "brief", self._require_reference(project, "brief"), action, reason
        )
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, "project_brief_gate_not_found")
        return _Answer(
            200 if status == "APPLIED" else 409,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "event": None if event is None else _event_payload(event),
                "issue": issue,
            },
        )

    def _route_brief_gate_events(self, call: _Call) -> _Answer:
        return _Answer(200, self._gate_events(self._owned(call), "brief", call.params["gate_id"]))

    def _require_reference(self, project: FakeProject, stage: str) -> GateArtifactReference:
        reference = self._reference(project, stage)
        if reference is None:
            raise RuntimeError(f"no artifact at {stage}")
        return reference

    def _team_rules(
        self, project: FakeProject, brief: _BriefVersion, dropped: Sequence[str] = ()
    ) -> DeterministicTeamConstraints:
        constraints = determine_team_constraints(
            project_mode=ProjectMode(project.mode), brief=brief.brief
        )
        if not dropped:
            return constraints
        return replace(
            constraints,
            role_constraints=tuple(
                TeamRoleConstraint(agent_id=item.agent_id, kind=TeamRoleConstraintKind.OPTIONAL)
                if item.agent_id.value in dropped
                else item
                for item in constraints.role_constraints
            ),
            issues=tuple(item for item in constraints.issues if item.agent_id.value not in dropped),
        )

    def _team_content(
        self,
        project: FakeProject,
        brief: _BriefVersion,
        selected: Sequence[str],
        previous: Sequence[Mapping[str, object]],
        rationales: Mapping[str, str],
        rules: Mapping[str, object],
        *,
        owner: bool = False,
    ) -> dict[str, object]:
        constraints = {str(item["agent_id"]): item for item in rules["role_constraints"]}
        earlier = {str(member["agent_id"]): member for member in previous}
        members = []
        for agent in AGENT_ORDER:
            if agent not in selected:
                continue
            if agent in earlier:
                members.append(copy.deepcopy(earlier[agent]))
            elif owner:
                members.append(
                    {
                        "agent_id": agent,
                        "source": "OWNER_ADDED",
                        "justifications": [
                            _justification(
                                "OWNER_RATIONALE",
                                "OWNER_SELECTED_ROLE",
                                statement=rationales.get(agent, OWNER_CHOICE_STATEMENT),
                            )
                        ],
                    }
                )
            elif constraints[agent]["kind"] == "MANDATORY":
                members.append(
                    {
                        "agent_id": agent,
                        "source": "DETERMINISTIC_MANDATORY",
                        "justifications": _rule_justifications(constraints[agent]),
                    }
                )
            else:
                members.append(
                    {
                        "agent_id": agent,
                        "source": "PROPOSER_SUGGESTED",
                        "justifications": [
                            _justification(
                                "PROPOSER_RATIONALE",
                                "MODEL_RECOMMENDATION",
                                statement=TEAM_TEXTS[self.language],
                            )
                        ],
                    }
                )
        return {
            "schema_version": 1,
            "provider_kind": "MODEL_ADAPTER" if self.hosted else "FAKE_DETERMINISTIC",
            "provider_id": HOSTED_TEAM_PROVIDER if self.hosted else DETERMINISTIC_TEAM_PROVIDER,
            "provider_version": 1,
            "project_mode": project.mode,
            "brief_version_id": brief.id,
            "brief_version_number": brief.number,
            "brief_content_hash": brief.content_hash,
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "constraints_content_hash": rules["constraints_content_hash"],
            "selected_agent_ids": [agent for agent in AGENT_ORDER if agent in selected],
            "role_constraints": copy.deepcopy(list(rules["role_constraints"])),
            "constraint_issues": copy.deepcopy(list(rules["constraint_issues"])),
            "members": members,
        }

    def _append_team(
        self,
        project: FakeProject,
        content: dict[str, object],
        revision_kind: str,
        account: _Account,
    ) -> dict[str, object]:
        previous = project.team
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": len(project.teams) + 1,
            "revision_kind": revision_kind,
            "based_on_version_number": None if previous is None else previous["version_number"],
            **{key: content[key] for key in TEAM_CONTENT_KEYS},
            "content_hash": _digest(content),
            "selected_agent_ids": content["selected_agent_ids"],
            "role_constraints": content["role_constraints"],
            "constraint_issues": content["constraint_issues"],
            "members": content["members"],
            "perspectives": _perspectives(content),
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
        }
        version["content_hash"] = _fake_team_proposal(version).content_hash
        project.teams.append(version)
        return version

    def _generated_team(
        self,
        project: FakeProject,
        brief: _BriefVersion,
        constraints: DeterministicTeamConstraints,
        dropped: Sequence[str] = (),
    ) -> dict[str, object]:
        selected = [agent.value for agent in constraints.mandatory_agent_ids]
        if self.hosted:
            optional = {agent.value for agent in constraints.optional_agent_ids}
            selected.extend(
                agent
                for agent in SUGGESTED_SPECIALISTS
                if agent in optional and agent not in dropped
            )
        return self._team_content(project, brief, selected, (), {}, _rules_payload(constraints))

    def _team_matches(self, project: FakeProject) -> bool:
        team = project.team
        brief = project.brief
        return (
            team is not None
            and brief is not None
            and team["brief_version_id"] == brief.id
            and team["brief_version_number"] == brief.number
            and team["brief_content_hash"] == brief.content_hash
        )

    def _route_team_proposal(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "team_proposal_context_not_found")
        if not self._approvals(project)["brief"]:
            return _Answer(409, {"status": "BRIEF_NOT_APPROVED", "version": None, "issues": []})
        constraints = self._team_rules(project, project.brief)
        self._record(project, "TEAM_PROPOSAL")
        content = self._generated_team(project, project.brief, constraints)
        issues = copy.deepcopy(content["constraint_issues"])
        current = project.team
        if (
            current is not None
            and current["content_hash"]
            == _fake_team_proposal({**content, "project_id": project.id}).content_hash
        ):
            return _Answer(200, {"status": "UNCHANGED", "version": current, "issues": issues})
        version = self._append_team(project, content, "PROPOSER_GENERATED", call.account)
        return _Answer(201, {"status": "CREATED", "version": version, "issues": issues})

    def _team_alignment_issue(self, project: FakeProject | None) -> str | None:
        if project is None or project.team is None:
            return "TEAM_NOT_FOUND"
        if not self._gate_approved(project, "brief"):
            return "BRIEF_APPROVAL_REQUIRED"
        if not self._gate_approved(project, "team"):
            return "TEAM_APPROVAL_REQUIRED"
        if self._team_matches(project):
            return "ALREADY_ALIGNED"
        if not team_selection_can_realign(
            _fake_team_proposal(project.team),
            brief=project.brief.brief,
            project_mode=ProjectMode(project.mode),
        ):
            return "PREPARE_AGAIN"
        return None

    def _route_team_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        issue = self._team_alignment_issue(project)
        return _Answer(
            200,
            {
                "aligned": issue == "ALREADY_ALIGNED",
                "issue": issue,
                "team_version_number": None
                if project is None or project.team is None
                else project.team["version_number"],
                "brief_version_number": None
                if project is None or project.brief is None
                else project.brief.number,
            },
        )

    def _realign_team(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._team_alignment_issue(project)
        if issue is not None:
            raise _Refusal(404 if issue == "TEAM_NOT_FOUND" else 409, {"code": issue})
        proposal = reanchored_team(
            _fake_team_proposal(project.team),
            brief=_fake_brief_version(project.brief),
            project_mode=ProjectMode(project.mode),
        )
        content = self._team_content(
            project,
            project.brief,
            [agent.value for agent in proposal.selected_agent_ids],
            proposal.to_snapshot()["members"],
            {},
            _rules_payload(proposal.constraints),
            owner=True,
        )
        return self._append_team(project, content, "OWNER_EDITED", account)

    def _route_realign_team(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "TEAM_NOT_FOUND"})
        version = self._realign_team(project, call.account)
        return _Answer(
            200,
            {
                "version_id": version["id"],
                "version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "gate_approval_required": True,
            },
        )

    def _route_team_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.teams))

    def _route_team_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.team is None:
            raise _Refusal(404, "team_proposal_not_found")
        return _Answer(200, project.team)

    def _route_team_edit(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("selected_agent_ids", "owner_rationales"))
        selected = fields.texts(
            "selected_agent_ids",
            required=True,
            nullable=False,
            minimum_items=1,
            maximum_items=len(AGENT_ORDER),
        )
        for index, agent in enumerate(selected or []):
            if agent not in AGENT_ORDER:
                fields.errors.append(_error(("body", "selected_agent_ids", index), "enum"))
        raw_rationales = fields.value("owner_rationales", required=False)
        rationales: list[tuple[str, str]] = []
        if raw_rationales is not None:
            if not isinstance(raw_rationales, list) or len(raw_rationales) > len(AGENT_ORDER):
                fields.errors.append(_error(("body", "owner_rationales"), "list_type"))
            else:
                for index, item in enumerate(raw_rationales):
                    location = ("body", "owner_rationales", index)
                    if (
                        not isinstance(item, dict)
                        or set(item) != {"agent_id", "statement"}
                        or item["agent_id"] not in AGENT_ORDER
                        or not isinstance(item["statement"], str)
                        or not 1 <= len(item["statement"]) <= 2000
                        or not " ".join(item["statement"].split())
                    ):
                        fields.errors.append(_error(location, "value_error"))
                        continue
                    rationales.append(
                        (str(item["agent_id"]), " ".join(str(item["statement"]).split()))
                    )
        fields.check()
        selected = selected or []
        empty = {"version": None, "issues": [], "events": []}
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, "team_proposal_not_found")
        if not self._approvals(project)["brief"]:
            return _Answer(409, {"status": "BRIEF_NOT_APPROVED", **empty})
        current = project.team
        if current is None:
            raise _Refusal(404, "team_proposal_not_found")
        if not self._team_matches(project):
            return _Answer(409, {"status": "PROPOSAL_STALE", **empty})
        issues = _team_issues(current, selected, rationales)
        if issues:
            return _Answer(
                422, {"status": "REJECTED", "version": None, "issues": issues, "events": []}
            )
        content = self._team_content(
            project,
            project.brief,
            selected,
            list(current["members"]),
            dict(rationales),
            {key: current[key] for key in RULE_KEYS},
            owner=True,
        )
        if _digest(content) == current["content_hash"]:
            return _Answer(
                200, {"status": "UNCHANGED", "version": current, "issues": [], "events": []}
            )
        version = self._append_team(project, content, "OWNER_EDITED", call.account)
        events = []
        latest = project.gates.get("team")
        reference = self._require_reference(project, "team")
        if (
            latest is not None
            and latest.status not in {HumanGateStatus.STALE, HumanGateStatus.CANCELLED}
            and latest.artifact != reference
        ):
            stale = mark_human_gate_stale(
                latest,
                current_artifact=reference,
                occurred_at=self._now(),
                event_id=UUID(self._new_id()),
            )
            if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                self._save_gate(project, "team", stale.gate, stale.event)
                events.append(_event_payload(stale.event))
        return _Answer(
            201, {"status": "UPDATED", "version": version, "issues": [], "events": events}
        )

    def _route_team_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, "project_not_found")
        approvals = self._approvals(project)
        if not approvals["brief"]:
            status = "BRIEF_APPROVAL_REQUIRED"
        elif not self._team_matches(project):
            status = "TEAM_PROPOSAL_REQUIRED"
        elif not approvals["team"]:
            status = "TEAM_APPROVAL_REQUIRED"
        else:
            status = "READY_FOR_MAIN_WORKFLOW"
        return _Answer(200, {"status": status})

    def _team_gate_context(self, call: _Call, missing: str) -> tuple[FakeProject | None, str]:
        project = self._owned(call)
        if project is None or project.brief is None:
            raise _Refusal(404, missing)
        if not self._approvals(project)["brief"]:
            return None, "BRIEF_NOT_APPROVED"
        if project.team is None:
            raise _Refusal(404, missing)
        if not self._team_matches(project):
            return None, "PROPOSAL_STALE"
        return project, ""

    def _route_team_gate_submit(self, call: _Call) -> _Answer:
        project, blocked = self._team_gate_context(call, "agent_team_gate_context_not_found")
        if project is None:
            return _Answer(409, {"status": blocked, "gate": None, "events": [], "issue": None})
        status, gate, events, issue = self._submit_gate(
            project, "team", self._require_reference(project, "team")
        )
        return _Answer(
            _submission_status(status),
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "issue": issue,
            },
        )

    def _route_team_gate_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("team")
        if gate is None:
            raise _Refusal(404, "agent_team_gate_not_found")
        return _Answer(200, _gate_payload(gate))

    def _route_team_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, DECISION_ACTIONS, literal=True, maximum=2000)
        project, blocked = self._team_gate_context(call, "agent_team_gate_not_found")
        if project is None:
            return _Answer(409, {"status": blocked, "gate": None, "event": None, "issue": None})
        status, gate, event, issue = self._decide_gate(
            project, "team", self._require_reference(project, "team"), action, reason
        )
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, "agent_team_gate_not_found")
        return _Answer(
            200 if status == "APPLIED" else 409,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "event": None if event is None else _event_payload(event),
                "issue": issue,
            },
        )

    def _route_team_gate_events(self, call: _Call) -> _Answer:
        return _Answer(200, self._gate_events(self._owned(call), "team", call.params["gate_id"]))

    def _modeling_issue(self, project: FakeProject | None) -> None:
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        approvals = self._approvals(project)
        if not approvals["brief"]:
            raise _Refusal(409, {"code": "BRIEF_APPROVAL_REQUIRED"})
        if project.team is None:
            raise _Refusal(409, {"code": "TEAM_PROPOSAL_REQUIRED"})
        if not approvals["team"]:
            raise _Refusal(409, {"code": "TEAM_APPROVAL_REQUIRED"})

    def _brief_source(self, version: _BriefVersion, locator: str) -> dict[str, object]:
        return {
            "source_kind": "PROJECT_BRIEF",
            "source_id": version.id,
            "source_version": version.number,
            "content_hash": version.content_hash,
            "locator": locator,
            "summary": None,
        }

    def _persona_profile(
        self, name: str, version: _BriefVersion, status: str, reason: str | None
    ) -> dict[str, object]:
        texts = PROFILE[self.language]
        source = self._brief_source(version, "target_users")
        return {
            "name": name,
            "source": "SYSTEM_PROPOSED",
            "kind": "PROTO_PERSONA",
            "confirmation_status": status,
            "rejection_reason": reason,
            "observations": [
                _observation("persona.role", _text_value(name), source),
                _observation(
                    "persona.summary", _text_value(texts["summary"].format(name=name)), source
                ),
                _observation("persona.goals", _items_value(texts["goals"]), source),
                _observation("persona.context_of_use", _text_value(texts["context"]), source),
            ],
        }

    def _persona_version(
        self,
        project: FakeProject,
        persona_id: str,
        number: int,
        profile: dict[str, object],
        account: _Account,
    ) -> dict[str, object]:
        return {
            "id": self._new_id(),
            "project_id": project.id,
            "persona_id": persona_id,
            "version_number": number,
            "based_on_version_number": None if number == 1 else number - 1,
            "content_hash": _fake_persona_profile(profile).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "profile": profile,
        }

    def _current_personas(self, project: FakeProject | None) -> list[dict[str, object]]:
        if project is None:
            return []
        return [
            project.personas[key][-1]
            for key in sorted(project.personas)
            if not project.personas[key][-1]["profile"].get("archived", False)
        ]

    def _archetype_service(self, project: FakeProject) -> ArchetypeService:
        class Unit:
            def __init__(unit, *, owner_user_id):
                unit.owner = owner_user_id
                unit.staged = copy.deepcopy(project.personas)
                unit.personas = unit

            async def __aenter__(unit):
                return unit

            async def __aexit__(unit, *_args):
                return None

            async def lock_project(unit, *, project_id):
                return str(project_id) == project.id and str(unit.owner) == project.account.id

            async def has_pending_revision(unit, *, project_id):
                return str(project_id) == project.id and any(
                    update["status"] == "PROPOSED" for update in project.updates
                )

            async def list_current(unit, *, project_id):
                return tuple(_fake_persona(versions[-1]) for versions in unit.staged.values())

            async def current(unit, *, project_id, persona_id):
                versions = unit.staged.get(str(persona_id))
                return None if not versions else _fake_persona(versions[-1])

            async def append(unit, version):
                unit.staged.setdefault(str(version.persona_id), []).append(version.to_snapshot())
                return VersionAppendStatus.APPENDED

            async def commit(unit):
                project.personas = unit.staged

        return ArchetypeService(
            uow_factory=Unit, uuid_factory=lambda: UUID(self._new_id()), clock=self._now
        )

    def _archetype_input(self, call: _Call, *, editing: bool = False):
        fields = _Fields(
            call.json(),
            (
                "name",
                "description",
                "role",
                "goals",
                "context",
                *(["based_on_version_number"] if editing else []),
            ),
        )
        name = fields.text("name")
        description = fields.text("description")
        role = fields.text("role")
        goals = fields.texts("goals", default=[], nullable=False)
        context = fields.text("context", required=False, nullable=True)
        base = fields.integer("based_on_version_number", minimum=1) if editing else None
        fields.check()
        try:
            data = ArchetypeInput(
                name=name,
                description=description,
                role=role,
                goals=tuple(goals or ()),
                context=context,
            )
        except (TypeError, ValueError) as error:
            raise _domain_refusal(str(error)) from None
        return data, base

    def _archetype_command(self, call: _Call, operation: str, **arguments):
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        service = self._archetype_service(project)
        try:
            result = asyncio.run(
                getattr(service, operation)(
                    owner_user_id=UUID(call.account.id), project_id=UUID(project.id), **arguments
                )
            )
        except ArchetypeFailure as error:
            raise _Refusal(
                404 if error.issue.value in {"PROJECT_NOT_FOUND", "ARCHETYPE_NOT_FOUND"} else 409,
                {"code": error.issue.value},
            ) from None
        return result

    def _route_archetypes(self, call: _Call) -> _Answer:
        return _Answer(
            200, [archetype_payload(item) for item in self._archetype_command(call, "list_current")]
        )

    def _route_archetype_create(self, call: _Call) -> _Answer:
        data, _ = self._archetype_input(call)
        return _Answer(201, archetype_payload(self._archetype_command(call, "create", data=data)))

    def _route_archetype_edit(self, call: _Call) -> _Answer:
        data, base = self._archetype_input(call, editing=True)
        result = self._archetype_command(
            call,
            "edit",
            persona_id=UUID(call.params["persona_id"]),
            based_on_version_number=base,
            data=data,
        )
        return _Answer(200, archetype_payload(result))

    def _route_archetype_archive(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("based_on_version_number",))
        base = fields.integer("based_on_version_number", minimum=1)
        fields.check()
        result = self._archetype_command(
            call,
            "archive",
            persona_id=UUID(call.params["persona_id"]),
            based_on_version_number=base,
        )
        return _Answer(200, archetype_payload(result))

    def _archetypes_current(self, project: FakeProject, snapshot: Mapping[str, object]) -> bool:
        active = [
            item
            for item in self._current_personas(project)
            if item["profile"]["confirmation_status"] != "REJECTED"
        ]
        if any(item["profile"]["confirmation_status"] != "CONFIRMED" for item in active):
            return False

        def key(item):
            return item["id"], item["version_number"], item["content_hash"]

        return {item["persona_id"]: key(item) for item in active} == {
            item["persona_id"]: key(item) for item in snapshot["snapshot"]["persona_versions"]
        }

    def _readable_snapshot(self, snapshot: Mapping[str, object]) -> dict[str, object]:
        document = copy.deepcopy(snapshot)
        for twin in document["snapshot"]["twin_versions"]:
            reference = twin["profile"]["persona_reference"]
            persona = next(
                (
                    item
                    for item in snapshot["snapshot"]["persona_versions"]
                    if all(
                        item[key] == reference[key]
                        for key in ("persona_id", "version_number", "content_hash")
                    )
                ),
                None,
            )
            twin["view"] = _fake_twin_view(twin, persona)
        return document

    def _route_personas(self, call: _Call) -> _Answer:
        return _Answer(200, self._current_personas(self._owned(call)))

    def _route_persona_proposals(self, call: _Call) -> _Answer:
        return self._later(call, "PERSONA_PROPOSAL", {}, lambda: self._proposed_personas(call))

    def _proposed_personas(self, call: _Call) -> _Answer:
        project = self._owned(call)
        self._modeling_issue(project)
        assert project is not None
        if project.personas:
            raise _Refusal(409, {"code": "PERSONAS_ALREADY_EXIST"})
        self._record(project, "PERSONA_PROPOSAL")
        versions = self._propose_personas(project, call.account)
        return _Answer(
            200,
            {
                "status": "CREATED",
                "issue": None,
                "candidate_issue": None,
                "proposal_issue": None,
                "versions": versions,
            },
        )

    def _propose_personas(self, project: FakeProject, account: _Account) -> list:
        brief = project.brief
        if brief is None:
            raise RuntimeError("personas need a brief")
        versions = []
        for name in PERSONAS[self.language][: self.twins]:
            persona_id = self._new_id()
            profile = self._persona_profile(name, brief, "PENDING_CONFIRMATION", None)
            version = self._persona_version(project, persona_id, 1, profile, account)
            project.personas[persona_id] = [version]
            versions.append(version)
        return versions

    def _route_persona_decision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("decision", "reason"))
        decision = fields.choice("decision", ("CONFIRM", "REJECT"))
        reason = fields.text("reason", required=False, nullable=True)
        fields.check()
        project = self._owned(call)
        self._modeling_issue(project)
        assert project is not None
        versions = project.personas.get(call.params["persona_id"])
        if versions is None:
            raise _Refusal(404, {"code": "PERSONA_NOT_FOUND"})
        version = self._decide_persona(project, versions, decision or "", reason, call.account)
        if version is None:
            return _Answer(
                200,
                {
                    "status": "NO_CHANGE",
                    "issue": None,
                    "decision_issue": None,
                    "version": versions[-1],
                },
            )
        return _Answer(
            200,
            {"status": "APPLIED", "issue": None, "decision_issue": None, "version": version},
        )

    def _decide_persona(
        self,
        project: FakeProject,
        versions: list[dict[str, object]],
        decision: str,
        reason: str | None,
        account: _Account,
    ) -> dict[str, object] | None:
        current = versions[-1]
        profile = copy.deepcopy(current["profile"])
        status = profile["confirmation_status"]
        if (decision, status) in {("CONFIRM", "CONFIRMED"), ("REJECT", "REJECTED")}:
            return None
        if status != "PENDING_CONFIRMATION":
            raise _Refusal(409, {"code": "PERSONA_DECISION_REJECTED"})
        if decision == "CONFIRM":
            profile["confirmation_status"] = "CONFIRMED"
        else:
            normalized = " ".join((reason or "").split())
            if not normalized or len(normalized) > 2000:
                raise _Refusal(409, {"code": "PERSONA_DECISION_REJECTED"})
            profile["confirmation_status"] = "REJECTED"
            profile["rejection_reason"] = normalized
        version = self._persona_version(
            project,
            str(current["persona_id"]),
            int(current["version_number"]) + 1,
            profile,
            account,
        )
        versions.append(version)
        return version

    def _snapshot_current(self, project: FakeProject, snapshot: Mapping[str, object]) -> bool:
        brief = project.brief
        team = project.team
        body = snapshot["snapshot"]
        return (
            brief is not None
            and team is not None
            and body["project_brief_reference"]
            == {
                "artifact_id": brief.id,
                "version_number": brief.number,
                "content_hash": brief.content_hash,
            }
            and body["agent_team_reference"] == _plain_reference(team)
        )

    def _route_twins_generate(self, call: _Call) -> _Answer:
        return self._later(call, "USER_TWIN_GENERATION", {}, lambda: self._generated_twins(call))

    def _generated_twins(self, call: _Call) -> _Answer:
        project = self._owned(call)
        self._modeling_issue(project)
        assert project is not None
        snapshot = project.snapshot
        if any(update["status"] == "PROPOSED" for update in project.updates):
            raise _Refusal(409, {"code": "USER_TWIN_REVISION_PENDING"})
        if (
            snapshot is not None
            and self._snapshot_current(project, snapshot)
            and self._archetypes_current(project, snapshot)
        ):
            raise _Refusal(409, {"code": "SNAPSHOT_ALREADY_EXISTS"})
        personas = self._current_personas(project)
        if not personas:
            raise _Refusal(409, {"code": "PERSONAS_REQUIRED"})
        statuses = [persona["profile"]["confirmation_status"] for persona in personas]
        if "PENDING_CONFIRMATION" in statuses:
            raise _Refusal(409, {"code": "PERSONA_CONFIRMATION_REQUIRED"})
        if "CONFIRMED" not in statuses:
            raise _Refusal(409, {"code": "PERSONAS_REQUIRED"})
        self._record(project, "USER_TWIN_GENERATION")
        created = self._create_twins(project, personas, call.account)
        return _Answer(
            200,
            {
                "status": "CREATED",
                "issue": None,
                "proposal_issue": None,
                "snapshot_version": self._readable_snapshot(created),
                "twin_versions": self._readable_snapshot(created)["snapshot"]["twin_versions"],
            },
        )

    def _create_twins(
        self,
        project: FakeProject,
        personas: Sequence[Mapping[str, object]],
        account: _Account,
    ) -> dict[str, object]:
        brief = project.brief
        team = project.team
        if brief is None or team is None:
            raise RuntimeError("twins need a brief and a team")
        confirmed = [
            persona
            for persona in personas
            if persona["profile"]["confirmation_status"] == "CONFIRMED"
        ]
        brief_reference = {
            "artifact_id": brief.id,
            "version_number": brief.number,
            "content_hash": brief.content_hash,
        }
        team_reference = _plain_reference(team)
        twins = []
        previous_twins = (
            {}
            if project.snapshot is None
            else {
                item["profile"]["persona_reference"]["persona_id"]: item
                for item in project.snapshot["snapshot"]["twin_versions"]
            }
        )
        for persona in confirmed:
            twin = self._twin_version(
                project,
                persona,
                brief,
                team_reference,
                account,
                previous=previous_twins.get(persona["persona_id"]),
            )
            project.twins.setdefault(str(twin["twin_id"]), []).append(twin)
            twins.append(twin)
        twins.sort(key=lambda twin: str(twin["twin_id"]))
        ordered = sorted(confirmed, key=lambda persona: str(persona["persona_id"]))
        body = {
            "project_id": project.id,
            "project_brief_reference": brief_reference,
            "agent_team_reference": team_reference,
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "persona_count": len(ordered),
            "twin_count": len(twins),
            "persona_versions": [copy.deepcopy(persona) for persona in ordered],
            "twin_versions": twins,
        }
        previous = project.snapshot
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_modeling(body).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "snapshot": body,
        }
        project.snapshots.append(version)
        return version

    def _twin_version(
        self,
        project: FakeProject,
        persona: Mapping[str, object],
        brief: _BriefVersion,
        team_reference: Mapping[str, object],
        account: _Account,
        *,
        previous: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        texts = PROFILE[self.language]
        name = str(persona["profile"]["name"])
        source = self._brief_source(brief, "target_users")
        values = {
            "role": _text_value(name),
            "expertise": _items_value(texts["expertise"]),
            "goals": _items_value(texts["goals"]),
            "recurring_tasks": _items_value(texts["tasks"]),
            "context_of_use": _text_value(texts["context"]),
            "information_needs": _items_value(texts["needs"]),
            "decision_criteria": None,
            "preferred_vocabulary": None,
            "frustrations": _items_value(texts["frustrations"]),
            "pain_points": _items_value(texts["pain_points"]),
            "trust_concerns": None,
            "accessibility_needs": None,
            "operational_constraints": None,
            "technical_literacy": _text_value(texts["literacy"]),
            "risk_sensitivity": None,
            "assumptions": _items_value(texts["assumptions"]),
        }
        source_values = {
            item["observation_key"]: item["value"] for item in persona["profile"]["observations"]
        }
        for source_field in ("role", "goals", "context_of_use"):
            supplied = source_values.get(f"persona.{source_field}")
            if supplied is not None:
                values[source_field] = supplied if supplied["kind"] in {"TEXT", "ITEMS"} else None
        role_value = source_values.get("persona.role") or {}
        values.update(
            {
                "description": source_values.get("persona.summary"),
                "represents": _items_value([role_value["text"]])
                if role_value.get("kind") == "TEXT" and role_value.get("text")
                else None,
                "does_not_represent": None,
                "evidence_gaps": None,
            }
        )
        observations = [
            _observation(f"user_twin.{key}", value, source)
            if value is not None
            else _unknown_observation(f"user_twin.{key}", source)
            for key, value in values.items()
        ]
        profile = {
            "name": name,
            "persona_reference": {
                "persona_id": persona["persona_id"],
                "version_number": persona["version_number"],
                "content_hash": persona["content_hash"],
                "source": persona["profile"]["source"],
                "kind": persona["profile"]["kind"],
                "confirmation_status": persona["profile"]["confirmation_status"],
            },
            "project_brief_reference": {
                "artifact_id": brief.id,
                "version_number": brief.number,
                "content_hash": brief.content_hash,
            },
            "agent_team_reference": dict(team_reference),
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "validation_status": "PROJECT_GROUNDED_UT",
            "observations": observations,
        }
        return {
            "id": self._new_id(),
            "project_id": project.id,
            "twin_id": self._new_id() if previous is None else previous["twin_id"],
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_twin_profile(profile).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "profile": profile,
        }

    def _route_snapshot_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.snapshot is None:
            raise _Refusal(404, {"code": "USER_MODELING_SNAPSHOT_NOT_FOUND"})
        return _Answer(200, self._readable_snapshot(project.snapshot))

    def _route_snapshot_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(
            200,
            []
            if project is None
            else [self._readable_snapshot(item) for item in project.snapshots],
        )

    def _route_modeling_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        snapshot = None if project is None else project.snapshot
        gate = None if project is None else project.gates.get("twins")
        base = {
            "gate_exists": gate is not None,
            "gate_id": None if gate is None else str(gate.id),
            "gate_status": None if gate is None else gate.status.value,
        }
        if project is None or snapshot is None:
            return _Answer(
                200,
                {
                    "snapshot_exists": False,
                    "snapshot_version_id": None,
                    "snapshot_version_number": None,
                    "snapshot_content_hash": None,
                    **base,
                    "approved_current_snapshot": False,
                    "context_current": True,
                    "archetypes_current": False,
                    "workflow_state": "USER_MODELING_REQUIRED",
                    "twins": [],
                },
            )
        context_current = self._snapshot_current(project, snapshot)
        archetypes_current = self._archetypes_current(project, snapshot)
        reference = self._require_reference(project, "twins")
        approved = (
            context_current
            and archetypes_current
            and gate is not None
            and gate.status is HumanGateStatus.APPROVED
            and gate.artifact == reference
        )
        return _Answer(
            200,
            {
                "snapshot_exists": True,
                "snapshot_version_id": snapshot["id"],
                "snapshot_version_number": snapshot["version_number"],
                "snapshot_content_hash": snapshot["content_hash"],
                **base,
                "approved_current_snapshot": approved,
                "context_current": context_current,
                "archetypes_current": archetypes_current,
                "workflow_state": "READY_FOR_REQUIREMENTS_DEFINITION"
                if approved
                else "USER_MODELING_REVIEW_REQUIRED",
                "twins": [
                    {
                        "twin_id": twin["twin_id"],
                        "version_number": twin["version_number"],
                        "persisted_status": twin["profile"]["validation_status"],
                        "effective_status": "OWNER_APPROVED_UT"
                        if approved
                        else "PROJECT_GROUNDED_UT",
                    }
                    for twin in snapshot["snapshot"]["twin_versions"]
                ],
            },
        )

    def _twins_command(
        self,
        outcome: str,
        gate: HumanGate | None,
        events: Sequence[HumanGateEvent],
    ) -> _Answer:
        return _Answer(
            200,
            {
                "outcome": outcome,
                "gate": None if gate is None else _gate_payload(gate, resume=False),
                "events": [_event_payload(event) for event in events],
                "issue": None,
            },
        )

    def _route_twins_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.snapshot is None:
            raise _Refusal(404, {"code": "SNAPSHOT_NOT_FOUND"})
        status, gate, events, issue = self._submit_gate(
            project, "twins", self._require_reference(project, "twins")
        )
        if status == "SUBMITTED":
            return self._twins_command("APPLIED", gate, events)
        if status in {"ALREADY_PENDING", "ALREADY_APPROVED"}:
            return self._twins_command("NO_CHANGE", gate, events)
        raise _Refusal(409, {"code": issue or status})

    def _route_twins_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, GATE_ACTIONS, literal=False, maximum=None)
        if action == "SUBMIT":
            raise _Invalid([_error(("body",), "value_error")])
        project = self._owned(call)
        if project is None or project.snapshot is None:
            raise _Refusal(404, {"code": "SNAPSHOT_NOT_FOUND"})
        status, gate, event, issue = self._decide_gate(
            project, "twins", self._require_reference(project, "twins"), action, reason
        )
        if status == "APPLIED":
            return self._twins_command("APPLIED", gate, [] if event is None else [event])
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, {"code": status})
        raise _Refusal(409, {"code": issue or status})

    def _route_twins_gate_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("twins")
        if gate is None:
            raise _Refusal(404, {"code": "USER_MODELING_GATE_NOT_FOUND"})
        return _Answer(200, _gate_payload(gate, resume=False))

    def _route_twins_gate_events(self, call: _Call) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get("twins")
        if project is None or gate is None:
            return _Answer(200, [])
        return _Answer(
            200, [_event_payload(event) for event in project.gate_events.get(str(gate.id), [])]
        )

    def _current_twin(self, project: FakeProject | None, twin_id: str) -> dict | None:
        if project is None or twin_id not in project.twins:
            return None
        return project.twins[twin_id][-1]

    def _route_conversation(self, call: _Call) -> _Answer:
        project = self._owned(call)
        conversation = (
            None if project is None else project.conversations.get(call.params["twin_id"])
        )
        if conversation is None:
            raise _Refusal(404, {"code": "TWIN_CONVERSATION_NOT_FOUND"})
        return _Answer(200, {"snapshot": conversation.to_snapshot()})

    def _route_conversation_turn(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("question", "expected_turn_count"))
        question = fields.text("question", minimum=1, maximum=MAX_QUESTION_CHARACTERS)
        expected = fields.integer(
            "expected_turn_count", minimum=0, maximum=MAX_TURNS_PER_CONVERSATION
        )
        fields.check()
        try:
            question = normalized_text(question, maximum=MAX_QUESTION_CHARACTERS)
        except ValueError as error:
            raise _Refusal(422, {"code": "TWIN_QUESTION_INVALID"}) from error
        project = self._owned(call)
        twin_id = call.params["twin_id"]
        twin = self._current_twin(project, twin_id)
        if project is None or twin is None:
            raise _Refusal(404, {"code": "USER_TWIN_NOT_FOUND"})
        latest = project.conversations.get(twin_id)
        current = (
            latest if latest is not None and str(latest.twin_version_id) == twin["id"] else None
        )
        turns = () if current is None else current.turns
        if expected != len(turns):
            raise _Refusal(409, {"code": "TWIN_CONVERSATION_CHANGED"})
        if len(turns) >= MAX_TURNS_PER_CONVERSATION:
            raise _Refusal(409, {"code": "TWIN_CONVERSATION_FULL"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TWIN_CHAT_MODEL_NOT_CONFIGURED"})
        generation = self._record(project, "TWIN_CHAT")
        moment = self._now()
        name = str(twin["profile"]["name"])
        conversation = current or TwinConversation(
            id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=UUID(call.account.id),
            twin_id=UUID(twin_id),
            twin_version_id=UUID(str(twin["id"])),
            twin_version_number=int(twin["version_number"]),
            twin_content_hash=str(twin["content_hash"]),
            twin_name=name,
            created_at=moment,
            turns=(),
        )
        reply, insight = CHAT[self.language]
        turn = TwinConversationTurn(
            id=UUID(self._new_id()),
            conversation_id=conversation.id,
            ordinal=len(turns) + 1,
            question=question,
            reply=reply.format(name=name),
            insights=(
                TwinInsight(
                    kind=TwinInsightKind.NEED,
                    text=insight,
                    confidence=0.6,
                    grounded_on=("user_twin.goals",),
                ),
            ),
            model_generation_id=UUID(generation),
            created_at=moment,
        )
        recorded = conversation.with_turn(turn)
        project.conversations[twin_id] = recorded
        return _Answer(201, {"status": "TWIN_TURN_RECORDED", "snapshot": recorded.to_snapshot()})

    def _specification(self, project: FakeProject, *, schema_version: int = 2) -> dict[str, object]:
        brief = project.brief
        team = project.team
        snapshot = project.snapshot
        if brief is None or team is None or snapshot is None:
            raise RuntimeError("requirements need brief, team and twins")
        language = self.language
        twins = [_twin_reference(twin) for twin in snapshot["snapshot"]["twin_versions"]]
        source = {
            "kind": "PROJECT_BRIEF",
            "source_id": brief.id,
            "source_version": brief.number,
            "content_hash": brief.content_hash,
            "locator": "functional_requirements",
        }
        requirements = [
            {
                "id": self._new_id(),
                "code": f"REQ-{index:03d}",
                "title": title,
                "statement": statement,
                "kind": kind,
                "priority": priority,
                "sources": [dict(source)],
                "user_twin_references": copy.deepcopy(twins),
            }
            for index, (kind, priority, title, statement) in enumerate(
                REQUIREMENTS[language], start=1
            )
        ]
        goal, benefit = STORY[language]
        stories = [
            {
                "id": self._new_id(),
                "code": f"USR-{index:03d}",
                "user_twin_reference": dict(twin),
                "goal": goal,
                "benefit": benefit,
                "requirement_ids": _identifiers(requirements[:2]),
            }
            for index, twin in enumerate(twins, start=1)
        ]
        criteria = [
            {
                "id": self._new_id(),
                "code": f"AC-{index:03d}",
                "statement": statement,
                "verification_method": "AUTOMATED_TEST",
                "requirement_ids": [requirements[index - 1]["id"]],
                "user_story_ids": [stories[0]["id"]] if index == 1 else [],
            }
            for index, statement in enumerate(CRITERIA[language], start=1)
        ]
        title, preconditions, trigger, steps, outcome = SCENARIO[language]
        summary, mitigation = RISK[language]
        specification = {
            "schema_version": 1,
            "project_id": project.id,
            "project_brief_reference": {
                "kind": "PROJECT_BRIEF",
                "artifact_id": brief.id,
                "version_number": brief.number,
                "content_hash": brief.content_hash,
            },
            "agent_team_reference": {"kind": "AGENT_TEAM", **_plain_reference(team)},
            "user_modeling_reference": {"kind": "USER_MODELING", **_plain_reference(snapshot)},
            "catalog_version": AGENT_CATALOG_VERSION,
            "catalog_content_hash": AGENT_CATALOG_CONTENT_HASH,
            "user_twin_references": twins,
            "requirements": requirements,
            "user_stories": stories,
            "acceptance_criteria": criteria,
            "scenarios": [
                {
                    "id": self._new_id(),
                    "code": "SCN-001",
                    "title": title,
                    "actor": dict(twins[0]),
                    "preconditions": list(preconditions),
                    "trigger": trigger,
                    "steps": list(steps),
                    "expected_outcome": outcome,
                    "requirement_ids": _identifiers(requirements[:2]),
                    "acceptance_criterion_ids": _identifiers(criteria[:2]),
                }
            ],
            "risks": [
                {
                    "id": self._new_id(),
                    "code": "RSK-001",
                    "summary": summary,
                    "likelihood": "POSSIBLE",
                    "impact": "MEDIUM",
                    "mitigation": mitigation,
                    "requirement_ids": [requirements[1]["id"]],
                    "sources": [dict(source)],
                    "review_status": "PROPOSED",
                }
            ],
            "definition_of_done": [
                {
                    "id": self._new_id(),
                    "code": f"DOD-{index:03d}",
                    "statement": statement,
                    "verification_method": "MANUAL_REVIEW",
                    "applicability": "REQUIRED",
                    "condition": None,
                    "requirement_ids": [],
                }
                for index, statement in enumerate(DONE[language], start=1)
            ],
        }

        if schema_version == 2:
            self._definition(
                specification,
                context=str(brief.brief.problem or brief.brief.description),
                goal=str((brief.brief.goals or (goal,))[0]),
            )
        return specification

    def _definition(
        self,
        specification: dict[str, object],
        *,
        context: str | None = None,
        goal: str | None = None,
    ) -> None:
        twins = specification["user_twin_references"]
        scenarios = specification["scenarios"]
        source = copy.deepcopy(specification["requirements"][0]["sources"])
        stories = specification["user_stories"]
        template = copy.deepcopy(scenarios[0])
        numbers = [_code_number(item["code"]) for item in scenarios]
        for twin in twins:
            if not any(item["actor"]["twin_id"] == twin["twin_id"] for item in scenarios):
                scenario = copy.deepcopy(template)
                scenario["id"] = self._new_id()
                scenario["code"] = f"SCN-{max(numbers, default=0) + 1:03d}"
                numbers.append(_code_number(scenario["code"]))
                scenario["actor"] = copy.deepcopy(twin)
                scenarios.append(scenario)
        needs = []
        for index, twin in enumerate(twins, start=1):
            story = next(
                item
                for item in stories
                if item["user_twin_reference"]["twin_id"] == twin["twin_id"]
            )
            owned = [item for item in scenarios if item["actor"]["twin_id"] == twin["twin_id"]]
            for scenario in owned:
                scenario["context"] = context or str(scenario["trigger"])
                scenario["goal"] = goal or str(story["goal"])
                scenario["criticalities"] = [
                    str(item["summary"]) for item in specification["risks"]
                ]
                scenario["sources"] = copy.deepcopy(source)
            need = {
                "id": self._new_id(),
                "code": f"NED-{index:03d}",
                "title": str(story["goal"]),
                "statement": str(story["benefit"]),
                "scenario_ids": _identifiers(owned),
                "sources": copy.deepcopy(source),
            }
            needs.append(need)
            story["need_ids"] = [need["id"]]
        for requirement in specification["requirements"]:
            requirement["need_ids"] = _identifiers(needs)
        specification["needs"] = needs
        specification["schema_version"] = 2

    def _append_requirements(
        self, project: FakeProject, specification: dict[str, object], account: _Account
    ) -> dict[str, object]:
        previous = project.specification
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_requirements(specification).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "specification": specification,
        }
        project.requirements.append(version)
        return version

    def _requirements_governance(self, project: FakeProject | None) -> None:
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        approvals = self._approvals(project)
        for stage, code in APPROVAL_CODES[:3]:
            if not approvals[stage]:
                raise _Refusal(409, {"code": code})

    def _route_requirements_proposal(self, call: _Call) -> _Answer:
        return self._later(
            call, "REQUIREMENTS_PROPOSAL", {}, lambda: self._generated_requirements(call)
        )

    def _generated_requirements(self, call: _Call) -> _Answer:
        project = self._owned(call)
        self._requirements_governance(project)
        assert project is not None
        if project.specification is not None:
            raise _Refusal(409, {"code": "SPECIFICATION_ALREADY_EXISTS"})
        self._record(project, "REQUIREMENTS_PROPOSAL")
        version = self._append_requirements(project, self._specification(project), call.account)
        return _Answer(
            201,
            {
                "status": "CREATED",
                "version": version,
                "issue": None,
                "proposal_issue": None,
                "persistence_status": "APPENDED",
            },
        )

    def _route_requirements_current(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.specification is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"})
        return _Answer(200, project.specification)

    def _route_requirements_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.requirements))

    def _route_requirements_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        version = None if project is None else project.specification
        gate = None if project is None else project.gates.get("requirements")
        if project is None or version is None:
            status = "REQUIREMENTS_REQUIRED"
        elif self._approvals(project)["requirements"]:
            status = "READY_FOR_DESIGN_EXPLORATION"
        else:
            status = "REQUIREMENTS_APPROVAL_REQUIRED"
        return _Answer(
            200,
            {
                "status": status,
                "version": version,
                "gate": None if gate is None else _gate_payload(gate),
                "approved_current_specification": status == "READY_FOR_DESIGN_EXPLORATION",
            },
        )

    def _route_requirements_change(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("request", "include_journeys"))
        request = fields.text("request")
        include_journeys = call.json().get("include_journeys", False)
        if not isinstance(include_journeys, bool):
            raise _Invalid([_error(("body", "include_journeys"), "bool_type")])
        fields.flag("include_journeys")
        fields.check()
        text = (request or "").strip()
        if not 1 <= len(text) <= MAX_CHANGE_REQUEST:
            raise _Invalid([_error(("body", "request"), "value_error")])
        return self._later(
            call,
            "REQUIREMENTS_CHANGE",
            {"request": text, **({"include_journeys": True} if include_journeys else {})},
            lambda: self._changed_requirements(call, text, include_journeys=include_journeys),
        )

    def _changed_requirements(
        self, call: _Call, text: str, *, include_journeys: bool = False
    ) -> _Answer:
        project = self._owned(call)
        self._requirements_governance(project)
        assert project is not None
        current = project.specification
        if current is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"})
        if any(
            diff["status"] == "PROPOSED" and diff["base_version_id"] == current["id"]
            for diff in project.requirement_diffs
        ):
            raise _Refusal(409, {"code": "REQUIREMENTS_REVISION_PENDING"})
        self._record(project, "REQUIREMENTS_CHANGE")
        if include_journeys:
            proposed = self._with_journeys(current["specification"])
        else:
            proposed, _ = self._with_requirement(current["specification"], text)
        base = {
            **current,
            "specification": _fake_requirements(current["specification"]).to_snapshot(),
        }
        result = propose_requirements_diff(
            base_version=stage_versions({"requirements": base})["requirements"],
            proposed_specification=_fake_requirements(proposed),
            diff_id=UUID(self._new_id()),
            created_by_user_id=UUID(call.account.id),
            created_at=self._now(),
        )
        if result.diff is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_UNCHANGED"})
        diff = RequirementsSpecificationDiffPayload.from_domain(result.diff).model_dump(mode="json")
        project.requirement_diffs.append(diff)
        return _Answer(201, _revision_payload("CREATED", diff, None))

    def _with_journeys(self, specification: Mapping[str, object]) -> dict[str, object]:
        proposed = copy.deepcopy(dict(specification))
        if proposed.get("schema_version", 1) == 1:
            self._definition(proposed)
        journeys = proposed.setdefault("journeys", [])
        covered = {item["scenario_id"] for item in journeys}
        number = max((_code_number(item["code"]) for item in journeys), default=0)
        for scenario in proposed["scenarios"]:
            if scenario["id"] in covered:
                continue
            need_ids = [
                item["id"] for item in proposed["needs"] if scenario["id"] in item["scenario_ids"]
            ]
            number += 1
            journeys.append(
                {
                    "id": self._new_id(),
                    "code": f"JRN-{number:03d}",
                    "title": scenario["title"],
                    "scenario_id": scenario["id"],
                    "phases": [
                        {
                            "title": f"{'Fase' if self.language == 'it' else 'Phase'} {index}",
                            "action": action,
                            "touchpoint": None,
                            "criticalities": scenario.get("criticalities", [])
                            if index == 1
                            else [],
                            "need_ids": need_ids,
                        }
                        for index, action in enumerate(scenario["steps"][:32], 1)
                    ],
                    "sources": copy.deepcopy(scenario["sources"]),
                }
            )
        return proposed

    def _with_requirement(
        self, specification: Mapping[str, object], text: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        proposed = copy.deepcopy(dict(specification))
        if proposed.get("schema_version", 1) == 1:
            self._definition(proposed)
        requirements = proposed["requirements"]
        numbers = [_code_number(item["code"]) for item in requirements]
        added = {
            "id": self._new_id(),
            "code": f"REQ-{max(numbers, default=0) + 1:03d}",
            "title": OWNER_CHANGE[self.language],
            "statement": " ".join(text.split()),
            "kind": "FUNCTIONAL",
            "priority": "SHOULD",
            "sources": [
                {
                    "kind": "OWNER_INPUT",
                    "source_id": "owner-request",
                    "source_version": None,
                    "content_hash": None,
                    "locator": None,
                }
            ],
            "user_twin_references": [],
        }
        added["need_ids"] = _identifiers(proposed["needs"][:1])
        requirements.append(added)
        return proposed, added

    def _pending_requirements_diff(self, project: FakeProject) -> dict[str, object] | None:
        current = project.specification
        return next(
            (
                diff
                for diff in project.requirement_diffs
                if current is not None
                and diff["status"] == "PROPOSED"
                and diff["base_version_id"] == current["id"]
            ),
            None,
        )

    def _route_requirements_revisions(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.requirement_diffs))

    def _route_requirements_revision(self, call: _Call) -> _Answer:
        project = self._owned(call)
        diff = _by_id([] if project is None else project.requirement_diffs, call.params["diff_id"])
        if diff is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_DIFF_NOT_FOUND"})
        return _Answer(200, diff)

    def _route_requirements_revision_decision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("decision", "reason"))
        decision = fields.choice("decision", ("APPROVE", "REJECT"))
        reason = fields.text("reason", required=False, nullable=True, maximum=2000)
        fields.check()
        project = self._owned(call)
        diff = _by_id([] if project is None else project.requirement_diffs, call.params["diff_id"])
        if project is None or diff is None:
            raise _Refusal(404, {"code": "DIFF_NOT_FOUND"})
        wanted = "APPROVED" if decision == "APPROVE" else "REJECTED"
        if diff["status"] != "PROPOSED":
            if diff["status"] == wanted:
                return _Answer(200, _revision_payload("NO_CHANGE", diff, None))
            raise _Refusal(409, {"code": "DECISION_REJECTED"})
        normalized = _blank_to_none(reason)
        if decision == "REJECT" and normalized is None:
            raise _Refusal(409, {"code": "DECISION_REJECTED"})
        current = project.specification
        if current is None:
            raise _Refusal(404, {"code": "SPECIFICATION_NOT_FOUND"})
        if (current["id"], current["version_number"], current["content_hash"]) != (
            diff["base_version_id"],
            diff["base_version_number"],
            diff["base_content_hash"],
        ):
            raise _Refusal(409, {"code": "CONTEXT_CHANGED"})
        version = None
        if decision == "APPROVE":
            version = self._append_requirements(
                project, copy.deepcopy(diff["proposed_specification"]), call.account
            )
            diff["applied_specification_version_id"] = version["id"]
        diff["status"] = wanted
        diff["decided_by_user_id"] = call.account.id
        diff["decided_at"] = _stamp(self._now())
        diff["decision_reason"] = normalized
        return _Answer(200, _revision_payload("APPLIED", diff, version))

    def _route_requirements_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.specification is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND"})
        status, gate, events, issue = self._submit_gate(
            project, "requirements", self._require_reference(project, "requirements")
        )
        if status not in {"SUBMITTED", "ALREADY_PENDING", "ALREADY_APPROVED"}:
            raise _Refusal(409, {"code": status})
        return _Answer(
            200,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "issue": issue,
            },
        )

    def _route_requirements_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, GATE_ACTIONS, literal=False, maximum=2000)
        if action == "SUBMIT":
            raise _Invalid([_error(("body",), "value_error")])
        project = self._owned(call)
        if project is None or project.specification is None:
            raise _Refusal(404, {"code": "SPECIFICATION_NOT_FOUND"})
        return self._stage_decision(project, "requirements", action, reason)

    def _stage_decision(
        self, project: FakeProject, stage: str, action: str, reason: str | None
    ) -> _Answer:
        status, gate, event, issue = self._decide_gate(
            project, stage, self._require_reference(project, stage), action, reason
        )
        if status == "GATE_NOT_FOUND":
            raise _Refusal(404, {"code": status})
        if status != "APPLIED":
            raise _Refusal(409, {"code": issue or status})
        return _Answer(
            200,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "event": None if event is None else _event_payload(event),
                "issue": None,
            },
        )

    def _stage_gate(self, call: _Call, stage: str, missing: str) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get(stage)
        if gate is None:
            raise _Refusal(404, {"code": missing})
        return _Answer(200, _gate_payload(gate))

    def _stage_events(self, call: _Call, stage: str, missing: str) -> _Answer:
        project = self._owned(call)
        gate = None if project is None else project.gates.get(stage)
        if project is None or gate is None:
            raise _Refusal(404, {"code": missing})
        return _Answer(
            200, [_event_payload(event) for event in project.gate_events.get(str(gate.id), [])]
        )

    def _route_requirements_gate_current(self, call: _Call) -> _Answer:
        return self._stage_gate(call, "requirements", "REQUIREMENTS_GATE_NOT_FOUND")

    def _route_requirements_gate_events(self, call: _Call) -> _Answer:
        return self._stage_events(call, "requirements", "REQUIREMENTS_GATE_NOT_FOUND")

    def _design_package(self, project: FakeProject) -> dict[str, object]:
        requirements = project.specification
        team = project.team
        snapshot = project.snapshot
        if requirements is None or team is None or snapshot is None:
            raise RuntimeError("design needs requirements, team and twins")
        twins = sorted(
            (dict(item) for item in requirements["specification"]["user_twin_references"]),
            key=lambda twin: str(twin["twin_id"]),
        )
        grounding = _grounding(requirements, team, snapshot, twins)
        if self.hosted:
            return self._hosted_package(project, twins, grounding)
        return self._deterministic_package(project, requirements, twins, grounding)

    def _deterministic_package(
        self,
        project: FakeProject,
        requirements: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        grounding: Mapping[str, object],
    ) -> dict[str, object]:
        specification = requirements["specification"]
        stories = list(specification["user_stories"])
        goal = _bounded(str(stories[0]["goal"]))
        references = [
            (grounding[key], summary)
            for key, summary in (
                ("requirements_reference", "Approved Requirements baseline used by design."),
                ("agent_team_reference", "Approved Agent Team used by design."),
                ("user_modeling_reference", "Approved User Modeling state used by design."),
            )
        ]
        alternatives: list[dict[str, object]] = []
        critiques: list[dict[str, object]] = []
        concerns: list[dict[str, object]] = []
        for ordinal, template in enumerate(_ALTERNATIVE_TEMPLATES, start=1):
            approach = template.approach.value
            direction = approach.casefold().replace("_", " ")
            code = f"DES-{ordinal:03d}"
            language = create_visual_language(
                choices=template.visual,
                product_name=template.product_name,
                rationale=template.visual_rationale,
                twin_fit=tuple(
                    TwinFit(
                        twin_id=UUID(str(twin["twin_id"])),
                        name=str(twin["name"]),
                        statement=f"{template.product_name} keeps the {direction} direction "
                        f"legible and predictable for {twin['name']}.",
                    )
                    for twin in twins
                ),
            )
            alternative_id = self._new_id()
            alternatives.append(
                {
                    "id": alternative_id,
                    "code": code,
                    "approach": approach,
                    "title": f"{template.title_prefix}: {goal}",
                    "summary": template.summary,
                    "rationale": template.rationale,
                    "requirement_ids": list(grounding["requirement_ids"]),
                    "user_story_ids": list(grounding["user_story_ids"]),
                    "acceptance_criterion_ids": list(grounding["acceptance_criterion_ids"]),
                    "user_twin_references": copy.deepcopy(list(twins)),
                    "workflows": [
                        {
                            "id": self._new_id(),
                            "code": f"FLOW-{index:03d}",
                            "title": f"{template.title_prefix}: {_bounded(str(story['goal']))}",
                            "steps": [
                                step.format(code=story["code"]) for step in WORKFLOW_STEPS[approach]
                            ],
                            "requirement_ids": list(story["requirement_ids"]),
                            "user_story_ids": [story["id"]],
                        }
                        for index, story in enumerate(stories, start=1)
                    ],
                    "information_architecture": list(template.information_architecture),
                    "accessibility_considerations": list(template.accessibility_considerations),
                    "security_considerations": list(template.security_considerations),
                    "advantages": list(template.advantages),
                    "trade_offs": list(template.trade_offs),
                    "assumptions": [],
                    "open_questions": [template.open_question],
                    "visual_language": language.to_snapshot(),
                }
            )
            for twin in twins:
                observations = self._twin_observations(project, twin)
                grounded = next(
                    item
                    for item in observations
                    if item["value"]["kind"] in ("TEXT", "ITEMS")
                    and item["epistemic_status"] != "UNSUPPORTED_ASSUMPTION"
                )
                context = (
                    grounded["value"]["text"] or twin["name"]
                    if grounded["value"]["kind"] == "TEXT"
                    else grounded["value"]["items"][0]
                )
                provenance = [
                    dict(reference) for item in observations for reference in item["provenance"]
                ]
                for reference, summary in references:
                    evidence = {
                        "source_kind": "SYSTEM_ARTIFACT",
                        "source_id": reference["artifact_id"],
                        "source_version": reference["version_number"],
                        "content_hash": reference["content_hash"],
                        "locator": str(reference["kind"]).casefold(),
                        "summary": summary,
                    }
                    provenance.append(evidence)
                provenance.append(
                    {
                        "source_kind": "MODEL_OUTPUT",
                        "source_id": FAKE_DESIGN_PROVIDER_ID,
                        "source_version": FAKE_DESIGN_PROVIDER_VERSION,
                        "content_hash": None,
                        "locator": f"alternatives.{code}.user_twins.{twin['twin_id']}"
                        f".v{twin['version_number']}",
                        "summary": "Deterministic synthetic design critique generated from "
                        "governed inputs.",
                    }
                )
                critiques.append(
                    {
                        "id": self._new_id(),
                        "code": f"CRQ-{len(critiques) + 1:03d}",
                        "kind": "SYNTHETIC_USER_TWIN",
                        "design_alternative_id": alternative_id,
                        "user_twin_reference": dict(twin),
                        "strengths": [
                            f"The {direction} direction keeps every proposed workflow linked "
                            "to approved requirements and user stories."
                        ],
                        "concerns": [
                            f"The main trade-off remains hypothetical for {twin['name']}: "
                            f"{template.trade_offs[0]}"
                        ],
                        "unmet_needs": [
                            "The approved profile does not provide concrete content for "
                            f"{item['observation_key']}."
                            for item in observations
                            if item["value"]["kind"] in ("UNKNOWN", "ABSTAINED")
                        ],
                        "accessibility_observations": [template.accessibility_considerations[0]],
                        "trust_concerns": [DESIGN_TRUST_CONCERN],
                        "questions": [
                            f"During human validation, does this direction support "
                            f"{twin['name']} without contradicting the approved profile "
                            f"context: {_bounded(str(context), 180)}?"
                        ],
                        "suggested_changes": [template.concern_mitigation],
                        "provenance": _unique(provenance),
                        "confidence": 0.6,
                        "epistemic_status": "MODEL_INFERRED",
                        "human_validation": "REQUIRED",
                        "rationale": DESIGN_CRITIQUE_RATIONALE,
                        "verdict": None,
                        "quote": None,
                    }
                )
            concerns.append(
                {
                    "id": self._new_id(),
                    "code": f"DRK-{ordinal:03d}",
                    "summary": template.concern_summary,
                    "mitigation": template.concern_mitigation,
                    "requirement_ids": list(grounding["requirement_ids"]),
                    "design_alternative_ids": [alternative_id],
                }
            )
        return {
            "schema_version": 1,
            "project_id": project.id,
            "grounding": copy.deepcopy(dict(grounding)),
            "alternatives": alternatives,
            "critiques": critiques,
            "recommended_alternative_id": alternatives[0]["id"],
            "owner_selected_alternative_id": None,
            "prototype": None,
            "concerns": concerns,
            "open_questions": list(DESIGN_OPEN_QUESTIONS),
            "generated_mockup": None,
            "owner_assertions": [],
        }

    def _twin_observations(
        self, project: FakeProject, twin: Mapping[str, object]
    ) -> list[Mapping[str, object]]:
        for version in project.twins.get(str(twin["twin_id"]), []):
            if version["version_number"] == twin["version_number"]:
                return list(version["profile"]["observations"])
        raise RuntimeError("the design needs the twins of its grounding")

    def _hosted_package(
        self,
        project: FakeProject,
        twins: Sequence[Mapping[str, object]],
        grounding: Mapping[str, object],
    ) -> dict[str, object]:
        requirement_ids = list(grounding["requirement_ids"])
        story_ids = list(grounding["user_story_ids"])
        criterion_ids = list(grounding["acceptance_criterion_ids"])
        texts = DESIGN_TEXTS[self.language]
        workflow_title, workflow_steps = texts["workflow"]
        alternatives = []
        fits = tuple(
            TwinFit(
                twin_id=UUID(str(twin["twin_id"])),
                name=str(twin["name"]),
                statement=texts["fit"].format(name=twin["name"]),
            )
            for twin in twins
        )
        for spec in ALTERNATIVES[self.language]:
            language = create_visual_language(
                choices=VisualChoices.from_snapshot(_choices(spec)),
                product_name=spec["product_name"],
                rationale=spec["rationale"],
                twin_fit=fits,
            )
            alternatives.append(
                {
                    "id": self._new_id(),
                    "code": spec["code"],
                    "approach": spec["approach"],
                    "title": spec["title"],
                    "summary": spec["summary"],
                    "rationale": spec["rationale"],
                    "requirement_ids": list(requirement_ids),
                    "user_story_ids": list(story_ids),
                    "acceptance_criterion_ids": list(criterion_ids),
                    "user_twin_references": copy.deepcopy(list(twins)),
                    "workflows": [
                        {
                            "id": self._new_id(),
                            "code": "FLOW-001",
                            "title": workflow_title,
                            "steps": list(workflow_steps),
                            "requirement_ids": requirement_ids[:2],
                            "user_story_ids": story_ids[:1],
                        }
                    ],
                    "information_architecture": list(texts["architecture"]),
                    "accessibility_considerations": list(texts["accessibility"]),
                    "security_considerations": list(texts["security"]),
                    "advantages": list(texts["advantages"]),
                    "trade_offs": list(texts["trade_offs"]),
                    "assumptions": list(texts["assumptions"]),
                    "open_questions": list(texts["questions"]),
                    "visual_language": language.to_snapshot(),
                }
            )
        critiques = []
        for alternative in alternatives:
            verdicts = CRITIQUES[self.language][alternative["code"]]
            for index, twin in enumerate(twins):
                verdict, quote = verdicts[index % len(verdicts)]
                critiques.append(
                    {
                        "id": self._new_id(),
                        "code": f"CRQ-{len(critiques) + 1:03d}",
                        "kind": "SYNTHETIC_USER_TWIN",
                        "design_alternative_id": alternative["id"],
                        "user_twin_reference": dict(twin),
                        "strengths": [texts["strength"]],
                        "concerns": [quote],
                        "unmet_needs": [],
                        "accessibility_observations": [],
                        "trust_concerns": [],
                        "questions": [],
                        "suggested_changes": [texts["suggestion"]],
                        "provenance": [
                            {
                                "source_kind": "MODEL_OUTPUT",
                                "source_id": alternative["id"],
                                "source_version": None,
                                "content_hash": None,
                                "locator": alternative["code"],
                                "summary": None,
                            }
                        ],
                        "confidence": 0.6,
                        "epistemic_status": "MODEL_INFERRED",
                        "human_validation": "REQUIRED",
                        "rationale": texts["rationale"],
                        "verdict": verdict,
                        "quote": quote,
                    }
                )
        concern, mitigation = texts["concern"]
        return {
            "schema_version": 1,
            "project_id": project.id,
            "grounding": copy.deepcopy(dict(grounding)),
            "alternatives": alternatives,
            "critiques": critiques,
            "recommended_alternative_id": alternatives[1]["id"],
            "owner_selected_alternative_id": None,
            "prototype": None,
            "concerns": [
                {
                    "id": self._new_id(),
                    "code": "DRK-001",
                    "summary": concern,
                    "mitigation": mitigation,
                    "requirement_ids": requirement_ids[-1:],
                    "design_alternative_ids": [alternatives[1]["id"]],
                }
            ],
            "open_questions": list(texts["questions"]),
            "generated_mockup": None,
            "owner_assertions": [],
        }

    def _append_design(
        self, project: FakeProject, package: dict[str, object], account: _Account
    ) -> dict[str, object]:
        previous = project.design
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": 1 if previous is None else int(previous["version_number"]) + 1,
            "based_on_version_number": None if previous is None else previous["version_number"],
            "content_hash": _fake_design(package).content_hash,
            "package": package,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "ready_for_gate": package["owner_selected_alternative_id"] is not None
            and package["prototype"] is not None,
        }
        project.designs.append(version)
        return version

    def _screens(self, code: str, variant: int) -> list[dict[str, object]]:
        screens = []
        for index, (screen, title, state, heading, markup) in enumerate(
            SCREENS[self.language][code]
        ):
            shown = ITERATED_HEADING[self.language] if index == 0 and variant > 0 else heading
            screens.append(
                {
                    "code": screen,
                    "title": title,
                    "state": state,
                    "markup": markup.format(heading=html.escape(shown, quote=False)),
                }
            )
        return screens

    def _generated(
        self,
        alternative: Mapping[str, object],
        variant: int,
        specification: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        language = alternative["visual_language"]
        identifiers = {
            str(item["code"]): UUID(str(item["id"])) for item in specification["requirements"]
        }

        def current_codes(match):
            codes = [code for code in match.group(2).split() if code in identifiers]
            if not codes:
                codes = [next(iter(identifiers))]
            return f" data-req={match.group(1)}{' '.join(codes)}{match.group(1)}" if codes else ""

        screens = self._screens(str(alternative["code"]), variant)
        for screen in screens:
            screen["markup"] = re.sub(r" data-req=([\"'])(.*?)\1", current_codes, screen["markup"])
        mockup = create_generated_mockup(
            design_alternative_id=UUID(str(alternative["id"])),
            title=str(language["product_name"]),
            styles=MOCKUP_STYLES,
            screens=screens,
            token_names=language["tokens"],
        )
        bound = create_bound_mockup(
            mockup=mockup,
            requirement_ids_by_code={
                code: identifiers[code] for code in markup_requirement_codes(mockup)
            },
        )
        return bound.to_snapshot(), bound.prototype().to_snapshot()

    def _mockup_package(
        self,
        project: FakeProject,
        package: Mapping[str, object],
        alternative_id: str,
        assertions: Sequence[str],
    ) -> dict[str, object]:
        result = copy.deepcopy(dict(package))
        alternative = _by_id(result["alternatives"], alternative_id)
        requirements = project.specification
        if alternative is None or requirements is None:
            raise RuntimeError("the mockup needs its alternative and requirements")
        bound, prototype = self._generated(
            alternative, project.variant, requirements["specification"]
        )
        result["owner_selected_alternative_id"] = alternative_id
        result["prototype"] = prototype
        result["generated_mockup"] = bound if self.hosted else None
        result["owner_assertions"] = list(assertions)
        return result

    def _governed_design(self, call: _Call) -> tuple[FakeProject, dict[str, object]]:
        project = self._owned(call)
        design = None if project is None else project.design
        if project is None or design is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        return project, design

    def _route_design_proposal(self, call: _Call) -> _Answer:
        return self._later(call, "DESIGN_PROPOSAL", {}, lambda: self._generated_design(call))

    def _generated_design(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        if not self._approvals(project)["requirements"]:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if project.design is not None:
            raise _Refusal(409, {"code": "DESIGN_PACKAGE_ALREADY_EXISTS"})
        if not self._has_designer(project):
            self._refuse_without_designer()
            raise _Refusal(
                409, {"code": "PROPOSAL_REJECTED", "proposal_issue": "UX_DESIGNER_REQUIRED"}
            )
        self._record(project, "DESIGN_PROPOSAL")
        version = self._append_design(project, self._design_package(project), call.account)
        return _Answer(201, _generation_payload("CREATED", version, None))

    def _has_designer(self, project: FakeProject) -> bool:
        team = project.team
        return team is not None and DESIGNER in team["selected_agent_ids"]

    def _refuse_without_designer(self) -> None:
        if self.hosted:
            raise _Refusal(502, {"code": "INVALID_PROVIDER_OUTPUT", "stage": "MODEL_PROPOSAL"})

    def _route_design_regeneration(self, call: _Call) -> _Answer:
        return self._later(call, "DESIGN_REGENERATION", {}, lambda: self._regenerated(call))

    def _regenerated(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            return _Answer(201, _generation_payload("REJECTED", None, "PROJECT_NOT_FOUND"))
        if not self._approvals(project)["requirements"]:
            return _Answer(
                201, _generation_payload("REJECTED", None, "REQUIREMENTS_APPROVAL_REQUIRED")
            )
        if project.design is None:
            return _Answer(201, _generation_payload("REJECTED", None, "DESIGN_PACKAGE_NOT_FOUND"))
        if not self._has_designer(project):
            self._refuse_without_designer()
            return _Answer(
                201,
                _generation_payload(
                    "REJECTED", None, "PROPOSAL_REJECTED", proposal_issue="UX_DESIGNER_REQUIRED"
                ),
            )
        self._record(project, "DESIGN_REGENERATION")
        version = self._append_design(project, self._design_package(project), call.account)
        return _Answer(201, _generation_payload("CREATED", version, None))

    def _route_design_current(self, call: _Call) -> _Answer:
        return _Answer(200, self._governed_design(call)[1])

    def _route_design_history(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.designs))

    def _route_design_readiness(self, call: _Call) -> _Answer:
        project = self._owned(call)
        version = None if project is None else project.design
        gate = None if project is None else project.gates.get("design")
        approved = (
            project is not None and version is not None and self._approvals(project)["design"]
        )
        if version is None:
            status = "DESIGN_REQUIRED"
        elif not version["ready_for_gate"]:
            status = "DESIGN_REVIEW_REQUIRED"
        elif approved:
            status = "READY_FOR_ARCHITECTURE_PLANNING"
        else:
            status = "DESIGN_APPROVAL_REQUIRED"
        return _Answer(
            200,
            {
                "status": status,
                "version": version,
                "gate": None if gate is None else _gate_payload(gate),
                "has_package": version is not None,
                "package_ready_for_gate": version is not None and bool(version["ready_for_gate"]),
                "approved_current_package": bool(approved),
            },
        )

    def _route_design_revision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("package",))
        package = fields.value("package")
        fields.check()
        _check_package(package)
        assert isinstance(package, dict)
        if str(UUID(str(package["project_id"]))) != call.project_id:
            raise _Refusal(422, {"code": "DESIGN_PROJECT_MISMATCH"})
        if not _coherent_package(package):
            raise _Refusal(422, {"code": "INVALID_DESIGN_PACKAGE"})
        package["project_id"] = call.project_id
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "PACKAGE_NOT_FOUND"})
        diff = self._design_diff(project, current, package, call.account)
        return _Answer(201, _design_revision_payload("CREATED", diff, None))

    def _pending_design_diff(self, project: FakeProject) -> dict[str, object] | None:
        current = project.design
        return next(
            (
                diff
                for diff in project.design_diffs
                if current is not None
                and diff["status"] == "PROPOSED"
                and diff["base_version_id"] == current["id"]
            ),
            None,
        )

    def _design_diff(
        self,
        project: FakeProject,
        current: Mapping[str, object],
        package: dict[str, object],
        account: _Account,
    ) -> dict[str, object]:
        if self._pending_design_diff(project) is not None:
            raise _Refusal(409, {"code": "DIFF_ALREADY_PENDING"})
        before = current["package"]
        if sorted(str(item["id"]) for item in before["alternatives"]) != sorted(
            str(item.get("id")) for item in package["alternatives"]
        ):
            raise _Refusal(409, {"code": "IDENTIFIER_CHANGED"})
        changes = _design_changes(before, package)
        if not changes:
            raise _Refusal(409, {"code": "NO_CHANGES"})
        diff = {
            "id": self._new_id(),
            "project_id": project.id,
            "owner_user_id": account.id,
            "base_version_id": current["id"],
            "base_version_number": current["version_number"],
            "base_content_hash": current["content_hash"],
            "proposed_package": package,
            "proposal_hash": _digest(package),
            "changes": changes,
            "status": "PROPOSED",
            "created_at": _stamp(self._now()),
            "decided_by_user_id": None,
            "decided_at": None,
            "decision_reason": None,
            "applied_version_id": None,
        }
        diff["content_hash"] = _digest(diff)
        project.design_diffs.append(diff)
        return diff

    def _route_design_revisions(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.design_diffs))

    def _route_design_revision_view(self, call: _Call) -> _Answer:
        project = self._owned(call)
        diff = _by_id([] if project is None else project.design_diffs, call.params["diff_id"])
        if diff is None:
            raise _Refusal(404, {"code": "DESIGN_DIFF_NOT_FOUND"})
        return _Answer(200, diff)

    def _route_design_revision_decision(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("decision", "reason"))
        decision = fields.choice("decision", ("APPROVE", "REJECT"))
        reason = fields.text("reason", required=False, nullable=True)
        fields.check()
        project = self._owned(call)
        diff = _by_id([] if project is None else project.design_diffs, call.params["diff_id"])
        if project is None or diff is None:
            raise _Refusal(404, {"code": "DIFF_NOT_FOUND"})
        current = project.design
        if current is None:
            raise _Refusal(404, {"code": "PACKAGE_NOT_FOUND"})
        if (current["id"], current["version_number"], current["content_hash"]) != (
            diff["base_version_id"],
            diff["base_version_number"],
            diff["base_content_hash"],
        ):
            raise _Refusal(409, {"code": "CONTEXT_CHANGED"})
        if diff["status"] != "PROPOSED":
            raise _Refusal(409, {"code": "DIFF_ALREADY_DECIDED"})
        normalized = _blank_to_none(reason)
        if decision == "REJECT" and normalized is None:
            raise _Refusal(409, {"code": "REASON_REQUIRED"})
        version = None
        if decision == "APPROVE":
            version = self._append_design(
                project, copy.deepcopy(diff["proposed_package"]), call.account
            )
            diff["applied_version_id"] = version["id"]
        diff["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
        diff["decided_by_user_id"] = call.account.id
        diff["decided_at"] = _stamp(self._now())
        diff["decision_reason"] = normalized
        diff["content_hash"] = _digest(
            {key: value for key, value in diff.items() if key != "content_hash"}
        )
        return _Answer(200, _design_revision_payload("APPLIED", diff, version))

    def _route_design_gate_submit(self, call: _Call) -> _Answer:
        project = self._owned(call)
        design = None if project is None else project.design
        if project is None or design is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if not design["ready_for_gate"]:
            raise _Refusal(409, {"code": "PACKAGE_NOT_READY"})
        status, gate, events, issue = self._submit_gate(
            project, "design", self._require_reference(project, "design")
        )
        if status not in {"SUBMITTED", "ALREADY_PENDING", "ALREADY_APPROVED"}:
            raise _Refusal(409, {"code": status})
        return _Answer(
            200,
            {
                "status": status,
                "gate": _gate_payload(gate),
                "events": [_event_payload(event) for event in events],
                "issue": issue,
            },
        )

    def _route_design_gate_decision(self, call: _Call) -> _Answer:
        action, reason = _gate_decision(call, GATE_ACTIONS, literal=False, maximum=None)
        project = self._owned(call)
        if project is None or project.design is None:
            raise _Refusal(404, {"code": "PACKAGE_NOT_FOUND"})
        return self._stage_decision(project, "design", action, reason)

    def _route_design_gate_current(self, call: _Call) -> _Answer:
        return self._stage_gate(call, "design", "DESIGN_GATE_NOT_FOUND")

    def _route_design_gate_events(self, call: _Call) -> _Answer:
        return self._stage_events(call, "design", "DESIGN_GATE_NOT_FOUND")

    def _route_mockup_capabilities(self, call: _Call) -> _Answer:
        return _Answer(
            200,
            {
                "generated_mockups": self.hosted,
                "iterations": self.hosted,
                "model": MODEL if self.hosted else None,
                "paid": self.billing != "SUBSCRIPTION",
                "static_check": False,
            },
        )

    def _route_mockup_generate(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(), ("design_version_id", "design_content_hash", "alternative_id")
        )
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        alternative_id = fields.identifier("alternative_id")
        fields.check()
        current = self._checked_design(self._owned(call), version_id, content_hash)
        if _by_id(current["package"]["alternatives"], str(alternative_id)) is None:
            raise _Refusal(422, {"code": "DESIGN_ALTERNATIVE_NOT_FOUND"})
        self._require_mockup_model()
        raise _Refusal(409, {"code": "GENERATED_MOCKUP_PATH_ACTIVE"})

    def _route_mockup_latest(self, call: _Call) -> _Answer:
        alternative_id = _query_identifier(call, "alternative_id")
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        stored = project.mockups.get(alternative_id)
        if stored is None or _by_id(current["package"]["alternatives"], alternative_id) is None:
            return _Answer(200, None)
        package = copy.deepcopy(stored["package"])
        if stored["design_content_hash"] != current["content_hash"]:
            package = _rebased(current["package"], package)
        if package["owner_selected_alternative_id"] != alternative_id:
            return _Answer(200, None)
        return _Answer(200, {**copy.deepcopy(stored), "package": package})

    def _checked_design(
        self, project: FakeProject | None, version_id: str | None, content_hash: str | None
    ) -> dict[str, object]:
        current = None if project is None else project.design
        if current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if (current["id"], current["content_hash"]) != (version_id, content_hash):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        return current

    def _grounded(self, project: FakeProject, design: Mapping[str, object]) -> bool:
        requirements = project.specification
        reference = design["package"]["grounding"]["requirements_reference"]
        return requirements is not None and (
            requirements["id"],
            requirements["content_hash"],
        ) == (reference["artifact_id"], reference["content_hash"])

    def _require_mockup_model(self) -> None:
        if not self.hosted:
            raise _Refusal(503, {"code": "REAL_MOCKUP_MODEL_NOT_CONFIGURED"})

    def _route_mockup_job(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(), ("design_version_id", "design_content_hash", "alternative_id")
        )
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        alternative_id = fields.identifier("alternative_id")
        fields.check()
        project = self._owned(call)
        current = self._checked_design(project, version_id, content_hash)
        assert project is not None
        alternative = _by_id(current["package"]["alternatives"], str(alternative_id))
        if alternative is None:
            raise _Refusal(422, {"code": "DESIGN_ALTERNATIVE_NOT_FOUND"})
        if alternative.get("visual_language") is None:
            raise _Refusal(422, {"code": "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE"})
        self._require_mockup_model()
        if not self._grounded(project, current):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        self._require_budget(project)
        job = self._start_job(
            call,
            kind="MOCKUP",
            operation="MOCKUP",
            key=f"{content_hash}:{alternative_id}",
            alternative_id=alternative_id,
            work=lambda _job: self._mockup_work(
                project, str(version_id), str(content_hash), str(alternative_id)
            ),
        )
        return _Answer(202, job.payload())

    def _mockup_work(
        self, project: FakeProject, version_id: str, content_hash: str, alternative_id: str
    ) -> dict[str, object]:
        current = project.design
        if current is None or (current["id"], current["content_hash"]) != (
            version_id,
            content_hash,
        ):
            raise _JobFailure("DESIGN_CONTEXT_CHANGED")
        if _by_id(current["package"]["alternatives"], alternative_id) is None:
            raise _JobFailure("DESIGN_ALTERNATIVE_NOT_FOUND")
        if not self._grounded(project, current):
            raise _JobFailure("DESIGN_CONTEXT_CHANGED")
        try:
            generation = self._record(project, "MOCKUP")
        except _Refusal as refusal:
            raise _JobFailure("GENERATION_BUDGET_EXCEEDED") from refusal
        package = self._mockup_package(
            project,
            current["package"],
            alternative_id,
            list(current["package"]["owner_assertions"]),
        )
        result = {
            "status": "MOCKUP_GENERATED",
            "generation_id": generation,
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "package": package,
            "approach": APPROACHES[self.language][0],
            "changes": [],
            "warnings": _mockup_warnings(package, project.specification["specification"]),
            "cost_microusd": COSTS["MOCKUP"],
        }
        project.mockups[alternative_id] = result
        return result

    def _route_mockup_job_view(self, call: _Call) -> _Answer:
        return self._read_job(call, "MOCKUP")

    def _route_mockup_document(self, call: _Call) -> _Answer:
        alternative_id = _query_identifier(call, "alternative_id")
        source = call.value("source") or "latest"
        entry_screen = call.value("entry_screen")
        if source not in ("applied", "latest"):
            raise _Invalid([_error(("query", "source"), "enum")])
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if source == "applied":
            package = current["package"]
            bound = package.get("generated_mockup")
            if bound is None or bound["mockup"]["design_alternative_id"] != alternative_id:
                raise _Refusal(404, {"code": "GENERATED_MOCKUP_NOT_FOUND"})
        else:
            stored = project.mockups.get(alternative_id)
            if stored is None or _by_id(current["package"]["alternatives"], alternative_id) is None:
                raise _Refusal(404, {"code": "GENERATED_MOCKUP_NOT_FOUND"})
            package = stored["package"]
            bound = package.get("generated_mockup")
            if bound is None:
                raise _Refusal(404, {"code": "GENERATED_MOCKUP_NOT_FOUND"})
        codes = [screen["code"] for screen in bound["mockup"]["screens"]]
        entry = codes[0] if entry_screen is None else entry_screen
        if entry not in codes:
            raise _Refusal(422, {"code": "MOCKUP_ENTRY_SCREEN_INVALID"})
        tokens = _tokens(package, alternative_id)
        mockup = generated_mockup_from_snapshot(bound["mockup"], token_names=tokens)
        document = mockup_document(
            mockup, tokens=tokens, language=_document_language(mockup), entry_screen=entry
        )
        return _Answer(
            200,
            {
                "html": document,
                "content_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
                "source": source,
                "alternative_id": alternative_id,
                "title": mockup.title,
                "entry_screen": entry,
                "screens": _screen_list(bound["mockup"]),
            },
        )

    def _route_iteration_job(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(), ("design_version_id", "design_content_hash", "request", "assertions")
        )
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        request = fields.text("request")
        assertions = fields.texts("assertions", nullable=False, default=[]) or []
        fields.check()
        text, added = _normalized_iteration(request or "", assertions)
        project = self._owned(call)
        current = self._checked_design(project, version_id, content_hash)
        assert project is not None
        package = current["package"]
        bound = package.get("generated_mockup")
        if bound is None:
            raise _Refusal(409, {"code": "GENERATED_MOCKUP_REQUIRED"})
        _merged_assertions(package["owner_assertions"], added)
        self._require_mockup_model()
        if not self._grounded(project, current):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        self._require_budget(project)
        alternative_id = str(bound["mockup"]["design_alternative_id"])
        job = self._start_job(
            call,
            kind="ITERATION",
            operation="ITERATION",
            key=str(content_hash),
            alternative_id=alternative_id,
            work=lambda job: self._iteration_work(
                job, project, str(version_id), str(content_hash), added
            ),
        )
        if not any(record["job_id"] == job.id for record in project.iterations):
            project.iterations.insert(
                0,
                {
                    "job_id": job.id,
                    "generation_id": None,
                    "requested_at": _iso(job.started_at),
                    "request": text,
                    "assertions": [
                        item for item in added if item not in package["owner_assertions"]
                    ],
                    "changes": [],
                    "failed": None,
                    "package_hash": None,
                    "base_design_version_number": current["version_number"],
                    "cost_microusd": 0,
                },
            )
        return _Answer(202, job.payload())

    def _iteration_work(
        self,
        job: _Job,
        project: FakeProject,
        version_id: str,
        content_hash: str,
        added: Sequence[str],
    ) -> dict[str, object]:
        current = project.design
        if current is None or (current["id"], current["content_hash"]) != (
            version_id,
            content_hash,
        ):
            raise _JobFailure("DESIGN_CONTEXT_CHANGED")
        package = current["package"]
        bound = package.get("generated_mockup")
        if bound is None:
            raise _JobFailure("GENERATED_MOCKUP_REQUIRED")
        try:
            merged = _merged_assertions(package["owner_assertions"], added)
        except _Refusal as refusal:
            raise _JobFailure("ITERATION_REQUEST_INVALID") from refusal
        try:
            generation = self._record(project, "ITERATION")
        except _Refusal as refusal:
            raise _JobFailure("GENERATION_BUDGET_EXCEEDED") from refusal
        project.variant += 1
        alternative_id = str(bound["mockup"]["design_alternative_id"])
        proposed = self._mockup_package(project, package, alternative_id, merged)
        changes = list(ITERATION_CHANGES[self.language])
        for record in project.iterations:
            if record["job_id"] == job.id:
                record["generation_id"] = generation
                record["changes"] = changes
                record["package_hash"] = _digest(proposed)
                record["cost_microusd"] = COSTS["ITERATION"]
        result = {
            "status": "MOCKUP_GENERATED",
            "generation_id": generation,
            "design_version_id": current["id"],
            "design_content_hash": current["content_hash"],
            "package": proposed,
            "approach": APPROACHES[self.language][1],
            "changes": changes,
            "warnings": _mockup_warnings(proposed, project.specification["specification"]),
            "cost_microusd": COSTS["ITERATION"],
        }
        project.mockups[alternative_id] = result
        return result

    def _route_iteration_job_view(self, call: _Call) -> _Answer:
        return self._read_job(call, "ITERATION")

    def _route_iterations(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            return _Answer(200, {"items": []})
        applied: dict[str, int] = {}
        for version in project.designs:
            applied.setdefault(str(version["content_hash"]), int(version["version_number"]))
        items = []
        for record in project.iterations:
            if record["generation_id"] is None and record["failed"] is None:
                continue
            number = applied.get(str(record["package_hash"]))
            if record["failed"] is not None:
                status = record["failed"]
            elif number is not None:
                status = "APPLIED"
            else:
                status = "PROPOSED"
            items.append(
                {
                    "generation_id": record["generation_id"],
                    "requested_at": record["requested_at"],
                    "request": record["request"],
                    "assertions": list(record["assertions"]),
                    "changes": list(record["changes"]),
                    "status": status,
                    "base_design_version_number": record["base_design_version_number"],
                    "applied_design_version_number": number if status == "APPLIED" else None,
                    "cost_microusd": record["cost_microusd"],
                }
            )
        return _Answer(200, {"items": items})

    def _route_evaluation(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(), ("design_version_id", "design_content_hash", "locale", "mode")
        )
        version_id = fields.identifier("design_version_id")
        content_hash = fields.digest("design_content_hash")
        locale = fields.text("locale", required=False, minimum=2, maximum=20, default="it-IT")
        mode = fields.choice("mode", ("TWIN_REVIEW", "STATIC_CHECK"), required=False, nullable=True)
        fields.check()
        body = {
            "design_version_id": version_id,
            "design_content_hash": content_hash,
            "locale": locale,
            "mode": mode,
        }
        return self._later(
            call,
            "DESIGN_EVALUATION",
            body,
            lambda: self._evaluated(call, str(version_id), str(content_hash), str(locale), mode),
        )

    def _evaluated(
        self, call: _Call, version_id: str, content_hash: str, locale: str, mode: str | None
    ) -> _Answer:
        project = self._owned(call)
        current = None if project is None else project.design
        if project is None or current is None:
            raise _Refusal(404, {"code": "DESIGN_PACKAGE_NOT_FOUND"})
        if (current["id"], current["content_hash"]) != (version_id, content_hash):
            raise _Refusal(409, {"code": "DESIGN_CONTEXT_CHANGED"})
        if mode == "STATIC_CHECK" or (mode is None and not self.hosted):
            raise _Refusal(503, {"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"})
        package = current["package"]
        if package["owner_selected_alternative_id"] is None or package["prototype"] is None:
            raise _Refusal(409, {"code": "DESIGN_PROTOTYPE_REQUIRED"})
        twins = [dict(item) for item in package["grounding"]["user_twin_references"]]
        for twin in twins:
            known = project.twins.get(str(twin["twin_id"]))
            if not known or not any(
                version["version_number"] == twin["version_number"]
                and version["content_hash"] == twin["content_hash"]
                for version in known
            ):
                raise _Refusal(409, {"code": "USER_TWIN_CONTEXT_CHANGED"})
        started = self._now()
        for _ in twins:
            self._record(project, "DESIGN_EVALUATION")
        run = self._run(project, current, twins, locale, started)
        project.runs.insert(0, run)
        return _Answer(201, run)

    def _run(
        self,
        project: FakeProject,
        version: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        started: datetime,
    ) -> dict[str, object]:
        texts = FINDINGS[self.language]
        run_id = self._new_id()
        package = version["package"]
        alternative = _by_id(package["alternatives"], str(package["owner_selected_alternative_id"]))
        if alternative is None:
            raise RuntimeError("the review needs the chosen alternative")
        scenario_name, task, outcome = texts["scenario"]
        document = f"{version['id']}:{version['content_hash']}".encode()
        bundle = {
            "id": self._new_id(),
            "project_id": project.id,
            "workflow_run_id": version["id"],
            "scenario": {
                "id": self._new_id(),
                "name": scenario_name,
                "task": task,
                "locale": locale,
                "expected_outcomes": [outcome],
            },
            "artifacts": [
                {
                    "artifact_id": version["id"],
                    "version_number": version["version_number"],
                    "kind": "DOM_SNAPSHOT",
                    "modality": "STRUCTURAL",
                    "media_type": "text/html",
                    "sha256_digest": hashlib.sha256(document).hexdigest(),
                    "size_bytes": len(document),
                    "storage_key": f"sha256/{hashlib.sha256(document).hexdigest()[:2]}/{hashlib.sha256(document).hexdigest()}",
                    "location": "design/mockup.html",
                }
            ],
            "modalities": ["STRUCTURAL"],
            "is_multimodal": False,
            "created_at": _iso(started),
        }
        bundle["content_hash"] = _digest(
            {key: bundle[key] for key in ("project_id", "workflow_run_id", "scenario", "artifacts")}
        )
        earlier = len(project.runs)
        anchors = _anchors(package["prototype"])
        responses = []
        for position, twin in enumerate(twins):
            if position < 2:
                templates = texts["first" if earlier == 0 else "later"][position]
            else:
                templates = (texts["other"],)
            findings = [
                self._finding(number, twin, version, anchors[template[0]], template[1:])
                for number, template in enumerate(templates, start=1)
            ]
            response = {
                "evaluation_run_id": run_id,
                "artifact_bundle_id": bundle["id"],
                "artifact_bundle_hash": bundle["content_hash"],
                "twin_id": twin["twin_id"],
                "twin_version": twin["version_number"],
                "evaluator": dict(EVALUATOR),
                "findings": findings,
                "summary": texts["summary"].format(name=twin["name"]),
                "evidence_gaps": [],
                "is_simulated_feedback": True,
            }
            response["content_hash"] = _digest(response)
            response["completed_at"] = _iso(self._now())
            response["disclaimer"] = DISCLAIMER
            responses.append(response)
        responses.sort(key=lambda item: str(item["twin_id"]))
        run = {
            "schema_version": 1,
            "id": run_id,
            "project_id": project.id,
            "owner_user_id": project.account.id,
            "design_version_id": version["id"],
            "design_version_number": version["version_number"],
            "design_content_hash": version["content_hash"],
            "alternative_id": alternative["id"],
            "alternative_code": alternative["code"],
            "bundle": bundle,
            "responses": responses,
            "started_at": _iso(started),
            "completed_at": _iso(self._now()),
        }
        run["content_hash"] = _digest(run)
        return run

    def _finding(
        self,
        number: int,
        twin: Mapping[str, object],
        version: Mapping[str, object],
        anchor: tuple[str, str],
        template: Sequence[str],
    ) -> dict[str, object]:
        texts = FINDINGS[self.language]
        key, location = anchor
        summary, severity, criterion = template
        finding = create_synthetic_finding(
            finding_id=f"UTF-{number:03d}",
            twin_id=UUID(str(twin["twin_id"])),
            twin_version=int(twin["version_number"]),
            artifact_id=UUID(str(version["id"])),
            artifact_version=int(version["version_number"]),
            location=" ".join(location.split()),
            summary=summary,
            rationale=texts["rationale"],
            criterion=SyntheticFindingCriterion(criterion),
            severity=SyntheticFindingSeverity(severity),
            epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            evidence_refs=(f"artifact:{version['id']}:v{version['version_number']}",),
            confidence=0.6,
            recommended_action=texts["action"],
            requires_human_validation=True,
            model_config_ref=EVALUATOR["model_config_ref"],
            prompt_version_ref=EVALUATOR["prompt_version_ref"],
        )
        return anchor_finding(finding, key).to_snapshot()

    def _route_evaluations(self, call: _Call) -> _Answer:
        project = self._owned(call)
        return _Answer(200, [] if project is None else list(project.runs))

    def _route_comparison(self, call: _Call) -> _Answer:
        project = self._owned(call)
        runs = [] if project is None else project.runs
        if not runs:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"})
        head = runs[0]
        evaluator = head["responses"][0]["evaluator"]["evaluator_id"]
        base = next(
            (
                run
                for run in runs[1:]
                if run["responses"][0]["evaluator"]["evaluator_id"] == evaluator
            ),
            None,
        )
        if base is None:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"})
        remaining = _run_findings(head)
        resolved = []
        persisting = []
        for finding in _run_findings(base):
            earlier = synthetic_finding_from_snapshot(finding)
            best, score = None, 0.0
            for candidate in remaining:
                similarity = finding_similarity(earlier, synthetic_finding_from_snapshot(candidate))
                if similarity > score:
                    best, score = candidate, similarity
            if best is not None and score >= MATCH_SIMILARITY:
                remaining.remove(best)
                persisting.append({"before": finding, "after": best})
            else:
                resolved.append(finding)
        return _Answer(
            200,
            {
                "base_run_id": base["id"],
                "head_run_id": head["id"],
                "resolved": resolved,
                "persisting": persisting,
                "introduced": remaining,
                "counts": {
                    "base": len(resolved) + len(persisting),
                    "head": len(remaining) + len(persisting),
                    "resolved": len(resolved),
                    "persisting": len(persisting),
                    "introduced": len(remaining),
                    "dismissed": 0,
                },
            },
        )

    def _review(self, call: _Call) -> tuple[dict[str, object], dict[str, object]]:
        project = self._owned(call)
        run = None if project is None else _by_id(project.runs, call.params["run_id"])
        if project is None or run is None:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_NOT_FOUND"})
        version = _by_id(project.designs, str(run["design_version_id"]))
        if version is None or version["content_hash"] != run["design_content_hash"]:
            raise _Refusal(404, {"code": "DESIGN_EVALUATION_NOT_FOUND"})
        if version["package"].get("generated_mockup") is None:
            raise _Refusal(409, {"code": "GENERATED_MOCKUP_REQUIRED"})
        return run, version

    def _route_review_pins(self, call: _Call) -> _Answer:
        run, version = self._review(call)
        return _Answer(200, _pins(run, version))

    def _route_review_document(self, call: _Call) -> _Answer:
        entry_screen = call.value("entry_screen")
        if entry_screen is not None and ENTRY_SCREEN_PATTERN.fullmatch(entry_screen) is None:
            raise _Invalid([_error(("query", "entry_screen"), "string_pattern_mismatch")])
        run, version = self._review(call)
        pins = _pins(run, version)
        bound = version["package"]["generated_mockup"]
        snapshot = bound["mockup"]
        codes = [screen["code"] for screen in snapshot["screens"]]
        entry = codes[0] if entry_screen is None else entry_screen
        if entry not in codes:
            raise _Refusal(422, {"code": "ENTRY_SCREEN_NOT_FOUND"})
        tokens = _tokens(version["package"], str(snapshot["design_alternative_id"]))
        mockup = generated_mockup_from_snapshot(snapshot, token_names=tokens)
        locale = str(run["bundle"]["scenario"]["locale"])
        document = mockup_document(
            mockup,
            tokens=tokens,
            language=locale if LANGUAGE_TAG.fullmatch(locale) else REVIEW_LANGUAGE,
            pins=tuple(
                MockupPin(
                    element_code=pin["element_code"], number=pin["number"], label=pin["label"]
                )
                for pin in pins["pins"]
            ),
            entry_screen=entry,
        )
        return _Answer(
            200,
            {
                "html": document,
                "content_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
                "source": "review",
                "alternative_id": snapshot["design_alternative_id"],
                "title": mockup.title,
                "entry_screen": entry,
                "screens": _screen_list(snapshot),
            },
        )

    def _route_jobs(self, call: _Call) -> _Answer:
        status = call.value("status")
        if status is not None and status not in JOB_STATUSES:
            raise _Invalid([_error(("query", "status"), "enum")])
        jobs = [
            job
            for job in self._jobs.values()
            if job.owner == call.account.id
            and job.project_id == call.project_id
            and not job.lost
            and (status is None or job.status == status)
        ]
        jobs.sort(key=lambda job: job.started_at)
        return _Answer(200, {"items": [job.payload() for job in jobs]})

    def _route_job(self, call: _Call) -> _Answer:
        return self._read_job(call, None)

    def _sections(self, project: FakeProject) -> dict[str, object]:
        return self._project_sections(project).to_snapshot()

    def _project_sections(self, project: FakeProject, *, learning: bool = True) -> ProjectSections:
        facts = self._section_facts(project)
        draft = project_sections(facts)
        twins = facts.user_twins
        if (
            learning
            and twins is not None
            and draft.section(ProjectStage.USER_TWINS).state is SectionState.FINE
        ):
            facts = replace(facts, user_twins=replace(twins, learned=self._twins_learned(project)))
        design = draft.section(ProjectStage.DESIGN)
        current, requirements = project.design, project.specification
        if (
            facts.design is not None
            and current is not None
            and requirements is not None
            and design.state in DESIGN_ALIGNMENT_STATES
            and design.blocked is not SectionBlock.UPSTREAM_NOT_READY
        ):
            facts = replace(
                facts,
                design=replace(
                    facts.design,
                    missing_codes=tuple(self._missing_codes(project, current, requirements)),
                    uncovered_codes=tuple(self._uncovered_codes(current, requirements)),
                ),
            )
        return project_sections(facts)

    def _section_facts(self, project: FakeProject) -> SectionFacts:
        brief = project.artifact("brief")
        team, snapshot = project.team, project.snapshot
        requirements, design = project.specification, project.design
        return SectionFacts(
            brief=None
            if brief is None
            else BriefFacts(
                version=_artifact_version(brief), approved=self._gate_approved(project, "brief")
            ),
            team=None
            if team is None
            else TeamFacts(
                version=_artifact_version(team),
                approved=self._gate_approved(project, "team"),
                brief=_team_brief_version(team),
                alignable=self._team_alignment_issue(project) is None,
            ),
            user_twins=None if snapshot is None else self._twins_facts(project, snapshot),
            requirements=None
            if requirements is None
            else self._requirements_facts(project, requirements),
            design=None if design is None else self._design_facts(project, design),
            folder=None
            if not project.packages
            else FolderFacts(
                version_number=int(project.packages[-1]["version_number"]),
                stages={
                    FOLDER_SECTIONS[stage]: held for stage, held in project.folders[-1].items()
                },
            ),
            design_approved_once=self._first_pass_complete(project),
        )

    def _twins_facts(self, project: FakeProject, snapshot: Mapping[str, object]) -> UserTwinsFacts:
        body = snapshot["snapshot"]
        return UserTwinsFacts(
            version=_artifact_version(snapshot),
            approved=self._gate_approved(project, "twins"),
            brief=_reference_version(body["project_brief_reference"]),
            team=_reference_version(body["agent_team_reference"]),
            twins=_twin_versions(body["twin_versions"]),
            archetypes_current=self._archetypes_current(project, snapshot),
        )

    def _requirements_facts(
        self, project: FakeProject, version: Mapping[str, object]
    ) -> RequirementsFacts:
        specification = version["specification"]
        return RequirementsFacts(
            version=_artifact_version(version),
            approved=self._gate_approved(project, "requirements"),
            brief=_reference_version(specification["project_brief_reference"]),
            team=_reference_version(specification["agent_team_reference"]),
            user_modeling=_reference_version(specification["user_modeling_reference"]),
            twins=_twin_versions(specification["user_twin_references"]),
            cited_twin_ids=frozenset(
                UUID(identifier) for identifier in _referenced_twins(specification)
            ),
            revision_pending=self._pending_requirements_diff(project) is not None,
            actor_codes=requirements_actor_codes(_fake_requirements(specification)),
        )

    def _design_facts(self, project: FakeProject, version: Mapping[str, object]) -> DesignFacts:
        package = version["package"]
        grounding = package["grounding"]
        has_mockup = (
            package["owner_selected_alternative_id"] is not None
            and package["prototype"] is not None
        )
        return DesignFacts(
            version=_artifact_version(version),
            approved=self._gate_approved(project, "design"),
            requirements=_reference_version(grounding["requirements_reference"]),
            team=_reference_version(grounding["agent_team_reference"]),
            user_modeling=_reference_version(grounding["user_modeling_reference"]),
            twins=_twin_versions(grounding["user_twin_references"]),
            revision_pending=self._pending_design_diff(project) is not None,
            has_mockup=has_mockup,
            reviewed=has_mockup
            and any(run["design_version_id"] == version["id"] for run in project.runs),
        )

    def _first_pass_complete(self, project: FakeProject) -> bool:
        return any(
            event.resulting_status is HumanGateStatus.APPROVED
            and event.artifact.gate_type is HumanGateType.DESIGN
            for events in project.gate_events.values()
            for event in events
        )

    def _twins_learned(self, project: FakeProject) -> bool:
        return any(
            self._pending_update(project, str(twin["twin_id"])) is not None
            or (self.hosted and any(self._new_material(project, str(twin["twin_id"]))))
            for twin in self._approved_twins(project)
        )

    def _grounded_requirements(
        self, project: FakeProject, design: Mapping[str, object]
    ) -> dict[str, object] | None:
        reference = design["package"]["grounding"]["requirements_reference"]
        return _by_id(project.requirements, str(reference["artifact_id"]))

    def _missing_codes(
        self,
        project: FakeProject,
        design: Mapping[str, object],
        requirements: Mapping[str, object],
    ) -> list[str]:
        grounded = self._grounded_requirements(project, design)
        if grounded is None:
            return []
        cited = _cited_ids(design["package"])
        current = {
            str(item["id"])
            for kind in SPECIFICATION_ITEMS
            for item in requirements["specification"][kind]
        }
        return [
            code
            for kind in SPECIFICATION_ITEMS
            for code in sorted(
                str(item["code"])
                for item in grounded["specification"][kind]
                if str(item["id"]) in cited and str(item["id"]) not in current
            )
        ]

    def _uncovered_codes(
        self, design: Mapping[str, object], requirements: Mapping[str, object]
    ) -> list[str]:
        prototype = design["package"].get("prototype")
        if prototype is None:
            return []
        cited = {
            str(identifier)
            for screen in prototype["screens"]
            for holder in (screen, *screen["elements"])
            for identifier in holder["requirement_ids"]
        }
        return sorted(
            str(item["code"])
            for item in requirements["specification"]["requirements"]
            if str(item["id"]) not in cited
        )

    def _route_sections(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        document = self._sections(project)
        if project.workflow_decisions or project.provided_prototypes:
            document = {**document, "workflow_inputs": self._workflow_inputs(project)}
        return _Answer(200, document)

    def _route_align_sections(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        answer = self._aligned_sections(project, call.account)
        project.gestures.append(_copy(answer))
        return _Answer(200, answer)

    def _aligned_sections(self, project: FakeProject, account: _Account) -> dict[str, object]:
        before = self._project_sections(project, learning=False)
        results: list[dict[str, object]] = []
        for key in before.alignment.sections:
            if results and results[-1]["outcome"] != "ALIGNED":
                results.append(_alignment_result(key.value, "SKIPPED"))
                continue
            section = before.section(key)
            if section.blocked is not None:
                results.append(
                    _alignment_result(
                        key.value,
                        "BLOCKED",
                        issue=_gesture_issue(section.blocked.value),
                        codes=section.codes,
                    )
                )
                continue
            results.append(self._update_section(project, key.value, account))
        return {
            "status": _gesture_status(results),
            "results": results,
            "sections": self._sections(project),
        }

    def _update_section(
        self, project: FakeProject, key: str, account: _Account
    ) -> dict[str, object]:
        stage = SECTION_STAGES[key]
        gate = project.gates.get(stage)
        if gate is not None and next_human_gate_iteration(gate) is None:
            return _alignment_result(key, "BLOCKED", issue="ITERATION_LIMIT_REACHED")
        realign = {
            "TEAM": self._realign_team,
            "USER_TWINS": self._realign_twins,
            "REQUIREMENTS": self._realign_requirements,
            "DESIGN": self._realign_design,
        }[key]
        try:
            realign(project, account)
        except _Refusal as refusal:
            code, missing = _refusal_code(refusal)
            return _alignment_result(key, "BLOCKED", issue=_gesture_issue(code), codes=missing)
        reference = self._require_reference(project, stage)
        submitted, current, _, _ = self._submit_gate(project, stage, reference)
        if submitted == "ALREADY_APPROVED" and current is not None:
            return _alignment_result(key, "ALIGNED", version_number=current.artifact.version)
        if submitted not in ("SUBMITTED", "ALREADY_PENDING"):
            return _alignment_result(key, "BLOCKED", issue=_gesture_issue(submitted))
        status, decided, _, issue = self._decide_gate(
            project, stage, reference, "APPROVE", ALIGNMENT_REASON
        )
        if status != "APPLIED" or decided is None:
            return _alignment_result(key, "BLOCKED", issue=_gesture_issue(issue or status))
        return _alignment_result(key, "ALIGNED", version_number=decided.artifact.version)

    def _twins_alignment_issue(self, project: FakeProject | None) -> str | None:
        if project is None or project.snapshot is None:
            return "USER_TWINS_NOT_FOUND"
        approvals = self._approvals(project)
        if not approvals["brief"]:
            return "BRIEF_APPROVAL_REQUIRED"
        if not approvals["team"]:
            return "TEAM_APPROVAL_REQUIRED"
        if not self._archetypes_current(project, project.snapshot):
            return "ARCHETYPES_CHANGED"
        if any(update["status"] == "PROPOSED" for update in project.updates):
            return "USER_TWIN_REVISION_PENDING"
        if self._snapshot_current(project, project.snapshot):
            return "ALREADY_ALIGNED"
        return None

    def _route_twins_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        issue = self._twins_alignment_issue(project)
        snapshot = None if project is None else project.snapshot
        brief = None if project is None else project.brief
        team = None if project is None else project.team
        return _Answer(
            200,
            {
                "aligned": issue == "ALREADY_ALIGNED",
                "issue": issue,
                "snapshot_version_number": None if snapshot is None else snapshot["version_number"],
                "brief_version_number": None if brief is None else brief.number,
                "team_version_number": None if team is None else team["version_number"],
            },
        )

    def _route_realign_twins(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "USER_TWINS_NOT_FOUND"})
        version = self._realign_twins(project, call.account)
        return _Answer(
            201,
            {
                "snapshot_version_id": version["id"],
                "snapshot_version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "twin_count": len(version["snapshot"]["twin_versions"]),
                "gate_approval_required": True,
            },
        )

    def _realign_twins(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._twins_alignment_issue(project)
        if issue is not None:
            raise _Refusal(404 if issue == "USER_TWINS_NOT_FOUND" else 409, {"code": issue})
        snapshot, brief, team = project.snapshot, project.brief, project.team
        brief_reference = {
            "artifact_id": brief.id,
            "version_number": brief.number,
            "content_hash": brief.content_hash,
        }
        team_reference = _plain_reference(team)
        twins = []
        for twin in snapshot["snapshot"]["twin_versions"]:
            versions = project.twins[str(twin["twin_id"])]
            previous = int(versions[-1]["version_number"])
            profile = copy.deepcopy(twin["profile"])
            profile["project_brief_reference"] = dict(brief_reference)
            profile["agent_team_reference"] = dict(team_reference)
            profile["catalog_version"] = AGENT_CATALOG_VERSION
            profile["catalog_content_hash"] = AGENT_CATALOG_CONTENT_HASH
            version = {
                "id": self._new_id(),
                "project_id": project.id,
                "twin_id": twin["twin_id"],
                "version_number": previous + 1,
                "based_on_version_number": previous,
                "content_hash": _fake_twin_profile(profile).content_hash,
                "created_by_user_id": account.id,
                "created_at": _stamp(self._now()),
                "profile": profile,
            }
            versions.append(version)
            twins.append(version)
        twins.sort(key=lambda item: str(item["twin_id"]))
        body = copy.deepcopy(snapshot["snapshot"])
        body["project_brief_reference"] = brief_reference
        body["agent_team_reference"] = team_reference
        body["catalog_version"] = AGENT_CATALOG_VERSION
        body["catalog_content_hash"] = AGENT_CATALOG_CONTENT_HASH
        body["twin_versions"] = twins
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "version_number": int(snapshot["version_number"]) + 1,
            "based_on_version_number": snapshot["version_number"],
            "content_hash": _fake_modeling(body).content_hash,
            "created_by_user_id": account.id,
            "created_at": _stamp(self._now()),
            "snapshot": body,
        }
        project.snapshots.append(version)
        return version

    def _requirements_alignment_issue(self, project: FakeProject | None) -> str | None:
        current = None if project is None else project.specification
        if project is None or current is None:
            return "REQUIREMENTS_NOT_FOUND"
        snapshot = project.snapshot
        if snapshot is None:
            return "USER_TWINS_REQUIRED"
        if not self._approvals(project)["twins"]:
            return "USER_TWINS_APPROVAL_REQUIRED"
        specification = current["specification"]
        if _requirements_aligned(specification, snapshot):
            return "REQUIREMENTS_ALREADY_ALIGNED"
        if not _referenced_twins(specification) <= _twin_ids(snapshot["snapshot"]["twin_versions"]):
            return "TWIN_NO_LONGER_AVAILABLE"
        if self._pending_requirements_diff(project) is not None:
            return "REQUIREMENTS_REVISION_PENDING"
        return None

    def _route_requirements_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        current = None if project is None else project.specification
        snapshot = None if project is None else project.snapshot
        return _Answer(
            200,
            {
                "aligned": current is not None
                and snapshot is not None
                and _requirements_aligned(current["specification"], snapshot),
                "issue": self._requirements_alignment_issue(project),
                "requirements_version_number": None
                if current is None
                else current["version_number"],
                "snapshot_version_number": None if snapshot is None else snapshot["version_number"],
                "twins_approved": project is not None and self._approvals(project)["twins"],
            },
        )

    def _route_realign_requirements(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "REQUIREMENTS_NOT_FOUND"})
        version = self._realign_requirements(project, call.account)
        specification = version["specification"]
        return _Answer(
            201,
            {
                "version_id": version["id"],
                "version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "user_modeling_version_number": specification["user_modeling_reference"][
                    "version_number"
                ],
                "twin_count": len(specification["user_twin_references"]),
                "gate_approval_required": True,
            },
        )

    def _realign_requirements(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._requirements_alignment_issue(project)
        if issue is not None:
            raise _Refusal(404 if issue == "REQUIREMENTS_NOT_FOUND" else 409, {"code": issue})
        snapshot = project.snapshot
        body = snapshot["snapshot"]
        specification = copy.deepcopy(project.specification["specification"])
        twins = [_twin_reference(twin) for twin in body["twin_versions"]]
        current = {str(twin["twin_id"]): twin for twin in twins}
        specification["project_brief_reference"] = {
            "kind": "PROJECT_BRIEF",
            **_reference_fields(body["project_brief_reference"]),
        }
        specification["agent_team_reference"] = {
            "kind": "AGENT_TEAM",
            **_reference_fields(body["agent_team_reference"]),
        }
        specification["user_modeling_reference"] = {
            "kind": "USER_MODELING",
            **_plain_reference(snapshot),
        }
        specification["catalog_version"] = body["catalog_version"]
        specification["catalog_content_hash"] = body["catalog_content_hash"]
        specification["user_twin_references"] = twins
        for requirement in specification["requirements"]:
            requirement["user_twin_references"] = _sorted_twins(
                current[str(reference["twin_id"])]
                for reference in requirement["user_twin_references"]
            )
        for story in specification["user_stories"]:
            story["user_twin_reference"] = dict(
                current[str(story["user_twin_reference"]["twin_id"])]
            )
        for scenario in specification["scenarios"]:
            scenario["actor"] = dict(current[str(scenario["actor"]["twin_id"])])
        return self._append_requirements(project, specification, account)

    def _design_alignment_issue(self, project: FakeProject | None) -> str | None:
        design = None if project is None else project.design
        if project is None or design is None:
            return "DESIGN_NOT_FOUND"
        requirements = project.specification
        if requirements is None or not self._gate_approved(project, "requirements"):
            return "REQUIREMENTS_APPROVAL_REQUIRED"
        if _design_aligned(design, requirements):
            return "ALREADY_ALIGNED"
        if self._missing_codes(project, design, requirements):
            return "REQUIREMENT_NO_LONGER_AVAILABLE"
        if _twin_ids(design["package"]["grounding"]["user_twin_references"]) != _twin_ids(
            requirements["specification"]["user_twin_references"]
        ):
            return "TWIN_SET_CHANGED"
        if self._pending_design_diff(project) is not None:
            return "DESIGN_REVISION_PENDING"
        return None

    def _route_design_alignment(self, call: _Call) -> _Answer:
        project = self._owned(call)
        design = None if project is None else project.design
        requirements = None if project is None else project.specification
        known = design is not None and requirements is not None
        grounding = None if design is None else design["package"]["grounding"]
        return _Answer(
            200,
            {
                "aligned": known and _design_aligned(design, requirements),
                "issue": self._design_alignment_issue(project),
                "design_version_number": None if design is None else design["version_number"],
                "grounded_requirements_version_number": None
                if grounding is None
                else grounding["requirements_reference"]["version_number"],
                "requirements_version_number": None
                if requirements is None
                else requirements["version_number"],
                "missing_codes": self._missing_codes(project, design, requirements)
                if known
                else [],
                "uncovered_codes": self._uncovered_codes(design, requirements) if known else [],
            },
        )

    def _route_realign_design(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "DESIGN_NOT_FOUND"})
        version = self._realign_design(project, call.account)
        requirements = project.specification
        return _Answer(
            201,
            {
                "version_id": version["id"],
                "version_number": version["version_number"],
                "based_on_version_number": version["based_on_version_number"],
                "content_hash": version["content_hash"],
                "requirements_version_number": requirements["version_number"],
                "gate_approval_required": True,
                "uncovered_codes": self._uncovered_codes(version, requirements),
            },
        )

    def _realign_design(self, project: FakeProject, account: _Account) -> dict[str, object]:
        issue = self._design_alignment_issue(project)
        if issue == "REQUIREMENT_NO_LONGER_AVAILABLE":
            missing = self._missing_codes(project, project.design, project.specification)
            raise _Refusal(409, {"code": issue, "missing_codes": missing})
        if issue is not None:
            raise _Refusal(404 if issue == "DESIGN_NOT_FOUND" else 409, {"code": issue})
        requirements = project.specification
        specification = requirements["specification"]
        twins = {str(twin["twin_id"]): twin for twin in specification["user_twin_references"]}
        package = copy.deepcopy(project.design["package"])
        package["grounding"] = _requirements_grounding(requirements)
        for alternative in package["alternatives"]:
            alternative["user_twin_references"] = [
                dict(twins[str(reference["twin_id"])])
                for reference in alternative["user_twin_references"]
            ]
        for critique in package["critiques"]:
            twin_id = str(critique["user_twin_reference"]["twin_id"])
            critique["user_twin_reference"] = dict(twins[twin_id])
        return self._append_design(project, package, account)

    def _publishable(self, project: FakeProject) -> list[str]:
        present = list(
            itertools.takewhile(lambda stage: self._gate_approved(project, stage), STAGES)
        )
        if "twins" in present and not self._archetypes_current(project, project.snapshot):
            return present[:2]
        if project.evidence_versions:
            for position in range(1, len(present) + 1):
                if self._folder_issue(project, present[:position]) is not None:
                    return present[: position - 1]
        return present

    def _folder_issue(self, project: FakeProject, present: Sequence[str]) -> str | None:
        keys = {stage: _key(project.artifact(stage)) for stage in present}
        brief, team, twins = (keys.get(stage) for stage in ("brief", "team", "twins"))
        if "team" in keys and _team_brief(project.team) != brief:
            return "TEAM_OUTDATED"
        if "twins" in keys:
            body = project.snapshot["snapshot"]
            if (
                _reference_key(body["project_brief_reference"]),
                _reference_key(body["agent_team_reference"]),
            ) != (brief, team):
                return "USER_TWINS_OUTDATED"
        if "requirements" in keys:
            context = project.specification["specification"]
            if (
                _reference_key(context["project_brief_reference"]),
                _reference_key(context["agent_team_reference"]),
                _reference_key(context["user_modeling_reference"]),
            ) != (brief, team, twins):
                return "REQUIREMENTS_OUTDATED"
        if "design" in keys:
            grounding = project.design["package"]["grounding"]
            if (
                _reference_key(grounding["requirements_reference"]),
                _reference_key(grounding["agent_team_reference"]),
                _reference_key(grounding["user_modeling_reference"]),
            ) != (keys["requirements"], team, twins):
                return "DESIGN_OUTDATED"
        return None

    def _route_publish(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        if not self._gate_approved(project, "brief"):
            raise _Refusal(409, {"code": "BRIEF_APPROVAL_REQUIRED"})
        present = self._publishable(project)
        issue = self._folder_issue(project, present)
        if issue is not None:
            raise _Refusal(409, {"code": issue})
        fingerprint = (
            *(str(project.artifact(stage)["id"]) for stage in present),
            f"changes={len(project.code_changes)}",
            f"runs={len(project.change_runs)}",
            f"decisions={project.decision_count}",
            f"tests={len(project.acceptance_runs)}",
            f"test_reviews={len(project.acceptance_reviews)}",
            f"tasks={_digest(project.code_tasks)}",
            f"learning={_digest(project.development)}",
        )
        if project.packages and project.fingerprint == fingerprint:
            return _Answer(200, {"reused": True, "version": project.packages[-1]})
        number = len(project.packages) + 1
        created_at = self._now()
        folder = self._knowledge_folder(project, present, number, created_at)
        archive = folder_archive(folder)
        manifest = folder.manifest
        views = [view for view in manifest["views"].values() if view]
        stages = [stage for stage in STAGES if manifest["stages"].get(stage)]
        version = {
            "id": self._new_id(),
            "project_id": project.id,
            "project_name": manifest["project"]["name"],
            "version_number": number,
            "schema_version": manifest["schema_version"],
            "content_hash": folder.content_hash,
            "archive_hash": archive.archive_hash,
            "file_name": f"orchestwin-{project.id}-knowledge-v{number}.zip",
            "file_count": len(archive.entries),
            "archive_size": len(archive.content),
            "created_at": _stamp(created_at),
            "stages": [
                {
                    "stage": stage,
                    "label": manifest["stages"][stage]["label"],
                    "version_number": manifest["stages"][stage]["version_number"],
                    "content_hash": manifest["stages"][stage]["content_hash"],
                }
                for stage in stages
            ],
            "progress": {
                "approved": list(manifest["progress"]["approved"]),
                "pending": manifest["progress"]["pending"],
                "complete": manifest["progress"]["complete"],
            },
            "state": {
                key: manifest["state"][key] for key in STATE_KEYS if key in manifest["state"]
            },
            "twins": [
                {
                    "twin_id": twin["twin_id"],
                    "name": twin["name"],
                    "slug": twin["slug"],
                    "version_number": twin["version_number"],
                    "document": twin["document"],
                }
                for twin in manifest["twins"]
            ],
            "feedback": {
                key: manifest["feedback"][key]
                for key in FEEDBACK_KEYS
                if key in manifest["feedback"]
            },
            "diagram_count": sum(len(view["diagrams"]) for view in views),
            "table_count": sum(len(view["tables"]) for view in views),
            "entries": list(archive.entries),
        }
        project.packages.append(version)
        project.folders.append(
            {stage: _artifact_version(project.artifact(stage)) for stage in present}
        )
        project.archives[number] = archive.content
        project.fingerprint = fingerprint
        return _Answer(201, {"reused": False, "version": version})

    def _route_package_history(self, call: _Call) -> _Answer:
        raw_limit = call.value("limit")
        limit = 50
        if raw_limit is not None:
            if re.fullmatch(r"[0-9]+", raw_limit) is None:
                raise _Invalid([_error(("query", "limit"), "int_parsing")])
            limit = int(raw_limit)
            if limit < 1:
                raise _Invalid([_error(("query", "limit"), "greater_than_equal")])
            if limit > 200:
                raise _Invalid([_error(("query", "limit"), "less_than_equal")])
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        return _Answer(
            200,
            {"project_id": call.project_id, "versions": list(reversed(project.packages))[:limit]},
        )

    def _route_package_archive(self, call: _Call) -> _Answer:
        number = int(call.params["version_number"])
        if number < 1:
            raise _Invalid([_error(("path", "version_number"), "greater_than_equal")])
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        content = project.archives.get(number)
        if content is None:
            raise _Refusal(404, {"code": "KNOWLEDGE_PACKAGE_NOT_FOUND"})
        version = project.packages[number - 1]
        return _Answer(
            200,
            raw=content,
            content_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{version["file_name"]}"',
                "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
            },
        )

    def _route_import_project(self, call: _Call) -> _Answer:
        declared = call.headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > MAX_ARCHIVE_SIZE + 64 * 1024:
            raise _Refusal(413, {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None})
        form = _multipart(call.headers.get("content-type", ""), call.raw)
        archive = form.get("archive")
        if archive is None or archive[0] is None:
            raise _Invalid([_error(("body", "archive"), "missing")])
        content = archive[1]
        if len(content) > MAX_ARCHIVE_SIZE:
            raise _Refusal(413, {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None})
        display = form.get("display_name")
        given = None if display is None else display[1].decode("utf-8", "replace")
        try:
            verified = read_verified_folder(content)
        except KnowledgeArchiveError as error:
            status = 413 if error.code == "FOLDER_ARCHIVE_TOO_LARGE" else 422
            raise _Refusal(status, {"code": error.code, "location": error.detail}) from error
        missing = [stage for stage in STAGES if not verified.manifest["stages"].get(stage)]
        if missing:
            raise _Refusal(422, {"code": "FOLDER_INCOMPLETE", "location": missing[0]})
        source_name = verified.project_name
        if not 1 <= len(source_name) <= MAX_SOURCE_NAME:
            raise _Refusal(
                422,
                {"code": "FOLDER_DOCUMENT_INVALID", "location": "orchestwin.json: project.name"},
            )
        name = " ".join((given or "").split())
        if name and len(name) > MAX_PROJECT_NAME:
            raise _Refusal(422, {"code": "PROJECT_NAME_INVALID", "location": "display_name"})
        if not name:
            name = " ".join(source_name.split())[:MAX_PROJECT_NAME].rstrip()
        if not name:
            raise _Refusal(422, {"code": "PROJECT_NAME_INVALID", "location": "display_name"})
        try:
            mode = str(verified.documents["team"]["proposal"]["project_mode"])
        except (KeyError, TypeError) as error:
            raise _Refusal(
                422, {"code": "FOLDER_DOCUMENT_INVALID", "location": "team: project_mode"}
            ) from error
        if mode not in PROJECT_MODES:
            raise _Refusal(
                422, {"code": "FOLDER_DOCUMENT_INVALID", "location": "team: project_mode"}
            )
        project = self._new_project(call.account, name, mode)
        self._seed(project, "design", approve=False)
        imported_at = self._now()
        plan = None
        if "twins/evidence.json" in verified.files or "why" in verified.manifest:
            from orchestwin.api.design import DesignPackagePayload
            from orchestwin.api.teams import TeamProposalVersionResponse
            from orchestwin.api.user_modeling import UserModelingSnapshotVersionPayload

            try:
                plan = plan_project_import(
                    verified,
                    project_id=UUID(project.id),
                    brief_version_id=UUID(self._new_id()),
                    owner_user_id=UUID(call.account.id),
                    created_at=imported_at,
                )
            except KnowledgeArchiveError as error:
                self._projects.pop(project.id, None)
                raise _Refusal(422, {"code": error.code, "location": error.detail}) from None
            documents = plan_documents(
                plan, owner_user_id=UUID(call.account.id), created_at=imported_at
            )
            project.briefs = [_BriefVersion(documents["brief"], plan.brief)]
            project.teams = [
                TeamProposalVersionResponse.from_domain(plan.team).model_dump(mode="json")
            ]
            project.snapshots = [
                UserModelingSnapshotVersionPayload.from_domain(plan.modeling).model_dump(
                    mode="json"
                )
            ]
            project.personas = {
                item["persona_id"]: [item]
                for item in project.snapshot["snapshot"]["persona_versions"]
            }
            project.twins = {
                item["twin_id"]: [item] for item in project.snapshot["snapshot"]["twin_versions"]
            }
            project.requirements = [
                {
                    **documents["requirements"],
                    "specification": RequirementsSpecificationPayload.from_domain(
                        plan.requirements.specification
                    ).model_dump(mode="json"),
                }
            ]
            project.designs = [
                {
                    **documents["design"],
                    "package": DesignPackagePayload.from_domain(plan.design.package).model_dump(
                        mode="json"
                    ),
                }
            ]
            project.gates = {}
            project.gate_events = {}
            project.mockups = {}
            project.runs = [item.to_snapshot() for item in plan.evaluations]
            project.finding_decisions = [item.to_snapshot() for item in plan.finding_decisions]
            project.validation_hypotheses = copy.deepcopy(
                (plan.validation_records or {}).get("hypotheses", [])
            )
            project.validation_outcomes = copy.deepcopy(
                (plan.validation_records or {}).get("outcomes", [])
            )
            project.evidence_versions = copy.deepcopy(
                (plan.research_evidence or {}).get("evidence", [])
            )
            for item in (plan.research_evidence or {}).get("citations", []):
                twin = next(
                    (twin for twin in plan.twins if str(twin.twin_id) == item["twin_id"]), None
                )
                observation = next(
                    (
                        observation
                        for observation in (() if twin is None else twin.profile.observations)
                        if observation.observation_key == f"user_twin.{item['field']}"
                    ),
                    None,
                )
                citation = item["citation"]
                project.evidence_changes.append(
                    {
                        "twin_id": item["twin_id"],
                        "twin_version": item["twin_version"],
                        "field": item["field"],
                        "source_id": citation["source_id"],
                        "source_version": citation["source_version"],
                        "change": {
                            "effect": item["effect"],
                            "field": item["field"],
                            **(
                                {"value": observation.value.to_snapshot()}
                                if observation is not None
                                else {"historical_only": True}
                            ),
                            "citation": copy.deepcopy(citation),
                            **(
                                {"imported_from": copy.deepcopy(item["imported_from"])}
                                if item.get("imported_from") is not None
                                else {}
                            ),
                        },
                        "before": None,
                        "after": observation.to_snapshot()
                        if observation is not None
                        else {"kind": "historical-citation", "profile_available": False},
                        "retired_at": None if item["status"] == "ACTIVE" else _iso(imported_at),
                    }
                )
        if plan is not None and "why" in verified.manifest:
            from orchestwin.knowledge.why import importable_why, normalized_why

            original = importable_why(verified, plan.omitted_sections)
            if normalized_why(
                original, identities=plan.identities, hashes=plan.hashes
            ) != normalized_why(self._why_document(project)):
                self._projects.pop(project.id, None)
                raise _Refusal(
                    422, {"code": "FOLDER_WHY_MISMATCH", "location": "exported derivation"}
                )
        stages = {
            stage: {
                "version_id": project.artifact(stage)["id"],
                "version_number": project.artifact(stage)["version_number"],
                "content_hash": project.artifact(stage)["content_hash"],
            }
            for stage in STAGES
        }
        origin = {
            "project_id": verified.project_id,
            "project_name": source_name,
            "package_version": verified.package_version,
            "package_content_hash": verified.content_hash,
            "schema_version": verified.manifest["schema_version"],
        }
        project.origin = {
            "origin": origin,
            "stages": stages,
            "imported_at": _stamp(imported_at),
            "archive_hash": hashlib.sha256(content).hexdigest(),
        }
        if plan is not None and plan.import_limits:
            project.origin["import_limits"] = list(plan.import_limits)
        if plan is not None and plan.omitted_sections:
            project.origin["omitted_sections"] = list(plan.omitted_sections)
        twins = project.snapshot["snapshot"]["twin_versions"] if project.snapshot else []
        return _Answer(
            201,
            {
                "project": {
                    "id": project.id,
                    "display_name": project.name,
                    "mode": project.mode,
                    "created_at": _stamp(project.created_at),
                },
                "origin": origin,
                "stages": stages,
                "twins": [
                    {"twin_id": twin["twin_id"], "name": twin["profile"]["name"]} for twin in twins
                ],
                "imported_at": _stamp(imported_at),
                "approval_required": list(STAGES),
                "why_verified": plan is not None and "why" in verified.manifest,
                "import_limits": [] if plan is None else list(plan.import_limits),
                **(
                    {"omitted_sections": list(plan.omitted_sections)}
                    if plan is not None and plan.omitted_sections
                    else {}
                ),
            },
        )

    def _route_import_origin(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None or project.origin is None:
            raise _Refusal(404, {"code": "PROJECT_IMPORT_NOT_FOUND", "location": None})
        return _Answer(200, project.origin)

    def _route_usage(self, call: _Call) -> _Answer:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        items = list(project.usage)
        return _Answer(
            200,
            {
                "items": items,
                "totals": {
                    "generations": len(items),
                    "input_tokens": sum(int(item["input_tokens"]) for item in items),
                    "output_tokens": sum(int(item["output_tokens"]) for item in items),
                    "reasoning_tokens": sum(int(item["reasoning_tokens"]) for item in items),
                    "cost_microusd": sum(int(item["cost_microusd"] or 0) for item in items),
                },
            },
        )

    def _code_project(self, call: _Call) -> FakeProject:
        project = self._owned(call)
        if project is None:
            raise _Refusal(404, {"code": "PROJECT_NOT_FOUND"})
        return project

    def _find_change(self, project: FakeProject, commit: str) -> dict[str, object]:
        wanted = commit.lower()
        if COMMIT_PATTERN.fullmatch(wanted) is None:
            raise _Refusal(404, {"code": "CODE_CHANGE_NOT_FOUND"})
        exact = next((item for item in project.code_changes if item["commit"] == wanted), None)
        if exact is not None:
            return exact
        found = [item for item in project.code_changes if str(item["commit"]).startswith(wanted)]
        if not found:
            raise _Refusal(404, {"code": "CODE_CHANGE_NOT_FOUND"})
        if len(found) > 1:
            raise _Refusal(409, {"code": "CODE_CHANGE_AMBIGUOUS"})
        return found[0]

    def _latest_run(self, project: FakeProject, commit: object) -> dict[str, object] | None:
        return next((run for run in project.change_runs if run["commit"] == commit), None)

    def _current_reference(self, project: FakeProject) -> dict[str, object] | None:
        reference = self._alignment_reference(project)
        requirements, design = reference["requirements"], reference["design"]
        if requirements is None or design is None:
            return None
        return {
            "requirements_version_number": requirements["version_number"],
            "design_version_number": design["version_number"],
            "alternative_code": design["alternative_code"],
        }

    def _change_payload(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        frame: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        latest = self._latest_run(project, record["commit"])
        review = None
        if latest is not None:
            reference = dict(latest["reference"])
            stale = review_is_stale(reference, self._current_reference(project))
            review = {
                "run_id": latest["id"],
                "reviewed_at": latest["reviewed_at"],
                "verdict": latest["alignment"]["status"],
                "summary": latest["alignment"]["summary"],
                "reference": reference,
                "stale": stale,
            }
            if frame is not None:
                del review["stale"]
                if frame["reference"] is not None and not stale:
                    review["reference"] = dict(frame["reference"])
        return {
            "commit": record["commit"],
            "parent": record["parent"],
            "committed_at": record["committed_at"],
            "author": record["author"],
            "message": record["message"],
            "files": copy.deepcopy(record["files"]),
            "recorded_at": record["recorded_at"],
            "review": review,
            "decision": copy.deepcopy(record["decision"]),
        }

    def _stale_reviews(self, project: FakeProject) -> int:
        current = self._current_reference(project)
        count = 0
        for record in self._pending(project):
            latest = self._latest_run(project, record["commit"])
            if latest is not None and review_is_stale(latest["reference"], current):
                count += 1
        return count

    def _aligned(self, project: FakeProject) -> dict[str, object] | None:
        record = next((item for item in project.code_changes if item["aligned"] is not None), None)
        return None if record is None else dict(record["aligned"])

    def _pending(self, project: FakeProject) -> list[dict[str, object]]:
        pending = []
        for record in project.code_changes:
            if record["aligned"] is not None:
                break
            pending.append(record)
        return pending

    def _alignment_reference(self, project: FakeProject) -> dict[str, object]:
        approvals = self._approvals(project)
        requirements = project.specification if approvals["requirements"] else None
        design = project.design if approvals["design"] else None
        return {
            "requirements": None
            if requirements is None
            else {
                "version_id": requirements["id"],
                "version_number": requirements["version_number"],
                "content_hash": requirements["content_hash"],
            },
            "design": None
            if design is None
            else {
                "version_id": design["id"],
                "version_number": design["version_number"],
                "content_hash": design["content_hash"],
                "alternative_code": _chosen_code(design["package"]),
            },
        }

    def _alignment_payload(self, project: FakeProject) -> dict[str, object]:
        latest = project.code_changes[0] if project.code_changes else None
        return {
            "project_id": project.id,
            "reference": self._alignment_reference(project),
            "aligned": self._aligned(project),
            "pending_changes": len(self._pending(project)),
            "stale_reviews": self._stale_reviews(project),
            "latest_change": None if latest is None else self._change_payload(project, latest),
            "tasks": self._task_list(project, every=False),
            "review_available": self.hosted,
        }

    def _approved_twins(self, project: FakeProject) -> list[dict[str, object]]:
        snapshot = project.snapshot
        if snapshot is None or not self._approvals(project)["twins"]:
            return []
        return list(snapshot["snapshot"]["twin_versions"])

    def _route_alignment(self, call: _Call) -> _Answer:
        return _Answer(200, self._alignment_payload(self._code_project(call)))

    def _route_record_change(self, call: _Call) -> _Answer:
        fields = _Fields(
            call.json(),
            ("commit", "parent", "committed_at", "author", "message", "files", "diff"),
        )
        commit = fields.pattern("commit", COMMIT_PATTERN)
        parent = fields.pattern("parent", COMMIT_PATTERN, required=False, nullable=True)
        committed_at = fields.moment("committed_at")
        author = fields.text("author", required=False, nullable=True, maximum=MAX_AUTHOR_LENGTH)
        if author is not None:
            author = fields.normalized("author", author, _optional_line)
        message = fields.text("message", minimum=1, maximum=MAX_MESSAGE_LENGTH)
        if message is not None:
            message = fields.normalized("message", message, _text_block)
        files = fields.changed_files("files")
        diff = fields.text("diff", required=False, maximum=MAX_DIFF_LENGTH, default="")
        diff = fields.normalized("diff", diff, _diff_text)
        fields.check()
        commit = str(commit).lower()
        parent = None if parent is None else parent.lower()
        if parent == commit:
            raise _Invalid([_error(("body",), "value_error")])
        project = self._code_project(call)
        stored = next((item for item in project.code_changes if item["commit"] == commit), None)
        if stored is not None:
            change = self._change_payload(project, stored)
            return _Answer(200, {"status": "ALREADY_RECORDED", "change": change})
        record: dict[str, object] = {
            "commit": commit,
            "parent": parent,
            "committed_at": _iso(committed_at) if committed_at is not None else None,
            "author": author,
            "message": message,
            "files": files,
            "recorded_at": _iso(self._now()),
            "decision": None,
            "diff": diff,
            "aligned": None,
        }
        project.code_changes.append(record)
        project.code_changes.sort(key=_recorded_order, reverse=True)
        return _Answer(201, {"status": "RECORDED", "change": self._change_payload(project, record)})

    def _route_changes(self, call: _Call) -> _Answer:
        raw = call.value("pending")
        pending = False if raw is None else _lax_boolean(raw)
        if pending is None:
            raise _Invalid([_error(("query", "pending"), "bool_parsing")])
        project = self._code_project(call)
        records = self._pending(project) if pending else project.code_changes
        return _Answer(
            200, {"items": [self._change_payload(project, record) for record in records]}
        )

    def _route_change(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        return _Answer(200, {**self._change_payload(project, record), "diff": record["diff"]})

    def _route_change_reviews(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        runs = [
            copy.deepcopy(run) for run in project.change_runs if run["commit"] == record["commit"]
        ]
        return _Answer(200, {"items": runs})

    def _route_review_change(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("locale", "again"))
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        again = fields.flag("again")
        fields.check()
        return self._later(
            call,
            "CODE_CHANGE_REVIEW",
            {"locale": locale, "again": again},
            lambda: self._reviewed_change(call, str(locale), again),
        )

    def _reviewed_change(self, call: _Call, locale: str, again: bool) -> _Answer:
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        if not again and any(run["commit"] == record["commit"] for run in project.change_runs):
            raise _Refusal(409, {"code": "CODE_CHANGE_REVIEW_EXISTS"})
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        twins = self._approved_twins(project)
        if not twins:
            raise _Refusal(409, {"code": "USER_MODELING_APPROVAL_REQUIRED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"})
        charged = 0
        for operation in (*("CODE_CHANGE_REVIEW" for _ in twins), "CODE_ALIGNMENT"):
            self._record(project, operation)
            charged += COSTS[operation]
        run = self._stored_change_run(project, record, twins, locale, reference, charged)
        return _Answer(201, {"status": "REVIEWED", "run": copy.deepcopy(run)})

    def _stored_change_run(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        reference: Mapping[str, object],
        charged: int,
    ) -> dict[str, object]:
        previous = self._latest_run(project, record["commit"])
        if previous is not None:
            earlier, source = _findings_by_twin(previous["critiques"]), "THIS_COMMIT"
        else:
            earlier, source = self._previous_commit_findings(project, record), "PREVIOUS_COMMIT"
        run = self._change_run(project, record, twins, locale, reference, charged)
        project.change_runs.insert(0, run)
        project.critique_contexts.insert(
            0,
            {
                "kind": "CODE_CHANGE",
                "run_id": run["id"],
                "commit": record["commit"],
                "twins": [
                    {
                        "twin_id": twin["twin_id"],
                        "earlier_source": source if earlier.get(twin["twin_id"]) else None,
                        "earlier_findings": earlier.get(twin["twin_id"], []),
                    }
                    for twin in twins
                ],
            },
        )
        return run

    def _previous_commit_findings(
        self, project: FakeProject, record: Mapping[str, object]
    ) -> dict[str, list[str]]:
        pending = self._pending(project)
        index = next(
            (place for place, item in enumerate(pending) if item["commit"] == record["commit"]),
            None,
        )
        if index is None:
            return {}
        for older in pending[index + 1 :]:
            latest = self._latest_run(project, older["commit"])
            if latest is not None:
                return _findings_by_twin(latest["critiques"])
        return {}

    def _change_run(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        reference: Mapping[str, object],
        charged: int,
    ) -> dict[str, object]:
        texts = CHANGE_CRITIQUES[self.language]
        verdicts = CHANGE_VERDICTS[self.language]
        specification = project.specification
        design = project.design
        if specification is None or design is None:
            raise RuntimeError("a review needs the approved requirements and design")
        line = _first_line(str(record["message"]))
        known = [str(item["code"]) for item in specification["specification"]["requirements"]]
        cited = [code for code in REQUIREMENT_CODE.findall(str(record["diff"])) if code in known]
        requirement = cited[0] if cited else known[0]
        screen = _first_screen(design["package"])
        files = record["files"]
        first_file = str(files[0]["path"]) if files else None
        critiques = []
        for position, twin in enumerate(twins):
            findings = []
            if position == 0:
                text, action = texts["requirement"]
                findings.append(
                    _change_finding(
                        "MEDIUM",
                        text.format(code=requirement),
                        action.format(code=requirement),
                        requirement=requirement,
                        file=first_file,
                    )
                )
                text, action = texts["screen"]
                findings.append(
                    _change_finding(
                        "LOW", text.format(code=screen), action.format(code=screen), screen=screen
                    )
                )
            elif position == 1:
                text, action = texts["check"]
                findings.append(
                    _change_finding(
                        "LOW",
                        text.format(code=requirement, screen=screen),
                        action.format(code=requirement, screen=screen),
                        requirement=requirement,
                        screen=screen,
                    )
                )
            verdict = "CONCERN" if position == 0 else "FINE"
            critiques.append(
                {
                    "twin_id": twin["twin_id"],
                    "twin_name": twin["profile"]["name"],
                    "verdict": verdict,
                    "summary": texts[verdict].format(goal=_first_goal(twin), line=line),
                    "findings": findings,
                }
            )
        status = _alignment_status(str(record["message"]))
        about = [finding["about"] for critique in critiques for finding in critique["findings"]]
        design_reference = reference["design"]
        requirements_reference = reference["requirements"]
        return {
            "id": self._new_id(),
            "commit": record["commit"],
            "reviewed_at": _iso(self._now()),
            "locale": locale,
            "reference": {
                "requirements_version_number": requirements_reference["version_number"],
                "design_version_number": design_reference["version_number"],
                "alternative_code": design_reference["alternative_code"],
            },
            "critiques": critiques,
            "alignment": {
                "status": status,
                "summary": verdicts[status].format(line=line),
                "affected": {
                    "requirements": sorted(
                        {str(item["requirement"]) for item in about if item["requirement"]}
                    ),
                    "screens": sorted({str(item["screen"]) for item in about if item["screen"]}),
                },
                "design_request": verdicts["design_request"].format(line=line, screen=screen)
                if status == "DESIGN_OUTDATED"
                else None,
                "requirements_request": verdicts["requirements_request"].format(
                    line=line, code=requirement
                )
                if status == "REQUIREMENTS_OUTDATED"
                else None,
                "code_tasks": [
                    task.format(screen=screen, code=requirement) for task in verdicts["tasks"]
                ]
                if status == "CODE_DRIFT"
                else [],
            },
            "cost_microusd": charged,
        }

    def _route_decide_change(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), DECISION_FIELDS)
        kind = fields.choice("kind", DECISIONS)
        note = fields.text("note", required=False, nullable=True, maximum=MAX_NOTE_LENGTH)
        if note is not None:
            note = fields.normalized("note", note, _optional_block)
        tasks = fields.texts(
            "tasks",
            nullable=False,
            maximum_items=MAX_TASKS,
            default=[],
            item_minimum=1,
            item_maximum=MAX_TASK_LENGTH,
        )
        texts = fields.normalized("tasks", tasks, _task_texts) if tasks else []
        findings = _models(
            fields,
            "findings",
            FINDING_FIELDS,
            _finding_of,
            required=False,
            maximum_items=MAX_TASKS,
        )
        fields.check()
        texts = list(texts or [])
        if kind == "CODE_TASKS":
            valid = 1 <= len(texts) + len(findings) <= MAX_TASKS
        else:
            valid = not texts and not findings
        if not valid:
            raise _Invalid([_error(("body",), "value_error")])
        project = self._code_project(call)
        record = self._find_change(project, call.params["commit"])
        self._decide(project, record, str(kind), note, texts, findings)
        return _Answer(
            200,
            {
                "status": "DECIDED",
                "change": self._change_payload(project, record),
                "alignment": self._alignment_payload(project),
            },
        )

    def _decide(
        self,
        project: FakeProject,
        record: dict[str, object],
        kind: str,
        note: str | None,
        texts: Sequence[str],
        findings: Sequence[Mapping[str, object]],
    ) -> None:
        sources = [
            {
                "kind": "CODE_CHANGE",
                "commit": record["commit"],
                "twin_id": item["twin_id"],
                "finding": item["finding"],
            }
            for item in findings
        ]
        resolved = self._resolve_sources(project, sources)
        latest = self._latest_run(project, record["commit"])
        affected = {"requirements": [], "screens": []}
        if latest is not None:
            affected = copy.deepcopy(latest["alignment"]["affected"])
        moment = _iso(self._now())
        record["decision"] = {"kind": kind, "decided_at": moment, "note": note}
        record["aligned"] = None
        if kind == "ALIGNED":
            reference = self._alignment_reference(project)
            requirements, design = reference["requirements"], reference["design"]
            record["aligned"] = {
                "commit": record["commit"],
                "decided_at": moment,
                "requirements_version_number": None
                if requirements is None
                else requirements["version_number"],
                "design_version_number": None if design is None else design["version_number"],
            }
            self._close_aligned_tasks(project, record, moment)
        origin = _task_origin("CODE_CHANGE", commit=str(record["commit"]))
        for text in texts:
            self._new_task(
                project,
                text,
                {**affected, "criteria": []},
                origin,
                moment,
            )
        self._create_tasks(project, [_prepared_task(None, item) for item in resolved], moment)
        project.decision_count += 1

    def _close_aligned_tasks(
        self, project: FakeProject, record: Mapping[str, object], moment: str
    ) -> None:
        places = {str(item["commit"]): place for place, item in enumerate(project.code_changes)}
        aligned_place = places[str(record["commit"])]
        recorded = datetime.fromisoformat(str(record["recorded_at"]))
        for task in project.code_tasks:
            if task["status"] != "OPEN":
                continue
            origin = task["origin"]
            if origin["kind"] == "CODE_CHANGE":
                closed = places[str(origin["commit"])] >= aligned_place
            else:
                closed = datetime.fromisoformat(str(task["created_at"])) <= recorded
            if closed:
                task["status"] = "DONE"
                task["closed_at"] = moment
                task["note"] = None

    def _task_list(self, project: FakeProject, *, every: bool) -> list[dict[str, object]]:
        return [
            copy.deepcopy(task) for task in project.code_tasks if every or task["status"] == "OPEN"
        ]

    def _find_task(self, project: FakeProject, code: str) -> dict[str, object]:
        wanted = code.upper()
        task = None
        if TASK_CODE.fullmatch(wanted) is not None:
            task = next((item for item in project.code_tasks if item["code"] == wanted), None)
        if task is None:
            raise _Refusal(404, {"code": "CODE_TASK_NOT_FOUND"})
        return task

    def _resolve_sources(
        self, project: FakeProject, sources: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        runs: dict[int, dict[str, object]] = {}
        changes: dict[int, dict[str, object]] = {}
        refusals: list[_Refusal] = []
        for index, source in enumerate(sources):
            if source["kind"] == "TEST_RUN":
                runs[index] = self._find_test_run(project, str(source["test_run_id"]))
        for index, source in enumerate(sources):
            if source["kind"] == "CODE_CHANGE":
                try:
                    changes[index] = self._find_change(project, str(source["commit"]))
                except _Refusal as refusal:
                    refusals.append(refusal)
        if refusals:
            raise min(refusals, key=lambda refusal: refusal.status == 409)
        resolved: list[dict[str, object]] = []
        for index, source in enumerate(sources):
            if source["kind"] == "OWNER":
                resolved.append({"origin": _task_origin("OWNER"), "finding": None})
                continue
            if source["kind"] == "TEST_RUN":
                record = runs[index]
                review = next(
                    (item for item in project.acceptance_reviews if item["run_id"] == record["id"]),
                    None,
                )
                critiques = [] if review is None else review["critiques"]
                subject = {"test_run_id": str(record["id"])}
            else:
                record = changes[index]
                latest = self._latest_run(project, record["commit"])
                critiques = [] if latest is None else latest["critiques"]
                subject = {"commit": str(record["commit"])}
            critique = next(
                (item for item in critiques if item["twin_id"] == source["twin_id"]), None
            )
            findings = [] if critique is None else critique["findings"]
            position = int(source["finding"])
            if position >= len(findings):
                raise _Refusal(422, {"code": "TASK_SOURCE_INVALID", "index": index})
            finding = findings[position]
            origin = _task_origin(
                str(source["kind"]),
                **subject,
                twin_id=str(critique["twin_id"]),
                twin_name=str(critique["twin_name"]),
                finding=str(finding["text"]),
            )
            resolved.append({"origin": origin, "finding": finding})
        return resolved

    def _new_task(
        self,
        project: FakeProject,
        text: str,
        about: Mapping[str, object],
        origin: Mapping[str, object],
        moment: str,
    ) -> dict[str, object]:
        task: dict[str, object] = {
            "code": f"TSK-{len(project.code_tasks) + 1:03d}",
            "text": text,
            "about": {
                "requirements": list(about["requirements"]),
                "screens": list(about["screens"]),
                "criteria": list(about["criteria"]),
            },
            "origin": dict(origin),
            "from_commit": origin["commit"],
            "created_at": moment,
            "status": "OPEN",
            "closed_at": None,
            "note": None,
        }
        project.code_tasks.append(task)
        return task

    def _create_tasks(
        self,
        project: FakeProject,
        prepared: Sequence[Mapping[str, object]],
        moment: str,
    ) -> tuple[int, list[dict[str, object]]]:
        created = 0
        tasks: list[dict[str, object]] = []
        for item in prepared:
            origin = item["origin"]
            existing = None if origin["twin_id"] is None else _open_task(project, origin)
            if existing is not None:
                tasks.append(existing)
                continue
            tasks.append(self._new_task(project, item["text"], item["about"], origin, moment))
            created += 1
        return created, tasks

    def _route_code_tasks(self, call: _Call) -> _Answer:
        wanted = call.value("status")
        if wanted is not None and wanted not in TASK_FILTERS:
            raise _Invalid([_error(("query", "status"), "literal_error")])
        project = self._code_project(call)
        return _Answer(200, {"items": self._task_list(project, every=wanted == "all")})

    def _route_create_tasks(self, call: _Call) -> _Answer:
        items = _task_items(call.json())
        project = self._code_project(call)
        created, tasks = self._created_tasks(project, items)
        return _Answer(
            201,
            {
                "status": "CREATED",
                "created": created,
                "tasks": copy.deepcopy(tasks),
                "alignment": self._alignment_payload(project),
            },
        )

    def _created_tasks(
        self, project: FakeProject, items: Sequence[Mapping[str, object]]
    ) -> tuple[int, list[dict[str, object]]]:
        resolved = self._resolve_sources(project, [item["source"] for item in items])
        prepared = [
            _prepared_task(item["text"], found) for item, found in zip(items, resolved, strict=True)
        ]
        return self._create_tasks(project, prepared, _iso(self._now()))

    def _route_task_status(self, call: _Call) -> _Answer:
        status, note = _task_status_of(call.json())
        project = self._code_project(call)
        task = self._find_task(project, call.params["code"])
        _set_task_status(task, status, note, _iso(self._now()))
        return _Answer(
            200,
            {
                "status": "UPDATED",
                "task": copy.deepcopy(task),
                "alignment": self._alignment_payload(project),
            },
        )

    def _changed_task(
        self, project: FakeProject, code: str, body: Mapping[str, object]
    ) -> dict[str, object]:
        status, note = _task_status_of(dict(body))
        task = self._find_task(project, code)
        _set_task_status(task, status, note, _iso(self._now()))
        return copy.deepcopy(task)

    def _add_tasks(
        self, project: FakeProject, items: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        _, tasks = self._created_tasks(
            project, _task_items({"tasks": [dict(item) for item in items]})
        )
        return copy.deepcopy(tasks)

    def _seeded(self, work: Callable[[], object]) -> object:
        try:
            return work()
        except _Refusal as refusal:
            raise ValueError(f"the fake studio refuses: {refusal.detail}") from refusal
        except _Invalid as invalid:
            raise ValueError(f"the fake studio refuses: {invalid.errors}") from invalid

    def _find_test_plan(self, project: FakeProject, identifier: str) -> dict[str, object]:
        plan = next((item for item in project.acceptance_plans if item["id"] == identifier), None)
        if plan is None:
            raise _Refusal(404, {"code": "TEST_PLAN_NOT_FOUND"})
        return plan

    def _find_test_run(self, project: FakeProject, identifier: str) -> dict[str, object]:
        record = next((item for item in project.acceptance_runs if item["id"] == identifier), None)
        if record is None:
            raise _Refusal(404, {"code": "TEST_RUN_NOT_FOUND"})
        return record

    def _test_run_payload(
        self, project: FakeProject, record: Mapping[str, object]
    ) -> dict[str, object]:
        payload = copy.deepcopy(dict(record))
        latest = next(
            (review for review in project.acceptance_reviews if review["run_id"] == record["id"]),
            None,
        )
        if latest is not None:
            payload["critiques"] = copy.deepcopy(latest["critiques"])
            payload["reviewed_at"] = latest["reviewed_at"]
            payload["cost_microusd"] = int(record["cost_microusd"]) + int(latest["cost_microusd"])
        return payload

    def _route_acceptance_tests(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        runs = project.acceptance_runs
        latest = runs[0] if runs else None
        reviewed = self._latest_reviewed_run(project)
        return _Answer(
            200,
            {
                "project_id": project.id,
                "reference": self._alignment_reference(project),
                "plan_available": self.hosted,
                "plans": len(project.acceptance_plans),
                "runs": len(runs),
                "latest_run": None if latest is None else self._test_run_payload(project, latest),
                "latest_run_stale": latest is not None
                and review_is_stale(latest["reference"], self._current_reference(project)),
                "latest_review": None
                if reviewed is None
                else {
                    "run_id": reviewed[0]["id"],
                    "finished_at": reviewed[0]["finished_at"],
                    "reviewed_at": reviewed[1]["reviewed_at"],
                    "critiques": copy.deepcopy(reviewed[1]["critiques"]),
                },
            },
        )

    def _route_plan_tests(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), PLAN_FIELDS)
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        application = _application_of(fields)
        snapshot = _snapshot_of(fields)
        criteria = fields.texts(
            "criteria",
            minimum_items=1,
            maximum_items=MAX_REQUESTED_CRITERIA,
            item_minimum=1,
            item_maximum=CRITERION_LENGTH,
            item_pattern=CRITERION_REQUEST,
        )
        earlier = _earlier_of(fields)
        if criteria is not None:
            criteria = list(dict.fromkeys(code.upper() for code in criteria))
        _model_rule(fields, lambda: _distinct(item["code"] for item in earlier or ()))
        fields.check()
        body = {
            "locale": locale,
            "application": application,
            "snapshot": snapshot,
            "criteria": criteria,
            "earlier": earlier,
        }
        return self._later(call, "TEST_PLAN", body, lambda: self._planned_tests(call, body))

    def _next_path_number(self, project: FakeProject) -> int:
        numbers = [
            int(str(path["code"]).split("-", 1)[1])
            for plan in project.acceptance_plans
            for path in plan["paths"]
        ]
        return max(numbers, default=0) + 1

    def _planned_tests(self, call: _Call, body: Mapping[str, object]) -> _Answer:
        project = self._code_project(call)
        first = self._next_path_number(project) if body["earlier"] else 1
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TEST_MODEL_NOT_CONFIGURED"})
        specification = project.specification
        if specification is None:
            raise RuntimeError("a plan needs the approved requirements")
        statements = {
            str(item["code"]): str(item["statement"])
            for item in specification["specification"]["acceptance_criteria"]
        }
        asked = body["criteria"]
        unknown = [code for code in dict.fromkeys(asked or ()) if code not in statements]
        if unknown:
            raise _Refusal(422, {"code": "ACCEPTANCE_CRITERION_UNKNOWN", "codes": unknown})
        earlier = body["earlier"] or []
        if earlier:
            named = {str(code) for path in earlier for code in path["criteria"]}
            wanted = [code for code in statements if code in named]
        else:
            wanted = [code for code in statements if asked is None or code in asked]
        self._record(project, "TEST_PLAN")
        plan = self._test_plan(
            body, reference, [(code, statements[code]) for code in wanted], first
        )
        project.acceptance_plans.insert(0, plan)
        project.acceptance_plan_requests.insert(0, _copy(dict(body)))
        return _Answer(201, {"status": "PLANNED", "plan": copy.deepcopy(plan)})

    def _test_plan(
        self,
        body: Mapping[str, object],
        reference: Mapping[str, object],
        wanted: Sequence[tuple[str, str]],
        first: int,
    ) -> dict[str, object]:
        earlier = body["earlier"] or []
        words = str(body["snapshot"]["title"]).split()
        title = words[0] if words else TITLE_WORD
        paths: list[dict[str, object]] = []
        not_covered = []
        for code, statement in wanted:
            if MANUAL_WORD in statement.casefold():
                not_covered.append({"criterion": code, "reason": NOT_COVERED_REASON[self.language]})
                continue
            steps = [
                _test_step("OPEN", value="/"),
                _test_step(
                    "CHECK",
                    expect=_test_expectation(
                        "TEXT_VISIBLE", " ".join(statement.split()[:CHECK_WORDS])
                    ),
                ),
            ]
            if earlier:
                steps.append(_test_step("CHECK", expect=_test_expectation("TITLE_CONTAINS", title)))
            paths.append(
                {
                    "code": f"TP-{first + len(paths):03d}",
                    "heading": statement[:HEADING_LENGTH].rstrip(),
                    "criteria": [code],
                    "steps": steps,
                }
            )
        requirements = reference["requirements"]
        design = reference["design"]
        return {
            "id": self._new_id(),
            "created_at": _iso(self._now()),
            "locale": body["locale"],
            "reference": {
                "requirements_version_number": requirements["version_number"],
                "design_version_number": design["version_number"],
                "alternative_code": design["alternative_code"],
            },
            "application": _normal_application(body["application"]),
            "criteria": [code for code, _ in wanted],
            "replan_of": [str(path["code"]) for path in earlier],
            "paths": paths,
            "not_covered": not_covered,
            "cost_microusd": COSTS["TEST_PLAN"],
        }

    def _route_test_plans(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, {"items": copy.deepcopy(project.acceptance_plans[:LIST_LIMIT])})

    def _route_test_plan(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, copy.deepcopy(self._find_test_plan(project, call.params["plan_id"])))

    def _route_record_test_run(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), RUN_FIELDS)
        plan_id = fields.identifier("plan_id")
        replan_ids = fields.identifiers("replan_ids", maximum_items=MAX_REPLANS)
        started_at = fields.moment("started_at")
        finished_at = fields.moment("finished_at")
        application = _application_of(fields)
        browsers = _models(
            fields,
            "browsers",
            BROWSER_FIELDS,
            _browser_of,
            minimum_items=1,
            maximum_items=MAX_BROWSERS,
        )
        results = _models(fields, "results", RESULT_FIELDS, _result_of, maximum_items=MAX_RESULTS)
        not_covered = _models(
            fields,
            "not_covered",
            NOT_COVERED_FIELDS,
            _not_covered_of,
            maximum_items=MAX_REQUESTED_CRITERIA,
        )
        _model_rule(
            fields,
            lambda: _run_rule(
                plan_id, replan_ids, started_at, finished_at, browsers, results, not_covered
            ),
        )
        fields.check()
        project = self._code_project(call)
        plans = [
            self._find_test_plan(project, identifier) for identifier in (str(plan_id), *replan_ids)
        ]
        bound = _bound_results(plans, results, not_covered)
        uncovered = [
            {"criterion": item["criterion"], "reason": _single_line(item["reason"])}
            for item in not_covered
        ]
        outcomes = _criteria_outcomes(plans, bound, uncovered)
        record: dict[str, object] = {
            "id": self._new_id(),
            "started_at": _iso(started_at) if started_at is not None else None,
            "finished_at": _iso(finished_at) if finished_at is not None else None,
            "recorded_at": _iso(self._now()),
            "application": _normal_application(application or {}),
            "browsers": [
                {"name": item["name"], "version": _single_line(item["version"])}
                for item in browsers
            ],
            "reference": copy.deepcopy(plans[0]["reference"]),
            "summary": _run_summary(outcomes),
            "criteria": outcomes,
            "not_covered": uncovered,
            "results": bound,
            "critiques": [],
            "reviewed_at": None,
            "cost_microusd": sum(int(plan["cost_microusd"]) for plan in plans),
        }
        project.acceptance_runs.insert(0, record)
        return _Answer(201, {"status": "RECORDED", "run": self._test_run_payload(project, record)})

    def _route_test_runs(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(
            200,
            {
                "items": [
                    self._test_run_payload(project, record)
                    for record in project.acceptance_runs[:LIST_LIMIT]
                ]
            },
        )

    def _route_test_run(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_test_run(project, call.params["run_id"])
        return _Answer(200, self._test_run_payload(project, record))

    def _route_review_test_run(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("locale", "again"))
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        again = fields.flag("again")
        fields.check()
        return self._later(
            call,
            "TEST_REVIEW",
            {"locale": locale, "again": again},
            lambda: self._reviewed_test_run(call, str(locale), again),
        )

    def _reviewed_test_run(self, call: _Call, locale: str, again: bool) -> _Answer:
        project = self._code_project(call)
        record = self._find_test_run(project, call.params["run_id"])
        if not again and any(
            review["run_id"] == record["id"] for review in project.acceptance_reviews
        ):
            raise _Refusal(409, {"code": "TEST_REVIEW_EXISTS"})
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        twins = self._approved_twins(project)
        if not twins:
            raise _Refusal(409, {"code": "USER_MODELING_APPROVAL_REQUIRED"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TEST_MODEL_NOT_CONFIGURED"})
        charged = 0
        for _ in twins:
            self._record(project, "TEST_REVIEW")
            charged += COSTS["TEST_REVIEW"]
        review = self._stored_test_review(project, record, twins, locale, charged)
        return _Answer(201, {"status": "REVIEWED", "review": copy.deepcopy(review)})

    def _stored_test_review(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
        locale: str,
        charged: int,
    ) -> dict[str, object]:
        earlier = self._earlier_test_findings(project, record)
        review = {
            "id": self._new_id(),
            "run_id": record["id"],
            "reviewed_at": _iso(self._now()),
            "locale": locale,
            "critiques": self._test_critiques(project, record, twins),
            "cost_microusd": charged,
        }
        project.acceptance_reviews.insert(0, review)
        project.critique_contexts.insert(
            0,
            {
                "kind": "TEST_RUN",
                "review_id": review["id"],
                "run_id": record["id"],
                "twins": [
                    {
                        "twin_id": twin["twin_id"],
                        "earlier_findings": earlier.get(twin["twin_id"], []),
                    }
                    for twin in twins
                ],
            },
        )
        return review

    def _latest_test_review(self, project: FakeProject, run_id: object) -> dict[str, object] | None:
        return next(
            (review for review in project.acceptance_reviews if review["run_id"] == run_id), None
        )

    def _latest_reviewed_run(
        self, project: FakeProject
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        for record in project.acceptance_runs:
            review = self._latest_test_review(project, record["id"])
            if review is not None:
                return record, review
        return None

    def _earlier_test_findings(
        self, project: FakeProject, record: Mapping[str, object]
    ) -> dict[str, list[str]]:
        runs = project.acceptance_runs
        index = next(
            (place for place, item in enumerate(runs) if item["id"] == record["id"]), len(runs)
        )
        for older in runs[index + 1 :]:
            review = self._latest_test_review(project, older["id"])
            if review is not None:
                return _findings_by_twin(review["critiques"])
        return {}

    def _test_critiques(
        self,
        project: FakeProject,
        record: Mapping[str, object],
        twins: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        texts = TEST_CRITIQUES[self.language]
        criteria = record["criteria"]
        chosen = next(
            (item for item in criteria if item["status"] in FAILING_STATUSES),
            criteria[0] if criteria else None,
        )
        code = None if chosen is None else str(chosen["code"])
        about = {
            "criterion": code,
            "requirement": self._criterion_requirement(project, code),
            "screen": None if project.design is None else _first_screen(project.design["package"]),
        }
        numbers = texts["numbers"].format(**record["summary"])
        critiques = []
        for position, twin in enumerate(twins):
            findings = []
            if code is not None and position < 2:
                severity, key = ("MEDIUM", "concern") if position == 0 else ("LOW", "check")
                text, action = texts[key]
                findings.append(
                    {
                        "severity": severity,
                        "text": text.format(code=code),
                        "about": dict(about),
                        "action": action.format(code=code),
                    }
                )
            verdict = "CONCERN" if position == 0 else "FINE"
            critiques.append(
                {
                    "twin_id": twin["twin_id"],
                    "twin_name": twin["profile"]["name"],
                    "verdict": verdict,
                    "summary": texts[verdict].format(goal=_first_goal(twin), numbers=numbers),
                    "findings": findings,
                }
            )
        return critiques

    def _criterion_requirement(self, project: FakeProject, code: str | None) -> str | None:
        specification = project.specification
        if specification is None or code is None:
            return None
        content = specification["specification"]
        criterion = next(
            (item for item in content["acceptance_criteria"] if item["code"] == code), None
        )
        if criterion is None or not criterion["requirement_ids"]:
            return None
        codes = {str(item["id"]): str(item["code"]) for item in content["requirements"]}
        return codes.get(str(criterion["requirement_ids"][0]))

    def _route_test_run_reviews(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        record = self._find_test_run(project, call.params["run_id"])
        return _Answer(
            200,
            {
                "items": [
                    copy.deepcopy(review)
                    for review in project.acceptance_reviews
                    if review["run_id"] == record["id"]
                ]
            },
        )

    def _learning_entry(
        self, project: FakeProject, twin: Mapping[str, object]
    ) -> dict[str, object]:
        twin_id = str(twin["twin_id"])
        version = int(twin["version_number"])
        development = project.development.get(twin_id, 0)
        own = [item for item in project.learned if item["twin_id"] == twin_id]
        retired = sorted(
            (item for item in own if item["retired"] is not None),
            key=lambda item: (
                int(item["retired"]["retired_in_version"]),
                _code_number(item["code"]),
            ),
        )
        return {
            "twin_id": twin_id,
            "twin_name": str(twin["profile"]["name"]),
            "profile_version_number": version,
            "development_version_number": development,
            "label": f"{version}.{development}",
            "observations": [_active_entry(item) for item in own if item["retired"] is None],
            "retired": [_retired_entry(item) for item in retired],
        }

    def _learning_entries(self, project: FakeProject) -> list[dict[str, object]]:
        return [self._learning_entry(project, twin) for twin in self._approved_twins(project)]

    def _learning_twin(self, project: FakeProject, twin_id: str) -> dict[str, object]:
        twins = self._approved_twins(project)
        if not twins:
            raise _Refusal(409, {"code": "USER_MODELING_APPROVAL_REQUIRED"})
        twin = next((item for item in twins if item["twin_id"] == twin_id), None)
        if twin is None:
            raise _Refusal(404, {"code": "USER_TWIN_NOT_FOUND"})
        return twin

    def _pending_update(self, project: FakeProject, twin_id: str) -> dict[str, object] | None:
        return next(
            (
                update
                for update in project.updates
                if update["twin_id"] == twin_id and update["status"] == "PROPOSED"
            ),
            None,
        )

    def _refuse_pending(self, project: FakeProject, twin_id: str) -> None:
        pending = self._pending_update(project, twin_id)
        if pending is not None:
            raise _Refusal(409, {"code": "TWIN_UPDATE_PENDING", "update_id": pending["id"]})

    def _active_count(self, project: FakeProject, twin_id: str) -> int:
        return sum(
            1 for item in project.learned if item["twin_id"] == twin_id and item["retired"] is None
        )

    def _new_material(
        self, project: FakeProject, twin_id: str
    ) -> tuple[list[tuple[dict, dict]], list[tuple[dict, dict]]]:
        latest = next((update for update in project.updates if update["twin_id"] == twin_id), None)
        since = None if latest is None else datetime.fromisoformat(str(latest["created_at"]))
        changes = []
        for record in project.code_changes:
            run = self._latest_run(project, record["commit"])
            critique = None if run is None else _critique_of(run, twin_id)
            if critique is not None and _after(run["reviewed_at"], since):
                changes.append((run, critique))
        tests = []
        for record in project.acceptance_runs:
            review = self._latest_test_review(project, record["id"])
            critique = None if review is None else _critique_of(review, twin_id)
            if critique is not None and _after(review["reviewed_at"], since):
                tests.append((review, critique))
        changes.sort(key=_critique_moment, reverse=True)
        tests.sort(key=_critique_moment, reverse=True)
        return changes, tests

    def _proposal(
        self,
        project: FakeProject,
        twin: Mapping[str, object],
        changes: Sequence[tuple[dict, dict]],
        tests: Sequence[tuple[dict, dict]],
        language: str,
    ) -> list[dict[str, object]]:
        texts = LEARNING_TEXTS[language]
        name = str(twin["profile"]["name"])
        seen = {
            _comparable(str(item["statement"]))
            for item in project.learned
            if item["twin_id"] == twin["twin_id"] and item["retired"] is None
        }
        candidates = [
            *(
                (finding, texts["tests"])
                for _, critique in tests
                for finding in critique["findings"]
            ),
            *(
                (finding, texts["commit"].format(commit=str(run["commit"])[:8]))
                for run, critique in changes
                for finding in critique["findings"]
            ),
        ]
        observations: list[dict[str, object]] = []
        for finding, basis in candidates:
            statement = _cut_line(f"{name}: {finding['text']}", MAX_OBSERVATION_LENGTH)
            if _comparable(statement) in seen:
                continue
            seen.add(_comparable(statement))
            about = finding["about"]
            observations.append(
                {
                    "index": len(observations),
                    "statement": statement,
                    "basis": basis,
                    "about": {
                        "requirement": about.get("requirement"),
                        "screen": about.get("screen"),
                    },
                    "contradicts_profile": None,
                }
            )
            if len(observations) == PROPOSED_OBSERVATIONS:
                break
        return observations

    def _update_of(
        self,
        project: FakeProject,
        twin: Mapping[str, object],
        locale: str,
        observations: Sequence[Mapping[str, object]],
        material: Mapping[str, int],
        cost: int,
    ) -> dict[str, object]:
        texts = LEARNING_TEXTS[_locale_language(locale)]
        twin_id = str(twin["twin_id"])
        return {
            "id": self._new_id(),
            "twin_id": twin_id,
            "twin_name": str(twin["profile"]["name"]),
            "created_at": _iso(self._now()),
            "locale": locale,
            "status": "PROPOSED" if observations else "EMPTY",
            "base": {
                "profile_version_number": int(twin["version_number"]),
                "development_version_number": project.development.get(twin_id, 0),
            },
            "comment": texts["learned"].format(count=len(observations))
            if observations
            else texts["nothing"],
            "observations": [copy.deepcopy(dict(item)) for item in observations],
            "material": dict(material),
            "decision": None,
            "cost_microusd": cost,
        }

    def _add_observation(
        self,
        project: FakeProject,
        twin: Mapping[str, object],
        observation: Mapping[str, object],
        *,
        source: str,
        version: int,
        moment: str,
        update_id: str | None,
    ) -> None:
        about = observation.get("about") or {}
        project.learned.append(
            {
                "twin_id": str(twin["twin_id"]),
                "code": f"{OBSERVATION_CODE_PREFIX}-{len(project.learned) + 1:03d}",
                "statement": observation["statement"],
                "basis": observation.get("basis"),
                "source": source,
                "about": {"requirement": about.get("requirement"), "screen": about.get("screen")},
                "contradicts_profile": observation.get("contradicts_profile"),
                "added_in_version": version,
                "approved_at": moment,
                "update_id": update_id,
                "retired": None,
            }
        )

    def _find_update(self, project: FakeProject, update_id: str) -> dict[str, object]:
        update = next((item for item in project.updates if item["id"] == update_id), None)
        if update is None:
            raise _Refusal(404, {"code": "TWIN_UPDATE_NOT_FOUND"})
        return update

    def _named_twin(
        self, project: FakeProject, twin_id: str, name: object, version: object
    ) -> dict[str, object]:
        twin = next(
            (item for item in self._approved_twins(project) if item["twin_id"] == twin_id), None
        )
        if twin is not None:
            return twin
        return {"twin_id": twin_id, "version_number": version, "profile": {"name": name}}

    def _route_twin_learning(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        twins = []
        for twin in self._approved_twins(project):
            twin_id = str(twin["twin_id"])
            changes, tests = self._new_material(project, twin_id)
            pending = self._pending_update(project, twin_id)
            twins.append(
                {
                    **self._learning_entry(project, twin),
                    "pending_update": None if pending is None else copy.deepcopy(pending),
                    "new_material": {"changes": len(changes), "tests": len(tests)},
                }
            )
        return _Answer(
            200, {"project_id": project.id, "update_available": self.hosted, "twins": twins}
        )

    def _evidence_citations(self, project: FakeProject) -> list[dict[str, object]]:
        return [
            {
                "twin_id": row["twin_id"],
                "twin_version": row["twin_version"],
                "field": row["field"],
                "effect": row["change"]["effect"],
                "citation": copy.deepcopy(row["change"]["citation"]),
                "status": "ACTIVE" if row["retired_at"] is None else "RETIRED",
                **(
                    {"imported_from": copy.deepcopy(row["change"]["imported_from"])}
                    if row["change"].get("imported_from") is not None
                    else {}
                ),
            }
            for row in project.evidence_changes
        ]

    def _evidence_dossier(self, project: FakeProject) -> dict[str, object]:
        result = {
            "kind": "orchestwin.research-evidence",
            "schema_version": 1,
            "project_id": project.id,
            "evidence": copy.deepcopy(project.evidence_versions),
            "citations": self._evidence_citations(project),
        }
        present = self._publishable(project)
        if project.evidence_versions and any(
            project.artifact(stage) is not None for stage in STAGES if stage not in present
        ):
            sections = self._project_sections(project)
            result["omitted_sections"] = []
            for stage in STAGES:
                if stage in present or project.artifact(stage) is None:
                    continue
                section = sections.section(FOLDER_SECTIONS[stage])
                result["omitted_sections"].append(
                    {
                        "stage": stage,
                        "reason": ",".join(reason.value for reason in section.reasons)
                        or "APPROVAL_REQUIRED",
                        "affected_codes": {
                            key: list(values) for key, values in section.affected_codes.items()
                        },
                    }
                )
        return result

    def _evidence_source(self, project: FakeProject, source_id: str, version: int | None = None):
        found = [
            item
            for item in project.evidence_versions
            if item["id"] == source_id and (version is None or item["version"] == version)
        ]
        if not found:
            raise _Refusal(404, {"code": "EVIDENCE_NOT_FOUND"})
        return max(found, key=lambda item: item["version"])

    def _route_evidence_list(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        values = project.evidence_versions
        if call.query.get("all") != ["true"]:
            latest = {item["id"]: item for item in values}
            values = [
                item
                for item in latest.values()
                if item["status"] == "ACTIVE" and item["text_available"]
            ]
        return _Answer(
            200,
            {
                "project_id": project.id,
                "evidence": copy.deepcopy(values),
                "citations": self._evidence_citations(project),
            },
        )

    def _why_document(self, project: FakeProject, *, validation_context=False) -> dict[str, object]:
        from orchestwin.why import build_why_document

        return build_why_document(
            project_id=project.id,
            validation_context=validation_context,
            stages={
                "brief": [
                    {**item.payload, "brief": item.brief.to_snapshot()} for item in project.briefs
                ],
                "team": [
                    {
                        **{name: value for name, value in item.items() if name != "perspectives"},
                        "proposal": _fake_team_proposal(item).to_snapshot(),
                    }
                    for item in project.teams
                ],
                "twins": [
                    {**item, "snapshot": _fake_modeling(item["snapshot"]).to_snapshot()}
                    for item in project.snapshots
                ],
                "requirements": [
                    {
                        **item,
                        "specification": _fake_requirements(item["specification"]).to_snapshot(),
                    }
                    for item in project.requirements
                ],
                "design": [
                    {**item, "package": _fake_design(item["package"]).to_snapshot()}
                    for item in project.designs
                ],
            },
            evidence={
                "evidence": project.evidence_versions,
                "citations": self._evidence_citations(project),
            },
            evaluations=[{"runs": project.runs, "decisions": project.finding_decisions}],
            hypotheses=project.validation_hypotheses,
            outcomes=project.validation_outcomes,
            learning={"twins": self._learning_entries(project)},
            workflow_inputs=self._workflow_inputs(project),
            mockups=[
                item
                for item in project.mockups.values()
                if item.get("base_reference") and item.get("audit_reference")
            ],
        )

    def _route_why_document(self, call: _Call) -> _Answer:
        return _Answer(200, self._why_document(self._code_project(call)))

    def seed_validation_records(self, project: FakeProject, *, hypotheses=(), outcomes=()):
        from orchestwin.artifacts.human_validation import (
            hypothesis_from_snapshot,
            outcome_from_snapshot,
        )

        for restore, items in (
            (hypothesis_from_snapshot, hypotheses),
            (outcome_from_snapshot, outcomes),
        ):
            for item in items:
                record = restore(item).to_snapshot()
                if record["project_id"] != project.id or record["owner_user_id"] != str(
                    project.account.id
                ):
                    raise ValueError("validation fixture must match its project and owner")
        project.validation_hypotheses = copy.deepcopy(list(hypotheses))
        project.validation_outcomes = copy.deepcopy(list(outcomes))

    def _route_validation(self, call: _Call) -> _Answer:
        from orchestwin.validation import validation_overview

        project = self._code_project(call)
        document = validation_overview(
            document=self._why_document(project, validation_context=True),
            hypotheses=project.validation_hypotheses,
            outcomes=project.validation_outcomes,
            evidence={"evidence": project.evidence_versions},
        )
        if project.workflow_decisions or project.provided_prototypes:
            document = {**document, "workflow_inputs": self._workflow_inputs(project)}
        return _Answer(200, document)

    def _route_validation_walkthrough(self, call: _Call) -> _Answer:
        from orchestwin.validation import ValidationError, scenario_walkthrough

        try:
            return _Answer(
                200,
                scenario_walkthrough(
                    self._why_document(self._code_project(call), validation_context=True),
                    call.query.get("scenario_key", [""])[0],
                    alternative_id=call.query.get("alternative_id", [None])[0],
                    document_hash=call.query.get("document_hash", [None])[0],
                ),
            )
        except ValidationError as error:
            raise _Refusal(409, {"code": error.code}) from None

    def _route_why(self, call: _Call) -> _Answer:
        from orchestwin.why import WhyError, explain_why

        document = self._why_document(self._code_project(call))
        try:
            return _Answer(200, explain_why(document, call.query.get("code", [""])[0]))
        except WhyError as error:
            status = {"WHY_CODE_INVALID": 422, "WHY_CODE_AMBIGUOUS": 409}.get(error.code, 404)
            raise _Refusal(
                status, {"code": error.code, "candidates": list(error.candidates)}
            ) from None

    def _route_evidence_show(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        version = call.query.get("version", [None])[0]
        try:
            version = None if version is None else int(version)
        except ValueError:
            raise _Refusal(422, {"code": "EVIDENCE_INVALID_TEXT"}) from None
        source = self._evidence_source(project, call.params["evidence_id"], version)
        result = copy.deepcopy(source)
        result["citations"] = [
            item
            for item in self._evidence_citations(project)
            if item["citation"]["source_id"] == source["id"]
        ]
        if call.query.get("text") == ["true"]:
            text = project.evidence_texts.get((source["id"], source["version"]))
            if text is None:
                raise _Refusal(409, {"code": "EVIDENCE_TEXT_UNAVAILABLE"})
            result["text"] = text
        return _Answer(200, result)

    def _evidence_insert(self, call: _Call, *, revision: bool) -> _Answer:
        project = self._code_project(call)
        try:
            body = EvidenceBody.model_validate(call.json())
            text = normalize_evidence_text(body.text)
        except ResearchEvidenceError as error:
            raise _Refusal(422, {"code": error.code}) from None
        except ValueError:
            raise _Refusal(422, {"code": "EVIDENCE_INVALID_TEXT"}) from None
        if not body.acknowledged:
            raise _Refusal(422, {"code": "EVIDENCE_ACKNOWLEDGEMENT_REQUIRED"})
        if (
            len(project.evidence_versions) >= 50
            or sum(len(value.encode("utf-8")) for value in project.evidence_texts.values())
            + len(text.encode("utf-8"))
            > 1048576
        ):
            raise _Refusal(422, {"code": "EVIDENCE_LIMIT", "message": "Split the text into parts."})
        previous = self._evidence_source(project, call.params["evidence_id"]) if revision else None
        if previous is not None and previous["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        source = EvidenceVersion(
            id=UUID(self._new_id() if previous is None else previous["id"]),
            code=f"EVD-{len({item['id'] for item in project.evidence_versions}) + 1:03d}"
            if previous is None
            else previous["code"],
            version=1 if previous is None else previous["version"] + 1,
            title=body.title,
            source_kind=body.source_kind,
            source_ref=body.source_ref,
            context=body.context,
            method=body.method,
            collected_at=body.collected_at,
            limitations=body.limitations,
            empirical=body.empirical,
            content_hash=evidence_content_hash(text),
            character_count=len(text),
            byte_count=len(text.encode("utf-8")),
            created_at=self._now(),
        ).to_snapshot()
        project.evidence_versions.append(source)
        project.evidence_texts[(source["id"], source["version"])] = text
        project.fingerprint = None
        if revision:
            self._invalidate_evidence_pending(
                project, source["id"], "The evidence source has a new version."
            )
        return _Answer(
            201,
            {
                "status": "EVIDENCE_REVISED" if revision else "EVIDENCE_ADDED",
                "evidence": copy.deepcopy(source),
            },
        )

    def _route_evidence_add(self, call: _Call) -> _Answer:
        return self._evidence_insert(call, revision=False)

    def _route_evidence_revise(self, call: _Call) -> _Answer:
        return self._evidence_insert(call, revision=True)

    def _invalidate_evidence_pending(
        self, project: FakeProject, source_id: str, reason: str
    ) -> None:
        for update in project.updates:
            if (
                update["status"] == "PROPOSED"
                and update.get("evidence", {}).get("source_id") == source_id
            ):
                update["status"] = "REJECTED"
                update["decision"] = {"decided_at": _iso(self._now()), "kept": [], "reason": reason}

    def _append_evidence_profiles(self, project: FakeProject, profiles: Mapping[str, object]):
        previous = project.snapshot
        body = copy.deepcopy(previous["snapshot"])
        twins = []
        for base in body["twin_versions"]:
            profile = profiles.get(base["twin_id"])
            if profile is None:
                twins.append(base)
                continue
            twin = {
                **base,
                "id": self._new_id(),
                "version_number": base["version_number"] + 1,
                "based_on_version_number": base["version_number"],
                "created_at": _stamp(self._now()),
                "profile": profile.to_snapshot(),
                "content_hash": profile.content_hash,
            }
            project.twins[twin["twin_id"]].append(twin)
            twins.append(twin)
        body["twin_versions"] = twins
        version = {
            **previous,
            "id": self._new_id(),
            "version_number": previous["version_number"] + 1,
            "based_on_version_number": previous["version_number"],
            "created_at": _stamp(self._now()),
            "snapshot": body,
            "content_hash": _fake_modeling(body).content_hash,
        }
        project.snapshots.append(version)
        reference = self._reference(project, "twins")
        latest = project.gates.get("twins")
        if latest is not None and latest.status is not HumanGateStatus.STALE:
            stale = mark_human_gate_stale(
                latest,
                current_artifact=reference,
                occurred_at=self._now(),
                event_id=UUID(self._new_id()),
            )
            if stale.event is not None:
                self._save_gate(project, "twins", stale.gate, stale.event)
        gate = create_human_gate(
            gate_id=UUID(self._new_id()),
            project_id=UUID(project.id),
            owner_user_id=UUID(project.account.id),
            gate_type=GATE_TYPES["twins"],
            artifact=reference,
            created_at=self._now(),
        )
        for action in (HumanGateAction.SUBMIT, HumanGateAction.APPROVE):
            transition = transition_human_gate(
                gate,
                action=action,
                actor_user_id=UUID(project.account.id),
                occurred_at=self._now(),
                event_id=UUID(self._new_id()),
            )
            if transition.event is None:
                raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
            gate = transition.gate
            self._save_gate(project, "twins", gate, transition.event)
        project.fingerprint = None
        return version

    def _route_evidence_retire(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), ("reason",))
        reason = fields.text("reason", minimum=1, maximum=300)
        fields.check()
        project = self._code_project(call)
        source_id = call.params["evidence_id"]
        self._evidence_source(project, source_id)
        moment = _iso(self._now())
        for source in project.evidence_versions:
            if source["id"] == source_id and source["status"] == "ACTIVE":
                source.update(status="RETIRED", retired_at=moment, retired_reason=reason)
        self._invalidate_evidence_pending(project, source_id, "The evidence source was withdrawn.")
        affected = {
            row["twin_id"]
            for row in project.evidence_changes
            if row["source_id"] == source_id and row["retired_at"] is None
        }
        for row in project.evidence_changes:
            if row["source_id"] == source_id:
                row["retired_at"] = row["retired_at"] or moment
        profiles = {}
        review_required = bool(affected) and not self._approvals(project)["twins"]
        if affected and not review_required:
            for twin in project.snapshot["snapshot"]["twin_versions"]:
                if twin["twin_id"] not in affected:
                    continue
                profile = _fake_twin_profile(twin["profile"])
                records = [
                    row for row in project.evidence_changes if row["twin_id"] == twin["twin_id"]
                ]
                fields = {row["field"] for row in records if row["source_id"] == source_id}
                observations = [
                    withdrawn_observation(
                        observation,
                        [
                            row
                            for row in records
                            if row["field"]
                            == observation.observation_key.removeprefix("user_twin.")
                        ],
                        source_id=UUID(source_id),
                    )
                    for observation in profile.observations
                    if observation.observation_key.removeprefix("user_twin.") in fields
                ]
                profiles[twin["twin_id"]] = evidence_profile(profile, observations)
            self._append_evidence_profiles(project, profiles)
        project.fingerprint = None
        result = {
            "status": "EVIDENCE_RETIRED",
            "evidence": copy.deepcopy(self._evidence_source(project, source_id)),
            "affected_twins": sorted(affected),
        }
        if review_required:
            result["review_required"] = True
        return _Answer(200, result)

    def _route_evidence_delete(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        source_id = call.params["evidence_id"]
        self._evidence_source(project, source_id)
        body = call.json()
        if not isinstance(body, dict) or body.get("acknowledged") is not True:
            raise _Refusal(422, {"code": "EVIDENCE_ACKNOWLEDGEMENT_REQUIRED"})
        if any(
            item["id"] == source_id and item["status"] == "ACTIVE"
            for item in project.evidence_versions
        ):
            raise _Refusal(409, {"code": "EVIDENCE_RETIRE_REQUIRED"})
        for source in project.evidence_versions:
            if source["id"] == source_id:
                project.evidence_texts.pop((source_id, source["version"]), None)
                source["text_available"] = False
        project.fingerprint = None
        return _Answer(
            200,
            {
                "status": "EVIDENCE_TEXT_DELETED",
                "evidence": copy.deepcopy(self._evidence_source(project, source_id)),
            },
        )

    def _route_evidence_associate(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        body = call.json()
        if not isinstance(body, dict) or body.get("acknowledged") is not True:
            raise _Refusal(422, {"code": "EVIDENCE_ACKNOWLEDGEMENT_REQUIRED"})
        source = self._evidence_source(project, call.params["evidence_id"], body.get("version"))
        if source["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        try:
            text = normalize_evidence_text(body.get("text"))
        except ResearchEvidenceError as error:
            raise _Refusal(422, {"code": error.code}) from None
        if evidence_content_hash(text) != source["content_hash"]:
            raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
        if (
            not source["text_available"]
            and sum(len(value.encode("utf-8")) for value in project.evidence_texts.values())
            + len(text.encode("utf-8"))
            > 1048576
        ):
            raise _Refusal(422, {"code": "EVIDENCE_LIMIT", "message": "Split the text into parts."})
        project.evidence_texts[(source["id"], source["version"])] = text
        source["text_available"] = True
        project.fingerprint = None
        return _Answer(
            200, {"status": "EVIDENCE_TEXT_REASSOCIATED", "evidence": copy.deepcopy(source)}
        )

    def _route_propose_update(self, call: _Call) -> _Answer:
        fields = _Fields(call.json(), UPDATE_FIELDS)
        locale = fields.pattern(
            "locale",
            LOCALE_PATTERN,
            required=False,
            minimum=2,
            maximum=MAX_LOCALE_LENGTH,
            default=DEFAULT_LOCALE,
        )
        source_id = fields.identifier("evidence_id", required=False, nullable=True)
        source_version = fields.integer("evidence_version", required=False, minimum=1)
        fields.check()
        return self._later(
            call,
            "TWIN_UPDATE",
            {
                "locale": locale,
                **(
                    {"evidence_id": source_id, "evidence_version": source_version}
                    if source_id is not None
                    else {}
                ),
            },
            lambda: self._proposed_update(
                call, str(locale), evidence_id=source_id, evidence_version=source_version
            ),
        )

    def _proposed_update(
        self, call: _Call, locale: str, *, evidence_id=None, evidence_version=None
    ) -> _Answer:
        project = self._code_project(call)
        twin = self._learning_twin(project, call.params["twin_id"])
        if evidence_id is not None:
            return self._proposed_evidence_update(
                project, twin, locale, evidence_id, evidence_version
            )
        reference = self._alignment_reference(project)
        if reference["requirements"] is None:
            raise _Refusal(409, {"code": "REQUIREMENTS_APPROVAL_REQUIRED"})
        if reference["design"] is None:
            raise _Refusal(409, {"code": "DESIGN_APPROVAL_REQUIRED"})
        twin_id = str(twin["twin_id"])
        self._refuse_pending(project, twin_id)
        changes, tests = self._new_material(project, twin_id)
        if not changes and not tests:
            raise _Refusal(409, {"code": "TWIN_UPDATE_NOTHING_NEW"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TWIN_UPDATE_MODEL_NOT_CONFIGURED"})
        self._record(project, "TWIN_UPDATE")
        changes, tests = changes[:MAX_UPDATE_CHANGES], tests[:MAX_UPDATE_TESTS]
        observations = self._proposal(project, twin, changes, tests, _locale_language(locale))
        update = self._update_of(
            project,
            twin,
            locale,
            observations,
            {"changes": len(changes), "tests": len(tests)},
            COSTS["TWIN_UPDATE"],
        )
        project.updates.insert(0, update)
        return _Answer(201, {"status": "PROPOSED", "update": copy.deepcopy(update)})

    def _proposed_evidence_update(self, project, twin, locale, source_id, source_version):
        self._refuse_pending(project, str(twin["twin_id"]))
        source = self._evidence_source(project, source_id, source_version)
        latest = self._evidence_source(project, source_id)
        if source["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        if source["version"] != latest["version"]:
            raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
        text = project.evidence_texts.get((source_id, source["version"]))
        if text is None:
            raise _Refusal(409, {"code": "EVIDENCE_TEXT_UNAVAILABLE"})
        if not self.hosted:
            raise _Refusal(503, {"code": "TWIN_UPDATE_MODEL_NOT_CONFIGURED"})
        it = _locale_language(locale) == "it"
        passages = [(index, line) for index, line in enumerate(text.split("\n"), 1) if line.strip()]
        candidates = []
        fields = ("goals", "context_of_use", "preferred_vocabulary")
        effects = ("SUPPORTS", "CONTRADICTS", "ADDS")
        current = {
            item["observation_key"]: item["value"] for item in twin["profile"]["observations"]
        }
        for index, (line, quote) in enumerate(passages[:3]):
            field, effect = fields[index], effects[index]
            value = copy.deepcopy(current.get(f"user_twin.{field}"))
            if effect == "ADDS":
                value = _items_value([" ".join(quote.split())[:300]])
            elif value is None or value.get("kind") not in ("TEXT", "ITEMS"):
                continue
            value.pop("reason", None)
            candidates.append(
                {
                    "statement": (
                        "Interpretazione di prova della fonte "
                        if it
                        else "Test interpretation of the source "
                    )
                    + str(index + 1),
                    "basis": "Citazione da testo di prova, senza validazione umana."
                    if it
                    else "Quotation from test text, without human validation.",
                    "effect": effect,
                    "field": field,
                    "value": value,
                    "quote": quote[:1000],
                    "line": line,
                }
            )
        context = evidence_update_context(
            project_id=project.id, locale=locale, twin=twin, evidence=source, text=text
        )
        comment, observations, rejected = bind_evidence_update(
            EvidenceUpdateOutput(
                comment="Proposte simulate da testo di prova; il proprietario decide."
                if it
                else "Simulated proposals from test text; the owner decides.",
                changes=candidates,
            ),
            context=context,
        )
        self._record(project, "TWIN_UPDATE")
        update = self._update_of(
            project,
            twin,
            locale,
            [item.to_snapshot() for item in observations],
            {"changes": 0, "tests": 0},
            COSTS["TWIN_UPDATE"],
        )
        update["comment"] = comment
        update["evidence"] = {
            "source_id": source_id,
            "source_version": source["version"],
            "content_hash": source["content_hash"],
            "rejected_changes": rejected,
        }
        project.updates.insert(0, update)
        return _Answer(201, {"status": "PROPOSED", "update": copy.deepcopy(update)})

    def _route_twin_update(self, call: _Call) -> _Answer:
        project = self._code_project(call)
        return _Answer(200, copy.deepcopy(self._find_update(project, call.params["update_id"])))

    def _route_decide_update(self, call: _Call) -> _Answer:
        decision, kept, reason = _update_decision_of(call.json())
        project = self._code_project(call)
        update = self._find_update(project, call.params["update_id"])
        if update["status"] != "PROPOSED":
            raise _Refusal(409, {"code": "TWIN_UPDATE_ALREADY_DECIDED"})
        twin_id = str(update["twin_id"])
        twin = self._named_twin(
            project, twin_id, update["twin_name"], update["base"]["profile_version_number"]
        )
        development = project.development.get(twin_id, 0)
        approving = decision == "APPROVE"
        if approving and development != update["base"]["development_version_number"]:
            raise _Refusal(409, {"code": "TWIN_UPDATE_CONTEXT_CHANGED"})
        if (
            approving
            and not update.get("evidence")
            and self._active_count(project, twin_id) + len(kept) > (MAX_LEARNED_OBSERVATIONS)
        ):
            raise _Refusal(409, {"code": "TWIN_OBSERVATIONS_LIMIT"})
        proposed = update["observations"]
        position = next(
            (place for place, item in enumerate(kept) if item["index"] >= len(proposed)), None
        )
        if position is not None:
            raise _Refusal(
                422,
                {
                    "code": "invalid_request",
                    "errors": [
                        {
                            "loc": ["body", "kept", position, "index"],
                            "type": "value_error",
                            "msg": UNKNOWN_INDEX,
                        }
                    ],
                },
            )
        moment = _iso(self._now())
        if approving and update.get("evidence"):
            twin = self._decide_evidence_update(project, twin, update, kept)
        elif approving:
            for item in sorted(kept, key=lambda entry: int(entry["index"])):
                observation = dict(proposed[item["index"]])
                if item["statement"] is not None:
                    observation["statement"] = item["statement"]
                self._add_observation(
                    project,
                    twin,
                    observation,
                    source="TWIN_CRITIQUE",
                    version=development + 1,
                    moment=moment,
                    update_id=str(update["id"]),
                )
            project.development[twin_id] = development + 1
        update["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
        update["decision"] = {
            "decided_at": moment,
            "kept": sorted(int(item["index"]) for item in kept),
            "reason": reason,
        }
        return _Answer(
            200,
            {
                "status": "DECIDED",
                "update": copy.deepcopy(update),
                "twin": self._learning_entry(project, twin),
            },
        )

    def _decide_evidence_update(self, project, twin, update, kept):
        twin = self._learning_twin(project, str(twin["twin_id"]))
        reference = update["evidence"]
        source = self._evidence_source(project, reference["source_id"], reference["source_version"])
        latest = self._evidence_source(project, reference["source_id"])
        if source["status"] != "ACTIVE":
            raise _Refusal(409, {"code": "EVIDENCE_RETIRED"})
        if (
            latest["version"] != source["version"]
            or source["content_hash"] != reference["content_hash"]
            or twin["version_number"] != update["base"]["profile_version_number"]
        ):
            raise _Refusal(409, {"code": "TWIN_UPDATE_CONTEXT_CHANGED"})
        text = project.evidence_texts.get((source["id"], source["version"]))
        if text is None:
            raise _Refusal(409, {"code": "EVIDENCE_TEXT_UNAVAILABLE"})
        domain_source = EvidenceVersion(
            **{
                key: value
                for key, value in source.items()
                if key
                not in {"id", "source_kind", "status", "created_at", "retired_at", "imported_from"}
            },
            id=UUID(source["id"]),
            source_kind=EvidenceSourceKind(source["source_kind"]),
            status=EvidenceStatus(source["status"]),
            created_at=datetime.fromisoformat(source["created_at"]),
            retired_at=None
            if source["retired_at"] is None
            else datetime.fromisoformat(source["retired_at"]),
        )
        profile = _fake_twin_profile(twin["profile"])
        observations, rows, touched = [], [], set()
        for item in kept:
            proposal = update["observations"][item["index"]]
            change = EvidenceChange.from_snapshot(proposal["evidence"])
            if change.field in touched or not change.citation.verify(text):
                raise _Refusal(409, {"code": "EVIDENCE_CONTEXT_CHANGED"})
            touched.add(change.field)
            before = profile.observation_for(change.field)
            after = apply_evidence_change(
                before,
                change,
                domain_source,
                statement=item["statement"],
                rationale=proposal["basis"],
            )
            observations.append(after)
            rows.append(
                {
                    "twin_id": twin["twin_id"],
                    "twin_version": twin["version_number"] + 1,
                    "field": change.field.value,
                    "source_id": str(change.citation.source_id),
                    "source_version": change.citation.source_version,
                    "change": change.to_snapshot(),
                    "before": None if before is None else before.to_snapshot(),
                    "after": after.to_snapshot(),
                    "retired_at": None,
                }
            )
        updated = evidence_profile(profile, observations)
        snapshot = self._append_evidence_profiles(project, {twin["twin_id"]: updated})
        project.evidence_changes.extend(rows)
        return next(
            item
            for item in snapshot["snapshot"]["twin_versions"]
            if item["twin_id"] == twin["twin_id"]
        )

    def _route_learn(self, call: _Call) -> _Answer:
        observation = _owner_observation_of(call.json())
        project = self._code_project(call)
        twin = self._learning_twin(project, call.params["twin_id"])
        twin_id = str(twin["twin_id"])
        if self._active_count(project, twin_id) >= MAX_LEARNED_OBSERVATIONS:
            raise _Refusal(409, {"code": "TWIN_OBSERVATIONS_LIMIT"})
        self._refuse_pending(project, twin_id)
        version = project.development.get(twin_id, 0) + 1
        self._add_observation(
            project,
            twin,
            observation,
            source="OWNER",
            version=version,
            moment=_iso(self._now()),
            update_id=None,
        )
        project.development[twin_id] = version
        return _Answer(201, {"status": "LEARNED", "twin": self._learning_entry(project, twin)})

    def _route_retire_observation(self, call: _Call) -> _Answer:
        reason = _retire_reason_of(call.json())
        project = self._code_project(call)
        twin = self._learning_twin(project, call.params["twin_id"])
        twin_id = str(twin["twin_id"])
        number = _observation_number(call.params["code"])
        observation = next(
            (
                item
                for item in project.learned
                if item["twin_id"] == twin_id
                and item["retired"] is None
                and _code_number(item["code"]) == number
            ),
            None,
        )
        if observation is None:
            raise _Refusal(404, {"code": "TWIN_OBSERVATION_NOT_FOUND"})
        self._refuse_pending(project, twin_id)
        version = project.development.get(twin_id, 0) + 1
        observation["retired"] = {
            "retired_in_version": version,
            "retired_at": _iso(self._now()),
            "reason": reason,
        }
        project.development[twin_id] = version
        return _Answer(200, {"status": "RETIRED", "twin": self._learning_entry(project, twin)})

    def _seed_twin(self, project: FakeProject, twin: int | str) -> dict[str, object]:
        twins = self._approved_twins(project)
        if not twins:
            raise ValueError("the twins of the project are not approved")
        if isinstance(twin, bool) or not isinstance(twin, int | str):
            raise ValueError("name the twin by its position or its twin_id")
        if isinstance(twin, int):
            if not 0 <= twin < len(twins):
                raise ValueError(f"the project has no twin at position {twin}")
            return twins[twin]
        found = next((item for item in twins if item["twin_id"] == twin), None)
        if found is None:
            raise ValueError(f"the project has no approved twin {twin}")
        return found

    def _seed_locale(self) -> str:
        return "it-IT" if self.language == "it" else "en-US"

    def _seed_ground(self, project: FakeProject) -> dict[str, object]:
        reference = self._alignment_reference(project)
        if reference["requirements"] is None or reference["design"] is None:
            raise ValueError("the project needs approved requirements and an approved design")
        return reference

    def _seed_twins(self, project: FakeProject) -> list[dict[str, object]]:
        twins = self._approved_twins(project)
        if not twins:
            raise ValueError("a review needs the approved twins")
        return twins

    def _seed_commit(self, project: FakeProject) -> str:
        number = len(project.code_changes)
        known = {str(item["commit"]) for item in project.code_changes}
        while True:
            number += 1
            seed = f"orchestwin-fake-seed:{project.id}:{number}".encode()
            commit = hashlib.sha256(seed).hexdigest()[:40]
            if commit not in known:
                return commit

    def _seed_change(
        self, project: FakeProject, message: str | None, commit: str | None, reviewed: bool
    ) -> dict[str, object]:
        chosen = self._seed_commit(project) if commit is None else commit.lower()
        if COMMIT_PATTERN.fullmatch(chosen) is None:
            raise ValueError("a commit holds 7 to 64 hexadecimal characters")
        if any(item["commit"] == chosen for item in project.code_changes):
            raise ValueError(f"the commit {chosen} is already recorded")
        text = SEED_TEXTS[self.language]["message"] if message is None else _text_block(message)
        reference = self._seed_ground(project) if reviewed else None
        twins = self._seed_twins(project) if reviewed else []
        parent = str(project.code_changes[0]["commit"]) if project.code_changes else None
        record: dict[str, object] = {
            "commit": chosen,
            "parent": parent,
            "committed_at": _iso(self._now()),
            "author": SEED_AUTHOR,
            "message": text,
            "files": [dict(SEED_FILE)],
            "recorded_at": _iso(self._now()),
            "decision": None,
            "diff": SEED_DIFF,
            "aligned": None,
        }
        project.code_changes.append(record)
        project.code_changes.sort(key=_recorded_order, reverse=True)
        if reference is not None:
            cost = len(twins) * COSTS["CODE_CHANGE_REVIEW"] + COSTS["CODE_ALIGNMENT"]
            self._stored_change_run(project, record, twins, self._seed_locale(), reference, cost)
        return self._change_payload(project, record)

    def _seed_test_run(
        self, project: FakeProject, *, failed: bool, reviewed: bool
    ) -> dict[str, object]:
        reference = self._seed_ground(project)
        twins = self._seed_twins(project) if reviewed else []
        specification = project.specification
        if specification is None:
            raise ValueError("the project needs approved requirements")
        locale = self._seed_locale()
        body = {
            "locale": locale,
            "application": {"kind": "STATIC", "address": SEED_ADDRESS},
            "snapshot": {
                "url": SEED_PAGE,
                "title": project.name,
                "text": project.name,
                "hidden_text": "",
                "elements": [],
            },
            "criteria": None,
            "earlier": None,
        }
        wanted = [
            (str(item["code"]), str(item["statement"]))
            for item in specification["specification"]["acceptance_criteria"]
        ]
        plan = self._test_plan(body, reference, wanted, 1)
        project.acceptance_plans.insert(0, plan)
        project.acceptance_plan_requests.insert(0, _copy(body))
        results = [
            _seeded_result(path, "FAILED" if failed and position == 0 else "PASSED", project.name)
            for position, path in enumerate(plan["paths"])
        ]
        uncovered = copy.deepcopy(plan["not_covered"])
        outcomes = _criteria_outcomes([plan], results, uncovered)
        record: dict[str, object] = {
            "id": self._new_id(),
            "started_at": _iso(self._now()),
            "finished_at": _iso(self._now()),
            "recorded_at": _iso(self._now()),
            "application": {"kind": "STATIC", "address": SEED_ADDRESS},
            "browsers": [dict(SEED_BROWSER)],
            "reference": copy.deepcopy(plan["reference"]),
            "summary": _run_summary(outcomes),
            "criteria": outcomes,
            "not_covered": uncovered,
            "results": results,
            "critiques": [],
            "reviewed_at": None,
            "cost_microusd": int(plan["cost_microusd"]),
        }
        project.acceptance_runs.insert(0, record)
        if twins:
            cost = len(twins) * COSTS["TEST_REVIEW"]
            self._stored_test_review(project, record, twins, locale, cost)
        return self._test_run_payload(project, record)

    def _seed_version(self, project: FakeProject, stage: str) -> dict[str, object]:
        approvals = self._approvals(project)
        if stage == "design":
            design = project.design
            if design is None or not approvals["design"]:
                raise ValueError("the design of the project is not approved")
            version = self._append_design(
                project, copy.deepcopy(design["package"]), project.account
            )
        elif stage == "requirements":
            specification = project.specification
            if specification is None or not approvals["requirements"]:
                raise ValueError("the requirements of the project are not approved")
            version = self._append_requirements(
                project, copy.deepcopy(specification["specification"]), project.account
            )
        else:
            raise ValueError("stage must be requirements or design")
        self._approve(project, stage)
        return _copy(version)

    def _seed_perspective_change(self, project: FakeProject, agent_id: str) -> dict[str, object]:
        team = project.team
        if team is None or not self._approvals(project)["team"]:
            raise ValueError("the perspectives of the project are not approved")
        units = {
            str(unit["agent_id"]): bool(unit["editable"])
            for perspective in team["perspectives"]
            for unit in (perspective, *perspective["aspects"])
            if unit["agent_id"] is not None
        }
        if agent_id not in units:
            raise ValueError(f"{agent_id} does not switch a perspective or an aspect")
        if not units[agent_id]:
            raise ValueError(f"the brief does not let the owner switch {agent_id}")
        current = list(team["selected_agent_ids"])
        selected = (
            [agent for agent in current if agent != agent_id]
            if agent_id in current
            else [*current, agent_id]
        )
        content = self._team_content(
            project,
            project.brief,
            selected,
            list(team["members"]),
            {},
            {key: team[key] for key in RULE_KEYS},
            owner=True,
        )
        self._append_team(project, content, "OWNER_EDITED", project.account)
        self._seed_approval(project, "team")
        return _copy(self._sections(project))

    def _seed_requirements_change(self, project: FakeProject) -> dict[str, object]:
        current = project.specification
        if current is None or not self._approvals(project)["requirements"]:
            raise ValueError("the requirements of the project are not approved")
        if self._pending_requirements_diff(project) is not None:
            raise ValueError("a proposed change of the requirements waits for its decision")
        proposed, _ = self._with_requirement(
            current["specification"], SEED_TEXTS[self.language]["requirement"]
        )
        self._append_requirements(project, proposed, project.account)
        self._seed_approval(project, "requirements")
        return _copy(self._sections(project))

    def _seed_brief_change(self, project: FakeProject) -> dict[str, object]:
        version = project.brief
        if version is None or not self._approvals(project)["brief"]:
            raise ValueError("the brief of the project is not approved")
        goal = SEED_TEXTS[self.language]["goal"]
        goals = version.brief.value_for(BriefField.GOALS) or ()
        if goal in goals:
            raise ValueError("the brief already holds the seeded goal")
        unknown = set(version.brief.unknown_fields)
        unknown.discard(BriefField.GOALS)
        changed = replace(version.brief, goals=(*goals, goal), unknown_fields=frozenset(unknown))
        self._append_brief(project, changed, project.account)
        self._seed_approval(project, "brief")
        return _copy(self._sections(project))

    def _seed_requirement_removed(self, project: FakeProject) -> dict[str, object]:
        current, design = project.specification, project.design
        approvals = self._approvals(project)
        if current is None or design is None or not approvals["requirements"]:
            raise ValueError("the project needs approved requirements and a design")
        if not approvals["design"]:
            raise ValueError("the design of the project is not approved")
        if self._pending_requirements_diff(project) is not None:
            raise ValueError("a proposed change of the requirements waits for its decision")
        specification = current["specification"]
        cited = _cited_ids(design["package"])
        removed = next(
            (item for item in reversed(specification["requirements"]) if str(item["id"]) in cited),
            None,
        )
        if removed is None or len(specification["requirements"]) < 2:
            raise ValueError("the design cites no requirement that can be removed")
        proposed = _without_requirement(specification, str(removed["id"]))
        self._append_requirements(project, proposed, project.account)
        self._seed_approval(project, "requirements")
        return _copy(self._sections(project))

    def _seed_design_revision(self, project: FakeProject) -> dict[str, object]:
        design = project.design
        if design is None or not self._approvals(project)["design"]:
            raise ValueError("the design of the project is not approved")
        package = copy.deepcopy(design["package"])
        assertion = SEED_TEXTS[self.language]["assertion"]
        if assertion in package["owner_assertions"]:
            raise ValueError("the design already holds the seeded assertion")
        package["owner_assertions"] = [*package["owner_assertions"], assertion]
        self._seeded(lambda: self._design_diff(project, design, package, project.account))
        return _copy(self._sections(project))

    def _seed_tasks(self, project: FakeProject) -> list[dict[str, object]]:
        twin_id = str(self._seed_twins(project)[0]["twin_id"])
        texts = SEED_TEXTS[self.language]
        change = next(
            (
                record
                for record in project.code_changes
                if _has_findings(self._latest_run(project, record["commit"]), twin_id)
            ),
            None,
        )
        if change is None:
            commit = str(self._seed_change(project, None, None, True)["commit"])
            change = next(item for item in project.code_changes if item["commit"] == commit)
        reviewed = self._latest_reviewed_run(project)
        if reviewed is not None and _has_findings(reviewed[1], twin_id):
            run_id = str(reviewed[0]["id"])
        else:
            run_id = str(self._seed_test_run(project, failed=True, reviewed=True)["id"])
        self._decide(project, change, "CODE_TASKS", None, [texts["verdict_task"]], [])
        verdict = project.code_tasks[-1]
        items = [
            {
                "text": None,
                "source": {
                    "kind": "CODE_CHANGE",
                    "commit": change["commit"],
                    "twin_id": twin_id,
                    "finding": 0,
                },
            },
            {
                "text": None,
                "source": {
                    "kind": "TEST_RUN",
                    "test_run_id": run_id,
                    "twin_id": twin_id,
                    "finding": 0,
                },
            },
            {"text": texts["owner_task"], "source": {"kind": "OWNER"}},
        ]
        _, tasks = self._created_tasks(project, _task_items({"tasks": items}))
        return copy.deepcopy([verdict, *tasks])

    def _seed_learning(
        self,
        project: FakeProject,
        twin: int | str,
        statements: Sequence[str] | None,
        source: str,
    ) -> dict[str, object]:
        if source not in ("TWIN_CRITIQUE", "OWNER"):
            raise ValueError("source must be TWIN_CRITIQUE or OWNER")
        chosen = self._seed_twin(project, twin)
        twin_id = str(chosen["twin_id"])
        defaults = SEED_TEXTS[self.language]["observations"]
        wanted = (
            [statement for statement, _ in defaults]
            if statements is None
            else [_cut_line(statement, MAX_OBSERVATION_LENGTH) for statement in statements]
        )
        if not wanted or (source == "TWIN_CRITIQUE" and len(wanted) > MAX_UPDATE_OBSERVATIONS):
            raise ValueError(f"give 1 to {MAX_UPDATE_OBSERVATIONS} statements")
        _valid_statements(wanted)
        if self._pending_update(project, twin_id) is not None:
            raise ValueError("a proposal of the twin waits for its decision")
        if self._active_count(project, twin_id) + len(wanted) > MAX_LEARNED_OBSERVATIONS:
            raise ValueError(f"a twin keeps at most {MAX_LEARNED_OBSERVATIONS} observations")
        material = self._seed_material(project, twin_id) if source == "TWIN_CRITIQUE" else {}
        moment = _iso(self._now())
        observations = [
            {
                "index": index,
                "statement": statement,
                "basis": None if source == "OWNER" else defaults[index % len(defaults)][1],
                "about": {"requirement": None, "screen": None},
                "contradicts_profile": None,
            }
            for index, statement in enumerate(wanted)
        ]
        if source == "OWNER":
            for observation in observations:
                version = project.development.get(twin_id, 0) + 1
                self._add_observation(
                    project,
                    chosen,
                    observation,
                    source="OWNER",
                    version=version,
                    moment=moment,
                    update_id=None,
                )
                project.development[twin_id] = version
            return self._learning_entry(project, chosen)
        update = self._update_of(
            project, chosen, self._seed_locale(), observations, material, COSTS["TWIN_UPDATE"]
        )
        version = project.development.get(twin_id, 0) + 1
        for observation in observations:
            self._add_observation(
                project,
                chosen,
                observation,
                source="TWIN_CRITIQUE",
                version=version,
                moment=moment,
                update_id=str(update["id"]),
            )
        project.development[twin_id] = version
        update["status"] = "APPROVED"
        update["decision"] = {
            "decided_at": moment,
            "kept": [int(item["index"]) for item in observations],
            "reason": None,
        }
        project.updates.insert(0, update)
        return self._learning_entry(project, chosen)

    def _seed_update(
        self,
        project: FakeProject,
        twin: int | str,
        observations: Sequence[Mapping[str, object]] | None,
    ) -> dict[str, object]:
        chosen = self._seed_twin(project, twin)
        twin_id = str(chosen["twin_id"])
        if self._pending_update(project, twin_id) is not None:
            raise ValueError("a proposal of the twin already waits for its decision")
        defaults = SEED_TEXTS[self.language]["observations"]
        given = (
            [{"statement": statement, "basis": basis} for statement, basis in defaults]
            if observations is None
            else [dict(item) for item in observations]
        )
        if len(given) > MAX_UPDATE_OBSERVATIONS:
            raise ValueError(f"a proposal holds at most {MAX_UPDATE_OBSERVATIONS} observations")
        proposed = []
        for index, item in enumerate(given):
            if not isinstance(item.get("statement"), str):
                raise ValueError("every observation needs a statement")
            about = item.get("about") or {}
            contradicts = item.get("contradicts_profile")
            proposed.append(
                {
                    "index": index,
                    "statement": _cut_line(str(item["statement"]), MAX_OBSERVATION_LENGTH),
                    "basis": _cut_line(
                        str(item.get("basis") or defaults[index % len(defaults)][1]),
                        MAX_BASIS_LENGTH,
                    ),
                    "about": {
                        "requirement": about.get("requirement"),
                        "screen": about.get("screen"),
                    },
                    "contradicts_profile": None
                    if contradicts is None
                    else _cut_line(str(contradicts), MAX_BASIS_LENGTH),
                }
            )
        _valid_statements([str(item["statement"]) for item in proposed])
        material = self._seed_material(project, twin_id)
        update = self._update_of(
            project, chosen, self._seed_locale(), proposed, material, COSTS["TWIN_UPDATE"]
        )
        project.updates.insert(0, update)
        return copy.deepcopy(update)

    def _seed_material(self, project: FakeProject, twin_id: str) -> dict[str, int]:
        changes, tests = self._new_material(project, twin_id)
        if not changes and not tests:
            raise ValueError(
                "the twin has no new material: seed a reviewed change or test run first"
            )
        return {
            "changes": min(len(changes), MAX_UPDATE_CHANGES),
            "tests": min(len(tests), MAX_UPDATE_TESTS),
        }

    def _knowledge_folder(
        self, project: FakeProject, present: Sequence[str], number: int, moment: datetime
    ):
        from types import SimpleNamespace

        from orchestwin.artifacts.design_evaluation import design_evaluation_run_from_snapshot
        from orchestwin.artifacts.design_finding_validations import finding_validation_from_snapshot
        from orchestwin.knowledge.sources import knowledge_feedback
        from orchestwin.knowledge.validation_records import preserve_import_history

        origin = None
        if project.origin is not None:
            metadata = project.origin["origin"]
            origin = SimpleNamespace(
                source_project_id=metadata["project_id"],
                package_version=metadata["package_version"],
                package_content_hash=metadata["package_content_hash"],
                omitted_sections=project.origin.get("omitted_sections", ()),
                import_limits=project.origin.get("import_limits", ()),
            )

        documents = {}
        for stage in present:
            version = copy.deepcopy(project.artifact(stage))
            if stage == "brief":
                version["brief"] = project.brief.brief.to_snapshot()
            elif stage == "team":
                version["proposal"] = _fake_team_proposal(version).to_snapshot()
                if version["revision_kind"] == "PROPOSER_GENERATED":
                    version["based_on_version_number"] = None
            elif stage == "twins":
                version["snapshot"] = _fake_modeling(version["snapshot"]).to_snapshot()
            elif stage == "requirements":
                version["specification"] = _fake_requirements(
                    version["specification"]
                ).to_snapshot()
            elif stage == "design":
                version["package"] = _fake_design(version["package"]).to_snapshot()
            documents[stage] = version
        versions = stage_versions(documents)
        values = {
            "project_id": UUID(project.id),
            "project_name": project.name,
            "state": self._state_sources(project, present[-1]),
            "research_evidence": self._evidence_dossier(project),
            "validation_records": preserve_import_history(
                {
                    "hypotheses": project.validation_hypotheses,
                    "outcomes": project.validation_outcomes,
                },
                origin,
            ),
            "feedback": knowledge_feedback(
                runs=(design_evaluation_run_from_snapshot(item) for item in project.runs),
                validations=(
                    finding_validation_from_snapshot(item) for item in project.finding_decisions
                ),
            ),
        }
        for stage, version in versions.items():
            name = "modeling" if stage == "twins" else stage
            values[name] = version
            values[f"{name}_gate"] = project.gates[stage]
        return build_knowledge_folder(
            KnowledgeSources(**values), version_number=number, created_at=moment
        )

    def _state_sources(self, project: FakeProject, through: str) -> ProjectStateSources:
        frame = {
            "reference": self._current_reference(project) if through == "design" else None,
            "twins": tuple(
                {
                    "twin_id": twin["twin_id"],
                    "twin_name": twin["profile"]["name"],
                    "profile_version_number": twin["version_number"],
                }
                for twin in (
                    []
                    if project.snapshot is None
                    or through not in ("twins", "requirements", "design")
                    else project.snapshot["snapshot"]["twin_versions"]
                )
            ),
        }
        return ProjectStateSources(
            aligned=self._aligned(project),
            changes=tuple(
                self._change_payload(project, record, frame) for record in project.code_changes
            ),
            runs=tuple(copy.deepcopy(run) for run in project.change_runs),
            tasks=tuple(copy.deepcopy(task) for task in project.code_tasks),
            tests=tuple(
                self._test_run_payload(project, record)
                for record in project.acceptance_runs[:MAX_FOLDER_TEST_RUNS]
            ),
            learning=self._folder_learning(project, frame),
        )

    def _folder_learning(
        self, project: FakeProject, frame: Mapping[str, object]
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                **entry,
                "twin_id": twin["twin_id"],
                "twin_name": twin["twin_name"],
                "profile_version_number": twin["profile_version_number"],
                "label": f"{twin['profile_version_number']}.{entry['development_version_number']}",
            }
            for entry, twin in zip(self._learning_entries(project), frame["twins"], strict=False)
        )

    def _seed(
        self,
        project: FakeProject,
        through: str,
        *,
        approve: bool,
        dropped: Sequence[str] = (),
        requirements_schema_version: int = 2,
    ) -> None:
        account = project.account
        steps = STAGES[: STAGES.index(through) + 1]
        texts = SEED_BRIEF[self.language]
        provided = {
            "name": project.name,
            "description": texts["description"],
            "problem": texts["problem"],
            "goals": texts["goals"],
            "target_users": PERSONAS[self.language][: self.twins],
            "functional_requirements": texts["functional_requirements"],
            "domain": texts["domain"],
        }
        unknown = {item for item in BriefField if item.value not in provided}
        self._append_brief(
            project, create_project_brief(**provided, unknown_fields=unknown), account
        )
        if approve:
            self._approve(project, "brief")
        if "team" not in steps:
            return
        brief = project.brief
        assert brief is not None
        constraints = self._team_rules(project, brief, dropped)
        self._append_team(
            project,
            self._generated_team(project, brief, constraints, dropped),
            "PROPOSER_GENERATED",
            account,
        )
        if approve:
            self._approve(project, "team")
        if "twins" not in steps:
            return
        for persona in self._propose_personas(project, account):
            versions = project.personas[str(persona["persona_id"])]
            self._decide_persona(project, versions, "CONFIRM", None, account)
        self._create_twins(project, self._current_personas(project), account)
        if approve:
            self._approve(project, "twins")
        if "requirements" not in steps:
            return
        self._append_requirements(
            project,
            self._specification(project, schema_version=requirements_schema_version),
            account,
        )
        if approve:
            self._approve(project, "requirements")
        if "design" not in steps:
            return
        package = self._design_package(project)
        chosen = str(package["recommended_alternative_id"])
        self._append_design(project, package, account)
        selected = self._mockup_package(project, package, chosen, [])
        design = self._append_design(project, selected, account)
        if self.hosted:
            project.mockups[chosen] = {
                "status": "MOCKUP_GENERATED",
                "generation_id": self._new_id(),
                "design_version_id": design["id"],
                "design_content_hash": design["content_hash"],
                "package": copy.deepcopy(selected),
                "approach": APPROACHES[self.language][0],
                "changes": [],
                "warnings": _mockup_warnings(selected, project.specification["specification"]),
                "cost_microusd": COSTS["MOCKUP"],
            }
        if approve:
            self._approve(project, "design")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    block_on_close = True

    def __init__(self, studio: FakeStudio) -> None:
        self.studio = studio
        super().__init__(("127.0.0.1", 0), _Handler)

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

    def handle_error(self, request: object, client_address: object) -> None:
        self.studio._record_error(traceback.format_exc())


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeStudio/1"
    sys_version = ""
    timeout = 30

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def do_PATCH(self) -> None:
        self._serve()

    def do_PUT(self) -> None:
        self._serve()

    def do_DELETE(self) -> None:
        self._serve()

    def _serve(self) -> None:
        length = self.headers.get("Content-Length", "0")
        size = int(length) if length.isdecimal() else 0
        raw = self.rfile.read(size) if size > 0 else b""
        headers = {name.lower(): value for name, value in self.headers.items()}
        studio = self.server.studio
        answer = studio._handle(self.command, self.path, headers, raw)
        content = answer.content()
        self.send_response(answer.status)
        self.send_header("Content-Type", answer.content_type)
        if answer.status != 204:
            self.send_header("Content-Length", str(len(content)))
        for name, value in answer.headers.items():
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if content:
            self.wfile.write(content)
        self.close_connection = True


def _compile(template: str) -> re.Pattern[str]:
    return re.compile(TEMPLATE_PARAMETER.sub(r"(?P<\1>[^/]+)", template))


def _path_parameters(values: Mapping[str, str]) -> dict[str, str]:
    errors = []
    parsed: dict[str, str] = {}
    for name, value in values.items():
        if name == "version_number":
            if re.fullmatch(r"[+-]?[0-9]+", value) is None:
                errors.append(_error(("path", name), "int_parsing"))
            else:
                parsed[name] = str(int(value))
            continue
        if name in ("commit", "code"):
            parsed[name] = value
            continue
        try:
            parsed[name] = str(UUID(value))
        except ValueError:
            errors.append(_error(("path", name), "uuid_parsing"))
    if errors:
        raise _Invalid(errors)
    return parsed


def _query_identifier(call: _Call, name: str) -> str:
    value = call.value(name)
    if value is None:
        raise _Invalid([_error(("query", name), "missing")])
    try:
        return str(UUID(value))
    except ValueError as error:
        raise _Invalid([_error(("query", name), "uuid_parsing")]) from error


def _error(location: Sequence[object], kind: str) -> dict[str, object]:
    return {"loc": list(location), "type": kind}


def _text_error(
    item: object,
    minimum: int,
    maximum: int | None,
    expression: re.Pattern[str] | None = None,
) -> str | None:
    if not isinstance(item, str):
        return "string_type"
    if len(item) < minimum:
        return "string_too_short"
    if maximum is not None and len(item) > maximum:
        return "string_too_long"
    if expression is not None and expression.fullmatch(item) is None:
        return "string_pattern_mismatch"
    return None


def _control_free(value: str) -> bool:
    return all(ord(character) >= 32 and ord(character) != 127 for character in value)


def _single_line(value: object) -> str:
    normalized = " ".join(str(value).split())
    if not normalized or not _control_free(normalized):
        raise ValueError("the text must be one visible line")
    return normalized


def _text_block(value: object) -> str:
    normalized = str(value).strip()
    if not normalized or "\x00" in normalized:
        raise ValueError("the text must hold visible characters")
    return normalized


def _optional_line(value: object) -> str | None:
    return None if value is None or not str(value).strip() else _single_line(value)


def _optional_block(value: object) -> str | None:
    return None if value is None or not str(value).strip() else _text_block(value)


def _changed_path(value: object) -> str:
    path = str(value)
    if not path.strip() or not _control_free(path):
        raise ValueError("the path must be visible")
    return path


def _diff_text(value: object) -> str:
    diff = str(value)
    if "\x00" in diff:
        raise ValueError("the diff must not hold a null character")
    return diff


def _task_texts(value: object) -> list[str]:
    return [_single_line(item) for item in value] if isinstance(value, list) else []


def _lax_integer(value: object) -> tuple[str | None, int]:
    if isinstance(value, bool | int):
        return None, int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "finite_number", 0
        return (None, int(value)) if value.is_integer() else ("int_from_float", 0)
    if isinstance(value, str):
        try:
            return None, int(value.strip())
        except ValueError:
            return "int_parsing", 0
    return "int_type", 0


def _lax_boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return LAX_BOOLEANS.get(value.lower())
    return None


def _json_media_type(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    main, _, sub = media.partition("/")
    return main == "application" and (sub == "json" or sub.endswith("+json"))


def _prefers_async(header: str | None) -> bool:
    if not header:
        return False
    return any(
        item.split(";", 1)[0].split("=", 1)[0].strip().lower() == "respond-async"
        for item in header.split(",")
    )


def _email_key(email: str) -> str | None:
    try:
        return NormalizedEmail.parse(email).value
    except InvalidEmailAddress:
        return None


def _registered_email(email: str) -> str:
    if not isinstance(email, str) or not 3 <= len(email) <= 320:
        raise ValueError("the real Studio registers only e-mail addresses of 3 to 320 characters")
    try:
        return NormalizedEmail.parse(email).value
    except InvalidEmailAddress as error:
        reason = error.__cause__ if error.__cause__ is not None else error
        raise ValueError(
            f"the real Studio refuses {email!r} at the registration: {reason}"
        ) from error


def _password_code(violation: PasswordPolicyViolation) -> str:
    return f"password_{violation.value}"


def _registration_code(errors: Sequence[Mapping[str, object]]) -> str:
    for issue in errors:
        if issue["loc"] == ["body", "password"]:
            violation = REGISTRATION_LENGTH_VIOLATIONS.get(str(issue["type"]))
            return "invalid_registration" if violation is None else _password_code(violation)
    return "invalid_registration"


def _stage(stage: str) -> str:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    return stage


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _copy(value: object) -> object:
    return json.loads(json.dumps(value))


def _identifiers(items: Sequence[Mapping[str, object]]) -> list[str]:
    return sorted(str(item["id"]) for item in items)


def _grounding(
    requirements: Mapping[str, object],
    team: Mapping[str, object],
    snapshot: Mapping[str, object],
    twins: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    specification = requirements["specification"]
    return {
        "requirements_reference": {
            "kind": "REQUIREMENTS_SPECIFICATION",
            **_plain_reference(requirements),
        },
        "agent_team_reference": {"kind": "AGENT_TEAM", **_plain_reference(team)},
        "user_modeling_reference": {"kind": "USER_MODELING", **_plain_reference(snapshot)},
        "catalog": {"version": AGENT_CATALOG_VERSION, "content_hash": AGENT_CATALOG_CONTENT_HASH},
        "requirement_ids": _identifiers(specification["requirements"]),
        "user_story_ids": _identifiers(specification["user_stories"]),
        "acceptance_criterion_ids": _identifiers(specification["acceptance_criteria"]),
        "user_twin_references": [dict(twin) for twin in twins],
    }


def _bounded(value: str, maximum: int = 120) -> str:
    return value if len(value) <= maximum else f"{value[: maximum - 3].rstrip()}..."


def _chosen_code(package: Mapping[str, object]) -> str | None:
    chosen = _by_id(package["alternatives"], str(package["owner_selected_alternative_id"]))
    return None if chosen is None else str(chosen["code"])


def _first_screen(package: Mapping[str, object]) -> str:
    prototype = package.get("prototype")
    screens = [] if prototype is None else prototype["screens"]
    return str(screens[0]["code"]) if screens else "SCR-001"


def _first_line(message: str) -> str:
    line = next((" ".join(item.split()) for item in message.splitlines() if item.strip()), "")
    return _bounded(line, FIRST_LINE_LENGTH)


def _first_goal(twin: Mapping[str, object]) -> str:
    for item in twin["profile"]["observations"]:
        goals = item["value"]["items"]
        if item["observation_key"] == "user_twin.goals" and goals:
            return str(goals[0])
    return str(twin["profile"]["name"])


def _change_finding(
    severity: str,
    text: str,
    action: str,
    *,
    requirement: str | None = None,
    screen: str | None = None,
    file: str | None = None,
) -> dict[str, object]:
    return {
        "severity": severity,
        "text": text,
        "about": {"requirement": requirement, "screen": screen, "file": file},
        "action": action,
    }


def _alignment_status(message: str) -> str:
    words = message.casefold()
    for status, keys in ALIGNMENT_WORDS:
        if any(key in words for key in keys):
            return status
    return "ALIGNED"


def _recorded_order(record: Mapping[str, object]) -> tuple[datetime, datetime, str]:
    return (
        datetime.fromisoformat(str(record["recorded_at"])),
        datetime.fromisoformat(str(record["committed_at"])),
        str(record["commit"]),
    )


def _findings_by_twin(critiques: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    return {
        str(critique["twin_id"]): [str(item["text"]) for item in critique["findings"]][
            :MAX_FINDINGS
        ]
        for critique in critiques
    }


def _critique_of(
    document: Mapping[str, object] | None, twin_id: object
) -> dict[str, object] | None:
    if document is None:
        return None
    return next((item for item in document["critiques"] if item["twin_id"] == twin_id), None)


def _has_findings(document: Mapping[str, object] | None, twin_id: object) -> bool:
    critique = _critique_of(document, twin_id)
    return critique is not None and bool(critique["findings"])


def _after(moment: object, since: datetime | None) -> bool:
    return since is None or datetime.fromisoformat(str(moment)) > since


def _critique_moment(item: tuple[Mapping[str, object], Mapping[str, object]]) -> datetime:
    return datetime.fromisoformat(str(item[0]["reviewed_at"]))


def _comparable(text: str) -> str:
    return " ".join(text.split()).casefold()


def _cut_line(value: str, maximum: int) -> str:
    return " ".join(value.split())[:maximum].rstrip()


def _locale_language(locale: str) -> str:
    return "it" if locale.split("-", 1)[0].lower() == "it" else "en"


def _code_number(code: object) -> int:
    return int(str(code).split("-", 1)[1])


def _valid_statements(statements: Sequence[str]) -> None:
    keys = [_comparable(statement) for statement in statements]
    if not all(keys) or len(set(keys)) != len(keys):
        raise ValueError("the statements must hold words and differ from each other")


def _observation_number(code: str) -> int | None:
    if OBSERVATION_CODE.fullmatch(code) is None:
        return None
    number = _code_number(code)
    return number if 1 <= number <= MAX_OBSERVATION_NUMBER else None


def _listed(value: object) -> list[str]:
    return [] if value is None else [str(value)]


def _task_origin(
    kind: str,
    *,
    commit: str | None = None,
    test_run_id: str | None = None,
    twin_id: str | None = None,
    twin_name: str | None = None,
    finding: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "commit": commit,
        "test_run_id": test_run_id,
        "twin_id": twin_id,
        "twin_name": twin_name,
        "finding": finding,
    }


def _prepared_task(text: str | None, resolved: Mapping[str, object]) -> dict[str, object]:
    finding = resolved["finding"]
    if finding is None:
        return {
            "text": text,
            "about": {"requirements": [], "screens": [], "criteria": []},
            "origin": resolved["origin"],
        }
    about = finding["about"]
    action = finding["action"]
    written = " ".join(str(action if action and action.strip() else finding["text"]).split())
    if len(written) > MAX_TASK_LENGTH:
        written = written[: MAX_TASK_LENGTH - len(CUT_MARK)].rstrip() + CUT_MARK
    return {
        "text": written if text is None else text,
        "about": {
            "requirements": _listed(about.get("requirement")),
            "screens": _listed(about.get("screen")),
            "criteria": _listed(about.get("criterion")),
        },
        "origin": resolved["origin"],
    }


def _open_task(project: FakeProject, origin: Mapping[str, object]) -> dict[str, object] | None:
    keys = ("kind", "commit", "test_run_id", "twin_id", "finding")
    return next(
        (
            task
            for task in project.code_tasks
            if task["status"] == "OPEN" and all(task["origin"][key] == origin[key] for key in keys)
        ),
        None,
    )


def _set_task_status(task: dict[str, object], status: str, note: str | None, moment: str) -> None:
    if task["status"] != status:
        task["status"] = status
        task["closed_at"] = moment if status in CLOSED_STATUSES else None
    task["note"] = note


def _active_entry(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "code": item["code"],
        "statement": item["statement"],
        "basis": item["basis"],
        "source": item["source"],
        "about": dict(item["about"]),
        "contradicts_profile": item["contradicts_profile"],
        "added_in_version": item["added_in_version"],
        "approved_at": item["approved_at"],
        "update_id": item["update_id"],
    }


def _retired_entry(item: Mapping[str, object]) -> dict[str, object]:
    retired = item["retired"]
    return {
        "code": item["code"],
        "statement": item["statement"],
        "retired_in_version": retired["retired_in_version"],
        "retired_at": retired["retired_at"],
        "reason": retired["reason"],
    }


def _seeded_result(path: Mapping[str, object], status: str, title: str) -> dict[str, object]:
    count = len(path["steps"])
    steps = []
    for index, step in enumerate(path["steps"], start=1):
        failed = status == "FAILED" and index == count
        expect = step["expect"]
        detail = None
        if failed and expect is not None:
            detail = _cut_text(f"{expect['kind']}: {expect['text']}", MAX_STEP_DETAIL_LENGTH)
        steps.append(
            {
                "index": index,
                "status": "FAILED" if failed else "DONE",
                "detail": detail,
                "url": SEED_PAGE,
                "title": _cut_text(title, MAX_SNAPSHOT_TITLE_LENGTH),
                "screenshot": f"{path['code']}/chrome/{index:02d}.png",
            }
        )
    return {
        "path": copy.deepcopy(dict(path)),
        "browser": "chrome",
        "status": status,
        "seconds": 2.5,
        "steps": steps,
        "page_text": _cut_text(title, MAX_PAGE_TEXT_LENGTH),
    }


def _source_of(fields: _Fields) -> dict[str, object] | None:
    present, value = fields._get("source", True)
    if not present:
        return None
    location = (*fields.location, "source")
    if not isinstance(value, dict):
        fields.errors.append(_error(location, "model_attributes_type"))
        return None
    if "kind" not in value:
        fields.errors.append(_error(location, "union_tag_not_found"))
        return None
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in SOURCE_FIELDS:
        fields.errors.append(_error(location, "union_tag_invalid"))
        return None
    child = _Fields(value, SOURCE_FIELDS[kind], location=(*location, kind))
    source: dict[str, object] = {"kind": kind}
    if kind == "TEST_RUN":
        source["test_run_id"] = child.identifier("test_run_id")
    elif kind == "CODE_CHANGE":
        source["commit"] = child.pattern("commit", COMMIT_PATTERN)
    if kind != "OWNER":
        source["twin_id"] = child.identifier("twin_id")
        source["finding"] = child.whole("finding", minimum=0)
    fields.adopt(child)
    return source


def _owner_text(source: Mapping[str, object] | None, text: str | None) -> None:
    if source is not None and source["kind"] == "OWNER" and text is None:
        raise ValueError("a task written by the owner needs a text")


def _task_items(body: object) -> list[dict[str, object]]:
    fields = _Fields(body, TASK_FIELDS)
    items = fields.children("tasks", TASK_ITEM_FIELDS, minimum_items=1, maximum_items=MAX_TASKS)
    parsed = []
    for item in items or []:
        text = item.text("text", required=False, nullable=True, minimum=1, maximum=MAX_TASK_LENGTH)
        if text is not None:
            text = item.normalized("text", text, _single_line)
        source = _source_of(item)
        _model_rule(item, lambda source=source, text=text: _owner_text(source, text))
        fields.adopt(item)
        parsed.append({"text": text, "source": source})
    fields.check()
    return parsed


def _task_status_of(body: object) -> tuple[str, str | None]:
    fields = _Fields(body, TASK_STATUS_FIELDS)
    status = fields.choice("status", TASK_STATUSES)
    note = fields.text("note", required=False, nullable=True, maximum=MAX_TASK_NOTE_LENGTH)
    if note is not None:
        note = fields.normalized("note", note, _optional_line)
    fields.check()
    return str(status), note


def _finding_of(fields: _Fields) -> dict[str, object]:
    return {
        "twin_id": fields.identifier("twin_id"),
        "finding": fields.whole("finding", minimum=0),
    }


def _kept_of(fields: _Fields) -> dict[str, object]:
    index = fields.whole("index", minimum=0)
    statement = fields.text(
        "statement", required=False, nullable=True, minimum=1, maximum=MAX_OBSERVATION_LENGTH
    )
    if statement is not None:
        statement = fields.normalized("statement", statement, _single_line)
    return {"index": index, "statement": statement}


def _kept_rule(decision: object, kept: Sequence[Mapping[str, object]]) -> None:
    indexes = [item["index"] for item in kept]
    _distinct(indexes)
    if (decision == "APPROVE") != bool(indexes):
        raise ValueError("an approval keeps one observation or more, a rejection keeps none")


def _update_decision_of(body: object) -> tuple[str, list[dict[str, object]], str | None]:
    fields = _Fields(body, UPDATE_DECISION_FIELDS)
    decision = fields.choice("decision", UPDATE_DECISIONS)
    kept = _models(
        fields,
        "kept",
        KEPT_FIELDS,
        _kept_of,
        required=False,
        maximum_items=MAX_UPDATE_OBSERVATIONS,
    )
    reason = fields.text("reason", required=False, nullable=True, maximum=MAX_TASK_NOTE_LENGTH)
    if reason is not None:
        reason = fields.normalized("reason", reason, _optional_line)
    _model_rule(fields, lambda: _kept_rule(decision, kept))
    fields.check()
    return str(decision), kept, reason


def _owner_observation_of(body: object) -> dict[str, object]:
    fields = _Fields(body, OBSERVATION_FIELDS)
    statement = fields.text("statement", minimum=1, maximum=MAX_OBSERVATION_LENGTH)
    if statement is not None:
        statement = fields.normalized("statement", statement, _single_line)
    about: dict[str, object] = {"requirement": None, "screen": None}
    child = fields.child("about", ABOUT_FIELDS, required=False, nullable=True)
    if child is not None:
        about = {
            "requirement": child.pattern(
                "requirement", REQUIREMENT_REFERENCE, required=False, nullable=True
            ),
            "screen": child.pattern("screen", SCREEN_REFERENCE, required=False, nullable=True),
        }
        fields.adopt(child)
    fields.check()
    return {"statement": statement, "basis": None, "about": about, "contradicts_profile": None}


def _retire_reason_of(body: object) -> str | None:
    fields = _Fields(body, RETIRE_FIELDS)
    reason = fields.text("reason", required=False, nullable=True, maximum=MAX_TASK_NOTE_LENGTH)
    if reason is not None:
        reason = fields.normalized("reason", reason, _optional_line)
    fields.check()
    return reason


def _test_step(
    action: str,
    *,
    target: Mapping[str, object] | None = None,
    value: str | None = None,
    expect: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {"action": action, "target": target, "value": value, "expect": expect}


def _test_expectation(kind: str, text: str) -> dict[str, object]:
    return {"kind": kind, "target": None, "text": text}


def _models(
    fields: _Fields,
    name: str,
    allowed: Sequence[str],
    parse: Callable[[_Fields], dict[str, object]],
    *,
    required: bool = True,
    minimum_items: int = 0,
    maximum_items: int | None = None,
) -> list[dict[str, object]]:
    found = []
    items = fields.children(
        name,
        allowed,
        required=required,
        minimum_items=minimum_items,
        maximum_items=maximum_items,
    )
    for item in items or []:
        found.append(parse(item))
        fields.adopt(item)
    return found


def _model_rule(fields: _Fields, rule: Callable[[], object]) -> None:
    if fields.errors:
        return
    try:
        rule()
    except ValueError:
        fields.errors.append(_error(fields.location, "value_error"))


def _application_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("application", APPLICATION_FIELDS)
    if child is None:
        return None
    application = {
        "kind": child.choice("kind", APPLICATION_KINDS),
        "address": child.text("address", minimum=1, maximum=MAX_ADDRESS_LENGTH),
    }
    _model_rule(child, lambda: _normal_application(application))
    fields.adopt(child)
    return application


def _snapshot_of(fields: _Fields, *, required: bool = True) -> dict[str, object] | None:
    child = fields.child("snapshot", SNAPSHOT_FIELDS, required=required, nullable=not required)
    if child is None:
        return None
    snapshot = {
        "url": child.text("url", maximum=MAX_RAW_TEXT_LENGTH),
        "title": child.text("title", maximum=MAX_RAW_TEXT_LENGTH),
        "text": child.text("text", maximum=MAX_RAW_TEXT_LENGTH),
        "hidden_text": child.text(
            "hidden_text", required=False, maximum=MAX_RAW_TEXT_LENGTH, default=""
        ),
        "elements": _models(
            child, "elements", ELEMENT_FIELDS, _element_of, maximum_items=MAX_SNAPSHOT_ELEMENTS
        ),
    }
    _model_rule(child, lambda: _distinct(item["index"] for item in snapshot["elements"]))
    fields.adopt(child)
    return snapshot


def _element_of(fields: _Fields) -> dict[str, object]:
    element = {
        "index": fields.integer("index", minimum=0),
        "role": fields.choice("role", TEST_ROLES, literal=True),
        "name": fields.text("name", maximum=MAX_RAW_TEXT_LENGTH),
        "value": fields.text("value", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "state": fields.choice(
            "state", ELEMENT_STATES, required=False, nullable=True, literal=True
        ),
        "options": fields.texts(
            "options", maximum_items=MAX_SNAPSHOT_OPTIONS, item_maximum=MAX_RAW_TEXT_LENGTH
        ),
    }
    _model_rule(fields, lambda: _element_rule(element))
    return element


def _target_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("target", TARGET_FIELDS, required=False, nullable=True)
    if child is None:
        return None
    target = {
        "role": child.choice("role", TEST_ROLES, required=False, nullable=True, literal=True),
        "name": child.text("name", minimum=1, maximum=MAX_TARGET_NAME_LENGTH),
    }
    _model_rule(child, lambda: _normal_target(target))
    fields.adopt(child)
    return target


def _expectation_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("expect", EXPECTATION_FIELDS, required=False, nullable=True)
    if child is None:
        return None
    expectation = {
        "kind": child.choice("kind", TEST_EXPECTATIONS),
        "target": _target_of(child),
        "text": child.text("text", required=False, nullable=True, maximum=MAX_EXPECTED_TEXT_LENGTH),
    }
    _model_rule(child, lambda: _normal_expectation(expectation))
    fields.adopt(child)
    return expectation


def _step_of(fields: _Fields) -> dict[str, object]:
    step = {
        "action": fields.choice("action", TEST_ACTIONS),
        "target": _target_of(fields),
        "value": fields.text("value", required=False, nullable=True, maximum=MAX_STEP_VALUE_LENGTH),
        "expect": _expectation_of(fields),
    }
    _model_rule(fields, lambda: _normal_step(step))
    return step


def _path_fields(fields: _Fields) -> dict[str, object]:
    return {
        "code": fields.pattern("code", PATH_CODE),
        "heading": fields.text("heading", minimum=1, maximum=MAX_PATH_HEADING_LENGTH),
        "criteria": fields.texts(
            "criteria",
            required=True,
            nullable=False,
            minimum_items=1,
            maximum_items=MAX_CRITERIA_PER_PATH,
            item_pattern=CRITERION_CODE,
        ),
        "steps": _models(
            fields, "steps", STEP_FIELDS, _step_of, minimum_items=1, maximum_items=MAX_STEPS
        ),
    }


def _path_of(fields: _Fields) -> dict[str, object] | None:
    child = fields.child("path", PATH_FIELDS)
    if child is None:
        return None
    path = _path_fields(child)
    _model_rule(child, lambda: _normal_path(path))
    fields.adopt(child)
    return path


def _earlier_of(fields: _Fields) -> list[dict[str, object]] | None:
    items = fields.children(
        "earlier", EARLIER_FIELDS, required=False, nullable=True, maximum_items=MAX_EARLIER_PATHS
    )
    if items is None:
        return None
    earlier = []
    for item in items:
        entry = {
            **_path_fields(item),
            "blocked_step": item.integer("blocked_step", minimum=1, maximum=MAX_STEPS),
            "detail": item.text(
                "detail", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH
            ),
            "snapshot": _snapshot_of(item, required=False),
        }
        _model_rule(item, lambda entry=entry: _earlier_rule(entry))
        earlier.append(entry)
        fields.adopt(item)
    return earlier


def _browser_of(fields: _Fields) -> dict[str, object]:
    browser = {
        "name": fields.choice("name", BROWSER_NAMES, literal=True),
        "version": fields.text("version", minimum=1, maximum=MAX_BROWSER_VERSION_LENGTH),
    }
    _model_rule(fields, lambda: _single_line(browser["version"]))
    return browser


def _result_of(fields: _Fields) -> dict[str, object]:
    result = {
        "path": _path_of(fields),
        "browser": fields.choice("browser", BROWSER_NAMES, literal=True),
        "status": fields.choice("status", PATH_STATUSES),
        "seconds": fields.number("seconds", minimum=0, maximum=MAX_PATH_SECONDS),
        "steps": _models(
            fields,
            "steps",
            STEP_RESULT_FIELDS,
            _step_result_of,
            required=False,
            maximum_items=MAX_STEPS,
        ),
        "page_text": fields.text(
            "page_text", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH
        ),
    }
    _model_rule(fields, lambda: _result_rule(result))
    return result


def _step_result_of(fields: _Fields) -> dict[str, object]:
    result = {
        "index": fields.integer("index", minimum=1, maximum=MAX_STEPS),
        "status": fields.choice("status", STEP_STATUSES),
        "detail": fields.text("detail", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "url": fields.text("url", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "title": fields.text("title", required=False, nullable=True, maximum=MAX_RAW_TEXT_LENGTH),
        "screenshot": fields.text(
            "screenshot", required=False, nullable=True, maximum=MAX_SCREENSHOT_PATH_LENGTH
        ),
    }
    _model_rule(fields, lambda: result["screenshot"] is None or _screenshot(result["screenshot"]))
    return result


def _not_covered_of(fields: _Fields) -> dict[str, object]:
    item = {
        "criterion": fields.pattern("criterion", CRITERION_CODE),
        "reason": fields.text("reason", minimum=1, maximum=MAX_REASON_LENGTH),
    }
    _model_rule(fields, lambda: _single_line(item["reason"]))
    return item


def _distinct(values: Iterable[object]) -> None:
    listed = list(values)
    if len(set(listed)) != len(listed):
        raise ValueError("the values must not repeat")


def _element_rule(element: Mapping[str, object]) -> None:
    if element["options"] is not None and element["role"] != "combobox":
        raise ValueError("only a combobox lists its options")


def _normal_application(application: Mapping[str, object]) -> dict[str, object]:
    kind = application["kind"]
    address = str(application["address"]).strip()
    if not address or not _control_free(address):
        raise ValueError("the address of the application must be visible")
    if kind == "URL":
        if any(character.isspace() for character in address):
            raise ValueError("an address has no spaces")
        parts = urlsplit(address)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise ValueError("an address is an http or https address")
    elif (
        "\\" in address
        or ":" in address
        or (address != "." and any(part in ("", ".", "..") for part in address.split("/")))
    ):
        raise ValueError("a static folder is relative to the project and stays inside it")
    return {"kind": kind, "address": address}


def _normal_target(target: Mapping[str, object]) -> dict[str, object]:
    return {"role": target["role"], "name": _single_line(target["name"])}


def _normal_expectation(expectation: Mapping[str, object]) -> dict[str, object]:
    kind = expectation["kind"]
    target = None if expectation["target"] is None else _normal_target(expectation["target"])
    text = None if expectation["text"] is None else _single_line(expectation["text"])
    if (target is not None) != (kind in TARGET_EXPECTATIONS):
        raise ValueError("the expectation names a target exactly when its kind needs one")
    if (text is not None) != (kind in TEXT_EXPECTATIONS):
        raise ValueError("the expectation gives a text exactly when its kind needs one")
    return {"kind": kind, "target": target, "text": text}


def _normal_step(step: Mapping[str, object]) -> dict[str, object]:
    action = step["action"]
    target = None if step["target"] is None else _normal_target(step["target"])
    value = None if step["value"] is None else _single_line(step["value"])
    expect = None if step["expect"] is None else _normal_expectation(step["expect"])
    if (target is not None) != (action in TARGET_ACTIONS):
        raise ValueError("the step names a target exactly when its action needs one")
    if (value is not None) != (action in VALUE_ACTIONS):
        raise ValueError("the step gives a value exactly when its action needs one")
    if action == "CHECK" and expect is None:
        raise ValueError("a CHECK step needs an expectation")
    if action == "OPEN":
        parts = urlsplit(str(value))
        scheme = parts.scheme.lower()
        if scheme and (scheme not in ("http", "https") or not parts.netloc):
            raise ValueError("an OPEN step opens a path of the application or an http address")
    if action == "PRESS" and value not in TEST_KEYS:
        raise ValueError("a PRESS step presses one of the test keys")
    roles = ACTION_ROLES.get(str(action))
    if roles is not None and target is not None and target["role"] not in (None, *roles):
        raise ValueError("the step cannot act on an element of that role")
    return {"action": action, "target": target, "value": value, "expect": expect}


def _normal_path(path: Mapping[str, object]) -> dict[str, object]:
    criteria = [str(code) for code in path["criteria"]]
    _distinct(criteria)
    steps = [_normal_step(step) for step in path["steps"]]
    if steps[0]["action"] != "OPEN":
        raise ValueError("the first step of a path is OPEN")
    return {
        "code": path["code"],
        "heading": _single_line(path["heading"]),
        "criteria": criteria,
        "steps": steps,
    }


def _earlier_rule(entry: Mapping[str, object]) -> None:
    path = _normal_path(entry)
    if int(entry["blocked_step"]) > len(path["steps"]):
        raise ValueError("the blocked step is a step of the path")


def _result_rule(result: Mapping[str, object]) -> None:
    indexes = [step["index"] for step in result["steps"]]
    if indexes != list(range(1, len(indexes) + 1)):
        raise ValueError("the steps of a result are numbered from 1 in order")
    if len(indexes) > len(result["path"]["steps"]):
        raise ValueError("a result holds at most the steps of its path")


def _run_rule(
    plan_id: str | None,
    replan_ids: Sequence[str],
    started_at: datetime | None,
    finished_at: datetime | None,
    browsers: Sequence[Mapping[str, object]],
    results: Sequence[Mapping[str, object]],
    not_covered: Sequence[Mapping[str, object]],
) -> None:
    _distinct(replan_ids)
    if plan_id in replan_ids:
        raise ValueError("the replans are other plans than the plan of the run")
    if started_at is not None and finished_at is not None and finished_at < started_at:
        raise ValueError("a run ends after it starts")
    names = [item["name"] for item in browsers]
    _distinct(names)
    if any(item["browser"] not in names for item in results):
        raise ValueError("every result names a browser of the run")
    _distinct(item["criterion"] for item in not_covered)


def _screenshot(value: object) -> str:
    path = str(value)
    if not path or not _control_free(path) or "\\" in path or ":" in path:
        raise ValueError("the screenshot is a relative path with / as separator")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError("the screenshot stays inside the run folder")
    return path


def _cut_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    kept = "".join(
        character
        for character in str(value)
        if character.isspace() or (ord(character) >= 32 and ord(character) != 127)
    )
    text = " ".join(kept.split())
    if len(text) <= maximum:
        return text
    return text[: maximum - len(CUT_MARK)].rstrip() + CUT_MARK


def _domain_refusal(message: str) -> _Refusal:
    return _Refusal(
        422,
        {
            "code": "invalid_request",
            "errors": [{"loc": ["body"], "type": "value_error", "msg": message}],
        },
    )


def _bound_results(
    plans: Sequence[Mapping[str, object]],
    results: Sequence[Mapping[str, object]],
    not_covered: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    paths = [path for plan in plans for path in plan["paths"]]
    requested = {str(code) for plan in plans for code in plan["criteria"]}
    bound = []
    for position, result in enumerate(results):
        code = str(result["path"]["code"])
        candidates = [path for path in paths if path["code"] == code]
        if not candidates:
            raise _domain_refusal(
                f"result {position} names the path {code}, "
                "which is not in the plan or in its replans"
            )
        wanted = _normal_path(result["path"])
        planned = next((path for path in candidates if path == wanted), candidates[-1])
        if len(result["steps"]) > len(planned["steps"]):
            raise _domain_refusal(f"result {position} holds more steps than its path")
        bound.append(
            {
                "path": copy.deepcopy(planned),
                "browser": result["browser"],
                "status": result["status"],
                "seconds": float(result["seconds"]),
                "steps": [
                    {
                        "index": step["index"],
                        "status": step["status"],
                        "detail": _cut_text(step["detail"], MAX_STEP_DETAIL_LENGTH),
                        "url": _cut_text(step["url"], MAX_SNAPSHOT_URL_LENGTH),
                        "title": _cut_text(step["title"], MAX_SNAPSHOT_TITLE_LENGTH),
                        "screenshot": step["screenshot"],
                    }
                    for step in result["steps"]
                ],
                "page_text": _cut_text(result["page_text"], MAX_PAGE_TEXT_LENGTH),
            }
        )
    unknown = [str(item["criterion"]) for item in not_covered if item["criterion"] not in requested]
    if unknown:
        raise _domain_refusal(f"the not covered criteria {', '.join(unknown)} are not in the plans")
    return bound


def _criteria_outcomes(
    plans: Sequence[Mapping[str, object]],
    results: Sequence[Mapping[str, object]],
    not_covered: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    requested = list(dict.fromkeys(str(code) for plan in plans for code in plan["criteria"]))
    paths = [path for plan in plans for path in plan["paths"]]
    uncovered = {str(item["criterion"]) for item in not_covered}
    outcomes = []
    for code in requested:
        named = [result for result in results if code in result["path"]["criteria"]]
        statuses = {result["status"] for result in named}
        if "FAILED" in statuses:
            status = "FAILED"
        elif "BLOCKED" in statuses:
            status = "BLOCKED"
        elif named and statuses == {"PASSED"}:
            status = "PASSED"
        elif not named and code in uncovered:
            status = "NOT_COVERED"
        else:
            status = "NOT_RUN"
        if named:
            codes = [str(result["path"]["code"]) for result in named]
        elif status == "NOT_RUN":
            codes = [str(path["code"]) for path in paths if code in path["criteria"]]
        else:
            codes = []
        outcomes.append({"code": code, "status": status, "paths": list(dict.fromkeys(codes))})
    return outcomes


def _run_summary(outcomes: Sequence[Mapping[str, object]]) -> dict[str, int]:
    summary = dict.fromkeys(SUMMARY_KEYS, 0)
    for item in outcomes:
        summary[str(item["status"]).lower()] += 1
    return summary


def _unique(items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    unique: list[dict[str, object]] = []
    for item in items:
        if dict(item) not in unique:
            unique.append(dict(item))
    return unique


def _by_id(items: Sequence[Mapping[str, object]], identifier: str) -> dict | None:
    return next((item for item in items if str(item.get("id")) == identifier), None)


def _issue(issue: object) -> str | None:
    return None if issue is None else str(getattr(issue, "value", issue))


def _submission_status(status: str) -> int:
    if status == "SUBMITTED":
        return 201
    if status in {"ALREADY_PENDING", "ALREADY_APPROVED"}:
        return 200
    return 409


def _gate_decision(
    call: _Call, actions: Sequence[str], *, literal: bool, maximum: int | None
) -> tuple[str, str | None]:
    fields = _Fields(call.json(), ("action", "reason"))
    action = fields.choice("action", actions, literal=literal)
    reason = fields.text("reason", required=False, nullable=True, maximum=maximum)
    fields.check()
    return str(action), reason


def _decision_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = " ".join(reason.split())
    if not normalized:
        raise _Invalid([_error(("body", "reason"), "value_error")])
    return normalized


def _blank_to_none(reason: str | None) -> str | None:
    normalized = " ".join((reason or "").split())
    return normalized or None


def _version(artifact: Mapping[str, object] | None) -> ArtifactVersion | None:
    return None if artifact is None else _artifact_version(artifact)


def _artifact_version(artifact: Mapping[str, object]) -> ArtifactVersion:
    return ArtifactVersion(
        UUID(str(artifact["id"])), int(artifact["version_number"]), str(artifact["content_hash"])
    )


def _reference_version(reference: Mapping[str, object]) -> ArtifactVersion:
    return ArtifactVersion(
        UUID(str(reference["artifact_id"])),
        int(reference["version_number"]),
        str(reference["content_hash"]),
    )


def _plain_reference(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        "artifact_id": artifact["id"],
        "version_number": artifact["version_number"],
        "content_hash": artifact["content_hash"],
    }


def _reference_fields(reference: Mapping[str, object]) -> dict[str, object]:
    return {
        "artifact_id": reference["artifact_id"],
        "version_number": reference["version_number"],
        "content_hash": reference["content_hash"],
    }


def _key(artifact: Mapping[str, object] | None) -> tuple[str, int, str] | None:
    if artifact is None:
        return None
    return (str(artifact["id"]), int(artifact["version_number"]), str(artifact["content_hash"]))


def _reference_key(reference: Mapping[str, object]) -> tuple[str, int, str]:
    return (
        str(reference["artifact_id"]),
        int(reference["version_number"]),
        str(reference["content_hash"]),
    )


def _team_brief(team: Mapping[str, object] | None) -> tuple[str, int, str] | None:
    if team is None:
        return None
    return (
        str(team["brief_version_id"]),
        int(team["brief_version_number"]),
        str(team["brief_content_hash"]),
    )


def _twin_ids(items: Iterable[Mapping[str, object]]) -> frozenset[str]:
    return frozenset(str(item["twin_id"]) for item in items)


def _sorted_twins(items: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    return sorted((dict(item) for item in items), key=lambda item: str(item["twin_id"]))


def _referenced_twins(specification: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        {
            *(
                str(reference["twin_id"])
                for requirement in specification["requirements"]
                for reference in requirement["user_twin_references"]
            ),
            *(
                str(story["user_twin_reference"]["twin_id"])
                for story in specification["user_stories"]
            ),
            *(str(scenario["actor"]["twin_id"]) for scenario in specification["scenarios"]),
        }
    )


def _on_snapshot(
    specification: Mapping[str, object], snapshot: Mapping[str, object] | None
) -> bool:
    if snapshot is None:
        return False
    twins = (_twin_reference(twin) for twin in snapshot["snapshot"]["twin_versions"])
    return _reference_key(specification["user_modeling_reference"]) == _key(
        snapshot
    ) and _sorted_twins(specification["user_twin_references"]) == _sorted_twins(twins)


def _requirements_aligned(
    specification: Mapping[str, object], snapshot: Mapping[str, object]
) -> bool:
    body = snapshot["snapshot"]
    return (
        _reference_key(specification["project_brief_reference"])
        == _reference_key(body["project_brief_reference"])
        and _reference_key(specification["agent_team_reference"])
        == _reference_key(body["agent_team_reference"])
        and (specification["catalog_version"], specification["catalog_content_hash"])
        == (body["catalog_version"], body["catalog_content_hash"])
        and _on_snapshot(specification, snapshot)
    )


def _requirements_grounding(requirements: Mapping[str, object]) -> dict[str, object]:
    specification = requirements["specification"]
    return {
        "requirements_reference": {
            "kind": "REQUIREMENTS_SPECIFICATION",
            **_plain_reference(requirements),
        },
        "agent_team_reference": {
            "kind": "AGENT_TEAM",
            **_reference_fields(specification["agent_team_reference"]),
        },
        "user_modeling_reference": {
            "kind": "USER_MODELING",
            **_reference_fields(specification["user_modeling_reference"]),
        },
        "catalog": {
            "version": specification["catalog_version"],
            "content_hash": specification["catalog_content_hash"],
        },
        "requirement_ids": _identifiers(specification["requirements"]),
        "user_story_ids": _identifiers(specification["user_stories"]),
        "acceptance_criterion_ids": _identifiers(specification["acceptance_criteria"]),
        "user_twin_references": _sorted_twins(specification["user_twin_references"]),
    }


def _design_aligned(design: Mapping[str, object], requirements: Mapping[str, object]) -> bool:
    return design["package"]["grounding"] == _requirements_grounding(requirements)


def _cited_ids(package: Mapping[str, object]) -> frozenset[str]:
    holders: list[Mapping[str, object]] = []
    for alternative in package["alternatives"]:
        holders.append(alternative)
        holders.extend(alternative["workflows"])
    holders.extend(package["concerns"])
    prototype = package.get("prototype")
    if prototype is not None:
        for screen in prototype["screens"]:
            holders.append(screen)
            holders.extend(screen["elements"])
    cited = {
        str(identifier)
        for holder in holders
        for key in CITED_KEYS
        for identifier in holder.get(key) or ()
    }
    bound = package.get("generated_mockup")
    if bound is not None:
        for value in bound["requirement_ids_by_code"].values():
            cited.update(str(item) for item in (value if isinstance(value, list) else [value]))
    return frozenset(cited)


def _without_requirement(specification: Mapping[str, object], identifier: str) -> dict[str, object]:
    proposed = copy.deepcopy(dict(specification))
    proposed["requirements"] = [
        item for item in proposed["requirements"] if str(item["id"]) != identifier
    ]
    dropped = set()
    criteria = []
    for item in proposed["acceptance_criteria"]:
        item["requirement_ids"] = [
            value for value in item["requirement_ids"] if str(value) != identifier
        ]
        if item["requirement_ids"]:
            criteria.append(item)
        else:
            dropped.add(str(item["id"]))
    proposed["acceptance_criteria"] = criteria
    for key in ("user_stories", "scenarios", "risks", "definition_of_done"):
        for item in proposed[key]:
            item["requirement_ids"] = [
                value for value in item["requirement_ids"] if str(value) != identifier
            ]
    for scenario in proposed["scenarios"]:
        scenario["acceptance_criterion_ids"] = [
            value for value in scenario["acceptance_criterion_ids"] if str(value) not in dropped
        ]
    return proposed


def _twin_versions(items: Iterable[Mapping[str, object]]) -> frozenset[ArtifactVersion]:
    return frozenset(
        ArtifactVersion(
            UUID(str(item["twin_id"])), int(item["version_number"]), str(item["content_hash"])
        )
        for item in items
    )


def _team_brief_version(team: Mapping[str, object]) -> ArtifactVersion:
    return ArtifactVersion(
        UUID(str(team["brief_version_id"])),
        int(team["brief_version_number"]),
        str(team["brief_content_hash"]),
    )


def _gesture_issue(code: str) -> str:
    return GESTURE_ISSUES.get(code, code)


def _alignment_result(
    key: str,
    outcome: str,
    *,
    issue: str | None = None,
    version_number: int | None = None,
    codes: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "key": key,
        "outcome": outcome,
        "issue": issue,
        "version_number": version_number,
        "codes": list(codes),
    }


def _gesture_status(results: Sequence[Mapping[str, object]]) -> str:
    outcomes = [result["outcome"] for result in results]
    if "ALIGNED" not in outcomes:
        return "NOTHING_TO_ALIGN"
    return "PARTIAL" if "BLOCKED" in outcomes else "ALIGNED"


def _refusal_code(refusal: _Refusal) -> tuple[str, list[str]]:
    detail = refusal.detail
    if isinstance(detail, Mapping):
        return str(detail.get("code")), [str(code) for code in detail.get("missing_codes", ())]
    return str(detail), []


def _gate_state(gate: HumanGate | None) -> GateState | None:
    if gate is None:
        return None
    return GateState(
        status=gate.status,
        artifact=ArtifactVersion(
            gate.artifact.artifact_id, gate.artifact.version, gate.artifact.content_hash
        ),
    )


def _approves(gate: GateState | None, artifact: ArtifactVersion | None) -> bool:
    return gate is not None and gate.approves(artifact)


def _gate_artifact(reference: GateArtifactReference) -> dict[str, object]:
    return {
        "project_id": str(reference.project_id),
        "gate_type": reference.gate_type.value,
        "artifact_id": str(reference.artifact_id),
        "version": reference.version,
        "content_hash": reference.content_hash,
    }


def _gate_payload(gate: HumanGate | None, *, resume: bool = True) -> dict[str, object] | None:
    if gate is None:
        return None
    payload: dict[str, object] = {
        "id": str(gate.id),
        "project_id": str(gate.project_id),
        "owner_user_id": str(gate.owner_user_id),
        "gate_type": gate.gate_type.value,
        "artifact": _gate_artifact(gate.artifact),
        "iteration": gate.iteration,
        "max_iterations": gate.max_iterations,
        "status": gate.status.value,
        "created_at": _stamp(gate.created_at),
        "updated_at": _stamp(gate.updated_at),
        "event_sequence": gate.event_sequence,
    }
    if resume:
        payload["resume_status"] = None if gate.resume_status is None else gate.resume_status.value
    return payload


def _event_payload(event: HumanGateEvent) -> dict[str, object]:
    return {
        "id": str(event.id),
        "gate_id": str(event.gate_id),
        "sequence_number": event.sequence_number,
        "kind": event.kind.value,
        "previous_status": event.previous_status.value,
        "resulting_status": event.resulting_status.value,
        "artifact": _gate_artifact(event.artifact),
        "occurred_at": _stamp(event.occurred_at),
        "actor_user_id": None if event.actor_user_id is None else str(event.actor_user_id),
        "reason": event.reason,
    }


def _user_payload(account: _Account) -> dict[str, object]:
    return {
        "id": account.id,
        "email": account.email,
        "is_active": True,
        "created_at": _stamp(account.created_at),
    }


def _assumption_payload(assumption: BriefAssumption) -> dict[str, object]:
    return {
        "id": str(assumption.id),
        "project_id": str(assumption.project_id),
        "brief_version_number": assumption.brief_version_number,
        "field": assumption.field.value,
        "statement": assumption.statement,
        "source": assumption.source.value,
        "status": assumption.status.value,
        "created_by_user_id": str(assumption.created_by_user_id),
        "created_at": _stamp(assumption.created_at),
        "decided_by_user_id": None
        if assumption.decided_by_user_id is None
        else str(assumption.decided_by_user_id),
        "decided_at": None if assumption.decided_at is None else _stamp(assumption.decided_at),
        "decision_reason": assumption.decision_reason,
    }


def _with_assumption(brief: ProjectBrief, assumption: BriefAssumption) -> ProjectBrief:
    unknown = set(brief.unknown_fields)
    unknown.discard(assumption.field)
    value: object = assumption.statement
    if assumption.field in LIST_FIELDS:
        existing = brief.value_for(assumption.field)
        value = (
            (*existing, assumption.statement)
            if isinstance(existing, tuple)
            else (assumption.statement,)
        )
    return replace(brief, **{assumption.field.value: value, "unknown_fields": frozenset(unknown)})


def _reason_payload(reason: TeamSelectionReason) -> dict[str, object]:
    return {
        "code": reason.code.value,
        "evidence": {
            "fields": [item.value for item in reason.evidence.fields],
            "terms": list(reason.evidence.terms),
        },
    }


def _rules_payload(constraints: DeterministicTeamConstraints) -> dict[str, object]:
    return {
        "constraints_content_hash": constraints.content_hash,
        "role_constraints": constraints.to_snapshot()["role_constraints"],
        "constraint_issues": [
            {
                "code": issue.code.value,
                "agent_id": issue.agent_id.value,
                "mandatory_reasons": [_reason_payload(item) for item in issue.mandatory_reasons],
                "impossible_reasons": [_reason_payload(item) for item in issue.impossible_reasons],
            }
            for issue in constraints.issues
        ],
    }


def _selection_reason(payload: Mapping[str, object]) -> TeamSelectionReason:
    evidence = payload["evidence"]
    return TeamSelectionReason(
        code=TeamSelectionReasonCode(str(payload["code"])),
        evidence=RuleEvidence(
            fields=tuple(BriefField(str(item)) for item in evidence["fields"]),
            terms=tuple(str(item) for item in evidence["terms"]),
        ),
    )


def _team_constraints(content: Mapping[str, object]) -> DeterministicTeamConstraints:
    return DeterministicTeamConstraints(
        catalog_version=int(content["catalog_version"]),
        catalog_content_hash=str(content["catalog_content_hash"]),
        project_mode=ProjectMode(str(content["project_mode"])),
        role_constraints=tuple(
            TeamRoleConstraint(
                agent_id=AgentIdentifier(str(item["agent_id"])),
                kind=TeamRoleConstraintKind(str(item["kind"])),
                reasons=tuple(_selection_reason(reason) for reason in item["reasons"]),
            )
            for item in content["role_constraints"]
        ),
        issues=tuple(
            TeamSelectionIssue(
                code=TeamSelectionIssueCode(str(item["code"])),
                agent_id=AgentIdentifier(str(item["agent_id"])),
                mandatory_reasons=tuple(
                    _selection_reason(reason) for reason in item["mandatory_reasons"]
                ),
                impossible_reasons=tuple(
                    _selection_reason(reason) for reason in item["impossible_reasons"]
                ),
            )
            for item in content["constraint_issues"]
        ),
    )


def _perspectives(content: Mapping[str, object]) -> list[dict[str, object]]:
    views = perspective_views(_team_constraints(content), content["selected_agent_ids"])
    return [view.to_snapshot() for view in views]


def _rule_justifications(constraint: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {
            "kind": "DETERMINISTIC_RULE",
            "code": reason["code"],
            "evidence_fields": list(reason["evidence"]["fields"]),
            "evidence_terms": list(reason["evidence"]["terms"]),
            "statement": None,
        }
        for reason in constraint["reasons"]
    ]


def _justification(
    kind: str,
    code: str,
    fields: Sequence[str] = (),
    *,
    statement: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "code": code,
        "evidence_fields": list(fields),
        "evidence_terms": [],
        "statement": statement,
    }


def _team_issues(
    current: Mapping[str, object],
    selected: Sequence[str],
    rationales: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    issues = []
    for agent in sorted(set(selected)):
        if selected.count(agent) > 1:
            issues.append({"code": "DUPLICATE_AGENT", "agent_id": agent})
    named = [agent for agent, _ in rationales]
    for agent in sorted(set(named)):
        if named.count(agent) > 1:
            issues.append({"code": "DUPLICATE_RATIONALE", "agent_id": agent})
    mandatory = {
        constraint["agent_id"]
        for constraint in current["role_constraints"]
        if constraint["kind"] == "MANDATORY"
    }
    issues.extend(
        {"code": "MANDATORY_AGENT_MISSING", "agent_id": agent}
        for agent in mandatory - set(selected)
    )
    blocked = {
        constraint["agent_id"]
        for constraint in current["role_constraints"]
        if constraint["kind"] == "IMPOSSIBLE"
    }
    issues.extend(
        {"code": "AGENT_NOT_SELECTABLE", "agent_id": agent} for agent in set(selected) & blocked
    )
    added = set(selected) - set(current["selected_agent_ids"])
    issues.extend({"code": "UNUSED_RATIONALE", "agent_id": agent} for agent in set(named) - added)
    return sorted(
        issues, key=lambda issue: (AGENT_ORDER.index(str(issue["agent_id"])), str(issue["code"]))
    )


def _text_value(text: str) -> dict[str, object]:
    return {"kind": "TEXT", "text": text, "items": [], "reason": None}


def _items_value(items: Sequence[str]) -> dict[str, object]:
    return {"kind": "ITEMS", "text": None, "items": list(items), "reason": None}


def _fake_team_proposal(version: Mapping[str, object]):
    return proposal_from_snapshot(
        {
            "schema_version": version["schema_version"],
            "project_id": version["project_id"],
            "project_mode": version["project_mode"],
            "provider": {key: version[key] for key in ("provider_id", "provider_version")}
            | {"kind": version["provider_kind"]},
            "brief_version": {
                "id": version["brief_version_id"],
                "version_number": version["brief_version_number"],
                "content_hash": version["brief_content_hash"],
            },
            "catalog": {
                "version": version["catalog_version"],
                "content_hash": version["catalog_content_hash"],
            },
            "constraints": _team_constraints(version).to_snapshot(),
            "constraints_content_hash": version["constraints_content_hash"],
            "members": version["members"],
        }
    )


def _fake_brief_version(version: _BriefVersion):
    from orchestwin.projects.briefs import ProjectBriefVersion

    return ProjectBriefVersion(
        id=UUID(version.id),
        project_id=UUID(version.payload["project_id"]),
        version_number=version.number,
        schema_version=version.brief.SCHEMA_VERSION,
        brief=version.brief,
        content_hash=version.brief.content_hash,
        created_by_user_id=UUID(version.payload["created_by_user_id"]),
        created_at=datetime.fromisoformat(version.payload["created_at"]),
    )


def _fake_requirements(specification: Mapping[str, object]):
    return RequirementsSpecificationPayload.model_validate(specification).to_domain()


def _fake_design(package: Mapping[str, object]):
    from orchestwin.api.design import DesignPackagePayload

    return DesignPackagePayload.model_validate(package).to_domain()


def _fake_persona_profile(profile: Mapping[str, object]):
    payload = copy.deepcopy(dict(profile))
    payload.setdefault("schema_version", 1)
    return persona_profile_from_snapshot(payload)


def _fake_twin_profile(profile: Mapping[str, object]):
    payload = copy.deepcopy(dict(profile))
    payload.setdefault("schema_version", 1)
    payload.setdefault(
        "catalog",
        {
            "version": payload.pop("catalog_version", AGENT_CATALOG_VERSION),
            "content_hash": payload.pop("catalog_content_hash", AGENT_CATALOG_CONTENT_HASH),
        },
    )
    payload.setdefault(
        "requires_human_validation",
        any(item["human_validation"] == "REQUIRED" for item in payload["observations"]),
    )
    return user_twin_profile_from_snapshot(payload)


def _fake_modeling(body: Mapping[str, object]):
    def reference(value):
        return VersionedArtifactReference(
            artifact_id=UUID(value["artifact_id"]),
            version_number=value["version_number"],
            content_hash=value["content_hash"],
        )

    return create_user_modeling_snapshot(
        project_id=UUID(body["project_id"]),
        project_brief_reference=reference(body["project_brief_reference"]),
        agent_team_reference=reference(body["agent_team_reference"]),
        catalog_version=body["catalog_version"],
        catalog_content_hash=body["catalog_content_hash"],
        persona_versions=(_fake_persona(version) for version in body["persona_versions"]),
        twin_versions=(
            UserTwinProfileVersion(
                id=UUID(version["id"]),
                project_id=UUID(version["project_id"]),
                twin_id=UUID(version["twin_id"]),
                version_number=version["version_number"],
                based_on_version_number=version.get("based_on_version_number"),
                profile=_fake_twin_profile(version["profile"]),
                content_hash=version["content_hash"],
                created_by_user_id=UUID(version["created_by_user_id"]),
                created_at=datetime.fromisoformat(version["created_at"]),
            )
            for version in body["twin_versions"]
        ),
    )


def _fake_persona(version: Mapping[str, object]) -> PersonaProfileVersion:
    payload = copy.deepcopy(version["profile"])
    payload.setdefault("schema_version", 1)
    profile = persona_profile_from_snapshot(payload)
    return PersonaProfileVersion(
        id=UUID(version["id"]),
        project_id=UUID(version["project_id"]),
        persona_id=UUID(version["persona_id"]),
        version_number=version["version_number"],
        based_on_version_number=version.get("based_on_version_number"),
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=UUID(version["created_by_user_id"]),
        created_at=datetime.fromisoformat(version["created_at"]),
    )


def _fake_twin_view(
    version: Mapping[str, object], persona: Mapping[str, object] | None
) -> dict[str, object]:
    payload = copy.deepcopy(version["profile"])
    payload.setdefault("schema_version", 1)
    payload.setdefault(
        "catalog",
        {
            "version": payload.pop("catalog_version", AGENT_CATALOG_VERSION),
            "content_hash": payload.pop("catalog_content_hash", AGENT_CATALOG_CONTENT_HASH),
        },
    )
    payload.setdefault(
        "requires_human_validation",
        any(item["human_validation"] == "REQUIRED" for item in payload["observations"]),
    )
    archetype = None if persona is None else _fake_persona(persona)
    if archetype is not None:
        payload["persona_reference"]["content_hash"] = archetype.content_hash
    profile = user_twin_profile_from_snapshot(payload)
    twin = UserTwinProfileVersion(
        id=UUID(version["id"]),
        project_id=UUID(version["project_id"]),
        twin_id=UUID(version["twin_id"]),
        version_number=version["version_number"],
        based_on_version_number=version.get("based_on_version_number"),
        profile=profile,
        content_hash=profile.content_hash,
        created_by_user_id=UUID(version["created_by_user_id"]),
        created_at=datetime.fromisoformat(version["created_at"]),
    )
    return twin_view(twin, archetype)


def _observation(
    key: str, value: Mapping[str, object], source: Mapping[str, object]
) -> dict[str, object]:
    return {
        "observation_key": key,
        "value": dict(value),
        "epistemic_status": "MODEL_INFERRED",
        "confidence": 0.6,
        "provenance": [dict(source)],
        "human_validation": "REQUIRED",
        "rationale": "Simulated inference from the cited project brief.",
    }


def _unknown_observation(key: str, source: Mapping[str, object]) -> dict[str, object]:
    return {
        "observation_key": key,
        "value": {"kind": "UNKNOWN", "text": None, "items": [], "reason": None},
        "epistemic_status": "MODEL_INFERRED",
        "confidence": 0.0,
        "provenance": [dict(source)],
        "human_validation": "REQUIRED",
        "rationale": "No value was supplied for this field.",
    }


def _twin_reference(twin: Mapping[str, object]) -> dict[str, object]:
    return {
        "twin_id": twin["twin_id"],
        "version_number": twin["version_number"],
        "content_hash": twin["content_hash"],
        "name": twin["profile"]["name"],
    }


def _revision_payload(
    status: str, diff: Mapping[str, object], version: Mapping[str, object] | None
) -> dict[str, object]:
    return {
        "status": status,
        "diff": diff,
        "version": version,
        "issue": None,
        "proposal_issue": None,
        "diff_persistence_status": None,
        "version_persistence_status": None,
    }


def _design_revision_payload(
    status: str, diff: Mapping[str, object], version: Mapping[str, object] | None
) -> dict[str, object]:
    return {
        "status": status,
        "diff": diff,
        "version": version,
        "issue": None,
        "domain_issue": None,
        "diff_persistence_status": None,
        "version_persistence_status": None,
    }


def _generation_payload(
    status: str,
    version: Mapping[str, object] | None,
    issue: str | None,
    *,
    proposal_issue: str | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "version": version,
        "issue": issue,
        "proposal_issue": proposal_issue,
        "persistence_status": "APPENDED" if version is not None else None,
    }


def _choices(spec: Mapping[str, str]) -> dict[str, str]:
    return {
        "archetype": spec["archetype"],
        "hue_family": spec["hue"],
        "color_scheme": "ANALOGOUS",
        "color_mode": spec["mode"],
        "saturation": "BALANCED",
        "surface_tone": "NEUTRAL",
        "heading_family": "HUMANIST_SANS",
        "body_family": "HUMANIST_SANS",
        "type_scale": "REGULAR",
        "heading_case": "SENTENCE",
        "heading_weight": "SEMIBOLD",
        "corners": "SOFT",
        "density": "COMFORTABLE",
        "buttons": "FILLED",
        "inputs": "BOXED",
        "elevation": "SUBTLE",
        "borders": "HAIRLINE",
        "navigation": "NONE",
        "header": "MINIMAL",
        "background": "PLAIN",
        "emphasis": "BALANCED",
        "tone": spec["tone"],
    }


def _tokens(package: Mapping[str, object], alternative_id: str) -> dict[str, str]:
    alternative = _by_id(package["alternatives"], alternative_id)
    if alternative is None:
        raise RuntimeError("the mockup needs its alternative")
    return dict(alternative["visual_language"]["tokens"])


def _mockup_warnings(
    package: Mapping[str, object], specification: Mapping[str, object]
) -> list[dict[str, object]]:
    bound = package.get("generated_mockup")
    if bound is None:
        return []
    snapshot = bound["mockup"]
    alternative = _by_id(package["alternatives"], str(snapshot["design_alternative_id"]))
    if alternative is None:
        raise RuntimeError("the mockup needs its alternative")
    language = alternative["visual_language"]
    tokens = dict(language["tokens"])
    mode = VisualChoices.from_snapshot(language["choices"]).color_mode
    report = review_generated_mockup(
        generated_mockup_from_snapshot(snapshot, token_names=tokens),
        tokens=tokens,
        requirement_codes=[str(item["code"]) for item in specification["requirements"]],
        text_contrast_threshold=MODES[mode].text_threshold,
    )
    return [
        {"code": issue.code, "screen_code": issue.screen_code, "detail": issue.detail}
        for issue in report.issues
        if issue.severity is MockupIssueSeverity.WARNING
    ]


def _document_language(mockup: GeneratedMockup) -> str:
    trees = screen_trees(mockup)
    return (
        dominant_language(nodes_text(trees[screen.code]) for screen in mockup.screens)
        or DOCUMENT_LANGUAGE
    )


def _screen_list(mockup: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        {"code": screen["code"], "title": screen["title"], "state": screen["state"]}
        for screen in mockup["screens"]
    ]


def _anchor_label(text: str) -> str:
    return text if len(text) <= ANCHOR_LABEL_LENGTH else text[: ANCHOR_LABEL_LENGTH - 1] + "…"


def _anchors(prototype: Mapping[str, object]) -> dict[str, tuple[str, str]]:
    screens = {str(screen["code"]): screen for screen in prototype["screens"]}
    places = {
        code: f"{code} {_anchor_label(str(screen['title']))}" for code, screen in screens.items()
    }
    anchors = {code: (code, place) for code, place in places.items()}
    for role, (code, kinds, last) in ANCHOR_KINDS.items():
        chosen = [item for item in screens[code]["elements"] if item["kind"] in kinds]
        if not chosen:
            anchors[role] = anchors[code]
            continue
        element = chosen[-1] if last else chosen[0]
        label = _anchor_label(str(element["accessible_name"] or element["content"]))
        anchors[role] = (
            f"{code}/{element['code']}",
            f"{places[code]} · {element['code']} {label}",
        )
    return anchors


def _label(summary: str, finding_id: str) -> str:
    text = " ".join(FORBIDDEN_CHARACTERS.sub(" ", summary).split())
    if not text:
        return finding_id
    if len(text) <= PIN_LABEL_LENGTH:
        return text
    return text[: PIN_LABEL_LENGTH - 1].rstrip() + "…"


def _run_findings(run: Mapping[str, object]) -> list[dict[str, object]]:
    return [finding for response in run["responses"] for finding in response["findings"]]


def _placement(
    finding: Mapping[str, object], elements: Mapping[str, str], screens: Sequence[str]
) -> tuple[str, str | None]:
    key = finding.get("anchor_key")
    if isinstance(key, str):
        screen, _, element = key.partition("/")
        if element and elements.get(element) == screen:
            return screen, element
        if screen in screens:
            return screen, None
    match = LEADING_SCREEN.match(str(finding["location"]))
    if match is not None and match[1] in screens:
        return match[1], None
    return screens[0], None


def _pins(run: Mapping[str, object], version: Mapping[str, object]) -> dict[str, object]:
    prototype = version["package"]["prototype"]
    entry = next(
        screen["code"]
        for screen in prototype["screens"]
        if screen["id"] == prototype["entry_screen_id"]
    )
    screens = [
        entry,
        *(screen["code"] for screen in prototype["screens"] if screen["code"] != entry),
    ]
    elements = {
        element["code"]: screen["code"]
        for screen in prototype["screens"]
        for element in screen["elements"]
    }
    pins = []
    unanchored = []
    for number, finding in enumerate(_run_findings(run), start=1):
        screen, element = _placement(finding, elements, screens)
        if element is None:
            unanchored.append(
                {
                    "number": number,
                    "screen_code": screen,
                    "twin_id": finding["twin_id"],
                    "finding_id": finding["finding_id"],
                }
            )
            continue
        pins.append(
            {
                "number": number,
                "element_code": element,
                "screen_code": screen,
                "twin_id": finding["twin_id"],
                "finding_id": finding["finding_id"],
                "severity": finding["severity"],
                "label": _label(str(finding["summary"]), str(finding["finding_id"])),
            }
        )
    return {"design_version_id": run["design_version_id"], "pins": pins, "unanchored": unanchored}


def _control(text: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) < 160 for character in text)


def _normalized_iteration(request: str, assertions: Sequence[str]) -> tuple[str, list[str]]:
    invalid = _Refusal(422, {"code": "ITERATION_REQUEST_INVALID"})
    text = " ".join(request.split())
    if not 1 <= len(text) <= MAX_ITERATION_REQUEST or _control(text):
        raise invalid
    if len(assertions) > MAX_NEW_ASSERTIONS:
        raise invalid
    added: list[str] = []
    for item in assertions:
        normalized = " ".join(item.split())
        if not 1 <= len(normalized) <= MAX_OWNER_ASSERTION or _control(normalized):
            raise invalid
        if normalized not in added:
            added.append(normalized)
    return text, added


def _rebased(current: Mapping[str, object], package: Mapping[str, object]) -> dict[str, object]:
    kept = list(current["owner_assertions"])
    assertions = [*kept, *(item for item in package["owner_assertions"] if item not in kept)]
    return {
        **copy.deepcopy(dict(current)),
        "owner_selected_alternative_id": package["owner_selected_alternative_id"],
        "prototype": copy.deepcopy(package["prototype"]),
        "generated_mockup": copy.deepcopy(package["generated_mockup"]),
        "owner_assertions": assertions if len(assertions) <= MAX_OWNER_ASSERTIONS else kept,
    }


def _merged_assertions(current: Sequence[str], added: Sequence[str]) -> list[str]:
    merged = [*current, *(item for item in added if item not in current)]
    if len(merged) > MAX_OWNER_ASSERTIONS:
        raise _Refusal(422, {"code": "ITERATION_REQUEST_INVALID"})
    return merged


PACKAGE_KEYS = (
    "schema_version",
    "project_id",
    "grounding",
    "alternatives",
    "critiques",
    "recommended_alternative_id",
    "owner_selected_alternative_id",
    "prototype",
    "concerns",
    "open_questions",
)
OPTIONAL_PACKAGE_KEYS = ("generated_mockup", "owner_assertions")


def _check_package(package: object) -> None:
    location = ("body", "package")
    if not isinstance(package, dict):
        raise _Invalid([_error(location, "model_type")])
    errors = [_error((*location, key), "missing") for key in PACKAGE_KEYS if key not in package]
    errors.extend(
        _error((*location, key), "extra_forbidden")
        for key in package
        if key not in PACKAGE_KEYS and key not in OPTIONAL_PACKAGE_KEYS
    )
    for key in ("alternatives", "critiques", "concerns", "open_questions"):
        if key in package and not isinstance(package[key], list):
            errors.append(_error((*location, key), "tuple_type"))
    if "owner_assertions" in package and not isinstance(package["owner_assertions"], list):
        errors.append(_error((*location, "owner_assertions"), "tuple_type"))
    for key in ("grounding",):
        if key in package and not isinstance(package[key], dict):
            errors.append(_error((*location, key), "model_type"))
    for key in ("prototype", "generated_mockup"):
        if package.get(key) is not None and not isinstance(package[key], dict):
            errors.append(_error((*location, key), "model_type"))
    for key in ("project_id", "recommended_alternative_id", "owner_selected_alternative_id"):
        value = package.get(key)
        if value is None and key != "project_id":
            continue
        try:
            UUID(str(value))
        except ValueError:
            errors.append(_error((*location, key), "uuid_parsing"))
    if errors:
        raise _Invalid(errors)


def _coherent_package(package: Mapping[str, object]) -> bool:
    alternatives = package["alternatives"]
    if not all(isinstance(item, dict) and "id" in item for item in alternatives):
        return False
    identifiers = {str(item["id"]) for item in alternatives}
    selected = package["owner_selected_alternative_id"]
    if selected is not None and str(selected) not in identifiers:
        return False
    prototype = package["prototype"]
    if prototype is not None and str(prototype.get("design_alternative_id")) != str(selected):
        return False
    bound = package.get("generated_mockup")
    if bound is not None:
        mockup = bound.get("mockup") if isinstance(bound, dict) else None
        if not isinstance(mockup, dict) or str(mockup.get("design_alternative_id")) != str(
            selected
        ):
            return False
    assertions = package.get("owner_assertions") or []
    return len(assertions) <= MAX_OWNER_ASSERTIONS and all(
        isinstance(item, str) and 1 <= len(item) <= MAX_OWNER_ASSERTION for item in assertions
    )


def _design_changes(
    before: Mapping[str, object], after: Mapping[str, object]
) -> list[dict[str, object]]:
    changes = []
    old_selection = before["owner_selected_alternative_id"]
    new_selection = after["owner_selected_alternative_id"]
    if old_selection != new_selection:
        changes.append(
            {
                "kind": "REPLACE" if old_selection and new_selection else "ADD",
                "artifact_kind": "SELECTION",
                "artifact_id": new_selection or old_selection,
                "before": None if old_selection is None else {"alternative_id": old_selection},
                "after": None if new_selection is None else {"alternative_id": new_selection},
            }
        )
    for key, kind, identifier in (
        ("prototype", "PROTOTYPE", "id"),
        ("generated_mockup", "GENERATED_MOCKUP", None),
    ):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        source = new if new is not None else old
        artifact_id = (
            source[identifier]
            if identifier is not None
            else source["mockup"]["design_alternative_id"]
        )
        changes.append(
            {
                "kind": "ADD" if old is None else "REMOVE" if new is None else "REPLACE",
                "artifact_kind": kind,
                "artifact_id": artifact_id,
                "before": None if old is None else {"id": artifact_id},
                "after": None if new is None else {"id": artifact_id},
            }
        )
    old_assertions = list(before.get("owner_assertions") or [])
    new_assertions = list(after.get("owner_assertions") or [])
    for text in new_assertions:
        if text not in old_assertions:
            changes.append(_assertion_change("ADD", text))
    for text in old_assertions:
        if text not in new_assertions:
            changes.append(_assertion_change("REMOVE", text))
    for key, kind in (
        ("alternatives", "ALTERNATIVE"),
        ("critiques", "CRITIQUE"),
        ("concerns", "CONCERN"),
        ("open_questions", "OPEN_QUESTIONS"),
    ):
        if before[key] != after[key]:
            changes.append(
                {
                    "kind": "REPLACE",
                    "artifact_kind": kind,
                    "artifact_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{kind}:{_digest(after[key])}")
                    ),
                    "before": None,
                    "after": None,
                }
            )
    return changes


def _assertion_change(kind: str, text: str) -> dict[str, object]:
    identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, f"assertion:{text}"))
    return {
        "kind": kind,
        "artifact_kind": "OWNER_ASSERTION",
        "artifact_id": identifier,
        "before": None if kind == "ADD" else {"text": text},
        "after": {"text": text} if kind == "ADD" else None,
    }


def _multipart(content_type: str, body: bytes) -> dict[str, tuple[str | None, bytes]]:
    if not content_type.lower().startswith("multipart/form-data"):
        return {}
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body
    )
    if not message.is_multipart():
        return {}
    fields: dict[str, tuple[str | None, bytes]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str):
            continue
        payload = part.get_payload(decode=True)
        fields[name] = (part.get_filename(), payload if isinstance(payload, bytes) else b"")
    return fields
