import type { ProvidedPrototype } from "@/types/workflowInputs";

export function suppliedPrototype(values: Partial<ProvidedPrototype> = {}): ProvidedPrototype {
  return {
    id: "provided-prototype",
    code: "PRT-001",
    project_id: "project",
    version_number: 1,
    based_on_version_number: null,
    definition_reference: {
      artifact_id: "definition",
      version_number: 2,
      content_hash: "d".repeat(64),
    },
    title: "Owner prototype",
    declared_origin: "Penpot",
    visual_choices: {},
    created_at: "2026-10-03T00:00:00Z",
    content_hash: "a".repeat(64),
    mockup: {
      mockup: {
        contract_version: 1,
        design_alternative_id: "provided-prototype",
        title: "Owner prototype",
        styles: "",
        screens: [
          { code: "SCR-001", title: "Input", state: "DEFAULT", markup: "<main>Input</main>" },
          { code: "SCR-002", title: "Result", state: "SUCCESS", markup: "<main>Result</main>" },
        ],
      },
      requirement_ids_by_code: {},
    },
    ...values,
  };
}
