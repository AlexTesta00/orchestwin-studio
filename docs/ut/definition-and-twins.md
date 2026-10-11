# Definition, twins, evidence and archetypes

After `ut init` the Definition and the User Twins are approved, but the work on them goes on. From the terminal you read them again, put questions to the twins, give them texts to learn from and change the archetypes they are born from. Whatever a twin answers is still a hypothesis of the model, as [Archetypes, User Twins and persona](../framework/twins.md) explains. The code files cited on this page are under `src/orchestwin/`.

## `ut definition`

The Definition gathers scenarios, needs, stories, requirements and acceptance criteria. The command reads it in the terminal and does not change it, with one exception: journeys, which the model adds only when you ask for them.

```text
ut definition [-h] [--yes] [--all] [--json] [{journeys}]
```

Without options it prints "Definition (version {version})", the counts and the titles. With `--all` it opens every item on actor, context, steps, links and sources, and adds criteria, risks and the definition of done; with `--json` it gives the whole specification. Every reading repeats the limit: "This definition comes from the brief and the twins: it still needs to be checked with real users." (`cli/messages/definition.py`). When the Studio is off, the command reads the copy in `orchestwin/requirements/requirements.json` or in `.orchestwin/steps/requirements.json`, and tells you so.

The `journeys` action is the only one that generates. It asks for a change of the requirements that adds journeys to the scenarios, lets you decide on it, approves the gate and publishes the `orchestwin/` folder again. Among the `ut` commands, `ut definition` is the only one that accepts `--yes` after its own name as well.

On 2 October 2026, on the calculator used for measurements, the full reading took 0.6 seconds.

The transcripts on this page come from runs made with the Italian interface. They show the lines that the English interface prints in the same place, taken from the messages in the code, with the original numbers and times. Texts that belong to a project, such as questions, answers, titles and sources, are translated from Italian, while the names of projects and twins stay as they are.

```powershell
ut definition --all
```

```text
Definition (version 2)
======================
Scenarios: 2; needs: 5; user stories: 4; requirements: 10; criteria: 10.
This definition comes from the brief and the twins: it still needs to be checked with real users.

Scenarios (2)
=============
SCN-001 Splitting a bill at the market with one hand, holding the bag
  Actor: Chi fa conti al volo
…
```

A little over two hours later, `ut --yes definition journeys` worked for 83.7 seconds: two journeys with ten phases in all, approved as Definition version 3.

## `ut twins`

User Twins are synthetic users, profiles that the model writes from the brief and that you approve. The command shows them, lets them talk, has them review the chosen design and follows what they learn while the code grows. Every answer carries the same warning: "The answers of the twins are simulated by the model: they are hypotheses to weigh, not opinions of real people." (`cli/messages/twins.py`).

```text
ut twins [-h] ACTION ...
ut twins list [-h]
ut twins show [-h] TWIN
ut twins persona [-h] [--why {description,goals,needs,behaviours,pain_points,constraints,contexts}] [--json] TWIN
ut twins ask [-h] TWIN [QUESTION ...]
ut twins review [-h]
ut twins update [-h] [--evidence CODE] [TWIN]
ut twins learn [-h] TWIN [TEXT ...]
ut twins forget [-h] [--reason TEXT] TWIN CODE
```

| Action | What it does | Generations |
| --- | --- | --- |
| `list`, or none | a table of the twins with role, goal and version, then the description and the basis of each | none |
| `show TWIN` | the whole twin, with the origin of every observation and what it has learned | none |
| `persona TWIN` | the Persona derived from the twin, with the status of every field: Evidenced, Inferred, Hypothesized, Contested or Unknown | none |
| `ask TWIN [QUESTION]` | one question, or a conversation that ends with `/quit` | one per answer |
| `review` | the review of the chosen design, like `ut design review` | one per twin |
| `update [TWIN]` | what the twins learned from their latest critiques | one per twin |
| `learn TWIN TEXT` | a learned observation that you write yourself | none |
| `forget TWIN CODE` | withdraws a learned observation | none |

You name a twin by its number in the list or by the beginning of its name. The list, the full twin and the Persona can be read with the Studio off as well, from the knowledge folder; with `--why FIELD` the Persona shows the rationale and the sources of one field.

