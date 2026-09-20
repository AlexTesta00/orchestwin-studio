# OrchesTwin Studio

Piattaforma di tesi per un processo di progettazione centrato sull'utente, assistito da agenti e User Twin, con approvazioni umane, artefatti versionati ed esecuzione verificabile del software generato.

Questo README riassume **l'intero progetto**, le funzionalità implementate, le prove disponibili e il lavoro ancora aperto. Viene aggiornato al completamento delle attività. Codice implementato, servizio disponibile, qualità del modello e validazione scientifica sono stati distinti.

**Aggiornamento: 20 settembre 2026, Europe/Rome.** Branch di riferimento: `sprint/12-case-studies-expert-evaluation`; base applicativa ora committata in HEAD `2f25d131e0313d2b87ebeab31a842b5018c815bc`. Il README resta intenzionalmente non committato e viene aggiornato durante i sei passaggi autorizzati; nuove modifiche preparatorie vengono riportate separatamente.

## Avanzamento dei sei passaggi autorizzati

**Ripresa del 20 settembre conclusa con esiti diagnostici negativi conservati.** La prova BF16 dalla GUI e le tre riparazioni JVM sono state eseguite; nessuna ha prodotto un'applicazione completamente verificata. I controlli hanno respinto gli output non conformi. Il pod è spento e la demo è tornata ai modelli reali locali. Nessun training, promozione del candidato, staging, commit o push è stato eseguito durante questa ripresa.

### Punto di ripresa aggiornato durante il lavoro

Situazione verificata il **20 settembre, circa 12:16 Europe/Rome**:

- **Repository:** HEAD `2f25d131e0313d2b87ebeab31a842b5018c815bc`; modifiche ancora locali. Commit e push restano all'utente.
- **Studio locale:** sessione `var/studio/session-20260920-111212`, indirizzo `http://127.0.0.1:8080`. API ripristinata esplicitamente sulla configurazione locale `models.json`, salute HTTP 200; frontend, modelli locali e database conservati. Ricevuta `var/studio/resume-20260920-01/api-restoration-receipt.json`. Nessun fallback fake.
- **Nuova calcolatrice Web:** cinque risposte native BF16 complete. JavaScript e test accettati sintatticamente; primo HTML respinto per etichetta accessibile, unico retry respinto per duplicazione di `ELM-002`. Zero revisioni complete e **17 casi browser non eseguiti**. Un controllo supplementare isolato dei soli JavaScript nativi ha eseguito **16 test, zero passati**: mancano le funzioni esportate attese dai test. Non è una prova browser né una pubblicazione Level D. Report `experiments/studio-demo/calculator-bf16-gui-verification-20260920.json`; fotografia DB con 345 file verificati, 23 generazioni complessive, nessun oggetto mancante.
- **Riparazioni JVM:** una richiesta reale per ciascun linguaggio. Kotlin produce una revisione ma fallisce `BUILD` per due importazioni `kotlin.test` nel sorgente principale; Scala produce una revisione ma fallisce `STATIC_CHECKS` con otto errori del compilatore; Java restituisce entrambi i file identici agli originali ed è respinto prima di creare una revisione. **Zero pipeline complete; 102 controlli indipendenti V2 non eseguiti.** I 140 file storici restano invariati. Report `experiments/studio-demo/jvm-calculator-bf16-repair-results-20260920.json`; archivio nativo di 65 file verificato. Nessun sorgente del modello corretto manualmente.
- **Runpod:** otto richieste complessive nella ripresa, cinque Web e tre JVM. Recuperate otto ricevute/log senza file segreti, archivio SHA-256 `60fce121b7f299016466f7be5b8eb00f0b1abd490a9b05bdea84d6af4fbe3818`. Pod `26co8lvd4b2aml` verificato **EXITED** alle 12:08 Europe/Rome tramite API e controllo locale indipendente, prima della scadenza di protezione delle 12:50. Tunnel terminato; volume persistente conservato. La seconda ripresa aveva tetto USD 3,50 nel limite complessivo circa USD 7; non è un nuovo training.
- **Runner:** cleanup confermato delle esecuzioni Kotlin/Scala e del probe JavaScript. Dopo la pulizia, readiness JVM `runtime_inputs_ready: true`, nessun blocco. Un primo avvio Scala contemporaneo al setup Kotlin era stato respinto prima dell'esecuzione: la rete richiede accesso esclusivo e le due pipeline sono poi state eseguite sequenzialmente.
- **CI e Web Level D:** correzione CI locale pronta, ancora in attesa di commit/push dell'utente. La campagna formale non è stata eseguita sulla CI fallita.

Le prove precedenti interrotte restano separate: `experiments/model-proposals/coder-bf16-comparison-20260920.json` conserva l'interruzione, non un confronto finale. Ricevute della ripresa e dello spegnimento: `C:/Users/alext/.codex/visualizations/2026/09/12/01a09597-4b2a-7a30-bc8f-e6e729d91f04/coder-source-resume-2f25d13-20260920-02`. L'identità cloud ora offline è `proposal-base-2a9ec8f5-a406-4dfc-bf10-b2da4b2d01aa`: 531 tensori BF16 su CUDA, senza offload; revisione del modello osservata e tokenizer `REQUEST_PIN_ONLY`.

