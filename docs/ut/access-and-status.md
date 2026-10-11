# Access and status

Before you generate anything you need to know which Studio you are talking to and where the project stands. `ut login` and `ut logout` open and close the sign-in, `ut status` and `ut sections` read the state, and `ut activity` measures times and steps. None of them puts the model to work.

## `ut login`

A Studio with accounts wants `ut` to identify itself, just as it wants you to sign in on the web. A local Studio does not.

```text
usage: ut login [-h] [--studio ADDRESS] [--email EMAIL] [--password-stdin]
```

Without `--studio` the command uses the Studio of the last successful sign-in, or `http://127.0.0.1:8000` when there is none; plain `http` is allowed only towards the computer itself. It checks `GET /health` first and exits with 4 if the Studio does not answer. Facing a local Studio it writes "The Studio {studio} is local and needs no sign-in: the commands work without `ut login`." and exits with 0. Otherwise it asks for your e-mail and password in the terminal, or reads the password from the first line of the standard input with `--password-stdin`, which is handy in scripts.

A successful sign-in ends with "Signed in as {email} to the Studio {studio}." A refusal gives "Sign-in refused: the e-mail or the password is not correct." and exit code 3. If the folder is linked to another Studio, the command adds "This folder is linked to a project of the Studio {linked}: the commands launched here use that Studio." (`messages/login.py`).

On 29 September 2026 the sprint 25 measurement opened the session in 0.4 seconds. That run used the Italian interface, and the e-mail is masked in the transcript:

```powershell
ut --lang it login --studio http://127.0.0.1:8000 --email *** --password-stdin
```

On 6 October at 21:29, `ut login` without options ran into the local Studio, from the folder of the Calcolatrice iPhone, the iPhone-style calculator. Ports 8000 and 8080 lead to the same Studio: the first is the API, the second the web interface, which forwards its requests to the API. That run used the Italian interface too; here are the same two lines with the English messages from the code.

```powershell
ut login
```

```text
The Studio http://127.0.0.1:8000 is local and needs no sign-in: the commands work without `ut login`.
This folder is linked to a project of the Studio http://127.0.0.1:8080: the commands launched here use that Studio.
```

## `ut logout`

`ut logout` removes the sign-in from this computer even when the Studio does not answer. The file that holds the sign-ins is yours.

```text
usage: ut logout [-h] [--studio ADDRESS]
```

With a saved sign-in it sends `POST /auth/logout` and deletes the entry whatever happens; without one, it removes any entry left behind. Either way it exits with 0. The answers (`messages/logout.py`) are "Signed out of the Studio {studio}.", "Nobody is signed in to the Studio {studio} from this computer." and "The Studio {studio} does not answer: the sign-in was removed from this computer all the same." A local Studio gets the answer seen in the run of 6 October, shown here in English:

```powershell
ut logout
```

```text
The Studio http://127.0.0.1:8000 is local: there is no sign-in to close.
```

## `ut status`

This is the command to launch when you come back to a project. It tells you where the project stands, what is waiting for you and whether the code has fallen behind the design.

```text
usage: ut status [-h] [--offline | --all] [--json]
```

Inside a project it shows, in this order:

1. the name, the Studio, with "(local, no sign-in)" in local mode, and the mode of the project;
2. the table of the sections, with the same states as the web: "Waiting", "Your turn", "Up to date", "Update available" and "To update"; before the first complete pass, the table of the steps instead;
3. the sentences about the sections and "Next step: {action}";
4. the version of the knowledge folder here and in the Studio;
5. the development: commits recorded, the aligned point, open tasks;
6. if the design has moved on, "Code: aligned with design version {aligned}; the design is at version {current}: `ut align --from-design` brings the code up to the current design.";
7. the knowledge aligned with the code, the latest check of the acceptance criteria, what the twins learned, and the spending.

Outside a project, or with `--all`, it lists the projects of the account under the columns "Project", "Step" and "Your turn". `--json` prints a single document, with `schema_version` 1. `--offline` reads only the folder, and the command does the same on its own when the Studio does not answer: "State read from this folder: the Studio {studio} does not answer." The sentences are in `messages/status.py` and `messages/sections.py`.

Here is an excerpt of the run of 6 October 2026 at 21:29, with an empty configuration folder. The run used the Italian interface; the lines below are the English messages from the code, with the same values.

```powershell
ut status
```

