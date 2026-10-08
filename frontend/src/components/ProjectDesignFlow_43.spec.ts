import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { DesignApiError, type DesignApi, type DesignDistanceApi } from "../api/design";
import { DesignAlignmentApiError, type DesignAlignmentApi } from "../api/designAlignment";
import type { DesignLoopApi } from "../api/designLoop";
import { DesignMockupsApiError, type DesignMockupsApi } from "../api/designMockups";
import {
  DesignRestoreApiError,
  type DesignRestoreApi,
  type DesignRestorePayload,
  type DesignRestoreRequest,
} from "../api/designRestore";
import type { GuidanceMode, UserResponse } from "../api/contracts";
import type { ModelUsageApi } from "../api/modelUsage";
import type { RequirementsApi } from "../api/requirements";
import { useAuthStore } from "../stores/auth";
import { expectAccessible } from "../test/axe";
import {
  DESIGN_CREATED_AT,
  DESIGN_OWNER_ID,
  DESIGN_PROJECT_ID,
  PENDING_DESIGN_GATE,
  SELECTED_DESIGN_PACKAGE,
  SELECTED_DESIGN_VERSION,
  UNSELECTED_DESIGN_VERSION,
} from "../test/designFixtures";
import type {
  DesignPackageDiffPayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
} from "../types/design";
import type {
  RequirementsReadinessPayload,
  RequirementsSpecificationPayload,
} from "../types/requirements";
import ProjectDesignFlow from "./ProjectDesignFlow.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("access-token");
const RESTORED_ID = "00000000-0000-4000-8000-000000004304";

const THIRD_VERSION: DesignPackageVersionPayload = {
  ...SELECTED_DESIGN_VERSION,
  id: "00000000-0000-4000-8000-000000004303",
  version_number: 3,
  based_on_version_number: 2,
  content_hash: "3".repeat(64),
  package: {
    ...SELECTED_DESIGN_PACKAGE,
    open_questions: ["Should the night shift see the same list?"],
  },
};

