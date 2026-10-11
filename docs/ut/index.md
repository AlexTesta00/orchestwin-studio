# ut reference

`ut` brings the steps of the Studio into the terminal and, once the design is done, follows the development in the code folder. It started from a suggestion one of the supervisors made on 28 September 2026: a command-line tool that runs the steps, with `ut init`, `ut design`, `ut test` and `ut align` as examples. The next day it existed, with seven commands. Today it has twenty-two.

`ut` never calls the model itself. It talks to the Studio's API, and the Studio generates with `claude --print` ([Generating with claude --print](../installation/generation.md)). `ut code` and `ut align --from-design` are the exception: they start an external coding agent, such as Claude Code, which works with your own account. Throughout this reference the messages are quoted verbatim from the English interface, and file paths given without a root live in `src/orchestwin/cli/`.

## Installation

`ut` is part of the repository's Python package and needs Python 3.12 or later. From the root of the repository, with the virtual environment active:

```powershell
npm run install:python
```

The script installs the package in editable mode, together with the development dependencies; for the command alone, `pip install --editable .` is enough. If `ut --version` answers `ut 0.0.0`, the command is installed. Everything else is in [Requirements and installation](../installation/index.md).

## Global options

Global options go before the command, as in `ut --lang en status`. The descriptions come from `ut --help`.

| Option | Meaning | Without the option |
|---|---|---|
| `-h`, `--help` | show this help and exit | - |
| `--version` | show the version of ut and exit | - |
| `--lang {it,en}` | language of the messages: it or en | `ORCHESTWIN_LANG`, then the system language, then English |
| `--no-color` | do not use colours | colours on a terminal, unless `NO_COLOR` is set |
| `--yes` | confirm the estimated spending without asking | the command asks |
| `--project-dir PATH` | folder of the project, when it is not the one you are in | the current folder |
| `--debug` | show every technical detail when an error happens | one line |

`--yes` also answers a few questions, such as the ones asked by `ut sections update` and `ut design restore`, but it never takes the place of a step's approval in `ut init`, `ut push`, `ut verify` or `ut align`. Without a command, `ut` prints the help, writes "Choose a command, for example `ut status`." and exits with 2.

## The two folders of a project

The `orchestwin/` folder is the Dossier downloaded from the Studio. You start reading from `ORCHESTWIN.md`; `orchestwin.json` keeps the hash of every file, and each step has a folder with a `.json` document and a `.md` one. The Definition and the design also carry CSV tables and Mermaid diagrams, and the design carries the chosen mockup as well. `ut` adds a `.gitattributes` with `* -text` to the folder, so that Git does not rewrite the line endings and the hashes stay valid.

The `.orchestwin/` folder is the link with the Studio: `project.json` with the address, the project and the mode (`DESIGN_ONLY` or `DESIGN_AND_CODE`), the approved versions in `steps/`, the design previews in `previews/` and the working folders of the development commands. `ut` finds the project by climbing from the current folder up to `.orchestwin/project.json`, so a command launched in a subfolder works on the project that contains it. The details are in [The knowledge folder](../architecture/knowledge-folder.md).

## Sign-in and local mode

A sign-in opened with `ut login` is kept in your user folder, never in the project: `%APPDATA%\orchestwin\sessions.json` on Windows, `~/Library/Application Support/orchestwin` on macOS, `~/.config/orchestwin` or `$XDG_CONFIG_HOME/orchestwin` elsewhere. The `ORCHESTWIN_CONFIG_DIR` variable picks another folder. The password is never saved.

Since 6 October 2026 the Studio can run in local mode ([Local mode and accounts](../installation/local-mode.md)). When `GET /api/v1/auth/mode` answers `LOCAL_OWNER` and the address is the computer's own, `ut` works without signing in. A sign-in saved for that address still comes first, as [`ut status`](access-and-status.md#ut-status) explains.

## Before a generation

Every command that puts the model to work tells you first how long you will wait. On the Claude subscription it writes "This generation runs on the Claude subscription: it spends no credit. Estimated time: about {minutes}." and asks nothing. With pay-as-you-go billing it shows the amount and the credit left and, above 0.50 USD, asks "Go ahead with this spending?" (`messages/costs.py`). The estimates are fixed per operation, in `costs.py`: one minute for the brief dialogue, three for the design alternatives, ten for a mockup.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | the command succeeded |
| 1 | generic error, including failed criteria in `ut test` or an agent that exited with an error in `ut code` |
| 2 | wrong usage, an invalid Studio address, or `http` towards another computer |
| 3 | sign-in missing, expired or refused |
| 4 | the Studio does not answer, or another service answers at that address |
| 5 | spending not confirmed, or a spending ceiling exceeded |
| 6 | the folder is not linked to a project |
| 7 | the knowledge folder does not pass the verification |
| 130 | the command was interrupted |

An unexpected error prints "Unexpected error: {kind}: {detail}. Launch the command again with --debug to see the details."

## The commands

| Page | Commands |
|---|---|
| [Access and status](access-and-status.md) | `ut login`, `ut logout`, `ut status`, `ut sections`, `ut activity` |
| [ut init](init.md) | `ut init` |
| [ut design](design.md) | `ut design`, `ut design critique` |
| [Definition, twins, evidence and archetypes](definition-and-twins.md) | `ut definition`, `ut twins`, `ut evidence`, `ut archetypes` |
| [Dossier, push, why and validation](dossier.md) | `ut package`, `ut push`, `ut why`, `ut validation` |
| [Development](development.md) | `ut code`, `ut test`, `ut tasks`, `ut verify`, `ut align`, `ut watch`, `ut mcp` |

That makes twenty-three entries: the twenty-two commands of `ut --help` plus `ut design critique`, an action of `ut design` that gets a section of its own. Every command also has its own help, such as `ut design --help`, and the syntax shown in these pages is copied from there.
