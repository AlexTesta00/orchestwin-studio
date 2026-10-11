export const designCritiqueCopy = {
  it: {
    title: "Critica di un design esistente",
    intro:
      "Porta un'immagine di un'interfaccia già fatta: i twin ti dicono che cosa funziona per loro e che cosa cambierebbero.",
    file: "Immagine del design",
    limit: "Un'immagine PNG o JPEG, al massimo 5 MB.",
    titleLabel: "Titolo (facoltativo)",
    titleHint: "Se lo lasci vuoto, uso il nome del file.",
    ask: "Chiedi il parere dei twin",
    askTime: "Tempo stimato: circa 3 minuti.",
    twinsMissing: "Prima approva i twin.",
    loading: "Carico le critiche precedenti…",
    uploading: "Carico l'immagine…",
    critiquing: "I twin guardano il design…",
    received: "Parere ricevuto in {seconds} s.",
    kinds: { IMAGE: "Immagine caricata", WEB_PAGE: "Pagina web" },
    supplied: "Immagine fornita",
    screen: "Schermata {n}",
    screenWidth: "Schermata {n} · {width} px",
    shotAlt: "{title}, {screen}",
    shotMissing: "L'anteprima di questa schermata non si può mostrare.",
    verdictsOn: "Il verdetto dei twin su {screen}",
    verdicts: { WORKS: "Funziona per me", SLOWS: "Mi rallenta", BLOCKS: "Mi blocca" },
    note: "Sono ipotesi dei twin da pesare, non prove.",
    noFindings: "Nessuna osservazione su questo design.",
    severity: {
      critical: "Critica",
      major: "Importante",
      moderate: "Moderata",
      minor: "Minore",
      observation: "Osservazione",
    },
    todo: "Cosa fare",
    gaps: "Non posso giudicare",
    someone: "Un twin",
    costSubscription: "Parere in {seconds} s · incluso nell'abbonamento",
    costPaid: "Parere in {seconds} s · {cost}",
    latest: "Torna all'ultima critica",
    history: "Critiche precedenti ({n})",
    redrawText:
      "Il designer disegna una nuova versione del mockup con l'aspetto di questo design: poi decidi tu se applicarla.",
    redraw: "Ridisegna come mockup",
    redrawTime: "Tempo stimato: circa 7 minuti.",
    redrawMissing:
      "Per ridisegnare serve un design dello Studio con il suo mockup: prepara il design, poi ridisegna.",
    redrawBusy:
      "Un'altra modifica del design è in corso o aspetta la tua decisione: ridisegna quando è conclusa.",
    errors: {
      DESIGN_CRITIQUE_FILE_TYPE: "Scegli un'immagine PNG o JPEG.",
      DESIGN_CRITIQUE_FILE_TOO_LARGE: "L'immagine supera 5 MB: scegline una più leggera.",
      DESIGN_CRITIQUE_IMAGE_TOO_LARGE:
        "L'immagine è troppo grande: al massimo 5 MB e 8000 pixel per lato.",
      DESIGN_CRITIQUE_IMAGE_INVALID:
        "Lo Studio non riesce a leggere questa immagine: scegli un altro file PNG o JPEG.",
      DESIGN_CRITIQUE_SOURCE_INVALID:
        "Lo Studio non ha accettato l'immagine o il titolo: controllali e riprova.",
      DESIGN_CRITIQUE_SOURCE_NOT_FOUND: "L'immagine non è più nello Studio: caricala di nuovo.",
      DESIGN_CRITIQUE_TWINS_REQUIRED: "Prima approva i twin: sono loro a dare il parere.",
      DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED:
        "Il modello collegato allo Studio non può guardare le immagini: chi gestisce lo Studio deve collegare Claude Code.",
      DESIGN_REVIEWER_NOT_CONFIGURED:
        "Il modello che interpreta i twin non è collegato, quindi i twin non possono dare il loro parere.",
      DESIGN_CRITIQUE_FAILED: "Il parere dei twin non è arrivato. Riprova tra poco.",
      DESIGN_CRITIQUE_INVALID: "La risposta dei twin non si poteva usare. Riprova tra poco.",
      DESIGN_CRITIQUE_LOAD_FAILED:
        "Le critiche precedenti non si possono leggere adesso. Chiudi e riapri questo riquadro per riprovare.",
      DESIGN_CRITIQUE_UPLOAD_FAILED: "L'immagine non è stata caricata. Riprova tra poco.",
    },
  },
  en: {
    title: "Critique of an existing design",
    intro:
      "Bring an image of an interface that already exists: the twins tell you what works for them and what they would change.",
    file: "Image of the design",
    limit: "A PNG or JPEG image, at most 5 MB.",
    titleLabel: "Title (optional)",
    titleHint: "If you leave it empty, I use the name of the file.",
    ask: "Ask the twins for their opinion",
    askTime: "Estimated time: about 3 minutes.",
    twinsMissing: "Approve the twins first.",
    loading: "Loading the earlier critiques…",
    uploading: "Uploading the image…",
    critiquing: "The twins are looking at the design…",
    received: "Opinion received in {seconds} s.",
    kinds: { IMAGE: "Uploaded image", WEB_PAGE: "Web page" },
    supplied: "Supplied image",
    screen: "Screen {n}",
    screenWidth: "Screen {n} · {width} px",
    shotAlt: "{title}, {screen}",
    shotMissing: "The preview of this screen cannot be shown.",
    verdictsOn: "The verdict of the twins on {screen}",
    verdicts: { WORKS: "Works for me", SLOWS: "Slows me down", BLOCKS: "Blocks me" },
    note: "They are hypotheses of the twins to weigh, not evidence.",
    noFindings: "No observation on this design.",
    severity: {
      critical: "Critical",
      major: "Major",
      moderate: "Moderate",
      minor: "Minor",
      observation: "Observation",
    },
    todo: "What to do",
    gaps: "I cannot judge",
    someone: "A twin",
    costSubscription: "Opinion in {seconds} s · included in the subscription",
    costPaid: "Opinion in {seconds} s · {cost}",
    latest: "Back to the latest critique",
    history: "Earlier critiques ({n})",
    redrawText:
      "The designer draws a new version of the mockup with the look of this design: then you decide whether to apply it.",
    redraw: "Redraw as a mockup",
    redrawTime: "Estimated time: about 7 minutes.",
    redrawMissing:
      "To redraw you need a Studio design with its mockup: prepare the design, then redraw.",
    redrawBusy:
      "Another change of the design is in progress or waiting for your decision: redraw once it is settled.",
    errors: {
      DESIGN_CRITIQUE_FILE_TYPE: "Choose a PNG or JPEG image.",
      DESIGN_CRITIQUE_FILE_TOO_LARGE: "The image is larger than 5 MB: choose a lighter one.",
      DESIGN_CRITIQUE_IMAGE_TOO_LARGE:
        "The image is too large: at most 5 MB and 8000 pixels per side.",
      DESIGN_CRITIQUE_IMAGE_INVALID:
        "The Studio cannot read this image: choose another PNG or JPEG file.",
      DESIGN_CRITIQUE_SOURCE_INVALID:
        "The Studio did not accept the image or the title: check them and try again.",
      DESIGN_CRITIQUE_SOURCE_NOT_FOUND: "The image is no longer in the Studio: upload it again.",
      DESIGN_CRITIQUE_TWINS_REQUIRED:
        "Approve the twins first: they are the ones who give the opinion.",
      DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED:
        "The model connected to the Studio cannot look at images: whoever manages the Studio has to connect Claude Code.",
      DESIGN_REVIEWER_NOT_CONFIGURED:
        "The model that plays the twins is not connected, so the twins cannot give their opinion.",
      DESIGN_CRITIQUE_FAILED: "The opinion of the twins did not arrive. Try again in a moment.",
      DESIGN_CRITIQUE_INVALID: "The answer of the twins could not be used. Try again in a moment.",
      DESIGN_CRITIQUE_LOAD_FAILED:
        "The earlier critiques cannot be read now. Close and open this box again to retry.",
      DESIGN_CRITIQUE_UPLOAD_FAILED: "The image was not uploaded. Try again in a moment.",
    },
  },
} as const;
