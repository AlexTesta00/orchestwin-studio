# The test suites

The Studio has four families of tests: Python for the backend and for `ut`, the Vue frontend, the Visual Studio Code extension, and integration on a real PostgreSQL. On 11 October 2026, at commit `a850cd6`, pytest collects 12,436 cases from 517 `test_*.py` files. Of these, 12,262 run without a database and 174 need PostgreSQL, while 5 carry the `browser` marker. The Python tests add up to 247,634 lines, more than the code they test (181,798 in `src/orchestwin`).

## Why three operating systems and two browsers

On the morning of 29 September, as sprint 24 was closing, two defects turned up that the checks had missed. In Firefox I found the table of the twins' opinions collapsed with seven twins in it, while Chrome, where all the visual checks had been made, showed it correctly. In CI a test passed on Windows and failed on Ubuntu and macOS, because it wrote a provider's file as `C:/models/proposal.json`, a path that is absolute only on Windows. The code was right. The test was wrong.

Since that day every test has to pass on Ubuntu, macOS and Windows, with no dependence on paths, encodings, line endings, permissions or the terminal. Every visual check is made in Chrome and in the installed Firefox. The Linux container described further down was born the same day; on macOS the tests run only in [CI](ci.md).

## Python tests by folder

In the collection of 11 October, four of the `test_*.py` files are helper modules with no cases.

| Folder | Files | Cases | Integration | What it tests |
|---|---|---|---|---|
| root | 4 | 35 | 0 | configuration and access |
| `agents` | 9 | 142 | 0 | agents and perspectives |
| `api` | 74 | 1,648 | 1 | FastAPI routes |
| `artifacts` | 55 | 2,677 | 1 | design, mockups, "Why?" |
| `cli` | 104 | 3,341 | 0 | `ut`, against the fake Studio |
| `evaluation` | 10 | 140 | 0 | twin reviews |
| `identity` | 7 | 73 | 0 | accounts and sessions |
| `integration` | 47 | 163 | 163 | full flows on PostgreSQL |
| `knowledge` | 35 | 888 | 1 | knowledge folder |
| `models` | 75 | 1,654 | 2 | adapters and instructions |
| `persistence` | 22 | 88 | 6 | database and migrations |
| `projects` | 48 | 1,194 | 0 | brief, requirements, sections, development |
| `twins` | 19 | 355 | 0 | User Twins and archetypes |
| `workflow` | 8 | 38 | 0 | gates |
| Total | 517 | 12,436 | 174 | |

The configuration lives in `pyproject.toml`. It declares two markers, `integration` and `browser`, admits no others, and turns every warning into an error except a deprecated alias that `starlette.testclient` still uses. The root `conftest.py` empties `ORCHESTWIN_DESIGN_REFERENCES` and `ORCHESTWIN_DESIGN_SYSTEM` for every test, so that no test reads `var/studio` and the Apple design system, the default since 10 October, does not change the instruction hashes.

| Command | What it runs |
|---|---|
| `npm run test` | `python -m pytest -m "not integration"` |
| `npm run test:integration:python` | `python -m pytest -m integration src/test/python/integration` |
| `npm run test:coverage:python` | the same as `npm run test`, with line and branch coverage |
| `npm run test:coverage:integration:python` | the same as the integration run, adding coverage and writing `coverage.xml` |

## The CLI's fake Studio

The CLI talks to the Studio only over HTTP, so the 3,341 cases in the `cli` folder test it against a fake Studio. The fake is a real HTTP server, in memory, on `127.0.0.1`, and it imitates 178 API operations without PostgreSQL, a model or a network. The `FakeStudio` class combines 19 mixins, one per area. Its constructor chooses the language, the number of twins, the hosted model, the spending ceiling and the `ACCOUNTS` or `LOCAL_OWNER` mode, and a test can make a request fail, lose a job or inject the clock.

A fake can drift away from the real thing without anybody noticing. The tests in `test_fake_studio_routes.py` prevent it: every route of the fake has to exist in the OpenAPI of the real application, and its answers have to pass the real Pydantic models and domain rules. In the sprint 46 refactor the old 15,215-line file became the `cli/support/fake_studio/` package of 28 modules, and the collection of the `cli` folder stayed identical.

## PostgreSQL

Of the 174 integration cases, 163 live in the 47 files of `src/test/python/integration/` and 11 in other folders. The address comes from `ORCHESTWIN_DATABASE_URL`. Two modules on proposal evidence also want `ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL`, and they are skipped without it. In CI the database is the runner's PostgreSQL 18; locally it is the Compose one on port 15432.

No test empties tables or switches off the audit triggers. Each test in the `test_postgresql_*` modules gets a schema of its own, `test_orchestwin_` followed by 32 hexadecimal digits, migrated to the latest revision and seen through a `search_path` that leaves out the public tables. When the test ends, the schema is dropped only if it is still the one the test created. The same mechanism checks that the migrations can be reversed. The full-flow tests start the real API on a free port, never 8000 or 8080, with deterministic fake models.

