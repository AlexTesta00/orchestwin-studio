# Development

Once the design is approved, the code is written outside the Studio, in the project's repository. The Studio does not read the repository and does not run code: what happens during development reaches it through these seven commands. The whole cycle, and the reasons behind its choices, are in [After the design](../framework/development.md); the files mentioned here are under `src/orchestwin/`. The runs quoted on this page were made with the Italian interface of `ut`: their transcripts show the English messages the code prints for the same lines, with the real numbers and dates.

## `ut code`

An external agent writes the code. The command starts it in your terminal, with the knowledge folder as context and the open tasks as the work order. The default agent is Claude Code, but it can be a command of your own.

```text
ut code [-h] [--task CODES] [--agent {claude,custom}] [--command TEXT] [--model NAME] [--headless]
               [--max-agent-usd USD] [--spend] [--dry-run]
               [REQUEST ...]
```

| Option | Meaning | Without the option |
| --- | --- | --- |
| `REQUEST …` | your request, in your own words | the open tasks |
| `--task CODES` | the tasks to carry out, separated by commas or spaces | every open task |
| `--agent` | claude or custom | claude |
| `--command TEXT` | the command of the custom agent, with placeholders such as `{prompt_file}` | none |
| `--model NAME` | the Claude Code model, for example opus | the default one |
| `--headless` | Claude Code works and ends by itself | a conversation |
| `--max-agent-usd USD` | spending ceiling on your account, with `--headless` | none |
| `--spend` | switches on the paid MCP tools | off |
| `--dry-run` | writes the work order without starting the agent | the agent starts |

Agent, command and model are remembered in `.orchestwin/code.json`. With the approved design in the folder, the command writes the work order `prompt.md`, in English, and the MCP configuration into `.orchestwin/code/`; one of the rules in the order is "Do not commit and do not push" (`cli/flows/code_order.py`). Before starting, it reminds you that the agent spends on your account, outside the Studio's ceilings, and asks "Start the agent now?" (`cli/messages/code.py`).

With `--headless` Claude Code receives `--print`, `--permission-mode acceptEdits` and `--allowedTools mcp__orchestwin-twins`. It edits files and questions the twins, but it runs no commands, not even the tests. When the work is over, the command lists the changed files and, if the agent exited with 0, writes into `.orchestwin/code/design.json` the design version the code comes from. The commit is yours to make, and the `.orchestwin/code/` folder stays out of Git.

On 30 September 2026, on Calcolatore mancia per camerieri, a tip calculator for waiters, the command below worked for 6 minutes and 4 seconds and brought the design's three buttons, 5, 10 and 15%, into the app. The paths in the excerpt are shortened.

```powershell
ut code --task TSK-006 --headless --max-agent-usd 3
```

```text
Coding agent for "Calcolatore mancia per camerieri"
===================================================
Agent: Claude Code (…\claude.EXE).
Mode: headless, Claude Code works alone, applies its edits to the files without asking and ends by itself.
The most the agent may spend in this run: 3.00 USD, on your Claude Code account.
Work: the tasks TSK-006.
Work order: …\.orchestwin\code\20260930-114726\prompt.md
The agent works with your own account of that agent: what it spends is outside the spending ceilings of the Studio, which does not count it.
Start the agent now? [Y/n]
```

## `ut test`

An acceptance criterion counts only when it is checked on the real application. The command does this in the browsers already installed, Chrome, Chromium or Edge through CDP and Firefox through WebDriver BiDi, with a WebSocket client that uses the standard library alone. It downloads nothing.

```text
ut test [-h] [--url ADDRESS | --static FOLDER] [--browser {chrome,firefox,all}] [--criteria CODES]
               [--plan {latest,new}] [--no-review] [--no-tasks] [--max-usd USD] [--open] [--json]
```

| Option | Meaning | Without the option |
| --- | --- | --- |
| `--url ADDRESS` | http or https address of the application | the remembered one |
| `--static FOLDER` | folder with `index.html`, served by `ut` | the remembered one |
| `--browser` | chrome, firefox or all | all |
| `--criteria CODES` | criteria to verify, such as AC-001,AC-003 | all of them |
| `--plan` | latest reuses the plan, new asks for one | latest |
| `--no-review` | no critiques from the twins | critiques |
| `--no-tasks` | does not offer findings as tasks | offers them |
| `--max-usd USD` | the most to spend on the plans | 2.00 |
| `--open` | opens the report at the end | does not open it |
| `--json` | prints the run as JSON | text |