```text
Calcolatrice Iphone
===================
Studio: http://127.0.0.1:8080 (local, no sign-in)
Mode: design and code

Section              State             Version
-------------------  ----------------  -------
Brief                Up to date        v2
Perspectives         Up to date        v2
User Twin            Update available  v1
Definition           Up to date        v3
Design & Evaluation  Update available  v5
Dossier              Up to date        v7
…
Knowledge folder: version 7 in this folder, version 7 in the Studio.
Development: commits recorded: 4; after the aligned point: 1; aligned commit: decd548; open tasks for the code: 0.
Knowledge: aligned with the code up to commit 30694ab (2026-10-06 08:42); proposals waiting: 3.
…
Generations run on the Claude subscription: no credit is spent.
```

The "Code:" line is missing because it arrived the next day, with `ut align --from-design`.

!!! warning "A saved sign-in counts for more than local mode"
    If the sign-in file holds a session for the folder's address, `ut` uses it even with a local Studio. On 11 October 2026 the folder of the gym project, linked to `http://127.0.0.1:8000`, found the session of an account from earlier sprints, and the Studio answered 404. The command then wrote "State read from this folder: the Studio {studio} does not find this project for your account." The way out is to close that session, or to point `ORCHESTWIN_CONFIG_DIR` at an empty folder.

    ```powershell
    ut logout --studio http://127.0.0.1:8000
    ```

    The defect is recorded and still open.

## `ut sections`

After the first complete pass a project is a set of sections, each with its own state. When something upstream changes, say a twin that learns during development, the sections downstream fall behind even when their content is still right. `ut sections update` re-anchors them to the new versions without generating them again.

```text
usage: ut sections [-h] [--json] ACTION ...
usage: ut sections update [-h]
```

Without an action the command shows the table of `ut status` with the sentences about what is missing; `--json` prints the object of the sections as the Studio gives it. With `update` it says which sections are behind, asks "Update and confirm these sections?" and sends `POST /projects/{id}/sections/alignment`. The Studio re-anchors each section and approves its gate (`projects/sections_service.py`), so your yes counts as an approval. Then `ut` downloads the knowledge folder again. A blocked section, such as a design that cites requirements that were taken out, does not re-anchor by itself, and the command tells you what to do.

On 1 October 2026 regenerating the twins of the calculator left the Definition behind. At 23:43 the re-anchoring took 8.2 seconds, with no generation at all. The run used the Italian interface (`--lang it`); this is its output with the English messages:

```powershell
ut --lang it --yes sections update
```

```text
Definition to update: something upstream changed. The content you approved stays the same, it is only re-anchored to the new versions.
Definition: updated and confirmed at version 2.
Sections updated: Definition.
Preparing the knowledge folder in the Studio...
Preparing the knowledge folder in the Studio: done in 0 s.
Downloading the knowledge folder...
Downloading the knowledge folder: done in 5 s.
Knowledge folder updated in orchestwin/: version 5.
```

A comparison made the same evening found the 10 requirements, the 4 stories and the 10 acceptance criteria unchanged.

## `ut activity`

Tests with people need to know how long each step lasts and how long you wait for the model. Since 4 October 2026 the Studio derives a timeline from the facts it already records. `ut activity` reads that timeline, and it opens or closes a study session.

```text
usage: ut activity [-h] [--json] [--csv FILE] [{start,stop}] [CODE]
```

Without an action it shows one row per section, with the columns "Start", "Approved", "Time", "Actions", "Gener.", "Wait" and "Retried". Underneath come the brief dialogue, the sessions and the limits of the measure, one of them being that the times include the pauses. With `--json` it prints the Studio's document, and with `--csv FILE` it writes the events to a file.

`ut activity start CODE` opens a study session and remembers it in `.orchestwin/activity-session.json`. The code starts with `SES-` (`src/orchestwin/activity.py`) and must not contain names. While the session is open, every command except `login`, `logout` and `activity` sends the Studio its start, its waits and its end, never its arguments or any content. The opening message says so: "Study session {code} started: from now on ut records which commands you launch in this folder and how long they take, without arguments or project content. Stop it with `ut activity stop`." `ut activity stop` closes the session.

On 4 October 2026 `ut activity` read the timeline of the measurement calculator in 1.0 seconds: 94 events, 18 successful generations, 51 owner actions and 27 hours on the design, pauses included. On 7 October the technical trial without people exported the session `SES-PT0`, opened from the web, with `--json` and `--csv`: 1,507 events from an account declared synthetic. What follows is an example of use, not a recorded run:

```powershell
ut activity start SES-P01
```
