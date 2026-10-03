import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, vShow, withDirectives } from "vue";

import { createAppI18n } from "@/i18n";
import { createDesignApi, DesignApiError, type DesignApi } from "../api/design";
import {
  DesignAlignmentApiError,
  type DesignAlignmentApi,
  type DesignAlignmentPayload,
} from "../api/designAlignment";
import type { DesignIterationsApi } from "../api/designIterations";
import type { DesignLoopApi } from "../api/designLoop";
import { DesignMockupsApiError, type DesignMockupsApi } from "../api/designMockups";
import type { DesignReviewPinsApi } from "../api/designReviewPins";
import {
  clearFollowedGenerations,
  generationJobsApi,
  type GenerationRequestJob,
} from "../api/generationJobs";
import type { ModelUsageApi } from "../api/modelUsage";
import { useInsightTrayStore } from "../stores/insightTray";
import { useGuidanceStore } from "../stores/guidance";
import { expectAccessible } from "../test/axe";
import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_CREATED_AT,
  DESIGN_OWNER_ID,
  DESIGN_PROJECT_ID,
  PENDING_DESIGN_GATE,
  PROPOSED_DESIGN_DIFF,
  SECOND_DESIGN_ALTERNATIVE_ID,
  SELECTED_DESIGN_PACKAGE,
  SELECTED_DESIGN_VERSION,
  UNSELECTED_DESIGN_VERSION,
} from "../test/designFixtures";
import { buildSelectedDesignPackage } from "../test/prototypeFixtures";
import type {
  DesignChangePayload,
  DesignGenerationIssue,
  DesignGenerationPayload,
  DesignMockupPayload,
  DesignMockupRequest,
  DesignPackageDiffPayload,
  DesignPackagePayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
  SyntheticDesignCritiquePayload,
} from "../types/design";
import type {
  DesignEvaluationRunPayload,
  InsightApplicationPayload,
  SyntheticFindingPayload,
} from "../types/designLoop";
import type {
  BoundGeneratedMockupPayload,
  DesignMockupCapabilitiesPayload,
  GenerationJobPayload,
  MockupDocumentPayload,
  MockupResultPayload,
  ReviewPinsPayload,
} from "../types/designMockups";
import type {
  RequirementsGateDecisionPayload,
  RequirementsGateSubmissionPayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationPayload,
  RequirementsSpecificationVersionPayload,
} from "../types/requirements";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import ProjectDesignEvaluationPanel from "./ProjectDesignEvaluationPanel.vue";
import ProjectDesignDiscussionPanel from "./ProjectDesignDiscussionPanel.vue";
import ProjectDesignFlow, {
  designChangeQuote,
  designChangeSentence,
  readablePlace,
} from "./ProjectDesignFlow.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");
const TWIN_ID = BASE_DESIGN_PACKAGE.grounding.user_twin_references[0]!.twin_id;
const STARTED_AT = "2026-09-29T09:12:03+00:00";

const loopApi: DesignLoopApi = {
  evaluate: async () => {
    throw new Error("not evaluated in this spec");
  },
  runs: async () => [],
  comparison: async () => null,
  regenerate: async () => ({ status: "REJECTED", issue: "DESIGN_PACKAGE_NOT_FOUND" }) as never,
  applyInsight: async () => {
    throw new Error("not applied in this spec");
  },
  applications: async () => [],
  validations: async () => [],
  validate: async () => {
    throw new Error("not decided in this spec");
  },
  discussions: async () => [],
  startDiscussion: async () => {
    throw new Error("not discussed in this spec");
  },
  nextDiscussionRound: async () => {
    throw new Error("not discussed in this spec");
  },
  decideDiscussion: async () => {
    throw new Error("not discussed in this spec");
  },
};

const DESIGN_REQUIREMENTS = SELECTED_DESIGN_PACKAGE.grounding.requirements_reference;

function requirementsVersion(
  id: string,
  number: number,
  contentHash: string,
): RequirementsSpecificationVersionPayload {
  return {
    id,
    project_id: DESIGN_PROJECT_ID,
    version_number: number,
    based_on_version_number: number > 1 ? number - 1 : null,
    content_hash: contentHash,
    created_by_user_id: DESIGN_OWNER_ID,
    created_at: DESIGN_CREATED_AT,
    specification: {} as RequirementsSpecificationPayload,
  };
}

const REQUIREMENTS_V1 = requirementsVersion(
  DESIGN_REQUIREMENTS.artifact_id,
  DESIGN_REQUIREMENTS.version_number,
  DESIGN_REQUIREMENTS.content_hash,
);
const REQUIREMENTS_V2 = requirementsVersion(
  "00000000-0000-4000-8000-000000000170",
  2,
  "7".repeat(64),
);

const REGENERATED_DESIGN_VERSION: DesignPackageVersionPayload = {
  ...SELECTED_DESIGN_VERSION,
  id: "00000000-0000-4000-8000-000000000180",
  version_number: 3,
  based_on_version_number: 2,
  content_hash: "8".repeat(64),
  package: {
    ...SELECTED_DESIGN_PACKAGE,
    grounding: {
      ...SELECTED_DESIGN_PACKAGE.grounding,
      requirements_reference: {
        ...DESIGN_REQUIREMENTS,
        artifact_id: REQUIREMENTS_V2.id,
        version_number: REQUIREMENTS_V2.version_number,
        content_hash: REQUIREMENTS_V2.content_hash,
      },
    },
  },
};

function generatedMockup(
  alternativeId: string,
  title = "Reservation desk",
): BoundGeneratedMockupPayload {
  return {
    mockup: {
      contract_version: 1,
      design_alternative_id: alternativeId,
      title,
      styles: ".desk{display:grid}",
      screens: [
        { code: "SCR-001", title: "Desk", state: "DEFAULT", markup: "<h1>Desk</h1>" },
        { code: "SCR-002", title: "Booking", state: "DEFAULT", markup: "<h1>Booking</h1>" },
      ],
    },
    requirement_ids_by_code: {},
  };
}

const CRITIQUES_WITH_VERDICTS: SyntheticDesignCritiquePayload[] = [
  {
    ...BASE_DESIGN_PACKAGE.critiques[0]!,
    verdict: "Useful, with doubts",
    quote: "I see the next arrival, but the flow slows me down at peak times.",
  },
  {
    ...BASE_DESIGN_PACKAGE.critiques[0]!,
    id: "00000000-0000-4000-8000-000000000143",
    code: "CRQ-002",
    design_alternative_id: SECOND_DESIGN_ALTERNATIVE_ID,
    verdict: "Too dense for a shift",
    quote: "The tiles are many and I lose the queue.",
    concerns: ["Dense tiles may hide the next arrival."],
    suggested_changes: ["Pin the next arrival above the tiles."],
  },
];

const GENERATED_UNSELECTED: DesignPackageVersionPayload = {
  ...UNSELECTED_DESIGN_VERSION,
  package: { ...BASE_DESIGN_PACKAGE, critiques: CRITIQUES_WITH_VERDICTS },
};

const GENERATED_SELECTED: DesignPackageVersionPayload = {
  ...SELECTED_DESIGN_VERSION,
  package: {
    ...SELECTED_DESIGN_PACKAGE,
    critiques: CRITIQUES_WITH_VERDICTS,
    generated_mockup: generatedMockup(DESIGN_ALTERNATIVE_ID),
    owner_assertions: ["The tone stays kind"],
  },
};

const REANCHORED_DESIGN_VERSION: DesignPackageVersionPayload = {
  ...GENERATED_SELECTED,
  id: "00000000-0000-4000-8000-0000000001a0",
  version_number: 3,
  based_on_version_number: 2,
  content_hash: "a".repeat(64),
  package: {
    ...GENERATED_SELECTED.package,
    grounding: {
      ...GENERATED_SELECTED.package.grounding,
      requirements_reference: {
        ...DESIGN_REQUIREMENTS,
        artifact_id: REQUIREMENTS_V2.id,
        version_number: REQUIREMENTS_V2.version_number,
        content_hash: REQUIREMENTS_V2.content_hash,
      },
    },
  },
};

function alignment(overrides: Partial<DesignAlignmentPayload> = {}): DesignAlignmentPayload {
  return {
    aligned: false,
    issue: null,
    design_version_number: 2,
    grounded_requirements_version_number: 1,
    requirements_version_number: 2,
    missing_codes: [],
    uncovered_codes: [],
    ...overrides,
  };
}

function alignmentRouteMissing(): DesignAlignmentApiError {
  return new DesignAlignmentApiError("The design alignment request failed", {
    status: 404,
    code: null,
    payload: { detail: "Not Found" },
  });
}

function fakeAlignmentApi(answer: DesignAlignmentPayload | Error) {
  return {
    status: vi.fn(async (): Promise<DesignAlignmentPayload> => {
      if (answer instanceof Error) {
        throw answer;
      }
      return answer;
    }),
  } satisfies Pick<DesignAlignmentApi, "status">;
}

function mockupResult(
  alternativeId: string,
  version: DesignPackageVersionPayload = GENERATED_UNSELECTED,
  overrides: Partial<MockupResultPayload> = {},
): MockupResultPayload {
  return {
    status: "MOCKUP_GENERATED",
    generation_id: `generation-${alternativeId.slice(-3)}`,
    design_version_id: version.id,
    design_content_hash: version.content_hash,
    package: {
      ...buildSelectedDesignPackage(version.package, alternativeId),
      generated_mockup: generatedMockup(alternativeId),
    },
    approach: "A calm desk first",
    changes: [],
    warnings: [],
    cost_microusd: 412000,
    ...overrides,
  };
}

function job(
  alternativeId: string | null,
  status: GenerationJobPayload["status"] = "RUNNING",
  overrides: Partial<GenerationJobPayload> = {},
): GenerationJobPayload {
  return {
    job_id: `job-${alternativeId?.slice(-3) ?? "iteration"}`,
    kind: alternativeId === null ? "ITERATION" : "MOCKUP",
    status,
    stage: status === "RUNNING" ? "GENERATING" : null,
    attempt: 1,
    started_at: STARTED_AT,
    finished_at: status === "RUNNING" ? null : STARTED_AT,
    alternative_id: alternativeId,
    result: null,
    failure: null,
    ...overrides,
  };
}

function mockupDocument(
  alternativeId: string,
  source: MockupDocumentPayload["source"],
  entry = "SCR-001",
): MockupDocumentPayload {
  return {
    html: `<!doctype html><html lang="en"><body><h1 class="${source}-marker">${alternativeId} ${entry}</h1></body></html>`,
    content_hash: `${source}-${alternativeId}`.padEnd(64, "0"),
    source,
    alternative_id: alternativeId,
    title: "Reservation desk",
    entry_screen: entry,
    screens: [
      { code: "SCR-001", title: "Desk", state: "DEFAULT" },
      { code: "SCR-002", title: "Booking", state: "DEFAULT" },
    ],
  };
}

function notFound(code: string | null): DesignMockupsApiError {
  return new DesignMockupsApiError(code ?? "Design Mockups API request failed with status 404", {
    status: 404,
    code,
    payload: code === null ? { detail: "Not Found" } : { detail: { code } },
  });
}

interface MockupsFake {
  capabilities?: DesignMockupCapabilitiesPayload | Error;
  latest?: Record<string, MockupResultPayload | null>;
  documents?: Record<string, MockupDocumentPayload>;
  started?: (alternativeId: string) => GenerationJobPayload;
}

const GENERATED: DesignMockupCapabilitiesPayload = {
  generated_mockups: true,
  iterations: true,
  model: "claude-opus-5-5",
};

function fakeMockupsApi(options: MockupsFake = {}) {
  return {
    capabilities: vi.fn(async () => {
      const value = options.capabilities ?? notFound(null);
      if (value instanceof Error) {
        throw value;
      }
      return value;
    }),
    startJob: vi.fn(async (_project: string, request: { alternative_id: string }) =>
      options.started === undefined
        ? job(request.alternative_id)
        : options.started(request.alternative_id),
    ),
    job: vi.fn(async (_project: string, jobId: string) =>
      job(jobId.replace("job-", "00000000-0000-4000-8000-000000000"), "REJECTED", {
        job_id: jobId,
        failure: { code: "MOCKUP_QUALITY_REJECTED", reasons: [] },
      }),
    ),
    latest: vi.fn(async (_project: string, alternativeId: string) => {
      return options.latest?.[alternativeId] ?? null;
    }),
    document: vi.fn(
      async (
        _project: string,
        query: { alternative_id: string; source: string; entry_screen?: string },
      ) => {
        const found = options.documents?.[`${query.alternative_id}|${query.source}`];
        if (found === undefined) {
          throw notFound("GENERATED_MOCKUP_NOT_FOUND");
        }
        return query.entry_screen === undefined
          ? found
          : { ...found, entry_screen: query.entry_screen };
      },
    ),
  } satisfies DesignMockupsApi;
}

function fakeIterationsApi(started: () => GenerationJobPayload) {
  return {
    startJob: vi.fn<DesignIterationsApi["startJob"]>(async () => started()),
    job: vi.fn(async () => started()),
    list: vi.fn(async () => ({ items: [] })),
  } satisfies DesignIterationsApi;
}

function fakeUsageApi(cost = 412000) {
  return {
    usage: vi.fn(async () => ({
      items: [
        {
          generation_id: "generation-usage-1",
          recorded_at: STARTED_AT,
          task: "design",
          purpose: "DESIGN_MOCKUP_HTML",
          provider_kind: "ANTHROPIC_HOSTED" as const,
          model: "claude-opus-5-5",
          status: "SUCCEEDED",
          failure_code: null,
          input_tokens: 10234,
          output_tokens: 17890,
          reasoning_tokens: 3120,
          cache_read_input_tokens: 0,
          cache_write_input_tokens: 0,
          cost_microusd: cost,
          latency_milliseconds: 184000,
        },
      ],
      totals: {
        generations: 1,
        input_tokens: 10234,
        output_tokens: 17890,
        reasoning_tokens: 3120,
        cost_microusd: cost,
      },
    })),
    budget: vi.fn(async () => {
      throw new Error("not used in this spec");
    }),
  } satisfies ModelUsageApi;
}

function fakeSubscriptionUsageApi() {
  const paid = fakeUsageApi(412000);
  return {
    ...paid,
    usage: vi.fn(async () => {
      const report = await paid.usage();
      return {
        items: [
          {
            ...report.items[0]!,
            generation_id: "generation-usage-2",
            provider_kind: "CLAUDE_CODE_CLI" as const,
            cost_microusd: null,
          },
          ...report.items,
        ],
        totals: { ...report.totals, generations: 2 },
      };
    }),
  } satisfies ModelUsageApi;
}

function readyRequirements(version: RequirementsSpecificationVersionPayload) {
  return {
    status: "READY_FOR_DESIGN_EXPLORATION" as const,
    version,
    gate: null,
    approved_current_specification: true,
  };
}

class FakeRequirementsGate {
  current: RequirementsReadinessPayload;

  constructor(initial: RequirementsReadinessPayload) {
    this.current = initial;
  }

  readiness = vi.fn(async () => this.current);

  submitGate = vi.fn(async (): Promise<RequirementsGateSubmissionPayload> => {
    return { status: "SUBMITTED", gate: null, events: [], issue: null };
  });

  decideGate = vi.fn(async (): Promise<RequirementsGateDecisionPayload> => {
    this.current = readyRequirements(REQUIREMENTS_V2);
    return { status: "APPLIED", gate: null, event: null, issue: null };
  });
}

function fakeLoopApi(): DesignLoopApi {
  return {
    ...loopApi,
    runs: vi.fn(async () => []),
    regenerate: vi.fn(),
    applyInsight: vi.fn(),
    validations: vi.fn(async () => []),
    discussions: vi.fn(async () => []),
  };
}

function reviewingLoopApi(): DesignLoopApi {
  return { ...fakeLoopApi(), evaluate: vi.fn(async () => evaluationRun()) };
}

function rejected(issue: DesignGenerationIssue): DesignGenerationPayload {
  return {
    status: "REJECTED",
    version: null,
    issue,
    proposal_issue: null,
    persistence_status: null,
  };
}

function finding(id: string, summary: string, twinId = "twin-1"): SyntheticFindingPayload {
  return {
    finding_id: id,
    twin_id: twinId,
    twin_version: 1,
    artifact_id: "prototype-1",
    artifact_version: 1,
    location: "SCR-001 Guest name",
    summary,
    rationale: "The receptionist types under time pressure.",
    criterion: "comprehensibility",
    severity: "major",
    epistemic_status: "MODEL_INFERRED",
    evidence_refs: [],
    confidence: 0.7,
    confidence_semantics: "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED",
    recommended_action: "Add a format hint.",
    requires_human_validation: true,
    model_config_ref: "config",
    prompt_version_ref: "prompt",
    is_simulated_feedback: true,
    content_hash: id.repeat(16).slice(0, 64),
  };
}