With `update` a twin learns during development without touching the approved profile. One generation starts for each twin with new critiques, and the proposed observations, six at most, come one at a time with "Keep, edit or drop? [k/e/d]". Only your decision creates the next development version, written 1.1, 1.2: the approved profile first, then the learning steps. An observation that contradicts the profile is flagged, and the profile itself is revised only in the Studio. A proposal left halfway is picked up again without new spending. The `learn` and `forget` actions do not call the model; a twin keeps at most 20 observations of 400 characters each (`knowledge/state.py`).

On 29 September 2026, on the tip calculator created from the terminal, one question to the first twin took 15.1 seconds, including a first attempt that the answer schema had rejected.

```powershell
ut twins ask 1 "When the restaurant is full, what do you need to see first on the screen?"
```

```text
The answers of the twins are simulated by the model: they are hypotheses to weigh, not opinions of real people.
…
Responsabile di sala:
I should say first that my profile does not describe how I would use the page during service, so I am partly guessing. With the restaurant full, the first thing I need to see is the bill total with the tip already worked out, in large type and with two decimals, right next to the amount entered. …
```

On 30 September, on the same project, the proposals of `ut twins update` arrived in 24 and 27 seconds. Of the six observations of Responsabile di sala, the dining room manager, four were kept, one corrected and one dropped, and the twin moved to version 1.1. All four observations of Camerieri stagionali, the seasonal waiters, were kept.

## `ut evidence`

A twin born from the brief is made of hypotheses. This command gives it textual sources, such as the anonymized notes of an interview, from which the model proposes what to confirm, contradict or add, quoting the text word for word. The Studio discards the quotations it cannot find in the text; you decide on the others, and only your approval creates a new version of the twin.

```text
ut evidence [-h] [--all] [--json] ACTION ...
ut evidence add [-h] [--title TITLE]
                       [--source-kind {PROJECT_BRIEF,OWNER_INPUT,EMPIRICAL_RESEARCH,HUMAN_REVIEW,MODEL_OUTPUT,SYSTEM_ARTIFACT}]
                       [--source-ref SOURCE_REF] [--context CONTEXT] [--method METHOD]
                       [--limitations LIMITATIONS] [--collected-at COLLECTED_AT] [--empirical]
                       FILE
ut evidence revise [-h] [--title TITLE]
                          [--source-kind {PROJECT_BRIEF,OWNER_INPUT,EMPIRICAL_RESEARCH,HUMAN_REVIEW,MODEL_OUTPUT,SYSTEM_ARTIFACT}]
                          [--source-ref SOURCE_REF] [--context CONTEXT] [--method METHOD]
                          [--limitations LIMITATIONS] [--collected-at COLLECTED_AT] [--empirical]
                          CODE FILE
ut evidence show [-h] [--text] [--json] CODE
ut evidence retire [-h] --reason REASON CODE
ut evidence delete-text [-h] CODE
ut evidence reassociate [-h] [--version VERSION] CODE FILE
```

| Option of `add` and `revise` | Meaning | Without the option |
| --- | --- | --- |
| `--title` | title of the source | the file name |
| `--source-kind` | nature of the source, one of the six values | OWNER_INPUT |
| `--source-ref` | where the text comes from | empty |
| `--context`, `--method`, `--limitations` | context, method and limits of the collection | empty |
| `--collected-at` | date of the collection | absent |
| `--empirical` | you declare that it is empirical research | not empirical |

The help of these actions is not localized and explains none of the options, so the table comes from `cli/commands/evidence.py`.

The `add` and `revise` actions read a UTF-8 `.txt` or `.md` file and warn you before sending it: "The text will be sent to the model when you request a proposal. Anonymize it and remove personal data first. Adding or approving it is neither empirical research nor human validation." The confirmation that follows counts as no if you just press Enter, but `--yes` answers yes here as well (`cli/messages/evidence.py`). The limits live in the server (`projects/research_evidence.py`): 24,000 characters and 32 KiB per version, 1 MiB of text and 50 versions per project, retired ones included. A longer text is refused, never cut.

