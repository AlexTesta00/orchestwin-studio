import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TwinImportsApiError, type TwinImportsApi } from "@/api/twinImports";
import { expectAccessible } from "@/test/axe";
import type {
  ImportableTwinPayload,
  TwinImportCandidatePayload,
  TwinImportPayload,
  TwinImportSourcePayload,
  TwinImportSourcesPayload,
} from "@/types/twinImports";
import TwinImportPanel from "./TwinImportPanel.vue";

const PROJECT_ID = "project-current";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

const ZETA: TwinImportCandidatePayload = {
  project_id: "project-zeta",
  project_name: "Zeta clinic",
  snapshot_version_number: 2,
  approved_at: "2026-09-24T09:30:00Z",
  twin_names: ["Sara"],
};

const ALPHA: TwinImportCandidatePayload = {
  project_id: "project-alpha",
  project_name: "Alpha hotel",
  snapshot_version_number: 3,
  approved_at: "2026-09-20T12:00:00Z",
  twin_names: ["Giulia", "Marco"],
};

const SOURCES: TwinImportSourcesPayload = { sources: [ZETA, ALPHA] };

function twin(name: string, overrides: Partial<ImportableTwinPayload> = {}): ImportableTwinPayload {
  return {
    twin_id: `twin-${name.toLowerCase()}`,
    name,
    version_number: 1,
    content_hash: "a".repeat(64),
    validation_status: "PROJECT_GROUNDED_UT",
    summary: null,
    issue: null,
    ...overrides,
  };
}

const SOURCE: TwinImportSourcePayload = {
  project_id: "project-alpha",
  project_name: "Alpha booking",
  snapshot_version_number: 3,
  approved_at: "2026-09-20T12:00:00Z",
  twins: [
    twin("Giulia", { summary: "Receptionist on the night shift" }),
    twin("Marco", { issue: "TWIN_NAME_ALREADY_USED" }),
  ],
};

const DOCUMENT = {
  schema_version: 2,
  kind: "orchestwin.user-twin",
  slug: "sara",
  origin: { project_id: "project-beta", project_name: "Beta pharmacy" },
  persona: { persona_id: "persona-sara" },
  twin: { twin_id: "twin-sara", profile: { name: "Sara" } },
};

function imported(name: string): TwinImportPayload {
  return {
    status: "TWIN_IMPORTED",
    twin: {
      twin_id: `imported-${name}`,
      version_id: `imported-${name}-v1`,
      version_number: 1,
      name,
      content_hash: "b".repeat(64),
      validation_status: "PROJECT_GROUNDED_UT",
    },
    persona: {
      persona_id: `persona-${name}`,
      version_id: `persona-${name}-v1`,
      version_number: 1,
      name,
    },
    snapshot: {
      version_id: "snapshot-4",
      version_number: 4,
      content_hash: "c".repeat(64),
      twin_count: 3,
    },
    origin: {
      project_id: "project-alpha",
      project_name: "Alpha booking",
      twin_id: "twin-giulia",
      twin_version_number: 1,
      twin_content_hash: "a".repeat(64),
      persona_id: "persona-giulia",
      persona_version_number: 2,
      persona_content_hash: "d".repeat(64),
    },
    gate_approval_required: true,
  };
}

function mediumDate(value: string, locale: "en-GB" | "it-IT"): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(value));
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

class FakeTwinImports implements TwinImportsApi {
  sources = vi.fn<TwinImportsApi["sources"]>(async () => SOURCES);
  source = vi.fn<TwinImportsApi["source"]>(async () => SOURCE);
  importFromProject = vi.fn<TwinImportsApi["importFromProject"]>(async () => imported("Giulia"));
  importDocument = vi.fn<TwinImportsApi["importDocument"]>(async () => imported("Sara"));
}

interface MountOptions {
  locale?: "en" | "it";
  readFile?: (file: File) => Promise<string>;
}

enableAutoUnmount(afterEach);

function mountPanel(api: TwinImportsApi, options: MountOptions = {}) {
  return mount(TwinImportPanel, {
    attachTo: document.body,
    props: {
      projectId: PROJECT_ID,
      locale: options.locale ?? "en",
      authorize,
      api,
      readFile: options.readFile,
    },
  });
}

type PanelWrapper = ReturnType<typeof mountPanel>;

async function openPanel(wrapper: PanelWrapper): Promise<void> {
  await wrapper.get('[data-testid="twin-import-open"]').trigger("click");
  await flushPromises();
}

async function showTwinsOf(wrapper: PanelWrapper, projectId: string): Promise<void> {
  await wrapper.get('[data-testid="twin-import-project"]').setValue(projectId);
  await wrapper.get('[data-testid="twin-import-show-twins"]').trigger("click");
  await flushPromises();
}

