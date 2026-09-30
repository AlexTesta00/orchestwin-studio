import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectTwinLearningBlock from "./ProjectTwinLearningBlock.vue";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";

import { TwinLearningApiError, type TwinLearningApi } from "../api/twinLearning";
import type {
  LearningTwinPayload,
  TwinLearningPayload,
  TwinUpdatePayload,
} from "../types/twinLearning";

type Locale = "en" | "it";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";
const RECEPTION_ID = "55555555-5555-4555-8555-555555555555";
const MANAGER_ID = "66666666-6666-4666-8666-666666666666";

const REQUIREMENT_TITLES = { "REQ-003": "Guests are checked in quickly" };
const SCREEN_TITLES = { "SCR-001": "Guest list" };

const RECEPTION: LearningTwinPayload = {
  twin_id: RECEPTION_ID,
  twin_name: "Reception staff",
  profile_version_number: 1,
  development_version_number: 2,
  label: "1.2",
  observations: [
    {
      code: "OBS-001",
      statement: "Reception staff look for a new guest at the top of the list.",
      basis: "Two findings on the acceptance tests of the guest list.",
      source: "TWIN_CRITIQUE",
      about: { requirement: "REQ-003", screen: "SCR-001" },
      contradicts_profile: null,
      added_in_version: 1,
      approved_at: "2026-09-29T10:00:00+00:00",
      update_id: "77777777-7777-4777-8777-777777777777",
    },
    {
      code: "OBS-003",
      statement: "Reception staff work standing, with one hand free.",
      basis: null,
      source: "OWNER",
      about: { requirement: null, screen: "SCR-009" },
      contradicts_profile: "The profile says that they work sitting at a desk.",
      added_in_version: 2,
      approved_at: "2026-09-29T11:00:00+00:00",
      update_id: null,
    },
  ],
  retired: [
    {
      code: "OBS-002",
      statement: "Reception staff print the list of the day.",
      retired_in_version: 2,
      retired_at: "2026-09-29T11:30:00+00:00",
      reason: null,
    },
  ],
  pending_update: null,
  new_material: { changes: 2, tests: 1 },
};

const PROPOSAL: TwinUpdatePayload = {
  id: "88888888-8888-4888-8888-888888888888",
  twin_id: MANAGER_ID,
  twin_name: "Restaurant manager",
  created_at: "2026-09-29T12:00:00+00:00",
  locale: "en-GB",
  status: "PROPOSED",
  base: { profile_version_number: 1, development_version_number: 0 },
  comment: "From the latest critiques I learned 1 things about my group.",
  observations: [
    {
      index: 0,
      statement: "Restaurant manager: the total of the guests is missing.",
      basis: "A finding on the commit c0ffee12.",
      about: { requirement: null, screen: null },
      contradicts_profile: null,
    },
  ],
  material: { changes: 1, tests: 0 },
  decision: null,
  cost_microusd: 150000,
};

const MANAGER: LearningTwinPayload = {
  twin_id: MANAGER_ID,
  twin_name: "Restaurant manager",
  profile_version_number: 1,
  development_version_number: 0,
  label: "1.0",
  observations: [],
  retired: [],
  pending_update: PROPOSAL,
  new_material: { changes: 1, tests: 0 },
};

function learning(overrides: Partial<TwinLearningPayload> = {}): TwinLearningPayload {
  return {
    project_id: PROJECT_ID,
    update_available: true,
    twins: [RECEPTION, MANAGER],
    ...overrides,
  };
}

function learningApi(read: TwinLearningApi["overview"] = async () => learning()) {
  return { overview: vi.fn<TwinLearningApi["overview"]>(read) };
}

function mountBlock(api: TwinLearningApi, locale: Locale = "en") {
  return mount(ProjectTwinLearningBlock, {
    global: { plugins: [createAppI18n(locale)] },
    props: {
      projectId: PROJECT_ID,
      locale,
      authorize: (operation) => operation(TOKEN),
      api,
      requirementTitles: REQUIREMENT_TITLES,
      screenTitles: SCREEN_TITLES,
    },
    attachTo: document.body,
  });
}