The application you name the first time is kept in `.orchestwin/test.json`. The model writes the plan by reading the page as it opens, and the plan holds until the requirements or the design change, or until `ut align` asks for a new one. Every path runs in every browser, with a screenshot for each step; the HTML report and the screenshots go into `.orchestwin/tests/`, and the run is recorded in the Studio. Then come the twins' critiques and the choice of which findings to turn into tasks (`cli/messages/test.py`). With a failed or blocked criterion the exit code is 1.

On 30 September 2026 the first run on the static app Mancia Subito, roughly "Tip Now", took 195.5 seconds with 12 criteria.

```powershell
ut test --static . --browser all
```

```text
Acceptance tests of "Calcolo della mancia da terminale"
=======================================================
Application: the folder ., served by this computer at http://127.0.0.1:56671/.
Browsers: Google Chrome 151.0.7922.76, Mozilla Firefox 157.0.
The Studio now writes a test plan: the model reads the page as it opens and writes the paths for the acceptance criteria.
…
New test plan: 13 paths, 5 criteria not covered.
…
Criteria: 7 passed, 0 failed, 0 blocked, 5 not covered, 0 not run.
```

All 26 runs, 13 paths in two browsers, passed. The criteria left uncovered needed an inspection of the screen, a smartphone, a person or a date. The plan is not repeatable, though: from the same input the model later wrote a different one.

## `ut tasks`

Tasks for the code, with TSK-nnn codes, connect the twins' findings to the agent's work. They come from the tests, from the commits, from the decision on a commit or from you, and `ut code` reads them from the knowledge folder.

```text
ut tasks [-h] [--all] [--json] ACTION ...
ut tasks add [-h] TEXT [TEXT ...]
ut tasks done [-h] [--note TEXT] CODE [CODE ...]
ut tasks drop [-h] [--note TEXT] CODE [CODE ...]
ut tasks reopen [-h] CODE [CODE ...]
ut tasks from-test [-h] [--run RUN_ID]
ut tasks from-commit [-h] [COMMIT]
```

Without an action the command lists the open tasks; `--all` adds the done and dropped ones, and with the Studio switched off the list comes from the folder. With `add` you write a task of your own. The `done` and `drop` actions close one or more tasks, with an optional `--note`, while `reopen` opens them again. With `from-test` and `from-commit` you choose which of the twins' findings become tasks: "Which become tasks? Type their numbers separated by commas or spaces, a for all; Enter for none:" (`cli/messages/tasks.py`). Every change publishes the folder again.

On 30 September 2026 the task the agent had carried out was closed like this. The note and the text of the task were written in Italian, like the rest of that project, and are translated here.

```powershell
ut tasks done TSK-006 --note "three buttons in commit da73b84"
```

```text
Tasks marked as done: 1.
- TSK-006: Replace the free percentage field with three buttons, 5%, 10% and
  15%, keeping the last one chosen selected after New calculation, as in the
  Calculate the tip and New calculation screens.
```

## `ut verify`

After a commit one question is left: do the code, the Definition and the Design still agree? The command records the commits in the Studio, has the twins review them and asks the model for a verdict. You decide. Until 6 October 2026 it was called `ut align`; the supervisors asked for it to be renamed `ut verify`, next to `ut test`, and for `align` to be left to the command that realigns.

```text
ut verify [-h] [--since COMMIT] [--latest] [--dry-run] [--decide COMMIT] [--recheck]
```

| Option | Meaning |
| --- | --- |
| `--since COMMIT` | the commits after this one, not after the aligned point |
| `--latest` | only the newest commit |
| `--dry-run` | records without reviewing or spending |
| `--decide COMMIT` | opens again the decision on a reviewed commit |
| `--recheck` | repeats the reviews made against older versions |

