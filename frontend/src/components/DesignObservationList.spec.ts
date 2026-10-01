import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import DesignObservationList, {
  type ObservationCritique,
  type ObservationFinding,
} from "./DesignObservationList.vue";

const OLD_STEP_NAMES =
  /passo Squadra|Team step|passo Requisiti|Requirements step|passo Pacchetto|Package step|\bPacchetto\b/;

const TEAM_WORDS =
  /\b(?:squadr[ae]|teams?|agent[ei]|agents?|assistent[ei]|assistants?|specialist[ai]|specialists?|ruol[oi]|roles?|membr[oi]|members?)\b/i;

const twin = { id: "twin-vb", name: "Volontari al banco" };
const alternative = { id: "alt-1", code: "DES-001", title: "Vista Scheda" };

const findings: ObservationFinding[] = [
  {
    finding_id: "UTF-001",
    twin_id: "twin-vb",
    summary: "Non si può cercare o filtrare un libro nella lista.",
    location: "Selezione del libro · Libro",
    criterion: "actionability",
    severity: "major",
    recommended_action: "Aggiungere una ricerca e filtri per giorni di ritardo.",
    number: 1,
  },
  {
    finding_id: "UTF-002",
    twin_id: "twin-vb",
    summary: "Il libro si sceglie da un menu con quattro titoli fissi.",
    location: "Selezione del libro · Libro",
    criterion: "task_alignment",
    severity: "critical",
    recommended_action: "Sostituire il menu con l'elenco dei ritardi.",
    number: 3,
  },
  {
    finding_id: "UTF-003",
    twin_id: "twin-vb",
    summary: "Non si capisce a che punto è il lavoro del turno.",
    location: "",
    criterion: "comprehensibility",
    severity: "moderate",
    recommended_action: "",
    number: null,
  },
];

const critique: ObservationCritique = {
  code: "CRT-004",
  user_twin_reference: { twin_id: "twin-lb", name: "Lettori della biblioteca" },
  strengths: ["Il promemoria dice da quanto sono in ritardo."],
  concerns: ["Non posso rileggere il promemoria.", " ", "Il tono sembra una multa."],
  unmet_needs: [],
  accessibility_observations: ["Il testo è piccolo sul telefono."],
  trust_concerns: [],
  questions: ["Riceverò un secondo promemoria?"],
  suggested_changes: ["Mostrare il testo del promemoria nella conferma."],
};

function key(finding: ObservationFinding): string {
  return `run-1:${finding.twin_id}:${finding.finding_id}`;
}

function mountList(props: Partial<InstanceType<typeof DesignObservationList>["$props"]> = {}) {
  return mount(DesignObservationList, {
    props: { twin, alternative, runId: "run-1", findings, ...props },
    global: { plugins: [createAppI18n("it")] },
  });
}

function cards(wrapper: ReturnType<typeof mountList>) {
  return wrapper.findAll("[data-testid='design-observation']");
}

