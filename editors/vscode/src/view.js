"use strict";

const { commandLine, costOf } = require("./commands");
const {
  formatDate,
  formatDay,
  languageOf,
  plural,
  text,
} = require("./messages");

const SHORT_COMMIT = 7;
const MAX_TASKS = 8;
const MAX_PROBLEMS = 6;
const STAGE_ORDER = Object.freeze([
  "brief",
  "team",
  "twins",
  "requirements",
  "design",
]);
const BROWSER_NAMES = Object.freeze({ chrome: "Chrome", firefox: "Firefox" });
const OUTCOMES = Object.freeze([
  Object.freeze({ key: "passed", status: "PASSED", tone: "good" }),
  Object.freeze({ key: "failed", status: "FAILED", tone: "bad" }),
  Object.freeze({ key: "blocked", status: "BLOCKED", tone: "warn" }),
  Object.freeze({ key: "notCovered", status: "NOT_COVERED", tone: "muted" }),
  Object.freeze({ key: "notRun", status: "NOT_RUN", tone: "faint" }),
]);
const VERDICT_TONES = Object.freeze({
  ALIGNED: "good",
  CODE_DRIFT: "bad",
  DESIGN_OUTDATED: "warn",
  REQUIREMENTS_OUTDATED: "warn",
});
const CRITIQUE_TONES = Object.freeze({
  FINE: "good",
  CONCERN: "warn",
  DRIFT: "bad",
});
const STATUS_TONES = Object.freeze({
  PASSED: "good",
  FAILED: "bad",
  BLOCKED: "warn",
});
const AGENT_TONES = Object.freeze({
  CONNECTED: "good",
  INVALID: "warn",
  UNREADABLE: "warn",
});
const NEXT_SENTENCES = Object.freeze({
  NO_FOLDER: "next.noFolder",
  NOT_LINKED: "next.notLinked",
  FOLDER_MISSING: "next.folderMissing",
  FOLDER_BROKEN: "next.folderBroken",
  INIT: "next.init",
  DESIGN: "next.design",
  RECHECK: "next.recheck",
  CODE: "next.code",
  TASKS_FROM_TEST: "next.tasksFromTest",
  ALIGN: "next.align",
  FIRST_TEST: "next.firstTest",
  TEST: "next.test",
});
const ACTION_ICONS = Object.freeze({
  openReport: "external",
  connectAgents: "plug",
});
const KNOWN_AGENTS = Object.freeze(["claude", "custom"]);
const ENTITIES = Object.freeze({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
});
const ICONS = Object.freeze({
  check: '<path d="M3.5 8.5 6.5 11.5 12.5 4.5"/>',
  pending: '<circle cx="8" cy="8" r="4.5"/>',
  terminal:
    '<rect x="1.5" y="2.5" width="13" height="11" rx="1.5"/><path d="M4.5 6 6.5 8 4.5 10M8 10.5h3.5"/>',
  external: '<path d="M9.5 2.5h4v4M13.5 2.5 8 8M12 9.5v4H2.5V4h4"/>',
  plug: '<path d="M5.5 1.5v3M10.5 1.5v3M3.5 4.5h9v2.5a4.5 4.5 0 0 1-9 0zM8 11.5v3"/>',
  warning: '<path d="M8 1.8 14.6 13.6H1.4z"/><path d="M8 6.2v3.6M8 11.7v.3"/>',
});

