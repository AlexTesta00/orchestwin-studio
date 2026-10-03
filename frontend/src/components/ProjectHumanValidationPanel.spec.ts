import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectHumanValidationPanel from "./ProjectHumanValidationPanel.vue";
import { HumanValidationApiError, type HumanValidationApi } from "../api/humanValidation";
import type { ResearchEvidenceApi } from "../api/researchEvidence";
import {
  operationalHypothesis,
  validationCandidate,
  validationDocument,
  validationOutcome,
  validationOverview,
  validationSource,
  VALIDATION_QUOTE,
  VALIDATION_SOURCE_ID,
} from "../test/humanValidationFixtures";
import type { HumanValidationOverview, OperationalHypothesis } from "../types/humanValidation";
import { expectAccessible } from "../test/axe";

const wrappers: { unmount: () => void }[] = [];
afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount();
  wrappers.length = 0;
});

function clients(initial = validationOverview()) {
  let current = initial;
  const api = {
    overview: vi.fn<HumanValidationApi["overview"]>(async () => current),
    walkthrough: vi.fn<HumanValidationApi["walkthrough"]>(),
    createHypothesis: vi.fn<HumanValidationApi["createHypothesis"]>(async () => {
      current = validationOverview({
        hypotheses: [operationalHypothesis()],
        summary: { ...current.summary, hypotheses: 1, to_verify: 1 },
      });
      return { status: "HYPOTHESIS_SAVED", hypothesis: operationalHypothesis() };
    }),
    reviseHypothesis: vi.fn<HumanValidationApi["reviseHypothesis"]>(async () => {
      const previous = operationalHypothesis({ current: false, outcomes: [validationOutcome()] });
      const revised = operationalHypothesis({
        version_number: 2,
        based_on_version_number: 1,
        task: "Nuovo compito scelto",
        content_hash: "d".repeat(64),
      });
      current = validationOverview({
        hypotheses: [previous, revised],
        outcomes: [validationOutcome()],
        summary: { ...current.summary, hypotheses: 1, to_verify: 1 },
      });
      return { status: "HYPOTHESIS_REVISED", hypothesis: revised };
    }),
    recordOutcome: vi.fn<HumanValidationApi["recordOutcome"]>(async () => {
      const outcome = validationOutcome();
      current = validationOverview({
        hypotheses: [operationalHypothesis({ outcomes: [outcome] })],
        outcomes: [outcome],
        summary: { ...current.summary, hypotheses: 1, to_verify: 1 },
        empirical_summary: { human_session_outcomes: 0, synthetic_exercise_outcomes: 1 },
      });
      return { status: "VALIDATION_OUTCOME_RECORDED", outcome };
    }),
  };
  const evidence = {
    list: vi.fn<ResearchEvidenceApi["list"]>(async () => ({
      project_id: "project",
      evidence: [validationSource()],
    })),
    show: vi.fn<ResearchEvidenceApi["show"]>(async () => ({
      ...validationSource(),
      text: VALIDATION_QUOTE,
    })),
    add: vi.fn(),
    revise: vi.fn(),
    retire: vi.fn(),
    deleteText: vi.fn(),
    propose: vi.fn(),
    decide: vi.fn(),
  };
  const why = { document: vi.fn(async () => validationDocument()), explain: vi.fn() };
  return {
    api,
    evidence,
    why,
    set: (value: HumanValidationOverview) => {
      current = value;
    },
  };
}

function panel(client = clients(), props: Record<string, unknown> = {}) {
  const wrapper = mount(ProjectHumanValidationPanel, {
    attachTo: document.body,
    props: {
      projectId: "project",
      authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
      locale: "it",
      api: client.api,
      evidenceApi: client.evidence,
      whyApi: client.why,
      ...props,
    },
  });
  wrappers.push(wrapper);
  return { wrapper, client };
}

async function completeHypothesis(wrapper: ReturnType<typeof panel>["wrapper"]) {
  await wrapper.get('[data-testid="validation-twin"]').setValue("twin");
  await wrapper.get('[data-testid="validation-scenario"]').setValue("scenario");
  await wrapper.get('[data-testid="validation-design"]').setValue("design");
  await wrapper
    .get('[data-testid="validation-task"]')
    .setValue("Calcolare 2 + 2 senza indicazioni");
  await wrapper
    .get('[data-testid="validation-observe"]')
    .setValue("Individuazione del risultato\nRichiesta di aiuto");
  await wrapper
    .get('[data-testid="validation-limitations"]')
    .setValue("Compito scelto dal proprietario, da verificare");
}

