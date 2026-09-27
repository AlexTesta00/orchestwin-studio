import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DesignLoopApi } from "@/api/designLoop";
import { DesignLoopApiError } from "@/api/designLoop";
import { expectAccessible } from "@/test/axe";
import type {
  DesignDiscussionPayload,
  DiscussionRoundPayload,
  DiscussionStatementPayload,
  InsightApplicationPayload,
} from "@/types/designLoop";
import ProjectDesignDiscussionPanel from "./ProjectDesignDiscussionPanel.vue";

const authorize = <T>(operation: (accessToken: string) => Promise<T>) => operation("token");

function statement(
  twinId: string,
  name: string,
  stance: DiscussionStatementPayload["stance"],
  text: string,
  repliesTo: string[] = [],
  proposals: string[] = [],
): DiscussionStatementPayload {
  return {
    twin_id: twinId,
    twin_version: 1,
    twin_name: name,
    stance,
    statement: text,
    replies_to: repliesTo,
    proposals,
    grounded_on: ["user_twin.goals"],
    confidence: 0.6,
    model_generation_id: `generation-${twinId}`,
  };
}

function round(ordinal: number, ownerNote: string | null = null): DiscussionRoundPayload {
  return {
    ordinal,
    owner_note: ownerNote,
    created_at: "2026-09-26T10:00:00Z",
    content_hash: String(ordinal).repeat(64),
    statements: [
      statement(
        "twin-1",
        "Marta Rinaldi",
        "SUPPORT",
        `The guided flow keeps me calm at the desk (round ${ordinal}).`,
        [],
        ["Keep the booking summary visible"],
      ),
      statement(
        "twin-2",
        "Luca Bianchi",
        "OBJECTION",
        "Too many steps for someone who books twenty rooms a day.",
        ["twin-1"],
        ["Add a keyboard shortcut"],
      ),
    ],
    synthesis: {
      agreements: ["The confirmation screen is clear."],
      conflicts: [
        {
          topic: "Number of steps",
          positions: [
            { twin_id: "twin-1", position: "Keep the steps separate." },
            { twin_id: "twin-2", position: "Merge the steps into one screen." },
          ],
        },
      ],
      proposals: [
        {
          code: "PRP-001",
          text: "Offer an express path for frequent users.",
          target: "DESIGN",
          supported_by: ["twin-1", "twin-2"],
        },
      ],
      questions_for_owner: ["Who uses the desk at peak times?"],
      model_generation_id: `synthesis-${ordinal}`,
    },
  };
}

function reactingRound(ordinal: number): DiscussionRoundPayload {
  return {
    ...round(ordinal),
    statements: [
      {
        ...statement(
          "twin-1",
          "Marta Rinaldi",
          "CONCERN",
          "A shortcut is fine if the booking summary stays on screen.",
          ["twin-2"],
        ),
        reactions: [
          {
            twin_id: "twin-2",
            verdict: "PARTLY",
            reason: "Speed matters, but so does the summary.",
          },
        ],
      },
      {
        ...statement(
          "twin-2",
          "Luca Bianchi",
          "SUPPORT",
          "With a shortcut I can live with the separate steps.",
          ["twin-1"],
        ),
        reactions: [
          {
            twin_id: "twin-1",
            verdict: "AGREE",
            reason: "Keeping the summary visible helps me too.",
          },
          {
            twin_id: "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            verdict: "DISAGREE",
            reason: "The night shift does not need a separate flow.",
          },
        ],
      },
    ],
  };
}

function answeredRound(ordinal: number): DiscussionRoundPayload {
  const base = round(ordinal, "Pensate ai turni di notte");
  return {
    ...base,
    statements: base.statements.map((item) =>
      item.twin_id === "twin-1"
        ? { ...item, answer_to_owner: "Di notte serve lo stesso percorso rapido, con meno campi." }
        : item,
    ),
  };
}

function discussion(
  overrides: Partial<DesignDiscussionPayload> = {},
  rounds = 1,
): DesignDiscussionPayload {
  return {
    id: "discussion-1",
    project_id: "project-1",
    owner_user_id: "owner-1",
    design_version_id: "version-1",
    design_version_number: 1,
    design_content_hash: "a".repeat(64),
    alternative_id: "alternative-1",
    alternative_code: "DES-001",
    status: "OPEN",
    created_at: "2026-09-26T10:00:00Z",
    decided_at: null,
    max_rounds: 3,
    rounds: Array.from({ length: rounds }, (_item, index) => round(index + 1)),
    ...overrides,
  };
}