function words(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function spoken(element: { text(): string }): string {
  return words(element.text());
}

function dated(value: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "it" ? "it-IT" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(Date.parse(value));
}

describe("ProjectTwinLearningBlock", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
  });

  it("reads what the twins learned once and shows every twin with its version", async () => {
    const api = learningApi();
    const wrapper = mountBlock(api);
    await flushPromises();

    expect(api.overview).toHaveBeenCalledTimes(1);
    expect(api.overview).toHaveBeenCalledWith(PROJECT_ID, TOKEN);
    const block = wrapper.get('[data-testid="learning-block"]');
    expect(block.get("h3").text()).toBe("What the twins learned");
    expect(block.text()).toContain(
      "An observation becomes part of the twin only when you approve it, and each change raises the number after the dot in its version: 1.2 is profile version 1 with two changes.",
    );
    const twins = block.findAll('[data-testid="learning-twin"]');
    expect(twins.map((twin) => twin.get("h4").text())).toEqual([
      "Reception staff",
      "Restaurant manager",
    ]);
    expect(twins.map((twin) => twin.get('[data-testid="learning-twin-label"]').text())).toEqual([
      "version 1.2",
      "version 1.0",
    ]);
    expect(wrapper.findAll("button")).toHaveLength(0);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      [
        `From its critiques, approved on ${dated("2026-09-29T10:00:00+00:00", "en")}`,
        `Written by you on ${dated("2026-09-29T11:00:00+00:00", "en")}`,
      ],
      "Based on: Two findings on the acceptance tests of the guest list.",
      ["REQ-003 · Guests are checked in quickly", "SCR-001 · Guest list"],
      "It contradicts the profile: The profile says that they work sitting at a desk.",
    ],
    [
      "it",
      [
        `Dalle sue critiche, approvata il ${dated("2026-09-29T10:00:00+00:00", "it")}`,
        `Scritta da te il ${dated("2026-09-29T11:00:00+00:00", "it")}`,
      ],
      "Si basa su: Two findings on the acceptance tests of the guest list.",
      ["REQ-003 · Guests are checked in quickly", "SCR-001 · Guest list"],
      "Contraddice il profilo: The profile says that they work sitting at a desk.",
    ],
  ] as const)(
    "shows in %s every learned observation with where it comes from, when, what it is about and a contradiction",
    async (locale, sources, basis, subjects, contradiction) => {
      const wrapper = mountBlock(learningApi(), locale);
      await flushPromises();

      const reception = wrapper.findAll('[data-testid="learning-twin"]')[0]!;
      const frame = reception.get('[data-testid="learning-observations"]');
      expect(frame.attributes("data-claim-status")).toBe("confirmed");
      const observations = frame.findAll('[data-testid="learning-observation"]');
      expect(
        observations.map((item) => item.get('[data-testid="learning-observation-code"]').text()),
      ).toEqual(["OBS-001", "OBS-003"]);
      expect(spoken(observations[0]!.get("p"))).toBe(
        "OBS-001 · Reception staff look for a new guest at the top of the list.",
      );
      expect(
        observations.map((item) => item.get('[data-testid="learning-observation-source"]').text()),
      ).toEqual(sources);
      expect(spoken(observations[0]!.get('[data-testid="learning-observation-basis"]'))).toBe(
        basis,
      );
      expect(observations[0]!.findAll('[data-testid="learning-subject"]').map(spoken)).toEqual(
        subjects,
      );
      expect(observations[0]!.find('[data-testid="learning-contradiction"]').exists()).toBe(false);
      expect(observations[1]!.find('[data-testid="learning-observation-basis"]').exists()).toBe(
        false,
      );
      expect(observations[1]!.findAll('[data-testid="learning-subject"]').map(spoken)).toEqual([
        "SCR-009",
      ]);
      expect(spoken(observations[1]!.get('[data-testid="learning-contradiction"]'))).toBe(
        contradiction,
      );
      wrapper.unmount();
    },
  );

  it.each([
    ["en", "1 observation was retired.", "3 observations were retired.", "Nothing learned yet."],
    [
      "it",
      "1 osservazione è stata ritirata.",
      "3 osservazioni sono state ritirate.",
      "Non ha ancora imparato nulla.",
    ],
  ] as const)(
    "counts in %s the retired observations and says when a twin learned nothing",
    async (locale, one, many, nothing) => {
      const retired = RECEPTION.retired[0]!;
      const api = learningApi(async () =>
        learning({
          twins: [
            RECEPTION,
            {
              ...MANAGER,
              retired: [retired, { ...retired, code: "OBS-004" }, { ...retired, code: "OBS-005" }],
            },
          ],
        }),
      );
      const wrapper = mountBlock(api, locale);
      await flushPromises();

      const twins = wrapper.findAll('[data-testid="learning-twin"]');
      expect(twins[0]!.get('[data-testid="learning-retired"]').text()).toBe(one);
      expect(twins[1]!.get('[data-testid="learning-retired"]').text()).toBe(many);
      expect(twins[1]!.get('[data-testid="learning-nothing"]').text()).toBe(nothing);
      expect(twins[1]!.find('[data-testid="learning-observations"]').exists()).toBe(false);
      expect(twins[0]!.find('[data-testid="learning-nothing"]').exists()).toBe(false);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "en",
      "It has new critiques to learn from, on 2 commits and 1 test run: ut twins update.",
      "A proposal waits for your decision: ut twins update.",
    ],
    [
      "it",
      "Ha nuove critiche da cui imparare, su 2 commit e 1 verifica: ut twins update.",
      "Una proposta attende la tua decisione: ut twins update.",
    ],
  ] as const)(
    "says in %s when a twin has new critiques to learn from and when a proposal waits",
    async (locale, material, pending) => {
      const wrapper = mountBlock(learningApi(), locale);
      await flushPromises();

      const [reception, manager] = wrapper.findAll('[data-testid="learning-twin"]');
      const fresh = reception!.get('[data-testid="learning-new-material"]');
      expect(spoken(fresh)).toBe(material);
      expect(fresh.findAll("code").map((item) => item.text())).toEqual(["ut twins update"]);
      expect(reception!.find('[data-testid="learning-pending"]').exists()).toBe(false);
      const waiting = manager!.get('[data-testid="learning-pending"]');
      expect(spoken(waiting)).toBe(pending);
      expect(waiting.findAll("code").map((item) => item.text())).toEqual(["ut twins update"]);
      expect(manager!.find('[data-testid="learning-new-material"]').exists()).toBe(false);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "en",
      { changes: 1, tests: 0 },
      "It has new critiques to learn from, on 1 commit: ut twins update.",
    ],
    [
      "en",
      { changes: 0, tests: 2 },
      "It has new critiques to learn from, on 2 test runs: ut twins update.",
    ],
    [
      "it",
      { changes: 3, tests: 0 },
      "Ha nuove critiche da cui imparare, su 3 commit: ut twins update.",
    ],
    [
      "it",
      { changes: 0, tests: 1 },
      "Ha nuove critiche da cui imparare, su 1 verifica: ut twins update.",
    ],
    [
      "it",
      { changes: 0, tests: 4 },
      "Ha nuove critiche da cui imparare, su 4 verifiche: ut twins update.",
    ],
  ] as const)("names in %s the new critiques %o", async (locale, material, sentence) => {
    const wrapper = mountBlock(
      learningApi(async () => learning({ twins: [{ ...RECEPTION, new_material: material }] })),
      locale,
    );
    await flushPromises();

    expect(spoken(wrapper.get('[data-testid="learning-new-material"]'))).toBe(sentence);
    wrapper.unmount();
  });

  it("says nothing about new critiques when there are none", async () => {
    const wrapper = mountBlock(
      learningApi(async () =>
        learning({ twins: [{ ...RECEPTION, new_material: { changes: 0, tests: 0 } }] }),
      ),
    );
    await flushPromises();

    expect(wrapper.find('[data-testid="learning-new-material"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="learning-pending"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "On this Studio the twins cannot propose what they learned: connect a model. You can still write an observation yourself with ut twins learn.",
    ],
    [
      "it",
      "In questo Studio i twin non possono proporre ciò che hanno imparato: collega un modello. Puoi comunque scrivere tu un'osservazione con ut twins learn.",
    ],
  ] as const)(
    "says in %s that the twins cannot propose what they learned without a model",
    async (locale, sentence) => {
      const wrapper = mountBlock(
        learningApi(async () => learning({ update_available: false })),
        locale,
      );
      await flushPromises();

      const notice = wrapper.get('[data-testid="learning-no-model"]');
      expect(spoken(notice)).toBe(sentence);
      expect(notice.findAll("code").map((item) => item.text())).toEqual(["ut twins learn"]);
      expect(wrapper.find('[data-testid="learning-new-material"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="learning-pending"]').exists()).toBe(true);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "en",
      "What the twins learned",
      "Everything happens in the terminal: ut twins update has the twins propose what they learned, ut twins learn writes an observation yourself, ut twins forget retires one.",
    ],
    [
      "it",
      "Che cosa hanno imparato i twin",
      "Tutto avviene nel terminale: ut twins update fa proporre ai twin ciò che hanno imparato, ut twins learn scrive una tua osservazione, ut twins forget ne ritira una.",
    ],
  ] as const)("names the commands of the terminal in %s", async (locale, title, sentence) => {
    const wrapper = mountBlock(learningApi(), locale);
    await flushPromises();

    expect(wrapper.get("h3").text()).toBe(title);
    const terminal = wrapper.get('[data-testid="learning-terminal"]');
    expect(spoken(terminal)).toBe(sentence);
    expect(terminal.findAll("code").map((item) => item.text())).toEqual([
      "ut twins update",
      "ut twins learn",
      "ut twins forget",
    ]);
    expect(wrapper.find('[data-testid="learning-no-model"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("speaks Italian", async () => {
    const wrapper = mountBlock(learningApi(), "it");
    await flushPromises();

    expect(
      wrapper.findAll('[data-testid="learning-twin-label"]').map((item) => item.text()),
    ).toEqual(["versione 1.2", "versione 1.0"]);
    expect(wrapper.text()).toContain(
      "Un'osservazione entra nel twin solo quando la approvi, e ogni cambiamento aumenta il numero dopo il punto nella sua versione: 1.2 è il profilo versione 1 con due cambiamenti.",
    );
    expect(wrapper.text()).toContain("Riguarda:");
    wrapper.unmount();
  });

  it("is absent while no twin is approved", async () => {
    const wrapper = mountBlock(learningApi(async () => learning({ twins: [] })));
    await flushPromises();

    expect(wrapper.find('[data-testid="learning-block"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("is absent without an error when the Studio does not serve what the twins learned", async () => {
    const api = learningApi(async () => null);
    const wrapper = mountBlock(api);
    await flushPromises();

    expect(api.overview).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[data-testid="learning-block"]').exists()).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("shows nothing while it reads", async () => {
    const wrapper = mountBlock(learningApi(() => new Promise<never>(() => undefined)));
    await flushPromises();

    expect(wrapper.find('[data-testid="learning-block"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      new TwinLearningApiError("The twin learning request failed", {
        status: 503,
        code: "DATABASE_UNAVAILABLE",
        payload: null,
      }),
      "What the twins learned could not be loaded (DATABASE_UNAVAILABLE).",
    ],
    [
      "it",
      new TwinLearningApiError("The twin learning request failed", {
        status: 503,
        code: "DATABASE_UNAVAILABLE",
        payload: null,
      }),
      "Non è stato possibile caricare ciò che hanno imparato i twin (DATABASE_UNAVAILABLE).",
    ],
    ["en", new TypeError("Failed to fetch"), "What the twins learned could not be loaded."],
  ] as const)(
    "says in %s that what the twins learned could not be loaded",
    async (locale, error, text) => {
      const wrapper = mountBlock(
        learningApi(async () => {
          throw error;
        }),
        locale,
      );
      await flushPromises();

      const failure = wrapper.get('[data-testid="learning-error"]');
      expect(failure.attributes("role")).toBe("alert");
      expect(spoken(failure)).toBe(text);
      expect(wrapper.findAll('[data-testid="learning-twin"]')).toHaveLength(0);
      wrapper.unmount();
    },
  );

  it("reads what the twins of another project learned when the project changes", async () => {
    const api = learningApi(async (projectId) =>
      projectId === PROJECT_ID ? learning() : learning({ project_id: projectId, twins: [MANAGER] }),
    );
    const wrapper = mountBlock(api);
    await flushPromises();

    await wrapper.setProps({ projectId: SECOND_PROJECT_ID });
    await flushPromises();

    expect(api.overview).toHaveBeenCalledTimes(2);
    expect(api.overview).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, TOKEN);
    expect(wrapper.findAll('[data-testid="learning-twin"] h4').map((item) => item.text())).toEqual([
      "Restaurant manager",
    ]);
    wrapper.unmount();
  });

  it("has no axe violations with learned observations, a proposal and new critiques", async () => {
    const wrapper = mountBlock(learningApi(), "it");
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations without a model and when the read fails", async () => {
    const withoutModel = mountBlock(learningApi(async () => learning({ update_available: false })));
    await flushPromises();
    await expectAccessible(withoutModel.element);
    withoutModel.unmount();

    setActivePinia(createPinia());
    const failed = mountBlock(
      learningApi(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await flushPromises();
    await expectAccessible(failed.element);
    failed.unmount();
  });
});
