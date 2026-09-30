import { createPinia, setActivePinia } from "pinia";
import { h, type VNode } from "vue";

import { flushPromises, mount } from "@vue/test-utils";

import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDesignPackagePanel from "./ProjectDesignPackagePanel.vue";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import { SELECTED_DESIGN_VERSION, UNSELECTED_DESIGN_VERSION } from "@/test/designFixtures";

import { KnowledgePackagesApiError, type KnowledgePackagesApi } from "../api/knowledgePackages";
import { useDesignStore } from "../stores/design";
import { useUserModelingStore } from "../stores/userModeling";
import type { DeclarativePrototypePayload, DesignAlternativePayload } from "../types/design";
import type {
  KnowledgePackagePublicationPayload,
  KnowledgePackageVersionPayload,
} from "../types/knowledgePackages";
import type { UserTwinVersionPayload } from "../types/userModeling";

const PROJECT_ID = SELECTED_DESIGN_VERSION.project_id;
const STAGES = [
  { label: "Brief", version: 2, approved: true },
  { label: "Team", version: 1, approved: true },
  { label: "User Twins", version: 1, approved: true },
  { label: "Requirements", version: 3, approved: true },
  { label: "Design", version: 1, approved: true },
];

function twin(name: string): UserTwinVersionPayload {
  return { id: `twin-${name}`, profile: { name } } as unknown as UserTwinVersionPayload;
}

function version(number: number): KnowledgePackageVersionPayload {
  return {
    id: `00000000-0000-4000-8000-00000000c00${number}`,
    project_id: PROJECT_ID,
    project_name: "Lista ospiti workshop",
    version_number: number,
    schema_version: 3,
    content_hash: String(number).repeat(64),
    archive_hash: "a".repeat(64),
    file_name: `orchestwin-${PROJECT_ID}-knowledge-v${number}.zip`,
    file_count: 54,
    archive_size: 150000,
    created_at: "2026-09-27T20:00:00Z",
    stages: [],
    progress: {
      approved: ["brief", "team", "twins", "requirements", "design"],
      pending: null,
      complete: true,
    },
    state: { changes: 0, pending_changes: 0, aligned_commit: null, open_tasks: 0 },
    twins: [
      {
        twin_id: "00000000-0000-4000-8000-0000000000a1",
        name: "Addetti all'accoglienza",
        slug: "addetti-all-accoglienza-00000000",
        version_number: 1,
        document: "twins/addetti-all-accoglienza-00000000/twin.json",
      },
    ],
    feedback: {
      reviews: 5,
      findings: 44,
      decisions: 2,
      discussions: 6,
      insights: 1,
      change_reviews: 0,
    },
    diagram_count: 7,
    table_count: 14,
    entries: ["ORCHESTWIN.md"],
  };
}

function partialVersion(number: number): KnowledgePackageVersionPayload {
  return {
    ...version(number),
    file_count: 27,
    progress: { approved: ["brief", "team", "twins"], pending: "requirements", complete: false },
    feedback: {
      reviews: 0,
      findings: 0,
      decisions: 0,
      discussions: 0,
      insights: 0,
      change_reviews: 0,
    },
    diagram_count: 0,
    table_count: 0,
  };
}

function approvedUpTo(count: number): typeof STAGES {
  return STAGES.map((stage, index) => ({ ...stage, approved: index < count }));
}

function spoken(element: { text(): string }): string {
  return element.text().replace(/\s+/g, " ");
}

function knowledgeApi(overrides: Partial<KnowledgePackagesApi> = {}): KnowledgePackagesApi {
  return {
    publish: vi.fn(() => Promise.resolve({ reused: false, version: version(2) })),
    history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [version(1)] })),
    download: vi.fn((_project: string, number: number) =>
      Promise.resolve({
        blob: new Blob(["PK"], { type: "application/zip" }),
        fileName: `orchestwin-${PROJECT_ID}-knowledge-v${number}.zip`,
        archiveHash: "a".repeat(64),
      }),
    ),
    ...overrides,
  };
}

interface PreviewSlot {
  alternative: DesignAlternativePayload;
  prototype: DeclarativePrototypePayload | null;
}

