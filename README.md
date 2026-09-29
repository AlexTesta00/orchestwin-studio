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

La persona approva ogni passo con un gesto e nessuna generazione a pagamento parte senza un suo gesto; ogni generazione registra modello, token, tempo e costo, entro tetti di spesa per generazione, per progetto e totali. La prova finale è con utenti reali e confronta ciò che dicono i twin con ciò che dicono le persone sugli stessi design.

## Che cosa fa

Sei passi dal browser o dal terminale, ognuno approvato con un gesto:

1. **Brief**: un dialogo completa il brief una domanda alla volta; ciò che non dici viene proposto e segnato come ipotesi.
2. **Squadra**: gli specialisti AI del progetto, con il motivo di ciascuno; designer UX/UI e specialista di accessibilità sono sempre presenti.
3. **User Twin**: utenti sintetici ricavati dal brief, con obiettivi, difficoltà e contesto d'uso; puoi fare loro domande.
4. **Requisiti**: requisiti, storie e criteri di accettazione; una richiesta di modifica a parole produce una nuova versione da approvare.
5. **Design**: alternative con scelte visive distinte, mockup in HTML disegnati dal modello, il parere di ogni twin su ogni alternativa, modifiche a parole con regole che restano valide, revisione dei twin sul mockup scelto.
6. **Cartella di conoscenza**: una cartella `orchestwin/` versionata e verificabile, pubblicata dal brief in poi, con brief, squadra, twin, requisiti, design, mockup, diagrammi Mermaid, tabelle CSV, schemi JSON e lo stato dello sviluppo (commit registrati, critiche dei twin, decisioni, attività per il codice).

Poi, durante lo sviluppo: `ut align` fa criticare i commit ai twin e chiede al modello se codice, design e requisiti sono ancora allineati, e propone il riallineamento (una nuova versione del design o dei requisiti, oppure attività per il codice); `ut watch` osserva i commit; `ut mcp` dà la stessa conoscenza agli agenti dell'editor (Claude Code, Cursor, VS Code) attraverso il protocollo MCP.

Le generazioni le fa un modello ospitato (Claude Opus 5.5 attraverso l'API di Anthropic; provider e modelli sono configurabili). Il comando `ut` non chiama mai un provider: parla con l'API dello Studio.

## Requisiti

- Windows 11 con PowerShell (gli script di avvio sono PowerShell; API, frontend e `ut` girano anche su macOS e Linux, dove la CI esegue i test).
- Python 3.12 o successivo (3.13 in locale, 3.14 nella CI), Node 26 (versione in `.nvmrc`), Docker Desktop per PostgreSQL 18.
- Una chiave API di Anthropic per generare. Senza chiave lo Studio funziona in modalità di sviluppo con generatori deterministici (vedi sotto).

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

4. Configura il modello. Copia `scripts/model-providers.example.json` in `var/studio/model-providers.json` (modelli, impegno di ragionamento, prezzi e tetti di spesa sono lì), metti la chiave nel file `.env` nella radice, ignorato da git:

   ```dotenv
   ORCHESTWIN_ANTHROPIC_API_KEY=<chiave>
   ```

   e scrivi `var/studio/local-settings-hosted.json` con percorsi assoluti:

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

`compose.yaml` costruisce le immagini dell'API e del frontend (nginx che inoltra `/api`) e avvia database, migrazioni, API e frontend su 127.0.0.1:8080; `npm run test:compose` le costruisce e le prova. Per un server pubblico servono un proxy con TLS davanti al frontend, `ORCHESTWIN_CORS_ALLOWED_ORIGINS` sull'origine pubblica, `ORCHESTWIN_AUTH_REFRESH_COOKIE_SECURE=true`, la cartella dei modelli montata in `/models` con il manifesto e la variabile della chiave nell'ambiente dell'API.

## Dal terminale: `ut`

```powershell
ut login --studio http://127.0.0.1:8000
mkdir calcolo-mancia; cd calcolo-mancia
ut init                 # idea, brief, squadra, user twin, requisiti: una domanda alla volta
ut design               # alternative, mockup nel browser, modifiche a parole, revisione dei twin, approvazione
ut twins ask 1 "Che cosa ti serve vedere per primo?"
ut package verify       # controlla la cartella orchestwin/ senza lo Studio
git init; git add .; git commit -m "feat: prima versione"
ut align                # i twin criticano i commit, il modello dice se codice e design sono allineati, tu decidi
ut watch --twins        # osserva i commit e li fa criticare man mano, fino a un tetto di spesa
ut mcp --config claude-code   # il server MCP per l'agente dell'editor
ut status
```

- `ut login` conserva l'accesso in un file nella cartella dell'utente (`%APPDATA%\orchestwin` su Windows, `~/Library/Application Support/orchestwin` su macOS, `~/.config/orchestwin` altrove), mai nel progetto; la password si scrive a terminale e non viene salvata.
- Nella cartella del progetto `orchestwin/` è la cartella di conoscenza, `.orchestwin/` il legame con lo Studio e lo stato locale.
- Sopra 0,50 USD di stima il comando mostra costo e credito rimasto e chiede conferma; `--yes` la salta. `--lang it|en` sceglie la lingua; `ut init --answers file.json` esegue il percorso senza domande.
- Ciò che gira da solo non spende: `ut watch` critica i commit solo se avviato con `--twins`, `ut mcp` risponde alle domande a pagamento solo se avviato con `--spend`.
- Ogni comando ha `--help`.

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
| `src/orchestwin` | backend: dominio dei progetti, squadra, twin, requisiti, design, cartella di conoscenza, cambiamenti del codice e critiche, provider dei modelli, API FastAPI, comando `ut` (`cli`) |
| `src/test` | test Python, fixture, test di integrazione |
| `frontend` | applicazione Vue 3 dello Studio, in italiano e in inglese |
| `scripts` | avvio e arresto dello Studio, esempio di configurazione dei provider, verifiche |
| `environments/training` | ambiente per il valutatore locale, facoltativo |
| `docs/brand` | marchio |

## Licenza

Apache-2.0, vedi `LICENSE`.