CI runs only the `integration/` folder, so the 11 marked tests that live elsewhere never start on the runners. The local sprint chains run all of them.

## Browser tests

Two commands, `ut test` and `ut design critique --url`, open the browsers installed on the computer: Chrome through the DevTools Protocol, Firefox through WebDriver BiDi. Almost every test uses fake browsers. The five `browser` cases use the real ones, on a local page and with the real Studio, and they are skipped when the browser is missing or when `ORCHESTWIN_SKIP_BROWSER_TESTS=1` is set. In CI they run on the runners, where they have already caught a defect: in the sprint 41 pull request, Firefox on Ubuntu did not start ("no answer within 30 seconds"). Sprint 42 raised the wait to 60 seconds, made `ut` recognise a Firefox installed as a snap and added a second attempt.

## Tests that pin the instruction hashes

A new feature, as long as it is switched off, must not change a single byte of what reaches the model, and the tests make sure it does not. The system instruction, the context, the answer schema and the request each have a SHA-256 hash written as a constant in the test file, such as `PLAIN_INSTRUCTION_SHA256` in `models/test_generated_mockup_instructions.py`. The test names carry the reason, as in `test_an_alternative_without_direction_keeps_the_instruction_and_the_context_of_today`. When an instruction really changes, the new hash is written by hand, together with the new contract version where there is one, and the change is there to see in the diff. The structured request is content-addressed: changing one of its fields without recomputing the hash fails with "content hash is inconsistent". Outside the repository the contract guard does the same job (see [Sprint tools and live trials](tools.md) and [Providers, model contracts and guard](../architecture/models.md)).

## Frontend and extension

The frontend has 164 `*.spec.ts` files that run with vitest 4.1.11 on jsdom 30 (`npm run test:frontend`): 2,482 tests in the latest chain, all green. Of those 164 files, 74 call `expectAccessible`, which hands the mounted component to axe-core 4.13.0 with the WCAG 2.0 and 2.1 rules at levels A and AA. Colour contrast is left out, because jsdom does not render the page. Frontend quality, meaning eslint with no warnings, prettier, vue-tsc and tsc, runs in CI in the `build` job.

The extension has 13 `*.test.js` files that run with `node --test` and without Visual Studio Code (`npm run test:editor`), and 197 tests out of 197 pass. To try the extension inside a real Visual Studio Code there is `npm run check:editor-host`, which runs only locally (see [The Visual Studio Code extension](../architecture/vscode-extension.md)).

## Linux before CI

Locally there is Python 3.13, CI uses 3.14, and the WSL on the computer had only 3.12. To see a Linux failure before sending a commit, the sprints have used the `orchestwin-test:py314` container since 29 September. It is a 246 MB `python:3.14-slim` image with the dependencies of the backend and of the tests, built from a seven-line Dockerfile kept outside the repository. The repository is mounted read-only. From Git Bash, with `REPO` set to the repository folder written with forward slashes:

```bash
MSYS_NO_PATHCONV=1 docker run --rm --pull=never --volume "$REPO:/repo:ro" --workdir /repo --env PYTHONPATH=/repo/src orchestwin-test:py314 python3 -m pytest src/test/python -m "not integration" -q -p no:cacheprovider -W error
```

Without git and without the installed package, `api/test_server.py` cannot find the entry point: this is the known environment failure. Up to sprint 45 the baseline had 19 red cases, and 18 of them were tests of the `training` package, which sprint 46 deleted.

## The latest numbers

The final chain of sprint 46 ran on 11 October between 04:06 and 05:09, and the sources stayed unchanged through every suite.

| Suite | Result | Duration |
|---|---|---|
| Ruff, check and format | 1,183 files clean | 0.8 s |
| Frontend quality | green | 44.5 s |
| Frontend build | green | 5.5 s |
| Frontend, vitest | 2,482 passed in 164 files | 150.9 s |
| Extension | 197 of 197 passed | 1.9 s |
| Python on Windows | 12,248 passed, 13 skipped, 174 deselected | 23 min 28 s |
| Python on Linux, Docker | 12,242 passed, 17 skipped, 2 failed | 20 min 49 s |
| PostgreSQL | 173 passed, 1 skipped | 14 min 35 s |

The chain ran before commit 23, which adds one test; that is why the Windows cases add up to 12,435. The skipped PostgreSQL test is the probe with a real model, which runs only when it is switched on by hand. Of the two Linux failures, one is the environment failure. The other, in `cli/test_session.py`, checks that the string "4242" from the previous process does not remain in the `ut` lock, and the random identifier of the new lock happened to contain it. A second run is green.

## Coverage

Codecov receives line and branch coverage only from the Ubuntu job of the CI, which adds together the tests without integration and the integration tests. On 11 October the public Codecov API gave 86.94% on `main` (`64d8e16`) and 87.19% on `develop` (`2cbc053`). That is the coverage of the Python backend alone; the frontend and the extension are not counted.
