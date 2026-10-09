import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { DesignApiError, type DesignApi, type DesignDistanceApi } from "../api/design";
import { DesignAlignmentApiError, type DesignAlignmentApi } from "../api/designAlignment";
import type { DesignCritiqueApi } from "../api/designCritique";
import type { DesignIterationsApi } from "../api/designIterations";
import type { DesignLoopApi } from "../api/designLoop";
import { DesignMockupsApiError, type DesignMockupsApi } from "../api/designMockups";
import type { GuidanceMode, UserResponse } from "../api/contracts";
import type { ModelUsageApi } from "../api/modelUsage";
import type { RequirementsApi } from "../api/requirements";
import { useAuthStore } from "../stores/auth";
import { expectAccessible } from "../test/axe";
import {
  DESIGN_ALTERNATIVE_ID,
  DESIGN_CREATED_AT,
  DESIGN_OWNER_ID,
  DESIGN_PROJECT_ID,
  SELECTED_DESIGN_PACKAGE,
  SELECTED_DESIGN_VERSION,
  UNSELECTED_DESIGN_VERSION,
} from "../test/designFixtures";
import type { DesignPackageVersionPayload, DesignReadinessPayload } from "../types/design";
import type {
  DesignCritiqueResultPayload,
  DesignCritiqueRunPayload,
  DesignCritiqueSourcePayload,
} from "../types/designCritique";
import type { GenerationJobPayload } from "../types/designMockups";
import type {
  RequirementsReadinessPayload,
  RequirementsSpecificationPayload,
} from "../types/requirements";
import ProjectDesignFlow from "./ProjectDesignFlow.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");
const SOURCE_ID = "00000000-0000-4000-8000-000000004401";
const TWIN_ID = SELECTED_DESIGN_PACKAGE.grounding.user_twin_references[0]!.twin_id;

const DRAWN_VERSION: DesignPackageVersionPayload = {
  ...SELECTED_DESIGN_VERSION,
  package: {
    ...SELECTED_DESIGN_PACKAGE,
    generated_mockup: {
      mockup: {
        contract_version: 1,
        design_alternative_id: DESIGN_ALTERNATIVE_ID,
        title: "Reservation desk",
        styles: ".desk{display:grid}",
        screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT", markup: "<h1>Desk</h1>" }],
      },
      requirement_ids_by_code: {},
    },
  },
};

const SOURCE: DesignCritiqueSourcePayload = {
  id: SOURCE_ID,
  project_id: DESIGN_PROJECT_ID,
  kind: "IMAGE",
  title: "Front desk of a hotel",
  url: null,
  page: null,
  shots: [
    {
      code: "SCR-001",
      media_type: "image/png",
      byte_size: 8,
      sha256: "a".repeat(64),
      width: 1440,
      height: 900,
      viewport_width: null,
    },
  ],
  created_at: DESIGN_CREATED_AT,
  content_hash: "b".repeat(64),
};

const RUN: DesignCritiqueRunPayload = {
  id: "00000000-0000-4000-8000-000000004402",
  project_id: DESIGN_PROJECT_ID,
  source: SOURCE,
  twins: [{ twin_id: TWIN_ID, version_number: 1, name: "Receptionist Twin" }],
  responses: [
    {
      twin_id: TWIN_ID,
      twin_version: 1,
      summary: "I see the arrivals at once.",
      evidence_gaps: [],
      findings: [],
    },
  ],
  verdicts: [{ twin_id: TWIN_ID, anchor_key: "SCR-001", verdict: "WORKS" }],
  started_at: DESIGN_CREATED_AT,
  completed_at: DESIGN_CREATED_AT,
  duration_seconds: 120,
  cost_microusd: 0,
  content_hash: "c".repeat(64),
};

const REDRAW_REQUESTS = {
  en: "Redraw the mockup so that it reproduces the look and the structure of the supplied design “Front desk of a hotel”: same layout, colours and hierarchy of the content, with the screens and the requirements of the project.",
  it: "Ridisegna il mockup perché riproduca l'aspetto e la struttura del design fornito «Front desk of a hotel»: stessa disposizione, stessi colori e stessa gerarchia dei contenuti, con le schermate e i requisiti del progetto.",
} as const;

