import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ProjectImportsApiError, type ProjectImportsApi } from "@/api/projectImports";
import { expectAccessible } from "@/test/axe";
import type { ProjectImportPayload } from "@/types/projectImports";
import ProjectImportDialog from "./ProjectImportDialog.vue";

const LIMIT = 16 * 1024 * 1024;

const IMPORTED: ProjectImportPayload = {
  project: {
    id: "project-9",
    display_name: "Reception desk",
    mode: "GREENFIELD_GENERATION",
    created_at: "2026-09-27T10:00:00Z",
  },
  origin: {
    project_id: "project-1",
    project_name: "Reception desk",
    package_version: 3,
    package_content_hash: "a".repeat(64),
    schema_version: 2,
  },
  stages: {},
  twins: [{ twin_id: "twin-1", name: "Giulia" }],
  imported_at: "2026-09-27T10:00:00Z",
  approval_required: ["brief", "team", "twins", "requirements", "design"],
};

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

interface FakeImportsApi extends ProjectImportsApi {
  importArchive: Mock<ProjectImportsApi["importArchive"]>;
  origin: Mock<ProjectImportsApi["origin"]>;
}

function importsApi(): FakeImportsApi {
  return {
    importArchive: vi.fn<ProjectImportsApi["importArchive"]>(async () => IMPORTED),
    origin: vi.fn<ProjectImportsApi["origin"]>(async () => null),
  };
}

function refused(code: string, location: string | null = null, status = 422) {
  return new ProjectImportsApiError("The project import request failed", {
    status,
    code,
    payload: { detail: { code, location } },
    location,
  });
}

function archive(size?: number): File {
  const file = new File(["PK"], "orchestwin-knowledge-v3.zip", { type: "application/zip" });
  if (size !== undefined) Object.defineProperty(file, "size", { value: size });
  return file;
}

function mountDialog(api: ProjectImportsApi, locale: "en" | "it" = "it") {
  return mount(ProjectImportDialog, { props: { locale, authorize, api } });
}

async function choose(wrapper: ReturnType<typeof mountDialog>, file: File): Promise<void> {
  const input = wrapper.get('[data-testid="project-import-file"]');
  Object.defineProperty(input.element, "files", { value: [file], configurable: true });
  await input.trigger("change");
}

const submit = '[data-testid="project-import-submit"]';
const error = '[data-testid="project-import-error"]';