function evaluationRun(
  twinId = "twin-1",
  version: DesignPackageVersionPayload = SELECTED_DESIGN_VERSION,
  findings: SyntheticFindingPayload[] = [finding("UTF-001", "The guest name lacks a format hint.")],
): DesignEvaluationRunPayload {
  return {
    schema_version: 1,
    id: "run-1",
    project_id: DESIGN_PROJECT_ID,
    owner_user_id: DESIGN_OWNER_ID,
    design_version_id: version.id,
    design_version_number: version.version_number,
    design_content_hash: version.content_hash,
    alternative_id: DESIGN_ALTERNATIVE_ID,
    alternative_code: "DES-001",
    bundle: {},
    responses: [
      {
        evaluation_run_id: "run-1",
        artifact_bundle_id: "bundle-1",
        artifact_bundle_hash: "b".repeat(64),
        twin_id: twinId,
        twin_version: 1,
        evaluator: {
          evaluator_id: "proposer-design-twin-review",
          evaluator_version: "1",
          model_config_ref: "config",
          prompt_version_ref: "prompt",
        },
        findings,
        summary: "The flow is short.",
        evidence_gaps: [],
        is_simulated_feedback: true,
        completed_at: DESIGN_CREATED_AT,
        content_hash: "d".repeat(64),
        disclaimer: "Simulated feedback.",
      },
    ],
    started_at: DESIGN_CREATED_AT,
    completed_at: DESIGN_CREATED_AT,
    content_hash: "e".repeat(64),
  };
}

const REQUIREMENTS_APPLICATION: InsightApplicationPayload = {
  id: "application-1",
  project_id: DESIGN_PROJECT_ID,
  owner_user_id: DESIGN_OWNER_ID,
  source_kind: "SYNTHETIC_FINDING",
  source_id: "run:run-1:twin-1:UTF-001",
  source_twin_id: "twin-1",
  text: "The guest name lacks a format hint.",
  target: "REQUIREMENTS",
  target_field: null,
  target_version_id: REQUIREMENTS_V2.id,
  target_version_number: 2,
  target_code: "REQ-004",
  created_at: DESIGN_CREATED_AT,
  content_hash: "c".repeat(64),
};

class FakeDesignApi implements DesignApi {
  savedMockups: Record<string, DesignMockupPayload | null> = {};
  failApproval = 0;
  approvedVersion: DesignPackageVersionPayload = SELECTED_DESIGN_VERSION;
  proposedPackage: DesignPackagePayload | null = null;
  proposals: DesignPackagePayload[] = [];
  decisions: string[] = [];
  gateActions: { action: string; reason: string | null | undefined }[] = [];
  submissions = 0;
  readinessResult: DesignReadinessPayload = {
    status: "DESIGN_REVIEW_REQUIRED",
    version: UNSELECTED_DESIGN_VERSION,
    gate: null,
    has_package: true,
    package_ready_for_gate: false,
    approved_current_package: false,
  };
  historyResult: DesignPackageVersionPayload[] = [UNSELECTED_DESIGN_VERSION];
  diffsResult: DesignPackageDiffPayload[] = [];

  constructor(version: DesignPackageVersionPayload = UNSELECTED_DESIGN_VERSION) {
    this.readinessResult = {
      ...this.readinessResult,
      status: version.ready_for_gate ? "DESIGN_APPROVAL_REQUIRED" : "DESIGN_REVIEW_REQUIRED",
      version,
      package_ready_for_gate: version.ready_for_gate,
    };
    this.historyResult = [version];
  }

  generateMockup = vi.fn(async (_projectId: string, request: DesignMockupRequest) => {
    const result = {
      status: "MOCKUP_GENERATED" as const,
      generation_id: "test-generation",
      design_version_id: request.design_version_id,
      design_content_hash: request.design_content_hash,
      package: buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, request.alternative_id),
    };
    this.savedMockups[request.alternative_id] = result;
    return result;
  });

  currentMockup = vi.fn(async (_projectId: string, alternativeId: string) => {
    return this.savedMockups[alternativeId] ?? null;
  });

  async generate() {
    return {
      status: "CREATED" as const,
      version: UNSELECTED_DESIGN_VERSION,
      issue: null,
      proposal_issue: null,
      persistence_status: "APPENDED" as const,
    };
  }

  async current() {
    return this.readinessResult.version ?? UNSELECTED_DESIGN_VERSION;
  }

  async history() {
    return this.historyResult;
  }

  proposeRevision = vi.fn(
    async (_projectId: string, request: { package: DesignPackagePayload }) => {
      this.proposedPackage = request.package;
      this.proposals.push(request.package);
      const base = this.readinessResult.version?.package ?? BASE_DESIGN_PACKAGE;
      this.diffsResult = [
        {
          ...PROPOSED_DESIGN_DIFF,
          proposed_package: request.package,
          changes: [
            {
              kind: "REPLACE",
              artifact_kind: "SELECTION",
              artifact_id: DESIGN_PROJECT_ID,
              before: {
                recommended_alternative_id: base.recommended_alternative_id,
                owner_selected_alternative_id: base.owner_selected_alternative_id,
              },
              after: {
                recommended_alternative_id: request.package.recommended_alternative_id,
                owner_selected_alternative_id: request.package.owner_selected_alternative_id,
              },
            },
            {
              kind: "ADD",
              artifact_kind: "PROTOTYPE",
              artifact_id: request.package.prototype?.id ?? DESIGN_ALTERNATIVE_ID,
              before: null,
              after: null,
            },
          ],
        },
      ];
      return {
        status: "CREATED" as const,
        diff: this.diffsResult[0] ?? null,
        version: null,
        issue: null,
        domain_issue: null,
        diff_persistence_status: "CREATED" as const,
        version_persistence_status: null,
      };
    },
  );

  async revisionHistory() {
    return this.diffsResult;
  }

  async getRevision() {
    return this.diffsResult[0] ?? PROPOSED_DESIGN_DIFF;
  }

  decideRevision = vi.fn(
    async (
      _projectId: string,
      _diffId: string,
      request: { decision: "APPROVE" | "REJECT"; reason?: string | null },
    ) => {
      this.decisions.push(request.decision);
      if (this.failApproval > 0) {
        this.failApproval -= 1;
        throw new Error("Design API request failed with status 503");
      }
      const currentDiff = this.diffsResult[0] ?? PROPOSED_DESIGN_DIFF;
      const decided = {
        ...currentDiff,
        status: request.decision === "APPROVE" ? ("APPROVED" as const) : ("REJECTED" as const),
        decided_by_user_id: DESIGN_OWNER_ID,
        decided_at: DESIGN_CREATED_AT,
        decision_reason: request.reason ?? null,
        applied_version_id: request.decision === "APPROVE" ? this.approvedVersion.id : null,
      };
      this.diffsResult = [decided];
      if (request.decision === "APPROVE") {
        this.readinessResult = {
          status: "DESIGN_APPROVAL_REQUIRED",
          version: this.approvedVersion,
          gate: null,
          has_package: true,
          package_ready_for_gate: true,
          approved_current_package: false,
        };
        this.historyResult = [...this.historyResult, this.approvedVersion];
      }
      return {
        status: "APPLIED" as const,
        diff: decided,
        version: request.decision === "APPROVE" ? this.approvedVersion : null,
        issue: null,
        domain_issue: null,
        diff_persistence_status: "UPDATED" as const,
        version_persistence_status: request.decision === "APPROVE" ? ("APPENDED" as const) : null,
      };
    },
  );

  async submitGate() {
    this.submissions += 1;
    const version = this.readinessResult.version ?? SELECTED_DESIGN_VERSION;
    const gate = {
      ...PENDING_DESIGN_GATE,
      artifact: {
        ...PENDING_DESIGN_GATE.artifact,
        artifact_id: version.id,
        version: version.version_number,
        content_hash: version.content_hash,
      },
    };
    this.readinessResult = { ...this.readinessResult, gate };
    return { status: "SUBMITTED" as const, gate, events: [], issue: null };
  }

  decideGate = vi.fn(
    async (_projectId: string, request: { action: string; reason?: string | null }) => {
      this.gateActions.push({ action: request.action, reason: request.reason });
      const gate = this.readinessResult.gate ?? PENDING_DESIGN_GATE;
      const status =
        request.action === "APPROVE"
          ? ("APPROVED" as const)
          : request.action === "REQUEST_REVISION"
            ? ("REVISION_REQUESTED" as const)
            : gate.status;
      const decided = { ...gate, status };
      this.readinessResult = {
        ...this.readinessResult,
        status:
          request.action === "APPROVE"
            ? "READY_FOR_ARCHITECTURE_PLANNING"
            : this.readinessResult.status,
        gate: decided,
        approved_current_package: request.action === "APPROVE",
      };
      return { status: "APPLIED" as const, gate: decided, event: null, issue: null };
    },
  );

  async currentGate() {
    return this.readinessResult.gate ?? PENDING_DESIGN_GATE;
  }

  async gateEvents() {
    return [];
  }

  async readiness() {
    return this.readinessResult;
  }
}

function approvedReadiness(version: DesignPackageVersionPayload): DesignReadinessPayload {
  return {
    status: "READY_FOR_ARCHITECTURE_PLANNING",
    version,
    gate: {
      ...PENDING_DESIGN_GATE,
      status: "APPROVED",
      artifact: {
        ...PENDING_DESIGN_GATE.artifact,
        artifact_id: version.id,
        version: version.version_number,
        content_hash: version.content_hash,
      },
    },
    has_package: true,
    package_ready_for_gate: true,
    approved_current_package: true,
  };
}

function designToPrepare(version: DesignPackageVersionPayload): FakeDesignApi {
  const api = new FakeDesignApi(version);
  const prepared = api.readinessResult;
  api.readinessResult = {
    status: "DESIGN_REQUIRED",
    version: null,
    gate: null,
    has_package: false,
    package_ready_for_gate: false,
    approved_current_package: false,
  };
  api.historyResult = [];
  vi.spyOn(api, "generate").mockImplementation(async () => {
    api.readinessResult = prepared;
    api.historyResult = [version];
    return {
      status: "CREATED" as const,
      version,
      issue: null,
      proposal_issue: null,
      persistence_status: "APPENDED" as const,
    };
  });
  return api;
}

interface MountOptions {
  locale?: "en" | "it";
  loop?: DesignLoopApi;
  requirementsApi?: FakeRequirementsGate;
  alignmentApi?: Pick<DesignAlignmentApi, "status">;
  sectionsMode?: boolean;
  mockupsApi?: DesignMockupsApi;
  iterationsApi?: DesignIterationsApi;
  pinsApi?: DesignReviewPinsApi;
  usageApi?: ModelUsageApi;
  attach?: boolean;
  pinia?: Pinia;
  stubs?: Record<string, boolean>;
}

const mounted: VueWrapper[] = [];

function mountFlow(api: FakeDesignApi, options: MountOptions = {}) {
  const locale = options.locale ?? "en";
  const wrapper = mount(ProjectDesignFlow, {
    props: {
      projectId: DESIGN_PROJECT_ID,
      locale,
      authorize,
      api,
      loopApi: options.loop ?? loopApi,
      requirementsApi:
        options.requirementsApi ?? new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1)),
      alignmentApi: options.alignmentApi ?? fakeAlignmentApi(alignmentRouteMissing()),
      ...(options.sectionsMode === undefined ? {} : { sectionsMode: options.sectionsMode }),
      mockupsApi: options.mockupsApi ?? fakeMockupsApi(),
      ...(options.iterationsApi === undefined ? {} : { iterationsApi: options.iterationsApi }),
      ...(options.pinsApi === undefined ? {} : { pinsApi: options.pinsApi }),
      usageApi: options.usageApi ?? fakeUsageApi(),
    },
    global: {
      plugins: [...(options.pinia === undefined ? [] : [options.pinia]), createAppI18n(locale)],
      stubs: { ProjectHumanValidationPanel: true, ...options.stubs },
    },
    ...(options.attach === true ? { attachTo: document.body } : {}),
  });
  mounted.push(wrapper);
  return wrapper;
}

function card(wrapper: VueWrapper, code: string) {
  return wrapper.get(`[data-test="alternative-${code}"]`);
}

function barOf(wrapper: VueWrapper) {
  return wrapper.get('[data-testid="decision-bar"]');
}

