"use strict";

const { validSelector } = require("./why");

const ENTITIES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
const STATES = [
  "EVIDENCED",
  "INFERRED",
  "HYPOTHESIZED",
  "CONTESTED",
  "UNKNOWN",
];
const ORIGINS = {
  MODEL: "why.model",
  OWNER: "why.owner",
  OWNER_INPUT: "workflow.owner",
  SYSTEM: "why.system",
  UNKNOWN: "why.unknownOrigin",
};
const STAGE_TITLES = {
  AGENT_TEAM: "stage.team",
  PROJECT_BRIEF: "why.stage.brief",
  USER_MODELING: "why.stage.twins",
  REQUIREMENTS_SPECIFICATION: "stage.requirements",
  DESIGN_PACKAGE: "why.stage.design",
};
const GAPS = [
  "MISSING_NEED",
  "MISSING_SCENARIO",
  "MISSING_TWIN",
  "MISSING_CLAIM",
  "MISSING_SOURCE",
  "MISSING_SOURCE_VERSION",
  "MISSING_RATIONALE",
  "SOURCE_RETIRED",
  "SOURCE_TEXT_UNAVAILABLE",
  "OMITTED_SECTION",
  "CONTEXT_OUTDATED",
  "DECLARED_MISSING",
];

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ENTITIES[character],
  );
}