function unused(): Promise<never> {
  return Promise.reject(new Error("not used in this spec"));
}

function notFound(): DesignMockupsApiError {
  return new DesignMockupsApiError("Design Mockups API request failed with status 404", {
    status: 404,
    code: null,
    payload: { detail: "Not Found" },
  });
}

function readinessOf(version: DesignPackageVersionPayload | null): DesignReadinessPayload {
  return {
    status: version === null ? "DESIGN_REQUIRED" : "DESIGN_APPROVAL_REQUIRED",
    version,
    gate: null,
    has_package: version !== null,
    package_ready_for_gate: version?.ready_for_gate ?? false,
    approved_current_package: false,
  };
}

class StepDesignApi implements DesignApi {
  constructor(private readonly version: DesignPackageVersionPayload | null) {}

  generateMockup = vi.fn(unused);
  currentMockup = vi.fn(async () => null);
  generate = vi.fn(unused);
  current = vi.fn(async () => this.version ?? UNSELECTED_DESIGN_VERSION);
  history = vi.fn(async () =>
    this.version === null ? [] : [UNSELECTED_DESIGN_VERSION, this.version],
  );
  proposeRevision = vi.fn(unused);
  revisionHistory = vi.fn(async () => []);
  getRevision = vi.fn(unused);
  decideRevision = vi.fn(unused);
  submitGate = vi.fn(unused);
  decideGate = vi.fn(unused);
  currentGate = vi.fn(unused);
  gateEvents = vi.fn(async () => []);
  readiness = vi.fn(async () => readinessOf(this.version));
}

const loopApi: DesignLoopApi = {
  evaluate: unused,
  runs: async () => [],
  comparison: async () => null,
  regenerate: unused,
  applyInsight: unused,
  applications: async () => [],
  validations: async () => [],
  validate: unused,
  discussions: async () => [],
  startDiscussion: unused,
  nextDiscussionRound: unused,
  decideDiscussion: unused,
};

const REQUIREMENTS = SELECTED_DESIGN_PACKAGE.grounding.requirements_reference;

const requirementsReadiness: RequirementsReadinessPayload = {
  status: "READY_FOR_DESIGN_EXPLORATION",
  version: {
    id: REQUIREMENTS.artifact_id,
    project_id: DESIGN_PROJECT_ID,
    version_number: REQUIREMENTS.version_number,
    based_on_version_number: null,
    content_hash: REQUIREMENTS.content_hash,
    created_by_user_id: DESIGN_OWNER_ID,
    created_at: DESIGN_CREATED_AT,
    specification: {} as RequirementsSpecificationPayload,
  },
  gate: null,
  approved_current_specification: true,
};

function requirementsApi(): Pick<RequirementsApi, "readiness" | "submitGate" | "decideGate"> {
  return {
    readiness: vi.fn(async () => requirementsReadiness),
    submitGate: vi.fn(unused),
    decideGate: vi.fn(unused),
  };
}

function alignmentApi(): Pick<DesignAlignmentApi, "status"> {
  return {
    status: vi.fn(async () => {
      throw new DesignAlignmentApiError("The design alignment request failed", {
        status: 404,
        code: null,
        payload: { detail: "Not Found" },
      });
    }),
  };
}

function mockupsApi(drawn: boolean): DesignMockupsApi {
  return {
    capabilities: vi.fn(async () => {
      if (!drawn) {
        throw notFound();
      }
      return { generated_mockups: true, iterations: true, model: "claude-opus-5-5" };
    }),
    startJob: vi.fn(unused),
    job: vi.fn(unused),
    latest: vi.fn(async () => null),
    document: vi.fn(async () => {
      throw notFound();
    }),
  };
}