describe("ProjectDesignFlow", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setActivePinia(createPinia());
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
    vi.useRealTimers();
  });

  it("restores a model mockup without changing the approved design or submitting a revision", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    api.savedMockups[DESIGN_ALTERNATIVE_ID] = {
      status: "MOCKUP_GENERATED",
      generation_id: "persisted-generation",
      design_version_id: SELECTED_DESIGN_VERSION.id,
      design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
      package: {
        ...SELECTED_DESIGN_VERSION.package,
        prototype: {
          ...SELECTED_DESIGN_VERSION.package.prototype!,
          title: "Persisted visual mockup",
        },
      },
    };
    const wrapper = mountFlow(api);
    await flushPromises();
    expect(wrapper.get("[data-design-mockup]").text()).toContain("Persisted visual mockup");
    expect(wrapper.get("[data-design-mockup]").text()).toContain("not applied");
    expect(api.proposedPackage).toBeNull();
    expect(api.decideRevision).not.toHaveBeenCalled();
    expect(api.readinessResult.version?.id).toBe(SELECTED_DESIGN_VERSION.id);
  });

  it("applies the chosen alternative in one press: proposal and approval of the revision", async () => {
    const api = new FakeDesignApi();
    const wrapper = mountFlow(api);
    await flushPromises();

    expect(wrapper.text()).toContain("Guided reservation flow");
    expect(wrapper.get('[data-testid="design-twin-matrix-simulated"]').text()).toBe(
      "Simulated feedback, not evidence",
    );
    const choose = card(wrapper, "DES-002").get('[data-testid="alternative-choose"]');
    expect(choose.attributes("disabled")).toBeDefined();
    expect(card(wrapper, "DES-002").get('[data-testid="alternative-hint"]').text()).toBe(
      "Try the mockup first: then you can choose it.",
    );

    await card(wrapper, "DES-002").get('[data-testid="alternative-open"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="design-preview"]').text()).toContain(
      "This alternative has no preview yet.",
    );
    await wrapper.get('[data-testid="design-create-preview"]').trigger("click");
    await flushPromises();
    expect(api.generateMockup).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="design-preview"]').text()).toContain(
      "Model-generated draft · not applied",
    );
    expect(wrapper.get('[data-testid="design-preview"]').text()).toContain(
      "the application is built from the knowledge folder with your own tools.",
    );
    expect(api.proposedPackage).toBeNull();
    expect(wrapper.emitted("sections-changed")).toBeUndefined();

    await card(wrapper, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    await flushPromises();

    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(api.proposeRevision).toHaveBeenCalledTimes(1);
    expect(api.proposedPackage?.owner_selected_alternative_id).toBe(SECOND_DESIGN_ALTERNATIVE_ID);
    expect(api.proposedPackage?.prototype?.design_alternative_id).toBe(
      SECOND_DESIGN_ALTERNATIVE_ID,
    );
    expect(api.decisions).toEqual(["APPROVE"]);
    expect(wrapper.find('[data-testid="design-pending-changes"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-error"]').exists()).toBe(false);
  });

  it("completes with the same button what is left when only the approval failed", async () => {
    const api = new FakeDesignApi();
    api.failApproval = 1;
    api.savedMockups[SECOND_DESIGN_ALTERNATIVE_ID] = {
      status: "MOCKUP_GENERATED",
      generation_id: "saved-generation",
      design_version_id: UNSELECTED_DESIGN_VERSION.id,
      design_content_hash: UNSELECTED_DESIGN_VERSION.content_hash,
      package: buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, SECOND_DESIGN_ALTERNATIVE_ID),
    };
    const wrapper = mountFlow(api, { locale: "it" });
    await flushPromises();

    await card(wrapper, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    await flushPromises();
    expect(api.proposeRevision).toHaveBeenCalledTimes(1);
    expect(api.decisions).toEqual(["APPROVE"]);
    expect(wrapper.get('[data-testid="design-error"]').text()).toBe(
      "La tua scelta è registrata ma non è ancora stata applicata. Premi di nuovo «Scegli questa».",
    );
    expect(wrapper.text()).not.toContain("503");
    const pending = wrapper.get('[data-testid="design-pending-change"]');
    expect(pending.findAll('[data-testid="design-change"]').map((item) => item.text())).toEqual([
      "Scegli DES-002 · Reservation operations dashboard",
      "Si aggiunge il mockup del design scelto",
    ]);
    expect(card(wrapper, "DES-001").get('[data-testid="alternative-hint"]').text()).toBe(
      "Decidi prima la modifica che aspetta qui sopra.",
    );

    await card(wrapper, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    await flushPromises();
    expect(api.proposeRevision).toHaveBeenCalledTimes(1);
    expect(api.decisions).toEqual(["APPROVE", "APPROVE"]);
    expect(wrapper.find('[data-testid="design-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-pending-changes"]').exists()).toBe(false);
  });

  it.each(
    (["it", "en"] as const).flatMap((locale) =>
      [UNSELECTED_DESIGN_VERSION, SELECTED_DESIGN_VERSION].flatMap((version) =>
        (["proposal", "decision"] as const).map((operation) => ({ locale, version, operation })),
      ),
    ),
  )(
    "explains an outdated upstream step in $locale during $operation and preserves the current choice",
    async ({ locale, version, operation }) => {
      const api = new FakeDesignApi(version);
      const loop = reviewingLoopApi();
      const rejected = new DesignApiError("The design request failed", {
        status: 409,
        code: "DESIGN_CONTEXT_CHANGED",
        payload: null,
      });
      if (operation === "proposal") api.proposeRevision.mockRejectedValueOnce(rejected);
      else {
        api.diffsResult = [
          {
            ...PROPOSED_DESIGN_DIFF,
            proposed_package: buildSelectedDesignPackage(
              version.package,
              SECOND_DESIGN_ALTERNATIVE_ID,
            ),
          },
        ];
        api.decideRevision.mockRejectedValueOnce(rejected);
      }
      api.savedMockups[SECOND_DESIGN_ALTERNATIVE_ID] = {
        status: "MOCKUP_GENERATED",
        generation_id: "saved-generation",
        design_version_id: version.id,
        design_content_hash: version.content_hash,
        package: buildSelectedDesignPackage(version.package, SECOND_DESIGN_ALTERNATIVE_ID),
      };
      const wrapper = mountFlow(api, { locale, loop });
      await flushPromises();
      await card(wrapper, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
      await flushPromises();
      expect(wrapper.get('[data-testid="design-error"]').text()).toBe(
        locale === "it"
          ? "Un passo precedente è da aggiornare. Rivedi quel passo prima di scegliere un'alternativa di design. La scelta attuale non è cambiata."
          : "An earlier step needs updating. Review that step before choosing a design alternative. Your current choice is unchanged.",
      );
      expect(wrapper.get('[data-testid="design-error"]').text()).not.toMatch(
        /DESIGN_CONTEXT_CHANGED|Riprova|Try again|Premi di nuovo|Press .*again/,
      );
      expect(api.proposeRevision).toHaveBeenCalledTimes(operation === "proposal" ? 1 : 0);
      expect(api.decideRevision).toHaveBeenCalledTimes(operation === "decision" ? 1 : 0);
      expect(api.readinessResult.version).toBe(version);
      expect(api.historyResult).toEqual([version]);
      expect(api.readinessResult.version?.package.owner_selected_alternative_id).toBe(
        version.package.owner_selected_alternative_id,
      );
      expect(card(wrapper, "DES-001").attributes("data-chosen")).toBe(
        version.package.owner_selected_alternative_id === DESIGN_ALTERNATIVE_ID ? "true" : "false",
      );
      expect(card(wrapper, "DES-002").attributes("data-chosen")).toBe("false");
      expect(api.submissions).toBe(0);
      expect(api.gateActions).toEqual([]);
      expect(api.generateMockup).not.toHaveBeenCalled();
      expect(loop.evaluate).not.toHaveBeenCalled();
      expect(loop.regenerate).not.toHaveBeenCalled();
      expect(wrapper.emitted("sections-changed")).toBeUndefined();
      await flushPromises();
      expect(api.proposeRevision).toHaveBeenCalledTimes(operation === "proposal" ? 1 : 0);
      expect(api.decideRevision).toHaveBeenCalledTimes(operation === "decision" ? 1 : 0);
    },
  );

  it.each(["it", "en"] as const)(
    "keeps the retry message for a transient choice proposal failure in %s",
    async (locale) => {
      const api = new FakeDesignApi();
      api.proposeRevision.mockRejectedValueOnce(
        new DesignApiError("The design request failed", { status: 503, code: null, payload: null }),
      );
      api.savedMockups[SECOND_DESIGN_ALTERNATIVE_ID] = {
        status: "MOCKUP_GENERATED",
        generation_id: "saved-generation",
        design_version_id: UNSELECTED_DESIGN_VERSION.id,
        design_content_hash: UNSELECTED_DESIGN_VERSION.content_hash,
        package: buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, SECOND_DESIGN_ALTERNATIVE_ID),
      };
      const wrapper = mountFlow(api, { locale });
      await flushPromises();
      await card(wrapper, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
      await flushPromises();
      expect(wrapper.get('[data-testid="design-error"]').text()).toBe(
        locale === "it"
          ? "Non è stato possibile registrare la tua scelta: non è cambiato nulla. Riprova tra poco."
          : "Your choice could not be recorded, so nothing changed. Try again in a moment.",
      );
      expect(api.proposeRevision).toHaveBeenCalledTimes(1);
      expect(api.decideRevision).not.toHaveBeenCalled();
      expect(api.submissions).toBe(0);
    },
  );

  it("does not confuse the provider recommendation with owner selection", async () => {
    const api = new FakeDesignApi();
    const wrapper = mountFlow(api);
    await flushPromises();

    const recommended = card(wrapper, "DES-001");
    expect(recommended.get('[data-testid="alternative-recommended"]').text()).toBe(
      "· recommended by the designer",
    );
    expect(recommended.attributes("data-chosen")).toBe("false");
    expect(recommended.find('[data-testid="alternative-chosen"]').exists()).toBe(false);
    expect(recommended.find('[data-testid="alternative-choose"]').exists()).toBe(true);
    expect(card(wrapper, "DES-002").find('[data-testid="alternative-recommended"]').exists()).toBe(
      false,
    );
    expect(BASE_DESIGN_PACKAGE.owner_selected_alternative_id).toBeNull();
  });

  it("guides the owner from an insight brought into the requirements to the new design", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const requirementsApi = new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1));
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([evaluationRun()]);
    vi.mocked(loop.applyInsight).mockImplementation(async () => {
      requirementsApi.current = {
        status: "REQUIREMENTS_APPROVAL_REQUIRED",
        version: REQUIREMENTS_V2,
        gate: null,
        approved_current_specification: false,
      };
      return REQUIREMENTS_APPLICATION;
    });
    vi.mocked(loop.regenerate).mockImplementation(async () => {
      api.readinessResult = { ...api.readinessResult, version: REGENERATED_DESIGN_VERSION };
      return {
        status: "CREATED",
        version: REGENERATED_DESIGN_VERSION,
        issue: null,
        proposal_issue: null,
        persistence_status: "APPENDED",
      };
    });
    const wrapper = mountFlow(api, { locale: "it", loop, requirementsApi });
    await flushPromises();
    expect(wrapper.find('[data-testid="design-evaluation-panel"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="design-discussion-panel"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-regenerate"]').exists()).toBe(true);
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(1);

    await wrapper
      .get('[data-testid="design-evaluation-panel"] [data-testid="insight-apply-requirements"]')
      .trigger("click");
    await flushPromises();
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="design-next-step"]').text()).toContain("REQ-004");
    expect(wrapper.find('[data-testid="design-regenerate"]').exists()).toBe(false);
    expect(
      wrapper.get('[data-testid="design-next-regenerate"]').attributes("disabled"),
    ).toBeDefined();

    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(requirementsApi.submitGate).toHaveBeenCalledTimes(1);
    expect(requirementsApi.decideGate).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[data-testid="design-next-step-1-done"]').exists()).toBe(true);

    await wrapper.get('[data-testid="design-next-regenerate"]').trigger("click");
    await flushPromises();
    expect(loop.regenerate).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-next-step"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-regenerate"]').exists()).toBe(true);
    expect(wrapper.emitted("sections-changed")).toHaveLength(3);
  });

  it("explains a rejected regeneration in plain words instead of showing its code", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const requirementsApi = new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1));
    const loop = fakeLoopApi();
    vi.mocked(loop.regenerate)
      .mockImplementationOnce(async () => {
        requirementsApi.current = {
          status: "REQUIREMENTS_APPROVAL_REQUIRED",
          version: REQUIREMENTS_V2,
          gate: null,
          approved_current_specification: false,
        };
        return rejected("REQUIREMENTS_APPROVAL_REQUIRED");
      })
      .mockResolvedValueOnce(rejected("DESIGN_PACKAGE_NOT_FOUND"));
    const wrapper = mountFlow(api, { locale: "it", loop, requirementsApi });
    await flushPromises();
    await wrapper.get('[data-testid="design-regenerate"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "I requisiti sono cambiati e aspettano la tua approvazione. Riapprovali, poi rigenera le alternative di design.",
    );
    expect(wrapper.text()).not.toContain("REQUIREMENTS_APPROVAL_REQUIRED");
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(2);
    await wrapper.get('[data-testid="design-reapprove-requirements"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    await wrapper.get('[data-testid="design-next-regenerate"]').trigger("click");
    await flushPromises();
    expect(loop.regenerate).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Non c'è ancora un design da rigenerare. Genera prima le alternative di design.",
    );
    expect(wrapper.text()).not.toContain("DESIGN_PACKAGE_NOT_FOUND");
  });

  it("reloads the design after an insight is recorded in the design", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([evaluationRun()]);
    vi.mocked(loop.applyInsight).mockResolvedValue({
      ...REQUIREMENTS_APPLICATION,
      target: "DESIGN",
      target_version_id: SELECTED_DESIGN_VERSION.id,
      target_code: "DRK-002",
    });
    const readiness = vi.spyOn(api, "readiness");
    const wrapper = mountFlow(api, { loop });
    await flushPromises();
    const loads = readiness.mock.calls.length;
    await wrapper
      .get('[data-testid="design-evaluation-panel"] [data-testid="insight-apply-design"]')
      .trigger("click");
    await flushPromises();
    expect(readiness.mock.calls.length).toBe(loads + 1);
  });

  it("shows the design as text first, then as tables and as diagrams on request", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const wrapper = mountFlow(api, {
      locale: "it",
      loop: fakeLoopApi(),
      attach: true,
      stubs: { ProjectDiagramsView: true },
    });
    await flushPromises();

    expect(wrapper.get('[data-testid="design-text-view"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="design-text-view"]').attributes("id")).toBe(
      "design-view-panel",
    );
    expect(wrapper.find('[data-testid="design-table-view"]').exists()).toBe(false);

    await wrapper.get('[data-testid="artifact-view-table"]').trigger("click");

    const table = wrapper.get('[data-testid="design-table-view"]');
    expect(wrapper.get('[data-testid="design-text-view"]').isVisible()).toBe(false);
    expect(table.attributes("id")).toBe("design-view-panel");
    expect(table.attributes("data-surface-context")).toBe("night");
    for (const alternative of SELECTED_DESIGN_VERSION.package.alternatives) {
      expect(table.text()).toContain(alternative.code);
      expect(table.text()).toContain(alternative.title);
    }

    await wrapper.get('[data-testid="artifact-view-diagram"]').trigger("click");

    expect(wrapper.find('[data-testid="design-table-view"]').exists()).toBe(false);
    expect(wrapper.getComponent({ name: "ProjectDiagramsView" }).props()).toMatchObject({
      projectId: DESIGN_PROJECT_ID,
      stage: "design",
      locale: "it",
      refreshKey: SELECTED_DESIGN_VERSION.content_hash,
    });
    expect(wrapper.find('[data-testid="design-evaluation-panel"]').exists()).toBe(true);
  });

  it("asks the twins to review the design as soon as the owner applies it", async () => {
    const api = new FakeDesignApi();
    const loop = reviewingLoopApi();
    const wrapper = mountFlow(api, { loop });
    await flushPromises();
    expect(wrapper.find('[data-testid="design-evaluation-panel"]').exists()).toBe(false);

    await card(wrapper, "DES-001").get('[data-testid="alternative-open"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="design-create-preview"]').trigger("click");
    await flushPromises();
    expect(loop.evaluate).not.toHaveBeenCalled();

    await card(wrapper, "DES-001").get('[data-testid="alternative-choose"]').trigger("click");
    await flushPromises();

    expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props()).toMatchObject({
      designVersionId: SELECTED_DESIGN_VERSION.id,
      designContentHash: SELECTED_DESIGN_VERSION.content_hash,
      autoEvaluateVersionId: SELECTED_DESIGN_VERSION.id,
    });
    expect(vi.mocked(loop.evaluate).mock.calls.map((call) => call[1])).toEqual([
      {
        design_version_id: SELECTED_DESIGN_VERSION.id,
        design_content_hash: SELECTED_DESIGN_VERSION.content_hash,
        mode: "TWIN_REVIEW",
        locale: "en-US",
      },
    ]);
    expect(wrapper.findAll('[data-testid="design-evaluation-run"]')).toHaveLength(1);
  });

  it("reads the design and its next step again once when the requirements before it change", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const readiness = vi.spyOn(api, "readiness");
    const requirementsApi = new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1));
    const wrapper = mountFlow(api, { requirementsApi });
    await flushPromises();
    expect(readiness).toHaveBeenCalledTimes(1);
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ upstream: "requirements-1:APPROVED" });
    await wrapper.setProps({ upstream: null });
    await wrapper.setProps({ upstream: "requirements-1:APPROVED" });
    await flushPromises();
    expect(readiness).toHaveBeenCalledTimes(1);
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(1);

    await wrapper.setProps({ upstream: "requirements-2:APPROVED" });
    await flushPromises();
    expect(readiness).toHaveBeenCalledTimes(2);
    expect(requirementsApi.readiness).toHaveBeenCalledTimes(2);
  });

  it("never asks the twins for a review when an existing design is opened", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const loop = reviewingLoopApi();
    const wrapper = mountFlow(api, { loop });
    await flushPromises();

    expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props("autoEvaluateVersionId")).toBe(
      null,
    );
    expect(loop.evaluate).not.toHaveBeenCalled();
    expect(wrapper.getComponent(DesignAlternativeComparison).props("twins")).toEqual(
      SELECTED_DESIGN_VERSION.package.grounding.user_twin_references,
    );
  });

  it.each([
    ["the endpoint is missing", notFound(null)],
    ["the network fails", new TypeError("Failed to fetch")],
    ["the model is local", { generated_mockups: false, iterations: false, model: null }],
  ])(
    "works as today with the declarative preview when %s, without an error",
    async (_label, failure) => {
      const api = new FakeDesignApi();
      const mockupsApi = fakeMockupsApi({ capabilities: failure });
      const wrapper = mountFlow(api, { mockupsApi });
      await flushPromises();

      expect(mockupsApi.capabilities).toHaveBeenCalledTimes(1);
      expect(mockupsApi.latest).not.toHaveBeenCalled();
      expect(mockupsApi.startJob).not.toHaveBeenCalled();
      expect(mockupsApi.document).not.toHaveBeenCalled();
      expect(wrapper.find('[role="alert"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="alternative-drawing"]').exists()).toBe(false);
      expect(wrapper.findAll('[data-testid="design-alternative"]')).toHaveLength(2);
      expect(card(wrapper, "DES-002").find('[data-testid="design-style-tile"]').exists()).toBe(
        true,
      );
      expect(api.currentMockup.mock.calls.map((call) => call[1])).toEqual([
        DESIGN_ALTERNATIVE_ID,
        SECOND_DESIGN_ALTERNATIVE_ID,
      ]);
      expect(barOf(wrapper).text()).toContain("Choose one of the alternatives");
      expect(
        barOf(wrapper).get('[data-testid="decision-primary"]').attributes("disabled"),
      ).toBeDefined();
      expect(wrapper.find('[data-testid="decision-secondary"]').exists()).toBe(false);
      await expectAccessible(wrapper.element);
    },
  );

  it("asks for each mockup only through the store, once, and never again on a new mount or view", async () => {
    const api = designToPrepare(GENERATED_UNSELECTED);
    const mockupsApi = fakeMockupsApi({ capabilities: GENERATED });
    const pinia = createPinia();
    setActivePinia(pinia);
    const first = mountFlow(api, { mockupsApi, pinia });
    await flushPromises();
    await first.get('[data-testid="generate-design"]').trigger("click");
    await flushPromises();

    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);
    expect(mockupsApi.startJob.mock.calls.map((call) => call[1].alternative_id).sort()).toEqual(
      [DESIGN_ALTERNATIVE_ID, SECOND_DESIGN_ALTERNATIVE_ID].sort(),
    );
    expect(mockupsApi.startJob.mock.calls[0]?.[1]).toMatchObject({
      design_version_id: GENERATED_UNSELECTED.id,
      design_content_hash: GENERATED_UNSELECTED.content_hash,
    });
    expect(first.findAll('[data-testid="alternative-drawing"]')).toHaveLength(2);

    await first.get('[data-testid="artifact-view-table"]').trigger("click");
    await first.get('[data-testid="artifact-view-text"]').trigger("click");
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);

    first.unmount();
    mounted.splice(mounted.indexOf(first), 1);
    const again = mountFlow(api, { mockupsApi, pinia });
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);
    expect(again.findAll('[data-testid="alternative-drawing"]')).toHaveLength(2);
    again.unmount();
    mounted.splice(mounted.indexOf(again), 1);

    const reloaded = createPinia();
    setActivePinia(reloaded);
    vi.mocked(mockupsApi.job).mockImplementation(async (_project, jobId) => ({
      ...job(DESIGN_ALTERNATIVE_ID),
      job_id: jobId,
    }));
    mountFlow(api, { mockupsApi, pinia: reloaded });
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);
  });

  it("waits for the step to be shown before asking for any mockup", async () => {
    const observers: ResizeObserverCallback[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: ResizeObserverCallback) {
          observers.push(callback);
        }
        observe(): void {}
        disconnect(): void {}
      },
    );
    let shown = false;
    Object.defineProperty(Element.prototype, "checkVisibility", {
      configurable: true,
      value(this: Element) {
        return shown;
      },
    });
    try {
      const api = new FakeDesignApi(GENERATED_UNSELECTED);
      const mockupsApi = fakeMockupsApi({ capabilities: GENERATED });
      const wrapper = mountFlow(api, { mockupsApi, attach: true });
      await flushPromises();

      expect(wrapper.findAll('[data-testid="design-alternative"]')).toHaveLength(2);
      expect(mockupsApi.capabilities).not.toHaveBeenCalled();
      expect(mockupsApi.latest).not.toHaveBeenCalled();
      expect(mockupsApi.document).not.toHaveBeenCalled();
      expect(mockupsApi.startJob).not.toHaveBeenCalled();

      shown = true;
      for (const callback of observers) {
        callback([], {} as ResizeObserver);
      }
      await flushPromises();
      expect(mockupsApi.capabilities).toHaveBeenCalledTimes(1);
      expect(mockupsApi.latest).toHaveBeenCalledTimes(2);
      expect(mockupsApi.startJob).not.toHaveBeenCalled();
      expect(wrapper.findAll('[data-testid="alternative-missing"]')).toHaveLength(2);

      shown = false;
      for (const callback of observers) {
        callback([], {} as ResizeObserver);
      }
      shown = true;
      for (const callback of observers) {
        callback([], {} as ResizeObserver);
      }
      await flushPromises();
      expect(mockupsApi.capabilities).toHaveBeenCalledTimes(1);
      expect(mockupsApi.latest).toHaveBeenCalledTimes(2);
      expect(mockupsApi.startJob).not.toHaveBeenCalled();
    } finally {
      Reflect.deleteProperty(Element.prototype, "checkVisibility");
      vi.unstubAllGlobals();
    }
  });

  it("prepares the step as soon as it becomes active, even in a page that is not being drawn", async () => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe(): void {}
        disconnect(): void {}
      },
    );
    Object.defineProperty(Element.prototype, "checkVisibility", {
      configurable: true,
      value(this: Element) {
        return this.closest("[style*='display: none']") === null;
      },
    });
    try {
      const bar = document.createElement("div");
      bar.id = "step-decision-bar";
      const row = document.createElement("div");
      row.id = "step-technical-row";
      document.body.append(bar, row);
      const api = new FakeDesignApi(GENERATED_SELECTED);
      const mockupsApi = fakeMockupsApi({
        capabilities: GENERATED,
        documents: {
          [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
        },
      });
      const requirementsApi = new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V1));
      const loop = fakeLoopApi();
      const usageApi = fakeUsageApi();
      const Page = defineComponent({
        props: { active: { type: Boolean, required: true } },
        setup(page) {
          return () =>
            withDirectives(
              h("div", { "data-testid": "stage-design" }, [
                h(ProjectDesignFlow, {
                  projectId: DESIGN_PROJECT_ID,
                  locale: "en",
                  authorize,
                  api,
                  loopApi: loop,
                  requirementsApi,
                  mockupsApi,
                  usageApi,
                  active: page.active,
                }),
              ]),
              [[vShow, page.active]],
            );
        },
      });
      const page = mount(Page, {
        props: { active: false },
        global: { plugins: [createAppI18n("en")] },
        attachTo: document.body,
      });
      mounted.push(page);
      await flushPromises();

      expect(page.findAll('[data-testid="design-alternative"]')).toHaveLength(2);
      expect(mockupsApi.capabilities).not.toHaveBeenCalled();
      expect(mockupsApi.document).not.toHaveBeenCalled();
      expect(bar.childElementCount).toBe(0);
      expect(row.childElementCount).toBe(0);

      await page.setProps({ active: true });
      await flushPromises();

      expect(mockupsApi.capabilities).toHaveBeenCalledTimes(1);
      expect(mockupsApi.document).toHaveBeenCalledWith(
        DESIGN_PROJECT_ID,
        { alternative_id: DESIGN_ALTERNATIVE_ID, source: "applied" },
        "access-token",
      );
      expect(page.find('[data-testid="alternative-thumbnail"]').exists()).toBe(true);
      expect(bar.querySelector('[data-testid="decision-bar"]')).not.toBeNull();
      expect(row.querySelector('[data-testid="step-technical-details"]')).not.toBeNull();
    } finally {
      Reflect.deleteProperty(Element.prototype, "checkVisibility");
      vi.unstubAllGlobals();
    }
  });

  it("starts nothing when an older design without mockups is opened and offers to draw each mockup", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const mockupsApi = fakeMockupsApi({ capabilities: GENERATED });
    const wrapper = mountFlow(api, { mockupsApi });
    await flushPromises();

    expect(mockupsApi.capabilities).toHaveBeenCalledTimes(1);
    expect(mockupsApi.startJob).not.toHaveBeenCalled();
    for (const code of ["DES-001", "DES-002"]) {
      const missing = card(wrapper, code).get('[data-testid="alternative-missing"]');
      expect(missing.text()).toContain("The mockup of this alternative has not been drawn yet.");
      expect(missing.text()).toContain("Drawing uses the hosted model and has a cost.");
      expect(missing.find('[data-testid="alternative-draw"]').exists()).toBe(true);
    }

    await card(wrapper, "DES-002").get('[data-testid="alternative-draw"]').trigger("click");
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(1);
    expect(mockupsApi.startJob.mock.calls[0]?.[1]).toEqual({
      design_version_id: GENERATED_UNSELECTED.id,
      design_content_hash: GENERATED_UNSELECTED.content_hash,
      alternative_id: SECOND_DESIGN_ALTERNATIVE_ID,
    });
    expect(card(wrapper, "DES-001").find('[data-testid="alternative-missing"]').exists()).toBe(
      true,
    );
  });

  it("draws the mockups of the alternatives prepared in this page, one request for each", async () => {
    const api = designToPrepare(GENERATED_UNSELECTED);
    const mockupsApi = fakeMockupsApi({ capabilities: GENERATED });
    const wrapper = mountFlow(api, { mockupsApi });
    await flushPromises();
    expect(mockupsApi.startJob).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="generate-design"]').trigger("click");
    await flushPromises();

    expect(api.generate).toHaveBeenCalledTimes(1);
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);
    expect(mockupsApi.startJob.mock.calls.map((call) => call[1].alternative_id).sort()).toEqual(
      [DESIGN_ALTERNATIVE_ID, SECOND_DESIGN_ALTERNATIVE_ID].sort(),
    );
    for (const call of mockupsApi.startJob.mock.calls) {
      expect(call[1]).toMatchObject({
        design_version_id: GENERATED_UNSELECTED.id,
        design_content_hash: GENERATED_UNSELECTED.content_hash,
      });
    }
    expect(wrapper.findAll('[data-testid="alternative-drawing"]')).toHaveLength(2);
  });

  it("requires an expert gesture for each mockup and never draws skipped mockups on a mode change", async () => {
    const guidance = useGuidanceStore();
    guidance.mode = "EXPERT";
    const api = designToPrepare(GENERATED_UNSELECTED);
    const mockupsApi = fakeMockupsApi({ capabilities: GENERATED });
    const wrapper = mountFlow(api, { mockupsApi });
    await flushPromises();
    await wrapper.get('[data-testid="generate-design"]').trigger("click");
    await flushPromises();
    expect(api.generate).toHaveBeenCalledTimes(1);
    expect(mockupsApi.startJob).not.toHaveBeenCalled();
    guidance.mode = "GUIDED";
    await flushPromises();
    expect(mockupsApi.startJob).not.toHaveBeenCalled();
    guidance.mode = "EXPERT";
    await flushPromises();
    await wrapper.get('[data-testid="generate-mockup-DES-001"]').trigger("click");
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(1);
    expect(mockupsApi.startJob.mock.calls[0]?.[1].alternative_id).toBe(DESIGN_ALTERNATIVE_ID);
    expect(wrapper.find('[data-testid="generate-mockup-DES-002"]').exists()).toBe(true);
  });

  it("resumes the drawings after a reload in the middle and starts nothing", async () => {
    const api = designToPrepare(GENERATED_UNSELECTED);
    const mockupsApi = fakeMockupsApi({ capabilities: GENERATED });
    const first = mountFlow(api, { mockupsApi });
    await flushPromises();
    await first.get('[data-testid="generate-design"]').trigger("click");
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);
    first.unmount();
    mounted.splice(mounted.indexOf(first), 1);

    setActivePinia(createPinia());
    vi.mocked(mockupsApi.job).mockImplementation(async (_project, jobId) => ({
      ...job(DESIGN_ALTERNATIVE_ID),
      job_id: jobId,
    }));
    const reloaded = mountFlow(api, { mockupsApi });
    await flushPromises();

    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);
    expect(mockupsApi.job.mock.calls.map((call) => call[1]).sort()).toEqual(["job-104", "job-105"]);
    expect(reloaded.findAll('[data-testid="alternative-drawing"]')).toHaveLength(2);
  });

  it.each([
    ["the capabilities say that it cannot run", { ...GENERATED, static_check: false }, false],
    ["the capabilities say that it can run", { ...GENERATED, static_check: true }, true],
    ["the capabilities do not say", GENERATED, true],
  ])(
    "offers the static accessibility check according to the capabilities when %s",
    async (_label, capabilities, offered) => {
      const api = new FakeDesignApi(GENERATED_SELECTED);
      const mockupsApi = fakeMockupsApi({
        capabilities,
        documents: {
          [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
        },
      });
      const wrapper = mountFlow(api, { mockupsApi, loop: fakeLoopApi() });
      await flushPromises();

      expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props("staticCheckAvailable")).toBe(
        offered,
      );
      expect(wrapper.find('[data-testid="design-static-check"]').exists()).toBe(offered);
    },
  );

  it.each([
    [
      "say that it is not paid",
      { ...GENERATED, paid: false },
      "en",
      false,
      "Drawing uses your Claude subscription: it spends no credit.",
    ],
    [
      "say that it is not paid, in Italian",
      { ...GENERATED, paid: false },
      "it",
      false,
      "Il disegno usa il tuo abbonamento di Claude: non spende credito.",
    ],
    [
      "say that it is paid",
      { ...GENERATED, paid: true },
      "en",
      true,
      "Drawing uses the hosted model and has a cost.",
    ],
    ["do not say", GENERATED, "en", true, "Drawing uses the hosted model and has a cost."],
  ] as const)(
    "says under the drawing of a mockup what it spends when the capabilities %s",
    async (_label, capabilities, locale, paid, note) => {
      const api = new FakeDesignApi(GENERATED_UNSELECTED);
      const wrapper = mountFlow(api, { locale, mockupsApi: fakeMockupsApi({ capabilities }) });
      await flushPromises();

      expect(wrapper.getComponent(DesignAlternativeComparison).props("paid")).toBe(paid);
      for (const code of ["DES-001", "DES-002"]) {
        expect(card(wrapper, code).get('[data-testid="alternative-draw-cost"]').text()).toBe(note);
      }
    },
  );

  it("names the screens and the elements of the applied mockup in the texts of the review", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([
      evaluationRun(TWIN_ID, GENERATED_SELECTED, [
        {
          ...finding("UTF-001", "Da SCR-001 non si capisce come arrivare a SCR-002.", TWIN_ID),
          location: "SCR-001 Desk · ELM-014 Guest name",
        },
        {
          ...finding(
            "UTF-002",
            "In ELM-014 manca un esempio: FLOW-001 non lo dice, FLOW-002 non c'entra.",
            TWIN_ID,
          ),
          location: "SCR-002 Booking",
        },
      ]),
    ]);
    const pins: ReviewPinsPayload = {
      design_version_id: GENERATED_SELECTED.id,
      pins: [
        {
          number: 1,
          element_code: "ELM-014",
          screen_code: "SCR-001",
          twin_id: TWIN_ID,
          finding_id: "UTF-001",
          severity: "major",
          label: "Guest name",
        },
      ],
      unanchored: [{ number: 2, screen_code: "SCR-002", twin_id: TWIN_ID, finding_id: "UTF-002" }],
    };
    const pinsApi = {
      pins: vi.fn(async () => pins),
      document: vi.fn(async (_project: string, _run: string, entry: string | null) =>
        mockupDocument(DESIGN_ALTERNATIVE_ID, "review", entry ?? "SCR-001"),
      ),
    } satisfies DesignReviewPinsApi;
    const mockupsApi = fakeMockupsApi({
      capabilities: GENERATED,
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
      },
    });
    const wrapper = mountFlow(api, { loop, mockupsApi, pinsApi, locale: "it", attach: true });
    await flushPromises();

    await wrapper.get('[data-testid="design-observations-toggle"]').trigger("click");
    const list = wrapper.get('[data-testid="design-observation-list"]');
    expect(list.text()).toContain("Da «Desk» non si capisce come arrivare a «Booking».");
    expect(list.text()).toContain("Dove: Desk · Guest name");
    const named =
      "In «Guest name» manca un esempio: «Create a reservation» non lo dice, FLOW-002 non c'entra.";
    expect(list.text()).toContain(named);
    const workflows = {
      [DESIGN_ALTERNATIVE_ID]: [{ code: "FLOW-001", title: "Create a reservation" }],
      [SECOND_DESIGN_ALTERNATIVE_ID]: [
        { code: "FLOW-002", title: "Review and create reservations" },
      ],
    };
    expect(wrapper.getComponent(ProjectDesignDiscussionPanel).props("workflows")).toEqual(
      workflows,
    );
    expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props("workflows")).toEqual(
      workflows,
    );
    const screens = [
      { code: "SCR-001", title: "Desk" },
      { code: "SCR-002", title: "Booking" },
    ];
    const heading = GENERATED_SELECTED.package.prototype!.screens[0]!.elements[0]!;
    expect(wrapper.getComponent(ProjectDesignDiscussionPanel).props("screens")).toEqual(screens);
    expect(wrapper.getComponent(ProjectDesignDiscussionPanel).props("elements")).toMatchObject({
      "ELM-014": "Guest name",
      [heading.code]: heading.content,
    });
    expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props("screens")).toEqual(screens);
    expect(wrapper.getComponent(ProjectDesignEvaluationPanel).props("elements")).toMatchObject({
      "ELM-014": "Guest name",
    });

    await card(wrapper, "DES-001").get('[data-testid="alternative-open"]').trigger("click");
    await flushPromises();
    const observations = [
      ...document.body.querySelectorAll<HTMLElement>("[data-testid='mockup-dialog-observation']"),
    ];
    expect(observations[0]?.textContent).toContain(
      "Da «Desk» non si capisce come arrivare a «Booking».",
    );
    expect(observations[0]?.textContent).toContain("Dove: Desk · Guest name");
    expect(observations[1]?.textContent).toContain(named);
  });

  it("quotes the note of the owner and the rules of a change as blocks, without adding quotation marks", async () => {
    const note = "Dopo «Togliti» chiedi sempre conferma";
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    api.readinessResult = {
      ...api.readinessResult,
      gate: { ...PENDING_DESIGN_GATE, status: "REVISION_REQUESTED" },
    };
    vi.spyOn(api as DesignApi, "gateEvents").mockResolvedValue([
      {
        id: "00000000-0000-4000-8000-000000000195",
        gate_id: PENDING_DESIGN_GATE.id,
        sequence_number: 2,
        kind: "REQUEST_REVISION",
        previous_status: "PENDING_APPROVAL",
        resulting_status: "REVISION_REQUESTED",
        artifact: PENDING_DESIGN_GATE.artifact,
        occurred_at: DESIGN_CREATED_AT,
        actor_user_id: DESIGN_OWNER_ID,
        reason: note,
      },
    ]);
    api.diffsResult = [
      {
        ...PROPOSED_DESIGN_DIFF,
        changes: [
          {
            kind: "ADD",
            artifact_kind: "OWNER_ASSERTION",
            artifact_id: "assertion",
            before: null,
            after: { text: note },
          },
        ],
      },
    ];
    const wrapper = mountFlow(api, { locale: "it" });
    await flushPromises();

    const gateNote = wrapper.get('[data-testid="design-gate-note"]');
    expect(gateNote.get("p").text()).toBe("La tua nota");
    expect(gateNote.get("blockquote").text()).toBe(note);
    const change = wrapper.get('[data-testid="design-change"]');
    expect(change.text()).toContain("Una nuova regola");
    expect(change.get('[data-testid="design-change-quote"]').element.tagName).toBe("BLOCKQUOTE");
    expect(change.get('[data-testid="design-change-quote"]').text()).toBe(note);
    expect(wrapper.text()).not.toContain("««");
  });

  it("shows the thumbnails of the drawn mockups inside a sandboxed frame and chooses one in one press", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const results = {
      [DESIGN_ALTERNATIVE_ID]: mockupResult(DESIGN_ALTERNATIVE_ID),
      [SECOND_DESIGN_ALTERNATIVE_ID]: mockupResult(SECOND_DESIGN_ALTERNATIVE_ID),
    };
    const mockupsApi = fakeMockupsApi({
      capabilities: GENERATED,
      latest: results,
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|latest`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "latest"),
        [`${SECOND_DESIGN_ALTERNATIVE_ID}|latest`]: mockupDocument(
          SECOND_DESIGN_ALTERNATIVE_ID,
          "latest",
        ),
      },
    });
    const wrapper = mountFlow(api, { mockupsApi });
    await flushPromises();

    expect(mockupsApi.startJob).not.toHaveBeenCalled();
    const frames = wrapper.findAllComponents(GeneratedMockupFrame);
    expect(frames).toHaveLength(2);
    expect(frames.every((frame) => frame.props("interactive") === false)).toBe(true);
    for (const frame of wrapper.findAll("iframe")) {
      expect(frame.attributes("sandbox")).toBe("");
    }
    expect(wrapper.find(".latest-marker").exists()).toBe(false);
    expect(card(wrapper, "DES-002").attributes("data-preview")).toBe("document");

    await card(wrapper, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    await flushPromises();
    expect(api.proposals).toEqual([results[SECOND_DESIGN_ALTERNATIVE_ID]!.package]);
    expect(api.decisions).toEqual(["APPROVE"]);
  });

  it("chooses a mockup drawn for an earlier version on top of the current design", async () => {
    const current: DesignPackageVersionPayload = {
      ...GENERATED_SELECTED,
      package: {
        ...GENERATED_SELECTED.package,
        concerns: [
          ...GENERATED_SELECTED.package.concerns,
          {
            id: "00000000-0000-4000-8000-000000000151",
            code: "DRK-002",
            summary: "Guests arrive in groups.",
            mitigation: "Show the group size.",
            requirement_ids: [],
            design_alternative_ids: [],
          },
        ],
      },
    };
    const api = new FakeDesignApi(current);
    const earlier = mockupResult(SECOND_DESIGN_ALTERNATIVE_ID, GENERATED_UNSELECTED);
    const mockupsApi = fakeMockupsApi({
      capabilities: { ...GENERATED, iterations: false },
      latest: { [SECOND_DESIGN_ALTERNATIVE_ID]: earlier },
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
        [`${SECOND_DESIGN_ALTERNATIVE_ID}|latest`]: mockupDocument(
          SECOND_DESIGN_ALTERNATIVE_ID,
          "latest",
        ),
      },
    });
    const wrapper = mountFlow(api, { mockupsApi });
    await flushPromises();

    expect(card(wrapper, "DES-001").get('[data-testid="alternative-chosen"]').text()).toBe(
      "Your choice",
    );
    await card(wrapper, "DES-002").get('[data-testid="alternative-choose"]').trigger("click");
    await flushPromises();
    const proposed = api.proposals[0]!;
    expect(proposed.owner_selected_alternative_id).toBe(SECOND_DESIGN_ALTERNATIVE_ID);
    expect(proposed.generated_mockup).toEqual(earlier.package.generated_mockup);
    expect(proposed.prototype).toEqual(earlier.package.prototype);
    expect(proposed.concerns.map((concern) => concern.code)).toEqual(["DRK-001", "DRK-002"]);
    expect(proposed.owner_assertions).toEqual(["The tone stays kind"]);
  });

  it("treats a mockup drawn for an earlier version as the mockup of the alternative and offers to draw only the missing one", async () => {
    const current: DesignPackageVersionPayload = {
      ...GENERATED_UNSELECTED,
      id: "00000000-0000-4000-8000-000000000185",
      version_number: 2,
      based_on_version_number: 1,
      content_hash: "4".repeat(64),
    };
    const api = new FakeDesignApi(current);
    const earlier = mockupResult(SECOND_DESIGN_ALTERNATIVE_ID, GENERATED_UNSELECTED, {
      package: {
        ...buildSelectedDesignPackage(current.package, SECOND_DESIGN_ALTERNATIVE_ID),
        generated_mockup: generatedMockup(SECOND_DESIGN_ALTERNATIVE_ID),
      },
      warnings: [
        { code: "LIST_TOO_SHORT", screen_code: "SCR-001", detail: "ul has 1 item" },
        { code: "REQUIREMENTS_NOT_COVERED", screen_code: null, detail: "REQ-004, REQ-007" },
      ],
    });
    const mockupsApi = fakeMockupsApi({
      capabilities: { ...GENERATED, iterations: false },
      latest: { [SECOND_DESIGN_ALTERNATIVE_ID]: earlier },
      documents: {
        [`${SECOND_DESIGN_ALTERNATIVE_ID}|latest`]: mockupDocument(
          SECOND_DESIGN_ALTERNATIVE_ID,
          "latest",
        ),
      },
    });
    const wrapper = mountFlow(api, { mockupsApi, locale: "it" });
    await flushPromises();

    expect(earlier.design_version_id).not.toBe(current.id);
    expect(mockupsApi.startJob).not.toHaveBeenCalled();
    const missing = card(wrapper, "DES-001").get('[data-testid="alternative-missing"]');
    await missing.get('[data-testid="alternative-draw"]').trigger("click");
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(1);
    expect(mockupsApi.startJob.mock.calls[0]?.[1]).toEqual({
      design_version_id: current.id,
      design_content_hash: current.content_hash,
      alternative_id: DESIGN_ALTERNATIVE_ID,
    });
    const dashboard = card(wrapper, "DES-002");
    expect(dashboard.attributes("data-preview")).toBe("document");
    expect(dashboard.get('[data-testid="alternative-note"]').text()).toBe(
      "Il mockup non mostra ancora questi requisiti: REQ-004 e REQ-007.",
    );
    expect(dashboard.find('[role="alert"]').exists()).toBe(false);

    await dashboard.get('[data-testid="alternative-choose"]').trigger("click");
    await flushPromises();
    expect(api.proposals).toEqual([earlier.package]);
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(1);
  });

  it("says that the designer is drawing, then explains a discarded answer and draws again only when asked", async () => {
    const api = designToPrepare(GENERATED_UNSELECTED);
    const mockupsApi = fakeMockupsApi({
      capabilities: GENERATED,
      started: (alternativeId) =>
        alternativeId === DESIGN_ALTERNATIVE_ID
          ? job(alternativeId)
          : job(alternativeId, "REJECTED", {
              failure: {
                code: "MOCKUP_QUALITY_REJECTED",
                reasons: [
                  { code: "TABLE_TOO_SHORT", screen_code: "SCR-002", detail: "table has 2 rows" },
                  { code: "WEAK_CONTROL_BORDER", screen_code: null, detail: "input 1.20" },
                ],
              },
            }),
    });
    const wrapper = mountFlow(api, { mockupsApi, locale: "it" });
    await flushPromises();
    await wrapper.get('[data-testid="generate-design"]').trigger("click");
    await flushPromises();

    const drawing = card(wrapper, "DES-001").get('[data-testid="alternative-drawing"]');
    expect(drawing.text()).toContain("Il designer sta disegnando il mockup");
    expect(drawing.text()).toContain("Disegna le schermate.");
    expect(drawing.get('[data-testid="alternative-elapsed"]').text()).toMatch(/^In corso da /);

    const failure = card(wrapper, "DES-002").get('[data-testid="alternative-failure"]');
    expect(failure.text()).toContain("Il mockup va rifatto");
    expect(card(wrapper, "DES-001").find('[data-testid="alternative-open"]').exists()).toBe(false);
    expect(card(wrapper, "DES-002").find('[data-testid="alternative-open"]').exists()).toBe(false);
    expect(failure.text()).toContain(
      "Lo Studio ha scartato la risposta perché non superava i controlli di qualità.",
    );
    expect(failure.findAll("li").map((item) => item.text())).toEqual([
      "Una tabella aveva troppo poche righe per sembrare vera",
      "Il bordo di un campo o di un pulsante si vedeva appena",
    ]);
    expect(failure.text()).not.toMatch(/TABLE_TOO_SHORT|SCR-002|WEAK_CONTROL/);
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);

    await failure.get('[data-testid="alternative-retry"]').trigger("click");
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(3);
    expect(mockupsApi.startJob.mock.calls[2]?.[1].alternative_id).toBe(
      SECOND_DESIGN_ALTERNATIVE_ID,
    );
  });

  it("offers to draw the mockup of the other alternative after a choice, without drawing it by itself", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    const mockupsApi = fakeMockupsApi({
      capabilities: GENERATED,
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
      },
    });
    const wrapper = mountFlow(api, { mockupsApi });
    await flushPromises();

    expect(mockupsApi.startJob).not.toHaveBeenCalled();
    expect(card(wrapper, "DES-001").attributes("data-preview")).toBe("document");
    const missing = card(wrapper, "DES-002").get('[data-testid="alternative-missing"]');
    expect(missing.text()).toContain("The mockup of this alternative has not been drawn yet.");
    expect(missing.text()).toContain("Drawing uses the hosted model and has a cost.");

    await missing.get('[data-testid="alternative-draw"]').trigger("click");
    await flushPromises();
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(1);
    expect(mockupsApi.startJob.mock.calls[0]?.[1].alternative_id).toBe(
      SECOND_DESIGN_ALTERNATIVE_ID,
    );
  });

  it("shows the verdict and the quote of every twin and the same twin image in the matrix and in the list", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const wrapper = mountFlow(api, { locale: "it" });
    await flushPromises();

    const cells = wrapper.findAll('[data-testid="design-twin-matrix-cell"]');
    expect(cells).toHaveLength(2);
    expect(cells[0]?.get('[data-testid="design-twin-matrix-verdict"]').text()).toBe(
      "Useful, with doubts",
    );
    expect(cells[0]?.get('[data-testid="design-twin-matrix-quote"]').text()).toBe(
      "«I see the next arrival, but the flow slows me down at peak times.»",
    );
    expect(cells[0]?.attributes("aria-pressed")).toBe("true");
    await wrapper.get('[data-testid="design-observations-toggle"]').trigger("click");
    const list = () => wrapper.get('[data-testid="design-observation-list"]');
    expect(list().get("h3").text()).toBe("Receptionist Twin su DES-001 · Guided reservation flow");

    const matrixImage = wrapper
      .get('[data-testid="design-twin-matrix-avatar"] img')
      .attributes("src");
    const listImage = list().get('[data-testid="design-observation-avatar"] img').attributes("src");
    expect(matrixImage).toMatch(/^\/twins\/.+\.webp$/);
    expect(listImage).toBe(matrixImage);

    await cells[1]!.trigger("click");
    expect(list().get("h3").text()).toBe(
      "Receptionist Twin su DES-002 · Reservation operations dashboard",
    );
    expect(list().text()).toContain("Dense tiles may hide the next arrival.");
    expect(list().get('[data-testid="design-observation-avatar"] img').attributes("src")).toBe(
      matrixImage,
    );
  });

  it.each([
    [
      "en",
      "Read every observation of Receptionist Twin on DES-001 · Guided reservation flow (6)",
      "6 observations",
    ],
    [
      "it",
      "Leggi tutte le osservazioni di Receptionist Twin su DES-001 · Guided reservation flow (6)",
      "6 osservazioni",
    ],
  ] as const)(
    "keeps the observations of the cell chosen by default closed when the step loads (%s)",
    async (locale, sentence, count) => {
      const api = new FakeDesignApi(GENERATED_UNSELECTED);
      const wrapper = mountFlow(api, { locale });
      await flushPromises();

      const toggle = wrapper.get('[data-testid="design-observations-toggle"]');
      expect(toggle.element.tagName).toBe("BUTTON");
      expect(toggle.attributes("type")).toBe("button");
      expect(toggle.attributes("aria-expanded")).toBe("false");
      expect(toggle.get('[data-testid="design-observations-label"]').text()).toBe(sentence);
      const region = wrapper.get(`[id="${toggle.attributes("aria-controls")}"]`);
      expect(region.attributes("data-testid")).toBe("design-observations-region");
      expect(region.element.children).toHaveLength(0);
      expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="design-critique-list"]').exists()).toBe(false);
      const cells = wrapper.findAll('[data-testid="design-twin-matrix-cell"]');
      expect(cells.map((cell) => cell.attributes("aria-pressed"))).toEqual(["true", "false"]);
      expect(cells[0]?.get('[data-testid="design-twin-matrix-count"]').text()).toBe(count);
    },
  );

  it.each([
    [
      "en",
      "Close the observations",
      "Receptionist Twin on DES-001 · Guided reservation flow",
      "Read every observation of Receptionist Twin on DES-001 · Guided reservation flow (6)",
    ],
    [
      "it",
      "Chiudi le osservazioni",
      "Receptionist Twin su DES-001 · Guided reservation flow",
      "Leggi tutte le osservazioni di Receptionist Twin su DES-001 · Guided reservation flow (6)",
    ],
  ] as const)(
    "opens the observations with their button and closes them again (%s)",
    async (locale, close, heading, sentence) => {
      const api = new FakeDesignApi(GENERATED_UNSELECTED);
      const wrapper = mountFlow(api, { locale });
      await flushPromises();

      const toggle = () => wrapper.get('[data-testid="design-observations-toggle"]');
      const label = () => wrapper.get('[data-testid="design-observations-label"]').text();
      await toggle().trigger("click");
      expect(toggle().attributes("aria-expanded")).toBe("true");
      expect(label()).toBe(close);
      const region = wrapper.get(`[id="${toggle().attributes("aria-controls")}"]`);
      const list = region.get('[data-testid="design-observation-list"]');
      expect(list.get("h3").text()).toBe(heading);
      expect(list.findAll('[data-testid="design-critique-list"]')).toHaveLength(6);
      expect(list.findAll('[data-testid="design-critique-item"]')).toHaveLength(6);

      await toggle().trigger("click");
      expect(toggle().attributes("aria-expanded")).toBe("false");
      expect(label()).toBe(sentence);
      expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);
    },
  );

  it("opens the observations when the person clicks a cell of the matrix and keeps them open on another cell", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const wrapper = mountFlow(api);
    await flushPromises();

    const toggle = () => wrapper.get('[data-testid="design-observations-toggle"]');
    const label = () => wrapper.get('[data-testid="design-observations-label"]').text();
    const list = () => wrapper.get('[data-testid="design-observation-list"]');
    const cell = (alternativeId: string) =>
      wrapper
        .findAll('[data-testid="design-twin-matrix-cell"]')
        .find((item) => item.attributes("data-alternative") === alternativeId)!;

    await cell(SECOND_DESIGN_ALTERNATIVE_ID).trigger("click");
    expect(toggle().attributes("aria-expanded")).toBe("true");
    expect(cell(SECOND_DESIGN_ALTERNATIVE_ID).attributes("aria-pressed")).toBe("true");
    expect(list().get("h3").text()).toBe(
      "Receptionist Twin on DES-002 · Reservation operations dashboard",
    );
    expect(list().text()).toContain("Dense tiles may hide the next arrival.");

    await cell(DESIGN_ALTERNATIVE_ID).trigger("click");
    expect(toggle().attributes("aria-expanded")).toBe("true");
    expect(list().get("h3").text()).toBe("Receptionist Twin on DES-001 · Guided reservation flow");

    await cell(SECOND_DESIGN_ALTERNATIVE_ID).trigger("click");
    await toggle().trigger("click");
    expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);
    expect(label()).toBe(
      "Read every observation of Receptionist Twin on DES-002 · Reservation operations dashboard (6)",
    );

    await cell(SECOND_DESIGN_ALTERNATIVE_ID).trigger("click");
    expect(toggle().attributes("aria-expanded")).toBe("true");
    expect(list().get("h3").text()).toBe(
      "Receptionist Twin on DES-002 · Reservation operations dashboard",
    );
  });

  it("opens the observations again by itself when a decision taken in them fails after the person closed them", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([
      evaluationRun(TWIN_ID, GENERATED_SELECTED, [
        finding("UTF-001", "The guest name lacks a format hint.", TWIN_ID),
      ]),
    ]);
    let refuse: (error: Error) => void = () => undefined;
    loop.validate = vi.fn(
      () =>
        new Promise<never>((_resolve, reject) => {
          refuse = reject;
        }),
    );
    const wrapper = mountFlow(api, { loop, locale: "it" });
    await flushPromises();

    const toggle = () => wrapper.get('[data-testid="design-observations-toggle"]');
    const list = () => wrapper.get('[data-testid="design-observation-list"]');
    expect(wrapper.get('[data-testid="design-observations-label"]').text()).toBe(
      "Leggi tutte le osservazioni di Receptionist Twin su DES-001 · Guided reservation flow (1)",
    );
    await toggle().trigger("click");
    await list().get('[data-testid="design-observation-confirm"]').trigger("click");
    expect(list().get('[data-testid="design-observation-saving"]').text()).toBe(
      "Salvo la tua decisione…",
    );

    await toggle().trigger("click");
    expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);

    refuse(new Error("Design loop API request failed with status 503"));
    await flushPromises();
    expect(toggle().attributes("aria-expanded")).toBe("true");
    const error = list().get('[data-testid="design-observation-error"]');
    expect(error.attributes("role")).toBe("alert");
    expect(error.text()).toBe("Non è stato possibile salvare la tua decisione. Riprova.");
    expect(list().get('[data-testid="design-observation"]').attributes("data-decision")).toBe(
      "NONE",
    );
  });

  it("opens the observations again by itself when bringing one into the project fails after the person closed them", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const loop = fakeLoopApi();
    let refuse: (error: Error) => void = () => undefined;
    vi.mocked(loop.applyInsight).mockImplementation(
      () =>
        new Promise<never>((_resolve, reject) => {
          refuse = reject;
        }),
    );
    const wrapper = mountFlow(api, { loop });
    await flushPromises();

    const toggle = () => wrapper.get('[data-testid="design-observations-toggle"]');
    const list = () => wrapper.get('[data-testid="design-observation-list"]');
    await wrapper.findAll('[data-testid="design-twin-matrix-cell"]')[1]!.trigger("click");
    await list()
      .get('[data-testid="design-critique-bring"] [data-target="REQUIREMENTS"]')
      .trigger("click");
    expect(list().get('[role="status"]').text()).toBe("Bringing it into the project…");

    await toggle().trigger("click");
    expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);

    refuse(new Error("Design loop API request failed with status 503"));
    await flushPromises();
    expect(toggle().attributes("aria-expanded")).toBe("true");
    expect(list().get("h3").text()).toBe(
      "Receptionist Twin on DES-002 · Reservation operations dashboard",
    );
    expect(list().get('[role="alert"]').text()).toBe(
      "The insight could not be brought into the project. Try again.",
    );
  });

  it("starts with the observations closed again when another project is opened", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const wrapper = mountFlow(api);
    await flushPromises();
    await wrapper.get('[data-testid="design-observations-toggle"]').trigger("click");
    expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(true);

    await wrapper.setProps({ projectId: "00000000-0000-4000-8000-000000000199" });
    await flushPromises();

    expect(
      wrapper.get('[data-testid="design-observations-toggle"]').attributes("aria-expanded"),
    ).toBe("false");
    expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);
  });

  it("records the decisions on the findings of the review and brings a concern into the project", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([
      evaluationRun(TWIN_ID, GENERATED_SELECTED, [
        finding("UTF-001", "The guest name lacks a format hint.", TWIN_ID),
      ]),
    ]);
    loop.validate = vi.fn(async (_project, runId, body) => ({
      evaluation_run_id: runId,
      twin_id: body.twin_id,
      finding_id: body.finding_id,
      sequence_number: 1,
      project_id: DESIGN_PROJECT_ID,
      owner_user_id: DESIGN_OWNER_ID,
      decision: body.decision,
      note: body.note,
      decided_at: DESIGN_CREATED_AT,
      content_hash: "f".repeat(64),
    }));
    vi.mocked(loop.applyInsight).mockResolvedValue({
      ...REQUIREMENTS_APPLICATION,
      source_kind: "DESIGN_CRITIQUE",
      source_id: "CRQ-002:0",
    });
    const wrapper = mountFlow(api, { loop, locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="design-observations-toggle"]').trigger("click");
    const list = () => wrapper.get('[data-testid="design-observation-list"]');
    expect(list().text()).toContain("The guest name lacks a format hint.");
    await list().get('[data-testid="design-observation-confirm"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(loop.validate).mock.calls[0]?.slice(1, 3)).toEqual([
      "run-1",
      { twin_id: TWIN_ID, finding_id: "UTF-001", decision: "OWNER_CONFIRMED", note: null },
    ]);
    expect(list().get('[data-testid="design-observation"]').attributes("data-decision")).toBe(
      "OWNER_CONFIRMED",
    );

    await list()
      .get('[data-testid="design-observation-target"][data-target="BRIEF"]')
      .trigger("click");
    expect(useInsightTrayStore().itemsOf(DESIGN_PROJECT_ID)).toEqual([
      {
        sourceKind: "SYNTHETIC_FINDING",
        sourceId: `run:run-1:${TWIN_ID}:UTF-001`,
        sourceTwinId: TWIN_ID,
        text: "The guest name lacks a format hint.",
        briefField: "functional_requirements",
      },
    ]);
    expect(list().get('[data-testid="design-observation-applied"]').text()).toBe(
      "Messa da parte per il brief",
    );

    await wrapper
      .findAll('[data-testid="design-twin-matrix-cell"]')
      .find((cell) => cell.attributes("data-alternative") === SECOND_DESIGN_ALTERNATIVE_ID)!
      .trigger("click");
    await list()
      .get('[data-testid="design-critique-bring"] [data-target="REQUIREMENTS"]')
      .trigger("click");
    await flushPromises();
    expect(vi.mocked(loop.applyInsight).mock.calls[0]?.[1]).toEqual({
      source_kind: "DESIGN_CRITIQUE",
      source_id: "CRQ-002:0",
      source_twin_id: TWIN_ID,
      text: "Dense tiles may hide the next arrival.",
      target: "REQUIREMENTS",
      brief_field: null,
      mitigation: "Pin the next arrival above the tiles.",
    });
  });

  it("opens the reviewed mockup of the chosen design with its numbered pins and observations", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([
      evaluationRun(TWIN_ID, GENERATED_SELECTED, [
        finding("UTF-001", "The guest name lacks a format hint.", TWIN_ID),
        { ...finding("UTF-002", "The totals are hard to find.", TWIN_ID), severity: "critical" },
      ]),
    ]);
    const pins: ReviewPinsPayload = {
      design_version_id: GENERATED_SELECTED.id,
      pins: [
        {
          number: 1,
          element_code: "ELM-014",
          screen_code: "SCR-001",
          twin_id: TWIN_ID,
          finding_id: "UTF-001",
          severity: "major",
          label: "The guest name lacks a format hint.",
        },
      ],
      unanchored: [{ number: 2, screen_code: "SCR-002", twin_id: TWIN_ID, finding_id: "UTF-002" }],
    };
    const pinsApi = {
      pins: vi.fn(async () => pins),
      document: vi.fn(async (_project: string, _run: string, entry: string | null) =>
        mockupDocument(DESIGN_ALTERNATIVE_ID, "review", entry ?? "SCR-001"),
      ),
    } satisfies DesignReviewPinsApi;
    const mockupsApi = fakeMockupsApi({
      capabilities: GENERATED,
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
      },
    });
    const wrapper = mountFlow(api, { loop, mockupsApi, pinsApi, attach: true });
    await flushPromises();

    expect(pinsApi.pins).toHaveBeenCalledWith(DESIGN_PROJECT_ID, "run-1", "access-token");
    expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="design-observations-label"]').text()).toBe(
      "Read every observation of Receptionist Twin on DES-001 · Guided reservation flow (2)",
    );

    await card(wrapper, "DES-001").get('[data-testid="alternative-open"]').trigger("click");
    await flushPromises();
    expect(pinsApi.document).toHaveBeenCalledWith(DESIGN_PROJECT_ID, "run-1", null, "access-token");
    const dialog = document.body.querySelector("[data-testid='mockup-dialog']");
    expect(dialog).not.toBeNull();
    expect(dialog?.querySelector("iframe")?.getAttribute("sandbox")).toBe("");
    const observations = [
      ...document.body.querySelectorAll<HTMLElement>("[data-testid='mockup-dialog-observation']"),
    ];
    expect(observations.map((item) => item.dataset.number)).toEqual(["1", "2"]);
    expect(observations.map((item) => item.dataset.anchored)).toEqual(["true", "false"]);
    expect(observations[1]?.textContent).toContain("The totals are hard to find.");

    document.body.querySelector<HTMLElement>("[data-screen='SCR-002']")?.click();
    await flushPromises();
    expect(pinsApi.document).toHaveBeenLastCalledWith(
      DESIGN_PROJECT_ID,
      "run-1",
      "SCR-002",
      "access-token",
    );
    document.body.querySelector<HTMLElement>("[data-testid='mockup-dialog-close']")?.click();
    await flushPromises();
    expect(document.body.querySelector("[data-testid='mockup-dialog']")).toBeNull();

    await wrapper.get('[data-testid="design-observations-toggle"]').trigger("click");
    expect(
      wrapper.findAll('[data-testid="design-observation-number"]').map((item) => item.text()),
    ).toEqual(["1", "2"]);
  });

  it("asks for changes with a rule that stays valid and shows the designer at work", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    const iterationsApi = fakeIterationsApi(() => job(null));
    const mockupsApi = fakeMockupsApi({
      capabilities: GENERATED,
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
      },
    });
    const wrapper = mountFlow(api, { mockupsApi, iterationsApi, locale: "it" });
    await flushPromises();

    const bar = barOf(wrapper);
    expect(bar.get('[data-testid="decision-primary"]').text()).toBe("Approva il design scelto");
    expect(bar.text()).toContain(
      "Approvi DES-001 · Guided reservation flow. La cartella di conoscenza conterrà questo design e il parere dei twin.",
    );
    await bar.get('[data-testid="decision-secondary"]').trigger("click");
    const note = wrapper.get('[data-testid="decision-note"]');
    expect(note.attributes("placeholder")).toBe(
      "Scrivi che cosa cambiare: il designer disegna una nuova versione e decidi tu se applicarla.",
    );
    expect(barOf(wrapper).text()).toContain(
      "Finché non applichi la nuova versione, il design attuale resta com'è.",
    );
    expect(barOf(wrapper).text()).not.toContain("Il pacchetto conterrà");
    await note.setValue("Metti la ricerca in alto");
    await wrapper.get('[data-testid="design-request-rule-input"]').setValue(true);
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(iterationsApi.startJob.mock.calls[0]?.[1]).toEqual({
      design_version_id: GENERATED_SELECTED.id,
      design_content_hash: GENERATED_SELECTED.content_hash,
      request: "Metti la ricerca in alto",
      assertions: ["Metti la ricerca in alto"],
    });
    expect(wrapper.find('[data-testid="decision-note"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-request-rule"]').exists()).toBe(false);
    const panel = wrapper.get('[data-testid="design-iteration-panel"]');
    expect(panel.attributes("data-phase")).toBe("drawing");
    expect(panel.get('[data-testid="design-iteration-request"]').text()).toBe(
      "Metti la ricerca in alto",
    );
    expect(panel.get('[data-testid="design-iteration-duration"]').text()).toBe(
      "Di solito servono da 5 a 10 minuti. Puoi continuare a lavorare: il disegno prosegue anche se chiudi la pagina.",
    );
    expect(barOf(wrapper).text()).toContain("Il designer sta disegnando la nuova versione");
    expect(
      barOf(wrapper).find('[data-testid="decision-secondary"]').exists(),
      "a second request cannot start while the first one is drawn",
    ).toBe(false);
    expect(barOf(wrapper).get('[data-testid="decision-primary"]').attributes("disabled")).toBe(
      undefined,
    );
  });

  it("shows the new version next to the current one and applies it in one press", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    const iterated: DesignPackageVersionPayload = {
      ...GENERATED_SELECTED,
      id: "00000000-0000-4000-8000-000000000190",
      version_number: 3,
      content_hash: "9".repeat(64),
    };
    api.approvedVersion = iterated;
    const proposal = mockupResult(DESIGN_ALTERNATIVE_ID, GENERATED_SELECTED, {
      generation_id: "generation-iteration",
      changes: ["The search moves to the top"],
      warnings: [{ code: "LIST_TOO_SHORT", screen_code: "SCR-002", detail: "ul has 1 item" }],
      package: {
        ...GENERATED_SELECTED.package,
        generated_mockup: generatedMockup(DESIGN_ALTERNATIVE_ID, "Reservation desk, search first"),
        owner_assertions: ["The tone stays kind", "Search first"],
      },
    });
    const iterationsApi = fakeIterationsApi(() =>
      job(null, "SUCCEEDED", { result: proposal, alternative_id: DESIGN_ALTERNATIVE_ID }),
    );
    const mockupsApi = fakeMockupsApi({
      capabilities: GENERATED,
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
        [`${DESIGN_ALTERNATIVE_ID}|latest`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "latest"),
      },
    });
    const loop = reviewingLoopApi();
    const wrapper = mountFlow(api, { mockupsApi, iterationsApi, loop });
    await flushPromises();

    await barOf(wrapper).get('[data-testid="decision-secondary"]').trigger("click");
    await wrapper.get('[data-testid="decision-note"]').setValue("Search first");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    const panel = wrapper.get('[data-testid="design-iteration-panel"]');
    expect(panel.attributes("data-phase")).toBe("ready");
    expect(panel.get('[data-testid="design-iteration-changes"]').text()).toContain(
      "The search moves to the top",
    );
    const sides = panel.findAll('[data-testid="design-iteration-side"]');
    expect(sides.map((side) => side.find("iframe").attributes("srcdoc"))).toEqual([
      mockupDocument(DESIGN_ALTERNATIVE_ID, "applied").html,
      mockupDocument(DESIGN_ALTERNATIVE_ID, "latest").html,
    ]);
    expect(barOf(wrapper).text()).toContain("A new version is waiting above");
    expect(barOf(wrapper).find('[data-testid="decision-secondary"]').exists()).toBe(false);

    expect(wrapper.emitted("sections-changed")).toBeUndefined();
    await panel.get('[data-testid="design-iteration-apply"]').trigger("click");
    await flushPromises();
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(api.proposals).toEqual([proposal.package]);
    expect(api.decisions).toEqual(["APPROVE"]);
    expect(wrapper.find('[data-testid="design-iteration-ready"]').exists()).toBe(false);
    expect(barOf(wrapper).get('[data-testid="decision-secondary"]').text()).toBe("Ask for changes");
    expect(iterationsApi.list).toHaveBeenCalledTimes(2);
    expect(vi.mocked(loop.evaluate).mock.calls[0]?.[1]).toMatchObject({
      design_version_id: iterated.id,
      mode: "TWIN_REVIEW",
    });
  });

  it("approves the design in one press: it brings it to approval and approves it", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const wrapper = mountFlow(api, { locale: "it" });
    await flushPromises();

    expect(api.submissions).toBe(0);
    expect(api.gateActions).toEqual([]);
    const bar = barOf(wrapper);
    expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeUndefined();
    await bar.get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();

    expect(api.submissions).toBe(1);
    expect(api.gateActions.map((item) => item.action)).toEqual(["APPROVE"]);
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="design-readiness"]').text()).toBe(
      "Design approvato da te. Ora il Dossier.",
    );
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });

  it("says in English that the Dossier follows the approved design", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    api.readinessResult = approvedReadiness(SELECTED_DESIGN_VERSION);
    const wrapper = mountFlow(api);
    await flushPromises();

    expect(wrapper.get('[data-testid="design-readiness"]').text()).toBe(
      "Design approved by you. Next: the Dossier.",
    );
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
  });

  it("approves with the same button when only the approval failed the first time", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    api.decideGate.mockRejectedValueOnce(new Error("Design API request failed with status 503"));
    const wrapper = mountFlow(api);
    await flushPromises();

    await barOf(wrapper).get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(api.submissions).toBe(1);
    expect(wrapper.get('[data-testid="design-error"]').text()).toBe(
      "The design is ready for your approval, but the approval did not go through. Press “Approve the chosen design” again.",
    );

    await barOf(wrapper).get('[data-testid="decision-primary"]').trigger("click");
    await flushPromises();
    expect(api.submissions).toBe(1);
    expect(api.decideGate).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="design-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-readiness"]').exists()).toBe(true);
  });

  it("records a request for changes with its note when the step cannot draw a new version", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const wrapper = mountFlow(api);
    await flushPromises();

    await barOf(wrapper).get('[data-testid="decision-secondary"]').trigger("click");
    const note = wrapper.get('[data-testid="decision-note"]');
    expect(note.attributes("placeholder")).toBe(
      "Write what is wrong: the request is recorded with your note. For a different design, choose the other alternative or regenerate the alternatives.",
    );
    expect(barOf(wrapper).text()).toContain(
      "The current design does not change: your note stays in the history of the design.",
    );
    expect(wrapper.find('[data-testid="design-request-rule"]').exists()).toBe(false);
    await note.setValue("The dashboard is too dense.");
    await wrapper.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(api.submissions).toBe(1);
    expect(api.gateActions).toEqual([
      { action: "REQUEST_REVISION", reason: "The dashboard is too dense." },
    ]);
    expect(wrapper.get('[data-testid="design-gate-closed"]').text()).toContain(
      "You asked for changes",
    );
  });

  it("mounts the decision and the technical row in the page, the bar first", async () => {
    const bar = document.createElement("div");
    bar.id = "step-decision-bar";
    const row = document.createElement("div");
    row.id = "step-technical-row";
    document.body.append(bar, row);
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const wrapper = mountFlow(api, { attach: true });
    await flushPromises();

    expect(bar.querySelector('[data-testid="decision-bar"]')).not.toBeNull();
    expect(row.querySelector('[data-testid="step-technical-details"]')).not.toBeNull();
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="step-technical-details"]').exists()).toBe(false);
  });

  it("keeps the decision and then the technical row at the end of the step when the page has none", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const wrapper = mountFlow(api);
    await flushPromises();

    const flow = wrapper.get('[data-testid="design-flow"]').element;
    const bar = wrapper.get('[data-testid="decision-bar"]').element;
    const details = wrapper.get('[data-testid="step-technical-details"]').element;
    expect(flow.contains(bar)).toBe(true);
    expect(bar.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the cost of the generations only in the technical details", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const usageApi = fakeUsageApi(412000);
    const wrapper = mountFlow(api, {
      usageApi,
      mockupsApi: fakeMockupsApi({
        capabilities: GENERATED,
        latest: { [DESIGN_ALTERNATIVE_ID]: mockupResult(DESIGN_ALTERNATIVE_ID) },
      }),
    });
    await flushPromises();

    expect(usageApi.usage).toHaveBeenCalledWith(DESIGN_PROJECT_ID, "access-token");
    expect(wrapper.text()).not.toContain("$0.412");
    await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
    const details = wrapper.get('[data-testid="step-technical-details-content"]');
    expect(details.text()).toContain("Cost of the generations");
    expect(details.text()).toContain("$0.412");
    expect(details.text()).toContain("claude-opus-5-5");
    expect(details.text()).toContain("generation-104");
    expect(details.text()).toContain("10,234 in · 17,890 out · 3,120 reasoning");
  });

  it.each([
    [
      "en",
      "Cost of the generations",
      "· subscription · generation-usage-2",
      "· $0.412 · generation-usage-1",
      "$0.412",
    ],
    ["it", "Costo delle generazioni", "· abbonamento · generation-usage-2", "0,412", "0,412"],
  ] as const)(
    "shows a generation made on the Claude subscription without an amount and the cost of the paid ones (%s)",
    async (locale, costLabel, subscriptionLine, paidLine, cost) => {
      const api = new FakeDesignApi(GENERATED_UNSELECTED);
      const wrapper = mountFlow(api, {
        locale,
        usageApi: fakeSubscriptionUsageApi(),
        mockupsApi: fakeMockupsApi({ capabilities: GENERATED }),
      });
      await flushPromises();

      await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
      const details = wrapper.get('[data-testid="step-technical-details-content"]');
      const [subscription, paid] = details
        .findAll("li")
        .filter((item) => item.text().includes("generation-usage-"));
      expect(subscription?.text()).toContain(subscriptionLine);
      expect(subscription?.text()).not.toMatch(/\$|USD/);
      expect(paid?.text()).toContain(paidLine);
      const labels = details.findAll("dt").map((item) => item.text());
      expect(labels).toContain(costLabel);
      expect(details.findAll("dd")[labels.indexOf(costLabel)]?.text()).toContain(cost);
    },
  );

  it.each([
    ["en", "Approved · Decision no. 1"],
    ["it", "Approvato · Decisione n. 1"],
  ] as const)(
    "numbers the decision on the design in %s without a limit of attempts",
    async (locale, approval) => {
      const api = new FakeDesignApi(GENERATED_SELECTED);
      api.readinessResult = approvedReadiness(GENERATED_SELECTED);
      const wrapper = mountFlow(api, { locale });
      await flushPromises();

      await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
      const details = wrapper.get('[data-testid="step-technical-details-content"]');
      expect(details.text()).toContain(approval);
      expect(details.text()).not.toMatch(/ of 3| di 3/);
    },
  );

  it("tells only in the technical details what the Studio repaired in a drawn mockup", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const repaired = mockupResult(DESIGN_ALTERNATIVE_ID, GENERATED_UNSELECTED, {
      warnings: [
        { code: "ATTRIBUTE_REMOVED", screen_code: "SCR-001", detail: "input: onclick (2)" },
        { code: "STYLE_DECLARATION_REMOVED", screen_code: null, detail: "color" },
        { code: "ATTRIBUTE_REMOVED", screen_code: "SCR-001", detail: "a: target" },
        { code: "ELEMENT_UNWRAPPED", screen_code: "SCR-009", detail: "center" },
      ],
    });
    const wrapper = mountFlow(api, {
      locale: "it",
      mockupsApi: fakeMockupsApi({
        capabilities: GENERATED,
        latest: { [DESIGN_ALTERNATIVE_ID]: repaired },
      }),
    });
    await flushPromises();

    expect(wrapper.text()).not.toContain("il mockup resta valido");
    await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
    const notes = wrapper.get('[data-testid="design-mockup-notes"]');
    expect(notes.get("h3").text()).toBe("DES-001 · Guided reservation flow");
    expect(notes.findAll("li").map((item) => item.text())).toEqual([
      "Nella schermata «Desk»: Lo Studio ha tolto da un elemento un'impostazione che avrebbe caricato o avviato qualcosa: il mockup resta valido",
      "Lo Studio ha tolto dagli stili un'indicazione che non accetta, come un colore fuori dalla tavolozza: il mockup resta valido",
      "Lo Studio ha tolto un contenitore che non accetta e ne ha tenuto il contenuto: il mockup resta valido",
    ]);
    expect(notes.text()).not.toMatch(/ATTRIBUTE_REMOVED|onclick|SCR-00/);
  });

  it("has no axe violations with drawn thumbnails, the matrix and the bar", async () => {
    const api = new FakeDesignApi(GENERATED_UNSELECTED);
    const wrapper = mountFlow(api, {
      locale: "it",
      mockupsApi: fakeMockupsApi({
        capabilities: GENERATED,
        latest: {
          [DESIGN_ALTERNATIVE_ID]: mockupResult(DESIGN_ALTERNATIVE_ID),
          [SECOND_DESIGN_ALTERNATIVE_ID]: mockupResult(SECOND_DESIGN_ALTERNATIVE_ID),
        },
        documents: {
          [`${DESIGN_ALTERNATIVE_ID}|latest`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "latest"),
          [`${SECOND_DESIGN_ALTERNATIVE_ID}|latest`]: mockupDocument(
            SECOND_DESIGN_ALTERNATIVE_ID,
            "latest",
          ),
        },
      }),
    });
    await flushPromises();
    await expectAccessible(wrapper.element, { iframes: false });
  });

  it.each([
    ["the opinions of the twins", GENERATED_UNSELECTED, []],
    [
      "the findings of the review",
      GENERATED_SELECTED,
      [
        evaluationRun(TWIN_ID, GENERATED_SELECTED, [
          finding("UTF-001", "The guest name lacks a format hint.", TWIN_ID),
          { ...finding("UTF-002", "The totals are hard to find.", TWIN_ID), severity: "critical" },
        ]),
      ],
    ],
  ] as const)(
    "has no axe violations with the observations of %s closed and open",
    async (_label, version, runs) => {
      const api = new FakeDesignApi(version);
      const loop = fakeLoopApi();
      vi.mocked(loop.runs).mockResolvedValue([...runs]);
      const wrapper = mountFlow(api, { loop, locale: "it" });
      await flushPromises();

      expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(false);
      await expectAccessible(wrapper.element);

      await wrapper.get('[data-testid="design-observations-toggle"]').trigger("click");
      expect(wrapper.find('[data-testid="design-observation-list"]').exists()).toBe(true);
      await expectAccessible(wrapper.element);
    },
  );
});

describe("ProjectDesignFlow in sections mode", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setActivePinia(createPinia());
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
  });

  function drawnMockups() {
    return fakeMockupsApi({
      capabilities: GENERATED,
      documents: {
        [`${DESIGN_ALTERNATIVE_ID}|applied`]: mockupDocument(DESIGN_ALTERNATIVE_ID, "applied"),
      },
    });
  }

  it.each([
    [
      "en",
      "You approved this design. You can still ask for changes in words: the new version comes back here for your approval.",
      "Ask for changes",
      "The designer is drawing the new version you asked for: the approved design stays as it is until you apply it.",
    ],
    [
      "it",
      "Hai approvato questo design. Puoi ancora chiedere modifiche a parole: la nuova versione torna qui per la tua approvazione.",
      "Chiedi modifiche",
      "Il designer sta disegnando la nuova versione che hai chiesto: il design approvato resta com'è finché non la applichi.",
    ],
  ] as const)(
    "offers in %s the change in words on an approved design only in sections mode",
    async (locale, sentence, secondary, drawing) => {
      const api = new FakeDesignApi(GENERATED_SELECTED);
      api.readinessResult = approvedReadiness(GENERATED_SELECTED);
      const iterationsApi = fakeIterationsApi(() => job(null));
      const wrapper = mountFlow(api, { mockupsApi: drawnMockups(), iterationsApi, locale });
      await flushPromises();

      expect(wrapper.find('[data-testid="design-readiness"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);

      await wrapper.setProps({ sectionsMode: true });

      const bar = barOf(wrapper);
      expect(bar.text()).toContain(sentence);
      expect(bar.get('[data-testid="decision-primary"]').attributes("disabled")).toBeDefined();
      expect(bar.get('[data-testid="decision-secondary"]').text()).toBe(secondary);
      await expectAccessible(wrapper.element, { iframes: false });

      await bar.get('[data-testid="decision-secondary"]').trigger("click");
      await wrapper.get('[data-testid="decision-note"]').setValue("Metti la ricerca in alto");
      await wrapper.get('[data-testid="decision-send"]').trigger("click");
      await flushPromises();

      expect(iterationsApi.startJob.mock.calls[0]?.[1]).toEqual({
        design_version_id: GENERATED_SELECTED.id,
        design_content_hash: GENERATED_SELECTED.content_hash,
        request: "Metti la ricerca in alto",
        assertions: [],
      });
      expect(api.gateActions).toEqual([]);
      expect(wrapper.get('[data-testid="design-iteration-panel"]').attributes("data-phase")).toBe(
        "drawing",
      );
      expect(barOf(wrapper).text()).toContain(drawing);
    },
  );

  it("keeps the review and the discussion of an approved design available as today", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    api.readinessResult = approvedReadiness(GENERATED_SELECTED);
    const wrapper = mountFlow(api, { mockupsApi: drawnMockups(), sectionsMode: true });
    await flushPromises();

    expect(wrapper.find('[data-testid="design-evaluate"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="design-discussion-panel"]').exists()).toBe(true);
  });

  it.each([
    [
      "en",
      "The design was re-anchored to the new Definition: you can ask the twins for a new evaluation.",
    ],
    [
      "it",
      "Il design è stato riagganciato alla Definizione nuova: puoi chiedere ai twin una nuova valutazione.",
    ],
  ] as const)(
    "says in %s next to the review that a re-anchored design can be evaluated again and starts no review by itself",
    async (locale, sentence) => {
      const api = new FakeDesignApi(REANCHORED_DESIGN_VERSION);
      api.readinessResult = approvedReadiness(REANCHORED_DESIGN_VERSION);
      api.historyResult = [GENERATED_SELECTED, REANCHORED_DESIGN_VERSION];
      const loop = reviewingLoopApi();
      vi.mocked(loop.runs).mockResolvedValue([evaluationRun(TWIN_ID, GENERATED_SELECTED)]);
      const wrapper = mountFlow(api, {
        loop,
        locale,
        sectionsMode: true,
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V2)),
        alignmentApi: fakeAlignmentApi(
          alignment({
            aligned: true,
            issue: "ALREADY_ALIGNED",
            grounded_requirements_version_number: 2,
          }),
        ),
      });
      await flushPromises();

      const notice = wrapper.get('[data-testid="design-reanchored-review"]');
      expect(notice.text()).toBe(sentence);
      const panel = wrapper.getComponent(ProjectDesignEvaluationPanel);
      expect(notice.element.nextElementSibling).toBe(panel.element);
      expect(panel.props("autoEvaluateVersionId")).toBeNull();
      expect(loop.evaluate).not.toHaveBeenCalled();
      await expectAccessible(wrapper.element);

      await panel.get('[data-testid="design-evaluate"]').trigger("click");
      await flushPromises();

      expect(loop.evaluate).toHaveBeenCalledTimes(1);
      expect(vi.mocked(loop.evaluate).mock.calls[0]?.[1]).toMatchObject({
        design_version_id: REANCHORED_DESIGN_VERSION.id,
        mode: "TWIN_REVIEW",
      });
    },
  );

  it("says nothing about a re-anchoring for a version that only changed the design", async () => {
    const iterated: DesignPackageVersionPayload = {
      ...GENERATED_SELECTED,
      id: "00000000-0000-4000-8000-0000000001a1",
      version_number: 3,
      based_on_version_number: 2,
      content_hash: "b".repeat(64),
    };
    const api = new FakeDesignApi(iterated);
    api.historyResult = [GENERATED_SELECTED, iterated];
    const loop = reviewingLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([evaluationRun(TWIN_ID, GENERATED_SELECTED)]);
    const wrapper = mountFlow(api, { loop, sectionsMode: true });
    await flushPromises();

    expect(wrapper.find('[data-testid="design-reanchored-review"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-evaluation-panel"]').exists()).toBe(true);
    expect(loop.evaluate).not.toHaveBeenCalled();
  });

  it("says nothing about a re-anchoring once the re-anchored design has its own review", async () => {
    const api = new FakeDesignApi(REANCHORED_DESIGN_VERSION);
    api.readinessResult = approvedReadiness(REANCHORED_DESIGN_VERSION);
    api.historyResult = [GENERATED_SELECTED, REANCHORED_DESIGN_VERSION];
    const loop = fakeLoopApi();
    vi.mocked(loop.runs).mockResolvedValue([
      evaluationRun(TWIN_ID, GENERATED_SELECTED),
      { ...evaluationRun(TWIN_ID, REANCHORED_DESIGN_VERSION), id: "run-2" },
    ]);
    const wrapper = mountFlow(api, { loop, sectionsMode: true });
    await flushPromises();

    expect(wrapper.find('[data-testid="design-reanchored-review"]').exists()).toBe(false);
  });

  it.each([
    [
      "it",
      "Il design è agganciato alla Definizione v1; ora c'è la v2. Le alternative restano: usa «Aggiorna e conferma» qui sopra per riagganciarlo.",
    ],
    [
      "en",
      "The design is anchored to Definition v1; now there is v2. The alternatives stay: use «Update and confirm» above to re-anchor it.",
    ],
  ] as const)(
    "tells in %s to re-anchor an approved design above instead of regenerating it",
    async (locale, sentence) => {
      const api = new FakeDesignApi(GENERATED_SELECTED);
      api.readinessResult = approvedReadiness(GENERATED_SELECTED);
      const alignmentApi = fakeAlignmentApi(alignment());
      const wrapper = mountFlow(api, {
        locale,
        sectionsMode: true,
        requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V2)),
        alignmentApi,
      });
      await flushPromises();

      expect(alignmentApi.status).toHaveBeenCalledWith(DESIGN_PROJECT_ID, "access-token");
      expect(wrapper.get('[data-testid="design-next-step-reanchor"]').text()).toContain(sentence);
      expect(wrapper.find('[data-testid="design-regenerate"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="design-next-regenerate"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    },
  );

  it("keeps the regeneration as the way out when the design cites a requirement that is gone", async () => {
    const api = new FakeDesignApi(GENERATED_SELECTED);
    api.readinessResult = approvedReadiness(GENERATED_SELECTED);
    const loop = fakeLoopApi();
    vi.mocked(loop.regenerate).mockImplementation(async () => {
      api.readinessResult = { ...api.readinessResult, version: REGENERATED_DESIGN_VERSION };
      return {
        status: "CREATED",
        version: REGENERATED_DESIGN_VERSION,
        issue: null,
        proposal_issue: null,
        persistence_status: "APPENDED",
      };
    });
    const wrapper = mountFlow(api, {
      loop,
      sectionsMode: true,
      requirementsApi: new FakeRequirementsGate(readyRequirements(REQUIREMENTS_V2)),
      alignmentApi: fakeAlignmentApi(
        alignment({ issue: "REQUIREMENT_NO_LONGER_AVAILABLE", missing_codes: ["REQ-003"] }),
      ),
    });
    await flushPromises();

    expect(wrapper.get('[data-testid="design-next-step"]').text()).toContain(
      "Design & Evaluation cannot be updated by itself: the design cites REQ-003, which the Definition no longer contains: regenerate the alternatives in the Design & Evaluation step.",
    );
    await wrapper.get('[data-testid="design-next-regenerate"]').trigger("click");
    await flushPromises();
    expect(loop.regenerate).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });
});

describe("designChangeSentence", () => {
  function change(
    artifactKind: DesignChangePayload["artifact_kind"],
    kind: DesignChangePayload["kind"],
    artifactId: string,
    before: Record<string, unknown> | null = null,
    after: Record<string, unknown> | null = null,
  ): DesignChangePayload {
    return { kind, artifact_kind: artifactKind, artifact_id: artifactId, before, after };
  }

  const packages = [GENERATED_SELECTED.package];

  it("says every change of a revision in plain words, in Italian and in English", () => {
    const cases: [DesignChangePayload, string, string][] = [
      [
        change("GENERATED_MOCKUP", "ADD", DESIGN_ALTERNATIVE_ID),
        "The mockup drawn by the model for DES-001 · Guided reservation flow enters the design",
        "Entra nel design il mockup disegnato dal modello per DES-001 · Guided reservation flow",
      ],
      [
        change(
          "GENERATED_SCREEN",
          "REPLACE",
          "screen",
          { code: "SCR-002", title: "Booking" },
          {
            code: "SCR-002",
            title: "Booking",
          },
        ),
        "The screen “Booking” changes",
        "Cambia la schermata «Booking»",
      ],
      [
        change("GENERATED_SCREEN", "ADD", "screen", null, { code: "SCR-003", title: "Done" }),
        "A new screen: “Done”",
        "Una nuova schermata: «Done»",
      ],
      [
        change(
          "GENERATED_STYLES",
          "REPLACE",
          DESIGN_PROJECT_ID,
          { styles_hash: "a" },
          {
            styles_hash: "b",
          },
        ),
        "The colours and styles of the mockup change",
        "Cambiano colori e stili del mockup",
      ],
      [
        change("OWNER_ASSERTION", "ADD", "assertion", null, { text: "Search first" }),
        "A new rule",
        "Una nuova regola",
      ],
      [
        change("OWNER_ASSERTION", "REPLACE", "assertion", { text: "No red" }, { text: "No bold" }),
        "A rule changes",
        "Cambia una regola",
      ],
      [
        change("OWNER_ASSERTION", "REMOVE", "assertion", { text: "No red" }, null),
        "A rule is removed",
        "Viene tolta una regola",
      ],
      [
        change("OWNER_ASSERTION_ORDER", "REPLACE", DESIGN_PROJECT_ID, { items: [] }, { items: [] }),
        "The order of the rules changes",
        "Cambia l'ordine delle regole",
      ],
      [
        change("CRITIQUE_VERDICT", "REPLACE", CRITIQUES_WITH_VERDICTS[1]!.id),
        "The verdict of Receptionist Twin on DES-002 · Reservation operations dashboard changes",
        "Cambia il giudizio di Receptionist Twin su DES-002 · Reservation operations dashboard",
      ],
      [
        change("SELECTION", "REPLACE", DESIGN_PROJECT_ID, null, {
          owner_selected_alternative_id: SECOND_DESIGN_ALTERNATIVE_ID,
        }),
        "You choose DES-002 · Reservation operations dashboard",
        "Scegli DES-002 · Reservation operations dashboard",
      ],
      [
        change(
          "SELECTION",
          "REPLACE",
          DESIGN_PROJECT_ID,
          {
            recommended_alternative_id: DESIGN_ALTERNATIVE_ID,
            owner_selected_alternative_id: DESIGN_ALTERNATIVE_ID,
          },
          {
            recommended_alternative_id: SECOND_DESIGN_ALTERNATIVE_ID,
            owner_selected_alternative_id: DESIGN_ALTERNATIVE_ID,
          },
        ),
        "The designer now recommends DES-002 · Reservation operations dashboard",
        "Il designer ora consiglia DES-002 · Reservation operations dashboard",
      ],
      [
        change(
          "SELECTION",
          "REPLACE",
          DESIGN_PROJECT_ID,
          { owner_selected_alternative_id: DESIGN_ALTERNATIVE_ID },
          { owner_selected_alternative_id: null },
        ),
        "No alternative stays chosen",
        "Nessuna alternativa resta scelta",
      ],
      [
        change("CONCERN", "ADD", GENERATED_SELECTED.package.concerns[0]!.id),
        "A new point of attention: Experienced users may find the guided flow slower.",
        "Un nuovo punto di attenzione: Experienced users may find the guided flow slower.",
      ],
      [
        change("PROTOTYPE", "REPLACE", "prototype"),
        "The mockup of the chosen design changes",
        "Cambia il mockup del design scelto",
      ],
    ];
    for (const [value, english, italian] of cases) {
      expect(designChangeSentence(value, packages, "en")).toBe(english);
      expect(designChangeSentence(value, packages, "it")).toBe(italian);
    }
  });

  it("gives the text of a rule of the owner apart, to be shown as a quotation", () => {
    expect(
      designChangeQuote(
        change("OWNER_ASSERTION", "ADD", "assertion", null, {
          text: "Dopo «Togliti» chiedi sempre conferma",
        }),
      ),
    ).toBe("Dopo «Togliti» chiedi sempre conferma");
    expect(
      designChangeQuote(change("OWNER_ASSERTION", "REMOVE", "assertion", { text: "No red" }, null)),
    ).toBe("No red");
    expect(designChangeQuote(change("OWNER_ASSERTION", "ADD", "assertion"))).toBeNull();
    expect(
      designChangeQuote(change("GENERATED_SCREEN", "ADD", "screen", null, { text: "Done" })),
    ).toBeNull();
  });

  it("keeps plain words when a name cannot be found and for a kind it does not know", () => {
    expect(designChangeSentence(change("GENERATED_MOCKUP", "REMOVE", "gone"), [], "it")).toBe(
      "Esce dal design il mockup disegnato per un'alternativa",
    );
    const unknown = { ...change("PROTOTYPE", "ADD", "x"), artifact_kind: "SOMETHING_NEW" };
    expect(designChangeSentence(unknown as unknown as DesignChangePayload, [], "en")).toBe(
      "Another change to the design",
    );
  });
});

describe("ProjectDesignFlow and a long generation", () => {
  function requestJob(
    operation: GenerationRequestJob["operation"],
    overrides: Partial<GenerationRequestJob> = {},
  ): GenerationRequestJob {
    return {
      job_id: "00000000-0000-4000-8000-0000000009aa",
      kind: "REQUEST",
      operation,
      status: "RUNNING",
      stage: "GENERATING",
      attempt: 1,
      started_at: STARTED_AT,
      finished_at: null,
      alternative_id: null,
      failure: null,
      response: null,
      ...overrides,
    };
  }

  function emptyDesign(): FakeDesignApi {
    const api = new FakeDesignApi();
    api.readinessResult = {
      status: "DESIGN_REQUIRED",
      version: null,
      gate: null,
      has_package: false,
      package_ready_for_gate: false,
      approved_current_package: false,
    };
    api.historyResult = [];
    return api;
  }

  function settle() {
    return vi.advanceTimersByTimeAsync(50);
  }

  beforeEach(() => {
    window.sessionStorage.clear();
    setActivePinia(createPinia());
    clearFollowedGenerations();
    vi.useFakeTimers();
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it("waits for alternatives still being generated after a reload and shows them when ready", async () => {
    const api = emptyDesign();
    const running = requestJob("DESIGN_PROPOSAL");
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([running]);
    const reads = vi
      .spyOn(generationJobsApi, "job")
      .mockResolvedValueOnce(running)
      .mockImplementationOnce(async () => {
        api.readinessResult = {
          ...api.readinessResult,
          status: "DESIGN_REVIEW_REQUIRED",
          version: UNSELECTED_DESIGN_VERSION,
          has_package: true,
        };
        api.historyResult = [UNSELECTED_DESIGN_VERSION];
        return requestJob("DESIGN_PROPOSAL", {
          status: "SUCCEEDED",
          stage: null,
          finished_at: STARTED_AT,
          response: { status_code: 201, body: { status: "CREATED" } },
        });
      });
    const generate = vi.spyOn(api, "generate");
    const wrapper = mountFlow(api);
    await settle();

    const notice = wrapper.get('[data-testid="generation-job-notice"]');
    expect(notice.attributes("data-operation")).toBe("DESIGN_PROPOSAL");
    expect(notice.text()).toContain("The Studio is generating the design alternatives.");
    expect(notice.text()).toContain("You can leave this page and come back later");
    const button = wrapper.get('[data-testid="generate-design"]');
    expect(button.attributes("disabled")).toBeDefined();
    await button.trigger("click");
    expect(generate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(4000);

    expect(reads).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[data-testid="generation-job-notice"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="design-empty"]').exists()).toBe(false);
    expect(generate).not.toHaveBeenCalled();
  });

  it("draws the mockups of alternatives whose generation finished while the page was open", async () => {
    const api = emptyDesign();
    const running = requestJob("DESIGN_PROPOSAL");
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([running]);
    vi.spyOn(generationJobsApi, "job")
      .mockResolvedValueOnce(running)
      .mockImplementationOnce(async () => {
        api.readinessResult = {
          ...api.readinessResult,
          status: "DESIGN_REVIEW_REQUIRED",
          version: GENERATED_UNSELECTED,
          has_package: true,
        };
        api.historyResult = [GENERATED_UNSELECTED];
        return requestJob("DESIGN_PROPOSAL", {
          status: "SUCCEEDED",
          stage: null,
          finished_at: STARTED_AT,
          response: { status_code: 201, body: { status: "CREATED" } },
        });
      });
    const mockupsApi = fakeMockupsApi({ capabilities: GENERATED });
    const wrapper = mountFlow(api, { mockupsApi });
    await settle();
    expect(mockupsApi.startJob).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(4000);

    expect(wrapper.find('[data-testid="design-empty"]').exists()).toBe(false);
    expect(mockupsApi.startJob).toHaveBeenCalledTimes(2);
    expect(mockupsApi.startJob.mock.calls.map((call) => call[1].alternative_id).sort()).toEqual(
      [DESIGN_ALTERNATIVE_ID, SECOND_DESIGN_ALTERNATIVE_ID].sort(),
    );
  });

  it("waits for a regeneration that is still running instead of offering another one", async () => {
    const api = new FakeDesignApi(SELECTED_DESIGN_VERSION);
    const running = requestJob("DESIGN_REGENERATION");
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([running]);
    vi.spyOn(generationJobsApi, "job").mockResolvedValue(running);
    const loop = fakeLoopApi();
    const wrapper = mountFlow(api, { loop, locale: "it" });
    await settle();

    const notice = wrapper.get('[data-testid="generation-job-notice"]');
    expect(notice.attributes("data-operation")).toBe("DESIGN_REGENERATION");
    expect(notice.text()).toContain("Lo Studio sta generando le nuove alternative di design.");
    const regenerate = wrapper.get('[data-testid="design-regenerate"]');
    expect(regenerate.attributes("disabled")).toBeDefined();
    await regenerate.trigger("click");
    expect(loop.regenerate).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="design-regenerating"]').exists()).toBe(false);
  });

  it("says in plain words that its own generation stopped and reloads the design", async () => {
    const api = emptyDesign();
    const posts: string[] = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(String(input));
        return new Response(JSON.stringify(requestJob("DESIGN_PROPOSAL")), { status: 202 });
      }
      return new Response(JSON.stringify({ detail: { code: "GENERATION_JOB_NOT_FOUND" } }), {
        status: 404,
      });
    });
    const real = createDesignApi({ fetchImpl });
    vi.spyOn(api, "generate").mockImplementation(((projectId: string, token: string) =>
      real.generate(projectId, token)) as unknown as FakeDesignApi["generate"]);
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([]);
    const readiness = vi.spyOn(api, "readiness");
    const wrapper = mountFlow(api);
    await settle();
    const loads = readiness.mock.calls.length;

    await wrapper.get('[data-testid="generate-design"]').trigger("click");
    await settle();
    expect(wrapper.get('[data-testid="generation-job-notice"]').attributes("data-operation")).toBe(
      "DESIGN_PROPOSAL",
    );

    await vi.advanceTimersByTimeAsync(2000);

    const failure = wrapper.get('[data-testid="generation-job-failure"]');
    expect(failure.attributes("data-lost")).toBe("true");
    expect(failure.text()).toContain("The generation of the design alternatives stopped");
    expect(failure.text()).toContain("you can start it again whenever you want");
    expect(wrapper.find('[data-testid="design-error"]').exists()).toBe(false);
    expect(readiness.mock.calls.length).toBeGreaterThan(loads);
    expect(posts).toEqual([`/api/v1/projects/${DESIGN_PROJECT_ID}/design/proposals`]);

    await wrapper.get('[data-testid="generation-job-dismiss"]').trigger("click");
    expect(wrapper.find('[data-testid="generation-job-failure"]').exists()).toBe(false);
  });
});

describe("ProjectDesignFlow and a refused first proposal", () => {
  const NO_DESIGNER = { code: "PROPOSAL_REJECTED", proposal_issue: "UX_DESIGNER_REQUIRED" };
  const NO_REASON = { code: "PROPOSAL_REJECTED" };
  const DESIGNER_MISSING = {
    en: "The User experience (UX) perspective is missing: open Perspectives and prepare them again.",
    it: "Manca la prospettiva Esperienza d'uso (UX): apri Prospettive e preparale di nuovo.",
  };
  const NOT_PREPARED = {
    en: "The model could not prepare this proposal from the approved steps. Your project is unchanged. You can try again.",
    it: "Il modello non è riuscito a preparare questa proposta a partire dai passi approvati. Il progetto è invariato. Puoi riprovare.",
  };

  function proposalJob(detail: Record<string, string> | null): GenerationRequestJob {
    return {
      job_id: "00000000-0000-4000-8000-0000000009ab",
      kind: "REQUEST",
      operation: "DESIGN_PROPOSAL",
      status: detail === null ? "RUNNING" : "FAILED",
      stage: detail === null ? "GENERATING" : null,
      attempt: 1,
      started_at: STARTED_AT,
      finished_at: detail === null ? null : STARTED_AT,
      alternative_id: null,
      failure: null,
      response: detail === null ? null : { status_code: 409, body: { detail } },
    };
  }

  function refusing(detail: Record<string, string>, background: boolean) {
    return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      if (!background) {
        return new Response(JSON.stringify({ detail }), { status: 409 });
      }
      const posted = init?.method === "POST";
      return new Response(JSON.stringify(proposalJob(posted ? null : detail)), {
        status: posted ? 202 : 200,
      });
    });
  }

  function refusedDesign(fetchImpl: typeof fetch): FakeDesignApi {
    const api = designToPrepare(UNSELECTED_DESIGN_VERSION);
    const real = createDesignApi({ fetchImpl });
    vi.spyOn(api, "generate").mockImplementation(((projectId: string, token: string) =>
      real.generate(projectId, token)) as unknown as FakeDesignApi["generate"]);
    return api;
  }

  async function generateRefused(
    detail: Record<string, string>,
    background: boolean,
    locale: "en" | "it",
  ) {
    const fetchImpl = refusing(detail, background);
    const wrapper = mountFlow(refusedDesign(fetchImpl), { locale });
    await vi.advanceTimersByTimeAsync(50);

    await wrapper.get('[data-testid="generate-design"]').trigger("click");
    await vi.advanceTimersByTimeAsync(2050);

    expect(fetchImpl.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(wrapper.find('[data-testid="design-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="generation-job-notice"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("PROPOSAL_REJECTED");
    return wrapper;
  }

  beforeEach(() => {
    window.sessionStorage.clear();
    setActivePinia(createPinia());
    clearFollowedGenerations();
    vi.useFakeTimers();
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([]);
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
    vi.useRealTimers();
    clearFollowedGenerations();
  });

  it.each([
    { how: "at once", background: false, locale: "en" },
    { how: "at once", background: false, locale: "it" },
    { how: "through a job", background: true, locale: "en" },
    { how: "through a job", background: true, locale: "it" },
  ] as const)(
    "says that the UX perspective is missing when the proposal is refused $how ($locale)",
    async ({ background, locale }) => {
      const wrapper = await generateRefused(NO_DESIGNER, background, locale);

      expect(wrapper.get('[data-testid="design-error"]').text()).toBe(DESIGNER_MISSING[locale]);
      expect(wrapper.text()).not.toContain("UX_DESIGNER_REQUIRED");
    },
  );

  it.each([
    { how: "at once", background: false, locale: "en" },
    { how: "through a job", background: true, locale: "it" },
  ] as const)(
    "says that the proposal could not be prepared when it is refused $how without a reason",
    async ({ background, locale }) => {
      const wrapper = await generateRefused(NO_REASON, background, locale);

      expect(wrapper.get('[data-testid="design-error"]').text()).toBe(NOT_PREPARED[locale]);
    },
  );

  it("says why a proposal still running before a reload was refused", async () => {
    const api = designToPrepare(UNSELECTED_DESIGN_VERSION);
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([proposalJob(null)]);
    vi.spyOn(generationJobsApi, "job").mockResolvedValue(proposalJob(NO_DESIGNER));
    const wrapper = mountFlow(api, { locale: "it" });
    await vi.advanceTimersByTimeAsync(2050);

    const failure = wrapper.get('[data-testid="generation-job-failure"]');
    expect(failure.text()).toContain("La generazione delle alternative di design non è riuscita.");
    expect(failure.text()).toContain(DESIGNER_MISSING.it);
    expect(wrapper.text()).not.toContain("UX_DESIGNER_REQUIRED");
    expect(wrapper.text()).not.toContain("PROPOSAL_REJECTED");
    expect(wrapper.find('[data-testid="design-error"]').exists()).toBe(false);
    expect(api.generate).not.toHaveBeenCalled();
  });
});

describe("readablePlace", () => {
  it("names the place of an observation without the codes of screens and elements", () => {
    expect(readablePlace("SCR-001 Selezione Libro per Azione · ELM-004 Libro")).toBe(
      "Selezione Libro per Azione · Libro",
    );
    expect(readablePlace("SCR-002 Conferma Operazione")).toBe("Conferma Operazione");
    expect(readablePlace("SCR-003")).toBe("");
    expect(readablePlace("Il campo di ricerca in alto")).toBe("Il campo di ricerca in alto");
    expect(readablePlace("")).toBe("");
  });
});