const STYLE = `
:root {
  --ot-font: var(--vscode-font-family, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  --ot-mono: var(--vscode-editor-font-family, ui-monospace, "Cascadia Code", Consolas, monospace);
  --ot-size: var(--vscode-font-size, 13px);
  --ot-fg: var(--vscode-foreground, #3b3b3b);
  --ot-muted: var(--vscode-descriptionForeground, #616161);
  --ot-bg: var(--vscode-sideBar-background, #f8f8f8);
  --ot-line: var(--vscode-sideBarSectionHeader-border, var(--vscode-widget-border, color-mix(in srgb, var(--ot-fg) 16%, transparent)));
  --ot-card-line: var(--vscode-contrastBorder, color-mix(in srgb, var(--ot-fg) 15%, transparent));
  --ot-card: color-mix(in srgb, var(--ot-fg) 4%, var(--ot-bg));
  --ot-focus: var(--vscode-focusBorder, #005fb8);
  --ot-accent: var(--vscode-button-background, #005fb8);
  --ot-good: var(--vscode-charts-green, #388a34);
  --ot-bad: var(--vscode-charts-red, #e51400);
  --ot-warn: var(--vscode-charts-orange, #d18616);
  --ot-info: var(--vscode-charts-blue, #1a85ff);
}
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  padding: 12px 16px 0;
  background: var(--ot-bg);
  color: var(--ot-fg);
  font-family: var(--ot-font);
  font-size: var(--ot-size);
  font-weight: var(--vscode-font-weight, normal);
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.panel { max-width: 640px; }
h1, h2, h3, p, ul, ol, dl, dd { margin: 0; }
ul, ol { padding: 0; list-style: none; }
code {
  padding: 0 3px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--ot-fg) 9%, transparent);
  color: inherit;
  font-family: var(--ot-mono);
  font-size: 0.92em;
}
.sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
.icon {
  flex: none;
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.muted { color: var(--ot-muted); }
.project { padding: 2px 0 16px; }
.eyebrow {
  color: var(--ot-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
h1 { margin-top: 2px; font-size: 18px; font-weight: 600; line-height: 1.3; }
.meta { margin-top: 4px; color: var(--ot-muted); font-size: 12px; }
.steps { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; }
.step {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 7px 1px 4px;
  border: 1px solid var(--ot-card-line);
  border-radius: 999px;
  color: var(--ot-muted);
  font-size: 12px;
}
.step .icon { width: 14px; height: 14px; }
.step.done {
  border-color: color-mix(in srgb, var(--ot-good) 50%, transparent);
  background: color-mix(in srgb, var(--ot-good) 10%, transparent);
  color: var(--ot-fg);
}
.step.done .icon { color: var(--ot-good); stroke-width: 2; }
.callout {
  margin-top: 12px;
  padding: 8px 10px;
  border-left: 3px solid var(--ot-warn);
  border-radius: 0 4px 4px 0;
  background: color-mix(in srgb, var(--ot-warn) 10%, transparent);
  font-size: 12px;
}
.notices {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 14px;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--ot-warn) 60%, transparent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--ot-warn) 10%, transparent);
  font-size: 12px;
}
.notices .icon { margin-top: 1px; color: var(--ot-warn); }
.notices ul { display: grid; gap: 4px; }
section { padding: 16px 0 18px; border-top: 1px solid var(--ot-line); }
section.next {
  margin-bottom: 18px;
  padding: 12px 12px 12px 13px;
  border: 1px solid var(--ot-card-line);
  border-left: 3px solid var(--ot-accent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--ot-accent) 7%, var(--ot-bg));
}
h2 {
  margin-bottom: 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.next h2 { margin-bottom: 6px; }
h3 { margin: 16px 0 6px; color: var(--ot-muted); font-size: 12px; font-weight: 600; }
.facts { display: grid; gap: 5px; }
.facts > div {
  display: grid;
  grid-template-columns: minmax(96px, 40%) minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
}
.facts dt { color: var(--ot-muted); }
.facts dd { min-width: 0; }
.note { margin-top: 8px; font-size: 12px; }
.spaced { margin-top: 10px; }
.cards { display: grid; gap: 8px; }
.card {
  padding: 8px 10px 9px;
  border: 1px solid var(--ot-card-line);
  border-radius: 4px;
  background: var(--ot-card);
}
.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 4px 8px;
}
.card-text { margin-top: 3px; }
.card-note { margin-top: 5px; color: var(--ot-muted); font-size: 12px; }
.label { font-family: var(--ot-mono); font-size: 12px; font-weight: 600; }
.when { color: var(--ot-muted); font-size: 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
.chip {
  --tone: var(--ot-muted);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  padding: 0 8px 0 7px;
  border: 1px solid color-mix(in srgb, var(--tone) 50%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--tone) 12%, transparent);
  color: var(--ot-fg);
  font-size: 11.5px;
  line-height: 18px;
}
.chip::before {
  content: "";
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--tone);
}
.tone-good { --tone: var(--ot-good); }
.tone-bad { --tone: var(--ot-bad); }
.tone-warn { --tone: var(--ot-warn); }
.tone-info { --tone: var(--ot-info); }
.tone-muted { --tone: color-mix(in srgb, var(--ot-muted) 70%, transparent); }
.tone-faint { --tone: color-mix(in srgb, var(--ot-muted) 30%, transparent); }
.bar { display: block; width: 100%; height: 8px; margin: 12px 0 8px; border-radius: 4px; overflow: hidden; }
.bar rect { fill: var(--tone); }
.bar .gap { fill: var(--ot-bg); }
.legend { display: flex; flex-wrap: wrap; gap: 3px 14px; font-size: 12px; }
.legend li { display: inline-flex; align-items: center; gap: 6px; }
.legend .zero { color: var(--ot-muted); }
.swatch { flex: none; width: 9px; height: 9px; border-radius: 2px; background: var(--tone); }
.opinions { display: grid; gap: 4px; margin-top: 8px; }
.opinions li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 2px 8px;
  font-size: 12px;
}
.twin-name { font-weight: 600; }
.version {
  flex: none;
  padding: 0 7px;
  border-radius: 999px;
  background: var(--vscode-badge-background, #616161);
  color: var(--vscode-badge-foreground, #ffffff);
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
}
.learned { margin-top: 10px; font-size: 12px; font-weight: 600; }
.observations { display: grid; gap: 6px; margin-top: 6px; }
.observations li {
  padding-left: 9px;
  border-left: 2px solid color-mix(in srgb, var(--ot-info) 60%, transparent);
  font-size: 12px;
}
.actions { display: grid; gap: 6px; margin-top: 14px; }
.next .actions { margin-top: 10px; }
.action {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  width: 100%;
  padding: 7px 10px 8px;
  border: 1px solid var(--vscode-button-border, transparent);
  border-radius: 4px;
  background: var(--vscode-button-secondaryBackground, #e5e5e5);
  color: var(--vscode-button-secondaryForeground, #3b3b3b);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.action:hover { background: var(--vscode-button-secondaryHoverBackground, #cccccc); }
.action.primary {
  background: var(--vscode-button-background, #005fb8);
  color: var(--vscode-button-foreground, #ffffff);
}
.action.primary:hover { background: var(--vscode-button-hoverBackground, #0258a8); }
.action:focus-visible { outline: 1px solid var(--ot-focus); outline-offset: 2px; }
.action .icon { margin-top: 2px; }
.action-text { display: grid; gap: 1px; min-width: 0; }
.action-label { font-weight: 600; }
.action-detail { font-size: 11.5px; opacity: 0.88; }
.action-detail code { padding: 0; background: none; font-size: 11.5px; }
.footer { padding: 14px 0 18px; border-top: 1px solid var(--ot-line); color: var(--ot-muted); font-size: 12px; }
.status {
  position: sticky;
  bottom: 0;
  margin: 0 -16px;
  padding: 8px 16px;
  border-top: 1px solid var(--ot-line);
  background: var(--ot-bg);
  font-size: 12px;
}
.status::before {
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 8px;
  border-radius: 50%;
  background: var(--ot-accent);
  vertical-align: 1px;
}
.status:empty { padding: 0; border-top: 0; }
.status:empty::before { display: none; }
`;