function drawing(): GenerationJobPayload {
  return {
    job_id: "job-redraw",
    kind: "ITERATION",
    status: "RUNNING",
    stage: "GENERATING",
    attempt: 1,
    started_at: DESIGN_CREATED_AT,
    finished_at: null,
    alternative_id: DESIGN_ALTERNATIVE_ID,
    result: null,
    failure: null,
  };
}

function iterationsApi() {
  return {
    startJob: vi.fn<DesignIterationsApi["startJob"]>(async () => drawing()),
    job: vi.fn<DesignIterationsApi["job"]>(async () => drawing()),
    list: vi.fn<DesignIterationsApi["list"]>(async () => ({ items: [] })),
  } satisfies DesignIterationsApi;
}

function usageApi() {
  return {
    usage: vi.fn<ModelUsageApi["usage"]>(async () => ({
      items: [],
      totals: { generations: 0, input_tokens: 0, output_tokens: 0, cost_microusd: 0 },
    })),
    budget: vi.fn<ModelUsageApi["budget"]>(unused),
  } satisfies ModelUsageApi;
}

function distanceApi(): DesignDistanceApi {
  return {
    distance: vi.fn(async () => {
      throw new DesignApiError("DESIGN_PACKAGE_NOT_FOUND", {
        status: 404,
        code: "DESIGN_PACKAGE_NOT_FOUND",
        payload: { detail: { code: "DESIGN_PACKAGE_NOT_FOUND" } },
      });
    }),
  };
}

function critiqueApi(runs: DesignCritiqueRunPayload[] = [RUN]) {
  return {
    uploadSource: vi.fn<DesignCritiqueApi["uploadSource"]>(async () => SOURCE),
    sources: vi.fn<DesignCritiqueApi["sources"]>(async () => [SOURCE]),
    shot: vi.fn<DesignCritiqueApi["shot"]>(
      async () => new Blob(["fake-png"], { type: "image/png" }),
    ),
    critique: vi.fn<DesignCritiqueApi["critique"]>(
      async (): Promise<DesignCritiqueResultPayload> => ({
        status: "DESIGN_CRITIQUE_RECORDED",
        run: RUN,
      }),
    ),
    runs: vi.fn<DesignCritiqueApi["runs"]>(async () => runs),
  } satisfies DesignCritiqueApi;
}

function owner(guidanceMode: GuidanceMode): UserResponse {
  return {
    id: DESIGN_OWNER_ID,
    email: "owner@example.com",
    is_active: true,
    created_at: DESIGN_CREATED_AT,
    guidance_mode: guidanceMode,
  };
}

interface Step {
  version: DesignPackageVersionPayload | null;
  locale?: "en" | "it";
  critique?: ReturnType<typeof critiqueApi>;
  iterations?: ReturnType<typeof iterationsApi>;
  usage?: ReturnType<typeof usageApi>;
  twinsReady?: boolean;
  attach?: boolean;
}

const mounted: VueWrapper[] = [];

function mountFlow(step: Step) {
  const locale = step.locale ?? "en";
  const wrapper = mount(ProjectDesignFlow, {
    props: {
      projectId: DESIGN_PROJECT_ID,
      locale,
      authorize,
      api: new StepDesignApi(step.version),
      loopApi,
      requirementsApi: requirementsApi(),
      alignmentApi: alignmentApi(),
      mockupsApi: mockupsApi(step.version !== null),
      iterationsApi: step.iterations ?? iterationsApi(),
      usageApi: step.usage ?? usageApi(),
      distanceApi: distanceApi(),
      critiqueApi: step.critique ?? critiqueApi(),
      ...(step.twinsReady === undefined ? {} : { twinsReady: step.twinsReady }),
    },
    global: {
      plugins: [createAppI18n(locale)],
      stubs: { ProjectHumanValidationPanel: true, AlignmentProposalsNotice: true },
    },
    ...(step.attach === true ? { attachTo: document.body } : {}),
  });
  mounted.push(wrapper);
  return wrapper;
}

