<p align="center">
  <img src="docs/brand/orchestwin-wordmark.svg" width="381" alt="OrchesTwin Studio">
</p>

<p align="center">
  Da un'idea scritta in due righe a un design approvato, giudicato da utenti sintetici e tenuto allineato al codice. Tu decidi a ogni passo.
</p>

## Obiettivo della tesi

OrchesTwin Studio è il prototipo di una tesi magistrale che studia un framework agentico per la progettazione centrata sull'utente: quanto un'intelligenza artificiale, invocata dal framework e mai addestrata, può portare un'idea fino a un design di qualità e con vere alternative, e quanto degli utenti sintetici (gli User Twin) possono fare da fonte continua di feedback lungo tutto il progetto, prima con il design e poi con il codice scritto fuori dallo Studio.

La domanda di ricerca ha tre parti:

1. **Qualità e varietà del design.** Un modello ospitato, guidato da un contesto costruito dal framework (brief, twin, requisiti, scelte visive da un catalogo ampio e verificato staticamente), propone alternative davvero diverse e disegna mockup che sembrano un prodotto professionale. Nessun modello viene addestrato o adattato: la varietà viene dallo schema, dal catalogo e dalla validazione.
2. **Twin come fonte di feedback.** I twin, ricavati dal brief e approvati dalla persona, giudicano ogni alternativa, rivedono il mockup scelto, discutono fra loro e rispondono alle domande; le loro osservazioni rientrano nel brief, nei requisiti o nel design, e il progetto itera.
3. **Allineamento durante lo sviluppo.** Dopo il design il progetto si sviluppa con gli strumenti abituali; la cartella di conoscenza vive nel repository del progetto e i twin diventano proattivi: criticano i commit rispetto ai requisiti e al design, il framework riconosce quando il codice cambia il design o i requisiti e propone il riallineamento, la persona approva.

La persona approva ogni passo con un gesto e nessuna generazione parte senza un suo gesto; ogni generazione registra modello, token e tempo. La prova finale è con utenti reali e confronta ciò che dicono i twin con ciò che dicono le persone sugli stessi design.

## Che cosa fa

Sei passi dal browser o dal terminale, ognuno approvato con un gesto:

