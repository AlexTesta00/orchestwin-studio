import { describe, expect, it } from "vitest";

import {
  elementNames,
  placeLabel,
  placeScreens,
  withScreenNames,
  type ScreenName,
} from "./screenNames";

const screens: ScreenName[] = [
  { code: "SCR-001", title: "Elenco degli ospiti" },
  { code: "SCR-004", title: "Registra gli ospiti" },
];

const elements = { "ELM-041": "Lista numerata", "ELM-018": "Salva" };

describe("placeLabel", () => {
  it("keeps the names of a stored place without the codes of screens and elements", () => {
    expect(placeLabel("SCR-001 Registra gli ospiti · ELM-018 Lista numerata")).toBe(
      "Registra gli ospiti · Lista numerata",
    );
    expect(placeLabel("SCR-002 Conferma operazione")).toBe("Conferma operazione");
    expect(placeLabel("  SCR-004: Impostazioni  ")).toBe("Impostazioni");
    expect(placeLabel("SCR-001 Registra gli ospiti · ELM-018")).toBe("Registra gli ospiti");
  });

  it("keeps a place made only of codes and a place without codes as they are", () => {
    expect(placeLabel("SCR-003")).toBe("SCR-003");
    expect(placeLabel("SCR-001 · ELM-018")).toBe("SCR-001 · ELM-018");
    expect(placeLabel("Il campo di ricerca in alto")).toBe("Il campo di ricerca in alto");
    expect(placeLabel("")).toBe("");
  });
});

describe("elementNames and placeScreens", () => {
  const places = [
    "SCR-001 Registra gli ospiti · ELM-018 Lista numerata",
    "SCR-002 Nuovo ospite · ELM-041 Salva",
    "SCR-001 Registra · ELM-018 Un altro nome",
    "SCR-003 Riepilogo · ELM-050",
    "Il campo di ricerca",
  ];

  it("collects the name that follows each element code, the first one when it repeats", () => {
    expect(elementNames(places)).toEqual({ "ELM-018": "Lista numerata", "ELM-041": "Salva" });
    expect(elementNames([])).toEqual({});
  });

  it("collects the title that follows each screen code", () => {
    expect(placeScreens(places)).toEqual([
      { code: "SCR-001", title: "Registra gli ospiti" },
      { code: "SCR-002", title: "Nuovo ospite" },
      { code: "SCR-003", title: "Riepilogo" },
    ]);
  });
});

