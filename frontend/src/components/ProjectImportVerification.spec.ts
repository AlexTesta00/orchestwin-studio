import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { ProjectImportPayload } from "../types/projectImports";
import { projectImportResult, rememberProjectImportResult } from "../stores/projectImportResults";
import ProjectImportVerification from "./ProjectImportVerification.vue";

const result: ProjectImportPayload = {
  project: {
    id: "import-verification-project",
    display_name: "Imported",
    mode: "GREENFIELD",
    created_at: "2026-10-02",
  },
  origin: {
    project_id: "origin",
    project_name: "Original",
    package_version: 1,
    package_content_hash: "hash",
    schema_version: 3,
  },
  stages: {},
  twins: [],
  imported_at: "2026-10-02",
  approval_required: ["brief", "team"],
  why_verified: true,
  import_limits: ["LEARNED_PROJECTION_NOT_RESTORED", "LEGACY_FEEDBACK_CONTEXT_MISSING"],
};

describe("Import chain verification", () => {
  it.each(["it", "en"] as const)(
    "reports the recalculation and explicit limits in %s without approving sections",
    (locale) => {
      const wrapper = mount(ProjectImportVerification, { props: { result, locale } });
      expect(wrapper.get('[data-testid="project-import-why-verified"]').text()).toContain(
        locale === "it" ? "ricalcolata" : "recalculated",
      );
      expect(wrapper.get('[data-testid="project-import-limits"]').text()).toContain(
        locale === "it" ? "non è stata ripristinata" : "was not restored",
      );
      expect(wrapper.text()).toContain(
        locale === "it"
          ? "L'import non approva le sezioni."
          : "The import does not approve the sections.",
      );
      expect(wrapper.get("details").attributes("open")).toBeUndefined();
    },
  );

  it("declares unavailable verification for missing legacy flags and keeps unknown limits visible", () => {
    const legacy = { ...result, import_limits: ["UNKNOWN_HISTORY_LIMIT"] };
    delete legacy.why_verified;
    const wrapper = mount(ProjectImportVerification, { props: { result: legacy, locale: "en" } });
    expect(wrapper.get('[data-testid="project-import-why-verified"]').text()).toContain(
      "unavailable",
    );
    expect(wrapper.get('[data-testid="project-import-limits"]').text()).toBe(
      "Some historical links are unavailable.",
    );
    expect(wrapper.get("details").text()).toContain("UNKNOWN_HISTORY_LIMIT");
    rememberProjectImportResult(result);
    expect(projectImportResult(result.project.id)).toBe(result);
    expect(projectImportResult("other-project")).toBeUndefined();
  });

  it.each(["it", "en"] as const)(
    "keeps persisted import omissions visible after a reload in %s",
    (locale) => {
      const origin = {
        origin: result.origin,
        stages: result.stages,
        imported_at: result.imported_at,
        archive_hash: "archive",
        import_limits: ["FEEDBACK_CONTEXT_NOT_RESTORED", "HYPOTHESIS_HISTORY_PARTIAL"],
        omitted_sections: [
          {
            kind: "VALIDATION_HYPOTHESIS",
            reason: "HYPOTHESIS_HISTORY_PARTIAL",
            id: "historical-hypothesis",
          },
        ],
      };
      const wrapper = mount(ProjectImportVerification, { props: { origin, locale } });
      expect(wrapper.find('[data-testid="project-import-why-verified"]').exists()).toBe(false);
      expect(wrapper.get('[data-testid="project-import-limits"]').text()).toContain(
        locale === "it" ? "versioni mancanti" : "Missing versions",
      );
      expect(wrapper.get('[data-testid="project-import-omissions"]').text()).toContain(
        locale === "it" ? "Dati omessi · 1" : "Omitted data · 1",
      );
      expect(wrapper.get("details").text()).toContain("historical-hypothesis");
      expect(wrapper.get("details").attributes("open")).toBeUndefined();
    },
  );
});