1. **Brief**: un dialogo completa il brief una domanda alla volta; ciò che non dici viene proposto e segnato come ipotesi.
2. **Prospettive**: le competenze con cui guardare il progetto (esperienza d'uso, accessibilità, ingegneria del software, prodotto, sicurezza), ricavate dal brief e modificabili; ognuna porta le sue considerazioni quando si scrivono requisiti e design. Esperienza d'uso e accessibilità sono sempre applicate.
3. **User Twin**: utenti sintetici ricavati dal brief, con obiettivi, difficoltà e contesto d'uso; puoi fare loro domande.
4. **Definizione**: requisiti, storie e criteri di accettazione; una richiesta di modifica a parole produce una nuova versione da approvare.
5. **Design e valutazione**: alternative con scelte visive distinte, mockup in HTML disegnati dal modello, il parere di ogni twin su ogni alternativa, modifiche a parole con regole che restano valide, revisione dei twin sul mockup scelto.
6. **Dossier**: la cartella di conoscenza `orchestwin/`, versionata e verificabile, pubblicata dal brief in poi, con brief, prospettive, twin, requisiti, design, mockup, diagrammi Mermaid, tabelle CSV, schemi JSON e lo stato dello sviluppo (commit registrati, critiche dei twin, decisioni, attività per il codice).

Poi, durante lo sviluppo: `ut verify` fa esaminare i commit ai twin e chiede al modello se codice, Definizione e Design sono ancora allineati, e decidi tu (compiti per il codice, nuova versione del design o dei requisiti); `ut align` riallinea la parte che diverge nelle due direzioni, dal codice alla conoscenza con proposte da approvare una per una e, con `--from-design`, dal design al codice con un ordine di lavoro limitato alle differenze; `ut push` riporta nello Studio le modifiche fatte a mano nella cartella; `ut watch` osserva i commit; `ut mcp` dà la stessa conoscenza agli agenti dell'editor (Claude Code, Cursor, VS Code) attraverso il protocollo MCP.

Le generazioni le fa Claude Opus 5.5, invocato dallo Studio con la riga di comando di Claude Code installata sul computer (`claude --print`), che usa l'abbonamento di Claude di chi fa girare lo Studio. Modello e impegno di ragionamento si scelgono nel file dei provider. Il comando `ut` non chiama mai il modello: parla con lo Studio.

## Requisiti

- Windows 11 con PowerShell (gli script di avvio sono PowerShell; API, frontend e `ut` girano anche su macOS e Linux, dove la CI esegue i test).
- Python 3.12 o successivo (3.13 in locale, 3.14 nella CI), Node 26 (versione in `.nvmrc`), Docker Desktop per PostgreSQL 18.
- Per generare: Claude Code (2.1.280 o successivo) installato e collegato a un abbonamento di Claude. Senza, lo Studio funziona in modalità di sviluppo con generatori deterministici (vedi sotto).

## Installazione

1. Clona il repository e installa backend e frontend:

   ```powershell
   git clone https://github.com/AlexTesta00/orchestwin-studio.git
   cd orchestwin-studio
   py -3.13 -m venv .venv
   .venv\Scripts\Activate.ps1
   npm ci
   npm run install:python
   npm run install:frontend
   ```

   `install:python` installa il pacchetto in modalità modificabile e crea i comandi `ut`, `orchestwin-api` e `orchestwin-migrate`.

2. Crea `compose.env` nella radice (non è versionato):

   ```dotenv
   ORCHESTWIN_API_PORT=8000
   ORCHESTWIN_FRONTEND_PORT=8080
   ORCHESTWIN_POSTGRES_DB=orchestwin
   ORCHESTWIN_POSTGRES_USER=orchestwin
   ORCHESTWIN_POSTGRES_PASSWORD=<password locale>
   ORCHESTWIN_AUTH_JWT_SECRET=<segreto di almeno 32 caratteri>
   ```

3. Avvia il database e applica le migrazioni:

   ```powershell
   docker compose --env-file compose.env -f compose.yaml -f compose.studio.yaml up -d --wait database
   python scripts/studio_runtime.py migrate
   ```

4. Configura il modello. Installa Claude Code, esegui `claude` una volta e accedi con l'account del tuo abbonamento; poi copia `scripts/model-providers.claude-code.example.json` in `var/studio/model-providers.json` (modello e impegno di ragionamento sono lì). Non serve nessuna chiave: lo Studio esegue `claude --print` per ogni generazione, sul computer dove gira. Scrivi `var/studio/local-settings-hosted.json` con percorsi assoluti:

   ```json
   {
     "node": "C:\\Program Files\\nodejs\\node.exe",
     "providers_config_file": "C:\\...\\orchestwin-studio\\var\\studio\\model-providers.json"
   }
   ```

5. Avvia lo Studio e crea il tuo account dalla pagina di accesso:

   ```powershell
   ./scripts/start-studio.ps1 -Configuration var/studio/local-settings-hosted.json
   ```

   Lo Studio risponde su http://127.0.0.1:8080 (API su http://127.0.0.1:8000). Si ferma con `./scripts/stop-studio.ps1`. I progetti restano nel database.

### Senza modello

Per lavorare sull'interfaccia bastano database, API e server di sviluppo del frontend; le generazioni sono deterministiche e il design non si può scegliere né approvare, perché ha bisogno del modello:

```powershell
$env:ORCHESTWIN_DATABASE_URL = "postgresql+psycopg://orchestwin:<password>@127.0.0.1:15432/orchestwin"
$env:ORCHESTWIN_AUTH_JWT_SECRET = "<segreto>"
npm run start:api
npm run dev:frontend
```

Il frontend di sviluppo risponde su http://localhost:5173 e inoltra `/api` all'API su 8000.

### Con Docker

`compose.yaml` costruisce le immagini dell'API e del frontend (nginx che inoltra `/api`) e avvia database, migrazioni, API e frontend su 127.0.0.1:8080; `npm run test:compose` le costruisce e le prova. Per un server pubblico servono un proxy con TLS davanti al frontend, `ORCHESTWIN_CORS_ALLOWED_ORIGINS` sull'origine pubblica, `ORCHESTWIN_AUTH_REFRESH_COOKIE_SECURE=true` e la cartella dei modelli montata in `/models` con il manifesto.

## Dal terminale: `ut`

`ut` porta nel terminale gli stessi passi dello Studio e, dopo il design, accompagna lo sviluppo. Lavora nella cartella del progetto: `orchestwin/` è la cartella di conoscenza, `.orchestwin/` il legame con lo Studio e lo stato locale.

### Portare un progetto dello Studio nel tuo editor

Dal passo 6 del web (Dossier) si copiano gli stessi comandi, già compilati con l'indirizzo dello Studio e l'identificativo del progetto:

```powershell
ut login --studio http://127.0.0.1:8080
mkdir calcolatrice; cd calcolatrice
ut init --project <ID del progetto> --mode design-code
code .
```

`ut init --project` collega la cartella al progetto e scarica la cartella di conoscenza: non serve estrarre lo zip a mano. In Visual Studio Code il pannello OrchesTwin (estensione in `editors/vscode`, da costruire con `node editors/vscode/scripts/package-vsix.mjs` e installare con `code --install-extension`) mostra lo stato del progetto e lancia gli stessi comandi.

### Partire dal terminale

```powershell
ut login --studio http://127.0.0.1:8080
mkdir calcolo-mancia; cd calcolo-mancia
ut init                 # idea, brief, prospettive, user twin, requisiti: una domanda alla volta
ut design               # alternative, mockup nel browser, modifiche a parole, revisione dei twin, approvazione
git init
ut code                 # l'agente di programmazione scrive l'applicazione da requisiti e design
ut test --static .      # i criteri di accettazione verificati nei browser di questo computer
git add .; git commit -m "feat: prima versione"
ut verify               # i twin esaminano i commit, il modello dice se codice e design sono allineati, tu decidi
ut align                # riallinea la conoscenza dal codice, o il codice dal design con --from-design
ut twins update         # che cosa hanno imparato i twin dallo sviluppo
ut status
```

### I comandi e che cosa fanno

| Comando | Che cosa fa |
|---|---|
| `ut login` | Accede a uno Studio (`--studio INDIRIZZO`, `--email`, password chiesta a terminale o `--password-stdin`) e conserva l'accesso nella cartella dell'utente, mai nel progetto. Con lo Studio locale senza account non serve. |
| `ut logout` | Esce dallo Studio e toglie l'accesso da questo computer. |
| `ut status` | Mostra a che punto è il progetto: le sezioni con stato e versione, il prossimo passo, lo sviluppo (commit registrati, punto allineato, compiti aperti), il design a cui il codice è allineato, la conoscenza e le proposte in attesa. |
| `ut sections` | Mostra lo stato delle sezioni; `update` riaggancia alle versioni nuove quelle rimaste indietro, con i contenuti invariati, e le conferma (`ut --yes sections update` non chiede conferma). |
| `ut init` | Crea un progetto nella cartella in cui ti trovi e lo porta dall'idea alla Definizione approvata: brief con una domanda alla volta, prospettive, User Twin, requisiti, con la tua approvazione a ogni passo. `--name`, `--idea`, `--mode design|design-code`, `--answers FILE` per fare tutto senza domande, `--until brief|team|twins|requirements` per fermarsi prima, `--project ID` per collegare la cartella a un progetto che esiste già. Rilanciato nella stessa cartella riprende da dove era. |
| `ut design` | Lavora sul design: senza azione guida passo per passo; `show` mostra le alternative e il parere dei twin (`show --elements [SCR-002]` elenca gli elementi indicabili del mockup), `open N` apre le anteprime nel browser, `choose N` sceglie un'alternativa, `change "modifica a parole"` chiede una modifica (con `--rule` per una regola che deve restare valida; con `--screen SCR-002 --element ELM-012` la modifica è mirata a un elemento del mockup e dopo i twin dicono la loro su quell'elemento, salvo `--no-review`), `review` fa rivedere il design ai twin, `approve` approva, `regenerate` rigenera le alternative, `restore N` torna a una versione precedente creandone una nuova uguale, da approvare. |
| `ut definition` | Legge la Definizione approvata (`--all` con dettagli, collegamenti e fonti, `--json`); `journeys` chiede i journey per gli scenari. |
| `ut twins` | Gli User Twin: `list`, `show`, `persona` (la Persona derivata dal twin), `ask` fa una domanda o apre una conversazione, `review` fa rivedere il design scelto, `update` propone che cosa hanno imparato dalle ultime critiche (una generazione per twin), `learn` e `forget` scrivono o ritirano a mano un'osservazione senza spesa. |
| `ut evidence` | Le fonti testuali dei twin: `add` aggiunge un file `.txt` o `.md`, `revise` una versione nuova, `show` metadati e citazioni, `retire` ritira una fonte e riapre ciò che ne dipende, `delete-text` elimina i testi originali dopo il ritiro, `reassociate` riassocia un testo importato con lo stesso hash. |
| `ut archetypes` | Gli archetipi da cui nascono i twin: elenco, `add`, `edit`, `remove` (archivia conservando lo storico); dopo una modifica `ut init` rifà i twin e li fa approvare. |
| `ut package` | La cartella di conoscenza `orchestwin/`: senza azione lo stato; `publish` pubblica una versione nuova nello Studio e la scarica, `pull` scarica una versione già pubblicata, `verify` controlla la cartella senza lo Studio, `history` elenca le versioni, `import` crea nello Studio un progetto nuovo da una cartella o dal suo zip. |
| `ut push` | Invia allo Studio le modifiche fatte a mano nella cartella di conoscenza come versioni fornite da te, passando dalle differenze, dall'approvazione e dal gate; `--dry-run` mostra soltanto le differenze, `--stage` limita a un passo. |
| `ut verify` | Registra i commit nello Studio e li fa esaminare ai twin; il modello dice se codice, Definizione e Design sono allineati e decidi tu (allineato, compiti per il codice, nuova versione del design o dei requisiti, dopo). `--since COMMIT`, `--latest`, `--dry-run`, `--decide COMMIT` riapre una decisione, `--recheck` rifà gli esami fatti con versioni precedenti. |
| `ut align` | Il riallineamento nelle due direzioni. Dal codice alla conoscenza: legge le modifiche del codice e propone aggiornamenti alla Definizione, al Design e al piano dei test, che approvi uno per uno (`--pending` decide le proposte in attesa, `--since`, `--dry-run`). Dal design al codice, con `--from-design`: legge le differenze fra la versione del design a cui il codice è allineato e quella approvata, scrive un ordine di lavoro limitato a quelle e avvia il tuo agente di programmazione come `ut code` (`--max-agent-usd`). |
| `ut watch` | Osserva i commit del progetto e li registra nello Studio; con `--twins` li fa esaminare man mano, entro `--max-usd`; `--interval`, `--once`. |
| `ut mcp` | Avvia il server MCP `orchestwin-twins`, che dà agli agenti dell'editor la conoscenza approvata del progetto; `--config claude-code|cursor|vscode` mostra la configurazione da copiare; le operazioni che generano partono solo con `--spend`. |
| `ut test` | Verifica i criteri di accettazione sull'applicazione nei browser di questo computer (`--url INDIRIZZO` oppure `--static CARTELLA`, `--browser chrome|firefox|all`, `--criteria CODICI`), con un piano dei test dal Dossier (`--plan latest|new`), un rapporto con le schermate (`--open`) e le critiche dei twin (`--no-review` le salta, `--no-tasks` non chiede quali diventano compiti). |
| `ut tasks` | I compiti per il codice: elenco degli aperti (`--all` anche fatti e abbandonati), `add`, `done`, `drop`, `reopen`, `from-test` e `from-commit` trasformano in compiti i rilievi dei twin. |
| `ut code` | Affida lo sviluppo a un agente di programmazione esterno (Claude Code, oppure un comando tuo) con la cartella di conoscenza come contesto e i compiti aperti come ordine di lavoro; registra la versione del design da cui il codice nasce; non fa commit. |
| `ut why` | Mostra perché esiste un artefatto e che cosa ne dipende, da un codice (`REQ-001`, `ELM-012`…); `--all` citazioni, versioni e hash; `--offline` legge il Dossier locale senza lo Studio. |
| `ut validation` | Legge candidate da verificare, ipotesi operative, esiti delle sessioni con persone e percorsi degli scenari (`walkthrough SCENARIO`); `--offline` dal Dossier locale. |
| `ut activity` | Mostra i tempi e i passi del progetto ricavati dai fatti registrati; `--json` e `--csv FILE` li esportano; `start CODICE` e `stop` avviano e fermano una sessione di prova, durante la quale `ut` registra i propri comandi. |