describe("ProjectImportDialog", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("explains the import and waits for an archive before creating the project", async () => {
    const api = importsApi();
    const wrapper = mountDialog(api);
    const file = wrapper.get('[data-testid="project-import-file"]');
    expect(file.attributes("accept")).toBe(".zip");
    expect(wrapper.get(`label[for="${file.attributes("id")}"]`).text()).toBe(
      "Trascina qui l'archivio .zip della cartella di conoscenza, oppure sceglilo dal computer.",
    );
    expect(wrapper.find('[data-testid="project-import-chosen"]').exists()).toBe(false);
    const name = wrapper.get('[data-testid="project-import-name"]');
    expect(name.attributes("maxlength")).toBe("120");
    expect(wrapper.get(`#${name.attributes("aria-describedby")}`).text()).toBe(
      "Lascialo vuoto per tenere il nome del progetto originale.",
    );
    expect(wrapper.get(submit).text()).toBe("Crea il progetto");
    expect(wrapper.get(submit).attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    expect(api.importArchive).not.toHaveBeenCalled();
    await choose(wrapper, archive());
    expect(wrapper.get(submit).attributes("disabled")).toBeUndefined();
    expect(wrapper.get('[data-testid="project-import-chosen"]').text()).toBe(
      "Archivio scelto: orchestwin-knowledge-v3.zip",
    );
    expect(wrapper.get('[data-testid="project-import-drop"]').classes()).toContain("border-solid");
  });

  it("takes an archive dropped on the area and marks the area while it is dragged", async () => {
    const api = importsApi();
    const wrapper = mountDialog(api);
    const zone = wrapper.get('[data-testid="project-import-drop"]');
    expect(zone.classes()).toContain("border-dashed");
    await zone.trigger("dragenter");
    expect(zone.attributes("data-dragging")).toBe("true");
    await zone.trigger("dragleave", { relatedTarget: null });
    expect(zone.attributes("data-dragging")).toBeUndefined();
    await zone.trigger("dragover");
    const file = archive();
    await zone.trigger("drop", { dataTransfer: { files: [file] } });
    expect(zone.attributes("data-dragging")).toBeUndefined();
    expect(wrapper.get('[data-testid="project-import-chosen"]').text()).toBe(
      "Archivio scelto: orchestwin-knowledge-v3.zip",
    );
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.importArchive).toHaveBeenCalledWith(
      file,
      "orchestwin-knowledge-v3.zip",
      null,
      "token",
    );
  });

  it("refuses a dropped archive larger than 16 MB and ignores a drop without files", async () => {
    const api = importsApi();
    const wrapper = mountDialog(api, "en");
    const zone = wrapper.get('[data-testid="project-import-drop"]');
    await zone.trigger("drop", { dataTransfer: { files: [] } });
    expect(wrapper.find(error).exists()).toBe(false);
    await zone.trigger("drop", { dataTransfer: { files: [archive(LIMIT + 1)] } });
    expect(wrapper.get(error).get("p").text()).toBe(
      "The archive is larger than 16 MB, the most the Studio accepts.",
    );
    expect(wrapper.find('[data-testid="project-import-chosen"]').exists()).toBe(false);
    expect(wrapper.get(submit).attributes("disabled")).toBeDefined();
  });

  it("ignores an archive dropped while the project is being created", async () => {
    let resolve!: (value: ProjectImportPayload) => void;
    const api = importsApi();
    api.importArchive.mockImplementationOnce(
      () =>
        new Promise<ProjectImportPayload>((done) => {
          resolve = done;
        }),
    );
    const wrapper = mountDialog(api);
    await choose(wrapper, archive());
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const zone = wrapper.get('[data-testid="project-import-drop"]');
    await zone.trigger("dragenter");
    expect(zone.attributes("data-dragging")).toBeUndefined();
    const other = new File(["PK"], "another.zip", { type: "application/zip" });
    await zone.trigger("drop", { dataTransfer: { files: [other] } });
    expect(wrapper.get('[data-testid="project-import-chosen"]').text()).toBe(
      "Archivio scelto: orchestwin-knowledge-v3.zip",
    );
    resolve(IMPORTED);
    await flushPromises();
    expect(wrapper.emitted("imported")).toEqual([[IMPORTED]]);
  });

  it("uploads the archive without a name and emits the new project", async () => {
    const api = importsApi();
    const wrapper = mountDialog(api);
    const file = archive();
    await choose(wrapper, file);
    await wrapper.get('[data-testid="project-import-name"]').setValue("   ");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.importArchive).toHaveBeenCalledWith(
      file,
      "orchestwin-knowledge-v3.zip",
      null,
      "token",
    );
    expect(wrapper.emitted("imported")).toEqual([[IMPORTED]]);
  });

  it("sends the trimmed name of the new project", async () => {
    const api = importsApi();
    const wrapper = mountDialog(api);
    const file = archive();
    await choose(wrapper, file);
    await wrapper.get('[data-testid="project-import-name"]').setValue("  Front desk 2027  ");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.importArchive).toHaveBeenCalledWith(
      file,
      "orchestwin-knowledge-v3.zip",
      "Front desk 2027",
      "token",
    );
  });

  it("refuses an archive larger than 16 MB before any request", async () => {
    const api = importsApi();
    const wrapper = mountDialog(api);
    await choose(wrapper, archive(LIMIT + 1));
    expect(wrapper.get(error).attributes("role")).toBe("alert");
    expect(wrapper.get(error).get("p").text()).toBe(
      "L'archivio supera i 16 MB, il massimo che lo Studio accetta.",
    );
    expect(wrapper.get(submit).attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    expect(api.importArchive).not.toHaveBeenCalled();
    await choose(wrapper, archive(LIMIT));
    expect(wrapper.find(error).exists()).toBe(false);
    expect(wrapper.get(submit).attributes("disabled")).toBeUndefined();
  });

  it("shows the progress and blocks the form while the project is created", async () => {
    let resolve!: (value: ProjectImportPayload) => void;
    const api = importsApi();
    api.importArchive.mockImplementationOnce(
      () =>
        new Promise<ProjectImportPayload>((done) => {
          resolve = done;
        }),
    );
    const wrapper = mountDialog(api, "en");
    await choose(wrapper, archive());
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const running = wrapper.get('[data-testid="project-import-running"]');
    expect(running.attributes("role")).toBe("status");
    expect(running.text()).toBe("Reading the folder and creating the project…");
    expect(wrapper.get(submit).attributes("disabled")).toBeDefined();
    expect(
      wrapper.get('[data-testid="project-import-cancel"]').attributes("disabled"),
    ).toBeDefined();
    expect(wrapper.get('[data-testid="project-import-file"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="project-import-name"]').attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    expect(api.importArchive).toHaveBeenCalledTimes(1);
    resolve(IMPORTED);
    await flushPromises();
    expect(wrapper.find('[data-testid="project-import-running"]').exists()).toBe(false);
    expect(wrapper.emitted("imported")).toEqual([[IMPORTED]]);
  });

  it.each([
    [
      refused("FOLDER_ARCHIVE_TOO_LARGE", null, 413),
      "L'archivio supera i 16 MB, il massimo che lo Studio accetta.",
    ],
    [
      refused("FOLDER_ARCHIVE_INVALID"),
      "Questo file non è una cartella di conoscenza dello Studio. Scegli l'archivio .zip che hai scaricato alla fine di un progetto.",
    ],
    [
      refused("FOLDER_DOCUMENT_MISSING"),
      "Mancano alcuni file della cartella, quindi non può nascerne un progetto. Esporta di nuovo la cartella dallo Studio.",
    ],
    [
      refused("FOLDER_DOCUMENT_INVALID", "design"),
      "Alcuni file della cartella non si possono leggere, quindi non può nascerne un progetto. Esporta di nuovo la cartella dallo Studio.",
    ],
    [
      refused("FOLDER_DOCUMENT_INVALID", "design: package.generated_mockup: ATTRIBUTE_FORBIDDEN"),
      "Il mockup dentro questa cartella contiene qualcosa che lo Studio non accetta, quindi la cartella non è stata importata.",
    ],
    [
      refused("FOLDER_DOCUMENT_INVALID", "design: package.alternatives"),
      "Alcuni file della cartella non si possono leggere, quindi non può nascerne un progetto. Esporta di nuovo la cartella dallo Studio.",
    ],
    [
      refused("FOLDER_SCHEMA_UNSUPPORTED"),
      "Questa cartella è stata scritta da un'altra versione dello Studio, quindi qui non si può leggere.",
    ],
    [
      refused("FOLDER_TAMPERED", "requirements/requirements.json"),
      "Il file requirements/requirements.json è stato modificato dopo l'esportazione, quindi la cartella non è affidabile.",
    ],
    [
      refused("FOLDER_TAMPERED"),
      "Un file della cartella è stato modificato dopo l'esportazione, quindi la cartella non è affidabile.",
    ],
    [
      refused("FOLDER_INCONSISTENT", "DESIGN_OUTDATED"),
      "Le parti di questa cartella non appartengono allo stesso progetto approvato, quindi non può nascerne un progetto. Esporta di nuovo la cartella dallo Studio.",
    ],
    [
      refused("PROJECT_NAME_INVALID", "display_name"),
      "Il nome del nuovo progetto non è valido. Usa al massimo 120 caratteri, oppure lascialo vuoto.",
    ],
    [
      refused("PROJECT_IMPORT_REJECTED", "design", 409),
      "Non è stato possibile creare il progetto da questa cartella. Riprova; se succede di nuovo, esporta di nuovo la cartella dallo Studio.",
    ],
    [new Error("network down"), "Non è stato possibile creare il progetto. Riprova."],
  ])("explains the failure %#", async (failure, message) => {
    const api = importsApi();
    api.importArchive.mockRejectedValueOnce(failure);
    const wrapper = mountDialog(api);
    await choose(wrapper, archive());
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const alert = wrapper.get(error);
    expect(alert.attributes("role")).toBe("alert");
    expect(alert.get("p").text()).toBe(message);
    expect(wrapper.emitted("imported")).toBeUndefined();
    expect(wrapper.get(submit).attributes("disabled")).toBeUndefined();
  });

  it("keeps the technical reason of an inconsistent folder inside the details", async () => {
    const api = importsApi();
    api.importArchive.mockRejectedValueOnce(refused("FOLDER_INCONSISTENT", "DESIGN_OUTDATED"));
    const wrapper = mountDialog(api);
    await choose(wrapper, archive());
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const alert = wrapper.get(error);
    expect(alert.get("p").text()).not.toContain("DESIGN_OUTDATED");
    expect(alert.get("details summary").text()).toBe("Dettagli");
    expect(alert.get("details code").text()).toBe("FOLDER_INCONSISTENT · DESIGN_OUTDATED");
  });

  it("says in English that a refused mockup kept the folder out and keeps the reason in the details", async () => {
    const api = importsApi();
    api.importArchive.mockRejectedValueOnce(
      refused("FOLDER_DOCUMENT_INVALID", "design: package.generated_mockup: ELEMENT_FORBIDDEN"),
    );
    const wrapper = mountDialog(api, "en");
    await choose(wrapper, archive());
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    const alert = wrapper.get(error);
    expect(alert.get("p").text()).toBe(
      "The mockup inside this folder contains something that the Studio does not accept, so the folder was not imported.",
    );
    expect(alert.get("details code").text()).toBe(
      "FOLDER_DOCUMENT_INVALID · design: package.generated_mockup: ELEMENT_FORBIDDEN",
    );
    expect(wrapper.emitted("imported")).toBeUndefined();
  });

  it("emits cancel", async () => {
    const wrapper = mountDialog(importsApi(), "en");
    const cancel = wrapper.get('[data-testid="project-import-cancel"]');
    expect(cancel.text()).toBe("Cancel");
    await cancel.trigger("click");
    expect(wrapper.emitted("cancel")).toHaveLength(1);
    expect(wrapper.emitted("imported")).toBeUndefined();
  });

  it("has no axe violations", async () => {
    const api = importsApi();
    api.importArchive.mockRejectedValueOnce(refused("FOLDER_TAMPERED", "brief/brief.json"));
    const wrapper = mountDialog(api);
    await expectAccessible(wrapper.element);
    await choose(wrapper, archive());
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.find(error).exists()).toBe(true);
    await expectAccessible(wrapper.element);
  });
});
