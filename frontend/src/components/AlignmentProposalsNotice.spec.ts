import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import AlignmentProposalsNotice from "./AlignmentProposalsNotice.vue";
import { KnowledgeAlignmentApiError, type KnowledgeAlignmentApi } from "../api/knowledgeAlignment";
import { useKnowledgeAlignmentStore } from "../stores/knowledgeAlignment";
import { expectAccessible } from "../test/axe";
import {
  ALIGNMENT_EXCERPT,
  ALIGNMENT_PROJECT_ID as PROJECT_ID,
  applyAnswer,
  DESIGN_PROPOSAL,
  proposalList,
  REQUIREMENTS_PROPOSAL,
  RUN_SUMMARY,
  SECOND_REQUIREMENTS_PROPOSAL,
  skippedProposal,
  TESTS_PROPOSAL,
} from "../test/knowledgeAlignmentFixtures";
import type {
  AlignmentProposalPayload,
  ProposalApplyPayload,
  ProposalSection,
} from "../types/knowledgeAlignment";

type Locale = "en" | "it";

const SECOND_PROJECT_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "test-token-not-real";
const DIFF_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

const EVERY_PROPOSAL = [
  REQUIREMENTS_PROPOSAL,
  DESIGN_PROPOSAL,
  TESTS_PROPOSAL,
  SECOND_REQUIREMENTS_PROPOSAL,
];

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });

  return { promise, resolve, reject };
}

function byCode(code: string): AlignmentProposalPayload {
  const found = EVERY_PROPOSAL.find((proposal) => proposal.code === code);

  if (found === undefined) {
    throw new Error(`Unknown proposal ${code}`);
  }

  return found;
}

type AlignmentApiMocks = { [K in keyof KnowledgeAlignmentApi]: Mock<KnowledgeAlignmentApi[K]> };

function alignmentApi(overrides: Partial<AlignmentApiMocks> = {}): AlignmentApiMocks {
  return {
    proposals: vi.fn<KnowledgeAlignmentApi["proposals"]>(async () => proposalList(EVERY_PROPOSAL)),
    apply: vi.fn<KnowledgeAlignmentApi["apply"]>(async (_project, code, text) =>
      applyAnswer(byCode(code), text, byCode(code).section === "TESTS" ? null : DIFF_ID),
    ),
    skip: vi.fn<KnowledgeAlignmentApi["skip"]>(async (_project, code, reason) => ({
      proposal: skippedProposal(byCode(code), reason),
    })),
    runs: vi.fn<KnowledgeAlignmentApi["runs"]>(async () => ({ items: [RUN_SUMMARY] })),
    ...overrides,
  };
}

function refusal(status: number, code: string): KnowledgeAlignmentApiError {
  return new KnowledgeAlignmentApiError(code, { status, code, payload: { detail: { code } } });
}

const mounted: { unmount: () => void }[] = [];

async function mountNotice(
  section: ProposalSection,
  locale: Locale = "it",
  api: KnowledgeAlignmentApi = alignmentApi(),
  projectId = PROJECT_ID,
) {
  const wrapper = mount(AlignmentProposalsNotice, {
    attachTo: document.body,
    props: { projectId, section, locale, authorize: (operation) => operation(TOKEN), api },
  });
  mounted.push(wrapper);
  await flushPromises();
  return wrapper;
}

type Wrapper = Awaited<ReturnType<typeof mountNotice>>;

const notice = '[data-testid="alignment-proposals"]';
const cardSelector = '[data-testid="alignment-proposal"]';
const text = '[data-testid="alignment-proposal-text"]';
const why = '[data-testid="alignment-proposal-why"]';
const applyButton = '[data-testid="alignment-proposal-apply"]';
const skipButton = '[data-testid="alignment-proposal-skip"]';
const state = '[data-testid="alignment-proposal-state"]';

function card(wrapper: Wrapper, code: string) {
  return wrapper.get(`${cardSelector}[data-code="${code}"]`);
}

function codes(wrapper: Wrapper): string[] {
  return wrapper.findAll(cardSelector).map((item) => item.attributes("data-code") ?? "");
}

function words(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  for (const wrapper of mounted.splice(0)) {
    wrapper.unmount();
  }
});

