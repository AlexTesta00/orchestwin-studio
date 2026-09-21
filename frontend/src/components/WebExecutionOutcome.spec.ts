import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { ExecutionJourney } from "@/api/executionLaunch";
import type {
  WebBrowserEvidencePayload,
  WebExecutionAttemptPayload,
  WebExecutionReportPayload,
  WebPhaseResultPayload,
} from "@/types/webExecution";
import WebExecutionOutcome from "./WebExecutionOutcome.vue";

function phase(
  name: WebPhaseResultPayload["phase"],
  status: WebPhaseResultPayload["status"],
  findings: WebPhaseResultPayload["findings"] = [],
): WebPhaseResultPayload {
  return {
    phase: name,
    status,
    command_plan_hashes: [],
    started_at: null,
    completed_at: null,
    exit_codes: [],
    stdout_refs: [],
    stderr_refs: [],
    artifact_refs: [],
    findings,
    failure_category: status === "FAILED" ? "BROWSER" : null,
    failure_code: status === "FAILED" ? "WEB_BROWSER_CHECKS_FAILED" : null,
    normalized_summary: "",
  };
}

function report(status: "PASSED" | "FAILED", failed: WebPhaseResultPayload | null = null) {
  const phases = [
    phase("VALIDATE", "PASSED"),
    phase("SETUP", "SKIPPED"),
    phase("TEST", failed?.phase === "TEST" ? "FAILED" : "PASSED"),
    phase("RUN", failed ? "NOT_RUN" : "PASSED"),
    phase("BROWSER_EVIDENCE", failed?.phase === "BROWSER_EVIDENCE" ? "FAILED" : "PASSED"),
  ].map((item) => (failed && item.phase === failed.phase ? failed : item));
  return {
    source_revision_content_hash: "a".repeat(64),
    source_tree_hash: "b".repeat(64),
    profile_id: "web.static",
    profile_version: "1.0.0",
    runner_image_digest: "c".repeat(64),
    policy_content_hash: "d".repeat(64),
    status,
    phase_results: phases,
    failure_signatures:
      status === "FAILED"
        ? [
            {
              category: "BROWSER",
              phase: "BROWSER_EVIDENCE",
              profile_id: "web.static",
              profile_version: "1.0.0",
              failure_code: "WEB_BROWSER_CHECKS_FAILED",
              normalized_message: "WEB BROWSER CHECKS FAILED",
              subject_refs: ["#ELM-003"],
              digest: "e".repeat(64),
            },
          ]
        : [],
  } as WebExecutionReportPayload;
}

const execution = {
  id: "execution",
  source_revision: { revision_id: "source" },
} as unknown as WebExecutionAttemptPayload;

const journey: ExecutionJourney = {
  status: "DERIVED",
  source_revision_id: "source",
  declared_routes: [],
  browser_interactions: [],
  steps: [
    {
      action: { kind: "fill", selector: "#ELM-002", value: "Giulia Verdi" },
      element_code: "ELM-002",
      element_label: "Nome ospite",
      screen_code: "SCR-001",
      screen_title: "Inserimento",
    },
    {
      action: { kind: "press", selector: "#ELM-003", value: "Enter" },
      element_code: "ELM-003",
      element_label: "Aggiungi",
      screen_code: "SCR-001",
      screen_title: "Inserimento",
    },
  ],
};

const browserEvidence = {
  routes: [{ route: { route_id: "root", path: "/" }, status: "COLLECTED", failure_code: null }],
} as unknown as WebBrowserEvidencePayload;

describe("web execution outcome", () => {
  it("explains accessibility findings in plain Italian with the design labels", () => {
    const failed = phase("BROWSER_EVIDENCE", "FAILED", [
      {
        code: "AXE_COLOR_CONTRAST",
        message: "Ensure the contrast meets WCAG 2 AA",
        source_tool: "axe-core",
        location: "#ELM-003",
      },
      {
        code: "AXE_PAGE_HAS_HEADING_ONE",
        message: "Ensure the page has a level-one heading",
        source_tool: "axe-core",
        location: "html",
      },
    ]);
    const wrapper = mount(WebExecutionOutcome, {
      props: {
        locale: "it",
        execution,
        report: report("FAILED", failed),
        browserEvidence,
        journey,
      },
      slots: { repair: ({ signature }) => `RIPARA ${signature.digest.slice(0, 4)}` },
    });
    const text = wrapper.text();
    expect(text).toContain("Testo poco leggibile");
    expect(text).toContain("«Aggiungi» (SCR-001)");
    expect(text).toContain("Manca il titolo principale");
    expect(text).toContain("l’intera pagina");
    expect(text).toContain("Compila «Nome ospite» con «Giulia Verdi»");
    expect(text).toContain("Percorso completato");
    expect(text).toContain("Browser e accessibilità");
    expect(text).toContain("fallito");
    expect(text).toContain("RIPARA eeee");
    expect(text).not.toContain("sha256");
  });

  it("shows a success banner in English and no repair action", () => {
    const wrapper = mount(WebExecutionOutcome, {
      props: { locale: "en", execution, report: report("PASSED"), browserEvidence, journey: null },
      slots: { repair: () => "REPAIR" },
    });
    expect(wrapper.text()).toContain("Execution passed");
    expect(wrapper.text()).toContain("Automated tests");
    expect(wrapper.text()).not.toContain("REPAIR");
  });

  it("falls back to a generic card when the failed phase has no findings", () => {
    const wrapper = mount(WebExecutionOutcome, {
      props: {
        locale: "it",
        execution,
        report: report("FAILED", phase("TEST", "FAILED")),
        browserEvidence: null,
        journey: { ...journey, source_revision_id: "other" },
      },
    });
    expect(wrapper.text()).toContain("I test automatici non passano");
    expect(wrapper.text()).not.toContain("Percorso nel browser");
  });
});
