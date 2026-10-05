import { flushPromises, mount, type DOMWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import ProjectHumanValidationPanel from "./ProjectHumanValidationPanel.vue";
import { HumanValidationApiError, type HumanValidationApi } from "../api/humanValidation";
import type { ResearchEvidenceApi } from "../api/researchEvidence";
import { useDesignStore } from "../stores/design";
import { UNSELECTED_DESIGN_VERSION } from "../test/designFixtures";
import {
  operationalHypothesis,
  validationCandidate,
  validationDocument,
  validationOutcome,
  validationOverview,
  validationSource,
  VALIDATION_HASH,
  VALIDATION_ORIGIN,
  VALIDATION_QUOTE,
  VALIDATION_SOURCE_ID,
  VALIDATION_TWIN,
} from "../test/humanValidationFixtures";
import { whyNode } from "../test/whyFixtures";
import type { DesignPackageVersionPayload } from "../types/design";
import type { HumanValidationOverview, OperationalHypothesis } from "../types/humanValidation";
import type { WhyDocument, WhyNode } from "../types/why";
import { expectAccessible } from "../test/axe";

const wrappers: { unmount: () => void }[] = [];
beforeEach(() => {
  setActivePinia(createPinia());
});
afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount();
  wrappers.length = 0;
});

function clients(initial = validationOverview(), graph: WhyDocument = validationDocument()) {
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
  const why = { document: vi.fn(async () => graph), explain: vi.fn() };
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

const CRITIQUE_TEXT =
  "La proposta risponde agli obiettivi di velocità e di uso con il pollice per chi fa conti in piedi. Il giudizio si basa su osservazioni dedotte dal brief e non verificate con persone reali.";

const CONCERN_SUMMARY = "Con il pollice si preme facilmente il tasto accanto a quello giusto.";
const CONCERN_MITIGATION = "Tasti più distanziati nella prossima versione.";
const DESIGN_VERSION: DesignPackageVersionPayload = {
  ...UNSELECTED_DESIGN_VERSION,
  project_id: "project",
  package: {
    ...UNSELECTED_DESIGN_VERSION.package,
    project_id: "project",
    concerns: [
      {
        id: "concern-id",
        code: "DRK-001",
        summary: CONCERN_SUMMARY,
        mitigation: CONCERN_MITIGATION,
        requirement_ids: [],
        design_alternative_ids: [],
      },
    ],
  },
};
const READER_TWIN = whyNode({
  key: "reader-twin",
  code: "UT-002",
  kind: "USER_TWIN",
  title: "Reader twin",
  validation_required: false,
  reference: { artifact_id: "reader-twin-id", version_number: 1, content_hash: VALIDATION_HASH },
});

function rationale(text: string): WhyNode["rationale"] {
  return { text, origin: "MODEL", version_number: 2, content_hash: VALIDATION_HASH };
}

function candidateOf(origin: WhyNode, twins = [VALIDATION_TWIN, READER_TWIN]) {
  return validationCandidate({
    key: origin.key,
    code: origin.code,
    kind: origin.kind,
    title: origin.title,
    reference: origin.reference,
    origin,
    twin_references: twins,
  });
}

function readableCandidates(): HumanValidationOverview {
  const candidates = [
    candidateOf(
      whyNode({
        key: "silent",
        code: "DRK-001",
        kind: "DESIGN_CONCERN",
        title: "DRK-001",
        reference: {
          artifact_id: "concern-id",
          version_number: DESIGN_VERSION.version_number,
          content_hash: DESIGN_VERSION.content_hash,
        },
      }),
    ),
    candidateOf(
      whyNode({
        key: "explained",
        code: "DRK-002",
        kind: "DESIGN_CONCERN",
        title: "DRK-002",
        rationale: rationale("Il tasto per ricominciare è lontano dal pollice."),
      }),
    ),
    candidateOf(
      whyNode({
        key: "finding",
        code: "UTF-001",
        kind: "SYNTHETIC_FINDING",
        title: "Dopo il secondo numero il display non mostra più l'operazione.",
        rationale: rationale("Spiegazione completa che resta nei dettagli."),
      }),
    ),
    candidateOf(
      whyNode({
        key: "second-finding",
        code: "UTF-001",
        kind: "SYNTHETIC_FINDING",
        title: "Non vedo come cancellare soltanto l'ultima cifra.",
      }),
    ),
    candidateOf(
      whyNode({
        key: "critique",
        code: "CRQ-001",
        kind: "SYNTHETIC_DESIGN_CRITIQUE",
        title: CRITIQUE_TEXT,
        rationale: rationale(CRITIQUE_TEXT),
      }),
    ),
    candidateOf(
      whyNode({
        ...VALIDATION_ORIGIN,
        declared_context: {
          perspectives: [],
          observation_value: {
            kind: "ITEMS",
            text: null,
            items: ["Tasti grandi", "Cifre leggibili"],
            reason: null,
          },
        },
      }),
      [VALIDATION_TWIN],
    ),
    candidateOf(
      whyNode({
        ...VALIDATION_ORIGIN,
        key: "expertise",
        code: "UT-001:user_twin.expertise",
        title: "expertise",
        rationale: rationale("Il brief non descrive le competenze."),
        declared_context: {
          perspectives: [],
          observation_value: { kind: "UNKNOWN", text: null, items: [], reason: null },
        },
      }),
      [],
    ),
  ];
  return validationOverview({ candidates, candidate_count: candidates.length });
}

function readableDocument(): WhyDocument {
  const base = validationDocument();
  return {
    ...base,
    nodes: [...base.nodes, READER_TWIN],
    links: [
      ...base.links,
      { source: "finding", target: "twin", kind: "EVALUATED_BY" },
      { source: "second-finding", target: "reader-twin", kind: "EVALUATED_BY" },
      { source: "critique", target: "reader-twin", kind: "ACTOR" },
    ],
  };
}

async function openCandidates(wrapper: ReturnType<typeof panel>["wrapper"]) {
  await flushPromises();
  await wrapper.get('[data-testid="validation-show-candidates"]').trigger("click");
  await wrapper.get('[data-testid="validation-show-all"]').trigger("click");
  return wrapper.findAll('[data-testid="validation-candidate"]');
}

function read(cards: DOMWrapper<Element>[], part: "title" | "twin" | "text") {
  return cards.map((card) => {
    const element = card.find(`[data-testid="validation-candidate-${part}"]`);
    return element.exists() ? element.text() : null;
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

  it("shows the type, the twin and what each candidate says without opening the details", async () => {
    const { wrapper } = panel(clients(readableCandidates(), readableDocument()));
    const cards = await openCandidates(wrapper);
    expect(read(cards, "title")).toEqual([
      "Criticità · DRK-001",
      "Criticità · DRK-002",
      "Osservazione del twin · UTF-001",
      "Osservazione del twin · UTF-001",
      "Parere del twin · CRQ-001",
      "Calculator twin · Obiettivi",
      "Twin · Esperienza",
    ]);
    expect(read(cards, "twin")).toEqual([
      null,
      null,
      "Twin: Calculator twin",
      "Twin: Reader twin",
      "Twin: Reader twin",
      null,
      null,
    ]);
    expect(read(cards, "text")).toEqual([
      null,
      "Il tasto per ricominciare è lontano dal pollice.",
      "Dopo il secondo numero il display non mostra più l'operazione.",
      "Non vedo come cancellare soltanto l'ultima cifra.",
      CRITIQUE_TEXT,
      "Tasti grandi, Cifre leggibili",
      "Il brief non descrive le competenze.",
    ]);
    for (const text of wrapper.findAll('[data-testid="validation-candidate-text"]')) {
      expect(text.element.closest("details")).toBeNull();
      expect(text.classes()).toContain("line-clamp-3");
    }
    expect(cards[2]!.get("details").text()).toContain(
      "Spiegazione completa che resta nei dettagli.",
    );
    expect(cards[4]!.get("details").text()).toContain(CRITIQUE_TEXT);
    expect(cards[5]!.get("details").text()).toContain("UT-001:user_twin.goals");
  });

  it("names the candidate types and twins in English and keeps the cards accessible", async () => {
    const { wrapper } = panel(clients(readableCandidates(), readableDocument()), {
      locale: "en",
    });
    const cards = await openCandidates(wrapper);
    expect(read(cards, "title")).toEqual([
      "Concern · DRK-001",
      "Concern · DRK-002",
      "Twin observation · UTF-001",
      "Twin observation · UTF-001",
      "Twin opinion · CRQ-001",
      "Calculator twin · Goals",
      "Twin · Expertise",
    ]);
    expect(read(cards, "twin")[3]).toBe("Twin: Reader twin");
    expect(read(cards, "text")[5]).toBe("Tasti grandi, Cifre leggibili");
    expect(cards[5]!.text()).toContain("To verify");
    expect(cards[2]!.text()).toContain("Synthetic pre-validation");
    await expectAccessible(wrapper.element);
  });

  it("takes a concern sentence only from the loaded design version of this project", async () => {
    const design = useDesignStore();
    const { wrapper } = panel(clients(readableCandidates(), readableDocument()));
    const cards = await openCandidates(wrapper);
    expect(read(cards, "text")[0]).toBeNull();
    design.activateProject("other");
    design.applyVersion({ ...DESIGN_VERSION, project_id: "other" });
    await nextTick();
    expect(read(cards, "text")[0]).toBeNull();
    design.activateProject("project");
    design.applyVersion({ ...DESIGN_VERSION, content_hash: "e".repeat(64) });
    await nextTick();
    expect(read(cards, "text")[0]).toBeNull();
    design.applyVersion(DESIGN_VERSION);
    await nextTick();
    expect(read(cards, "text").slice(0, 2)).toEqual([
      CONCERN_SUMMARY,
      "Il tasto per ricominciare è lontano dal pollice.",
    ]);
    expect(read(cards, "title")[0]).toBe("Criticità · DRK-001");
    expect(cards[0]!.text()).not.toContain(CONCERN_MITIGATION);
    await wrapper.setProps({ locale: "en" });
    expect(read(cards, "title")[0]).toBe("Concern · DRK-001");
    expect(read(cards, "text")[0]).toBe(CONCERN_SUMMARY);
  });

  it("titles the hypothesis form with the heading of the chosen card", async () => {
    const { wrapper } = panel(clients(readableCandidates(), readableDocument()));
    const cards = await openCandidates(wrapper);
    const heading = () => wrapper.get('[data-testid="validation-hypothesis-form"] h3').text();
    await cards[0]!.get('[data-testid="validation-select-candidate"]').trigger("click");
    expect(heading()).toBe("Ipotesi operativa · Criticità · DRK-001");
    await cards[5]!.get('[data-testid="validation-select-candidate"]').trigger("click");
    expect(heading()).toBe("Ipotesi operativa · Calculator twin · Obiettivi");
    await wrapper.setProps({ locale: "en" });
    expect(heading()).toBe("Operational hypothesis · Calculator twin · Goals");
  });
});