describe("AlignmentProposalsNotice", () => {
  it.each<[Locale, Record<string, string>]>([
    [
      "it",
      {
        title: "Proposte dal codice",
        hypothesis:
          "Ipotesi del modello ricavata dal diff del codice: nessuna persona l'ha verificata.",
        text: "Richiesta da applicare",
        rationale: "Motivazione: The commit adds an empty state to the list of the reservations.",
        about: "Riguarda: REQ-003 e SCR-001",
        why: "Perché?",
        commits: "Commit:",
        files: "File:",
        excerpt: "Estratto del diff:",
        apply: "Aggiorna e conferma",
        skip: "Scarta",
      },
    ],
    [
      "en",
      {
        title: "Proposals from the code",
        hypothesis:
          "A hypothesis of the model drawn from the code diff: no person has verified it.",
        text: "Request to apply",
        rationale: "Reason: The commit adds an empty state to the list of the reservations.",
        about: "About: REQ-003 and SCR-001",
        why: "Why?",
        commits: "Commits:",
        files: "Files:",
        excerpt: "Diff excerpt:",
        apply: "Update and confirm",
        skip: "Skip",
      },
    ],
  ])(
    "shows the waiting proposals of its section with the editable request and the collapsed why in %s",
    async (locale, expected) => {
      const api = alignmentApi();
      const wrapper = await mountNotice("REQUIREMENTS", locale, api);

      expect(api.proposals).toHaveBeenCalledWith(PROJECT_ID, "waiting", TOKEN);
      const section = wrapper.get(notice);
      expect(section.attributes("data-section")).toBe("REQUIREMENTS");
      expect(section.attributes("aria-labelledby")).toBeDefined();
      expect(section.get(`#${section.attributes("aria-labelledby")}`).text()).toBe(expected.title);
      expect(codes(wrapper)).toEqual(["ALN-001", "ALN-004"]);

      const first = card(wrapper, "ALN-001");
      expect(first.attributes("data-state")).toBe("waiting");
      expect(first.text()).toContain("The day without reservations");
      expect(first.text()).toContain("ALN-001");
      expect(first.text()).toContain(expected.hypothesis);
      expect(first.get("label").text()).toBe(expected.text);
      const textarea = first.get<HTMLTextAreaElement>(text);
      expect(textarea.element.value).toBe(REQUIREMENTS_PROPOSAL.request);
      expect(textarea.attributes("maxlength")).toBe("2000");
      expect(textarea.attributes("disabled")).toBeUndefined();
      expect(first.get("label").attributes("for")).toBe(textarea.attributes("id"));
      expect(words(first.text())).toContain(expected.rationale);
      expect(words(first.text())).toContain(expected.about);

      const details = first.get<HTMLDetailsElement>(why);
      expect(details.element.open).toBe(false);
      expect(details.get("summary").text()).toBe(expected.why);
      expect(words(details.text())).toContain(expected.commits);
      expect(words(details.text())).toContain(expected.files);
      expect(words(details.text())).toContain(expected.excerpt);
      expect(details.text()).toContain("c0ffee1");
      expect(details.text()).toContain("b0b0b0b");
      expect(details.text()).not.toContain("c0ffee1234567890");
      expect(details.findAll("li").map((item) => item.text())).toEqual([
        "src/reservations.js",
        "src/reservations.css",
      ]);
      expect(details.get("pre").text()).toBe(ALIGNMENT_EXCERPT);
      await details.get("summary").trigger("click");
      expect(details.element.open).toBe(true);

      expect(first.get(applyButton).text()).toBe(expected.apply);
      expect(first.get(applyButton).attributes("disabled")).toBeUndefined();
      expect(first.get(skipButton).text()).toBe(expected.skip);
      expect(first.find(state).exists()).toBe(false);
      expect(wrapper.emitted("applied")).toBeUndefined();
      expect(wrapper.emitted("skipped")).toBeUndefined();
    },
  );

  it("limits the request of each section as the Studio does", async () => {
    const design = await mountNotice("DESIGN");
    const tests = await mountNotice("TESTS", "en");

    expect(design.get(text).attributes("maxlength")).toBe("1000");
    expect(design.get(cardSelector).text()).toContain("Riguarda: SCR-001");
    expect(tests.get(text).attributes("maxlength")).toBe("600");
    expect(tests.get(cardSelector).text()).toContain("About: REQ-003 and AC-002");
  });

  it("renders nothing for a section without waiting proposals, when the Studio has none and when it cannot read them", async () => {
    const empty = await mountNotice(
      "DESIGN",
      "it",
      alignmentApi({
        proposals: vi.fn<KnowledgeAlignmentApi["proposals"]>(async () =>
          proposalList([REQUIREMENTS_PROPOSAL]),
        ),
      }),
    );
    expect(empty.find(notice).exists()).toBe(false);
    expect(empty.html()).toBe("<!--v-if-->");

    const none = await mountNotice(
      "REQUIREMENTS",
      "it",
      alignmentApi({
        proposals: vi.fn<KnowledgeAlignmentApi["proposals"]>(async () => proposalList([], null)),
      }),
    );
    expect(none.html()).toBe("<!--v-if-->");

    const failed = await mountNotice(
      "REQUIREMENTS",
      "it",
      alignmentApi({
        proposals: vi.fn<KnowledgeAlignmentApi["proposals"]>(async () => {
          throw refusal(404, "PROJECT_NOT_FOUND");
        }),
      }),
    );
    expect(failed.html()).toBe("<!--v-if-->");

    const blank = await mountNotice("REQUIREMENTS", "it", alignmentApi(), "  ");
    expect(blank.html()).toBe("<!--v-if-->");
  });

  it.each<[Locale, string]>([
    ["it", "Applicata: le differenze da approvare sono in questa sezione."],
    ["en", "Applied: the differences to approve are in this section."],
  ])(
    "applies a proposal with its own text, says where the differences are and emits the diff in %s",
    async (locale, applied) => {
      const api = alignmentApi();
      const wrapper = await mountNotice("REQUIREMENTS", locale, api);
      const first = card(wrapper, "ALN-001");

      await first.get(applyButton).trigger("click");
      await flushPromises();

      expect(api.apply).toHaveBeenCalledWith(PROJECT_ID, "ALN-001", null, TOKEN);
      expect(wrapper.emitted("applied")).toEqual([
        [{ code: "ALN-001", section: "REQUIREMENTS", diffId: DIFF_ID }],
      ]);
      expect(wrapper.emitted("skipped")).toBeUndefined();
      expect(first.element.isConnected).toBe(true);
      expect(first.attributes("data-state")).toBe("applied");
      const announced = first.get(state);
      expect(announced.text()).toBe(applied);
      expect(announced.attributes("role")).toBe("status");
      expect(announced.attributes("data-state")).toBe("applied");
      expect(document.activeElement).toBe(announced.element);
      expect(first.find(applyButton).exists()).toBe(false);
      expect(first.find(skipButton).exists()).toBe(false);
      expect(first.get(text).attributes("disabled")).toBeDefined();

      const second = card(wrapper, "ALN-004");
      expect(second.attributes("data-state")).toBe("waiting");
      expect(second.get(applyButton).attributes("disabled")).toBeUndefined();
      expect(second.get(skipButton).attributes("disabled")).toBeUndefined();
      expect(codes(wrapper)).toEqual(["ALN-001", "ALN-004"]);
    },
  );

  it("sends the text edited by the owner only when it differs from the proposal", async () => {
    const api = alignmentApi();
    const wrapper = await mountNotice("REQUIREMENTS");
    await wrapper.setProps({ api });
    const first = card(wrapper, "ALN-001");
    const second = card(wrapper, "ALN-004");

    await first.get(text).setValue("Aggiungi al requisito la frase del giorno vuoto.");
    await second.get(text).setValue(`  ${SECOND_REQUIREMENTS_PROPOSAL.request}  `);
    await first.get(applyButton).trigger("click");
    await flushPromises();
    await second.get(applyButton).trigger("click");
    await flushPromises();

    expect(api.apply).toHaveBeenNthCalledWith(
      1,
      PROJECT_ID,
      "ALN-001",
      "Aggiungi al requisito la frase del giorno vuoto.",
      TOKEN,
    );
    expect(api.apply).toHaveBeenNthCalledWith(2, PROJECT_ID, "ALN-004", null, TOKEN);
    expect(first.get<HTMLTextAreaElement>(text).element.value).toBe(
      "Aggiungi al requisito la frase del giorno vuoto.",
    );
  });

  it("does not apply an empty request and still lets the owner skip it", async () => {
    const api = alignmentApi();
    const wrapper = await mountNotice("REQUIREMENTS", "it", api);
    const first = card(wrapper, "ALN-001");

    await first.get(text).setValue("   ");

    expect(first.get(applyButton).attributes("disabled")).toBeDefined();
    expect(first.get(skipButton).attributes("disabled")).toBeUndefined();
    await first.get(applyButton).trigger("click");
    await flushPromises();
    expect(api.apply).not.toHaveBeenCalled();
    expect(wrapper.emitted("applied")).toBeUndefined();
  });

  it.each<[Locale, string]>([
    ["it", "Applicata."],
    ["en", "Applied."],
  ])("applies a proposal of the tests without differences in %s", async (locale, applied) => {
    const api = alignmentApi();
    const wrapper = await mountNotice("TESTS", locale, api);

    await wrapper.get(applyButton).trigger("click");
    await flushPromises();

    expect(api.apply).toHaveBeenCalledWith(PROJECT_ID, "ALN-003", null, TOKEN);
    expect(wrapper.emitted("applied")).toEqual([
      [{ code: "ALN-003", section: "TESTS", diffId: null }],
    ]);
    expect(wrapper.get(state).text()).toBe(applied);
    expect(wrapper.get(cardSelector).attributes("data-state")).toBe("applied");
  });

  it.each<[Locale, string]>([
    ["it", "Scartata."],
    ["en", "Skipped."],
  ])("skips a proposal without a reason and says so in %s", async (locale, skipped) => {
    const api = alignmentApi();
    const wrapper = await mountNotice("DESIGN", locale, api);

    await wrapper.get(skipButton).trigger("click");
    await flushPromises();

    expect(api.skip).toHaveBeenCalledWith(PROJECT_ID, "ALN-002", null, TOKEN);
    expect(api.apply).not.toHaveBeenCalled();
    expect(wrapper.emitted("skipped")).toEqual([[{ code: "ALN-002", section: "DESIGN" }]]);
    expect(wrapper.emitted("applied")).toBeUndefined();
    const announced = wrapper.get(state);
    expect(announced.text()).toBe(skipped);
    expect(announced.attributes("role")).toBe("status");
    expect(wrapper.get(cardSelector).attributes("data-state")).toBe("skipped");
    expect(wrapper.find(applyButton).exists()).toBe(false);
    expect(wrapper.find(skipButton).exists()).toBe(false);
    expect(wrapper.get(text).attributes("disabled")).toBeDefined();
  });

  it.each<[Locale, string, string]>([
    [
      "it",
      "Lo Studio sta applicando la proposta… Il modello prepara le differenze: può richiedere qualche minuto.",
      "Lo Studio sta scartando la proposta…",
    ],
    [
      "en",
      "The Studio is applying the proposal… The model is preparing the differences: it can take a few minutes.",
      "The Studio is skipping the proposal…",
    ],
  ])(
    "says in %s that the Studio is working and blocks the other decisions meanwhile",
    async (locale, applying, skipping) => {
      const pendingApply = deferred<ProposalApplyPayload>();
      const api = alignmentApi({
        apply: vi.fn<KnowledgeAlignmentApi["apply"]>(async () => pendingApply.promise),
      });
      const wrapper = await mountNotice("REQUIREMENTS", locale, api);
      const first = card(wrapper, "ALN-001");
      const second = card(wrapper, "ALN-004");

      await first.get(applyButton).trigger("click");
      await flushPromises();

      expect(first.attributes("data-state")).toBe("applying");
      expect(first.attributes("aria-busy")).toBe("true");
      expect(words(first.get(state).text())).toBe(applying);
      expect(first.get(state).attributes("role")).toBe("status");
      expect(first.get(applyButton).attributes("disabled")).toBeDefined();
      expect(first.get(skipButton).attributes("disabled")).toBeDefined();
      expect(first.get(text).attributes("disabled")).toBeDefined();
      expect(second.get(applyButton).attributes("disabled")).toBeDefined();
      expect(second.get(skipButton).attributes("disabled")).toBeDefined();
      expect(second.attributes("aria-busy")).toBeUndefined();
      await first.get(applyButton).trigger("click");
      expect(api.apply).toHaveBeenCalledOnce();

      pendingApply.resolve(applyAnswer(REQUIREMENTS_PROPOSAL, null, DIFF_ID));
      await flushPromises();

      expect(first.attributes("data-state")).toBe("applied");
      expect(first.attributes("aria-busy")).toBeUndefined();
      expect(second.get(applyButton).attributes("disabled")).toBeUndefined();

      const pendingSkip = deferred<{ proposal: AlignmentProposalPayload }>();
      api.skip.mockImplementationOnce(async () => pendingSkip.promise);
      await second.get(skipButton).trigger("click");
      await flushPromises();

      expect(second.attributes("data-state")).toBe("skipping");
      expect(second.get(state).text()).toBe(skipping);

      pendingSkip.resolve({ proposal: skippedProposal(SECOND_REQUIREMENTS_PROPOSAL, null) });
      await flushPromises();
      expect(second.attributes("data-state")).toBe("skipped");
    },
  );

  it.each<[string, number, string]>([
    [
      "ALIGNMENT_PROPOSAL_DECIDED",
      409,
      "Non è stato possibile applicare la proposta. Questa proposta è già stata decisa, forse dal terminale.",
    ],
    [
      "REQUIREMENTS_REVISION_PENDING",
      409,
      "Non è stato possibile applicare la proposta. C'è già una nuova versione da decidere: applicala o scartala prima di applicare una proposta.",
    ],
    [
      "REQUIREMENTS_UNCHANGED",
      409,
      "Non è stato possibile applicare la proposta. Il modello non ha trovato nulla da cambiare con questa richiesta. Modifica il testo e riprova.",
    ],
    [
      "REQUIREMENTS_APPROVAL_REQUIRED",
      409,
      "Non è stato possibile applicare la proposta. Prima va approvata questa sezione.",
    ],
    [
      "KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED",
      503,
      "Non è stato possibile applicare la proposta. Il modello non è collegato: controlla lo stato dei modelli in Dettagli del progetto.",
    ],
    [
      "PROVIDER_UNAVAILABLE",
      502,
      "Non è stato possibile applicare la proposta. Il modello non è raggiungibile. Controlla la sua disponibilità in Dettagli del progetto prima di riprovare.",
    ],
    [
      "SOMETHING_UNEXPECTED",
      500,
      "Non è stato possibile applicare la proposta. Non è stato possibile completare la richiesta. Puoi riprovare.",
    ],
  ])(
    "explains in the page language why %s stopped the application",
    async (code, status, expected) => {
      const api = alignmentApi({
        apply: vi.fn<KnowledgeAlignmentApi["apply"]>(async () => {
          throw refusal(status, code);
        }),
      });
      const wrapper = await mountNotice("REQUIREMENTS", "it", api);
      const first = card(wrapper, "ALN-001");

      await first.get(applyButton).trigger("click");
      await flushPromises();

      expect(first.attributes("data-state")).toBe("failed");
      const announced = first.get(state);
      expect(announced.attributes("role")).toBe("alert");
      expect(announced.text()).toBe(expected);
      expect(announced.text()).not.toContain(code);
      expect(document.activeElement).toBe(announced.element);
      expect(first.get(applyButton).attributes("disabled")).toBeUndefined();
      expect(first.get(skipButton).attributes("disabled")).toBeUndefined();
      expect(first.get(text).attributes("disabled")).toBeUndefined();
      expect(wrapper.emitted("applied")).toBeUndefined();

      api.apply.mockImplementationOnce(async (_project, applied, text) =>
        applyAnswer(byCode(applied), text, DIFF_ID),
      );
      await first.get(applyButton).trigger("click");
      await flushPromises();
      expect(first.attributes("data-state")).toBe("applied");
      expect(wrapper.emitted("applied")).toHaveLength(1);
    },
  );

  it.each<[Locale, string]>([
    ["it", "Non è stato possibile scartare la proposta. Questa proposta non c'è più."],
    ["en", "The proposal could not be skipped. This proposal is no longer there."],
  ])("explains in %s why a skip was refused and keeps the proposal", async (locale, expected) => {
    const api = alignmentApi({
      skip: vi.fn<KnowledgeAlignmentApi["skip"]>(async () => {
        throw refusal(404, "ALIGNMENT_PROPOSAL_NOT_FOUND");
      }),
    });
    const wrapper = await mountNotice("DESIGN", locale, api);

    await wrapper.get(skipButton).trigger("click");
    await flushPromises();

    expect(wrapper.get(cardSelector).attributes("data-state")).toBe("failed");
    expect(wrapper.get(state).text()).toBe(expected);
    expect(wrapper.get(state).attributes("role")).toBe("alert");
    expect(wrapper.emitted("skipped")).toBeUndefined();
    expect(wrapper.find(skipButton).exists()).toBe(true);
  });

  it("names a connection failure without a code in plain words", async () => {
    const api = alignmentApi({
      apply: vi.fn<KnowledgeAlignmentApi["apply"]>(async () => {
        throw new TypeError("Failed to fetch");
      }),
    });
    const wrapper = await mountNotice("TESTS", "en", api);

    await wrapper.get(applyButton).trigger("click");
    await flushPromises();

    expect(wrapper.get(state).text()).toBe(
      "The proposal could not be applied. The request could not be completed. You can try again.",
    );
  });

  it("keeps a decided proposal visible with its state when the list is read again without it", async () => {
    const api = alignmentApi();
    const wrapper = await mountNotice("REQUIREMENTS", "it", api);
    const store = useKnowledgeAlignmentStore();

    await card(wrapper, "ALN-001").get(applyButton).trigger("click");
    await flushPromises();
    await store.reload(
      PROJECT_ID,
      (operation) => operation(TOKEN),
      alignmentApi({
        proposals: vi.fn<KnowledgeAlignmentApi["proposals"]>(async () =>
          proposalList([SECOND_REQUIREMENTS_PROPOSAL]),
        ),
      }),
    );
    await flushPromises();

    expect(codes(wrapper)).toEqual(["ALN-004", "ALN-001"]);
    expect(card(wrapper, "ALN-001").attributes("data-state")).toBe("applied");
    expect(card(wrapper, "ALN-001").get(state).text()).toBe(
      "Applicata: le differenze da approvare sono in questa sezione.",
    );
    expect(card(wrapper, "ALN-004").attributes("data-state")).toBe("waiting");
  });

  it("reads the proposals again when the project changes and forgets the decisions and the edits", async () => {
    const api = alignmentApi();
    const wrapper = await mountNotice("REQUIREMENTS", "it", api);

    await card(wrapper, "ALN-001").get(text).setValue("Testo cambiato.");
    await card(wrapper, "ALN-004").get(applyButton).trigger("click");
    await flushPromises();
    expect(card(wrapper, "ALN-004").attributes("data-state")).toBe("applied");

    await wrapper.setProps({ projectId: SECOND_PROJECT_ID });
    await flushPromises();

    expect(api.proposals).toHaveBeenCalledTimes(2);
    expect(api.proposals).toHaveBeenLastCalledWith(SECOND_PROJECT_ID, "waiting", TOKEN);
    expect(codes(wrapper)).toEqual(["ALN-001", "ALN-004"]);
    expect(card(wrapper, "ALN-001").get<HTMLTextAreaElement>(text).element.value).toBe(
      REQUIREMENTS_PROPOSAL.request,
    );
    expect(card(wrapper, "ALN-004").attributes("data-state")).toBe("waiting");
    expect(card(wrapper, "ALN-004").find(applyButton).exists()).toBe(true);
  });

  it("has no axe violations while waiting, while the Studio works and after the decisions", async () => {
    const pendingApply = deferred<ProposalApplyPayload>();
    const api = alignmentApi({
      apply: vi.fn<KnowledgeAlignmentApi["apply"]>(async (_project, code, text) => {
        if (code === "ALN-001") {
          return pendingApply.promise;
        }

        return applyAnswer(byCode(code), text, DIFF_ID);
      }),
    });
    const wrapper = await mountNotice("REQUIREMENTS", "it", api);
    await expectAccessible(wrapper.element);

    await card(wrapper, "ALN-001").get(applyButton).trigger("click");
    await flushPromises();
    await expectAccessible(wrapper.element);

    pendingApply.resolve(applyAnswer(REQUIREMENTS_PROPOSAL, null, DIFF_ID));
    await flushPromises();
    await card(wrapper, "ALN-004").get(skipButton).trigger("click");
    await flushPromises();
    await card(wrapper, "ALN-001").get(why).get("summary").trigger("click");
    await expectAccessible(wrapper.element);

    const failing = await mountNotice(
      "DESIGN",
      "en",
      alignmentApi({
        apply: vi.fn<KnowledgeAlignmentApi["apply"]>(async () => {
          throw refusal(409, "DESIGN_REVISION_PENDING");
        }),
      }),
    );
    await failing.get(applyButton).trigger("click");
    await flushPromises();
    expect(failing.get(state).text()).toBe(
      "The proposal could not be applied. A new version is already waiting for your decision: apply it or discard it before you apply a proposal.",
    );
    await expectAccessible(failing.element);
  });
});
