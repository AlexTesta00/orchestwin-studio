<p align="center">
  <img src="docs/brand/orchestwin-wordmark.svg" width="372" alt="OrchesTwin Studio">
</p>

<p align="center">
  Un'idea diventa un'applicazione. Tu decidi a ogni passo.
</p>

## Cos'è

OrchesTwin Studio è una piattaforma multi-agente governata da una persona, sviluppata come tesi in *Agentic User-Centred Design*. Orchestra una squadra di agenti AI lungo otto passi: dal brief scritto dal committente fino a un'applicazione web generata, eseguita e verificata in una sandbox.

Due regole reggono tutto il percorso:

- **Niente accade senza il committente.** Ogni passo termina con un cancello umano: l'AI propone, la persona approva o chiede una revisione.
- **Un'ipotesi resta tale finché non è verificata.** Le opinioni degli *User Twin* (utenti sintetici derivati dal brief), i requisiti e le critiche al design sono proposte etichettate come ipotesi. La prova è solo ciò che la sandbox osserva: test superati, controlli nel browser, audit di accessibilità.

Gli otto passi: Brief → Squadra → User Twin → Requisiti → Design → Architettura → Sorgenti → Esecuzione. Alla fine il progetto approvato si esporta come archivio con manifesto, hash e provenienza di ogni artefatto.

## Architettura in breve

- **Backend** Python (FastAPI, SQLAlchemy, Alembic) su PostgreSQL 18: cancelli umani, artefatti immutabili, evidenze di esecuzione e ricevute di ogni chiamata ai modelli.
- **Frontend** Vue 3, TypeScript, Pinia, Tailwind, con interfaccia in italiano e inglese.
- **Pacchetto di design** zip deterministico con brief, squadra, twin, requisiti e design approvati, in Markdown e JSON, da portare nel proprio ambiente di sviluppo.
- **Modelli** un valutatore locale (Qwen3-4B con adapter LoRA, in WSL2) e un proposer remoto (Qwen3-Coder-30B servito con vLLM su RunPod), entrambi con decodifica strutturata.

## Requisiti

- Windows 11 con PowerShell, Docker Desktop e WSL2 (Ubuntu) per i modelli locali.
- Python 3.13 e Node 22.14 o successivi.
- Una GPU NVIDIA per il valutatore locale; un account RunPod per il proposer remoto (opzionale in modalità sviluppo).

## Installazione

1. Clona il repository e crea l'ambiente Python:

   ```powershell
   git clone https://github.com/AlexTesta00/orchestwin-studio.git
   cd orchestwin-studio
   py -3.13 -m venv .venv
   .venv\Scripts\Activate.ps1
   npm ci
   npm run install:python
   npm run install:frontend
   ```

2. Crea il file `compose.env` nella radice del repository (non viene versionato):

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

4. Prepara i modelli. L'ambiente WSL2 del valutatore è descritto in `environments/training/README.md`; l'adapter verificato va indicato in `var/studio/local-settings.json` insieme al percorso di Node:

   ```json
   {
     "node": "C:\\Program Files\\nodejs\\node.exe",
     "adapter": "C:\\...\\evaluator-adapter",
     "weights_sha256": "<sha256 di adapter_model.safetensors>",
     "config_sha256": "<sha256 di adapter_config.json>"
   }
   ```

   Per il proposer remoto, `scripts/cloud_proposer.py` crea, prepara e serve il pod su RunPod (`create`, `bootstrap`, `serve`, `tunnel`, `stop`, `terminate`) leggendo la chiave dalla variabile d'ambiente `ORCHESTWIN_RUNPOD_API_KEY`; il pod scelto viene registrato in `local-settings.json` con `remote_pod` e `remote_proposal_config_file`.

5. Avvia lo Studio:

   ```powershell
   ./scripts/start-studio.ps1
   ```

   Lo Studio è raggiungibile su http://127.0.0.1:8080 e si ferma con `./scripts/stop-studio.ps1` (con `-StopPod` spegne anche il pod remoto).

### Modalità sviluppo senza modelli

Per lavorare sull'interfaccia bastano database, API e server di sviluppo del frontend:

```powershell
$env:ORCHESTWIN_DATABASE_URL = "postgresql+psycopg://orchestwin:<password>@127.0.0.1:15432/orchestwin"
$env:ORCHESTWIN_AUTH_JWT_SECRET = "<segreto>"
npm run start:api
npm run dev:frontend
```

Il frontend di sviluppo risponde su http://localhost:5173 e inoltra le chiamate `/api` all'API su 8000.

## Verifica

```powershell
npm run test
npm run test:frontend
npm run lint:python
npm run lint:frontend
npm run type-check:frontend
```

I test di integrazione su PostgreSQL si eseguono con `npm run test:integration:python` dopo aver impostato le variabili `ORCHESTWIN_*_DATABASE_URL` sul database locale.

## Struttura del repository

| Cartella | Contenuto |
|---|---|
| `src/orchestwin` | backend: dominio, persistenza, API, modelli, pacchetto di design |
| `src/test` | test Python, fixture e test di integrazione |
| `frontend` | applicazione Vue dello Studio |
| `environments/training` | ambiente WSL2 per addestramento e serving dei modelli locali |
| `scripts` | launcher dello Studio, controllo del pod remoto, verifiche |
| `docs/brand` | marchio |

## Licenza

Apache-2.0, vedi `LICENSE`.