describe("design observation list", () => {
  it("names the twin and the alternative of the chosen cell", () => {
    expect(mountList().get("h3").text()).toBe("Volontari al banco su DES-001 · Vista Scheda");
    expect(mountList({ twin: null }).get("h3").text()).toBe("Osservazioni dei twin");
  });

  it("shows every finding of the review as a hypothesis with its details", () => {
    const wrapper = mountList();
    const [first, second, third] = cards(wrapper);
    expect(first?.attributes("data-claim-status")).toBe("hypothesis");
    expect(first?.attributes("data-decision")).toBe("NONE");
    expect(first?.get("[data-testid='design-observation-number']").text()).toBe("1");
    expect(first?.text()).toContain("Importante");
    expect(first?.text()).toContain("Azionabilità");
    expect(first?.text()).toContain("Volontari al banco");
    expect(first?.text()).toContain("Non si può cercare o filtrare un libro nella lista.");
    expect(first?.text()).toContain("Dove: Selezione del libro · Libro");
    expect(first?.text()).toContain(
      "Azione suggerita: Aggiungere una ricerca e filtri per giorni di ritardo.",
    );
    expect(second?.text()).toContain("Critica");
    expect(second?.text()).toContain("Aderenza al compito");
    expect(second?.find(".text-fail-on-night").text()).toBe("Critica");
    expect(third?.find("[data-testid='design-observation-number']").exists()).toBe(false);
    expect(third?.text()).not.toContain("Dove:");
    expect(third?.text()).not.toContain("Azione suggerita");
    const group = first?.get("[data-testid='design-observation-decision']");
    expect(group?.attributes("role")).toBe("group");
    expect(group?.attributes("aria-label")).toBe("La tua decisione su questa osservazione");
    expect(group?.findAll("button").map((button) => button.text())).toEqual([
      "Confermo",
      "Non pertinente",
    ]);
  });

  it("names the twin on a finding only when the finding is of that twin", () => {
    const wrapper = mountList({ twin: { id: "twin-lb", name: "Lettori della biblioteca" } });
    expect(cards(wrapper)[0]?.text()).not.toContain("Lettori della biblioteca");
    expect(wrapper.get("h3").text()).toBe("Lettori della biblioteca su DES-001 · Vista Scheda");
  });

  it("asks to confirm or to set aside a finding", async () => {
    const wrapper = mountList();
    await cards(wrapper)[0]?.get("[data-testid='design-observation-confirm']").trigger("click");
    await cards(wrapper)[1]?.get("[data-testid='design-observation-dismiss']").trigger("click");
    expect(wrapper.emitted("confirm")).toEqual([[findings[0]]]);
    expect(wrapper.emitted("dismiss")).toEqual([[findings[1]]]);
  });

  it("waits while a decision is being saved", async () => {
    const first = findings[0] as ObservationFinding;
    const wrapper = mountList({ validating: key(first) });
    const buttons = wrapper.findAll(
      "[data-testid='design-observation-confirm'], [data-testid='design-observation-dismiss']",
    );
    expect(buttons.every((button) => button.attributes("disabled") !== undefined)).toBe(true);
    expect(cards(wrapper)[0]?.get("[data-testid='design-observation-saving']").text()).toBe(
      "Salvo la tua decisione…",
    );
    expect(cards(wrapper)[1]?.find("[data-testid='design-observation-saving']").exists()).toBe(
      false,
    );
    await buttons[0]?.trigger("click");
    expect(wrapper.emitted("confirm")).toBeUndefined();
  });

  it("offers to bring a confirmed finding into the project", async () => {
    const first = findings[0] as ObservationFinding;
    const wrapper = mountList({ validations: { [key(first)]: { decision: "OWNER_CONFIRMED" } } });
    const card = cards(wrapper)[0];
    expect(card?.attributes("data-claim-status")).toBe("confirmed");
    expect(card?.attributes("data-decision")).toBe("OWNER_CONFIRMED");
    expect(card?.find("[data-testid='design-observation-decision']").exists()).toBe(false);
    expect(card?.text()).toContain("Confermata · portala nel progetto:");
    const group = card?.get("[data-testid='design-observation-bring']");
    expect(group?.attributes("aria-label")).toBe("Portala nel progetto");
    expect(group?.findAll("button").map((button) => button.text())).toEqual([
      "Brief",
      "Requisiti",
      "Design",
    ]);
    await group?.get("[data-target='REQUIREMENTS']").trigger("click");
    expect(wrapper.emitted("apply-insight")).toEqual([
      [
        {
          target: "REQUIREMENTS",
          source: {
            kind: "SYNTHETIC_FINDING",
            id: "run:run-1:twin-vb:UTF-001",
            twinId: "twin-vb",
            text: "Non si può cercare o filtrare un libro nella lista.",
            mitigation: "Aggiungere una ricerca e filtri per giorni di ritardo.",
          },
        },
      ],
    ]);
  });

  it("says where a confirmed finding went and waits while it goes there", async () => {
    const first = findings[0] as ObservationFinding;
    const validations = { [key(first)]: { decision: "OWNER_CONFIRMED" as const } };
    const wrapper = mountList({ validations, applying: "run:run-1:twin-vb:UTF-001" });
    const targets = cards(wrapper)[0]?.findAll("[data-testid='design-observation-target']") ?? [];
    expect(targets.every((button) => button.attributes("disabled") !== undefined)).toBe(true);
    expect(cards(wrapper)[0]?.get("[data-testid='design-observation-applying']").text()).toBe(
      "La porto nel progetto…",
    );
    await targets[0]?.trigger("click");
    expect(wrapper.emitted("apply-insight")).toBeUndefined();
    await wrapper.setProps({ applying: null, applied: { "run:run-1:twin-vb:UTF-001": "DESIGN" } });
    expect(cards(wrapper)[0]?.get("[data-testid='design-observation-applied']").text()).toBe(
      "Aggiunta al design come proposta",
    );
    expect(cards(wrapper)[0]?.find("[data-testid='design-observation-bring']").exists()).toBe(
      false,
    );
  });

  it("dims a finding set aside and lets the person confirm it after all", async () => {
    const second = findings[1] as ObservationFinding;
    const wrapper = mountList({ validations: { [key(second)]: { decision: "OWNER_DISMISSED" } } });
    const card = cards(wrapper)[1];
    expect(card?.classes()).toContain("opacity-60");
    expect(card?.attributes("data-claim-status")).toBe("hypothesis");
    expect(card?.get("[data-testid='design-observation-dismissed']").text()).toContain(
      "Non pertinente: resta fuori dal progetto.",
    );
    await card?.get("[data-testid='design-observation-reconsider']").trigger("click");
    expect(wrapper.emitted("confirm")).toEqual([[second]]);
  });

  it("explains in plain words why a decision or a transfer did not work", () => {
    const first = findings[0] as ObservationFinding;
    const second = findings[1] as ObservationFinding;
    const wrapper = mountList({
      validations: { [key(first)]: { decision: "OWNER_CONFIRMED" } },
      failure: { key: key(second), code: "DESIGN_FINDING_NOT_FOUND" },
      applyFailure: { id: "run:run-1:twin-vb:UTF-001", code: "INSIGHT_ALREADY_APPLIED" },
    });
    expect(cards(wrapper)[1]?.get("[role='alert']").text()).toBe(
      "Questa osservazione non è più disponibile. Ricarica la pagina.",
    );
    expect(cards(wrapper)[0]?.get("[role='alert']").text()).toBe(
      "Questo spunto è già nel progetto.",
    );
    const other = mountList({
      failure: { key: key(first), code: "DESIGN_LOOP_REQUEST_FAILED" },
      applyFailure: null,
    });
    expect(cards(other)[0]?.get("[role='alert']").text()).toBe(
      "Non è stato possibile salvare la tua decisione. Riprova.",
    );
  });

  it("says when the review found nothing for this twin", () => {
    const wrapper = mountList({ findings: [] });
    expect(wrapper.get("[data-testid='design-observation-empty']").text()).toBe(
      "Nessuna osservazione: il twin non ha nulla da obiettare su questa alternativa.",
    );
  });

  it("shows the lists of a critique when there is no review", () => {
    const wrapper = mountList({ findings: null, critique });
    const lists = wrapper.findAll("[data-testid='design-critique-list']");
    expect(lists.map((list) => list.attributes("data-list"))).toEqual([
      "strengths",
      "concerns",
      "accessibility_observations",
      "questions",
      "suggested_changes",
    ]);
    expect(lists.map((list) => list.get("h4").text())).toEqual([
      "Punti di forza",
      "Criticità",
      "Accessibilità",
      "Domande aperte",
      "Modifiche suggerite",
    ]);
    expect(lists.every((list) => list.attributes("data-claim-status") === "hypothesis")).toBe(true);
    const concerns = lists[1]?.findAll("[data-testid='design-critique-item']") ?? [];
    expect(concerns.map((item) => item.find("span").text())).toEqual([
      "Non posso rileggere il promemoria.",
      "Il tono sembra una multa.",
    ]);
    expect(lists[0]?.find("[data-testid='design-critique-bring']").exists()).toBe(false);
    expect(wrapper.findAll("[data-testid='design-critique-bring']")).toHaveLength(2);
    expect(wrapper.find("[data-testid='design-observation']").exists()).toBe(false);
  });

  it("brings a concern of the critique into the project", async () => {
    const wrapper = mountList({
      findings: null,
      critique,
      applied: { "CRT-004:0": "BRIEF" },
    });
    const items = wrapper.findAll("[data-list='concerns'] [data-testid='design-critique-item']");
    expect(items[0]?.get("[data-testid='design-observation-applied']").text()).toBe(
      "Messa da parte per il brief",
    );
    expect(items[1]?.get("summary").text()).toBe("Porta nel progetto");
    await items[1]?.get("[data-target='DESIGN']").trigger("click");
    expect(wrapper.emitted("apply-insight")).toEqual([
      [
        {
          target: "DESIGN",
          source: {
            kind: "DESIGN_CRITIQUE",
            id: "CRT-004:2",
            twinId: "twin-lb",
            text: "Il tono sembra una multa.",
            mitigation: "Mostrare il testo del promemoria nella conferma.",
          },
        },
      ],
    ]);
  });

  it("names screens and elements by their titles in the stored texts and in what it brings into the project", async () => {
    const coded: ObservationFinding = {
      finding_id: "UTF-009",
      twin_id: "twin-vb",
      summary: "L'avviso di SCR-004 funziona, ma ELM-041 è lontano.",
      location: "SCR-001 Registra gli ospiti · ELM-018 Lista numerata",
      criterion: "actionability",
      severity: "major",
      recommended_action: "Sposta ELM-041 accanto a ELM-018.",
      number: 2,
    };
    const wrapper = mountList({
      findings: [coded],
      screens: [{ code: "SCR-004", title: "Conferma della presenza" }],
      elements: { "ELM-041": "Pulsante Salva" },
      validations: { [key(coded)]: { decision: "OWNER_CONFIRMED" } },
    });
    const card = cards(wrapper)[0];
    expect(card?.text()).toContain(
      "L'avviso di «Conferma della presenza» funziona, ma «Pulsante Salva» è lontano.",
    );
    expect(card?.text()).toContain("Dove: Registra gli ospiti · Lista numerata");
    expect(card?.text()).toContain(
      "Azione suggerita: Sposta «Pulsante Salva» accanto a «Lista numerata».",
    );
    expect(card?.text()).not.toMatch(/SCR-0|ELM-0/);
    await card?.get("[data-target='BRIEF']").trigger("click");
    expect(wrapper.emitted("apply-insight")?.[0]?.[0]).toMatchObject({
      source: {
        text: "L'avviso di «Conferma della presenza» funziona, ma «Pulsante Salva» è lontano.",
        mitigation: "Sposta «Pulsante Salva» accanto a «Lista numerata».",
      },
    });

    const english = mountList({
      findings: null,
      critique: { ...critique, concerns: ["SCR-004 is hard to reach."] },
      screens: [{ code: "SCR-004", title: "Check-in" }],
      locale: "en",
    });
    expect(english.get("[data-list='concerns']").text()).toContain("“Check-in” is hard to reach.");
  });

  it("names the workflows of the alternative by their titles in a stored observation", () => {
    const coded: ObservationFinding = {
      ...(findings[0] as ObservationFinding),
      summary: "Il flusso FLOW-002 dice che con Annulla la lista resta invariata.",
      recommended_action: "Allinea FLOW-002 e FLOW-009.",
    };
    const wrapper = mountList({
      findings: [coded],
      workflows: [{ code: "FLOW-002", title: "Nome vuoto e possibile duplicato" }],
    });
    const text = cards(wrapper)[0]?.text() ?? "";
    expect(text).toContain(
      "Il flusso «Nome vuoto e possibile duplicato» dice che con Annulla la lista resta invariata.",
    );
    expect(text).toContain("Allinea «Nome vuoto e possibile duplicato» e FLOW-009.");
  });

  it("says when the twin has not given an opinion yet", () => {
    const wrapper = mountList({ findings: null, critique: null });
    expect(wrapper.get("[data-testid='design-observation-empty']").text()).toBe(
      "Questo twin non ha ancora espresso un parere su questa alternativa.",
    );
  });

  it("speaks English when the page is in English", () => {
    const wrapper = mountList({ locale: "en" });
    expect(wrapper.get("h3").text()).toBe("Volontari al banco on DES-001 · Vista Scheda");
    expect(cards(wrapper)[0]?.text()).toContain("Major");
    expect(cards(wrapper)[0]?.text()).toContain("Actionability");
    expect(cards(wrapper)[0]?.text()).toContain("I confirm");
    expect(cards(wrapper)[0]?.text()).toContain("Not relevant");
  });

  it.each([
    ["it", ["Brief", "Requisiti", "Design"]],
    ["en", ["Brief", "Requirements", "Design"]],
  ] as const)(
    "names the places where a finding goes, no step by its old name and no team, in %s",
    (locale, targets) => {
      const first = findings[0] as ObservationFinding;
      const second = findings[1] as ObservationFinding;
      const review = mountList({
        locale,
        validations: {
          [key(first)]: { decision: "OWNER_CONFIRMED" },
          [key(second)]: { decision: "OWNER_DISMISSED" },
        },
      });
      const critiqueList = mountList({ locale, findings: null, critique });
      expect(
        review
          .get("[data-testid='design-observation-bring']")
          .findAll("button")
          .map((button) => button.text()),
      ).toEqual(targets);
      for (const wrapper of [review, critiqueList]) {
        expect(wrapper.text()).not.toMatch(OLD_STEP_NAMES);
        expect(wrapper.text()).not.toMatch(TEAM_WORDS);
      }
    },
  );

  it("has no axe violations for a review and for a critique", async () => {
    const first = findings[0] as ObservationFinding;
    const second = findings[1] as ObservationFinding;
    await expectAccessible(
      mountList({
        validations: {
          [key(first)]: { decision: "OWNER_CONFIRMED" },
          [key(second)]: { decision: "OWNER_DISMISSED" },
        },
      }).element,
    );
    await expectAccessible(mountList({ findings: null, critique }).element);
  });
});