| Passaggio | Stato al controllo del 20 settembre | Condizione ancora aperta |
|---|---|---|
| 1. Commit e CI | CI `35494854769` fallita; isolamento corretto localmente in due file, 107 test superati nello stesso ambiente CI | Commit/push dell'utente e CI pertinente superata |
| 2. Modello sorgenti più capace | Diagnosi 4-bit, confronto BF16 interrotto e nuova prova BF16 GUI/JVM conservati; candidato non promosso | Miglioramento funzionale misurato, non solo precisione o disponibilità |
| 3. Nuova calcolatrice dalla GUI | Tentativo concluso con fallimento; retry verificato dal vivo; probe JavaScript 0/16 | Revisione completa coerente con mockup, integrazione codice/test e 17 casi browser superati |
| 4. Riparazioni JVM | Tre tentativi conclusi; due revisioni non compilabili, un output invariato respinto; cleanup e originali verificati | Pipeline complete e 34 controlli indipendenti per linguaggio superati |
| 5. Web Level D | Preflight: 112 test superati e tre immagini esatte disponibili; CI corrente fallita | CI pertinente, matrice di 32 tentativi sui cinque profili e pubblicazione verificata |
| 6. Valutazione della tesi | Piano operativo: 15 input fissati tramite hash, tre casi e protocollo esperti; otto test superati | Esecuzioni comparabili e valutazioni di partecipanti reali |

Una diagnosi conclusa con fallimento non equivale al raggiungimento dell'obiettivo funzionale. La correzione CI isola i test che costruiscono un runtime reale dalle impostazioni `FAKE_DETERMINISTIC` delle altre fixture; non allenta i vincoli di produzione. Non riavviare prove cloud identiche né sovrascrivere gli esiti negativi.

## Stato attuale

| Area | Verificato | Limite o attività aperta |
|---|---|---|
| Backend e frontend | Piattaforma, persistenza e workflow presenti; ultima regressione frontend: 247 test superati, controlli TypeScript/lint/formattazione superati | Non tutti i percorsi sono stati provati integralmente con modelli reali |
| Modelli reali | Proposer e valutatore configurati; identità, richieste e risposte native conservate | Disponibilità non equivale a qualità delle proposte |
| Demo Web esistente | Calcolatrice rivista con assistenza: 16 verifiche browser superate | Non è un successo autonomo del modello né una pubblicazione Level D |
| Nuova calcolatrice Web | Percorso GUI reale e nuova prova BF16 con cinque risposte native; tentativi precedenti conservati | Entrambi gli HTML BF16 respinti dal contratto del mockup; nessuna revisione completa e 17 casi di accettazione non eseguiti |
| Fine-tuning proposer | Pilot QLoRA completato e confrontato con il modello base | Candidato respinto; non selezionato per la demo |
| Dataset proposer | V1/V2/V3 verificati, con famiglie di valutazione separate | Diversità ancora limitata; V3 congelato sul contratto V13, non ancora usato per un nuovo training |
| Motore JVM | Campagne Java/Kotlin/Scala concluse, 51 evidenze pubblicate; API HTTP 200 con tre profili `VALIDATED_LEVEL_D` e 17 riferimenti ciascuno | Qualifica il motore, non le calcolatrici del modello; la disponibilità runtime del catalogo resta `NOT_CHECKED` |
| Calcolatrice Kotlin | JAR originale: 20/20 controlli supplementari e main; riparazione BF16 eseguita | Originale `FAILED:TEST`; nuova revisione `FAILED:BUILD` per importazioni non risolte |
| Calcolatrice Scala | Originale e riparazione BF16 eseguiti e conservati | Compilazione fallita: nove errori originali, otto nella riparazione; nessun controllo aritmetico eseguito |
| Calcolatrice Java | JAR originale: 20/20 controlli supplementari e main; risposta BF16 conservata | Originale `FAILED:TEST`; tentativo di riparazione senza modifiche respinto; limite sui divisori piccoli ancora aperto |
| Web Level D | Runner e configurazione preparati e controllati localmente | Mancano CI pertinente alla revisione e campagna completa; nessuna promozione sulla base di una CI vecchia |

## Scopo e percorso del prodotto

Il proprietario definisce il progetto, esamina le proposte degli agenti e approva gli artefatti che guidano i passaggi successivi. Le fasi visibili sono:

1. **Idea:** problema, destinatari, obiettivi e vincoli.
2. **Team:** proposta e approvazione dei ruoli.
3. **Utenti:** personas, User Twin, contesto e ipotesi.
4. **Funzionalità:** requisiti, scenari e criteri di accettazione.
5. **Aspetto:** alternative di design e mockup interattivi.
6. **Soluzione:** architettura e revisione delle scelte.
7. **Creazione:** sorgenti versionati, controlli, esecuzione e riparazioni governate.
8. **Risultato:** anteprima o artefatti, valutazioni, evidenze e revisione finale.

Le fasi dell'interfaccia non sostituiscono i gate del dominio. Un'approvazione è legata alla versione e all'hash di un artefatto; una nuova revisione non eredita automaticamente una validazione del contenuto precedente. Il proprietario mantiene le decisioni sulle proposte e sulle operazioni governate.

