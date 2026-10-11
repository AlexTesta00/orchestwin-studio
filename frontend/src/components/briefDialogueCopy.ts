import { briefFieldLabels } from "./briefFieldLabels";

export const briefDialogueCopy = {
  en: {
    chat: {
      analyst: "Requirements analyst",
      analystSays: "The analyst:",
      youSay: "You:",
      greeting:
        "Hi! I am the requirements analyst. Tell me your idea in two lines: what do you want to build?",
      typing: "The analyst is writing",
      shapeTitle: "The brief takes shape",
      shapeIntro: "Each answer fills a point. What is missing, I will propose at the end.",
      waiting: "Waiting for your answer",
      asking: "I am asking you now",
      openPoint: "You do not know yet: it stays an open point",
      startHint: "Then I will ask one question at a time and compose the brief.",
      answerHint: "Answer in your own words. Press Enter to send.",
      listHint: "One item per line. Press Send when you are done.",
      unknownHint: "Not sure yet?",
      seeBrief: "See the brief and the proposals",
      fields: briefFieldLabels.en,
    },
  },
  it: {
    chat: {
      analyst: "Analista delle esigenze",
      analystSays: "L'analista:",
      youSay: "Tu:",
      greeting:
        "Ciao! Sono l'analista delle esigenze. Raccontami l'idea in due righe: che cosa vuoi realizzare?",
      typing: "L'analista sta scrivendo",
      shapeTitle: "Il brief prende forma",
      shapeIntro: "Ogni risposta riempie un punto. Quello che manca te lo proporrò alla fine.",
      waiting: "In attesa della tua risposta",
      asking: "Te lo sto chiedendo ora",
      openPoint: "Non lo sai ancora: resta un punto aperto",
      startHint: "Poi ti farò una domanda alla volta e comporrò il brief.",
      answerHint: "Rispondi con parole tue. Premi Invio per mandarla.",
      listHint: "Un elemento per riga. Premi Invia quando hai finito.",
      unknownHint: "Non lo sai ancora?",
      seeBrief: "Vedi il brief e le proposte",
      fields: briefFieldLabels.it,
    },
  },
};
