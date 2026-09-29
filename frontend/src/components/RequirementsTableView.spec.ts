import { mount, type VueWrapper } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { RequirementsSpecificationPayload } from "../types/requirements";
import RequirementsTableView from "./RequirementsTableView.vue";
import { expectAccessible } from "@/test/axe";

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

const RECEPTIONIST = {
  twin_id: "00000000-0000-4000-8000-000000000201",
  version_number: 1,
  content_hash: "a".repeat(64),
  name: "Receptionist Twin",
};
const MANAGER = {
  twin_id: "00000000-0000-4000-8000-000000000202",
  version_number: 1,
  content_hash: "b".repeat(64),
  name: "Manager Twin",
};

const REQUIREMENT_1 = "00000000-0000-4000-8000-000000000301";
const REQUIREMENT_2 = "00000000-0000-4000-8000-000000000302";
const REQUIREMENT_3 = "00000000-0000-4000-8000-000000000303";
const REQUIREMENT_10 = "00000000-0000-4000-8000-000000000310";
const STORY_1 = "00000000-0000-4000-8000-000000000401";
const STORY_2 = "00000000-0000-4000-8000-000000000402";
const CRITERION_1 = "00000000-0000-4000-8000-000000000501";
const CRITERION_2 = "00000000-0000-4000-8000-000000000502";
const UNKNOWN = "00000000-0000-4000-8000-000000000999";

const SPECIFICATION: RequirementsSpecificationPayload = {
  project_id: "00000000-0000-4000-8000-000000000101",
  project_brief_reference: {
    kind: "PROJECT_BRIEF",
    artifact_id: "00000000-0000-4000-8000-000000000601",
    version_number: 1,
    content_hash: "c".repeat(64),
  },
  agent_team_reference: {
    kind: "AGENT_TEAM",
    artifact_id: "00000000-0000-4000-8000-000000000602",
    version_number: 1,
    content_hash: "d".repeat(64),
  },
  user_modeling_reference: {
    kind: "USER_MODELING",
    artifact_id: "00000000-0000-4000-8000-000000000603",
    version_number: 1,
    content_hash: "e".repeat(64),
  },
  catalog_version: 1,
  catalog_content_hash: "f".repeat(64),
  user_twin_references: [RECEPTIONIST, MANAGER],
  requirements: [
    {
      id: REQUIREMENT_1,
      code: "REQ-001",
      title: "Create reservations",
      statement: "The desk can create a reservation for a guest.",
      kind: "FUNCTIONAL",
      priority: "SHOULD",
      sources: [],
      user_twin_references: [RECEPTIONIST],
    },
    {
      id: REQUIREMENT_2,
      code: "REQ-002",
      title: "Quick search",
      statement: "Search answers within one second.",
      kind: "NON_FUNCTIONAL",
      priority: "COULD",
      sources: [],
      user_twin_references: [RECEPTIONIST, MANAGER],
    },
    {
      id: REQUIREMENT_3,
      code: "REQ-003",
      title: "Data stays in Europe",
      statement: "Guest data is stored in the European Union.",
      kind: "CONSTRAINT",
      priority: "MUST",
      sources: [],
      user_twin_references: [],
    },
    {
      id: REQUIREMENT_10,
      code: "REQ-010",
      title: "Loyalty points",
      statement: "Guests collect points for every stay.",
      kind: "FUNCTIONAL",
      priority: "WONT_FOR_NOW",
      sources: [],
      user_twin_references: [MANAGER],
    },
  ],
  user_stories: [
    {
      id: STORY_2,
      code: "USR-002",
      user_twin_reference: MANAGER,
      goal: "see today's arrivals",
      benefit: "plan the shifts",
      requirement_ids: [REQUIREMENT_10, REQUIREMENT_1],
    },
    {
      id: STORY_1,
      code: "USR-001",
      user_twin_reference: RECEPTIONIST,
      goal: "book a room quickly",
      benefit: "serve the queue faster",
      requirement_ids: [REQUIREMENT_1, UNKNOWN],
    },
  ],
  acceptance_criteria: [
    {
      id: CRITERION_1,
      code: "AC-001",
      statement: "A booking is saved with the guest name.",
      verification_method: "AUTOMATED_TEST",
      requirement_ids: [REQUIREMENT_2, REQUIREMENT_1],
      user_story_ids: [STORY_2, STORY_1],
    },
    {
      id: CRITERION_2,
      code: "AC-002",
      statement: "No guest data leaves the European Union.",
      verification_method: "MANUAL_REVIEW",
      requirement_ids: [REQUIREMENT_3],
      user_story_ids: [],
    },
  ],
  scenarios: [
    {
      id: "00000000-0000-4000-8000-000000000701",
      code: "SCN-001",
      title: "Walk-in guest",
      actor: RECEPTIONIST,
      preconditions: ["The desk is open."],
      trigger: "A guest arrives without a booking",
      steps: [
        "Open the calendar on today's date",
        "Pick a free room that fits the guest",
        "Confirm the booking and hand over the key",
      ],
      expected_outcome: "The guest has a room",
      requirement_ids: [REQUIREMENT_1],
      acceptance_criterion_ids: [CRITERION_2, CRITERION_1],
    },
  ],
  risks: [
    {
      id: "00000000-0000-4000-8000-000000000801",
      code: "RSK-001",
      summary: "Double bookings at peak time",
      likelihood: "LIKELY",
      impact: "HIGH",
      mitigation: "Lock the room while it is being booked",
      requirement_ids: [REQUIREMENT_1],
      sources: [],
      review_status: "OWNER_ACKNOWLEDGED",
    },
  ],
  definition_of_done: [
    {
      id: "00000000-0000-4000-8000-000000000901",
      code: "DOD-001",
      statement: "Every requirement has a passing check.",
      verification_method: "INSPECTION",
      applicability: "REQUIRED",
      condition: null,
      requirement_ids: [REQUIREMENT_3, REQUIREMENT_1],
    },
    {
      id: "00000000-0000-4000-8000-000000000902",
      code: "DOD-002",
      statement: "The payment page is tried with a test card.",
      verification_method: "DEMONSTRATION",
      applicability: "CONDITIONAL",
      condition: "the guest pays online",
      requirement_ids: [REQUIREMENT_2],
    },
  ],
};