const SCRIPT = `(() => {
  const api = typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null;
  const saved = api ? api.getState() : null;
  if (saved && typeof saved.scroll === "number") {
    window.scrollTo(0, saved.scroll);
  }
  let waiting = false;
  window.addEventListener("scroll", () => {
    if (!api || waiting) {
      return;
    }
    waiting = true;
    window.requestAnimationFrame(() => {
      waiting = false;
      api.setState({ scroll: window.scrollY });
    });
  }, { passive: true });
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("button[data-command]") : null;
    if (target && api) {
      api.postMessage({ command: target.getAttribute("data-command") });
    }
  });
  window.addEventListener("message", (event) => {
    const message = event.data;
    const region = document.getElementById("status");
    if (region && message && message.type === "status" && typeof message.text === "string") {
      region.textContent = message.text;
    }
  });
})();`;

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ENTITIES[character],
  );
}

function rich(value) {
  return escapeHtml(value).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function listOf(value) {
  return Array.isArray(value) ? value : [];
}

function objectOf(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function shortCommit(commit) {
  return typeof commit === "string" ? commit.slice(0, SHORT_COMMIT) : "";
}

function asCode(value) {
  return `\`${String(value).replace(/`/g, "'")}\``;
}

function folderName(root) {
  if (typeof root !== "string") {
    return null;
  }
  const parts = root.split(/[\\/]/).filter((part) => part !== "");
  return parts.length > 0 ? parts[parts.length - 1] : root;
}

function contextOf(options) {
  const language = languageOf(options.language);
  const timeZone = options.timeZone;
  return {
    language,
    t: (key, values) => text(language, key, values),
    n: (key, count, values) => plural(language, key, count, values),
    date: (value) => formatDate(language, value, { timeZone }),
    day: (value) => formatDay(language, value, { timeZone }),
  };
}

function icon(name) {
  return `<svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">${ICONS[name]}</svg>`;
}

function chip(label, tone) {
  return `<span class="chip tone-${tone}">${escapeHtml(label)}</span>`;
}

function facts(rows) {
  const items = rows.map(
    ([term, value]) =>
      `<div><dt>${escapeHtml(term)}</dt><dd>${value}</dd></div>`,
  );
  return `<dl class="facts">${items.join("")}</dl>`;
}

function sectionOf(id, title, content) {
  return [
    `<section aria-labelledby="${id}-title">`,
    `<h2 id="${id}-title">${escapeHtml(title)}</h2>`,
    ...content,
    "</section>",
  ].join("\n");
}

function actionButton(id, context, options = {}) {
  const line = commandLine(id, "ut");
  const detail =
    line === null
      ? escapeHtml(context.t(`detail.${id}`))
      : `<code>${escapeHtml(line)}</code> · ${escapeHtml(context.t(`cost.${costOf(id)}`))}`;
  return [
    `<button type="button" class="action${options.primary ? " primary" : ""}" data-command="${escapeHtml(id)}">`,
    icon(ACTION_ICONS[id] ?? "terminal"),
    '<span class="action-text">',
    `<span class="action-label">${escapeHtml(context.t(`action.${id}`))}</span>`,
    `<span class="action-detail">${detail}</span>`,
    "</span>",
    "</button>",
  ].join("");
}

