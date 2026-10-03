import { createPinia, setActivePinia } from "pinia";
import { h, type VNode } from "vue";

import { flushPromises, mount } from "@vue/test-utils";

import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDesignPackagePanel from "./ProjectDesignPackagePanel.vue";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import { SELECTED_DESIGN_VERSION, UNSELECTED_DESIGN_VERSION } from "@/test/designFixtures";
import { suppliedPrototype } from "@/test/workflowInputsFixtures";
import type { ProvidedPrototype } from "@/types/workflowInputs";

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
  { label: "Perspectives", version: 1, approved: true },
  { label: "User Twin", version: 1, approved: true },
  { label: "Definition", version: 3, approved: true },
  { label: "Design & Evaluation", version: 1, approved: true },
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

function commands(
  wrapper: ReturnType<typeof mountPanel>["wrapper"],
  step: "package-cli-step" | "package-development-step",
): string[] {
  return wrapper
    .findAll(`[data-testid="${step}"] [data-testid="command-text"]`)
    .map((item) => item.text());
}

function namedFolder(name: string): KnowledgePackagesApi {
  return knowledgeApi({
    history: vi.fn(() =>
      Promise.resolve({
        project_id: PROJECT_ID,
        versions: [{ ...version(1), project_name: name }],
      }),
    ),
  });
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
  studioAddress?: string;
  sectionsMode?: boolean;
  providedPrototype?: ProvidedPrototype;
  providedDesignApproved?: boolean;
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
      ...(options.studioAddress === undefined ? {} : { studioAddress: options.studioAddress }),
      ...(options.sectionsMode === undefined ? {} : { sectionsMode: options.sectionsMode }),
      ...(options.providedPrototype === undefined
        ? {}
        : { providedPrototype: options.providedPrototype }),
      ...(options.providedDesignApproved === undefined
        ? {}
        : { providedDesignApproved: options.providedDesignApproved }),
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

  it.each(["it", "en"] as const)(
    "exports the supplied Design with declared origin and %s limits without suggesting code generation",
    async (locale) => {
      const api = knowledgeApi();
      const { wrapper } = mountPanel(api, {
        locale,
        providedPrototype: suppliedPrototype({ project_id: PROJECT_ID }),
        providedDesignApproved: true,
      });
      await flushPromises();
      const supplied = wrapper.get('[data-testid="package-provided-design"]');
      expect(supplied.text()).toContain("Penpot");
      expect(supplied.text()).toContain(
        locale === "it"
          ? "La valutazione dei twin sul prototipo fornito non è disponibile nello sprint 36."
          : "Twin evaluation of the supplied prototype is unavailable in sprint 36.",
      );
      expect(wrapper.find('[data-testid="package-no-design"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="package-development-steps"]').exists()).toBe(false);
      expect(wrapper.findComponent({ name: "ProjectDevelopmentPanel" }).exists()).toBe(false);
      expect(commands(wrapper, "package-cli-step")).toContain(
        `ut init --project ${PROJECT_ID} --mode design`,
      );
      const limits = wrapper.get('[data-testid="package-provided-limits"]');
      expect(
        limits.findAll('[data-testid="command-text"]').map((command) => command.text()),
      ).toEqual(["ut design show", "ut design open"]);
      expect(api.publish).not.toHaveBeenCalled();
      wrapper.unmount();
    },
  );

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
      "La cartella contiene 3 passi su 5: restano da approvare Definition e Design & Evaluation. Ogni passo entra nella cartella quando lo approvi.",
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
    expect(wrapper.get('[data-testid="package-no-design"]').text()).toBe(
      "Il design scelto compare qui dopo l'approvazione di Design e valutazione.",
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
      "3 passi su 5, il prossimo è Definition",
    );
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
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
      "2 of 5 steps, next: User Twin",
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
      "The folder holds 4 of 5 steps: Design & Evaluation is still to approve. Each step joins the folder when you approve it.",
    ],
    [
      "en",
      3,
      "The folder holds 3 of 5 steps: Definition and Design & Evaluation are still to approve. Each step joins the folder when you approve it.",
    ],
    [
      "it",
      4,
      "La cartella contiene 4 passi su 5: resta da approvare Design & Evaluation. Ogni passo entra nella cartella quando lo approvi.",
    ],
    [
      "it",
      1,
      "La cartella contiene 1 passo su 5: restano da approvare Perspectives, User Twin, Definition e Design & Evaluation. Ogni passo entra nella cartella quando lo approvi.",
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
    ).toEqual(["5 of 5 steps", "3 of 5 steps, next: Definition"]);
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

  function refusing(code: string): KnowledgePackagesApi {
    return knowledgeApi({
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
  }

  it.each([
    [
      "it",
      "USER_TWINS_OUTDATED",
      "User Twin è rimasta indietro: usa «Aggiorna e conferma» in cima alla pagina, poi pubblica di nuovo.",
    ],
    [
      "it",
      "REQUIREMENTS_OUTDATED",
      "Definizione è rimasta indietro: usa «Aggiorna e conferma» in cima alla pagina, poi pubblica di nuovo.",
    ],
    [
      "it",
      "DESIGN_OUTDATED",
      "Design e valutazione è rimasta indietro: usa «Aggiorna e conferma» in cima alla pagina, poi pubblica di nuovo.",
    ],
    [
      "it",
      "TEAM_OUTDATED",
      "Il brief è cambiato: prepara di nuovo le prospettive, poi pubblica di nuovo.",
    ],
    [
      "en",
      "USER_TWINS_OUTDATED",
      "User Twin is behind: use «Update and confirm» at the top of the page, then publish again.",
    ],
    [
      "en",
      "REQUIREMENTS_OUTDATED",
      "Definition is behind: use «Update and confirm» at the top of the page, then publish again.",
    ],
    [
      "en",
      "DESIGN_OUTDATED",
      "Design & Evaluation is behind: use «Update and confirm» at the top of the page, then publish again.",
    ],
    [
      "en",
      "TEAM_OUTDATED",
      "The brief changed: prepare the perspectives again, then publish again.",
    ],
  ] as const)(
    "says in %s what to do in sections mode when the server reports %s, without regenerating",
    async (locale, code, expected) => {
      const { wrapper, saveExport } = mountPanel(refusing(code), { locale, sectionsMode: true });
      await flushPromises();

      await wrapper.get('[data-testid="download-package"]').trigger("click");
      await flushPromises();

      const error = wrapper.get('[data-testid="download-error"]');
      expect(error.text()).toBe(expected);
      expect(error.text()).not.toMatch(/rigenera|regenerate|squadra|team/i);
      expect(saveExport).not.toHaveBeenCalled();
      expect(wrapper.emitted("sections-changed")).toBeUndefined();
      wrapper.unmount();
    },
  );

  it.each([
    [
      "it",
      "USER_TWINS_OUTDATED",
      "Il passo User Twin è rimasto indietro: aprilo e aggiornalo, poi pubblica di nuovo.",
    ],
    [
      "it",
      "DESIGN_OUTDATED",
      "Il passo Design e valutazione è rimasto indietro: aprilo e aggiornalo, poi pubblica di nuovo.",
    ],
    [
      "en",
      "REQUIREMENTS_OUTDATED",
      "The Definition step is behind: open it and bring it up to date, then publish again.",
    ],
    [
      "en",
      "TEAM_OUTDATED",
      "The brief changed: prepare the perspectives again, then publish again.",
    ],
  ] as const)(
    "says in %s what to do before the first pass is complete when the server reports %s",
    async (locale, code, expected) => {
      const { wrapper } = mountPanel(refusing(code), { locale });
      await flushPromises();

      await wrapper.get('[data-testid="download-package"]').trigger("click");
      await flushPromises();

      const error = wrapper.get('[data-testid="download-error"]');
      expect(error.text()).toBe(expected);
      expect(error.text()).not.toMatch(
        /Aggiorna e conferma|Update and confirm|rigenera|regenerate/,
      );
      wrapper.unmount();
    },
  );

  it.each([
    [
      "it",
      "Ho raccolto le cinque sezioni approvate in una cartella pronta per i tuoi strumenti di sviluppo.",
      "Le cinque sezioni sono approvate. La cartella raccoglie brief, prospettive, twin, requisiti e design scelto in forma di testo, tabelle e diagrammi.",
      "Le sezioni e le loro versioni",
      ["5 sezioni su 5", "3 sezioni su 5, la prossima è Definition"],
    ],
    [
      "en",
      "I gathered the five approved sections into a folder ready for your development tools.",
      "The five sections are approved. The folder holds the brief, the perspectives, the twins, the requirements and the chosen design as text, tables and diagrams.",
      "The sections and their versions",
      ["5 of 5 sections", "3 of 5 sections, next: Definition"],
    ],
  ] as const)(
    "speaks in %s of sections once the first pass is complete",
    async (locale, agent, intro, path, progress) => {
      const api = knowledgeApi({
        history: vi.fn(() =>
          Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), partialVersion(1)] }),
        ),
      });
      const { wrapper } = mountPanel(api, { locale, sectionsMode: true });
      await flushPromises();

      expect(wrapper.get('[data-testid="agent-message"]').text()).toContain(agent);
      expect(spoken(wrapper.get('[data-testid="package-hero"]'))).toContain(intro);
      expect(spoken(wrapper.get('[data-testid="package-path"] summary'))).toBe(path);
      expect(
        wrapper.findAll('[data-testid="package-version-progress"]').map((item) => item.text()),
      ).toEqual(progress);
      expect(wrapper.text()).not.toMatch(/\bpass[oi]\b|\bsteps?\b/);
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "it",
      "La cartella contiene 3 sezioni su 5: restano da approvare Definition e Design & Evaluation. Ogni sezione entra nella cartella quando la approvi.",
    ],
    [
      "en",
      "The folder holds 3 of 5 sections: Definition and Design & Evaluation are still to approve. Each section joins the folder when you approve it.",
    ],
  ] as const)(
    "says in %s which sections a partial folder still misses",
    async (locale, expected) => {
      const { wrapper } = mountPanel(knowledgeApi(), {
        stages: approvedUpTo(3),
        locale,
        sectionsMode: true,
      });
      await flushPromises();

      expect(spoken(wrapper.get('[data-testid="package-partial"]'))).toBe(expected);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "it",
      "I cinque passi sono approvati. La cartella raccoglie brief, prospettive, twin, requisiti e design scelto in forma di testo, tabelle e diagrammi.",
      "La cartella raccoglierà brief, prospettive, twin, requisiti e design scelto in forma di testo, tabelle e diagrammi.",
    ],
    [
      "en",
      "The five steps are approved. The folder holds the brief, the perspectives, the twins, the requirements and the chosen design as text, tables and diagrams.",
      "The folder will hold the brief, the perspectives, the twins, the requirements and the chosen design as text, tables and diagrams.",
    ],
  ] as const)(
    "names in %s the perspectives among what the folder holds",
    async (locale, complete, waiting) => {
      const ready = mountPanel(knowledgeApi(), { locale });
      await flushPromises();
      expect(spoken(ready.wrapper.get('[data-testid="package-hero"]'))).toContain(complete);
      expect(ready.wrapper.text()).not.toMatch(/squadra|\bteam\b/i);
      ready.wrapper.unmount();

      const empty = mountPanel(knowledgeApi(), { locale, stages: approvedUpTo(0) });
      await flushPromises();
      expect(spoken(empty.wrapper.get('[data-testid="package-hero"]'))).toContain(waiting);
      empty.wrapper.unmount();
    },
  );

  it("tells the page about a new folder only after a publication", async () => {
    const download = mountPanel(
      knowledgeApi({
        history: vi.fn(() =>
          Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), version(1)] }),
        ),
      }),
    );
    await flushPromises();
    await download.wrapper.findAll('[data-testid="download-version"]')[1]!.trigger("click");
    await flushPromises();
    expect(download.wrapper.emitted("sections-changed")).toBeUndefined();

    await download.wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();
    expect(download.wrapper.emitted("sections-changed")).toHaveLength(1);
    download.wrapper.unmount();
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
    expect(second.wrapper.get('[data-testid="package-no-design"]').text()).toBe(
      "Il design scelto compare qui dopo l'approvazione di Design e valutazione.",
    );
    second.wrapper.unmount();

    const english = mountPanel(knowledgeApi());
    await flushPromises();
    expect(english.wrapper.get('[data-testid="package-no-design"]').text()).toBe(
      "The chosen design appears here once Design & Evaluation is approved.",
    );
    english.wrapper.unmount();
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

  it("gives the commands that bring the project into Visual Studio Code from the terminal", async () => {
    const { wrapper } = mountPanel(knowledgeApi(), {
      locale: "it",
      studioAddress: "https://studio.example.org",
    });
    await flushPromises();

    expect(wrapper.get('[data-testid="package-howto"] h2').text()).toBe("Come usarla");
    const title = wrapper.get('[data-testid="package-cli-title"]');
    expect(title.element.tagName).toBe("H3");
    expect(spoken(title)).toBe("Dal terminale, con ut");
    expect(title.get("code").text()).toBe("ut");
    expect(wrapper.get('[data-testid="package-cli-steps"]').element.tagName).toBe("OL");
    const steps = wrapper.findAll('[data-testid="package-cli-step"]');
    expect(steps.map((step) => spoken(step.get('[data-testid="package-cli-text"]')))).toEqual([
      "Accedi allo Studio dal terminale. Serve una volta sola su questo computer.",
      "Crea una cartella vuota per il progetto ed entraci.",
      "Collega la cartella a questo progetto: ut scarica qui la cartella di conoscenza.",
      "Apri la cartella in Visual Studio Code: il pannello OrchesTwin mostra lo stato del progetto e lancia gli stessi comandi.",
    ]);
    expect(steps[2]!.get('[data-testid="package-cli-text"] code').text()).toBe("ut");
    expect(commands(wrapper, "package-cli-step")).toEqual([
      "ut login --studio https://studio.example.org",
      "mkdir lista-ospiti-workshop; cd lista-ospiti-workshop",
      `ut init --project ${PROJECT_ID} --mode design-code`,
      "code .",
    ]);
    expect(
      steps.map((step) => step.get('[data-testid="command-copy"]').attributes("aria-label")),
    ).toEqual([
      "Copia: ut login --studio https://studio.example.org",
      "Copia: mkdir lista-ospiti-workshop; cd lista-ospiti-workshop",
      `Copia: ut init --project ${PROJECT_ID} --mode design-code`,
      "Copia: code .",
    ]);
    expect(steps.map((step) => step.get('[data-testid="command-copy"]').text())).toEqual([
      "Copia",
      "Copia",
      "Copia",
      "Copia",
    ]);
    wrapper.unmount();
  });

  it("gives the same commands in English with the address of the page by default", async () => {
    const { wrapper } = mountPanel(knowledgeApi());
    await flushPromises();

    expect(spoken(wrapper.get('[data-testid="package-cli-title"]'))).toBe(
      "From the terminal, with ut",
    );
    expect(wrapper.findAll('[data-testid="package-cli-text"]').map((item) => spoken(item))).toEqual(
      [
        "Log in to the Studio from the terminal. You need this only once on this computer.",
        "Create an empty folder for the project and go into it.",
        "Link the folder to this project: ut downloads the knowledge folder here.",
        "Open the folder in Visual Studio Code: the OrchesTwin panel shows the state of the project and runs the same commands.",
      ],
    );
    expect(commands(wrapper, "package-cli-step")).toEqual([
      `ut login --studio ${window.location.origin}`,
      "mkdir lista-ospiti-workshop; cd lista-ospiti-workshop",
      `ut init --project ${PROJECT_ID} --mode design-code`,
      "code .",
    ]);
    const first = wrapper.get('[data-testid="command-copy"]');
    expect(first.text()).toBe("Copy");
    expect(first.attributes("aria-label")).toBe(
      `Copy: ut login --studio ${window.location.origin}`,
    );
    wrapper.unmount();
  });

  it.each([
    ["it", "  Caffè & Città — Prenotazioni 2026!  ", "caffe-citta-prenotazioni-2026"],
    ["en", "L'Agenda dell'Università: ÈLITE", "l-agenda-dell-universita-elite"],
    [
      "it",
      "Gestione delle prenotazioni per il menu del giorno",
      "gestione-delle-prenotazioni-per-il-menu",
    ],
    ["it", "¿¡!? — …", "progetto"],
    ["en", "", "project"],
  ] as const)("names the folder in %s after the project %j", async (locale, name, folder) => {
    const { wrapper } = mountPanel(namedFolder(name), { locale });
    await flushPromises();

    expect(commands(wrapper, "package-cli-step")[1]).toBe(`mkdir ${folder}; cd ${folder}`);
    wrapper.unmount();
  });

  it.each([
    ["it", "progetto"],
    ["en", "project"],
  ] as const)(
    "names the folder in %s %s while no version of the folder is known",
    async (locale, folder) => {
      const api = knowledgeApi({
        history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [] })),
      });
      const { wrapper } = mountPanel(api, { locale });
      await flushPromises();

      expect(commands(wrapper, "package-cli-step")[1]).toBe(`mkdir ${folder}; cd ${folder}`);
      wrapper.unmount();
    },
  );

  it.each([
    [
      "it",
      "Poi, durante lo sviluppo",
      [
        "Metti la cartella sotto git: ut align lavora sui commit.",
        "Fai scrivere l'applicazione al tuo agente di programmazione, con requisiti e design come contesto.",
        "Verifica i criteri di accettazione nei browser di questo computer (con --url se l'applicazione ha un suo indirizzo).",
        "Fai esaminare i commit ai twin e riallinea codice, design e requisiti.",
        "Fai proporre ai twin che cosa hanno imparato dallo sviluppo.",
        "Guarda a che punto è il progetto.",
      ],
    ],
    [
      "en",
      "Then, during development",
      [
        "Put the folder under git: ut align works on the commits.",
        "Have your coding agent write the application, with the requirements and the design as context.",
        "Check the acceptance criteria in the browsers of this computer (with --url if the application has an address of its own).",
        "Have the twins review the commits and bring code, design and requirements back in line.",
        "Have the twins propose what they learned from the development.",
        "See where the project stands.",
      ],
    ],
  ] as const)(
    "lists in %s the commands of the development once the design is approved",
    async (locale, title, sentences) => {
      const { wrapper } = mountPanel(knowledgeApi(), { locale });
      await flushPromises();

      const heading = wrapper.get('[data-testid="package-development-title"]');
      expect(heading.element.tagName).toBe("H3");
      expect(heading.text()).toBe(title);
      const items = wrapper.findAll('[data-testid="package-development-step"]');
      expect(
        items.map((item) => spoken(item.get('[data-testid="package-development-text"]'))),
      ).toEqual(sentences);
      expect(commands(wrapper, "package-development-step")).toEqual([
        "git init",
        "ut code",
        "ut test --static .",
        "ut align",
        "ut twins update",
        "ut status",
      ]);
      expect(items[0]!.get('[data-testid="package-development-text"] code').text()).toBe(
        "ut align",
      );
      expect(items[2]!.get('[data-testid="package-development-text"] code').text()).toBe("--url");
      wrapper.unmount();
    },
  );

  it("hides the commands of the development while the design is not approved", async () => {
    const { wrapper } = mountPanel(knowledgeApi(), { stages: approvedUpTo(4), locale: "it" });
    await flushPromises();

    expect(wrapper.findAll('[data-testid="package-cli-step"]')).toHaveLength(4);
    expect(wrapper.find('[data-testid="package-development-title"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="package-development-steps"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="command-line"]')).toHaveLength(4);
    wrapper.unmount();
  });

  it.each([
    [
      "it",
      "Senza ut: scarica lo zip",
      [
        "Scarica la cartella con il pulsante qui sopra ed estraila nel tuo progetto, in una cartella chiamata orchestwin.",
        "Apri ORCHESTWIN.md: è l'indice e spiega ogni file.",
        "Realizza il progetto con i tuoi strumenti. Requisiti, schermate ed elementi hanno codici stabili da citare nel lavoro.",
        "Quando lo scopo cambia, torna nello Studio, approva la nuova versione e scarica di nuovo la cartella.",
      ],
    ],
    [
      "en",
      "Without ut: download the zip",
      [
        "Download the folder with the button above and extract it into your project, in a folder named orchestwin.",
        "Open ORCHESTWIN.md: it is the index and explains every file.",
        "Build with your own tools. Requirements, screens and elements have stable codes to quote in your work.",
        "When the scope changes, come back to the Studio, approve the new version and download the folder again.",
      ],
    ],
  ] as const)(
    "keeps in %s the steps of the zip in a collapsed block after the commands",
    async (locale, summary, steps) => {
      const { wrapper } = mountPanel(knowledgeApi(), { locale });
      await flushPromises();

      const zip = wrapper.get('[data-testid="package-zip"]');
      expect(zip.element.tagName).toBe("DETAILS");
      expect(zip.attributes("open")).toBeUndefined();
      expect(spoken(zip.get("summary"))).toBe(summary);
      expect(zip.get("summary code").text()).toBe("ut");
      expect(
        zip
          .findAll('[data-testid="package-step"]')
          .map((step) => step.get("span:last-child").text()),
      ).toEqual(steps);
      const development = wrapper.get('[data-testid="package-development-steps"]').element;
      expect(
        development.compareDocumentPosition(zip.element) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      wrapper.unmount();
    },
  );

  it("copies a command with the clipboard of the browser and says so", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    try {
      const { wrapper } = mountPanel(knowledgeApi(), { locale: "it" });
      await flushPromises();

      const link = wrapper.findAll('[data-testid="package-cli-step"]')[2]!;
      await link.get('[data-testid="command-copy"]').trigger("click");
      await flushPromises();

      expect(writeText).toHaveBeenCalledWith(`ut init --project ${PROJECT_ID} --mode design-code`);
      expect(link.get('[data-testid="command-copy"]').text()).toBe("Copiato");
      expect(link.get('[data-testid="command-status"]').text()).toBe("Copiato");
      wrapper.unmount();
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("says when a command could not be copied", async () => {
    const { wrapper } = mountPanel(knowledgeApi());
    await flushPromises();

    const login = wrapper.findAll('[data-testid="package-cli-step"]')[0]!;
    await login.get('[data-testid="command-copy"]').trigger("click");
    await flushPromises();

    expect(login.get('[data-testid="command-copy"]').text()).toBe("Could not copy");
    expect(login.get('[data-testid="command-status"]').text()).toBe("Could not copy");
    expect(login.get('[data-testid="command-text"]').text()).toBe(
      `ut login --studio ${window.location.origin}`,
    );
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