- Ogni comando ha `--help`; `--lang it|en` sceglie la lingua, `--project-dir` indica la cartella del progetto quando non è quella in cui ti trovi.
- `ut login` chiede la password a terminale e non la salva; l'accesso sta in `%APPDATA%\orchestwin` su Windows, `~/Library/Application Support/orchestwin` su macOS, `~/.config/orchestwin` altrove.
- Prima di una generazione il comando dice il tempo stimato.
- Ciò che gira da solo non genera: `ut watch` fa esaminare i commit solo con `--twins`, `ut mcp` lascia agli agenti le domande ai twin, le revisioni e i test solo con `--spend`.

## Verifica

```powershell
npm run test                 # test Python, senza integrazione
npm run test:frontend
npm run check:python         # ruff check e ruff format
npm run quality:frontend     # eslint, prettier, tipi
```

I test di integrazione su PostgreSQL: `npm run test:integration:python` con le variabili `ORCHESTWIN_*_DATABASE_URL` sul database locale. La CI esegue tutto su Ubuntu, macOS e Windows con Python 3.14.

## Struttura del repository

| Cartella | Contenuto |
|---|---|
| `src/orchestwin` | backend: dominio dei progetti, prospettive, twin, requisiti, design, cartella di conoscenza, cambiamenti del codice e critiche, provider dei modelli, API FastAPI, comando `ut` (`cli`) |
| `src/test` | test Python, fixture, test di integrazione |
| `frontend` | applicazione Vue 3 dello Studio, in italiano e in inglese |
| `scripts` | avvio e arresto dello Studio, esempio di configurazione dei provider, verifiche |
| `environments/training` | ambiente per il valutatore locale, facoltativo |
| `docs/brand` | marchio |

## Licenza

Apache-2.0, vedi `LICENSE`.
