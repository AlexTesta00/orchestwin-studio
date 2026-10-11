# Generating with claude --print

Every proposal the Studio makes, from the questions in the Brief to the redraw of a mockup, is written by Claude Opus 5.5. The Studio does not call the model through the API: it runs the Claude Code command line installed on your computer, which uses the subscription you signed in with.

## Why the subscription

At the end of September 2026 the Studio generated through the Anthropic API and paid for every token. The iPhone-style calculator in the video for the supervisors, recorded on 30 September 2026, cost 9.17 USD. On 1 October 2026, commenting on that video, the first supervisor asked for the Studio to generate with `claude --print` and the subscription. The same day the calculator was redone on the subscription, from the idea to the approved design. It took 15 generations, all successful at the first attempt, about 12 minutes, and cost nothing.

Since then the paid API has been out of the recommended configuration and the README, although its code is still in the repository and in the tests. Cost is not the only reason. The Agent SDK documentation, read on 1 October 2026, does not allow offering claude.ai login to other people inside your own product. So a Studio on the subscription is for the person who holds it, and a Studio open to other people has to use API keys.

## Preparing Claude Code and the files

Install Claude Code, run `claude` once and sign in with the account of your subscription. Then copy `scripts/model-providers.claude-code.example.json` to `var/studio/model-providers.json`. The file decides which model works on which task, and with how much effort (`effort`, from `low` to `max`). The example has two entries, both on the same model.

| Entry | Model | `effort` | Timeout | Tasks |
|---|---|---|---|---|
| `opus-design` | `claude-opus-5-5` | `high` | 1,200 s | `design`: alternatives, mockups and changes |
| `opus` | `claude-opus-5-5` | `medium` | 900 s | all the others |

The routes under `routes` assign the entries: `default` for everything, `tasks` per task, `purposes` for a finer purpose. Claude Code entries must have zero prices, or the Studio rejects the file with `SUBSCRIPTION_MODEL_PRICED`.

The output ceiling that the Studio passes to Claude Code is the output expected for the task, capped at `max_output_tokens`, plus `reasoning_allowance_tokens`, the allowance for reasoning. In the example both are 64,000. The allowance exists because the model thinks before it writes. On 28 September 2026 a mockup stopped at the 64,000-token ceiling after 43,559 tokens of reasoning and was lost; with an allowance of 64,000, three mockups out of three went through at the first attempt.

The start script finds the providers file through the local settings, `var/studio/local-settings-hosted.json`, written with absolute paths.

```json
{
  "node": "C:\\Program Files\\nodejs\\node.exe",
  "providers_config_file": "C:\\...\\orchestwin-studio\\var\\studio\\model-providers.json"
}
```

The `node` field is the path to your `node.exe`, which may live somewhere else if you use a version manager. The script uses it for the web interface, the API for the syntax checks on JavaScript.

## What happens at each generation

For each generation the `CLAUDE_CODE_CLI` provider creates a temporary folder, writes the system prompt into it and starts `claude` as a child process. The command is built in `src/orchestwin/models/claude_code_cli.py:206-246`, and with the `opus-design` entry it is this one.

```text
claude --print --output-format json --model claude-opus-5-5 --effort high
  --no-session-persistence --safe-mode --tools ""
  --system-prompt-file <temporary folder>/system-prompt.txt
  --json-schema <response schema>
```

The project context goes in through standard input, and the answer comes back as JSON that matches the task's schema. If it arrives truncated at the ceiling, the Studio throws the whole answer away. Claude Code's tools are switched off, except `Read` on attached images: the images of a critique and, for mockups, up to two references placed in `var/studio/references`.

The child process receives no keys. The Studio strips `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, the Bedrock, Vertex and Foundry variables and every `ORCHESTWIN_*` variable from its environment (`claude_code_cli.py:57-67` and `188-203`). Only the subscription sign-in remains.

Before it starts, the Studio checks Claude Code without generating anything: `claude --version` must answer, and `claude auth status` must show a sign-in made with the `claude.ai` method. Otherwise the start script stops and `readiness.json` gives the reason, for example `CLAUDE_CODE_NOT_LOGGED_IN`. If `claude` is not on your `PATH`, put the absolute path of the program in the `executable` field of the providers file.

## What each generation leaves behind

Every generation leaves in the database the request, the raw answer with its SHA-256 hash, the input, output, reasoning and cache tokens, the duration, the model that actually answered and the links to the artifacts it produced. You read the project's receipt with `GET /projects/{id}/model-usage`, which lists the last 200 generations with the totals. The `GET /model-runtime/budget` route returns the ceilings, the spending and the billing type, `SUBSCRIPTION` when everything goes through the subscription; in that case the cost of a generation stays empty. Before generating, `ut` reminds you: "This generation runs on the Claude subscription: it spends no credit. Estimated time: about {minutes}." The evidence tables are described in [Providers, model contracts and guard](../architecture/models.md).

## How long it takes

These times were measured. The first row ran on the API, the others on the subscription.

| Date | Project | Generation | Time |
|---|---|---|---|
| 28 September 2026 | three measurement projects | one mockup | 277 to 621 s |
| 1 October 2026 | the iPhone-style calculator | two mockups in parallel | 285 and 342 s |
| 6 October 2026 | Calcolatrice iPhone | seven `ut align` proposals from the code | 1 min 27 s |
| 7 October 2026 | Calcolatrice iPhone | one change to the design, asked in words | 1 min 57 s |
| 9 October 2026 | Calcolatrice iPhone | the redraw of a design as a mockup | 5 min 41 s |
| 10 October 2026 | the gym project | three mockups drawn together | 10 min 35 s |

The estimates `ut` prints before it starts are fixed per operation: 3 minutes for the alternatives, 10 for a mockup. On 10 October 2026, for the design step of the gym project, the estimate said 13 minutes and it took a little over 17.

## The limits

The subscription has usage limits. At 14:06 on 4 October 2026 the one used by the command line answered `RATE_LIMITED`, and generations resumed at 14:49, when `claude` was signed in again with another subscription. The Studio does not move to the API on its own: you change the route only in the providers file.

Opus 5.5 needs Claude Code 2.1.280 or later. And on 1 October 2026 the Claude Code documentation announced that `--print` might stop using the subscription sign-in by default in the future.

## With the paid API

The `scripts/model-providers.example.json` file uses the `ANTHROPIC_HOSTED` provider, with prices per million tokens and the key in the `ORCHESTWIN_ANTHROPIC_API_KEY` variable. The `budget` ceilings matter only on this route, and they are checked before every call: in the example, 2.50 USD per generation, 10 per project, 60 in total. On the subscription the prices are zero, the estimate is zero and the check lets everything through. On the API, when the estimate goes above 0.50 USD, `ut` asks "Go ahead with this spending?" The critique of an existing design and the reference images stay out of this route, because only `CLAUDE_CODE_CLI` receives attached files.

## Without a model

Without Claude Code the Studio starts with the deterministic generators, as [Without a model](studio.md#without-a-model) explains. You go through the steps, but you cannot choose or approve a design.