function objectOf(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function listOf(value) {
  return Array.isArray(value) ? value : [];
}

function titleOf(node, context) {
  if (node.kind === "VALIDATION_OUTCOME" && ["CONFIRMED", "REFUTED", "UNCERTAIN"].includes(node.title)) {
    return context.t(`validation.state.${node.title}`);
  }
  return node.title === node.kind && Object.hasOwn(STAGE_TITLES, node.kind)
    ? context.t(STAGE_TITLES[node.kind])
    : (node.title ?? node.code);
}

function stateOf(node, context) {
  if (node.kind === "VALIDATION_HYPOTHESIS") {
    return context.t("validation.operationalHypothesis");
  }
  if (node.kind === "VALIDATION_OUTCOME") {
    return context.t(objectOf(node.declared_context).effective_status === "RETIRED" ? "validation.retired" : "validation.outcomes");
  }
  return context.t(`why.${STATES.includes(node.display_status) ? node.display_status : "UNKNOWN"}`);
}

function referenceOf(reference, context) {
  const found = objectOf(reference);
  return `<p class="why-reference"><code>${escapeHtml(found.artifact_id ?? found.generation_id ?? "—")}</code>${found.version_number === undefined || found.version_number === null ? "" : ` · v${escapeHtml(found.version_number)}`}<br><code>${escapeHtml(found.content_hash ?? "—")}</code>${found.request_content_hash ? `<br>${escapeHtml(context.t("why.requestHash"))}: <code>${escapeHtml(found.request_content_hash)}</code>` : ""}</p>`;
}

function mockupOf(value, context) {
  const mockup = objectOf(value);
  return `<p>${escapeHtml(context.t("why.mockup"))}: <code>${escapeHtml(mockup.prototype_id)}</code><br>${escapeHtml(context.t("why.alternative"))}: <code>${escapeHtml(mockup.alternative_id)}</code><br>${escapeHtml(context.t("why.screen"))}: <code>${escapeHtml(mockup.screen_code)}</code><br>${escapeHtml(context.t(mockup.source === "LATEST" ? "why.LATEST" : "why.APPLIED"))}</p>${Object.entries(
    objectOf(mockup.document_hashes),
  )
    .map(
      ([name, hash]) =>
        `<p>${escapeHtml(name)}: <code>${escapeHtml(hash)}</code></p>`,
    )
    .join("")}`;
}

function button(node, context) {
  return validSelector(node.key)
    ? `<button type="button" class="action" data-command="why" data-code="${escapeHtml(node.key)}">${escapeHtml(context.t("why.title"))} · ${escapeHtml(titleOf(node, context))}</button>`
    : "";
}

function citationOf(item, context) {
  const envelope = objectOf(item);
  const citation = objectOf(envelope.citation ?? item);
  const source = objectOf(envelope.source);
  const retired = envelope.status === "RETIRED" || source.status === "RETIRED";
  return [
    '<div class="why-citation">',
    `<p>${escapeHtml(source.title ?? source.code ?? citation.source_id)} · v${escapeHtml(citation.source_version ?? "—")}${envelope.session_kind ? ` · ${escapeHtml(context.t(`validation.session.${envelope.session_kind}`))}` : ` · ${escapeHtml(envelope.field)} · ${escapeHtml(envelope.effect)}`} · ${escapeHtml(retired ? context.t("why.retired") : envelope.status)}</p>`,
    `<p><code>${escapeHtml(citation.content_hash ?? "—")}</code> · ${escapeHtml(citation.start ?? "—")}:${escapeHtml(citation.end ?? "—")} · L${escapeHtml(citation.start_line ?? "—")}–L${escapeHtml(citation.end_line ?? "—")}</p>`,
    `<blockquote>${escapeHtml(citation.quote)}</blockquote>`,
    source.limitations ? `<p>${escapeHtml(source.limitations)}</p>` : "",
    envelope.applicable === false
      ? `<p>${escapeHtml(context.t("why.missing"))}</p>`
      : "",
    "</div>",
  ].join("");
}

function nodeOf(value, context, navigate = true) {
  const node = objectOf(value);
  const rationale = objectOf(node.rationale);
  const declared = objectOf(node.declared_context);
  return [
    '<li class="card">',
    `<p class="card-head"><strong>${escapeHtml(titleOf(node, context))}</strong></p>`,
    `<p>${escapeHtml(stateOf(node, context))} · ${escapeHtml(context.t(node.current === true ? "why.current" : "why.historical"))} · <code>${escapeHtml(node.code)}</code></p>`,
    declared.hypothesis ? `<p>${escapeHtml(context.t("validation.observe"))}</p><ul>${listOf(objectOf(declared.hypothesis).observe).map((item) => `<li class="why-verbatim">${escapeHtml(item)}</li>`).join("")}</ul><p>${escapeHtml(context.t("why.limits"))}</p><p class="why-verbatim">${escapeHtml(objectOf(declared.hypothesis).limitations)}</p>` : "",
    declared.outcome ? `<p>${escapeHtml(context.t(`validation.session.${objectOf(declared.outcome).session_kind}`))} · <code>${escapeHtml(objectOf(declared.outcome).session_ref)}</code></p>${objectOf(declared.outcome).coverage === "PARTIAL" ? `<p>${escapeHtml(context.t("validation.partial"))}</p>` : ""}<p class="why-verbatim">${escapeHtml(objectOf(declared.outcome).limitations)}</p>` : "",
    declared.observation_value
      ? observationOf(declared.observation_value, context)
      : "",
    `<details><summary>${escapeHtml(context.t("why.references"))}</summary>${referenceOf(node.reference, context)}${declared.base_reference ? `<p>${escapeHtml(context.t("why.baseReference"))}</p>${referenceOf(declared.base_reference, context)}` : ""}${declared.audit_reference ? `<p>${escapeHtml(context.t("why.auditReference"))}</p>${referenceOf(declared.audit_reference, context)}` : ""}${declared.evaluation_reference ? referenceOf(declared.evaluation_reference, context) : ""}${declared.mockup ? mockupOf(declared.mockup, context) : ""}</details>`,
    typeof rationale.text === "string" && rationale.text.length > 0
      ? `<p><strong>${escapeHtml(context.t(ORIGINS[rationale.origin] ?? "why.unknownOrigin"))}</strong></p><p class="why-verbatim">${escapeHtml(rationale.text)}</p>${referenceOf({ version_number: rationale.version_number, content_hash: rationale.content_hash, artifact_id: objectOf(node.reference).artifact_id }, context)}`
      : `<p>${escapeHtml(context.t("why.noRationale"))}</p>`,
    listOf(node.citations)
      .map((item) => citationOf(item, context))
      .join(""),
    node.kind === "SYNTHETIC_FINDING"
      ? `<p>${escapeHtml(context.t("why.synthetic"))}</p><p>${escapeHtml(context.t("why.modelRef"))}: <code>${escapeHtml(declared.model_config_ref ?? "—")}</code><br>${escapeHtml(context.t("why.promptRef"))}: <code>${escapeHtml(declared.prompt_version_ref ?? "—")}</code></p>`
      : "",
    node.validation_required === true
      ? `<p>${escapeHtml(context.t("why.validation"))}</p>`
      : "",
    navigate ? button(node, context) : "",
    "</li>",
  ].join("");
}

function nodesOf(nodes, context) {
  return nodes.length === 0
    ? `<p>${escapeHtml(context.t("why.noItems"))}</p>`
    : `<ul class="cards">${nodes.map((node) => nodeOf(node, context)).join("")}</ul>`;
}

function observationOf(value, context) {
  const observation = objectOf(value);
  if (observation.kind === "TEXT" && typeof observation.text === "string") {
    return `<p><strong>${escapeHtml(context.t("why.observation"))}</strong></p><p class="why-verbatim">${escapeHtml(observation.text)}</p>`;
  }
  if (observation.kind === "ITEMS") {
    return `<p><strong>${escapeHtml(context.t("why.observation"))}</strong></p><ul>${listOf(
      observation.items,
    )
      .filter((item) => typeof item === "string")
      .map((item) => `<li class="why-verbatim">${escapeHtml(item)}</li>`)
      .join("")}</ul>`;
  }
  return `<p>${escapeHtml(context.t(observation.kind === "ABSTAINED" ? "why.abstained" : "why.UNKNOWN"))}${observation.kind === "ABSTAINED" && typeof observation.reason === "string" ? `: ${escapeHtml(observation.reason)}` : ""}</p>`;
}

function gapOf(value, context) {
  const gap = objectOf(value);
  const label = GAPS.includes(gap.code) ? `why.gap.${gap.code}` : "why.missing";
  return `<li>${escapeHtml(context.t(label))} · <code>${escapeHtml(gap.code)}</code>${gap.related_code ? ` · ${escapeHtml(gap.related_code)}` : ""}${gap.stage ? ` · ${escapeHtml(gap.stage)}` : ""}<br><code>${escapeHtml(gap.node_key)}</code></li>`;
}

function gapsOf(values, summary, context) {
  const gaps = listOf(values);
  if (gaps.length === 0) {
    return "";
  }
  const counts = new Map();
  for (const value of gaps) {
    const code = objectOf(value).code;
    counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  const rows = [...counts.entries()]
    .sort(([left], [right]) =>
      String(left) < String(right) ? -1 : String(left) > String(right) ? 1 : 0,
    )
    .map(([code, count]) => {
      const label = GAPS.includes(code) ? `why.gap.${code}` : "why.missing";
      return `<li>${escapeHtml(context.t(label))} · <code>${escapeHtml(code)}</code> (${count})</li>`;
    });
  return `<h3>${escapeHtml(context.t(listOf(summary.stop_reasons).length > 0 ? "why.gaps" : "why.limits"))}</h3><ul class="why-gaps-preview">${rows.join("")}</ul><details id="why-gaps-details"><summary>${escapeHtml(context.t("why.details"))} (${gaps.length})</summary><ul>${gaps.map((gap) => gapOf(gap, context)).join("")}</ul></details>`;
}

function validationOf(values, context) {
  const nodes = listOf(values);
  const heading = `<h3>${escapeHtml(context.t("why.validation"))} (${nodes.length})</h3>`;
  if (nodes.length === 0) {
    return `${heading}<p>${escapeHtml(context.t("why.noValidation"))}</p>`;
  }
  const preview = nodes.slice(0, 3).map((value) => {
    const node = objectOf(value);
    const status = STATES.includes(node.display_status)
      ? node.display_status
      : "UNKNOWN";
    return `<li>${escapeHtml(titleOf(node, context))} · ${escapeHtml(context.t(`why.${status}`))}</li>`;
  });
  return `${heading}<ul class="why-validation-preview">${preview.join("")}</ul>${nodes.length > 3 ? `<p>3 / ${nodes.length}</p>` : ""}<details id="why-validation-details"><summary>${escapeHtml(context.t("why.details"))} (${nodes.length})</summary>${nodesOf(nodes, context)}</details>`;
}

function contextOf(answer, context) {
  const declared = objectOf(answer.declared_context);
  const views = listOf(declared.perspectives);
  if (views.length === 0) {
    return "";
  }
  return `<h3>${escapeHtml(context.t("why.context"))}</h3><ul>${views
    .map((value) => {
      const item = objectOf(value);
      return `<li>${escapeHtml(item.title ?? item.name ?? item.label ?? item.key ?? value)}${item.team_reference ? referenceOf(item.team_reference, context) : ""}</li>`;
    })
    .join(
      "",
    )}</ul>${declared.team_reference ? referenceOf(declared.team_reference, context) : ""}`;
}

function answerOf(answer, context) {
  const summary = objectOf(answer.summary);
  const nodes = [
    answer.target,
    ...listOf(answer.upstream),
    ...listOf(answer.downstream),
  ].map(objectOf);
  const labels = new Map(
    nodes.map((node) => [node.key, titleOf(node, context)]),
  );
  const flag = (value) =>
    escapeHtml(context.t(value === true ? "why.yes" : "why.no"));
  const target = objectOf(answer.target);
  const rationale = objectOf(target.rationale);
  const briefRationale =
    typeof rationale.text === "string"
      ? `${rationale.text.slice(0, 240)}${rationale.text.length > 240 ? "…" : ""}`
      : "";
  return [
    `<p class="note">${escapeHtml(context.t("why.offline"))}</p>`,
    `<h3>${escapeHtml(titleOf(target, context))}</h3><p>${escapeHtml(stateOf(target, context))} · v${escapeHtml(objectOf(target.reference).version_number ?? "—")} · <code>${escapeHtml(target.code)}</code></p>`,
    briefRationale
      ? `<p><strong>${escapeHtml(context.t(ORIGINS[rationale.origin] ?? "why.unknownOrigin"))}</strong></p><p class="why-verbatim">${escapeHtml(briefRationale)}</p>`
      : `<p>${escapeHtml(context.t("why.noRationale"))}</p>`,
    '<dl class="facts">',
    ...[
      ["why.completeTwin", summary.complete_to_twin],
      ["why.completeEvidence", summary.complete_to_evidence],
      ["why.allPaths", summary.all_paths_complete],
    ].map(
      ([label, value]) =>
        `<div><dt>${escapeHtml(context.t(label))}</dt><dd>${flag(value)}</dd></div>`,
    ),
    "</dl>",
    `<details><summary>${escapeHtml(context.t("why.details"))}</summary><ul class="cards">${nodeOf(answer.target, context, false)}</ul></details>`,
    contextOf(answer, context),
    `<details><summary>${escapeHtml(context.t("why.upstream"))} (${escapeHtml(summary.upstream_count ?? listOf(answer.upstream).length)})</summary>${nodesOf(listOf(answer.upstream), context)}</details>`,
    `<details><summary>${escapeHtml(context.t("why.downstream"))} (${escapeHtml(summary.downstream_count ?? listOf(answer.downstream).length)})</summary>${nodesOf(listOf(answer.downstream), context)}</details>`,
    listOf(answer.links).length === 0
      ? ""
      : `<details><summary>${escapeHtml(context.t("why.relations"))}</summary><ul>${answer.links.map((link) => `<li>${escapeHtml(labels.get(link.source) ?? link.source)} → ${escapeHtml(labels.get(link.target) ?? link.target)} · ${escapeHtml(link.kind)}</li>`).join("")}</ul></details>`,
    gapsOf(answer.gaps, summary, context),
    validationOf(answer.human_validation, context),
    listOf(answer.limits).length === 0
      ? ""
      : `<details><summary>${escapeHtml(context.t("why.limits"))}</summary><ul>${answer.limits.map((limit) => `<li>${limit.startsWith("PROVIDED_PROTOTYPE_") ? escapeHtml(context.t(`workflow.limit.${limit}`)) : ""} <code>${escapeHtml(limit)}</code></li>`).join("")}</ul></details>`,
  ].join("\n");
}

function whySection(state, context, result = {}) {
  const catalog = objectOf(state.why);
  const options = listOf(catalog.items).map(
    (node) =>
      `<option value="${escapeHtml(node.key)}"${result.answer && objectOf(result.answer.target).key === node.key ? " selected" : ""}>${escapeHtml(titleOf(node, context))} · ${escapeHtml(node.code)} · v${escapeHtml(objectOf(node.reference).version_number ?? "—")} · ${escapeHtml(context.t(node.current ? "why.current" : "why.historical"))} · ${escapeHtml(node.key)}</option>`,
  );
  const candidates = listOf(result.candidates).filter(validSelector);
  const content = [
    '<section aria-labelledby="why-title">',
    `<h2 id="why-title">${escapeHtml(context.t("why.title"))}</h2>`,
    `<p>${escapeHtml(context.t("why.intro"))}</p>`,
    options.length === 0
      ? `<p>${escapeHtml(context.t(catalog.problem === "MISSING" ? "why.legacy" : "why.invalidCatalog"))}</p>`
      : `<label for="why-selector">${escapeHtml(context.t("why.select"))}</label><select id="why-selector"><option value="">${escapeHtml(context.t("why.select"))}</option>${options.join("")}</select>`,
    `<form id="why-form"><label for="why-code">${escapeHtml(context.t("why.code"))}</label><input id="why-code" name="code" maxlength="2048" autocomplete="off" spellcheck="false" value="${escapeHtml(result.code ?? "")}"><button type="submit" class="action">${escapeHtml(context.t("why.title"))}</button></form>`,
    candidates.length === 0
      ? ""
      : `<p>${escapeHtml(context.t("why.ambiguous"))}</p><ul>${candidates.map((key) => `<li>${button({ key, title: key }, context)}</li>`).join("")}</ul>`,
    result.answer ? answerOf(result.answer, context) : "",
    "</section>",
  ];
  return content.join("\n");
}

module.exports = { whySection };
