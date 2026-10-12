# Dossier, push, why and validation

The Dossier is the `orchestwin/` folder in the project's repository. It holds what you approved in the Studio, as JSON and Markdown files, with a manifest that keeps the fingerprint of every file. Developers, and the agent that writes the code, read that folder and not the Studio, so it has to match a published version. Its contents are described in [The knowledge folder](../architecture/knowledge-folder.md); the code files mentioned here are under `src/orchestwin/`. The runs quoted on this page were made with the Italian interface of `ut`: their transcripts show the English messages the code prints for the same lines, with the real numbers and dates.

## `ut package`

The command keeps the folder identical to a published version. An old folder, or one touched up by hand, would give the agent the wrong knowledge without anyone noticing.

```text
ut package [-h] ACTION ...
ut package publish [-h]
ut package pull [-h] [--version N]
ut package verify [-h]
ut package history [-h]
ut package import [-h] [--name NAME] PATH
```

| Action | What it does |
| --- | --- |
| none | compares the folder with the latest version in the Studio and suggests the next step |
| `publish` | asks the Studio for a new version and downloads it; if nothing changed, it reuses the latest |
| `pull [--version N]` | downloads a published version, the latest if you give no N |
| `verify` | checks every file against the manifest, without the Studio |
| `history` | lists the versions with date, content hash and number of files |
| `import PATH [--name NAME]` | creates a new project in the Studio from a folder or from its zip |

The download is the part worth knowing about. The Studio sends the zip with an `X-Content-SHA256` header, and `ut` refuses it if the SHA-256 it computes again does not match (`ARCHIVE_HASH_MISMATCH`). Then it writes the files into a hidden folder alongside, moves the old folder aside and puts the new one in its place with a rename. If the rename fails, the old folder goes back where it was (`cli/folder.py`). So `orchestwin/` always holds one whole version, never a mixture of two. The files arrive with a `.gitattributes` containing `* -text`, so that Git does not change the line endings.

If you changed files by hand, `publish` and `pull` stop before replacing them: "The folder {path} is no longer as the Studio published it: the first file that differs is {file} ({code}). If it is replaced, the changes made by hand are lost." The question that follows counts as no if you just press Enter, and `--yes` does not skip it (`cli/messages/package.py`). A verification that does not pass exits with code 7.

Import accepts only a folder published by the Studio and left untouched, or its zip. If the folder you run the command in is not linked to a project, it offers to link it to the new one; the imported steps have to be approved again. The automated tests cover import with PostgreSQL on synthetic data, but a full import of a real project has not been measured yet.

On 6 October 2026, on Calcolatrice iPhone, the iPhone-style calculator, a sentence added by hand to `requirements/requirements.json` made the verification fail, as it should.

```powershell
ut package verify
```

```text
The knowledge folder orchestwin/ does not pass the verification: the file requirements/requirements.json was changed or added after the publication (FOLDER_TAMPERED). To go back to the published version download it again with `ut package pull`; the changes made by hand will be lost.
```

That time the remedy was not to download. It was to send the change to the Studio.

## `ut push`

On 6 October 2026 the supervisors asked for the project folder to be the single source of truth. A change made by hand must then be able to go back into the Studio without passing through the web. The command brings it back as a version supplied by you, with the same differences, the same approval and the same gate as the web, and it never calls the model.

```text
ut push [-h] [--dry-run] [--stage {brief,team,twins,requirements,design}]
```

First the command downloads and verifies the version the folder started from, then it sorts the changed files into three groups. The five step documents, `brief/brief.json`, `team/team.json`, `twins/twins.json`, `requirements/requirements.json` and `design/design.json`, can be sent. Derived files, such as Markdown, tables, diagrams and mockups, "are generated again by the Studio". Unknown files stay on the disk. If the Studio has already moved further ahead, the command stops and asks you to download with `ut package pull` (`cli/messages/push.py`).

With `--dry-run` it shows the differences and ends there; `--stage` limits the sending to one step. Otherwise it goes through the steps one at a time and asks two questions for each. The first comes before it sends the document to the revision route that the web uses too, the second after it has shown you the differences computed by the Studio.

```text
Send the changes of "{stage}" to the Studio?
Do you approve the differences of "{stage}"? They become a new version, supplied by you.
```

At the second question Enter means no, and `--yes` does not answer for you. Then come the gate, the re-anchoring of the downstream sections and a new folder, downloaded straight away. If the Studio has no Design yet, one written by hand cannot be supplied: it has to be generated with `ut design`.

On the evening of 6 October 2026 the sentence added to REQ-012 of Calcolatrice iPhone went back into the Studio like this.