function unused(): Promise<never> {
  return Promise.reject(new Error("not used in this spec"));
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

class HistoryDesignApi implements DesignApi {
  historyResult: DesignPackageVersionPayload[] = [
    UNSELECTED_DESIGN_VERSION,
    SELECTED_DESIGN_VERSION,
    THIRD_VERSION,
  ];
  readinessResult: DesignReadinessPayload = approvedReadiness(THIRD_VERSION);
  diffsResult: DesignPackageDiffPayload[] = [];

  generateMockup = vi.fn(unused);
  currentMockup = vi.fn(async () => null);
  generate = vi.fn(unused);
  current = vi.fn(async () => this.readinessResult.version ?? THIRD_VERSION);
  history = vi.fn(async () => this.historyResult);
  proposeRevision = vi.fn(unused);
  revisionHistory = vi.fn(async () => this.diffsResult);
  getRevision = vi.fn(unused);
  decideRevision = vi.fn(unused);
  submitGate = vi.fn(unused);
  decideGate = vi.fn(unused);
  currentGate = vi.fn(async () => this.readinessResult.gate ?? PENDING_DESIGN_GATE);
  gateEvents = vi.fn(async () => []);
  readiness = vi.fn(async () => this.readinessResult);
}

function restoreAnswer(
  api: HistoryDesignApi,
  request: DesignRestoreRequest,
  note: string,
): DesignRestorePayload {
  const source = api.historyResult.find((item) => item.version_number === request.version_number);
  if (source === undefined) {
    throw new Error("unknown version");
  }
  const created: DesignPackageVersionPayload = {
    ...source,
    id: RESTORED_ID,
    version_number: 4,
    based_on_version_number: 3,
    created_at: DESIGN_CREATED_AT,
  };
  const diff: DesignPackageDiffPayload = {
    id: "00000000-0000-4000-8000-000000004305",
    project_id: DESIGN_PROJECT_ID,
    owner_user_id: DESIGN_OWNER_ID,
    base_version_id: THIRD_VERSION.id,
    base_version_number: 3,
    base_content_hash: THIRD_VERSION.content_hash,
    proposed_package: created.package,
    proposal_hash: created.content_hash,
    changes: [
      {
        kind: "REPLACE",
        artifact_kind: "OPEN_QUESTIONS",
        artifact_id: DESIGN_PROJECT_ID,
        before: { items: THIRD_VERSION.package.open_questions },
        after: { items: created.package.open_questions },
      },
    ],
    status: "APPROVED",
    created_at: DESIGN_CREATED_AT,
    decided_by_user_id: DESIGN_OWNER_ID,
    decided_at: DESIGN_CREATED_AT,
    decision_reason: note,
    applied_version_id: created.id,
    content_hash: "5".repeat(64),
  };
  api.historyResult = [...api.historyResult, created];
  api.diffsResult = [diff];
  api.readinessResult = {
    status: created.ready_for_gate ? "DESIGN_APPROVAL_REQUIRED" : "DESIGN_REVIEW_REQUIRED",
    version: created,
    gate: api.readinessResult.gate,
    has_package: true,
    package_ready_for_gate: created.ready_for_gate,
    approved_current_package: false,
  };
  return {
    reason: "RESTORED",
    restored_version_number: request.version_number,
    note,
    revision: {
      status: "APPLIED",
      diff,
      version: created,
      issue: null,
      domain_issue: null,
      diff_persistence_status: "UPDATED",
      version_persistence_status: "APPENDED",
    },
  };
}

function fakeRestoreApi(api: HistoryDesignApi, refusal: Error | null = null) {
  return {
    restore: vi.fn(async (_projectId: string, request: DesignRestoreRequest) => {
      if (refusal !== null) {
        throw refusal;
      }
      const note =
        request.locale === "it-IT"
          ? `Ripristino della versione ${request.version_number}`
          : `Restored from version ${request.version_number}`;
      return restoreAnswer(api, request, note);
    }),
  } satisfies DesignRestoreApi;
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

function mockupsApi(): DesignMockupsApi {
  const missing = new DesignMockupsApiError("Design Mockups API request failed with status 404", {
    status: 404,
    code: null,
    payload: { detail: "Not Found" },
  });
  return {
    capabilities: vi.fn(async () => {
      throw missing;
    }),
    startJob: vi.fn(unused),
    job: vi.fn(unused),
    latest: vi.fn(async () => null),
    document: vi.fn(async () => {
      throw missing;
    }),
  };
}

function usageApi(): ModelUsageApi {
  return {
    usage: vi.fn(async () => ({
      items: [],
      totals: { generations: 0, input_tokens: 0, output_tokens: 0, cost_microusd: 0 },
    })),
    budget: vi.fn(unused),
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

function owner(guidanceMode: GuidanceMode): UserResponse {
  return {
    id: DESIGN_OWNER_ID,
    email: "owner@example.com",
    is_active: true,
    created_at: DESIGN_CREATED_AT,
    guidance_mode: guidanceMode,
  };
}

const mounted: VueWrapper[] = [];

function mountFlow(
  api: HistoryDesignApi,
  restoreApi: DesignRestoreApi,
  options: { locale?: "en" | "it"; attach?: boolean } = {},
) {
  const locale = options.locale ?? "en";
  const wrapper = mount(ProjectDesignFlow, {
    props: {
      projectId: DESIGN_PROJECT_ID,
      locale,
      authorize,
      api,
      loopApi,
      requirementsApi: requirementsApi(),
      alignmentApi: alignmentApi(),
      mockupsApi: mockupsApi(),
      usageApi: usageApi(),
      distanceApi: distanceApi(),
      restoreApi,
    },
    global: {
      plugins: [createAppI18n(locale)],
      stubs: { ProjectHumanValidationPanel: true, AlignmentProposalsNotice: true },
    },
    ...(options.attach === true ? { attachTo: document.body } : {}),
  });
  mounted.push(wrapper);
  return wrapper;
}

function appliedDiff(
  version: DesignPackageVersionPayload,
  reason: string | null,
): DesignPackageDiffPayload {
  return {
    id: "00000000-0000-4000-8000-000000004306",
    project_id: DESIGN_PROJECT_ID,
    owner_user_id: DESIGN_OWNER_ID,
    base_version_id: SELECTED_DESIGN_VERSION.id,
    base_version_number: SELECTED_DESIGN_VERSION.version_number,
    base_content_hash: SELECTED_DESIGN_VERSION.content_hash,
    proposed_package: version.package,
    proposal_hash: version.content_hash,
    changes: [
      {
        kind: "REPLACE",
        artifact_kind: "OPEN_QUESTIONS",
        artifact_id: DESIGN_PROJECT_ID,
        before: { items: SELECTED_DESIGN_VERSION.package.open_questions },
        after: { items: version.package.open_questions },
      },
    ],
    status: "APPROVED",
    created_at: DESIGN_CREATED_AT,
    decided_by_user_id: DESIGN_OWNER_ID,
    decided_at: DESIGN_CREATED_AT,
    decision_reason: reason,
    applied_version_id: version.id,
    content_hash: "6".repeat(64),
  };
}

async function openHistory(wrapper: VueWrapper): Promise<void> {
  await flushPromises();
  const history = wrapper.get('[data-testid="design-history"]');
  (history.element as HTMLDetailsElement).open = true;
  await history.trigger("toggle");
}

function versionItems(wrapper: VueWrapper) {
  return wrapper.get('[data-testid="design-history-list"]').findAll("li");
}

function versionItemOf(wrapper: VueWrapper, number: number) {
  return versionItems(wrapper).find((entry) =>
    entry.text().match(new RegExp(`^(Version|Versione) ${number} ·`)),
  );
}

function restoreButtonOf(wrapper: VueWrapper, number: number) {
  return versionItemOf(wrapper, number)?.find('[data-testid="design-restore"]');
}

describe("ProjectDesignFlow: going back to a past version", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setActivePinia(createPinia());
    useAuthStore().user = owner("GUIDED");
  });

  afterEach(() => {
    while (mounted.length > 0) {
      mounted.pop()?.unmount();
    }
    document.body.innerHTML = "";
  });

  it("offers the restore only on the past versions of the history", async () => {
    const api = new HistoryDesignApi();
    const restore = fakeRestoreApi(api);
    const wrapper = mountFlow(api, restore);
    await openHistory(wrapper);

    expect(versionItems(wrapper).map((item) => item.text().slice(0, 9))).toEqual([
      "Version 3",
      "Version 2",
      "Version 1",
    ]);
    expect(restoreButtonOf(wrapper, 1)?.exists()).toBe(true);
    expect(restoreButtonOf(wrapper, 2)?.exists()).toBe(true);
    expect(restoreButtonOf(wrapper, 3)?.exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="design-restore"]')).toHaveLength(2);
    expect(restoreButtonOf(wrapper, 2)?.text()).toBe("Go back to this version: version 2");
    expect(restore.restore).not.toHaveBeenCalled();
  });

  it.each([
    [
      "en",
      "A new version is created, identical to version 2: then it has to be approved, like every new version.",
      "Go back to version 2",
      "en-US",
      "Version 4 created from version 2: approve it with “Approve the chosen design”.",
      "Approve the chosen design",
    ],
    [
      "it",
      "Nasce una versione nuova, uguale alla versione 2: poi va approvata, come ogni versione nuova.",
      "Torna alla versione 2",
      "it-IT",
      "Versione 4 creata dalla versione 2: approvala con «Approva il design scelto».",
      "Approva il design scelto",
    ],
  ] as const)(
    "asks for a confirmation, restores and reloads the step with the new version waiting (%s)",
    async (locale, sentence, confirm, sentLocale, done, approve) => {
      const api = new HistoryDesignApi();
      const restore = fakeRestoreApi(api);
      const wrapper = mountFlow(api, restore, { locale });
      await openHistory(wrapper);
      const readsBefore = api.readiness.mock.calls.length;

      await restoreButtonOf(wrapper, 2)?.trigger("click");
      const panel = wrapper.get('[data-testid="design-restore-panel"]');
      expect(panel.text()).toContain(sentence);
      expect(panel.get('[data-testid="design-restore-confirm"]').text()).toBe(confirm);
      expect(restore.restore).not.toHaveBeenCalled();

      await panel.get('[data-testid="design-restore-confirm"]').trigger("click");
      await flushPromises();

      expect(restore.restore).toHaveBeenCalledTimes(1);
      expect(restore.restore).toHaveBeenCalledWith(
        DESIGN_PROJECT_ID,
        { version_number: 2, locale: sentLocale },
        "access-token",
      );
      expect(api.readiness.mock.calls.length).toBeGreaterThan(readsBefore);
      expect(wrapper.find('[data-testid="design-restore-panel"]').exists()).toBe(false);
      expect(versionItems(wrapper)).toHaveLength(4);
      expect(restoreButtonOf(wrapper, 4)?.exists()).toBe(false);
      expect(restoreButtonOf(wrapper, 3)?.exists()).toBe(true);
      expect(wrapper.get('[data-testid="design-restore-status"]').text()).toBe(done);
      expect(wrapper.get('[data-testid="decision-bar"]').text()).toContain(approve);
      expect(wrapper.emitted("sections-changed")).toHaveLength(1);
      expect(wrapper.find('[data-testid="design-readiness"]').exists()).toBe(false);
    },
  );

  it("closes the confirmation without calling the Studio", async () => {
    const api = new HistoryDesignApi();
    const restore = fakeRestoreApi(api);
    const wrapper = mountFlow(api, restore);
    await openHistory(wrapper);

    await restoreButtonOf(wrapper, 1)?.trigger("click");
    await wrapper.get('[data-testid="design-restore-cancel"]').trigger("click");

    expect(wrapper.find('[data-testid="design-restore-panel"]').exists()).toBe(false);
    expect(restoreButtonOf(wrapper, 1)?.exists()).toBe(true);
    expect(restore.restore).not.toHaveBeenCalled();
    expect(versionItems(wrapper)).toHaveLength(3);
  });

  it.each([
    [
      409,
      "DESIGN_RESTORE_CURRENT",
      "The current design is already the same as version 2: there is nothing to restore.",
    ],
    [404, "DESIGN_VERSION_NOT_FOUND", "Version 2 is no longer in the Studio: reload the page."],
    [
      409,
      "REQUIREMENT_NO_LONGER_AVAILABLE",
      "Version 2 cites requirements that the Definition no longer contains: it cannot come back.",
    ],
    [
      409,
      "TWIN_SET_CHANGED",
      "Version 2 was prepared with twins different from the current ones: it cannot come back.",
    ],
    [
      409,
      "DESIGN_CONTEXT_CHANGED",
      "An earlier step needs updating: update it, then go back to this version.",
    ],
    [
      409,
      "DIFF_ALREADY_PENDING",
      "Another change is waiting for your decision above: apply it or discard it first.",
    ],
    [500, null, "Going back to version 2 did not work, so nothing changed. Try again in a moment."],
  ] as const)(
    "explains a refusal %s %s next to the confirmation and keeps the design",
    async (status, code, message) => {
      const api = new HistoryDesignApi();
      const refusal = new DesignRestoreApiError("The design restore request failed", {
        status,
        code,
        payload: code === null ? null : { detail: { code } },
      });
      const restore = fakeRestoreApi(api, refusal);
      const wrapper = mountFlow(api, restore);
      await openHistory(wrapper);
      const readsBefore = api.readiness.mock.calls.length;

      await restoreButtonOf(wrapper, 2)?.trigger("click");
      await wrapper.get('[data-testid="design-restore-confirm"]').trigger("click");
      await flushPromises();

      const error = wrapper.get('[data-testid="design-restore-error"]');
      expect(error.text()).toBe(message);
      expect(error.attributes("role")).toBe("alert");
      expect(wrapper.find('[data-testid="design-restore-panel"]').exists()).toBe(true);
      expect(api.readiness.mock.calls.length).toBe(readsBefore);
      expect(wrapper.emitted("sections-changed")).toBeUndefined();
      expect(versionItems(wrapper)).toHaveLength(3);
      expect(wrapper.get('[data-testid="design-restore-status"]').text()).toBe("");
    },
  );

  it("moves the focus to the confirmation, back to the button and then to the result", async () => {
    const api = new HistoryDesignApi();
    const restore = fakeRestoreApi(api);
    const wrapper = mountFlow(api, restore, { attach: true });
    await openHistory(wrapper);

    await restoreButtonOf(wrapper, 2)?.trigger("click");
    await flushPromises();
    const confirm = wrapper.get('[data-testid="design-restore-confirm"]');
    expect(document.activeElement).toBe(confirm.element);
    const described = confirm.attributes("aria-describedby");
    expect(described).toBeDefined();
    expect(document.getElementById(described ?? "")?.textContent?.trim()).toBe(
      "A new version is created, identical to version 2: then it has to be approved, like every new version.",
    );

    await wrapper.get('[data-testid="design-restore-cancel"]').trigger("click");
    await flushPromises();
    expect(document.activeElement).toBe(restoreButtonOf(wrapper, 2)?.element);

    await restoreButtonOf(wrapper, 2)?.trigger("click");
    await wrapper.get('[data-testid="design-restore-confirm"]').trigger("click");
    await flushPromises();
    expect(document.activeElement).toBe(
      wrapper.get('[data-testid="design-restore-status"]').element,
    );
  });

  it("has no axe violations with the confirmation open", async () => {
    const api = new HistoryDesignApi();
    const wrapper = mountFlow(api, fakeRestoreApi(api), { locale: "it" });
    await openHistory(wrapper);

    await restoreButtonOf(wrapper, 2)?.trigger("click");

    await expectAccessible(wrapper.element);
  });

  it.each([
    ["en", "GUIDED", "Versions of the design (3)"],
    ["it", "EXPERT", "Versioni del design (3)"],
  ] as const)(
    "shows the versions in the step, closed, right before the alternatives (%s, %s)",
    async (locale, guidanceMode, summary) => {
      useAuthStore().user = owner(guidanceMode);
      const api = new HistoryDesignApi();
      const wrapper = mountFlow(api, fakeRestoreApi(api), { locale });
      await flushPromises();

      const history = wrapper.get('[data-testid="design-history"]');
      expect(history.element.tagName).toBe("DETAILS");
      expect((history.element as HTMLDetailsElement).open).toBe(false);
      expect(history.attributes("open")).toBeUndefined();
      const label = wrapper.get('[data-testid="design-history-summary"]');
      expect(label.element.tagName).toBe("SUMMARY");
      expect(label.get("span:not([aria-hidden])").text()).toBe(summary);
      expect(
        wrapper.get('[data-testid="design-text-view"]').element.contains(history.element),
      ).toBe(true);
      expect(history.element.nextElementSibling).toBe(
        wrapper.get('[data-testid="design-alternatives"]').element,
      );
    },
  );

  it.each([
    ["en", "current"],
    ["it", "attuale"],
  ] as const)(
    "marks the current version, listed first, without a way back to it (%s)",
    async (locale, badge) => {
      const api = new HistoryDesignApi();
      const wrapper = mountFlow(api, fakeRestoreApi(api), { locale });
      await openHistory(wrapper);

      const [latest, ...older] = versionItems(wrapper);
      expect(latest?.text()).toMatch(/^(Version|Versione) 3 ·/);
      expect(latest?.get('[data-testid="design-history-current"]').text()).toBe(badge);
      expect(latest?.find('[data-testid="design-restore"]').exists()).toBe(false);
      expect(wrapper.findAll('[data-testid="design-history-current"]')).toHaveLength(1);
      expect(older).toHaveLength(2);
      for (const item of older) {
        expect(item.find('[data-testid="design-history-current"]').exists()).toBe(false);
        expect(item.find('[data-testid="design-restore"]').exists()).toBe(true);
      }
    },
  );

  it("shows under a version the note of the change that created it, with no new request", async () => {
    const api = new HistoryDesignApi();
    api.diffsResult = [appliedDiff(THIRD_VERSION, "Restored from version 1")];
    const wrapper = mountFlow(api, fakeRestoreApi(api));
    await openHistory(wrapper);

    expect(
      wrapper.findAll('[data-testid="design-history-note"]').map((note) => note.text()),
    ).toEqual(["Restored from version 1"]);
    expect(versionItemOf(wrapper, 3)?.get('[data-testid="design-history-note"]').text()).toBe(
      "Restored from version 1",
    );
    expect(api.history).toHaveBeenCalledTimes(1);
    expect(api.revisionHistory).toHaveBeenCalledTimes(1);
  });

  it.each<[string, DesignPackageDiffPayload[]]>([
    ["no change in the history", []],
    ["a change applied without a note", [appliedDiff(THIRD_VERSION, null)]],
    ["a change applied with a blank note", [appliedDiff(THIRD_VERSION, "   ")]],
    [
      "a discarded change",
      [
        {
          ...appliedDiff(THIRD_VERSION, "The list is too dense"),
          status: "REJECTED",
          applied_version_id: null,
        },
      ],
    ],
  ])("shows no note under the versions with %s", async (_case, diffs) => {
    const api = new HistoryDesignApi();
    api.diffsResult = diffs;
    const wrapper = mountFlow(api, fakeRestoreApi(api));
    await openHistory(wrapper);

    expect(versionItems(wrapper)).toHaveLength(3);
    expect(wrapper.find('[data-testid="design-history-note"]').exists()).toBe(false);
  });

  it("keeps in the technical details the versions with their hash and no way back", async () => {
    const api = new HistoryDesignApi();
    const wrapper = mountFlow(api, fakeRestoreApi(api));
    await flushPromises();

    await wrapper.get('[data-testid="step-technical-details-toggle"]').trigger("click");
    const details = wrapper.get('[data-testid="step-technical-details-content"]');
    const lines = details
      .findAll("ol > li")
      .map((item) => item.text())
      .filter((text) => /^Version \d/.test(text));
    expect(lines.map((text) => text.slice(0, 9))).toEqual(["Version 1", "Version 2", "Version 3"]);
    expect(lines[2]).toContain(THIRD_VERSION.content_hash);
    expect(details.find('[data-testid="design-restore"]').exists()).toBe(false);
    expect(details.find('[data-testid="design-restore-status"]').exists()).toBe(false);
    expect(details.find('[data-testid="design-history"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="design-restore"]')).toHaveLength(2);
  });

  it.each([
    ["en", "current", "Restored from version 2"],
    ["it", "attuale", "Ripristino della versione 2"],
  ] as const)(
    "keeps the versions open after a restore, the new one first, current and with its note (%s)",
    async (locale, badge, note) => {
      const api = new HistoryDesignApi();
      const wrapper = mountFlow(api, fakeRestoreApi(api), { locale });
      await openHistory(wrapper);
      const history = wrapper.get('[data-testid="design-history"]').element;

      await restoreButtonOf(wrapper, 2)?.trigger("click");
      await wrapper.get('[data-testid="design-restore-confirm"]').trigger("click");
      await flushPromises();

      expect(wrapper.get('[data-testid="design-history"]').element).toBe(history);
      expect((history as HTMLDetailsElement).open).toBe(true);
      expect(
        wrapper.get('[data-testid="design-history-summary"] span:not([aria-hidden])').text(),
      ).toMatch(/ \(4\)$/);
      const [latest] = versionItems(wrapper);
      expect(latest?.text()).toMatch(/^(Version|Versione) 4 ·/);
      expect(latest?.get('[data-testid="design-history-current"]').text()).toBe(badge);
      expect(latest?.get('[data-testid="design-history-note"]').text()).toBe(note);
      expect(wrapper.findAll('[data-testid="design-history-note"]')).toHaveLength(1);
    },
  );
});