## Architettura e mappa del repository

| Percorso | Responsabilità implementata |
|---|---|
| `src/orchestwin/identity` | Registrazione, password Argon2, JWT, sessioni e autorizzazione per proprietario |
| `src/orchestwin/projects` | Progetti, brief, chiarimenti e contesto |
| `src/orchestwin/agents` | Composizione e ruoli dell'Agent Team |
| `src/orchestwin/twins` | Personas, User Twin e snapshot della modellazione degli utenti |
| `src/orchestwin/artifacts` | Requisiti, design, mockup, architettura, piani di test, tracciabilità e revisioni sorgenti |
| `src/orchestwin/workflow` | Orchestrazione, gate, operazioni, eventi, checkpoint, ripresa, riparazione e approvazione finale |
| `src/orchestwin/models` | Adapter reali, contratti delle proposte, identità, generazione strutturata e registrazione delle evidenze |
| `src/orchestwin/evaluation` | Valutazioni dei Twin, contenuti autorizzati, aggregazione, conflitti e casi studio |
| `src/orchestwin/sandbox` | Contratti Docker, isolamento, profili, limiti e archivio delle evidenze |
| `src/orchestwin/web_execution` | Runner, sorgenti, esecuzione e qualificazione Web |
| `src/orchestwin/jvm_execution` | Dipendenze, launcher, fasi isolate e qualificazione Java/Kotlin/Scala |
| `src/orchestwin/training` | Contratti applicativi di training e qualificazione |
| `src/orchestwin/persistence` | SQLAlchemy/PostgreSQL e Alembic; migrazioni presenti fino a `0044_source_design_retry` |
| `src/orchestwin/api` | API FastAPI, configurazione dei runtime, catalogo dei profili e accesso ai moduli |
| `frontend` | Vue, TypeScript, Pinia, router, traduzioni, componenti e test Vitest |
| `environments/training` | Ambiente separato Linux/WSL per inferenza, dataset, QLoRA, confronto e serving |
| `infra` | Immagini, ricette, proxy e infrastruttura dei runner |
| `scripts` | Avvio locale, verifiche, campagne e raccolta delle evidenze |
| `src/test` | Test backend, integrazione PostgreSQL e fixture dei profili |
| `experiments` | Report versionabili di modelli, demo, runner e casi studio |
| `var/studio` | Configurazioni e risultati locali; non è un archivio distribuito da Git |
| `.github/workflows/ci-cd.yml` | Pipeline di controlli, build e integrazione continua |

Backend: Python, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Alembic e LangGraph. Frontend: Vue 3, TypeScript, Pinia, Vue Router e Vite. Le versioni esatte sono nei manifest e nei lock del repository. Non esiste attualmente una directory `docs/`; i riferimenti operativi aggiuntivi sono i README sotto `infra/web-runners` ed `environments/training`.

## Implementazione e verifiche per area

### Identità, progetti e persistenza

Sono implementati autenticazione e gestione delle sessioni, accesso ai dati per proprietario, progetti/brief, repository persistenti e migrazioni. Le proposte vengono collegate agli artefatti con persistenza atomica. Sono presenti validazione dei dati e gestione degli errori API.

Restano da verificare sistematicamente i percorsi autenticati e di recupero dopo errore nella configurazione finale della demo, oltre a backup e ripristino. I test PostgreSQL richiedono un database di test dedicato; il database della demo non deve essere usato come sostituto.

È implementato anche l'ingresso di un progetto esistente (**brownfield**) tramite archivio: inventario dei file, hash, versioni, revisione delle capacità e scelta del profilo. Importare un archivio non autorizza automaticamente a eseguirlo. Questo percorso richiede ancora una prova completa della demo finale su un progetto rappresentativo, separata dal caso della calcolatrice creata da zero.

### Workflow, Agent Team e interfaccia

Sono presenti gate con motivazioni, revisioni, checkpoint/eventi, operazioni di esecuzione e revisione finale. Il frontend offre una progressione compatta, linguaggio rivolto al cliente, icone dei Twin, una fase principale alla volta e dettagli tecnici secondari.

È stata corretta una race fra refresh dell'autenticazione, letture precedenti e approvazioni che poteva mostrare uno stato obsoleto. La regressione frontend completa ha superato 247 test. Restano da provare il percorso autonomo completo, il recupero dopo riavvio e i cicli di rifiuto/riparazione su nuovi progetti reali.

### Personas, User Twin e valutazioni

Le proposte ricevono il brief approvato e i suoi riferimenti. Risposte strutturate, ipotesi, campi sconosciuti e collegamenti sono conservati. Sono implementate valutazioni indipendenti dei Twin, aggregazione, conflitti, lacune di evidenza e domande per la validazione umana.

Il paper (sezioni 3.3, 4.1 e 4.3; tabella 2) descrive agenti con un punto di vista di ruolo, interrogabili e aggiornabili; non attribuisce loro coscienza o esperienza soggettiva. I profili possono differire anche usando lo stesso modello: contesto, obiettivi, vincoli ed evidenze distinguono le prospettive. La fedeltà effettiva a ciascun ruolo richiede verifica.