async function openCritique(wrapper: VueWrapper): Promise<void> {
  const panel = wrapper.get('[data-testid="design-critique"]');
  (panel.element as HTMLDetailsElement).open = true;
  await panel.trigger("toggle");
  await flushPromises();
}

function follows(first: Element, second: Element): boolean {
  return (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
}

const URL_METHODS = ["createObjectURL", "revokeObjectURL"] as const;
const originals = Object.fromEntries(
  URL_METHODS.map((name) => [name, Object.getOwnPropertyDescriptor(URL, name)]),
);

describe("ProjectDesignFlow: critique of an existing design", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setActivePinia(createPinia());
    useAuthStore().user = owner("GUIDED");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => "blob:shot"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
    for (const name of URL_METHODS) {
      const original = originals[name];
      if (original === undefined) {
        Reflect.deleteProperty(URL, name);
      } else {
        Object.defineProperty(URL, name, original);
      }
    }
  });

  it.each([
    ["en", "Critique of an existing design"],
    ["it", "Critica di un design esistente"],
  ] as const)(
    "offers the critique, closed, after the button that prepares the alternatives (%s)",
    async (locale, label) => {
      const critique = critiqueApi();
      const wrapper = mountFlow({ version: null, locale, critique });
      await flushPromises();

      const empty = wrapper.get('[data-testid="design-empty"]');
      const panel = empty.get('[data-testid="design-critique"]');
      expect((panel.element as HTMLDetailsElement).open).toBe(false);
      expect(
        panel.get('[data-testid="design-critique-summary"] span:not([aria-hidden])').text(),
      ).toBe(label);
      expect(panel.element.previousElementSibling).toBe(
        wrapper.get('[data-testid="generate-design"]').element,
      );
      expect(wrapper.findAll('[data-testid="design-critique"]')).toHaveLength(1);
      expect(critique.runs).not.toHaveBeenCalled();
      expect(critique.sources).not.toHaveBeenCalled();
    },
  );

  it("keeps the redraw unavailable while the project has no design yet", async () => {
    const critique = critiqueApi();
    const wrapper = mountFlow({ version: null, critique });
    await flushPromises();

    await openCritique(wrapper);

    expect(critique.runs).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="design-critique-redraw"]').attributes("aria-disabled")).toBe(
      "true",
    );
    expect(wrapper.get('[data-testid="design-critique-redraw-missing"]').text()).toBe(
      "To redraw you need a Studio design with its mockup: prepare the design, then redraw.",
    );
  });

  it.each(["GUIDED", "EXPERT"] as const)(
    "offers the critique, closed, after the versions and the alternatives and before the explicit mockups (%s)",
    async (guidanceMode) => {
      useAuthStore().user = owner(guidanceMode);
      const critique = critiqueApi();
      const wrapper = mountFlow({ version: DRAWN_VERSION, critique });
      await flushPromises();

      const panel = wrapper.get('[data-testid="design-critique"]');
      expect((panel.element as HTMLDetailsElement).open).toBe(false);
      expect(wrapper.findAll('[data-testid="design-critique"]')).toHaveLength(1);
      expect(wrapper.find('[data-testid="design-empty"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="design-text-view"]').element.contains(panel.element)).toBe(
        true,
      );
      const history = wrapper.get('[data-testid="design-history"]').element;
      const alternatives = wrapper.get('[data-testid="design-alternatives"]').element;
      expect(history.nextElementSibling).toBe(alternatives);
      expect(follows(history, panel.element)).toBe(true);
      expect(follows(alternatives, panel.element)).toBe(true);
      const explicit = wrapper.find('[data-testid="explicit-mockup-actions"]');
      expect(explicit.exists()).toBe(guidanceMode === "EXPERT");
      if (explicit.exists()) {
        expect(follows(panel.element, explicit.element)).toBe(true);
      }
      expect(critique.runs).not.toHaveBeenCalled();
    },
  );

  it.each(["en", "it"] as const)(
    "redraws the supplied design as a mockup with the fixed request and the source of the critique (%s)",
    async (locale) => {
      const iterations = iterationsApi();
      const wrapper = mountFlow({ version: DRAWN_VERSION, locale, iterations });
      await flushPromises();
      await openCritique(wrapper);

      const redraw = wrapper.get('[data-testid="design-critique-redraw"]');
      expect(redraw.attributes("aria-disabled")).toBeUndefined();
      await redraw.trigger("click");
      await flushPromises();

      expect(iterations.startJob).toHaveBeenCalledTimes(1);
      expect(iterations.startJob).toHaveBeenCalledWith(
        DESIGN_PROJECT_ID,
        {
          design_version_id: DRAWN_VERSION.id,
          design_content_hash: DRAWN_VERSION.content_hash,
          request: REDRAW_REQUESTS[locale],
          assertions: [],
          critique_source_id: SOURCE_ID,
        },
        "access-token",
      );
      const panel = wrapper.get('[data-testid="design-iteration-panel"]');
      expect(panel.attributes("data-phase")).toBe("drawing");
      expect(panel.get('[data-testid="design-iteration-request"]').text()).toBe(
        REDRAW_REQUESTS[locale],
      );
      expect(
        wrapper.get('[data-testid="design-critique-redraw"]').attributes("aria-disabled"),
      ).toBe("true");
      expect(wrapper.find('[data-testid="design-critique-redraw-busy"]').exists()).toBe(true);

      await wrapper.get('[data-testid="design-critique-redraw"]').trigger("click");
      await flushPromises();
      expect(iterations.startJob).toHaveBeenCalledTimes(1);
    },
  );

  it("does not redraw when the Studio cannot draw new versions of the mockup", async () => {
    const iterations = iterationsApi();
    const wrapper = mountFlow({ version: SELECTED_DESIGN_VERSION, iterations });
    await flushPromises();
    await openCritique(wrapper);

    const redraw = wrapper.get('[data-testid="design-critique-redraw"]');
    expect(redraw.attributes("aria-disabled")).toBe("true");
    expect(wrapper.find('[data-testid="design-critique-redraw-missing"]').exists()).toBe(true);
    await redraw.trigger("click");
    await flushPromises();
    expect(iterations.startJob).not.toHaveBeenCalled();
  });

  it("tells the critique whether the twins are approved", async () => {
    const wrapper = mountFlow({ version: DRAWN_VERSION, twinsReady: false, locale: "it" });
    await flushPromises();
    await openCritique(wrapper);

    expect(wrapper.get('[data-testid="design-critique-twins-missing"]').text()).toBe(
      "Prima approva i twin.",
    );
    expect(wrapper.get('[data-testid="design-critique-ask"]').attributes("aria-disabled")).toBe(
      "true",
    );
  });

  it("reads the use of the model again after a critique", async () => {
    const usage = usageApi();
    const critique = critiqueApi([]);
    const wrapper = mountFlow({ version: null, usage, critique });
    await flushPromises();
    await openCritique(wrapper);
    const before = usage.usage.mock.calls.length;

    const input = wrapper.get('[data-testid="design-critique-file"]');
    Object.defineProperty(input.element, "files", {
      value: [new File(["fake-png"], "front-desk.png", { type: "image/png" })],
      configurable: true,
    });
    await input.trigger("change");
    await wrapper.get('[data-testid="design-critique-ask"]').trigger("click");
    await flushPromises();

    expect(critique.critique).toHaveBeenCalledWith(
      DESIGN_PROJECT_ID,
      { source_id: SOURCE_ID, locale: "en-US" },
      "access-token",
    );
    expect(usage.usage.mock.calls.length).toBe(before + 1);
    expect(wrapper.get('[data-testid="design-critique-run"] h3').text()).toBe(
      "Front desk of a hotel",
    );
  });

  it("has no axe violations with the critique open next to the design", async () => {
    const wrapper = mountFlow({ version: DRAWN_VERSION, locale: "it" });
    await flushPromises();
    await openCritique(wrapper);

    await expectAccessible(wrapper.element);
  });
});