function actions(ids, context) {
  const buttons = ids.filter(Boolean).map((id) => actionButton(id, context));
  return buttons.length === 0
    ? ""
    : `<div class="actions">${buttons.join("")}</div>`;
}

function nextStep(state) {
  const project = objectOf(state);
  if (typeof project.root !== "string" || project.root === "") {
    return { kind: "NO_FOLDER", command: null, count: null };
  }
  if (project.linked !== true) {
    return { kind: "NOT_LINKED", command: null, count: null };
  }
  const folder = objectOf(project.folder);
  if (folder.available !== true) {
    return folder.problem === "MISSING"
      ? { kind: "FOLDER_MISSING", command: "status", count: null }
      : { kind: "FOLDER_BROKEN", command: "publish", count: null };
  }
  const approved = listOf(folder.approved);
  if (!approved.includes("design")) {
    if (approved.includes("requirements")) {
      return { kind: "DESIGN", command: "design", count: null };
    }
    const stage =
      STAGE_ORDER.find((item) => !approved.includes(item)) ?? STAGE_ORDER[0];
    return { kind: "INIT", command: "init", count: null, stage };
  }
  const development = objectOf(project.development);
  const tests = objectOf(project.tests);
  if (development.available !== true || tests.available !== true) {
    return { kind: "FOLDER_BROKEN", command: "publish", count: null };
  }
  if (development.stale > 0) {
    return { kind: "RECHECK", command: "recheck", count: development.stale };
  }
  const open = listOf(objectOf(project.tasks).open).length;
  if (open > 0) {
    return { kind: "CODE", command: "code", count: open };
  }
  const latest = tests.latest ? objectOf(tests.latest) : null;
  const summary = objectOf(latest === null ? null : latest.summary);
  const problems = (summary.failed ?? 0) + (summary.blocked ?? 0);
  if (problems > 0) {
    return {
      kind: "TASKS_FROM_TEST",
      command: "tasksFromTest",
      count: problems,
    };
  }
  if (development.pending > 0) {
    return { kind: "ALIGN", command: "align", count: development.pending };
  }
  if (latest === null) {
    return { kind: "FIRST_TEST", command: "test", count: null };
  }
  return { kind: "TEST", command: "test", count: null };
}

function nextSentence(step, context) {
  const key = NEXT_SENTENCES[step.kind] ?? NEXT_SENTENCES.TEST;
  if (step.kind === "INIT") {
    return context.t(key, { stage: context.t(`stage.${step.stage}`) });
  }
  return step.count === null ? context.t(key) : context.n(key, step.count);
}

function nextSection(state, context) {
  const step = nextStep(state);
  const button =
    step.command === null
      ? ""
      : `<div class="actions">${actionButton(step.command, context, { primary: true })}</div>`;
  return [
    `<section class="next" aria-labelledby="next-title" data-step="${escapeHtml(step.kind)}">`,
    `<h2 id="next-title">${escapeHtml(context.t("next.title"))}</h2>`,
    `<p>${rich(nextSentence(step, context))}</p>`,
    button,
    "</section>",
  ].join("\n");
}

function unlinkedHeader(state, context) {
  const name = folderName(objectOf(state).root);
  const eyebrow =
    name === null
      ? context.t("panel.title")
      : context.t("panel.unlinkedEyebrow");
  return [
    '<header class="project">',
    `<p class="eyebrow">${escapeHtml(eyebrow)}</p>`,
    `<h1>${escapeHtml(name ?? context.t("panel.noFolder"))}</h1>`,
    "</header>",
  ].join("\n");
}

function stepsOf(folder, context) {
  const items = STAGE_ORDER.map((stage) => {
    const done = folder.approved.includes(stage);
    return [
      `<li class="step${done ? " done" : ""}">`,
      icon(done ? "check" : "pending"),
      `<span>${escapeHtml(context.t(`stage.${stage}`))}</span>`,
      `<span class="sr">, ${escapeHtml(context.t(done ? "stage.approved" : "stage.pending"))}</span>`,
      "</li>",
    ].join("");
  });
  return `<ol class="steps" aria-label="${escapeHtml(context.t("header.steps"))}">${items.join("")}</ol>`;
}

function headerOf(state, context) {
  const folder = state.folder;
  const project = objectOf(state.project);
  const name = folder.name ?? project.name ?? folderName(state.root);
  const lines = [
    '<header class="project">',
    `<p class="eyebrow">${escapeHtml(context.t("panel.eyebrow"))}</p>`,
    `<h1>${escapeHtml(name)}</h1>`,
  ];
  if (folder.available) {
    const published = context.date(folder.publishedAt);
    if (folder.version !== null) {
      const meta =
        published === null
          ? context.t("header.folderVersion", { version: folder.version })
          : context.t("header.folderPublished", {
              version: folder.version,
              date: published,
            });
      lines.push(`<p class="meta">${escapeHtml(meta)}</p>`);
    }
    lines.push(stepsOf(folder, context));
    if (!folder.approved.includes("design")) {
      lines.push(
        `<p class="callout">${escapeHtml(context.t("header.partial"))}</p>`,
      );
    }
  } else {
    const key =
      folder.problem === "MISSING"
        ? "header.folderMissing"
        : "header.folderBroken";
    lines.push(
      `<p class="meta">${escapeHtml(context.t(key, { folder: folder.path }))}</p>`,
    );
  }
  lines.push("</header>");
  return lines.join("\n");
}

