# Executable Web validation fixture sources

These are repository-owned application sources for the eight supported language
configurations. Their presence and source checks do not grant Level D. A later
governed campaign must execute them with approved runner identities, record the
actual evidence and validate each required configuration.

`matrix.json` identifies each immutable base source directory, its deterministic
one-file defect, the exact original repair content and the expected failure
phase. Every negative control must produce `LEVEL_D_NEGATIVE_CONTROL` in that
phase's captured output. A generic setup or runtime error does not qualify.

- Static: a browser-operated counter; its defect logs the marker and increments
  by two. The browser plan asserts one after a click and two after Enter.
- Vue JavaScript/TypeScript: a mounted Vue counter with actual Vitest assertions
  for the increment function and the same pointer/keyboard browser plan.
- Express JavaScript/TypeScript: real HTTP tests start Express on a loopback
  ephemeral port and check readiness, increment results and invalid inputs.
  Browser evidence is not applicable to these API-only fixtures.
- PHP: PHPUnit verifies the increment function and rendered public HTML.
- Vue + Express JavaScript/TypeScript: the UI calls the backend through Vite's
  same-origin `/api` preview proxy. Backend tests check actual HTTP responses;
  frontend tests reject malformed counter response values. Browser assertions
  therefore exercise the running frontend and backend together.

Each browser-backed application also declares one accessible local details
route. The PHP pages contain no interactive controls and need no interaction
plan. No fixture reads the frozen C94 calculator source or its evidence.

The npm manifests pin Vue 3.5.0, Vite 6.0.0, Vitest 3.0.0, plugin-vue 5.2.4,
Express 5.1.0 and TypeScript 5.8.3 where applicable. Full npm lockfiles were
generated using the verified Node 26.7.0 runner. Versions and integrity data
come from the [official npm registry](https://registry.npmjs.org/).

The Composer lock pins PHPUnit 12.5.35 and its resolved dependencies, generated
with Composer 2.10.2 on PHP 8.4.24 using
[Packagist metadata](https://repo.packagist.org/p2/phpunit/phpunit.json).
Composer platform and advisory checks remain enabled. Installation requires the
offline-pinned unzip package included in the updated PHP runner recipe.

Application dependency installation needs the explicitly provisioned restricted
network. npm tarballs use `registry.npmjs.org`; Composer ZIP archives use
`api.github.com`, with redirects to `codeload.github.com`. The runner recipe's
dependency change requires a fresh owner-committed bootstrap before a governed
campaign. Development builds and local source tests are not that campaign.