function mounted(
  specification: RequirementsSpecificationPayload = SPECIFICATION,
  locale: "en" | "it" = "en",
) {
  return mount(RequirementsTableView, { props: { specification, locale } });
}

function section(wrapper: VueWrapper, key: string) {
  return wrapper.get(`[data-testid="requirements-section-${key}"]`);
}

function rowsOf(wrapper: VueWrapper, key: string): string[][] {
  return section(wrapper, key)
    .findAll("tbody tr")
    .map((row) => row.findAll("th, td").map((cell) => cell.text()));
}

function rowHeaders(wrapper: VueWrapper, key: string): string[] {
  return section(wrapper, key)
    .findAll('tbody th[scope="row"]')
    .map((cell) => cell.text());
}

describe("RequirementsTableView", () => {
  it("shows the six tables in order with a heading and an explanation each", async () => {
    const wrapper = mounted();

    expect(wrapper.findAll("h2").map((heading) => heading.text())).toEqual([
      "Requirements",
      "User stories",
      "Acceptance criteria",
      "Usage scenarios",
      "Risks",
      "When the work is done",
    ]);
    expect(wrapper.findAll("caption").map((caption) => caption.text())).toEqual([
      "Requirements",
      "User stories",
      "Acceptance criteria",
      "Usage scenarios",
      "Risks",
      "When the work is done",
    ]);
    expect(section(wrapper, "requirements").get("p").text()).toContain("Each row is one thing");

    await wrapper.setProps({ locale: "it" });

    expect(wrapper.findAll("h2").map((heading) => heading.text())).toEqual([
      "Requisiti",
      "Storie degli utenti",
      "Criteri di accettazione",
      "Scenari d'uso",
      "Rischi",
      "Quando il lavoro è finito",
    ]);
    expect(section(wrapper, "risks").get("p").text()).toContain("potrebbe andare storto");
  });

  it("lists the requirements with plain words, twin names and sorted codes", () => {
    const wrapper = mounted();

    expect(
      section(wrapper, "requirements")
        .findAll("thead th")
        .map((cell) => cell.text().replace(/[↑↓↕]/u, "").trim()),
    ).toEqual([
      "Code",
      "Title",
      "Type",
      "Priority",
      "Requirement",
      "Verification",
      "For",
      "Stories",
    ]);
    expect(rowsOf(wrapper, "requirements")).toEqual([
      [
        "REQ-001",
        "Create reservations",
        "Feature",
        "Important",
        "The desk can create a reservation for a guest.",
        "AC-001",
        "Receptionist Twin",
        "USR-001\nUSR-002",
      ],
      [
        "REQ-002",
        "Quick search",
        "Quality",
        "Optional",
        "Search answers within one second.",
        "AC-001",
        "Receptionist Twin\nManager Twin",
        "—",
      ],
      [
        "REQ-003",
        "Data stays in Europe",
        "Constraint",
        "Essential",
        "Guest data is stored in the European Union.",
        "AC-002",
        "—",
        "—",
      ],
      [
        "REQ-010",
        "Loyalty points",
        "Feature",
        "For later",
        "Guests collect points for every stay.",
        "Missing",
        "Manager Twin",
        "USR-002",
      ],
    ]);
    expect(
      section(wrapper, "requirements").get('tr[data-row-key="REQ-010"] [data-missing]').classes(),
    ).toContain("text-warn");
  });

  it("keeps the table of the requirements open and the other tables closed until asked", async () => {
    const wrapper = mounted(SPECIFICATION, "it");
    const others = ["stories", "criteria", "scenarios", "risks", "done"];

    expect(section(wrapper, "requirements").element.tagName).toBe("SECTION");
    expect(section(wrapper, "requirements").get("h2").classes()).toContain("sr-only");
    expect(wrapper.text()).toContain("Altre tabelle");
    for (const key of others) {
      const details = section(wrapper, key);
      expect(details.element.tagName).toBe("DETAILS");
      expect(details.attributes("open")).toBeUndefined();
    }
    expect(section(wrapper, "stories").get("summary").text()).toContain("2 righe");
    expect(section(wrapper, "scenarios").get("summary").text()).toContain("1 riga");
    expect(section(wrapper, "risks").get("summary h2").text()).toBe("Rischi");
  });

  it("resolves every reference to a sorted code, one per line, and never shows an identifier", () => {
    const wrapper = mounted();

    expect(rowsOf(wrapper, "stories")).toEqual([
      ["USR-002", "Manager Twin", "see today's arrivals", "plan the shifts", "REQ-001\nREQ-010"],
      [
        "USR-001",
        "Receptionist Twin",
        "book a room quickly",
        "serve the queue faster",
        "REQ-001\n—",
      ],
    ]);
    expect(rowsOf(wrapper, "criteria")).toEqual([
      [
        "AC-001",
        "A booking is saved with the guest name.",
        "Automated test",
        "REQ-001\nREQ-002",
        "USR-001\nUSR-002",
      ],
      ["AC-002", "No guest data leaves the European Union.", "Manual review", "REQ-003", "—"],
    ]);
    expect(wrapper.text()).not.toMatch(UUID);
  });

  it("numbers the steps of a scenario one per line", () => {
    const wrapper = mounted();
    const steps = section(wrapper, "scenarios").get('td[data-column="steps"]');

    expect(rowsOf(wrapper, "scenarios")).toEqual([
      [
        "SCN-001",
        "Walk-in guest",
        "Receptionist Twin",
        "A guest arrives without a booking",
        "1. Open the calendar on today's date\n2. Pick a free room that fits the guest\n3. Confirm the booking and hand over the key",
        "The guest has a room",
        "REQ-001",
        "AC-001\nAC-002",
      ],
    ]);
    expect(steps.classes()).toContain("whitespace-pre-line");
  });

  it("translates risks and the definition of done, with the condition when it applies", async () => {
    const wrapper = mounted();

    expect(rowsOf(wrapper, "risks")).toEqual([
      [
        "RSK-001",
        "Double bookings at peak time",
        "Likely",
        "High",
        "Lock the room while it is being booked",
        "Confirmed by you",
        "REQ-001",
      ],
    ]);
    expect(rowsOf(wrapper, "done")).toEqual([
      [
        "DOD-001",
        "Every requirement has a passing check.",
        "Inspection",
        "Always",
        "REQ-001\nREQ-003",
      ],
      [
        "DOD-002",
        "The payment page is tried with a test card.",
        "Demonstration",
        "Only if the guest pays online",
        "REQ-002",
      ],
    ]);

    await wrapper.setProps({ locale: "it" });

    expect(rowsOf(wrapper, "requirements").map((row) => row.slice(2, 4))).toEqual([
      ["Funzionalità", "Importante"],
      ["Qualità", "Facoltativo"],
      ["Vincolo", "Essenziale"],
      ["Funzionalità", "Per il futuro"],
    ]);
    expect(rowsOf(wrapper, "requirements")[3]![5]).toBe("Mancante");
    expect(rowsOf(wrapper, "criteria").map((row) => row[2])).toEqual([
      "Test automatico",
      "Revisione manuale",
    ]);
    expect(rowsOf(wrapper, "risks")[0]!.slice(2, 6)).toEqual([
      "Probabile",
      "Alto",
      "Lock the room while it is being booked",
      "Confermato da te",
    ]);
    expect(rowsOf(wrapper, "done").map((row) => row.slice(2, 4))).toEqual([
      ["Ispezione", "Sempre"],
      ["Dimostrazione", "Solo se the guest pays online"],
    ]);
  });

  it("sorts the priority by importance instead of alphabetically", async () => {
    const wrapper = mounted();
    const sort = () => section(wrapper, "requirements").get('[data-testid="sort-priority"]');
    const priorityHeader = () =>
      section(wrapper, "requirements").get('thead th[data-column="priority"]');

    await sort().trigger("click");
    expect(priorityHeader().attributes("aria-sort")).toBe("ascending");
    expect(rowHeaders(wrapper, "requirements")).toEqual([
      "REQ-003",
      "REQ-001",
      "REQ-002",
      "REQ-010",
    ]);

    await sort().trigger("click");
    expect(priorityHeader().attributes("aria-sort")).toBe("descending");
    expect(rowHeaders(wrapper, "requirements")).toEqual([
      "REQ-010",
      "REQ-002",
      "REQ-001",
      "REQ-003",
    ]);

    await sort().trigger("click");
    expect(priorityHeader().attributes("aria-sort")).toBe("none");
    expect(rowHeaders(wrapper, "requirements")).toEqual([
      "REQ-001",
      "REQ-002",
      "REQ-003",
      "REQ-010",
    ]);
    expect(section(wrapper, "stories").find("thead button").exists()).toBe(false);
  });

  it("keeps a section with a short text when its table is empty", async () => {
    const wrapper = mounted({ ...SPECIFICATION, risks: [], scenarios: [] }, "it");

    expect(wrapper.findAll("h2")).toHaveLength(6);
    expect(section(wrapper, "risks").find("table").exists()).toBe(false);
    expect(section(wrapper, "risks").get('[data-testid="artifact-table-empty"]').text()).toBe(
      "Ancora nulla da mostrare.",
    );
    expect(section(wrapper, "scenarios").get('[data-testid="artifact-table-empty"]').text()).toBe(
      "Ancora nulla da mostrare.",
    );

    await wrapper.setProps({ locale: "en" });

    expect(section(wrapper, "risks").get('[data-testid="artifact-table-empty"]').text()).toBe(
      "Nothing to show yet.",
    );
  });

  it("has no axe violations", async () => {
    const wrapper = mounted(SPECIFICATION, "it");

    await expectAccessible(wrapper.element);
  });
});