function noticesOf(state, context) {
  const notices = listOf(state.notices);
  if (notices.length === 0) {
    return "";
  }
  const items = notices.map(
    (notice) =>
      `<li>${rich(context.t(`notice.${notice.problem}`, { file: asCode(notice.file) }))}</li>`,
  );
  return [
    `<aside class="notices" aria-label="${escapeHtml(context.t("notice.label"))}">`,
    icon("warning"),
    `<ul>${items.join("")}</ul>`,
    "</aside>",
  ].join("");
}

function unavailable(context) {
  return `<p>${rich(context.t("part.unavailable"))}</p>`;
}

function verdictChip(verdict, context) {
  if (verdict === null || verdict === undefined) {
    return chip(context.t("verdict.NONE"), "muted");
  }
  return chip(
    context.t(`verdict.${verdict}`),
    VERDICT_TONES[verdict] ?? "muted",
  );
}

function critiqueChip(verdict, context) {
  if (verdict === null || verdict === undefined) {
    return "";
  }
  return chip(
    context.t(`critique.${verdict}`),
    CRITIQUE_TONES[verdict] ?? "muted",
  );
}

function latestCommitCard(change, context) {
  const chips = [verdictChip(change.verdict, context)];
  if (change.stale) {
    chips.push(chip(context.t("chip.stale"), "warn"));
  }
  if (change.decision !== null) {
    chips.push(chip(context.t(`decision.${change.decision}`), "info"));
  }
  const when = context.date(change.committedAt);
  return [
    '<div class="card">',
    '<p class="card-head">',
    `<code>${escapeHtml(shortCommit(change.commit))}</code>`,
    when === null ? "" : `<span class="when">${escapeHtml(when)}</span>`,
    "</p>",
    change.subject === null
      ? ""
      : `<p class="card-text">${escapeHtml(change.subject)}</p>`,
    `<p class="chips">${chips.join("")}</p>`,
    "</div>",
  ].join("");
}

function developmentSection(state, context) {
  const development = state.development;
  const title = context.t("development.title");
  if (!development.available) {
    return sectionOf("development", title, [unavailable(context)]);
  }
  const aligned =
    development.aligned === null
      ? escapeHtml(context.t("development.noAligned"))
      : rich(
          [
            asCode(shortCommit(development.aligned.commit)),
            context.date(development.aligned.decidedAt),
          ]
            .filter(Boolean)
            .join(" · "),
        );
  const rows = [
    [context.t("development.aligned"), aligned],
    [context.t("development.pending"), escapeHtml(String(development.pending))],
  ];
  if (development.staleKnown) {
    const commits = development.staleCommits.map((commit) =>
      asCode(shortCommit(commit)),
    );
    const value =
      development.stale === 0
        ? context.t("development.none")
        : commits.length === 0
          ? String(development.stale)
          : `${development.stale} · ${commits.join(", ")}`;
    rows.push([context.t("development.stale"), rich(value)]);
  }
  const reference = state.reference;
  if (reference.requirements !== null && reference.design !== null) {
    const value = context.t("development.referenceValue", {
      requirements: reference.requirements,
      design: reference.design,
    });
    rows.push([
      context.t("development.reference"),
      escapeHtml(
        reference.alternative === null
          ? value
          : `${value} (${reference.alternative})`,
      ),
    ]);
  }
  const content = [facts(rows)];
  if (development.latest === null) {
    content.push(
      `<p class="note">${rich(context.t("development.noCommits"))}</p>`,
    );
  } else {
    content.push(`<h3>${escapeHtml(context.t("development.latest"))}</h3>`);
    content.push(latestCommitCard(development.latest, context));
  }
  content.push(
    actions(["align", development.stale > 0 ? "recheck" : null], context),
  );
  return sectionOf("development", title, content);
}