**Iterare fra Twin e riaddestrare i pesi sono operazioni diverse.** Il workflow può raffinare artefatti attraverso revisioni e feedback; il fine-tuning richiede una pipeline separata con dati, split, candidato e confronto. Ogni ciclo deve conservare versioni, motivazioni e condizioni di arresto.

Restano da verificare coerenza dei giudizi, specificità dei ruoli, gestione dell'incertezza e confronto con esperti/utenti. I Twin della demo contengono ancora ipotesi non validate. Le approvazioni delegate all'agente per una prova tecnica non costituiscono uno studio con partecipanti umani.

**Chat con lo User Twin — estensione discussa il 20 settembre, non implementata.** Nell'interfaccia attuale non esiste una conversazione dedicata con il singolo Twin. Il flusso proposto permette di selezionare un Twin, chiedergli chiarimenti o criticità rispetto a requisiti/mockup correnti e ottenere una proposta di miglioramento. Il Twin esprime il punto di vista del profilo simulato; designer e sviluppatori applicano la proposta approvata come nuova versione. Servono conversazioni persistenti per proprietario/progetto/Twin, riferimenti alle versioni degli artefatti, gestione dei contesti diventati obsoleti e approvazione prima delle modifiche. Aggiungere la funzionalità non richiede di per sé un nuovo training; qualità delle risposte e fedeltà al profilo richiedono verifiche dedicate. Nessuna conversazione simulata deve essere presentata come valutazione di un partecipante reale.

### Design e mockup

Sono implementate alternative di design, primitive di mockup, campi, selettori, pulsanti, collegamenti e schermate, con validazione strutturale e applicazione al design. Il codice Web deve rispettare marker, controlli, ordine e schermate approvate.

Sono stati corretti l'omissione dei marker testuali e il rifiuto di contenitori HTML semantici validi. Un mockup interattivo non è un'applicazione: nella nuova prova il numero mostrato nella schermata risultato è illustrativo. Il collegamento «Indietro» superfluo della proposta è registrato come limite.

Fedeltà visiva, accessibilità, correttezza degli input e comportamento reale richiedono verifiche nel browser; la sola corrispondenza strutturale non le dimostra.

### Generazione e riparazione dei sorgenti

Il flusso produce un manifest e file separati, conserva richieste/risposte native e collega le generazioni dei file al tentativo principale. Sono presenti controlli di ammissione, ricette fissate, controlli sintattici e feedback limitato per la riparazione.

Il retry strutturale HTML è implementato e verificato: un solo secondo tentativo, condiviso con il limite del retry sintattico, riceve la violazione precisa del mockup e i riferimenti approvati. Il primo HTML respinto rimane conservato; nessuna riscrittura automatica del sorgente o eccezione al validatore. La migrazione `0044_source_design_retry` protegge identità, collegamenti e unicità dei tentativi. Sono passati 85 test unitari e 66 test PostgreSQL, con revisione indipendente; report `experiments/studio-demo/source-design-retry-20260920.json`. La migrazione è applicata al database della demo e l'API è stata riavviata con disponibilità verificata. Prima dell'integrazione sono stati conservati 280 file verificati del progetto, senza oggetti mancanti. La prova reale BF16 ha esercitato il retry: il primo HTML non aveva le etichette accessibili richieste; il secondo duplicava un identificatore di elemento. Entrambi sono stati respinti e conservati, senza revisione sorgenti né anteprima. Il meccanismo di rifiuto è stato verificato dal vivo; la capacità del modello di produrre una calcolatrice conforme non è dimostrata.

Contratto attuale: `SOURCE_MANIFEST_V15_TARGET_SCOPED_OBSERVABLE_IMPLEMENTATION`. HTML/CSS e osservazioni `BROWSER:` sono limitati ai target Web; JVM richiede comportamento console. Funzioni che restituiscono sempre `true` non sono prove di qualità. JSON valido e sintassi valida non dimostrano correttezza funzionale.

La nuova prova Web ha fallito sotto V12, V13 e V14. Le correzioni successive V15 non trasformano questi tentativi in successi e non hanno ancora prodotto una nuova prova Web completa. Restano da dimostrare generazione autonoma funzionante, test corretti, riparazioni efficaci e conformità al mockup.

### Esecuzione Web e JVM

Sono implementati profili, ricette e launcher fissati, dipendenze su rete limitata, esecuzione isolata, timeout, limiti, raccolta degli output, inventario degli artefatti e cleanup. Il catalogo API usa evidenze di qualificazione.

Gli stati comprendono `DESIGN_ONLY_LEVEL_C`, `EXPERIMENTAL_LEVEL_D` e `VALIDATED_LEVEL_D`. **Level D qualifica un profilo e la sua esecuzione, non la qualità di ogni applicazione generata.** Le fixture controllate qualificano il motore; i probe sui sorgenti nativi valutano il modello. Le due prove non sono intercambiabili.