describe("withScreenNames", () => {
  it("replaces a known screen code with its title between the marks of the language", () => {
    expect(withScreenNames("L'avviso di SCR-004 funziona.", { screens, locale: "it" })).toBe(
      "L'avviso di «Registra gli ospiti» funziona.",
    );
    expect(withScreenNames("The notice of SCR-004 works.", { screens, locale: "en" })).toBe(
      "The notice of “Registra gli ospiti” works.",
    );
  });

  it("keeps a code that is not known as it is", () => {
    expect(withScreenNames("Porta ora alla nuova SCR-005.", { screens, locale: "it" })).toBe(
      "Porta ora alla nuova SCR-005.",
    );
    expect(withScreenNames("Il flusso FLOW-002 dice che", { screens, locale: "it" })).toBe(
      "Il flusso FLOW-002 dice che",
    );
    expect(
      withScreenNames("In ELM-099 manca un titolo.", { screens, elements, locale: "it" }),
    ).toBe("In ELM-099 manca un titolo.");
    expect(withScreenNames("Vedi SCR-004.", { screens: [], locale: "it" })).toBe("Vedi SCR-004.");
  });

  it("does not repeat a title that already follows its code", () => {
    for (const text of [
      "SCR-004 Registra gli ospiti funziona",
      "SCR-004 «Registra gli ospiti» funziona",
      "SCR-004 (Registra gli ospiti) funziona",
      "SCR-004: registra gli ospiti funziona",
      "SCR-004 · Registra gli ospiti funziona",
      "«SCR-004» funziona",
    ]) {
      expect(withScreenNames(text, { screens, locale: "it" })).toBe(
        "«Registra gli ospiti» funziona",
      );
    }
    expect(
      withScreenNames("La schermata «Registra gli ospiti» (SCR-004) funziona", {
        screens,
        locale: "it",
      }),
    ).toBe("La schermata «Registra gli ospiti» funziona");
    expect(withScreenNames('SCR-004 "Registra gli ospiti" works', { screens, locale: "en" })).toBe(
      "“Registra gli ospiti” works",
    );
  });

  it("replaces several screens and elements in the same sentence", () => {
    expect(
      withScreenNames("Da SCR-001 si passa a SCR-004, poi in ELM-041 serve ELM-018.", {
        screens,
        elements,
        locale: "it",
      }),
    ).toBe(
      "Da «Elenco degli ospiti» si passa a «Registra gli ospiti», poi in «Lista numerata» serve «Salva».",
    );
    expect(withScreenNames("From SCR-001 to SCR-004 and SCR-005.", { screens, locale: "en" })).toBe(
      "From “Elenco degli ospiti” to “Registra gli ospiti” and SCR-005.",
    );
  });

  it("ignores a code inside a longer word and a longer word after the code", () => {
    expect(
      withScreenNames("SCR-004b e XSCR-004 restano, SCR-004 no.", { screens, locale: "it" }),
    ).toBe("SCR-004b e XSCR-004 restano, «Registra gli ospiti» no.");
    expect(
      withScreenNames("SCR-004 Registrazione", {
        screens: [{ code: "SCR-004", title: "Registra" }],
        locale: "it",
      }),
    ).toBe("«Registra» Registrazione");
  });

  it("replaces a known workflow code with its title and keeps an unknown one", () => {
    const workflows = [{ code: "FLOW-002", title: "Nome vuoto e possibile duplicato" }];
    expect(
      withScreenNames("FLOW-002 parla di maiuscole o spazi diversi", {
        screens,
        workflows,
        locale: "it",
      }),
    ).toBe("«Nome vuoto e possibile duplicato» parla di maiuscole o spazi diversi");
    expect(
      withScreenNames("Il flusso FLOW-002 dice che con Annulla la lista resta invariata", {
        screens,
        workflows,
        locale: "it",
      }),
    ).toBe(
      "Il flusso «Nome vuoto e possibile duplicato» dice che con Annulla la lista resta invariata",
    );
    expect(
      withScreenNames("FLOW-002 · Nome vuoto e possibile duplicato regge, FLOW-003 no.", {
        screens,
        workflows,
        locale: "it",
      }),
    ).toBe("«Nome vuoto e possibile duplicato» regge, FLOW-003 no.");
    expect(
      withScreenNames("The workflow FLOW-002 starts in SCR-004.", {
        screens,
        workflows,
        locale: "en",
      }),
    ).toBe("The workflow “Nome vuoto e possibile duplicato” starts in “Registra gli ospiti”.");
    expect(
      withScreenNames("SCR-009 e FLOW-002", {
        screens: [],
        workflows: [{ code: "SCR-009", title: "Non è un flusso" }],
        locale: "it",
      }),
    ).toBe("SCR-009 e FLOW-002");
    expect(
      withScreenNames("<b>FLOW-002</b>", {
        screens: [],
        workflows: [{ code: "FLOW-002", title: "<i>Annulla</i>" }],
        locale: "en",
      }),
    ).toBe("<b>“<i>Annulla</i>”</b>");
  });

  it("never reads the text or the titles as markup", () => {
    expect(
      withScreenNames("Apri <b>SCR-001</b> <script>x</script>", {
        screens: [{ code: "SCR-001", title: "<i>Home</i>" }],
        locale: "en",
      }),
    ).toBe("Apri <b>“<i>Home</i>”</b> <script>x</script>");
  });
});