function originText(task, context) {
  const origin = objectOf(task.origin);
  const twin =
    typeof origin.twinName === "string"
      ? origin.twinName.replace(/`/g, "'")
      : null;
  if (origin.kind === "OWNER") {
    return context.t("origin.owner");
  }
  if (origin.kind === "TEST_RUN") {
    if (typeof twin !== "string") {
      return context.t("origin.testRun");
    }
    const criteria = listOf(task.criteria);
    return criteria.length === 0
      ? context.t("origin.twinTest", { twin })
      : context.n("origin.twinTestCriteria", criteria.length, {
          twin,
          criteria: criteria.map(asCode).join(", "),
        });
  }
  if (origin.kind === "CODE_CHANGE" && typeof origin.commit === "string") {
    const commit = asCode(shortCommit(origin.commit));
    return typeof twin === "string"
      ? context.t("origin.twinCommit", { twin, commit })
      : context.t("origin.verdictCommit", { commit });
  }
  return null;
}

function taskCard(task, context) {
  const origin = originText(task, context);
  return [
    '<li class="card">',
    `<p class="card-head"><span class="label">${escapeHtml(task.code ?? "")}</span></p>`,
    task.text === null
      ? ""
      : `<p class="card-text">${escapeHtml(task.text)}</p>`,
    origin === null ? "" : `<p class="card-note">${rich(origin)}</p>`,
    "</li>",
  ].join("");
}

function codeRun(code, context) {
  const rows = [];
  const when = context.date(code.finishedAt) ?? context.date(code.startedAt);
  if (when !== null) {
    rows.push([context.t("code.when"), escapeHtml(when)]);
  }
  if (code.agent !== null) {
    const known = KNOWN_AGENTS.includes(code.agent);
    const agent = known ? context.t(`code.agent.${code.agent}`) : code.agent;
    rows.push([context.t("code.agent"), escapeHtml(agent)]);
  }
  if (code.exitStatus !== null) {
    const outcome =
      code.exitStatus === 0
        ? context.t("code.exitOk")
        : context.t("code.exitStatus", { status: code.exitStatus });
    rows.push([context.t("code.outcome"), escapeHtml(outcome)]);
  }
  if (code.changedFiles !== null) {
    rows.push([context.t("code.files"), escapeHtml(String(code.changedFiles))]);
  }
  if (rows.length === 0) {
    return "";
  }
  return `<h3>${escapeHtml(context.t("code.title"))}</h3>${facts(rows)}`;
}

function tasksSection(state, context) {
  const tasks = state.tasks;
  const title = context.t("tasks.title");
  if (!tasks.available) {
    return sectionOf("tasks", title, [unavailable(context)]);
  }
  const counts = [
    context.n("tasks.open", tasks.open.length),
    context.n("tasks.done", tasks.done),
  ];
  if (tasks.dropped > 0) {
    counts.push(context.n("tasks.dropped", tasks.dropped));
  }
  const content = [`<p class="muted">${escapeHtml(counts.join(" · "))}</p>`];
  if (tasks.open.length === 0) {
    content.push(`<p class="note">${escapeHtml(context.t("tasks.none"))}</p>`);
  } else {
    const shown = tasks.open
      .slice(0, MAX_TASKS)
      .map((task) => taskCard(task, context));
    content.push(`<ul class="cards spaced">${shown.join("")}</ul>`);
    if (tasks.open.length > MAX_TASKS) {
      const more = context.n("tasks.more", tasks.open.length - MAX_TASKS);
      content.push(`<p class="note">${rich(more)}</p>`);
    }
  }
  if (state.code !== null && state.code !== undefined) {
    content.push(codeRun(state.code, context));
  }
  content.push(actions(["code", "tasks"], context));
  return sectionOf("tasks", title, content);
}

function percent(value) {
  return Number(value.toFixed(3));
}

function outcomes(summary, context) {
  const total = OUTCOMES.reduce(
    (sum, outcome) => sum + (summary[outcome.key] ?? 0),
    0,
  );
  const legend = OUTCOMES.map((outcome) => {
    const count = summary[outcome.key] ?? 0;
    return [
      `<li class="tone-${outcome.tone}${count === 0 ? " zero" : ""}">`,
      '<span class="swatch" aria-hidden="true"></span>',
      escapeHtml(context.n(`tests.${outcome.status}`, count)),
      "</li>",
    ].join("");
  });
  let bar = "";
  if (total > 0) {
    const segments = [];
    const gaps = [];
    let offset = 0;
    for (const outcome of OUTCOMES) {
      const count = summary[outcome.key] ?? 0;
      if (count === 0) {
        continue;
      }
      const start = percent((offset / total) * 100);
      const width = percent((count / total) * 100);
      segments.push(
        `<rect class="tone-${outcome.tone}" x="${start}%" y="0" width="${width}%" height="8"><title>${escapeHtml(context.n(`tests.${outcome.status}`, count))}</title></rect>`,
      );
      if (offset > 0) {
        gaps.push(
          `<rect class="gap" x="${start}%" y="0" width="2" height="8" transform="translate(-1 0)"/>`,
        );
      }
      offset += count;
    }
    bar = `<svg class="bar" width="100%" height="8" aria-hidden="true" focusable="false">${segments.join("")}${gaps.join("")}</svg>`;
  }
  return `${bar}<ul class="legend" aria-label="${escapeHtml(context.t("tests.counts"))}">${legend.join("")}</ul>`;
}

function browsersText(browsers) {
  return browsers
    .map((browser) => {
      const name = BROWSER_NAMES[browser.name] ?? browser.name;
      const major =
        typeof browser.version === "string"
          ? browser.version.split(".")[0]
          : "";
      return major === "" ? name : `${name} ${major}`;
    })
    .join(" · ");
}

function problemCard(problem, context) {
  const statement = problem.statement ?? context.t("tests.statementMissing");
  return [
    '<li class="card">',
    '<p class="card-head">',
    `<span class="label">${escapeHtml(problem.code ?? "")}</span>`,
    chip(
      context.t(`status.${problem.status}`),
      STATUS_TONES[problem.status] ?? "muted",
    ),
    "</p>",
    `<p class="card-text${problem.statement === null ? " muted" : ""}">${escapeHtml(statement)}</p>`,
    "</li>",
  ].join("");
}

function reviewOf(run, context) {
  if (!run.reviewed) {
    return `<p class="note muted">${escapeHtml(context.t("tests.notReviewed"))}</p>`;
  }
  const when = context.date(run.reviewedAt);
  const heading =
    when === null
      ? context.t("tests.reviewedUndated")
      : context.t("tests.reviewed", { date: when });
  const opinions = run.critiques
    .filter((critique) => critique.twinName !== null)
    .map(
      (critique) =>
        `<li><span>${escapeHtml(critique.twinName)}</span>${critiqueChip(critique.verdict, context)}</li>`,
    );
  return [
    `<h3>${escapeHtml(heading)}</h3>`,
    opinions.length === 0
      ? ""
      : `<ul class="opinions">${opinions.join("")}</ul>`,
  ].join("");
}

function testsSection(state, context) {
  const tests = state.tests;
  const title = context.t("tests.title");
  if (!tests.available) {
    return sectionOf("tests", title, [unavailable(context)]);
  }
  const run = tests.latest;
  if (run === null) {
    return sectionOf("tests", title, [
      `<p>${rich(context.t("tests.none"))}</p>`,
      actions(["test"], context),
    ]);
  }
  const rows = [];
  const when = context.date(run.finishedAt) ?? context.date(run.startedAt);
  if (when !== null) {
    rows.push([context.t("tests.latest"), escapeHtml(when)]);
  }
  if (run.browsers.length > 0) {
    rows.push([
      context.t("tests.browsers"),
      escapeHtml(browsersText(run.browsers)),
    ]);
  }
  const content = [facts(rows)];
  if (run.source === "LOCAL") {
    content.push(
      `<p class="note muted">${escapeHtml(context.t("tests.local"))}</p>`,
    );
  }
  if (run.stale) {
    content.push(
      `<p class="callout">${escapeHtml(context.t("tests.stale"))}</p>`,
    );
  }
  content.push(outcomes(run.summary, context));
  if (run.problems.length > 0) {
    content.push(`<h3>${escapeHtml(context.t("tests.problems"))}</h3>`);
    const shown = run.problems
      .slice(0, MAX_PROBLEMS)
      .map((problem) => problemCard(problem, context));
    content.push(`<ul class="cards">${shown.join("")}</ul>`);
    if (run.problems.length > MAX_PROBLEMS) {
      const more = context.n(
        "tests.moreProblems",
        run.problems.length - MAX_PROBLEMS,
      );
      content.push(`<p class="note">${escapeHtml(more)}</p>`);
    }
  }
  content.push(reviewOf(run, context));
  content.push(actions(["test", tests.report ? "openReport" : null], context));
  return sectionOf("tests", title, content);
}

function opinionLine(label, verdict, context) {
  return `<li><span>${rich(label)}</span>${critiqueChip(verdict, context)}</li>`;
}

function twinCard(twin, context) {
  const opinions = [];
  if (twin.commit === null) {
    opinions.push(
      `<li class="muted">${escapeHtml(context.t("twins.noCommit"))}</li>`,
    );
  } else {
    const label = context.t("twins.onCommit", {
      commit: asCode(shortCommit(twin.commit.commit)),
    });
    opinions.push(opinionLine(label, twin.commit.verdict, context));
  }
  if (twin.test === null) {
    opinions.push(
      `<li class="muted">${escapeHtml(context.t("twins.noTest"))}</li>`,
    );
  } else {
    const day =
      context.day(twin.test.finishedAt) ??
      context.day(twin.test.reviewedAt) ??
      "";
    opinions.push(
      opinionLine(
        context.t("twins.onTest", { date: day }),
        twin.test.verdict,
        context,
      ),
    );
  }
  const learned =
    twin.learned > 0
      ? context.n("twins.learned", twin.learned)
      : context.t("twins.learnedNone");
  const observations = twin.observations.map((observation) => {
    const source =
      observation.source === null
        ? ""
        : ` <span class="muted">· ${escapeHtml(context.t(`source.${observation.source}`))}</span>`;
    return [
      "<li>",
      observation.code === null
        ? ""
        : `<span class="label">${escapeHtml(observation.code)}</span> `,
      escapeHtml(observation.statement ?? ""),
      source,
      "</li>",
    ].join("");
  });
  const version =
    twin.label === null
      ? ""
      : `<span class="version">${escapeHtml(context.t("twins.version", { label: twin.label }))}</span>`;
  return [
    '<li class="card">',
    `<p class="card-head"><span class="twin-name">${escapeHtml(twin.name ?? "")}</span>${version}</p>`,
    `<ul class="opinions">${opinions.join("")}</ul>`,
    `<p class="learned">${escapeHtml(learned)}</p>`,
    observations.length === 0
      ? ""
      : `<ol class="observations">${observations.join("")}</ol>`,
    listOf(twin.evidence).length === 0
      ? ""
      : `<details><summary>${escapeHtml(context.t("twins.evidence"))}</summary><p>${escapeHtml(context.t("twins.evidenceLimit"))}</p>${listOf(
          twin.evidence,
        )
          .map(
            (item) =>
              `<p>${escapeHtml(item.code ?? "")} v${escapeHtml(item.version ?? "")} · ${escapeHtml(item.field ?? "")} · ${escapeHtml(item.effect ?? "")} · ${escapeHtml(item.status ?? "")} · L${escapeHtml(item.first ?? "")}–L${escapeHtml(item.last ?? "")}</p><blockquote>${escapeHtml(item.quote ?? "")}</blockquote><p>${escapeHtml(item.limitations ?? "")}</p>`,
          )
          .join("")}</details>`,
    "</li>",
  ].join("");
}

function twinsSection(state, context) {
  const twins = state.twins;
  const title = context.t("twins.title");
  const folder = state.folder;
  if (!twins.available) {
    const approved = folder.approved.includes("twins");
    const message = approved
      ? unavailable(context)
      : `<p>${rich(context.t("twins.notYet"))}</p>`;
    return sectionOf("twins", title, [message]);
  }
  const content = [];
  if (twins.items.length === 0) {
    content.push(`<p>${escapeHtml(context.t("twins.none"))}</p>`);
  } else {
    content.push(
      `<ul class="cards">${twins.items.map((twin) => twinCard(twin, context)).join("")}</ul>`,
    );
  }
  if (folder.approved.includes("design")) {
    content.push(actions(["twinsUpdate"], context));
  }
  return sectionOf("twins", title, content);
}

function agentsSection(state, context) {
  const status = objectOf(state.agents).status ?? "MISSING";
  return sectionOf("agents", context.t("agents.title"), [
    `<p>${rich(context.t("agents.intro"))}</p>`,
    `<p class="chips">${chip(context.t(`agents.${status}`), AGENT_TONES[status] ?? "muted")}</p>`,
    actions(["connectAgents"], context),
  ]);
}

function footerOf(state, context) {
  const step = nextStep(state);
  return [
    '<footer class="footer">',
    `<p>${rich(context.t("footer.note"))}</p>`,
    step.command === "status" ? "" : actions(["status"], context),
    "</footer>",
  ].join("\n");
}

function linkedBody(state, context) {
  const parts = [
    headerOf(state, context),
    noticesOf(state, context),
    nextSection(state, context),
  ];
  const folder = state.folder;
  if (folder.available) {
    if (folder.approved.includes("design")) {
      parts.push(developmentSection(state, context));
      parts.push(tasksSection(state, context));
      parts.push(testsSection(state, context));
    } else {
      parts.push(
        sectionOf("development", context.t("development.title"), [
          `<p>${escapeHtml(context.t("development.notYet"))}</p>`,
        ]),
      );
    }
    parts.push(twinsSection(state, context));
  }
  parts.push(agentsSection(state, context));
  parts.push(footerOf(state, context));
  return parts.filter((part) => part !== "").join("\n");
}

function bodyOf(state, context) {
  try {
    if (state.linked === true && typeof state.root === "string") {
      return linkedBody(state, context);
    }
    return [
      unlinkedHeader(state, context),
      noticesOf(state, context),
      nextSection(state, context),
    ]
      .filter((part) => part !== "")
      .join("\n");
  } catch {
    return [
      '<header class="project">',
      `<h1>${escapeHtml(context.t("panel.title"))}</h1>`,
      "</header>",
      `<p>${rich(context.t("panel.error"))}</p>`,
    ].join("\n");
  }
}

function renderPanel(state, options = {}) {
  const settings = objectOf(options);
  const context = contextOf(settings);
  const nonce = escapeHtml(settings.nonce ?? "");
  const status = typeof settings.status === "string" ? settings.status : "";
  return [
    "<!DOCTYPE html>",
    `<html lang="${context.language}">`,
    "<head>",
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">`,
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<title>${escapeHtml(context.t("panel.title"))}</title>`,
    `<style nonce="${nonce}">${STYLE}</style>`,
    "</head>",
    "<body>",
    '<main class="panel">',
    bodyOf(objectOf(state), context),
    "</main>",
    `<p id="status" class="status" role="status" aria-live="polite">${escapeHtml(status)}</p>`,
    `<script nonce="${nonce}">${SCRIPT}</script>`,
    "</body>",
    "</html>",
    "",
  ].join("\n");
}

module.exports = {
  escapeHtml,
  nextStep,
  renderPanel,
};