interface MountOptions {
  stages?: typeof STAGES;
  locale?: "en" | "it";
  saveExport?: () => void;
  preview?: (slot: PreviewSlot) => VNode;
}

function mountPanel(api: KnowledgePackagesApi, options: MountOptions = {}) {
  const saveExport = options.saveExport ?? vi.fn();
  const wrapper = mount(ProjectDesignPackagePanel, {
    global: {
      plugins: [createAppI18n(options.locale ?? "en")],
      stubs: { ProjectDevelopmentPanel: true, ProjectAcceptanceTestsPanel: true },
    },
    props: {
      projectId: PROJECT_ID,
      stages: options.stages ?? STAGES,
      locale: options.locale ?? "en",
      authorize: (operation) => operation("access-token"),
      api,
      saveExport,
    },
    slots: options.preview === undefined ? {} : { preview: options.preview },
    attachTo: document.body,
  });
  return { wrapper, saveExport };
}

describe("ProjectDesignPackagePanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    const design = useDesignStore();
    design.$patch({ projectId: PROJECT_ID, current: SELECTED_DESIGN_VERSION });
    const modeling = useUserModelingStore();
    modeling.$patch({
      projectId: PROJECT_ID,
      twinVersions: [twin("Receptionist"), twin("Manager")],
    });
  });

  it("summarises the approved path, the chosen design with its mockup and the twins", async () => {
    const { wrapper } = mountPanel(knowledgeApi());
    await flushPromises();

    const stages = wrapper.findAll('[data-testid="package-stage"]');
    expect(stages).toHaveLength(5);
    expect(stages[0]?.text()).toContain("1. Brief");
    expect(stages[0]?.text()).toContain("version 2");
    expect(stages[0]?.text()).toContain("approved");
    expect(wrapper.get('[data-testid="package-alternative"]').text()).toContain(
      SELECTED_DESIGN_VERSION.package.alternatives[0]?.title ?? "",
    );
    expect(wrapper.findComponent({ name: "DeclarativePrototypePreview" }).exists()).toBe(true);
    expect(wrapper.findAll('[data-testid="package-twin"]').map((item) => item.text())).toEqual([
      "Receptionist",
      "Manager",
    ]);
    expect(spoken(wrapper.get('[data-testid="package-summary"]'))).toContain(
      "2 twins, each in its own reusable file Receptionist, Manager",
    );
    expect(spoken(stages[0]!)).toBe("1. Brief version 2 · approved");
    expect(wrapper.findAll('[data-testid="package-step"]')).toHaveLength(4);
    wrapper.unmount();
  });

  it("puts the main action in the panel of the ready project, not in a decision bar", async () => {
    const { wrapper } = mountPanel(knowledgeApi(), { locale: "it" });
    await flushPromises();

    const hero = wrapper.get('[data-testid="package-hero"]');
    expect(hero.get("h2").text()).toBe("Il progetto è pronto");
    expect(hero.get('[data-testid="download-package"]').text()).toBe(
      "Prepara e scarica la cartella",
    );
    expect(hero.get('[data-testid="download-package"]').attributes("data-variant")).toBe("pill");
    expect(hero.get('[data-testid="package-latest"]').text()).toBe("54 file · versione 1");
    expect(wrapper.find('[data-testid="decision-bar"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="agent-message"]').text()).toContain(
      "Ho raccolto i cinque passi approvati",
    );
    expect(wrapper.get('[data-testid="package-path"]').attributes("open")).toBeUndefined();
    expect(wrapper.get('[data-testid="design-package"]').attributes("data-surface")).toBe("night");
    wrapper.unmount();
  });

  it("lists the versions already prepared and what the latest one contains", async () => {
    const api = knowledgeApi({
      history: vi.fn(() =>
        Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), version(1)] }),
      ),
    });
    const { wrapper } = mountPanel(api, { locale: "it" });
    await flushPromises();

    const versions = wrapper.findAll('[data-testid="package-version"]');
    expect(api.history).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(
      wrapper.findAll('[data-testid="package-version-title"]').map((item) => item.text()),
    ).toEqual(["Versione 2", "Versione 1"]);
    expect(versions[0]!.text()).toContain("54 file");
    expect(
      wrapper.findAll('[data-testid="package-version-progress"]').map((item) => item.text()),
    ).toEqual(["5 passi su 5", "5 passi su 5"]);
    expect(versions[0]!.get("button").attributes("aria-label")).toBe("Scarica la versione 2");
    expect(wrapper.get('[data-testid="package-history"] details summary').text()).toBe(
      "Versioni precedenti (1)",
    );
    const contents = spoken(wrapper.get('[data-testid="package-contents"]'));
    expect(contents).toContain("7 diagrammi di requisiti e design");
    expect(contents).toContain("14 tabelle di requisiti e design");
    expect(contents).toContain("44 osservazioni dei twin sul design scelto");
    expect(contents).toContain("5 revisioni dei twin · 2 tue decisioni · 6 discussioni approvate");
    expect(spoken(wrapper.get('[data-testid="package-summary"]'))).toContain(
      "2 twin, ciascuno in un file riutilizzabile",
    );
    expect(wrapper.find('[data-testid="package-counted-later"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("uses the singular words for a single item", async () => {
    const single = {
      ...version(1),
      diagram_count: 1,
      table_count: 1,
      feedback: {
        reviews: 1,
        findings: 1,
        decisions: 0,
        discussions: 0,
        insights: 0,
        change_reviews: 0,
      },
    };
    useUserModelingStore().$patch({ twinVersions: [twin("Receptionist")] });
    const api = knowledgeApi({
      history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [single] })),
    });
    const { wrapper } = mountPanel(api, { locale: "it" });
    await flushPromises();

    const summary = spoken(wrapper.get('[data-testid="package-summary"]'));
    expect(summary).toContain("1 twin, in un file riutilizzabile");
    expect(summary).toContain("1 diagramma di requisiti e design");
    expect(summary).toContain("1 tabella di requisiti e design");
    expect(summary).toContain("1 osservazione dei twin sul design scelto");
    wrapper.unmount();
  });

  it("prepares a new version and downloads it", async () => {
    const api = knowledgeApi();
    const { wrapper, saveExport } = mountPanel(api);
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(api.publish).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(api.download).toHaveBeenCalledWith(PROJECT_ID, 2, "access-token");
    expect(saveExport).toHaveBeenCalledTimes(1);
    expect(saveExport).toHaveBeenCalledWith(
      expect.any(Blob),
      `orchestwin-${PROJECT_ID}-knowledge-v2.zip`,
    );
    expect(wrapper.get('[data-testid="download-done"]').text()).toBe(
      `Version 2 of the folder is ready and downloaded: orchestwin-${PROJECT_ID}-knowledge-v2.zip`,
    );
    expect(
      wrapper.findAll('[data-testid="package-version-title"]').map((item) => item.text()),
    ).toEqual(["Version 2", "Version 1"]);
    expect(wrapper.get('[data-testid="package-latest"]').text()).toBe("54 files · version 2");
    wrapper.unmount();
  });

  it("says that it is preparing the folder and blocks a second request meanwhile", async () => {
    let publish: (value: KnowledgePackagePublicationPayload) => void = () => undefined;
    const api = knowledgeApi({
      publish: vi.fn(
        () =>
          new Promise<KnowledgePackagePublicationPayload>((resolve) => {
            publish = resolve;
          }),
      ),
    });
    const { wrapper } = mountPanel(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");

    const action = wrapper.get('[data-testid="download-package"]');
    expect(action.text()).toBe("Preparo la cartella…");
    expect(action.attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="download-version"]').attributes("disabled")).toBeDefined();
    await action.trigger("click");
    expect(api.publish).toHaveBeenCalledTimes(1);

    publish({ reused: false, version: version(2) });
    await flushPromises();
    expect(wrapper.get('[data-testid="download-package"]').text()).toBe(
      "Prepara e scarica la cartella",
    );
    wrapper.unmount();
  });

  it("says that nothing changed when the latest version is reused", async () => {
    const api = knowledgeApi({
      publish: vi.fn(() => Promise.resolve({ reused: true, version: version(1) })),
    });
    const { wrapper, saveExport } = mountPanel(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(saveExport).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="download-done"]').text()).toContain(
      "Non è cambiato nulla dalla versione 1",
    );
    expect(wrapper.findAll('[data-testid="package-version"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("downloads an earlier version exactly as it was", async () => {
    const api = knowledgeApi({
      history: vi.fn(() =>
        Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), version(1)] }),
      ),
    });
    const { wrapper, saveExport } = mountPanel(api);
    await flushPromises();

    await wrapper.findAll('[data-testid="download-version"]')[1]!.trigger("click");
    await flushPromises();

    expect(api.publish).not.toHaveBeenCalled();
    expect(api.download).toHaveBeenCalledWith(PROJECT_ID, 1, "access-token");
    expect(saveExport).toHaveBeenCalledWith(
      expect.any(Blob),
      `orchestwin-${PROJECT_ID}-knowledge-v1.zip`,
    );
    wrapper.unmount();
  });

  it("publishes the approved steps before the others and says which ones are missing", async () => {
    const api = knowledgeApi({
      history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [] })),
      publish: vi.fn(() => Promise.resolve({ reused: false, version: partialVersion(1) })),
    });
    const { wrapper, saveExport } = mountPanel(api, { stages: approvedUpTo(3), locale: "it" });
    await flushPromises();

    const action = wrapper.get('[data-testid="download-package"]');
    expect(action.attributes("disabled")).toBeUndefined();
    expect(spoken(wrapper.get('[data-testid="package-partial"]'))).toBe(
      "La cartella contiene 3 passi su 5: restano da approvare Requirements e Design. Ogni passo entra nella cartella quando lo approvi.",
    );
    expect(wrapper.find('[data-testid="package-not-ready"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="package-hero"] h2').text()).toBe("La cartella prende forma");
    expect(wrapper.get('[data-testid="agent-message"]').text()).toContain(
      "Raccolgo i passi approvati finora",
    );
    expect(wrapper.get('[data-testid="package-path"]').attributes("open")).toBeDefined();
    expect(wrapper.findAll('[data-testid="package-stage"]')[4]?.text()).toContain("in attesa");
    expect(wrapper.get('[data-testid="package-no-history"]').text()).toBe(
      "Non hai ancora preparato nessuna versione.",
    );
    expect(wrapper.find('[data-testid="package-contents"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="package-counted-later"]').text()).toContain(
      "si contano quando prepari la cartella",
    );
    expect(wrapper.find('[data-testid="package-latest"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="package-twin"]').map((item) => item.text())).toEqual([
      "Receptionist",
      "Manager",
    ]);
    expect(wrapper.find('[data-testid="package-design"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="package-no-design"]').text()).toContain(
      "dopo l'approvazione del passo Design",
    );

    await action.trigger("click");
    await flushPromises();

    expect(api.publish).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(saveExport).toHaveBeenCalledWith(
      expect.any(Blob),
      `orchestwin-${PROJECT_ID}-knowledge-v1.zip`,
    );
    expect(wrapper.get('[data-testid="package-latest"]').text()).toBe("27 file · versione 1");
    expect(wrapper.get('[data-testid="package-version-progress"]').text()).toBe(
      "3 passi su 5, il prossimo è Requirements",
    );
    wrapper.unmount();
  });

  it("lists only the twins that the folder holds while the twins are not approved", async () => {
    const folder: KnowledgePackageVersionPayload = {
      ...partialVersion(1),
      twins: [],
      progress: { approved: ["brief", "team"], pending: "twins", complete: false },
    };
    const api = knowledgeApi({
      history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [folder] })),
    });
    const { wrapper } = mountPanel(api, { stages: approvedUpTo(2) });
    await flushPromises();

    expect(wrapper.findAll('[data-testid="package-twin"]')).toHaveLength(0);
    expect(spoken(wrapper.get('[data-testid="package-summary"]'))).toContain(
      "0 twins, each in its own reusable file",
    );
    expect(wrapper.get('[data-testid="package-version-progress"]').text()).toBe(
      "2 of 5 steps, next: User Twins",
    );
    wrapper.unmount();
  });

  it("waits for the brief before preparing the folder", async () => {
    const api = knowledgeApi({
      history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [] })),
    });
    const { wrapper } = mountPanel(api, { stages: approvedUpTo(0), locale: "it" });
    await flushPromises();

    expect(wrapper.get('[data-testid="download-package"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="package-not-ready"]').text()).toBe(
      "La cartella si può preparare appena il brief è approvato.",
    );
    expect(wrapper.find('[data-testid="package-partial"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="package-hero"] h2').text()).toBe(
      "La cartella non è ancora pronta",
    );
    expect(wrapper.get('[data-testid="agent-message"]').text()).toContain(
      "Appena il brief è approvato",
    );
    expect(wrapper.find('[data-testid="package-terminal"]').exists()).toBe(false);
    expect(wrapper.findComponent({ name: "ProjectDevelopmentPanel" }).exists()).toBe(false);
    expect(wrapper.findComponent({ name: "ProjectAcceptanceTestsPanel" }).exists()).toBe(false);
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      4,
      "The folder holds 4 of 5 steps: Design is still to approve. Each step joins the folder when you approve it.",
    ],
    [
      "en",
      3,
      "The folder holds 3 of 5 steps: Requirements and Design are still to approve. Each step joins the folder when you approve it.",
    ],
    [
      "it",
      4,
      "La cartella contiene 4 passi su 5: resta da approvare Design. Ogni passo entra nella cartella quando lo approvi.",
    ],
    [
      "it",
      1,
      "La cartella contiene 1 passo su 5: restano da approvare Team, User Twins, Requirements e Design. Ogni passo entra nella cartella quando lo approvi.",
    ],
  ] as const)(
    "says in %s which steps a folder of %i approved steps still misses",
    async (locale, count, expected) => {
      const { wrapper } = mountPanel(knowledgeApi(), { stages: approvedUpTo(count), locale });
      await flushPromises();

      expect(spoken(wrapper.get('[data-testid="package-partial"]'))).toBe(expected);
      wrapper.unmount();
    },
  );

  it("shows the progress of an earlier partial version next to the complete one", async () => {
    const api = knowledgeApi({
      history: vi.fn(() =>
        Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), partialVersion(1)] }),
      ),
    });
    const { wrapper } = mountPanel(api);
    await flushPromises();

    expect(
      wrapper.findAll('[data-testid="package-version-progress"]').map((item) => item.text()),
    ).toEqual(["5 of 5 steps", "3 of 5 steps, next: Requirements"]);
    expect(wrapper.find('[data-testid="package-partial"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "Development goes on from the terminal: ut align checks the commits against the design and ut watch follows them.",
    ],
    [
      "it",
      "Lo sviluppo continua dal terminale: ut align confronta i commit con il design e ut watch li segue.",
    ],
  ] as const)(
    "names the commands of the terminal in %s after the versions once the design is approved",
    async (locale, expected) => {
      const { wrapper } = mountPanel(knowledgeApi(), { locale });
      await flushPromises();

      const sentence = wrapper.get('[data-testid="package-terminal"]');
      expect(spoken(sentence)).toBe(expected);
      expect(sentence.findAll("code").map((item) => item.text())).toEqual(["ut align", "ut watch"]);
      expect(
        wrapper.get('[data-testid="package-history"]').element.contains(sentence.element),
      ).toBe(true);
      wrapper.unmount();
    },
  );

  it("opens the development outside the Studio below the versions once the design is approved", async () => {
    const approved = mountPanel(knowledgeApi(), { locale: "it" });
    await flushPromises();

    const panel = approved.wrapper.findComponent({ name: "ProjectDevelopmentPanel" });
    expect(panel.exists()).toBe(true);
    expect(panel.props("projectId")).toBe(PROJECT_ID);
    expect(panel.props("locale")).toBe("it");
    const authorize = panel.props("authorize") as <T>(
      operation: (accessToken: string) => Promise<T>,
    ) => Promise<T>;
    await expect(authorize(async (accessToken) => accessToken)).resolves.toBe("access-token");
    const history = approved.wrapper.get('[data-testid="package-history"]').element;
    expect(history.compareDocumentPosition(panel.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    approved.wrapper.unmount();

    const waiting = mountPanel(knowledgeApi(), { stages: approvedUpTo(4) });
    await flushPromises();
    expect(waiting.wrapper.findComponent({ name: "ProjectDevelopmentPanel" }).exists()).toBe(false);
    expect(waiting.wrapper.find('[data-testid="package-terminal"]').exists()).toBe(false);
    waiting.wrapper.unmount();
  });

  it("shows the acceptance tests right after the development outside the Studio once the design is approved", async () => {
    const approved = mountPanel(knowledgeApi(), { locale: "it" });
    await flushPromises();

    const tests = approved.wrapper.findComponent({ name: "ProjectAcceptanceTestsPanel" });
    expect(tests.exists()).toBe(true);
    expect(tests.props("projectId")).toBe(PROJECT_ID);
    expect(tests.props("locale")).toBe("it");
    expect(tests.props("api")).toBeUndefined();
    const authorize = tests.props("authorize") as <T>(
      operation: (accessToken: string) => Promise<T>,
    ) => Promise<T>;
    await expect(authorize(async (accessToken) => accessToken)).resolves.toBe("access-token");
    const development = approved.wrapper.findComponent({ name: "ProjectDevelopmentPanel" });
    expect(development.element.nextElementSibling).toBe(tests.element);
    approved.wrapper.unmount();

    const waiting = mountPanel(knowledgeApi(), { stages: approvedUpTo(4) });
    await flushPromises();
    expect(waiting.wrapper.findComponent({ name: "ProjectAcceptanceTestsPanel" }).exists()).toBe(
      false,
    );
    waiting.wrapper.unmount();
  });

  it("shows that the versions are loading", async () => {
    const api = knowledgeApi({ history: vi.fn(() => new Promise<never>(() => undefined)) });
    const { wrapper } = mountPanel(api, { locale: "it" });
    await flushPromises();

    const history = wrapper.get('[data-testid="package-no-history"]');
    expect(history.text()).toBe("Carico le versioni…");
    expect(history.attributes("aria-busy")).toBe("true");
    wrapper.unmount();
  });

  it("explains a missing approval of the brief reported by the server and other failures", async () => {
    const refused = knowledgeApi({
      publish: vi.fn(() =>
        Promise.reject(
          new KnowledgePackagesApiError("The knowledge package request failed", {
            status: 409,
            code: "BRIEF_APPROVAL_REQUIRED",
            payload: null,
          }),
        ),
      ),
    });
    const broken = knowledgeApi({
      publish: vi.fn(() => Promise.reject(new Error("network down"))),
    });
    const first = mountPanel(refused);
    await flushPromises();
    await first.wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();
    const refusedText = first.wrapper.get('[data-testid="download-error"]').text();
    first.wrapper.unmount();
    setActivePinia(createPinia());
    const second = mountPanel(broken);
    await flushPromises();
    await second.wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(refusedText).toBe("The folder can be prepared as soon as the brief is approved.");
    expect(first.saveExport).not.toHaveBeenCalled();
    expect(second.wrapper.get('[data-testid="download-error"]').text()).toBe(
      "The folder could not be prepared.",
    );
    expect(second.wrapper.get('[data-testid="download-error"]').attributes("role")).toBe("alert");
    second.wrapper.unmount();
  });

  it("keeps the copy of a missing approval for the brief only", async () => {
    const api = knowledgeApi({
      publish: vi.fn(() =>
        Promise.reject(
          new KnowledgePackagesApiError("The knowledge package request failed", {
            status: 409,
            code: "DESIGN_APPROVAL_REQUIRED",
            payload: null,
          }),
        ),
      ),
    });
    const { wrapper } = mountPanel(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="download-error"]').text()).toBe(
      "Non è stato possibile preparare la cartella.",
    );
    wrapper.unmount();
  });

  it("explains an earlier version that cannot be downloaded", async () => {
    const api = knowledgeApi({ download: vi.fn(() => Promise.reject(new Error("offline"))) });
    const { wrapper, saveExport } = mountPanel(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="download-version"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="download-error"]').text()).toBe(
      "Non è stato possibile scaricare la cartella.",
    );
    expect(saveExport).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each([
    ["TEAM_OUTDATED", "Apri il passo Squadra"],
    ["USER_TWINS_OUTDATED", "Apri il passo User Twin"],
    ["REQUIREMENTS_OUTDATED", "aggiornali ai twin attuali"],
    ["DESIGN_OUTDATED", "rigenera le alternative"],
  ])("says which step to update when the server reports %s", async (code, expected) => {
    const api = knowledgeApi({
      publish: vi.fn(() =>
        Promise.reject(
          new KnowledgePackagesApiError("The knowledge package request failed", {
            status: 409,
            code,
            payload: null,
          }),
        ),
      ),
    });
    const { wrapper, saveExport } = mountPanel(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="download-error"]').text()).toContain(expected);
    expect(saveExport).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("shows the current declarative preview as an inert thumbnail by default", async () => {
    const { wrapper } = mountPanel(knowledgeApi());
    await flushPromises();

    const thumbnail = wrapper.get('[data-testid="package-preview-default"]');
    expect(thumbnail.attributes("inert")).toBeDefined();
    expect(thumbnail.attributes("aria-hidden")).toBe("true");
    expect(
      thumbnail.findComponent({ name: "DeclarativePrototypePreview" }).props("prototype"),
    ).toEqual(SELECTED_DESIGN_VERSION.package.prototype);
    wrapper.unmount();
  });

  it("lets the page fill the preview of the chosen design", async () => {
    const received: PreviewSlot[] = [];
    const { wrapper } = mountPanel(knowledgeApi(), {
      preview: (slot) => {
        received.push(slot);
        return h("div", { "data-testid": "generated-preview" }, slot.alternative.code);
      },
    });
    await flushPromises();

    expect(wrapper.get('[data-testid="generated-preview"]').text()).toBe("DES-001");
    expect(wrapper.find('[data-testid="package-preview-default"]').exists()).toBe(false);
    expect(received.at(-1)?.alternative.id).toBe(
      SELECTED_DESIGN_VERSION.package.owner_selected_alternative_id,
    );
    expect(received.at(-1)?.prototype).toEqual(SELECTED_DESIGN_VERSION.package.prototype);
    wrapper.unmount();
  });

  it("says when the chosen design has no preview or no design was chosen yet", async () => {
    const design = useDesignStore();
    design.$patch({
      current: {
        ...SELECTED_DESIGN_VERSION,
        package: { ...SELECTED_DESIGN_VERSION.package, prototype: null },
      },
    });
    const first = mountPanel(knowledgeApi(), { locale: "it" });
    await flushPromises();
    expect(first.wrapper.get('[data-testid="package-preview-missing"]').text()).toBe(
      "Nessuna anteprima",
    );
    first.wrapper.unmount();

    design.$patch({ current: UNSELECTED_DESIGN_VERSION });
    const second = mountPanel(knowledgeApi(), { locale: "it" });
    await flushPromises();
    expect(second.wrapper.find('[data-testid="package-design"]').exists()).toBe(false);
    expect(second.wrapper.get('[data-testid="package-no-design"]').text()).toContain(
      "dopo l'approvazione del passo Design",
    );
    second.wrapper.unmount();
  });

  it("counts the twins of the latest version when the twins are not loaded", async () => {
    useUserModelingStore().$patch({ projectId: "another-project" });
    const { wrapper } = mountPanel(knowledgeApi(), { locale: "it" });
    await flushPromises();

    expect(wrapper.findAll('[data-testid="package-twin"]').map((item) => item.text())).toEqual([
      "Addetti all'accoglienza",
    ]);
    wrapper.unmount();
  });

  it("has no axe violations", async () => {
    const { wrapper } = mountPanel(
      knowledgeApi({
        history: vi.fn(() =>
          Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), version(1)] }),
        ),
      }),
      { locale: "it" },
    );
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations while it waits for the approvals", async () => {
    const stages = STAGES.map((stage, index) => ({ ...stage, approved: index < 4 }));
    const { wrapper } = mountPanel(
      knowledgeApi({
        history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [] })),
      }),
      { stages },
    );
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