| Famiglia dichiarata | Target | Stato delle verifiche qui documentate |
|---|---|---|
| Web | `WEB_STATIC`, `WEB_VUE`, `WEB_NODE_EXPRESS`, `WEB_PHP`, `WEB_VUE_NODE` | Contratti/runner implementati; qualificazione completa della revisione corrente ancora aperta |
| JVM | `JVM_JAVA`, `JVM_KOTLIN`, `JVM_SCALA` | Profili CLI qualificati e pubblicati; qualità dei programmi generati valutata separatamente |
| Altri target dichiarati | `ANDROID_JAVA`, `ANDROID_KOTLIN`, `CUSTOM_DECLARATIVE` | Presenza nel modello dei target; nessuna verifica operativa completa o qualifica Android/custom attestata da questa sessione |

JVM comprende Java/Gradle, Kotlin/Gradle e Scala/sbt. Le calcolatrici attuali sono programmi **console**, non interfacce grafiche JVM. La prima versione dell'oracolo prevedeva 20 controlli indipendenti per linguaggio. I 40 controlli eseguiti sui JAR originali Kotlin/Java sono passati, ma le rispettive pipeline erano fallite sui test generati; Scala non compilava. Questi risultati storici restano distinti dalle nuove riparazioni.

Per le nuove riparazioni è pronto un oracolo V2 con 34 casi, inclusi divisori non nulli molto piccoli; la versione V1 e i risultati storici restano invariati. Tre piani immutabili collegano parent, sorgenti, evidenze ed errori; il comando `repair-development` usa l'adapter reale e produce una nuova revisione. Un registro comune impedisce di ripetere la stessa riparazione anche copiando o rinominando il piano; ricette e relativi metadati devono corrispondere agli input originali. La preparazione è documentata in `experiments/studio-demo/jvm-calculator-repair-preparation-20260920.json`: 46 test superati e due problemi emersi dalla revisione indipendente risolti; le tre inferenze sono ora concluse. Il report `experiments/studio-demo/jvm-calculator-bf16-repair-results-20260920.json` conserva i tre esiti negativi, 65 file archiviati e la verifica che 140 file storici siano rimasti invariati. Non sono stati eseguiti i 102 casi V2 perché nessuna pipeline ha raggiunto i prerequisiti.

Dopo il riavvio del computer sono stati ripristinati database, modelli e interfaccia locale. Le 51 evidenze JVM persistono nel database. La nuova rete JVM di sviluppo ha superato otto controlli reali e la verifica di disponibilità; le vecchie risorse attribuite alla prova sono state rimosse. Il preflight Web è in `experiments/studio-demo/web-leveld-preflight-20260920.json`; non sostituisce la campagna formale.

### Casi studio e tesi

Esistono strumenti per preparare, eseguire, raccogliere e verificare casi studio, artefatti e valutazioni. I report conservano anche errori, tentativi respinti e limiti.

Le definizioni versionate sotto `experiments/case-studies` comprendono calcolatrice Web, gestione alberghiera, confronto meteo, validazione JVM, protocollo per esperti e contratti delle campagne. Una definizione o un protocollo presente nel repository non prova che il relativo caso o studio sia già stato eseguito.

Il piano `experiments/case-studies/thesis-evaluation-plan-20260920.json` lega 15 file tramite hash, esplicita 21 metriche e riusa il protocollo con quattro esperti, 60 coppie e 120 schede complessive. Il verificatore ha superato otto test. Restano da fissare le identità delle esecuzioni e selezionare gli artefatti per gli esperti; nessun partecipante è stato contattato e nessun giudizio è stato inventato. I casi già utilizzati per correggere i prompt sono diagnostici: serviranno nuovi casi congelati per una valutazione finale indipendente. Il confronto 4B/30B è un confronto fra sistemi, non un'ablazione dello stesso modello base.

Restano da completare i risultati empirici finali: casi rappresentativi, confronti e ablazioni, valutazione di esperti/utenti e analisi dei limiti. Non è ancora giustificata una dichiarazione generale di generazione autonoma affidabile. Dati sintetici, approvazioni delegate e test software non sostituiscono validazione umana.

## Modelli e training

La diagnosi Qwen3-Coder del 20 settembre è in `experiments/model-proposals/coder-source-diagnostic-20260920.json`. Nel caso guest list il core supera 4/4 gruppi indipendenti e 6/6 test del modello, ma l'HTML omette i marker obbligatori del mockup ed è respinto. Nel caso divisione spesa manca l'export CommonJS; HTML e test del modello non sono completati entro la scadenza globale di 1.200 secondi. Uno dei PASS grezzi dell'oracolo è vacuo perché accetta l'errore del simbolo mancante: non dimostra la validazione degli input. Nessuna proposta è stata pubblicata o promossa da questa diagnosi.

Il percorso MoE a 4 bit delle librerie installate dequantizza i tensori di tutti gli esperti durante il forward: è un'ipotesi concreta per la lentezza, non una quota causale misurata. È stata implementata un'opzione BF16 esplicita, con controllo della precisione effettiva, permanenza sulla GPU e identità distinta; 125 test mirati sono passati. Dopo un consenso specifico aggiuntivo, la variante è stata trasferita nello stesso pod e avviata separatamente. Il confronto usa una copia del client con tutti i 48 hash identici alla prova 4-bit, senza incorporare il nuovo retry HTML in sviluppo. Report tecnico: `experiments/studio-demo/coder-serving-precision-diagnosis-20260920.json`.

