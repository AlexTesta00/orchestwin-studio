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
import type { UserResponse } from "../api/contracts";
import type { ModelUsageApi } from "../api/modelUsage";
import type { RequirementsApi } from "../api/requirements";
import { useAuthStore } from "../stores/auth";
import { expectAccessible } from "../test/axe";
import {
  BASE_DESIGN_PACKAGE,
  DESIGN_CREATED_AT,
  DESIGN_OWNER_ID,
  DESIGN_PROJECT_ID,
  UNSELECTED_DESIGN_VERSION,
} from "../test/designFixtures";
import type {
  DesignAlternativePayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
} from "../types/design";
import type {
  RequirementsReadinessPayload,
  RequirementsSpecificationPayload,
} from "../types/requirements";
import ProjectDesignFlow from "./ProjectDesignFlow.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");
const SYSTEM_ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000146";
const DASHBOARD = BASE_DESIGN_PACKAGE.alternatives[1]!;

const SYSTEM_ALTERNATIVE: DesignAlternativePayload = {
  ...DASHBOARD,
  id: SYSTEM_ALTERNATIVE_ID,
  code: "DES-003",
  title: "System desk",
  summary: "Arrivals on clear panels, like an app of the system.",
  visual_language: { ...DASHBOARD.visual_language!, design_system: "apple-hig" },
};

const THREE_VERSION: DesignPackageVersionPayload = {
  ...UNSELECTED_DESIGN_VERSION,
  package: {
    ...BASE_DESIGN_PACKAGE,
    alternatives: [...BASE_DESIGN_PACKAGE.alternatives, SYSTEM_ALTERNATIVE],
  },
};

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

function readinessOf(version: DesignPackageVersionPayload): DesignReadinessPayload {
  return {
    status: "DESIGN_APPROVAL_REQUIRED",
    version,
    gate: null,
    has_package: true,
    package_ready_for_gate: version.ready_for_gate,
    approved_current_package: false,
  };
}

class ThreeDesignApi implements DesignApi {
  generateMockup = vi.fn(unused);
  currentMockup = vi.fn(async () => null);
  generate = vi.fn(unused);
  current = vi.fn(async () => THREE_VERSION);
  history = vi.fn(async () => [THREE_VERSION]);
  proposeRevision = vi.fn(unused);
  revisionHistory = vi.fn(async () => []);
  getRevision = vi.fn(unused);
  decideRevision = vi.fn(unused);
  submitGate = vi.fn(unused);
  decideGate = vi.fn(unused);
  currentGate = vi.fn(unused);
  gateEvents = vi.fn(async () => []);
  readiness = vi.fn(async () => readinessOf(THREE_VERSION));
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

const REQUIREMENTS = BASE_DESIGN_PACKAGE.grounding.requirements_reference;

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

function mockupsApi(): DesignMockupsApi {
  return {
    capabilities: vi.fn(async () => {
      throw notFound();
    }),
    startJob: vi.fn(unused),
    job: vi.fn(unused),
    latest: vi.fn(async () => null),
    document: vi.fn(async () => {
      throw notFound();
    }),
  };
}

function iterationsApi(): DesignIterationsApi {
  return {
    startJob: vi.fn<DesignIterationsApi["startJob"]>(unused),
    job: vi.fn<DesignIterationsApi["job"]>(unused),
    list: vi.fn<DesignIterationsApi["list"]>(async () => ({ items: [] })),
  };
}

function usageApi(): ModelUsageApi {
  return {
    usage: vi.fn<ModelUsageApi["usage"]>(async () => ({
      items: [],
      totals: { generations: 0, input_tokens: 0, output_tokens: 0, cost_microusd: 0 },
    })),
    budget: vi.fn<ModelUsageApi["budget"]>(unused),
  };
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

function critiqueApi(): DesignCritiqueApi {
  return {
    uploadSource: vi.fn<DesignCritiqueApi["uploadSource"]>(unused),
    sources: vi.fn<DesignCritiqueApi["sources"]>(async () => []),
    shot: vi.fn<DesignCritiqueApi["shot"]>(unused),
    critique: vi.fn<DesignCritiqueApi["critique"]>(unused),
    runs: vi.fn<DesignCritiqueApi["runs"]>(async () => []),
  };
}

function owner(): UserResponse {
  return {
    id: DESIGN_OWNER_ID,
    email: "owner@example.com",
    is_active: true,
    created_at: DESIGN_CREATED_AT,
    guidance_mode: "GUIDED",
  };
}

const mounted: VueWrapper[] = [];

function mountFlow(locale: "en" | "it") {
  const wrapper = mount(ProjectDesignFlow, {
    props: {
      projectId: DESIGN_PROJECT_ID,
      locale,
      authorize,
      api: new ThreeDesignApi(),
      loopApi,
      requirementsApi: requirementsApi(),
      alignmentApi: alignmentApi(),
      mockupsApi: mockupsApi(),
      iterationsApi: iterationsApi(),
      usageApi: usageApi(),
      distanceApi: distanceApi(),
      critiqueApi: critiqueApi(),
    },
    global: {
      plugins: [createAppI18n(locale)],
      stubs: { ProjectHumanValidationPanel: true, AlignmentProposalsNotice: true },
    },
  });
  mounted.push(wrapper);
  return wrapper;
}

describe("ProjectDesignFlow with three design alternatives", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setActivePinia(createPinia());
    useAuthStore().user = owner();
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
  });

  it.each([
    [
      "en",
      "I prepared three alternatives and had the twins try them. Their opinion is below.",
      "Apple guidelines",
    ],
    [
      "it",
      "Ho preparato tre alternative e le ho fatte provare ai twin. Il loro parere è qui sotto.",
      "Linee guida Apple",
    ],
  ] as const)(
    "counts the three alternatives, shows a card for each and labels the Apple one (%s)",
    async (locale, intro, label) => {
      const wrapper = mountFlow(locale);
      await flushPromises();

      expect(wrapper.text()).toContain(intro);
      const section = wrapper.get('[data-testid="design-alternatives"]');
      expect(
        section
          .findAll('[data-testid="design-alternative"]')
          .map((item) => item.attributes("data-test")),
      ).toEqual(["alternative-DES-001", "alternative-DES-002", "alternative-DES-003"]);
      const labels = section.findAll('[data-testid="alternative-system"]');
      expect(labels.map((item) => item.text())).toEqual([label]);
      expect(
        section
          .get('[data-test="alternative-DES-003"]')
          .find('[data-testid="alternative-system"]')
          .exists(),
      ).toBe(true);
      expect(wrapper.text()).not.toContain("apple-hig");
    },
  );

  it("has no axe violations with the three alternatives", async () => {
    const wrapper = mountFlow("it");
    await flushPromises();

    await expectAccessible(wrapper.element);
  });
});