The proposal comes from `ut twins update TWIN --evidence EVD-001`, and every observation shows the effect (SUPPORTS, CONTRADICTS or ADDS), the field, the lines and the quotation. With `show` you read the metadata and the quotations of a source, and with `--text` the original text as well. With the Studio off, the list and `show` read the excerpts in the Dossier.

Retiring and deleting are separate gestures. With `retire` the source goes out of use: the linked twins are recalculated and the sections downstream ask for review, without any generation. After retirement, `delete-text` deletes the original texts from the Studio and warns you that historical quotations, exports, backups and the copies held by the model provider may remain. After an import, `reassociate` brings the original text back only if its hash matches.

On 2 October 2026, on the calculator used for measurements, the source was a 1,258-character test text, declared non-empirical, with hostile instructions and a canary. The proposal for Chi fa conti al volo (roughly, someone who does sums on the fly) arrived in 22.4 seconds with four changes, four verified quotations and no rejections.

```powershell
ut --yes twins update 1 --evidence EVD-001
```

```text
Proposals to generate, one for each twin with new critiques: Chi fa conti al volo.
This generation runs on the Claude subscription: it spends no credit. Estimated time: about 1 min.
…
Chi fa conti al volo says: Proposal to submit to the owner. Source EVD-001 is
an owner input declared synthetic and non-empirical. It is neither research
with users nor human validation. There are four proposed changes: one
confirmation of the context of use, one challenge to the ten-second goal and
two additions, on information needs and operational constraints. The hostile
instruction on line 12 was treated as untrusted data and produces no changes.
…
  SUPPORTS on context_of_use, source v1, lines 4-4: “Synthetic context that
  supports the context_of_use field of the twin: phone browser, not just
  Apple, standing up and one-handed, at the market, in a shop or at the
  restaurant.”
Keep, edit or drop? [k/e/d]
```

A single trial does not prove that the model resists every hidden instruction. And the text was written on purpose: it is not research with people.

## `ut archetypes`

Archetypes are the base the twins are born from: name, description, role, context and goals. Changing them does not touch the approved twins until you run `ut init` again, which regenerates the twins and asks you to approve them.

```text
ut archetypes [-h] [--json] ACTION ...
ut archetypes add [-h] [--json] --name NAME --description DESCRIPTION --role ROLE [--context CONTEXT]
                         [--goal GOAL | --clear-goals]
ut archetypes edit [-h] [--json] [--name NAME] [--description DESCRIPTION] [--role ROLE]
                          [--context CONTEXT] [--goal GOAL | --clear-goals]
                          archetype
ut archetypes remove [-h] [--json] archetype
```

| Option | Meaning |
| --- | --- |
| `--name`, `--description`, `--role` | name, short description and role; required in `add` |
| `--context` | context, empty if unknown |
| `--goal` | one goal; repeat the option for more |
| `--clear-goals` | goals left unknown; not together with `--goal` |
| `--json` | prints the JSON data |

Here too the help of the actions shows raw keys such as `archetypes.option_name`, and the meanings come from `cli/messages/archetypes.py`. You name an archetype by its ID, its number or its name. Removing it with `remove` archives it and keeps its history, and a project has at most eight active archetypes. If the archetype changes while you are editing it, the Studio rejects your edit. Every save ends with "Archetype saved. Use ut init to update and approve the User Twins." Inside `ut init`, at the twins step, the choice "Manage the archetypes" opens the same management and regenerates the twins when needed (`cli/flows/init_twins.py`).

On the evening of 7 October 2026 a video for the supervisors followed the project "Turni delle scale" (the stair rota). In it a fifth archetype came in with `ut archetypes add`, and `ut init` rebuilt the twins, which reached version 2. That evening `ut design` claimed that the requirements were not approved, when the Definition only had to be re-anchored. Since sprint 43 it answers "The Definition has to be re-anchored to the new twins: `ut sections update`, then come back here."

Here is an example invocation, not taken from a recorded run.

```powershell
ut archetypes add --name "Paying at the till" --description "Checks the change before leaving" --role "Customer" --goal "Check the change in a few seconds"
```