function withHypothesis(hypothesis: OperationalHypothesis = operationalHypothesis()) {
  return validationOverview({
    hypotheses: [hypothesis],
    outcomes: hypothesis.outcomes ?? [],
    summary: {
      hypotheses: 1,
      to_verify: 1,
      confirmed: 0,
      refuted: 0,
      uncertain: 0,
      contested: 0,
      retired_outcomes: 0,
    },
  });
}

describe("Web human validation", () => {
  it("reads only when active and keeps the candidate count separate from persisted hypotheses", async () => {
    const many = Array.from({ length: 47 }, (_, index) =>
      validationCandidate({ key: `candidate-${index}` }),
    );
    const { wrapper, client } = panel(
      clients(validationOverview({ candidates: many, candidate_count: 47 })),
      { active: false },
    );
    await flushPromises();
    expect(client.api.overview).not.toHaveBeenCalled();
    await wrapper.setProps({ active: true });
    await flushPromises();
    expect(wrapper.get('[data-testid="validation-candidate-count"]').text()).toBe("47");
    expect(wrapper.findAll('[data-testid="validation-candidate"]')).toHaveLength(0);
    expect(wrapper.text()).toContain("Nessuna ipotesi operativa salvata.");
    await wrapper.get('[data-testid="validation-show-candidates"]').trigger("click");
    expect(wrapper.findAll('[data-testid="validation-candidate"]')).toHaveLength(3);
    await wrapper.get('[data-testid="validation-show-all"]').trigger("click");
    expect(wrapper.findAll('[data-testid="validation-candidate"]')).toHaveLength(47);
    expect(client.api.createHypothesis).not.toHaveBeenCalled();
    expect(client.api.recordOutcome).not.toHaveBeenCalled();
    await wrapper.setProps({ active: false });
    await wrapper.setProps({ active: true });
    await flushPromises();
    expect(client.api.overview).toHaveBeenCalledTimes(1);
    await wrapper.setProps({ refreshKey: "source-retired" });
    await flushPromises();
    expect(client.api.overview).toHaveBeenCalledTimes(2);
  });

  it("saves only an explicitly selected candidate with owner task and exact graph choices", async () => {
    const { wrapper, client } = panel();
    await flushPromises();
    await wrapper.get('[data-testid="validation-show-candidates"]').trigger("click");
    await wrapper.get('[data-testid="validation-select-candidate"]').trigger("click");
    expect(
      (wrapper.get('[data-testid="validation-question"]').element as HTMLTextAreaElement).value,
    ).toBe("");
    expect(
      (wrapper.get('[data-testid="validation-task"]').element as HTMLTextAreaElement).value,
    ).toBe("");
    await wrapper.get('[data-testid="validation-hypothesis-form"]').trigger("submit");
    expect(client.api.createHypothesis).not.toHaveBeenCalled();
    await completeHypothesis(wrapper);
    await wrapper.get('[data-testid="validation-hypothesis-form"]').trigger("submit");
    await flushPromises();
    expect(client.api.createHypothesis).toHaveBeenCalledWith(
      "project",
      {
        candidate_key: "origin",
        twin_key: "twin",
        scenario_key: "scenario",
        design_key: "design",
        alternative_id: "alternative-id",
        anchor_keys: [],
        question: null,
        task: "Calcolare 2 + 2 senza indicazioni",
        observe: ["Individuazione del risultato", "Richiesta di aiuto"],
        limitations: "Compito scelto dal proprietario, da verificare",
      },
      "token",
    );
    expect(wrapper.get('[data-testid="validation-hypothesis-state"]').text()).toBe("Da verificare");
    expect(client.evidence.propose).not.toHaveBeenCalled();
  });

  it("revises against the exact base and leaves prior version outcomes in history", async () => {
    const { wrapper, client } = panel(clients(withHypothesis()));
    await flushPromises();
    await wrapper.get('[data-testid="validation-revise-hypothesis"]').trigger("click");
    await wrapper.get('[data-testid="validation-task"]').setValue("Nuovo compito scelto");
    await wrapper.get('[data-testid="validation-hypothesis-form"]').trigger("submit");
    await flushPromises();
    expect(client.api.reviseHypothesis).toHaveBeenCalledWith(
      "project",
      operationalHypothesis().id,
      expect.objectContaining({
        based_on_version_number: 1,
        based_on_content_hash: operationalHypothesis().content_hash,
        task: "Nuovo compito scelto",
      }),
      "token",
    );
    expect(wrapper.get('[data-testid="validation-history"]').text()).toContain(
      "Versione precedente 1",
    );
    expect(wrapper.get('[data-testid="validation-history"]').text()).toContain(VALIDATION_QUOTE);
    expect(wrapper.get('[data-testid="validation-hypothesis"]').text()).toContain("Esiti · 0");
    expect(wrapper.get('[data-testid="validation-hypothesis-state"]').text()).toBe("Da verificare");
  });

  it("requires a compatible existing source and an anonymised session code, preserving exact quote", async () => {
    const { wrapper, client } = panel(clients(withHypothesis()));
    await flushPromises();
    await wrapper.get('[data-testid="validation-record-outcome"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Nessuna fonte attiva con testo disponibile");
    expect(wrapper.find('[data-testid="validation-original-text"]').exists()).toBe(false);
    await wrapper.get('[data-testid="validation-session-kind"]').setValue("SYNTHETIC_EXERCISE");
    await wrapper.get('[data-testid="validation-source"]').setValue(`${VALIDATION_SOURCE_ID}:1`);
    expect(wrapper.text()).toContain(validationSource().method);
    expect(wrapper.text()).toContain(validationSource().context);
    await wrapper.get('[data-testid="validation-show-original"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="validation-original-text"]').text()).toContain(
      "Prova sintetica",
    );
    await wrapper.get('[data-testid="validation-session-ref"]').setValue("Participant name");
    await wrapper.get('[data-testid="validation-outcome-quote"]').setValue(VALIDATION_QUOTE);
    await wrapper
      .get('[data-testid="validation-outcome-limitations"]')
      .setValue("Non empirica; nessuna persona coinvolta");
    await wrapper.get('[data-testid="validation-outcome-form"]').trigger("submit");
    expect(client.api.recordOutcome).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="validation-session-ref"]').setValue("SYN-001");
    await wrapper.get('[data-testid="validation-outcome-form"]').trigger("submit");
    await flushPromises();
    expect(client.api.recordOutcome).toHaveBeenCalledWith(
      "project",
      expect.objectContaining({
        hypothesis_id: operationalHypothesis().id,
        hypothesis_version_number: 1,
        hypothesis_content_hash: operationalHypothesis().content_hash,
        session_kind: "SYNTHETIC_EXERCISE",
        outcome: "UNCERTAIN",
        coverage: "PARTIAL",
        evidence_id: VALIDATION_SOURCE_ID,
        evidence_version: 1,
        quote: VALIDATION_QUOTE,
        line: 1,
      }),
      "token",
    );
    expect(wrapper.get('[data-testid="validation-empirical-summary"]').text()).toContain(
      "Esiti attivi da sessioni con persone: 0",
    );
    expect(wrapper.get('[data-testid="validation-hypothesis-state"]').text()).toBe("Da verificare");
    expect(client.evidence.propose).not.toHaveBeenCalled();
    expect(client.evidence.decide).not.toHaveBeenCalled();
  });

  it("keeps the revision base while the owner explicitly chooses a current replacement for an old origin", async () => {
    const candidate = validationCandidate({
      key: "current-origin",
      origin: { ...validationCandidate().origin, key: "current-origin" },
    });
    const { wrapper, client } = panel(clients({ ...withHypothesis(), candidates: [candidate] }));
    await flushPromises();
    await wrapper.get('[data-testid="validation-revise-hypothesis"]').trigger("click");
    expect(wrapper.get('[data-testid="validation-revision-selection"]').text()).toContain(
      "nuova versione dell'ipotesi",
    );
    expect(client.api.reviseHypothesis).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="validation-select-candidate"]').trigger("click");
    await wrapper
      .get('[data-testid="validation-task"]')
      .setValue("Compito aggiornato scelto dal proprietario");
    await wrapper.get('[data-testid="validation-hypothesis-form"]').trigger("submit");
    await flushPromises();
    expect(client.api.reviseHypothesis).toHaveBeenCalledWith(
      "project",
      operationalHypothesis().id,
      expect.objectContaining({
        candidate_key: "current-origin",
        based_on_version_number: 1,
        based_on_content_hash: operationalHypothesis().content_hash,
      }),
      "token",
    );
    expect(client.api.createHypothesis).not.toHaveBeenCalled();
  });

  it("retains retired outcomes and their quote while displaying the hypothesis as to verify", async () => {
    const outcome = validationOutcome({
      effective_status: "RETIRED",
      source_text_available: false,
    });
    const { wrapper, client } = panel(
      clients(withHypothesis(operationalHypothesis({ outcomes: [outcome] }))),
    );
    await flushPromises();
    expect(wrapper.get('[data-testid="validation-retired-outcome"]').text()).toBe("Esito ritirato");
    expect(
      (
        wrapper.get('[data-testid="validation-quote"]').element as HTMLElement
      ).textContent?.trimStart(),
    ).toBe(VALIDATION_QUOTE.trimStart());
    expect(wrapper.text()).toContain("Fonte senza testo originale");
    expect(wrapper.get('[data-testid="validation-hypothesis-state"]').text()).toBe("Da verificare");
    await wrapper.get('[data-testid="validation-return-evidence"]').trigger("click");
    expect(wrapper.emitted("open-evidence")).toEqual([[{ id: VALIDATION_SOURCE_ID, version: 1 }]]);
    expect(client.api.recordOutcome).not.toHaveBeenCalled();
  });

  it("shows conflicting and partial outcomes without merging owner decisions or synthetic exercises", async () => {
    const outcomes = [
      validationOutcome({
        session_kind: "HUMAN_SESSION",
        session_ref: "SES-001",
        outcome: "CONFIRMED",
        coverage: "COMPLETE",
      }),
      validationOutcome({
        id: "another",
        code: "HVO-002",
        session_kind: "HUMAN_SESSION",
        session_ref: "SES-002",
        outcome: "REFUTED",
      }),
      validationOutcome({ id: "software", code: "HVO-003" }),
    ];
    const { wrapper } = panel(
      clients(
        validationOverview({
          hypotheses: [
            operationalHypothesis({
              state: "CONTESTED",
              conflicting_outcomes: true,
              partial_evidence: true,
              outcomes,
            }),
          ],
          outcomes,
          empirical_summary: { human_session_outcomes: 2, synthetic_exercise_outcomes: 1 },
        }),
      ),
      { locale: "en" },
    );
    await flushPromises();
    expect(wrapper.get('[data-testid="validation-hypothesis-state"]').text()).toBe(
      "Conflicting outcomes",
    );
    expect(wrapper.text()).toContain("Partial evidence");
    expect(wrapper.findAll('[data-session-kind="HUMAN_SESSION"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-session-kind="SYNTHETIC_EXERCISE"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("Synthetic exercise, not empirical");
    expect(wrapper.text()).not.toContain("OWNER_CONFIRMED");
  });

  it("reports a stale write and preserves the owner draft without silent reanchoring", async () => {
    const { wrapper, client } = panel();
    await flushPromises();
    await wrapper.get('[data-testid="validation-show-candidates"]').trigger("click");
    await wrapper.get('[data-testid="validation-select-candidate"]').trigger("click");
    await completeHypothesis(wrapper);
    client.api.createHypothesis.mockRejectedValueOnce(
      new HumanValidationApiError("changed", {
        status: 409,
        code: "VALIDATION_CONTEXT_CHANGED",
        payload: null,
      }),
    );
    await wrapper.get('[data-testid="validation-hypothesis-form"]').trigger("submit");
    await flushPromises();
    expect(wrapper.get('[data-testid="validation-error"]').text()).toContain(
      "Il contesto è cambiato",
    );
    expect(
      (wrapper.get('[data-testid="validation-task"]').element as HTMLTextAreaElement).value,
    ).toBe("Calcolare 2 + 2 senza indicazioni");
    expect(client.api.createHypothesis).toHaveBeenCalledTimes(1);
  });

  it("exposes labelled controls and keyboard details in both languages", async () => {
    const { wrapper } = panel();
    await flushPromises();
    await wrapper.get('[data-testid="validation-show-candidates"]').trigger("click");
    await wrapper.get('[data-testid="validation-select-candidate"]').trigger("click");
    await expectAccessible(wrapper.element);
    await wrapper.setProps({ locale: "en" });
    expect(wrapper.text()).toContain("Question");
    expect(wrapper.text()).toContain("What to observe");
    await expectAccessible(wrapper.element);
  });
});