function fakeApi(discussions: DesignDiscussionPayload[]): DesignLoopApi {
  return {
    evaluate: vi.fn(),
    runs: vi.fn(async () => []),
    comparison: vi.fn(async () => null),
    regenerate: vi.fn(),
    applyInsight: vi.fn(),
    applications: vi.fn(async () => []),
    validations: vi.fn(async () => []),
    validate: vi.fn(),
    discussions: vi.fn(async () => discussions),
    startDiscussion: vi.fn(async () => discussion()),
    nextDiscussionRound: vi.fn(async () => discussion({}, 2)),
    decideDiscussion: vi.fn(async (_project, _id, body) =>
      discussion(
        {
          status: body.action === "APPROVE" ? "APPROVED" : "CLOSED",
          decided_at: "2026-09-26T11:00:00Z",
        },
        2,
      ),
    ),
  };
}

function apiError(status: number, code: string): DesignLoopApiError {
  return new DesignLoopApiError("failed", { status, code, payload: null });
}

function mountPanel(api: DesignLoopApi, locale: "en" | "it" = "it") {
  return mount(ProjectDesignDiscussionPanel, {
    props: {
      projectId: "project-1",
      designVersionId: "version-1",
      designContentHash: "a".repeat(64),
      twinNames: { "twin-1": "Marta Rinaldi", "twin-2": "Luca Bianchi" },
      locale,
      authorize,
      api,
    },
  });
}

describe("ProjectDesignDiscussionPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("starts a discussion with the owner's note and shows the round and the synthesis", async () => {
    const api = fakeApi([]);
    const wrapper = mountPanel(api);
    await flushPromises();
    expect(wrapper.find('[data-testid="discussion-round"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="discussion-start-button"]').text()).toBe(
      "Avvia la discussione",
    );
    await wrapper.get('[data-testid="discussion-start-note"]').setValue("  Pensate al check-in ");
    await wrapper.get('[data-testid="discussion-start-button"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.startDiscussion).mock.calls[0]?.[1]).toEqual({
      design_version_id: "version-1",
      design_content_hash: "a".repeat(64),
      locale: "it-IT",
      owner_note: "Pensate al check-in",
    });
    expect(wrapper.get('[data-testid="discussion-status"]').text()).toContain("Giro 1 di 3");
    const statements = wrapper.findAll('[data-testid="discussion-statement"]');
    expect(statements).toHaveLength(2);
    expect(statements[0]?.text()).toContain("Marta Rinaldi");
    expect(statements[0]?.get('[data-testid="discussion-stance"]').text()).toBe("Favorevole");
    expect(statements[0]?.text()).toContain("Keep the booking summary visible");
    expect(statements[1]?.get('[data-testid="discussion-stance"]').text()).toBe("Contrario");
    expect(statements[1]?.text()).toContain("risponde a Marta Rinaldi");
    const synthesis = wrapper.get('[data-testid="discussion-synthesis"]');
    expect(synthesis.text()).toContain("The confirmation screen is clear.");
    expect(synthesis.get('[data-testid="discussion-conflict"]').text()).toContain(
      "Luca Bianchi: Merge the steps into one screen.",
    );
    const proposal = synthesis.get('[data-testid="discussion-proposal"]');
    expect(proposal.text()).toContain("Offer an express path for frequent users.");
    expect(proposal.text()).toContain("Sostenuta da Marta Rinaldi e Luca Bianchi");
    expect(proposal.get('[data-testid="discussion-proposal-target"]').text()).toBe(
      "Il moderatore suggerisce di portarla nel design.",
    );
    expect(proposal.find('[data-testid="insight-apply-menu"]').exists()).toBe(true);
    expect(synthesis.text()).toContain("Who uses the desk at peak times?");
    expect(wrapper.find('[data-testid="discussion-start"]').exists()).toBe(false);
    await expectAccessible(wrapper.element);
  });

  it("shows each twin's reactions to the others and keeps the replies for rounds without them", async () => {
    const api = fakeApi([discussion({ rounds: [round(1), reactingRound(2)] })]);
    const wrapper = mountPanel(api);
    await flushPromises();
    const rounds = wrapper.findAll('[data-testid="discussion-round"]');
    const [first, second] = rounds;
    if (first === undefined || second === undefined) {
      throw new Error("The discussion rounds were not rendered");
    }
    expect(first.find('[data-testid="discussion-reactions"]').exists()).toBe(false);
    expect(
      first
        .findAll('[data-testid="discussion-statement"]')[1]
        ?.get('[data-testid="discussion-replies-to"]')
        .text(),
    ).toBe("risponde a Marta Rinaldi");
    expect(second.find('[data-testid="discussion-replies-to"]').exists()).toBe(false);
    const statements = second.findAll('[data-testid="discussion-statement"]');
    expect(statements[0]?.get('[data-testid="discussion-reactions"]').text()).toContain(
      "Reazioni agli altri twin",
    );
    const lines = statements[1]?.findAll('[data-testid="discussion-reaction"]') ?? [];
    expect(
      lines.map((line) => [
        line.get("strong").text(),
        line.get('[data-testid="discussion-verdict"]').text(),
        line.attributes("data-verdict"),
      ]),
    ).toEqual([
      ["Marta Rinaldi", "D'accordo", "AGREE"],
      ["7c9e6679", "Non d'accordo", "DISAGREE"],
    ]);
    expect(lines[0]?.text()).toContain("Keeping the summary visible helps me too.");
    expect(lines[1]?.text()).toContain("The night shift does not need a separate flow.");
    await wrapper.setProps({ locale: "en" });
    expect(second.findAll('[data-testid="discussion-verdict"]').map((chip) => chip.text())).toEqual(
      ["Partly", "Agrees", "Disagrees"],
    );
    expect(first.findAll('[data-testid="discussion-replies-to"]')[0]?.text()).toBe(
      "answers Marta Rinaldi",
    );
    await expectAccessible(wrapper.element);
  });

  it("shows a twin's answer to the owner's note after the note and before the statement", async () => {
    const api = fakeApi([discussion({ rounds: [round(1), answeredRound(2)] })]);
    const wrapper = mountPanel(api);
    await flushPromises();
    const second = wrapper.findAll('[data-testid="discussion-round"]')[1];
    const answered = second?.findAll('[data-testid="discussion-statement"]')[0];
    if (second === undefined || answered === undefined) {
      throw new Error("The answered statement was not rendered");
    }
    const answer = answered.get('[data-testid="discussion-answer-to-owner"]');
    expect(answer.text()).toContain("Risposta alla nota del proprietario");
    expect(answer.text()).toContain("Di notte serve lo stesso percorso rapido, con meno campi.");
    expect(answered.text().indexOf("Di notte serve")).toBeLessThan(
      answered.text().indexOf("The guided flow keeps me calm"),
    );
    const roundText = second.text();
    expect(second.get('[data-testid="discussion-owner-note"]').text()).toBe(
      "La tua nota: Pensate ai turni di notte",
    );
    expect(roundText.indexOf("La tua nota")).toBeLessThan(
      roundText.indexOf("Risposta alla nota del proprietario"),
    );
    await wrapper.setProps({ locale: "en" });
    expect(answered.get('[data-testid="discussion-answer-to-owner"]').text()).toContain(
      "Answer to the owner's note",
    );
    await expectAccessible(wrapper.element);
  });

  it("shows no answer block for the statements that did not answer the owner", async () => {
    const api = fakeApi([discussion({ rounds: [round(1), answeredRound(2)] })]);
    const wrapper = mountPanel(api);
    await flushPromises();
    const [first, second] = wrapper.findAll('[data-testid="discussion-round"]');
    const silent = second?.findAll('[data-testid="discussion-statement"]')[1];
    if (first === undefined || silent === undefined) {
      throw new Error("The discussion rounds were not rendered");
    }
    expect(first.find('[data-testid="discussion-owner-note"]').exists()).toBe(false);
    expect(first.find('[data-testid="discussion-answer-to-owner"]').exists()).toBe(false);
    expect(first.text()).not.toContain("Risposta alla nota del proprietario");
    expect(silent.find('[data-testid="discussion-answer-to-owner"]').exists()).toBe(false);
    expect(silent.text()).not.toContain("Risposta alla nota del proprietario");
    expect(silent.text()).toContain("Too many steps for someone who books twenty rooms a day.");
  });

  it("asks for another round with a note, then approves the synthesis", async () => {
    const api = fakeApi([discussion()]);
    const wrapper = mountPanel(api);
    await flushPromises();
    await wrapper
      .get('[data-testid="discussion-round-note"]')
      .setValue("Parlate dei turni di notte");
    await wrapper.get('[data-testid="discussion-next-round"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.nextDiscussionRound).mock.calls[0]?.slice(1, 3)).toEqual([
      "discussion-1",
      { expected_round_count: 1, owner_note: "Parlate dei turni di notte" },
    ]);
    expect(wrapper.findAll('[data-testid="discussion-round"]')).toHaveLength(2);
    expect(wrapper.get('[data-testid="discussion-status"]').text()).toContain("Giro 2 di 3");
    expect(
      (wrapper.get('[data-testid="discussion-round-note"]').element as HTMLTextAreaElement).value,
    ).toBe("");
    await wrapper.get('[data-testid="discussion-approve"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.decideDiscussion).mock.calls[0]?.slice(1, 3)).toEqual([
      "discussion-1",
      { action: "APPROVE" },
    ]);
    const status = wrapper.get('[data-testid="discussion-status"]');
    expect(status.attributes("data-status")).toBe("APPROVED");
    expect(status.text()).toContain("Hai approvato la sintesi del moderatore");
    expect(wrapper.find('[data-testid="discussion-actions"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="discussion-start-button"]').text()).toBe(
      "Avvia una nuova discussione",
    );
  });

  it("closes a discussion that used all its rounds", async () => {
    const api = fakeApi([discussion({}, 3)]);
    const wrapper = mountPanel(api, "en");
    await flushPromises();
    expect(wrapper.find('[data-testid="discussion-next-round"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="discussion-round-note"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="discussion-full"]').text()).toContain("used all the rounds");
    await wrapper.get('[data-testid="discussion-close"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.decideDiscussion).mock.calls[0]?.[2]).toEqual({ action: "CLOSE" });
    expect(wrapper.get('[data-testid="discussion-status"]').text()).toContain(
      "You closed the discussion",
    );
  });

  it("flags a discussion about an earlier version of the design", async () => {
    const api = fakeApi([discussion({ design_version_id: "version-0", design_version_number: 4 })]);
    const wrapper = mountPanel(api, "en");
    await flushPromises();
    expect(wrapper.get('[data-testid="discussion-outdated"]').text()).toContain("(version 4)");
    expect(wrapper.find('[data-testid="discussion-next-round"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="discussion-approve"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="discussion-close"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="discussion-start"]').exists()).toBe(false);
  });

  it("explains the failures in plain words and reloads after a conflict", async () => {
    const api = fakeApi([]);
    vi.mocked(api.startDiscussion)
      .mockRejectedValueOnce(apiError(503, "DESIGN_DISCUSSION_NOT_CONFIGURED"))
      .mockRejectedValueOnce(apiError(409, "DESIGN_DISCUSSION_OPEN"))
      .mockRejectedValueOnce(apiError(500, "UNEXPECTED_FAILURE"));
    const wrapper = mountPanel(api, "en");
    await flushPromises();
    await wrapper.get('[data-testid="discussion-start-button"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="discussion-notice"]').text()).toBe(
      "The language model that plays the twins is not connected, so the discussion cannot run.",
    );
    expect(vi.mocked(api.discussions)).toHaveBeenCalledTimes(1);
    await wrapper.get('[data-testid="discussion-start-button"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(api.discussions)).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="discussion-notice"]').text()).toContain(
      "A discussion is already open",
    );
    await wrapper.get('[data-testid="discussion-start-button"]').trigger("click");
    await flushPromises();
    const error = wrapper.get('[data-testid="discussion-error"]');
    expect(error.text()).toContain("The discussion could not continue. Try again.");
    expect(error.get("details code").text()).toBe("UNEXPECTED_FAILURE");
    expect(wrapper.find('[data-testid="discussion-notice"]').exists()).toBe(false);
  });

  it("reloads the discussion when it changed in the meantime", async () => {
    const api = fakeApi([discussion()]);
    vi.mocked(api.nextDiscussionRound).mockRejectedValueOnce(
      apiError(409, "DESIGN_DISCUSSION_CHANGED"),
    );
    vi.mocked(api.discussions)
      .mockResolvedValueOnce([discussion()])
      .mockResolvedValueOnce([discussion({}, 2)]);
    const wrapper = mountPanel(api, "en");
    await flushPromises();
    await wrapper.get('[data-testid="discussion-next-round"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="discussion-notice"]').text()).toContain("has been reloaded");
    expect(wrapper.findAll('[data-testid="discussion-round"]')).toHaveLength(2);
  });

  it("brings a synthesis proposal into the project and re-emits the application", async () => {
    const api = fakeApi([discussion()]);
    const application: InsightApplicationPayload = {
      id: "application-1",
      project_id: "project-1",
      owner_user_id: "owner-1",
      source_kind: "TWIN_DISCUSSION",
      source_id: "discussion:discussion-1:1:PRP-001",
      source_twin_id: null,
      text: "Offer an express path for frequent users.",
      target: "DESIGN",
      target_field: null,
      target_version_id: "version-2",
      target_version_number: 2,
      target_code: "DRK-002",
      created_at: "2026-09-26T10:00:00Z",
      content_hash: "c".repeat(64),
    };
    vi.mocked(api.applyInsight).mockResolvedValueOnce(application);
    const wrapper = mountPanel(api);
    await flushPromises();
    await wrapper
      .get('[data-testid="discussion-proposal"]')
      .get('[data-testid="insight-apply-design"]')
      .trigger("click");
    await flushPromises();
    expect(vi.mocked(api.applyInsight).mock.calls[0]?.[1]).toEqual({
      source_kind: "TWIN_DISCUSSION",
      source_id: "discussion:discussion-1:1:PRP-001",
      source_twin_id: null,
      text: "Offer an express path for frequent users.",
      target: "DESIGN",
      brief_field: null,
      mitigation: null,
    });
    expect(wrapper.emitted("applied")).toEqual([[application]]);
  });
});