You need a Git repository. The command records the commits after the aligned point, that is the last commit marked as aligned, and does not send for review the ones that touch only `orchestwin/`. Every twin reviews every commit. The model gives one of four verdicts: `ALIGNED` if everything adds up, `CODE_DRIFT` if it is the code that has to change, `DESIGN_OUTDATED` or `REQUIREMENTS_OUTDATED` if the design or the requirements do not yet describe a legitimate evolution (`projects/code_changes.py`).

Then you decide. Five decisions can be recorded. `ALIGNED` moves the aligned point, `CODE_TASKS` writes tasks, and `DESIGN_CHANGE` and `REQUIREMENTS_CHANGE` ask for a new version of the design or of the requirements. The fifth, `DISMISSED`, is used by the command for older commits that have the same verdict as the newest one. "Leave it for later" records nothing, and `--yes` never approves a design or requirements on your behalf.

On 7 October 2026 commit `05d1fad` of Calcolatrice iPhone, the iPhone-style calculator, brought the ⌫ key of design 7 into the code. The aligned point was no longer in the history of the folder, which had been recreated on 6 October, so the starting point was given by hand.

```powershell
ut verify --since 30694ab
```

```text
Alignment of "Calcolatrice Iphone"
==================================
Approved reference: requirements version 4, design version 7 (alternative DES-001).
…
Commits that change only the knowledge folder, recorded without a review: 3 (538f7d6, 127ecbc, fafb35c).
Commits for the twins to review: 1. Twins in each review: 3. Each twin gives its opinion on each commit, then the model says whether code, design and requirements are still aligned.
…
Review of commit 05d1fad: done in 1 min 51 s.
…
The code departs from the approved design or requirements: the code should
change (CODE_DRIFT).
…
What do you do with this commit?
  1. Record these tasks for the code
  2. Mark it as aligned anyway
  3. Ask for a new version of the design that follows this commit
  4. Ask for a change of the requirements that follows this commit
  5. Leave it for later
```

The conflict was real: the ⌫ key took away the wide zero that REQ-001 still asked for. With `ut verify --decide 05d1fad` the decision was the first option, four tasks from TSK-005 to TSK-008.

## `ut align`

When code and knowledge diverge, one side has to follow the other. On 6 October 2026 the supervisors asked for a command that "starts from something that diverges and changes the other part to align with it", and `ut align` does this in both directions.

```text
ut align [-h] [--since COMMIT] [--dry-run] [--pending] [--from-design] [--max-agent-usd USD]
```

| Option | Meaning |
| --- | --- |
| `--since COMMIT` | the commits after this one; with `--from-design`, the design version to start from |
| `--dry-run` | shows what it would do, without spending |
| `--pending` | decides the waiting proposals; it takes no other option |
| `--from-design` | brings the code up to the approved design |
| `--max-agent-usd USD` | the agent's spending ceiling, only with `--from-design` |

### From the code to the knowledge

The command starts from `--since`, from the last commit it reviewed or from the aligned point of `ut verify`. A single generation reads the diff and proposes at most twelve updates, six per section, numbered ALN-nnn (`projects/knowledge_alignment.py`). Every proposal cites the commit, the file and an excerpt of the diff. It also carries the sentence "A hypothesis of the model drawn from the code diff: no person has verified it." You decide them one by one with "Apply", "Edit the text and apply", "Skip" or "Later", the default answer.

A proposal for the Definition goes through the requirements revision and the gate. One for the Design rewrites the texts of the chosen alternative without touching the mockup. One for the tests writes `.orchestwin/tests/redo.json`, so that the next `ut test` asks for a new plan.

On 6 October 2026 Calcolatrice iPhone had a scientific mode written by hand, outside `ut`, in commit `30694ab`. The commit subject in the transcript is translated from Italian.

```powershell
ut align --since 5157efa
```

```text
Knowledge of "Calcolatrice Iphone" aligned with the code
========================================================
Starting point: commit 5157efa, given with --since.
Commits to review: 1.
- 30694ab  2026-10-06 09:42  feat: scientific mode with functions, power and pi
  (files: 5)
Commits recorded now in the Studio: 1.
The model reads the diff of the commits and proposes updates to the Definition, the Design and the test plan. No proposal changes anything until you approve it.
This generation runs on the Claude subscription: it spends no credit. Estimated time: about 2 min.
…
Reading of the code changes: done in 1 min 27 s.
```