- Base proposer: `Qwen/Qwen3-4B-Instruct-2507`, revisione `abcc171021d4f320b2e7f47c6f0deca67ded870c`.
- Proposte e sorgenti usano un modello reale; l'adapter proposer respinto non è attivo.
- Il valutatore usa un adapter LoRA distinto, verificato per identità/hash. Restano limiti semantici da risolvere: servizio disponibile non significa valutatore scientificamente qualificato.
- Decodifica: `LLGUIDANCE_JSON_SCHEMA_CANONICAL_BOUNDED_WS_V3`, senza riparazione nascosta del testo nativo.
- È implementato un endpoint sorgenti separato con configurazione/identità dedicate; il candidato cloud BF16 è stato collegato temporaneamente alla demo e verificato disponibile. Dopo la pausa è stato ripristinato un nuovo runtime per la prova GUI/JVM; ora è spento e l'API usa di nuovo i modelli locali. Il candidato non è stato promosso.

I percorsi normali di avvio in `REAL_REQUIRED` rifiutano configurazioni reali mancanti. Restano adapter/fixture deterministici per test e sviluppo esplicito: non vanno rimossi indiscriminatamente e non sono il fallback della demo reale. La factory API diretta in sviluppo può ancora usare fixture senza configurazione; per la demo usare il launcher previsto.

Il pilot proposer ha eseguito QLoRA, 120 step e due epoche su 240 esempi. Il confronto diagnostico ha prodotto **`DO_NOT_PROMOTE_CANDIDATE`**. Una loss bassa o un training concluso non dimostrano applicazioni migliori.

Dataset V3: 240 esempi training, 64 validazione, 38 famiglie con split 30/8. Le famiglie dei casi finali sono escluse dal training. Sono dati sintetici ingegnerizzati, con diversità di implementazione/layout ancora limitata. I 76 bundle di riferimento e 380 test Node verificano i riferimenti, non le risposte future del modello. V2/V3 non sono stati usati per un nuovo training; V3 resta un artefatto congelato V13, non un dataset rigenerato V15.

La prova del modello più grande è ora disponibile e ha dato esiti negativi sulle richieste eseguite: struttura HTML non conforme, mancata integrazione fra modulo e test, riparazioni JVM non efficaci. Questi casi indicano cosa correggere nei contratti, negli esempi e nella valutazione; non giustificano da soli un nuovo training lungo né una conclusione generale su tutti i modelli più grandi. Occorre verificare prima un insieme diversificato di applicazioni funzionanti e riparazioni effettive, con casi finali separati.

Il pod della ripresa è verificato `EXITED`; i volumi persistenti hanno un ciclo di vita/costo separato. Nessuna credenziale è riportata qui. Per eventuali nuove esecuzioni autorizzate, le notifiche email restano limitate all'inizio e alla fine.

## Evidenze e risultati disponibili

I percorsi sono relativi alla radice del repository. I report JSON descrivono il loro scope e rimandano anche ad artefatti locali esclusi da Git.

| Evidenza | File in `experiments/` |
|---|---|
| Runtime reali e fallback di sviluppo | `studio-demo/real-model-runtime-audit-20260919.json` |
| Brief e User Twin | `studio-demo/user-modeling-brief-grounding-20260919.json` |
| Mockup e primitive | `studio-demo/mockup-primitive-contract-20260919.json` |
| Race delle approvazioni | `studio-demo/approval-refresh-race-20260919.json` |
| Regressione frontend | `studio-demo/frontend-regression-20260919.json` |
| Contratti sorgente e correzioni | `studio-demo/source-module-contract-20260919.json`, `studio-demo/source-observable-implementation-20260919.json` |
| Nuovo progetto GUI: esiti negativi 4B/BF16 | `studio-demo/new-project-real-model-diagnosis-20260919.json`, `studio-demo/calculator-bf16-gui-verification-20260920.json` |
| 17 casi del nuovo progetto | `studio-demo/calculator-acceptance-cases-20260919.json` |
| 16 verifiche della demo assistita | `studio-demo/assisted-calculator-browser-regression-20260919.json` |
| Preparazione runner | `studio-demo/web-runtime-readiness-20260919.json`, `studio-demo/jvm-development-readiness-20260919.json` |
| Qualificazione JVM e catalogo API verificato | `studio-demo/jvm-leveld-qualification-20260919.json` |
| Tre calcolatrici native e riparazioni BF16 | `studio-demo/jvm-calculator-real-model-verification-20260919.json`, `studio-demo/jvm-calculator-bf16-repair-results-20260920.json` |
| Baseline e confronto proposer | `model-proposals/proposer-postprompt-baseline-20260919.json`, `model-proposals/proposer-candidate-comparison-20260919.json` |
| Pilot e dataset | `model-proposals/proposer-training-pilot-20260919.json`, `model-proposals/proposer-dataset-v2-verification-20260919.json`, `model-proposals/proposer-dataset-v3-verification-20260919.json` |