async function chooseTwin(wrapper: PanelWrapper, twinId: string): Promise<void> {
  await wrapper.get(`input[value="${twinId}"]`).setValue(true);
  await wrapper.get('[data-testid="twin-import-continue"]').trigger("click");
  await flushPromises();
}

async function chooseFile(wrapper: PanelWrapper, name = "twin.json"): Promise<File> {
  const input = wrapper.get('[data-testid="twin-import-file"]');
  const file = new File(["{}"], name, { type: "application/json" });
  Object.defineProperty(input.element, "files", { value: [file], configurable: true });
  await input.trigger("change");
  await flushPromises();
  return file;
}

function optionTexts(wrapper: PanelWrapper): string[] {
  return wrapper
    .findAll('[data-testid="twin-import-project"] option')
    .map((option) => option.text());
}

function focusedText(): string {
  return document.activeElement?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

describe("TwinImportPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("stays collapsed until the owner asks to choose a twin", async () => {
    const api = new FakeTwinImports();
    const wrapper = mountPanel(api);

    const title = wrapper.get("h2");
    expect(title.text()).toBe("Add a twin from another project");
    expect(title.classes()).toContain("sr-only");
    expect(wrapper.get('[data-testid="twin-import"]').attributes("data-opened")).toBe("false");
    expect(wrapper.text()).not.toContain("A twin you already refined elsewhere");
    expect(wrapper.get('[data-testid="twin-import-open"]').text()).toBe(
      "Reuse a twin from another project",
    );
    expect(wrapper.find('[data-testid="twin-import-step-1"]').exists()).toBe(false);
    expect(wrapper.find("select").exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-cancel"]').exists()).toBe(false);
    expect(api.sources).not.toHaveBeenCalled();
    expect(api.source).not.toHaveBeenCalled();

    await openPanel(wrapper);

    expect(wrapper.get('[data-testid="twin-import"]').attributes("data-opened")).toBe("true");
    expect(wrapper.get("h2").classes()).not.toContain("sr-only");
    expect(wrapper.text()).toContain(
      "A twin you already refined elsewhere can be reused here: it keeps its profile and the record of where it comes from.",
    );
  });

  it("lists the other projects with approved twins in the order given by the Studio", async () => {
    const api = new FakeTwinImports();
    const wrapper = mountPanel(api);
    await openPanel(wrapper);

    expect(api.sources).toHaveBeenCalledWith(PROJECT_ID, "token");
    expect(optionTexts(wrapper)).toEqual([
      "Choose a project",
      `Zeta clinic · 1 twin · approved on ${mediumDate(ZETA.approved_at, "en-GB")}`,
      `Alpha hotel · 2 twins · approved on ${mediumDate(ALPHA.approved_at, "en-GB")}`,
    ]);
    expect(
      wrapper
        .findAll('[data-testid="twin-import-project"] option')
        .map((option) => option.attributes("value")),
    ).toEqual(["", "project-zeta", "project-alpha"]);
    const select = wrapper.get('[data-testid="twin-import-project"]');
    expect(wrapper.get(`label[for="${select.attributes("id")}"]`).text()).toBe(
      "Your other projects",
    );
    expect(wrapper.get('[data-testid="twin-import-show-twins"]').attributes("disabled")).toBe("");
    expect(wrapper.find('[data-testid="twin-import-source-twins"]').exists()).toBe(false);
    expect(select.attributes("aria-describedby")).toBeUndefined();
    expect(wrapper.get('[data-testid="twin-import-file-alternative"]').text()).toBe(
      "or load the twin file of a knowledge folder",
    );
    expect(wrapper.find('[data-testid="twin-import-no-sources"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="twin-import-step-1"]').attributes("aria-current")).toBe(
      "step",
    );
    expect(wrapper.get('[data-testid="twin-import-step-2"]').text()).toBe("2 Choose the twin");
    expect(wrapper.get('[data-testid="twin-import-step-3"]').text()).toBe("3 Confirm");
    expect(wrapper.find('[data-testid="twin-import-open"]').exists()).toBe(false);
  });

  it("names the twins of the chosen project under the list", async () => {
    const wrapper = mountPanel(new FakeTwinImports());
    await openPanel(wrapper);
    const select = wrapper.get('[data-testid="twin-import-project"]');
    const names = () => wrapper.get('[data-testid="twin-import-source-twins"]');

    await select.setValue("project-alpha");

    expect(names().text()).toBe("Twins: Giulia, Marco");
    expect(select.attributes("aria-describedby")).toBe(names().attributes("id"));
    expect(wrapper.get('[data-testid="twin-import-show-twins"]').attributes("disabled")).toBe(
      undefined,
    );

    await select.setValue("project-zeta");

    expect(names().text()).toBe("Twin: Sara");
  });

  it("writes the projects and their twins in Italian", async () => {
    const wrapper = mountPanel(new FakeTwinImports(), { locale: "it" });
    await openPanel(wrapper);

    expect(optionTexts(wrapper)).toEqual([
      "Scegli un progetto",
      `Zeta clinic · 1 twin · approvato il ${mediumDate(ZETA.approved_at, "it-IT")}`,
      `Alpha hotel · 2 twin · approvati il ${mediumDate(ALPHA.approved_at, "it-IT")}`,
    ]);
    const select = wrapper.get('[data-testid="twin-import-project"]');
    expect(wrapper.get(`label[for="${select.attributes("id")}"]`).text()).toBe(
      "I tuoi altri progetti",
    );

    await select.setValue("project-alpha");

    expect(wrapper.get('[data-testid="twin-import-source-twins"]').text()).toBe(
      "Twin: Giulia, Marco",
    );

    await select.setValue("project-zeta");

    expect(wrapper.get('[data-testid="twin-import-source-twins"]').text()).toBe("Twin: Sara");
  });

  it("loads the twins of the chosen project, explains the unavailable ones and adds the chosen one", async () => {
    const api = new FakeTwinImports();
    const wrapper = mountPanel(api);
    await openPanel(wrapper);
    expect(focusedText()).toBe("1 Choose the project");

    await showTwinsOf(wrapper, "project-alpha");

    expect(api.source).toHaveBeenCalledWith(PROJECT_ID, "project-alpha", "token");
    expect(wrapper.get('[data-testid="twin-import-project-summary"]').text()).toBe(
      "✓ Project: Alpha hotel",
    );
    expect(focusedText()).toBe("2 Choose the twin");
    const stepTwo = wrapper.get('[data-testid="twin-import-step-2"]');
    expect(stepTwo.attributes("aria-current")).toBe("step");
    expect(wrapper.get('[data-testid="twin-import-step-1"]').attributes("aria-current")).toBe(
      undefined,
    );
    expect(stepTwo.get("legend").text()).toBe("Twins of Alpha hotel");
    const approvedOn = new Intl.DateTimeFormat("en-GB", { dateStyle: "long" }).format(
      new Date(SOURCE.approved_at),
    );
    expect(stepTwo.text()).toContain(`Approved on ${approvedOn}.`);
    const radios = wrapper.findAll('[data-testid="twin-import-twin"]');
    expect(radios.map((radio) => radio.attributes("aria-label"))).toEqual(["Giulia", "Marco"]);
    expect(radios[0]?.attributes("disabled")).toBeUndefined();
    expect(radios[1]?.attributes("disabled")).toBe("");
    const options = wrapper.findAll('[data-testid="twin-import-option"]');
    expect(options[0]?.text()).toContain("Receptionist on the night shift");
    const issue = wrapper.get('[data-testid="twin-import-issue"]');
    expect(issue.text()).toBe("Not available. This project already has a twin with this name.");
    expect(radios[1]?.attributes("aria-describedby")).toBe(issue.attributes("id"));
    expect(wrapper.find('[data-testid="twin-import-none"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="twin-import-continue"]').attributes("disabled")).toBe("");

    await chooseTwin(wrapper, "twin-giulia");

    expect(wrapper.get('[data-testid="twin-import-twin-summary"]').text()).toBe("✓ Twin: Giulia");
    expect(focusedText()).toBe("3 Confirm");
    expect(wrapper.get('[data-testid="twin-import-confirmation"]').text()).toBe(
      "Giulia will be added to this project as a new twin. Its profile stays the same and every observation keeps the note that it comes from Alpha booking. After the import you approve the twins of this project again.",
    );

    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();

    expect(api.importFromProject).toHaveBeenCalledWith(
      PROJECT_ID,
      "project-alpha",
      "twin-giulia",
      "token",
    );
    expect(api.importDocument).not.toHaveBeenCalled();
    expect(wrapper.emitted("imported")).toEqual([[imported("Giulia")]]);
    const success = wrapper.get('[data-testid="twin-import-success"]');
    expect(success.attributes("role")).toBe("status");
    expect(success.text()).toBe(
      "✓ Giulia was added. Now approve the twins again at the end of this step.",
    );
    expect(wrapper.find('[data-testid="twin-import-step-1"]').exists()).toBe(false);
    expect(focusedText()).toBe("Reuse a twin from another project");

    await openPanel(wrapper);

    expect(wrapper.find('[data-testid="twin-import-success"]').exists()).toBe(false);
    expect(
      (wrapper.get('[data-testid="twin-import-project"]').element as HTMLSelectElement).value,
    ).toBe("");
  });

  it("shows the summary of a twin only when it says more than its name", async () => {
    const api = new FakeTwinImports();
    api.source.mockResolvedValue({
      ...SOURCE,
      twins: [
        twin("Giulia", { summary: "  giulia " }),
        twin("Marco", { summary: "Marco", issue: "TWIN_NAME_ALREADY_USED" }),
        twin("Sara", { summary: "Pharmacist at the counter" }),
        twin("Luca", { summary: "   " }),
      ],
    });
    const wrapper = mountPanel(api);
    await openPanel(wrapper);
    await showTwinsOf(wrapper, "project-alpha");

    const options = wrapper.findAll('[data-testid="twin-import-option"]');
    const radios = wrapper.findAll('[data-testid="twin-import-twin"]');
    const summaries = wrapper.findAll('[id$="-summary"]');
    expect(summaries.map((summary) => summary.text())).toEqual(["Pharmacist at the counter"]);
    expect(options[0]?.text()).toBe("Giulia");
    expect(options[3]?.text()).toBe("Luca");
    expect(radios.map((radio) => radio.attributes("aria-describedby"))).toEqual([
      undefined,
      wrapper.get('[data-testid="twin-import-issue"]').attributes("id"),
      summaries[0]?.attributes("id"),
      undefined,
    ]);
  });

  it("goes back to a completed step with Change and keeps the choices", async () => {
    const api = new FakeTwinImports();
    const wrapper = mountPanel(api);
    await openPanel(wrapper);
    await showTwinsOf(wrapper, "project-alpha");
    await chooseTwin(wrapper, "twin-giulia");

    const changeTwin = wrapper.get('[data-testid="twin-import-change-twin"]');
    expect(changeTwin.text()).toBe("Change");
    expect(changeTwin.attributes("aria-label")).toBe("Change the twin");
    expect(wrapper.get('[data-testid="twin-import-change-project"]').attributes("aria-label")).toBe(
      "Change the project",
    );

    await changeTwin.trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="twin-import-step-2"]').attributes("aria-current")).toBe(
      "step",
    );
    expect((wrapper.get('input[value="twin-giulia"]').element as HTMLInputElement).checked).toBe(
      true,
    );
    expect(wrapper.find('[data-testid="twin-import-confirmation"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-change-twin"]').exists()).toBe(false);

    await wrapper.get('[data-testid="twin-import-change-project"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="twin-import-step-1"]').attributes("aria-current")).toBe(
      "step",
    );
    expect(
      (wrapper.get('[data-testid="twin-import-project"]').element as HTMLSelectElement).value,
    ).toBe("project-alpha");
    expect(wrapper.get('[data-testid="twin-import-source-twins"]').text()).toBe(
      "Twins: Giulia, Marco",
    );
    expect(wrapper.find('[data-testid="twin-import-change-project"]').exists()).toBe(false);
    expect(api.sources).toHaveBeenCalledTimes(1);

    await wrapper.get('[data-testid="twin-import-show-twins"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="twin-import-continue"]').trigger("click");
    await flushPromises();

    expect(api.source).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="twin-import-confirmation"]').text()).toContain(
      "Giulia will be added to this project as a new twin.",
    );

    await wrapper.get('[data-testid="twin-import-cancel"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="twin-import-step-1"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-open"]').exists()).toBe(true);
    expect(api.importFromProject).not.toHaveBeenCalled();
    expect(wrapper.emitted("imported")).toBeUndefined();
  });

  it("adds a twin from the file of a knowledge folder", async () => {
    const api = new FakeTwinImports();
    const readFile = vi.fn<(file: File) => Promise<string>>(async () => JSON.stringify(DOCUMENT));
    const wrapper = mountPanel(api, { readFile });
    await openPanel(wrapper);

    const input = wrapper.get('[data-testid="twin-import-file"]');
    expect(input.attributes("accept")).toBe(".json,application/json");
    expect(wrapper.get(`label[for="${input.attributes("id")}"]`).text()).toBe(
      "Twin file (twin.json)",
    );

    const file = await chooseFile(wrapper);

    expect(readFile).toHaveBeenCalledWith(file);
    expect(api.source).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="twin-import-project-summary"]').text()).toBe(
      "✓ Twin file: twin.json",
    );
    expect(wrapper.get('[data-testid="twin-import-twin-summary"]').text()).toBe(
      "✓ Sara, read from the file",
    );
    expect(wrapper.get('[data-testid="twin-import-change-project"]').attributes("aria-label")).toBe(
      "Change the file",
    );
    expect(wrapper.get('[data-testid="twin-import-confirmation"]').text()).toBe(
      "Sara will be added to this project as a new twin. Its profile stays the same and every observation keeps the note that it comes from Beta pharmacy. After the import you approve the twins of this project again.",
    );

    await wrapper.get('[data-testid="twin-import-change-twin"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="twin-import-step-1"]').attributes("aria-current")).toBe(
      "step",
    );

    await chooseFile(wrapper);
    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();

    expect(api.importDocument).toHaveBeenCalledWith(PROJECT_ID, DOCUMENT, "token");
    expect(api.importFromProject).not.toHaveBeenCalled();
    expect(wrapper.emitted("imported")).toEqual([[imported("Sara")]]);
    expect(wrapper.get('[data-testid="twin-import-success"]').text()).toContain(
      "Sara was added. Now approve the twins again at the end of this step.",
    );
  });

  it("refuses a file that is not JSON or that does not describe a twin before any request", async () => {
    const api = new FakeTwinImports();
    const readFile = vi
      .fn<(file: File) => Promise<string>>()
      .mockResolvedValueOnce("name: Sara")
      .mockResolvedValueOnce(JSON.stringify({ ...DOCUMENT, twin: { profile: {} } }))
      .mockResolvedValueOnce(JSON.stringify({ ...DOCUMENT, origin: { project_name: " " } }))
      .mockResolvedValueOnce(JSON.stringify([DOCUMENT]))
      .mockRejectedValueOnce(new Error("The file could not be read"));
    const wrapper = mountPanel(api, { readFile });
    await openPanel(wrapper);
    const error = () => wrapper.get('[data-testid="twin-import-file-error"]');

    await chooseFile(wrapper, "notes.txt");

    expect(error().attributes("role")).toBe("alert");
    expect(error().text()).toBe(
      "This file cannot be read as a twin. Choose the twin.json file of a knowledge folder.",
    );

    for (let attempt = 0; attempt < 3; attempt += 1) {
      await chooseFile(wrapper);
      expect(error().text()).toBe(
        "This file does not describe a twin: the name of the twin or of its project is missing.",
      );
    }

    await chooseFile(wrapper);

    expect(error().text()).toBe(
      "This file cannot be read as a twin. Choose the twin.json file of a knowledge folder.",
    );
    expect(readFile).toHaveBeenCalledTimes(5);
    expect(wrapper.get('[data-testid="twin-import-step-1"]').attributes("aria-current")).toBe(
      "step",
    );
    expect(wrapper.find('[data-testid="twin-import-confirmation"]').exists()).toBe(false);
    expect(api.importDocument).not.toHaveBeenCalled();
    expect(api.importFromProject).not.toHaveBeenCalled();
  });

  it("explains in Italian why a twin of the chosen project cannot be added", async () => {
    const issues = {
      TWIN_ALREADY_IMPORTED: "Questo twin è già stato aggiunto a questo progetto.",
      TWIN_NAME_ALREADY_USED: "Questo progetto ha già un twin con questo nome.",
      TWIN_LIMIT_REACHED: "Questo progetto ha già otto twin, il massimo.",
      TWIN_BELONGS_TO_PROJECT: "Questo twin viene proprio da questo progetto.",
      USER_TWINS_REQUIRED: "Questo progetto non ha ancora twin: creali prima.",
      USER_TWINS_OUTDATED:
        "Il Brief o la Squadra di questo progetto sono cambiati: prima crea di nuovo i suoi twin.",
      TWIN_DOCUMENT_UNKNOWN_REASON: "Questo twin non si può aggiungere qui.",
    };
    const api = new FakeTwinImports();
    api.source.mockResolvedValue({
      ...SOURCE,
      twins: Object.keys(issues).map((issue, index) =>
        twin(`Twin ${index}`, { twin_id: `twin-${index}`, issue }),
      ),
    });
    const wrapper = mountPanel(api, { locale: "it" });
    await openPanel(wrapper);
    await showTwinsOf(wrapper, "project-alpha");

    expect(wrapper.get("legend").text()).toBe("Twin di Alpha hotel");
    expect(
      wrapper.findAll('[data-testid="twin-import-issue"]').map((reason) => reason.text()),
    ).toEqual(Object.values(issues).map((reason) => `Non disponibile. ${reason}`));
    expect(
      wrapper
        .findAll('[data-testid="twin-import-twin"]')
        .every((radio) => radio.attributes("disabled") === ""),
    ).toBe(true);
    expect(wrapper.get('[data-testid="twin-import-none"]').text()).toBe(
      "Nessuno di questi twin si può aggiungere a questo progetto. Scegli un altro progetto.",
    );
    expect(wrapper.get('[data-testid="twin-import-continue"]').attributes("disabled")).toBe("");
  });

  it("explains in Italian why the twin could not be added and lets the owner try again", async () => {
    const failures = {
      TWIN_ALREADY_IMPORTED: "Questo twin è già stato aggiunto a questo progetto.",
      TWIN_NAME_ALREADY_USED: "Questo progetto ha già un twin con questo nome.",
      TWIN_LIMIT_REACHED: "Questo progetto ha già otto twin, il massimo.",
      TWIN_BELONGS_TO_PROJECT: "Questo twin viene proprio da questo progetto.",
      USER_TWINS_REQUIRED: "Questo progetto non ha ancora twin: creali prima.",
      USER_TWINS_OUTDATED:
        "Il Brief o la Squadra di questo progetto sono cambiati: prima crea di nuovo i suoi twin.",
      CONTEXT_CHANGED: "Nel frattempo i twin di questo progetto sono cambiati. Riprova.",
      PERSISTENCE_REJECTED: "Non è stato possibile salvare il twin. Riprova.",
      PROJECT_NOT_FOUND: "Questo progetto non si trova. Ricarica la pagina.",
      SOURCE_PROJECT_NOT_FOUND: "Quel progetto non si trova, oppure non ha ancora un brief.",
      SOURCE_TWIN_NOT_FOUND: "Quel twin non è più tra i twin approvati del suo progetto.",
      SOURCE_TWINS_NOT_APPROVED: "I twin di quel progetto non sono ancora approvati.",
      BRIEF_APPROVAL_REQUIRED: "Prima approva il Brief di questo progetto.",
      TEAM_APPROVAL_REQUIRED: "Prima approva la Squadra di questo progetto.",
      TWIN_DOCUMENT_INVALID: "Il file del twin è danneggiato o incompleto.",
      TWIN_DOCUMENT_UNSUPPORTED:
        "Il file del twin viene da un'altra versione dello Studio e non si può usare.",
      TWIN_IMPORT_REQUEST_INVALID:
        "La richiesta non è stata compresa. Ricarica la pagina e riprova.",
      TWIN_IMPORT_TOO_LARGE: "Il file del twin è troppo grande: il limite è 1 MB.",
    };
    const api = new FakeTwinImports();
    const wrapper = mountPanel(api, { locale: "it" });
    await openPanel(wrapper);
    await showTwinsOf(wrapper, "project-alpha");
    await chooseTwin(wrapper, "twin-giulia");
    const error = () => wrapper.get('[data-testid="twin-import-error"]');

    expect(wrapper.get('[data-testid="twin-import-confirmation"]').text()).toBe(
      "Il twin «Giulia» sarà aggiunto a questo progetto. Il suo profilo resta lo stesso e ogni osservazione conserva la nota che arriva da Alpha booking. Dopo l'aggiunta approvi di nuovo i twin di questo progetto.",
    );

    for (const [code, message] of Object.entries(failures)) {
      api.importFromProject.mockRejectedValueOnce(
        new TwinImportsApiError("The twin import request failed", {
          status: 409,
          code,
          payload: { detail: { code } },
        }),
      );
      await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
      await flushPromises();

      expect(error().attributes("role")).toBe("alert");
      expect(error().text()).toBe(message);
      expect(error().find("details").exists()).toBe(false);
    }

    api.importFromProject.mockRejectedValueOnce(
      new TwinImportsApiError("The twin import request failed", {
        status: 503,
        code: "TWIN_IMPORT_SERVICE_UNAVAILABLE",
        payload: null,
      }),
    );
    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();

    expect(error().get("p").text()).toBe(
      "Non è stato possibile aggiungere il twin. Riprova tra poco.",
    );
    expect(error().get("summary").text()).toBe("Dettagli");
    expect(error().get("code").text()).toBe("TWIN_IMPORT_SERVICE_UNAVAILABLE");

    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();

    expect(api.importFromProject).toHaveBeenCalledTimes(Object.keys(failures).length + 2);
    expect(api.importFromProject).toHaveBeenLastCalledWith(
      PROJECT_ID,
      "project-alpha",
      "twin-giulia",
      "token",
    );
    expect(wrapper.find('[data-testid="twin-import-error"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="twin-import-success"]').text()).toBe(
      "✓ Il twin «Giulia» è stato aggiunto. Ora approva di nuovo i twin in fondo a questo passo.",
    );
    expect(wrapper.emitted("imported")).toHaveLength(1);
  });

  it("names the twin read from a file in Italian without a participle that follows the name", async () => {
    const api = new FakeTwinImports();
    const readFile = vi.fn<(file: File) => Promise<string>>(async () => JSON.stringify(DOCUMENT));
    const wrapper = mountPanel(api, { locale: "it", readFile });
    await openPanel(wrapper);
    await chooseFile(wrapper);

    expect(wrapper.get('[data-testid="twin-import-twin-summary"]').text()).toBe(
      "✓ Twin letto dal file: Sara",
    );
    expect(wrapper.get('[data-testid="twin-import-confirmation"]').text()).toBe(
      "Il twin «Sara» sarà aggiunto a questo progetto. Il suo profilo resta lo stesso e ogni osservazione conserva la nota che arriva da Beta pharmacy. Dopo l'aggiunta approvi di nuovo i twin di questo progetto.",
    );

    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="twin-import-success"]').text()).toBe(
      "✓ Il twin «Sara» è stato aggiunto. Ora approva di nuovo i twin in fondo a questo passo.",
    );
  });

  it("explains in Italian why the twins of a project cannot be shown", async () => {
    const api = new FakeTwinImports();
    api.source
      .mockRejectedValueOnce(
        new TwinImportsApiError("The twin import request failed", {
          status: 409,
          code: "SOURCE_TWINS_NOT_APPROVED",
          payload: null,
        }),
      )
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const wrapper = mountPanel(api, { locale: "it" });
    await openPanel(wrapper);
    const error = () => wrapper.get('[data-testid="twin-import-source-error"]');

    await showTwinsOf(wrapper, "project-zeta");

    expect(error().attributes("role")).toBe("alert");
    expect(error().text()).toBe("I twin di quel progetto non sono ancora approvati.");
    expect(wrapper.get('[data-testid="twin-import-step-1"]').attributes("aria-current")).toBe(
      "step",
    );

    await wrapper.get('[data-testid="twin-import-show-twins"]').trigger("click");
    await flushPromises();

    expect(error().get("p").text()).toBe(
      "Non è stato possibile caricare i twin di quel progetto. Riprova tra poco.",
    );
    expect(error().get("summary").text()).toBe("Dettagli");
    expect(error().get("code").text()).toBe("Failed to fetch");

    await wrapper.get('[data-testid="twin-import-show-twins"]').trigger("click");
    await flushPromises();

    expect(api.source).toHaveBeenCalledTimes(3);
    expect(api.source).toHaveBeenLastCalledWith(PROJECT_ID, "project-zeta", "token");
    expect(wrapper.find('[data-testid="twin-import-source-error"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="twin-import-step-2"]').attributes("aria-current")).toBe(
      "step",
    );
  });

  it("disables the buttons and says what is happening while a request runs", async () => {
    const api = new FakeTwinImports();
    const sourceRequest = deferred<TwinImportSourcePayload>();
    const importRequest = deferred<TwinImportPayload>();
    api.source.mockReturnValueOnce(sourceRequest.promise);
    api.importFromProject.mockReturnValueOnce(importRequest.promise);
    const wrapper = mountPanel(api);
    await openPanel(wrapper);
    const status = () => wrapper.get('[data-testid="twin-import-busy"]');

    await showTwinsOf(wrapper, "project-alpha");

    expect(status().attributes("role")).toBe("status");
    expect(status().text()).toBe("Loading the twins of Alpha hotel…");
    expect(wrapper.get('[data-testid="twin-import-show-twins"]').attributes("disabled")).toBe("");
    expect(wrapper.get('[data-testid="twin-import-project"]').attributes("disabled")).toBe("");
    expect(wrapper.get('[data-testid="twin-import-file"]').attributes("disabled")).toBe("");
    expect(wrapper.get('[data-testid="twin-import-cancel"]').attributes("disabled")).toBe("");

    sourceRequest.resolve(SOURCE);
    await flushPromises();

    expect(wrapper.find('[data-testid="twin-import-busy"]').exists()).toBe(false);

    await chooseTwin(wrapper, "twin-giulia");
    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();

    expect(status().text()).toBe("Adding Giulia to this project…");
    expect(wrapper.get('[data-testid="twin-import-add"]').attributes("disabled")).toBe("");
    expect(wrapper.get('[data-testid="twin-import-change-project"]').attributes("disabled")).toBe(
      "",
    );
    expect(wrapper.get('[data-testid="twin-import-change-twin"]').attributes("disabled")).toBe("");
    expect(wrapper.get('[data-testid="twin-import-cancel"]').attributes("disabled")).toBe("");

    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    importRequest.resolve(imported("Giulia"));
    await flushPromises();

    expect(api.importFromProject).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[data-testid="twin-import-busy"]').exists()).toBe(false);
    expect(wrapper.emitted("imported")).toHaveLength(1);
  });

  it("offers only the twin file when no other project has approved twins", async () => {
    const api = new FakeTwinImports();
    api.sources.mockResolvedValue({ sources: [] });
    const wrapper = mountPanel(api);
    await openPanel(wrapper);

    expect(wrapper.get('[data-testid="twin-import-no-sources"]').text()).toBe(
      "None of your other projects has approved twins. You can still upload the file of a twin.",
    );
    expect(wrapper.find("select").exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-show-twins"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-projects-error"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-file-alternative"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-file"]').exists()).toBe(true);
    await expectAccessible(wrapper.element);
  });

  it("says in Italian that no other project has approved twins", async () => {
    const api = new FakeTwinImports();
    api.sources.mockResolvedValue({ sources: [] });
    const wrapper = mountPanel(api, { locale: "it" });
    await openPanel(wrapper);

    expect(wrapper.get('[data-testid="twin-import-no-sources"]').text()).toBe(
      "Nessun altro tuo progetto ha twin approvati. Puoi comunque caricare il file di un twin.",
    );
    expect(wrapper.find('[data-testid="twin-import-file"]').exists()).toBe(true);
  });

  it("reads the list while it opens and reads it again every time the panel opens", async () => {
    const api = new FakeTwinImports();
    const firstLoad = deferred<TwinImportSourcesPayload>();
    api.sources.mockReturnValueOnce(firstLoad.promise).mockResolvedValueOnce({ sources: [ALPHA] });
    const wrapper = mountPanel(api);

    await openPanel(wrapper);

    expect(api.sources).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="twin-import-busy"]').text()).toBe("Loading your projects…");
    expect(wrapper.find("select").exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-no-sources"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-projects-error"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="twin-import-cancel"]').attributes("disabled")).toBe("");

    firstLoad.resolve(SOURCES);
    await flushPromises();

    expect(optionTexts(wrapper)).toHaveLength(3);

    await wrapper.get('[data-testid="twin-import-cancel"]').trigger("click");
    await openPanel(wrapper);

    expect(api.sources).toHaveBeenCalledTimes(2);
    expect(optionTexts(wrapper)).toEqual([
      "Choose a project",
      `Alpha hotel · 2 twins · approved on ${mediumDate(ALPHA.approved_at, "en-GB")}`,
    ]);
  });

  it("keeps the twin file available when the list cannot be read and reads it again on request", async () => {
    const api = new FakeTwinImports();
    const retried = deferred<TwinImportSourcesPayload>();
    api.sources
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(
        new TwinImportsApiError("The twin import request failed", {
          status: 404,
          code: "PROJECT_NOT_FOUND",
          payload: null,
        }),
      )
      .mockReturnValueOnce(retried.promise);
    const wrapper = mountPanel(api);
    await openPanel(wrapper);
    const failure = () => wrapper.get('[data-testid="twin-import-projects-error"]');
    const retry = () => wrapper.get('[data-testid="twin-import-sources-retry"]');

    expect(failure().attributes("role")).toBe("alert");
    expect(failure().get("p").text()).toBe(
      "Your projects with approved twins could not be loaded. Try again, or upload the file of a twin.",
    );
    expect(failure().get("summary").text()).toBe("Details");
    expect(failure().get("code").text()).toBe("Failed to fetch");
    expect(retry().text()).toBe("Try again");
    expect(wrapper.find("select").exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-no-sources"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="twin-import-file"]').exists()).toBe(true);
    await expectAccessible(wrapper.element);

    await retry().trigger("click");
    await flushPromises();

    expect(failure().get("p").text()).toBe("This project cannot be found. Reload the page.");
    expect(failure().find("details").exists()).toBe(false);
    expect(focusedText()).toBe("1 Choose the project");

    await retry().trigger("click");

    expect(wrapper.get('[data-testid="twin-import-busy"]').text()).toBe("Loading your projects…");
    expect(wrapper.find('[data-testid="twin-import-projects-error"]').exists()).toBe(false);

    retried.resolve(SOURCES);
    await flushPromises();

    expect(api.sources).toHaveBeenCalledTimes(3);
    expect(api.sources).toHaveBeenLastCalledWith(PROJECT_ID, "token");
    expect(wrapper.find('[data-testid="twin-import-projects-error"]').exists()).toBe(false);
    expect(optionTexts(wrapper)).toHaveLength(3);
    expect(focusedText()).toBe("1 Choose the project");
  });

  it("explains in Italian that the list cannot be read and offers to try again", async () => {
    const api = new FakeTwinImports();
    api.sources.mockRejectedValueOnce(
      new TwinImportsApiError("The twin import request failed", {
        status: 503,
        code: "TWIN_IMPORT_SOURCES_UNAVAILABLE",
        payload: null,
      }),
    );
    const wrapper = mountPanel(api, { locale: "it" });
    await openPanel(wrapper);
    const failure = wrapper.get('[data-testid="twin-import-projects-error"]');

    expect(failure.get("p").text()).toBe(
      "Non è stato possibile caricare i tuoi progetti con twin approvati. Riprova, oppure carica il file di un twin.",
    );
    expect(failure.get("summary").text()).toBe("Dettagli");
    expect(failure.get("code").text()).toBe("TWIN_IMPORT_SOURCES_UNAVAILABLE");
    expect(wrapper.get('[data-testid="twin-import-sources-retry"]').text()).toBe("Riprova");
  });

  it("is accessible in every step", async () => {
    const api = new FakeTwinImports();
    const wrapper = mountPanel(api, { locale: "it" });

    await expectAccessible(wrapper.element);
    await openPanel(wrapper);
    await expectAccessible(wrapper.element);
    await wrapper.get('[data-testid="twin-import-project"]').setValue("project-alpha");
    await expectAccessible(wrapper.element);
    await showTwinsOf(wrapper, "project-alpha");
    await expectAccessible(wrapper.element);
    await chooseTwin(wrapper, "twin-giulia");
    api.importFromProject.mockRejectedValueOnce(
      new TwinImportsApiError("The twin import request failed", {
        status: 500,
        code: null,
        payload: null,
      }),
    );
    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="twin-import-error"] code').text()).toBe("HTTP_500");
    await expectAccessible(wrapper.element);
    await wrapper.get('[data-testid="twin-import-add"]').trigger("click");
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