```powershell
ut push --dry-run
```

```text
Compared with version 7 of the folder: step documents changed 1, derived files changed 1, unknown files 0.
  requirements/requirements.json (changed): document of the "Definition" step, its changes can be sent.
    ~ requirements REQ-012
  requirements/requirements.md (changed): derived file, it is not sent.
Derived files are generated again by the Studio: change the JSON documents of the steps.
Trial without sending (--dry-run): the Studio and the folder stay as they are.
```

Then came `ut push` itself: Enter to send, and "s" to approve, which is yes in the Italian interface and "y" in the English one. It ended with "Sent: Definition. Folder at version 8 (72 files)." and made no generation at all. The Definition had moved to version 4, the regenerated `requirements.md` contained the new sentence, and `ut package verify` passed again.

## `ut why`

Every artifact, from a twin's claim to an element of the mockup, has a chain that says where it comes from and what depends on it. The command shows that chain starting from a code. The model plays no part: the chain is rebuilt from the recorded versions and links, as [The Why? and traceability](../framework/why.md) explains.

```text
ut why [-h] [--all] [--json] [--offline] code
```

The code can be short, such as `REQ-001` or `ELM-022`, or a full selector. The command asks the Studio for the chain; with `--offline`, or when the Studio does not answer, it rebuilds the chain from the verified local Dossier and says so. The answer starts with "Why? {title}" and goes on with "Where it comes from ({count})", "What depends on it ({count})" and "To verify with real people ({count})", followed by the gaps (`cli/messages/why.py`). With `--all` you also get citations, versions, hashes and links; with `--json`, the whole answer.

A short code can be ambiguous, because the Studio keeps the past versions as well. On 2 October 2026 `ut why REQ-001 --json` answered with `WHY_CODE_AMBIGUOUS` and three selectors, one for each version of the requirement. Without `--json` the sentence is "Ambiguous code. Use one of these selectors: {candidates}."

The same day, on the calculator kept for measurements, the chain of one of a twin's goals took 0.9 seconds online and 0.5 with `--offline`.

```powershell
ut why UT-31FCCC9B-v3:user_twin.goals --offline
```

```text
Why? goals
UT-31FCCC9B-v3:user_twin.goals · Hypothesized · version 3 · Undeclared origin
Reaches twin: yes · active evidence: no · all branches complete: no
Where it comes from (3)
  AGENT_TEAM (TEAM-v1)
  PROJECT_BRIEF (BRIEF-v3)
  Chi fa conti al volo (UT-31FCCC9B-v3)
What depends on it (0)
To verify with real people (2)
  Chi fa conti al volo (UT-31FCCC9B-v3)
  goals (UT-31FCCC9B-v3:user_twin.goals)
Interrupted chain: 1 gaps.
The linked source is missing.
```

Chi fa conti al volo is the twin's name, kept as the project has it: someone who does quick sums. The chain reaches the twin and no active evidence. That is the limit the "Why?" makes visible, not a fault of the command.

## `ut validation`

The twins produce hypotheses, and the ones that matter have to be checked with people. The command tells you how far that checking has got: candidates drawn from the twins, operational hypotheses you chose, outcomes of the sessions, the walkthrough of a scenario on the design. It only reads; hypotheses and outcomes are written in the web or through the API.

```text
ut validation [-h] [--alternative ALTERNATIVE] [--document-hash DOCUMENT_HASH] [--all] [--json]
                     [--offline]
                     [{walkthrough}] [scenario]
```

| Option | Meaning |
| --- | --- |
| `walkthrough SCENARIO` | the walkthrough of the scenario: task, steps, gaps, relevant elements |
| `--alternative ID` | the alternative to read the walkthrough on |
| `--document-hash HASH` | the hash of the mockup document |
| `--all` | every detail, historical ones included |
| `--json` | the complete answer as JSON |
| `--offline` | reads the verified Dossier, without the network |

The `--alternative` and `--document-hash` options apply only to `walkthrough`. A scenario walkthrough ends with "Software navigation is not an observation with people." (`cli/messages/validation.py`). A historical scenario that the Dossier does not contain can be read only online, and with `--offline` the command exits with 2.

On 3 October 2026, on the same measurement calculator, the reading took one second.

```powershell
ut validation
```

```text
Candidates to verify (57)
  Use --all for details of the 57 candidates.
Operational hypotheses (0)
Outcomes (0)
Outcomes do not automatically promote twin claims.
```

Zero hypotheses and zero outcomes, because no session with people has been held yet, on that project or on any other. The tests with people are planned for sprint 49 and described in [Validation with people](../validation.md).