Il nuovo progetto Web aveva un export di 280 file prima della ripresa; la fotografia finale BF16 conserva 345 file verificati e 23 generazioni complessive. Un probe separato sui due JavaScript nativi ha eseguito 16 test, tutti falliti per funzioni non esportate; le asserzioni aritmetiche non sono state raggiunte. Sono inoltre presenti asserzioni staticamente contraddittorie sul valore vuoto. Questo probe non crea una revisione applicativa e non sostituisce i controlli browser. I 17 casi sono **NOT_EXECUTED**, non 17 successi né 17 fallimenti funzionali: manca un'applicazione completa da eseguire. REQ-001 è stato chiarito manualmente prima della generazione; tale intervento è dichiarato.

Campagna JVM `jvm-leveld-d82bb48-20260919-02`: 21 tentativi, nove successi e dodici fallimenti attesi, 24 approvazioni e 125 container di fase rimossi. Sono passati 677 test Windows (cinque esclusioni di piattaforma), otto Linux e 55 PostgreSQL. Questi conteggi non rappresentano tutti i test del repository e non vanno sommati a suite sovrapposte.

Pacchetto JVM verificato: `94ef317c1d233c9afd2c5335f32558ee92bf45782c2a0807863cff77ccebe8fa`. Catalogo pubblicato: `4dfeab23d7b24d09f4e632df8f2ba497f898e46381d090b87f3fdf865135be9e`, 51 record. La pubblicazione diretta atomica ha avuto successo dopo un primo fallimento del wrapper CLI, conservato per diagnosi. Il primo tentativo di raccolta, fermato dalla readiness del PostgreSQL temporaneo, è anch'esso conservato.

Il controllo finale `GET /api/v1/execution-profiles` restituisce HTTP 200 e `VALIDATED_LEVEL_D` per Java, Kotlin e Scala, con 17 riferimenti ciascuno. Il campo di disponibilità runtime rimane `NOT_CHECKED`: la risposta non costituisce una nuova prova di disponibilità delle risorse. Sono stati rimossi i 125 container di fase, i due database temporanei e le tre reti formali; la rete di sviluppo è distinta.

Calcolatrici del modello: **zero su tre pipeline complete**, ma 40 su 40 controlli indipendenti eseguiti superati sui JAR Kotlin/Java. Scala non compila e i suoi 20 casi non sono stati eseguiti. Kotlin contiene `import kotlin.test.*` dentro una funzione del test; Java contiene un test che pretende il rifiuto di `1,5 + 2`, contrariamente ai requisiti. Inoltre Java considera zero divisori con valore assoluto inferiore a `1e-15`: è un limite individuato leggendo il sorgente, non coperto dai 20 casi fissi. Output originali e fallimenti sono conservati; nessun file generato è stato corretto per far passare le prove.

Archivio locale: `C:/Users/alext/.codex/visualizations/2026/09/12/01a09597-4b2a-7a30-bc8f-e6e729d91f04`. Contiene ricevute, adapter recuperati e pacchetti; non è distribuito con Git. Per riprodurre le prove su un'altra macchina occorre conservare/trasferire tali artefatti in modo autorizzato e verificarne gli hash.

## Avvio locale

Prerequisiti: Python >= 3.12, Node coerente con `.nvmrc` e `frontend/package.json` (26.6.0), npm compatibile, Docker Desktop con container Linux e PostgreSQL. Il serving locale configurato richiede anche WSL2, GPU NVIDIA e ambiente training. Quest'ultimo usa Python 3.13 e il proprio lock, separato dalla `.venv` del backend.

Installazione delle dipendenze di sviluppo da una nuova copia:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --editable . --requirement requirements-dev.txt
npm ci
npm --prefix frontend ci
```

Questi comandi non configurano automaticamente pesi, adapter e risorse della demo. Per l'ambiente GPU consultare anche `environments/training/README.md`.

Sulla postazione già configurata, con Docker avviato e nessuna sessione Studio attiva:

```powershell
./scripts/start-studio.ps1
```

Il launcher legge `var/studio/local-settings.json`, avvia il database, applica le migrazioni, costruisce il frontend, carica i modelli e controlla i servizi. Richiede percorsi e hash esatti degli adapter. Le configurazioni dei runner sono `var/studio/web-runtime.json` e `var/studio/jvm-runtime.json`; immagini e manifest di rete devono esistere ed essere verificabili.

| Servizio della sessione osservata | Indirizzo |
|---|---|
| Interfaccia | `http://127.0.0.1:8080` |
| API health | `http://127.0.0.1:8000/api/v1/health` |
| Proposer / valutatore | `127.0.0.1:8787` / `127.0.0.1:8788` |
| PostgreSQL demo | `127.0.0.1:15432` |

Per fermare i processi della sessione del launcher:

```powershell
./scripts/stop-studio.ps1
```

Questo non spegne risorse Runpod e non cancella volumi. Controllare separatamente le risorse Docker/cloud attribuite alla sessione.

La demo assistita verificata è il progetto locale `f6d7cae8-1a22-4d68-8799-714022b4af61`: dopo l'accesso dell'owner, aprire **Risultato**. Compare «Versione rivista con assistenza». Il nuovo tentativo autonomo incompleto è `ab355503-9374-448c-be27-0c32dc929b67`. Questi dati locali non vengono creati automaticamente da una nuova installazione.