There were seven proposals. With `ut align --pending`, ALN-001 took the requirements to version 3 and ALN-006 the design to version 5, while ALN-007 asked for a new test plan.

### From the design to the code

The design can change when the code already exists. With `--from-design` the command starts from the version the code is aligned with, the higher of `.orchestwin/code/design.json` and the point of `ut verify`, and prints the differences that touch the code. If there are none, the local aligned point moves forward at once, even with `--dry-run`. Otherwise, provided the repository is clean, it writes a work order limited to those differences and starts the agent the way `ut code` does, after the question "Start the agent now? It works on your Claude Code account, not on the Studio." (`cli/messages/align.py`).

On 7 October 2026 the design of Calcolatrice iPhone had gone from version 3 to version 7. The first dry run counted 157 differences, because the model had renumbered the elements; once elements were matched by fingerprint, there were 20.

```powershell
ut align --from-design
```

```text
Code of "Calcolatrice Iphone" aligned with the design
=====================================================
Starting point: design version 3, the aligned point of `ut verify`.
Approved design: version 7, alternative DES-001.

What changes from design 3 to design 7: 20 differences
======================================================
…
+ screen SCR-001: element ELM-022 "⌫" added
…
~ mockup styles changed
One other difference concerns critiques and concerns: it does not touch the code.
…
The agent ended after 2 min 57 s.
Files with changes not committed yet (4):
- public/app.js
- public/index.html
- public/styles.css
- public/sw.js
```

Claude Code was working without a conversation, on Opus. It could not run the tests ("I couldn't run the tests: `npm test` and `node --test` both needed approval and none was given."), and its work became commit `05d1fad`, the one described above.

## `ut watch`

The command stays open while you work and records every new commit in the Studio. It has the twins review commits only with `--twins` and within a spending ceiling; the decisions stay with `ut verify`.

```text
ut watch [-h] [--twins] [--max-usd USD] [--interval SECONDS] [--once]
```

| Option | Meaning | Without the option |
| --- | --- | --- |
| `--twins` | the twins review every commit | recording only |
| `--max-usd USD` | highest estimated spending of the session | 5.00 |
| `--interval SECONDS` | seconds between two checks, at least 2 | 15 |
| `--once` | a single check | until Ctrl+C |

Without `--twins` it tells you at once: "The twins do not review the commits: add --twins to have them reviewed." (`cli/messages/watch.py`). On the subscription the reviews spend no credit, but the ceiling counts them at paid prices, so that the subscription does not get used up too fast. On 29 September 2026 `ut watch --twins --interval 5` had a commit reviewed in 60 seconds; on the next one the review failed twice because of a defect in the answer schema, fixed afterwards.

## `ut mcp`

The agents in your editor work better when they know the approved project. The command starts the `orchestwin-twins` MCP server on standard input and output; with `--config claude-code`, `cursor` or `vscode` it prints the configuration to copy instead.

```text
ut mcp [-h] [--spend] [--config EDITOR]
```

There are fifteen tools, counted in `cli/mcp/tools.py`. The twelve free ones read the knowledge folder: `project_state`, `list_twins`, `get_twin`, `get_requirements`, `get_design`, `get_feedback`, `get_test_results`, `get_tasks`, `get_evidence`, `get_why`, `get_validation`, `get_scenario_walkthrough`. The three paid ones, `ask_twin`, `review_changes` and `run_tests`, answer with an error until you add `--spend`. On 29 September 2026 there were eight.

Here is an example that does not come from a recorded run, with the project in the imaginary folder `C:/projects/calculator`.

```powershell
ut mcp --config claude-code
```

```text
Without --spend the paid tools ask_twin, review_changes and run_tests answer with an error; to allow them, add --spend.
To add the server to Claude Code, launch this command from the folder of the project:
claude mcp add orchestwin-twins -- ut --project-dir C:/projects/calculator mcp
Or write this in the file .mcp.json of the folder of the project:
{
  "mcpServers": {
    "orchestwin-twins": {
      "command": "ut",
      "args": [
        "--project-dir",
        "C:/projects/calculator",
        "mcp"
      ],
      "cwd": "C:/projects/calculator"
    }
  }
}
```

Many of these commands can also be started from the [Visual Studio Code panel](../architecture/vscode-extension.md).
