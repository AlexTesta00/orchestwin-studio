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

Poi, durante lo sviluppo: `ut align` fa criticare i commit ai twin e chiede al modello se codice, design e requisiti sono ancora allineati, e propone il riallineamento (una nuova versione del design o dei requisiti, oppure attività per il codice); `ut watch` osserva i commit; `ut mcp` dà la stessa conoscenza agli agenti dell'editor (Claude Code, Cursor, VS Code) attraverso il protocollo MCP.

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
ut align                # i twin esaminano i commit, il modello dice se codice e design sono allineati, tu decidi
ut twins update         # che cosa hanno imparato i twin dallo sviluppo
ut status
```

### I comandi e che cosa fanno

| Comando | Che cosa fa |
|---|---|
| `ut login` | Accede allo Studio (`--studio INDIRIZZO`) e conserva l'accesso nella cartella dell'utente, mai nel progetto. `ut logout` lo toglie. |
| `ut init` | Crea un progetto nella cartella in cui ti trovi e lo porta dall'idea ai requisiti approvati: brief con una domanda alla volta, prospettive, User Twin, requisiti. Con `--project ID` collega invece la cartella a un progetto che esiste già nello Studio e ne scarica la cartella di conoscenza. Con `--answers FILE` fa il percorso senza domande. |
| `ut design` | Guida nel design: alternative, mockup nel browser, parere dei twin, scelta e approvazione. Le azioni singole sono `show`, `open`, `choose`, `change "modifica a parole"` (con `--rule` per una regola che resta valida), `review`, `approve`. |
| `ut twins` | Elenca gli User Twin. `show` ne mostra uno, `ask` gli fa una domanda, `review` fa rivedere il design scelto, `update` propone che cosa i twin hanno imparato dallo sviluppo, `learn` e `forget` aggiungono o ritirano a mano un'osservazione. |
| `ut package` | Mostra lo stato della cartella di conoscenza. `publish` pubblica una versione nuova e la scarica in `orchestwin/`, `pull` scarica una versione già pubblicata, `verify` controlla la cartella senza lo Studio, `history` elenca le versioni, `import` crea un progetto da una cartella o dal suo zip. |
| `ut code` | Affida lo sviluppo a un agente di programmazione (Claude Code, oppure un comando tuo con `--agent custom --command`): scrive l'ordine di lavoro da requisiti, design e compiti aperti e avvia l'agente con i twin collegati come server MCP. `--headless` lo fa lavorare da solo, `--task` sceglie i compiti, `--dry-run` mostra l'ordine senza avviare nulla. |
| `ut test` | Verifica i criteri di accettazione sull'applicazione nei browser di questo computer (`--static CARTELLA` oppure `--url INDIRIZZO`), scrive un rapporto con le schermate e chiede ai twin di commentare l'esito. |
| `ut align` | Registra i commit nello Studio, li fa esaminare ai twin e dice se codice, design e requisiti sono ancora allineati; propone come riallinearli e decidi tu. `--recheck` rifà gli esami fatti con versioni precedenti di requisiti o design, `--dry-run` mostra che cosa verrebbe esaminato. |
| `ut tasks` | Mostra i compiti aperti per il codice. `add`, `done`, `drop`, `reopen` li cambiano; `from-test` e `from-commit` trasformano in compiti i rilievi dei twin. |
| `ut watch` | Osserva i commit e li registra; con `--twins` li fa esaminare man mano, entro il limite di esami fissato con `--max-usd`. |
| `ut mcp` | Avvia il server MCP `orchestwin-twins`, che dà agli agenti dell'editor la conoscenza approvata del progetto; `--config claude-code`, `cursor` o `vscode` mostra la configurazione da copiare. |
| `ut status` | Mostra le sezioni del progetto con il loro stato e il prossimo passo; `--offline` legge solo la cartella. |
| `ut sections` | Mostra le sezioni con il loro stato; `update` riaggancia alle versioni nuove ciò che è rimasto indietro (twin, requisiti, design) senza rigenerare, lo approva e pubblica la cartella. |

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