## Comandi di verifica

I comandi indicano come eseguire i controlli; non dichiarano che tutte le suite siano state ripetute sull'ultima working tree.

```powershell
.venv/Scripts/python.exe -m pytest -m "not integration"
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
npm --prefix frontend run check
```

I test di integrazione richiedono un PostgreSQL di test migrato e la configurazione della suite. Training/GPU e campagne Docker hanno prerequisiti distinti dai normali unit test. La CI usa fixture riproducibili e non prova automaticamente un modello reale.

Strumenti principali, con opzioni documentate dal relativo `--help`:

- `scripts/check_real_model_runtime.py`: disponibilità e identità dei modelli.
- `scripts/validate_web_level_d.py`, `scripts/validate_jvm_level_d.py`: campagne e qualificazione.
- `scripts/verify_web_runner_manifest.py`, `scripts/verify_jvm_runner_manifest.py`: manifest dei runner.
- `scripts/verify_generated_jvm_calculator.py`: contratto, generazione reale, probe e controlli supplementari.
- `scripts/sprint12_case_run.py`, `scripts/sprint12_harvest_case_evidence.py`: casi studio e raccolta.

Un probe `DEVELOPMENT_CONSOLE_MODEL_PROBE_NOT_LEVEL_D` non approva gate né pubblica il catalogo. Un controllo supplementare dopo una fase fallita non annulla il fallimento della pipeline originale.

## Attività ancora da completare

1. Correggere le cause emerse nelle riparazioni JVM: gestione delle dipendenze di test Kotlin, tipi/eccezioni Scala, riparazioni Java senza cambiamenti, test contraddittori e divisori piccoli. I tre tentativi BF16 sono conclusi con fallimento; nuove prove richiedono nuove revisioni e una motivazione concreta, senza aggirare il registro dei tentativi.
2. Verificare dalla GUI un nuovo progetto JVM completo con sorgenti, approvazioni ed esecuzione, mantenendolo distinto dai probe console locali. Qualificazione e pubblicazione dei tre profili sono già concluse e confermate dall'API; non ripetere la campagna riuscita senza motivo.
3. Usare i risultati del confronto diagnostico per migliorare generazione, contratti e dataset. La prova Qwen3-Coder è conclusa, il pod è spento e il candidato non è promosso. Separare problemi di integrazione fra file, correttezza dei test e fedeltà al mockup; non ripetere la stessa prova cloud senza un cambiamento verificabile.
4. Ampliare il dataset con più implementazioni, layout, errori e riparazioni, mantenendo split e casi finali separati. Promuovere un adapter solo dopo miglioramenti misurati.
5. Ripetere un progetto nuovo dalla GUI fino all'applicazione funzionante: calcoli, input errati, tastiera, mobile, conservazione dello stato e conformità al mockup. L'obiettivo Web autonomo non è raggiunto.
6. Completare Web Level D dopo commit/push dell'utente e CI pertinente, eseguendo l'intera matrice prevista e pubblicando solo un pacchetto verificato.
7. Completare casi studio, confronti e valutazione con esperti/utenti per la tesi, distinguendo dati sintetici e risultati empirici.
8. Chiudere regressione, avvio/ripristino riproducibile, archivio delle evidenze e suddivisione delle modifiche in commit.

## Manutenzione, commit e registro

- Aggiornare il README a ogni attività conclusa: data, esito, prova e limite residuo. Non segnare come completata una verifica ancora in corso.
- Le modifiche saranno suddivise in runtime, proposte/mockup, contratti sorgente, training, frontend, esecuzione/evidenze e documentazione. La lista definitiva dei file viene verificata prima della consegna dei comandi.
- **`git add`, `git commit` e push restano all'utente.** L'assistente prepara comandi e messaggi senza eseguirli.
- Credenziali, dump, pesi e checkpoint voluminosi restano fuori da Git. Versionare codice, contratti e report; conservare esternamente le prove con hash verificabili.
- Non sostituire silenziosamente un esito negativo: registrare un nuovo tentativo mantenendo quello precedente.

| Data (Europe/Rome) | Completato | Aperto |
|---|---|---|
| 19 settembre 2026 | Dataset, pilot e confronto negativo; correzioni profili/mockup/frontend; demo assistita verificata; nuova GUI con esito autonomo negativo | Qualità del proposer e applicazione Web autonoma |
| 20 settembre 2026 | Campagne JVM, sigillo/verifica, pubblicazione atomica e catalogo API Level D; API riavviata con V15; Kotlin e Java 20/20 supplementari ciascuno; fallimenti delle tre pipeline conservati; report finali e README dell'intero progetto | Riparazioni del modello, nuovi percorsi GUI autonomi, qualifica Web, valutazione empirica e commit dell'utente |
| 20 settembre 2026, ripresa | Otto inferenze BF16 concluse; GUI respinta, probe JS 0/16, tre riparazioni JVM fallite; 140 file storici invariati; ricevute recuperate, pod spento, API locale ripristinata; README aggiornato | Applicazioni autonome funzionanti, chat Twin discussa ma non implementata, CI e Web Level D, validazione umana |

Licenza Apache-2.0: vedere `LICENSE`.
