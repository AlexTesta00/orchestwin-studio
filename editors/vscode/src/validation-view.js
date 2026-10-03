"use strict";

const { validSelector } = require("./why");

const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const GAP_LABELS = {
  STEP_ANCHOR_NOT_ATTESTED: "validation.linkToComplete",
  SOURCE_TEXT_UNAVAILABLE: "validation.sourceWithoutText",
  VALIDATION_REFERENCE_UNAVAILABLE: "validation.referenceUnavailable",
  MISSING_MOCKUP_ANCHOR: "validation.linkToComplete",
  SCENARIO_STEPS_UNAVAILABLE: "validation.stepsUnavailable",
  MISSING_DESIGN: "validation.linkToComplete",
  MISSING_TWIN: "why.gap.MISSING_TWIN",
  MISSING_SCENARIO: "why.gap.MISSING_SCENARIO",
  MISSING_SOURCE: "why.gap.MISSING_SOURCE",
  MISSING_SOURCE_VERSION: "why.gap.MISSING_SOURCE_VERSION",
  CONTEXT_OUTDATED: "why.gap.CONTEXT_OUTDATED",
  SOURCE_RETIRED: "why.retired",
};

function escape(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ENTITIES[character]);
}

function objectOf(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function listOf(value) {
  return Array.isArray(value) ? value : [];
}

function verbatim(value) {
  return `<p class="why-verbatim">${escape(value)}</p>`;
}

function reference(value, context) {
  const item = objectOf(value);
  return `<p class="why-reference"><code>${escape(item.artifact_id ?? item.generation_id ?? "—")}</code> · v${escape(item.version_number ?? "—")}<br><code>${escape(item.content_hash ?? "—")}</code></p>`;
}

function technical(value) {
  return `<pre class="validation-technical">${escape(JSON.stringify(value, null, 2))}</pre>`;
}

function whyAction(key, context) {
  return validSelector(key) && context.whyKeys.has(key)
    ? `<button type="button" class="action" data-command="why" data-code="${escape(key)}">${escape(context.t("why.title"))}</button>`
    : "";
}

function gaps(values, context) {
  const items = listOf(values);
  if (items.length === 0) {
    return "";
  }
  const labels = [...new Set(items.map((item) => GAP_LABELS[objectOf(item).code] ?? "validation.linkToComplete"))];
  return `<ul>${labels.map((key) => `<li>${escape(context.t(key))}</li>`).join("")}</ul><details><summary>${escape(context.t("validation.gapDetails"))}</summary>${technical(items)}</details>`;
}

function nodes(values, context) {
  return listOf(values).map((item) => {
    const node = objectOf(item);
    const mockup = objectOf(objectOf(node.declared_context).mockup);
    return `<li><strong>${escape(node.title ?? node.code)}</strong> · <code>${escape(node.code)}</code>${reference(node.reference, context)}${mockup.screen_code ? `<p>${escape(context.t("why.screen"))}: <code>${escape(mockup.screen_code)}</code></p>` : ""}${whyAction(node.key, context)}<details><summary>${escape(context.t("why.references"))}</summary>${technical(node)}</details></li>`;
  }).join("");
}

function candidate(value, context) {
  const item = objectOf(value);
  return `<li class="card"><strong>${escape(item.title)}</strong> · <code>${escape(item.code)}</code>${whyAction(item.key, context)}${gaps(item.gaps, context)}<details><summary>${escape(context.t("why.references"))}</summary>${reference(item.reference, context)}<h4>${escape(context.t("validation.twins"))}</h4><ul>${nodes(item.twin_references, context)}</ul><h4>${escape(context.t("validation.scenarios"))}</h4><ul>${nodes(item.scenario_candidates, context)}</ul><h4>${escape(context.t("validation.design"))}</h4><ul>${nodes(item.design_references, context)}</ul>${technical({ origin: item.origin, limits: item.limits })}</details></li>`;
}

function outcome(value, context) {
  const item = objectOf(value);
  const citation = objectOf(item.citation);
  return [
    '<li class="card validation-outcome">',
    `<p><strong>${escape(item.code)} · ${escape(context.t(`validation.state.${item.outcome}`))}</strong></p>`,
    `<p>${escape(context.t(`validation.session.${item.session_kind}`))} · <code>${escape(item.session_ref)}</code></p>`,
    item.coverage === "PARTIAL" ? `<p>${escape(context.t("validation.partial"))}</p>` : "",
    item.effective_status === "RETIRED" ? `<p><strong>${escape(context.t("validation.retired"))}</strong></p>` : "",
    item.effective_status === "SOURCE_UNAVAILABLE" ? `<p>${escape(context.t("validation.referenceUnavailable"))}</p>` : "",
    item.source_text_available === false ? `<p>${escape(context.t("validation.sourceWithoutText"))}</p>` : "",
    `<blockquote class="why-verbatim">${escape(citation.quote)}</blockquote>`,
    `<p>${escape(context.t("why.limits"))}</p>${verbatim(item.limitations)}`,
    `<details><summary>${escape(context.t("validation.provenance"))}</summary>`,
    `<p>${escape(context.t("validation.source"))}: <code>${escape(item.evidence_id)}</code> · v${escape(item.evidence_version)}<br><code>${escape(item.evidence_content_hash)}</code></p>`,
    `<p>L${escape(citation.start_line ?? "—")}–L${escape(citation.end_line ?? "—")} · ${escape(citation.start ?? "—")}:${escape(citation.end ?? "—")}</p>`,
    `<p>${escape(context.t("validation.hypothesisVersion"))}: <code>${escape(item.hypothesis_id)}</code> · v${escape(item.hypothesis_version_number)}<br><code>${escape(item.hypothesis_content_hash)}</code></p>`,
    `<p>${escape(context.date(item.recorded_at) ?? item.recorded_at)}</p>${technical(item)}`,
    "</details>",
    gaps(item.gaps, context),
    "</li>",
  ].join("");
}

function hypothesis(value, context) {
  const item = objectOf(value);
  const exact = context.catalog.find((node) => node.kind === "VALIDATION_HYPOTHESIS" && objectOf(node.reference).artifact_id === item.id && objectOf(node.reference).version_number === item.version_number && objectOf(node.reference).content_hash === item.content_hash);
  return [
    '<li class="card validation-hypothesis">',
    `<p><strong>${escape(item.code)} · v${escape(item.version_number)} · ${escape(context.t(`validation.state.${item.state}`))}</strong></p>`,
    item.current === false ? `<p>${escape(context.t("validation.previous"))}</p>` : "",
    item.partial_evidence === true ? `<p>${escape(context.t("validation.partial"))}</p>` : "",
    item.conflicting_outcomes === true ? `<p>${escape(context.t("validation.state.CONTESTED"))}</p>` : "",
    `<h4>${escape(context.t("validation.questionOrTask"))}</h4>${item.question ? verbatim(item.question) : ""}${item.task ? verbatim(item.task) : ""}`,
    `<h4>${escape(context.t("validation.observe"))}</h4><ul>${listOf(item.observe).map((text) => `<li class="why-verbatim">${escape(text)}</li>`).join("")}</ul>`,
    `<p>${escape(context.t("why.limits"))}</p>${verbatim(item.limitations)}`,
    gaps(item.gaps, context),
    exact ? whyAction(exact.key, context) : "",
    `<details><summary>${escape(context.t("validation.provenance"))}</summary>`,
    reference({ artifact_id: item.id, version_number: item.version_number, content_hash: item.content_hash }, context),
    `<p>${escape(context.t("validation.origin"))}</p>${reference(item.origin_reference, context)}${whyAction(item.origin_key, context)}`,
    `<p>${escape(context.t("validation.twins"))}</p>${reference(item.twin_reference, context)}${whyAction(item.twin_key, context)}`,
    `<p>${escape(context.t("validation.scenarios"))}</p>${reference(item.scenario_reference, context)}${whyAction(item.scenario_key, context)}`,
    `<p>${escape(context.t("validation.design"))}</p>${reference(item.design_reference, context)}${whyAction(item.design_key, context)}`,
    technical(item),
    "</details>",
    `<details><summary>${escape(context.t("validation.outcomes"))} (${listOf(item.outcomes).length})</summary><ul class="cards">${listOf(item.outcomes).map((value) => outcome(value, context)).join("")}</ul></details>`,
    "</li>",
  ].join("");
}

function overview(result, context) {
  const answer = objectOf(result.answer);
  if (!result.answer) {
    return "";
  }
  const summary = objectOf(answer.summary);
  const empirical = objectOf(answer.empirical_summary);
  return [
    `<h3>${escape(context.t("validation.candidates"))} (${escape(answer.candidate_count)})</h3>`,
    `<p>${escape(context.t("validation.candidateNote"))}</p>`,
    `<details id="validation-candidates"><summary>${escape(context.t("validation.candidateDetails"))} (${escape(answer.candidate_count)})</summary><ul class="cards">${listOf(answer.candidates).map((item) => candidate(item, context)).join("")}</ul></details>`,
    `<h3>${escape(context.t("validation.operational"))} (${escape(summary.hypotheses ?? 0)})</h3>`,
    `<p>${["TO_VERIFY", "CONFIRMED", "REFUTED", "UNCERTAIN", "CONTESTED"].map((key) => `${escape(context.t(`validation.state.${key}`))}: ${escape(summary[key.toLowerCase()] ?? 0)}`).join(" · ")}</p>`,
    listOf(answer.hypotheses).length === 0 ? `<p>${escape(context.t("validation.noHypotheses"))}</p>` : `<ul class="cards">${answer.hypotheses.map((item) => hypothesis(item, context)).join("")}</ul>`,
    `<h3>${escape(context.t("validation.outcomes"))} (${listOf(answer.outcomes).length})</h3>`,
    `<p>${escape(context.t("validation.retired"))}: ${escape(summary.retired_outcomes ?? 0)}</p>`,
    `<details><summary>${escape(context.t("validation.outcomeHistory"))}</summary><ul class="cards">${listOf(answer.outcomes).map((item) => outcome(item, context)).join("")}</ul></details>`,
    `<h3>${escape(context.t("validation.empiricalSummary"))}</h3><p>${escape(context.t("validation.session.HUMAN_SESSION"))}: ${escape(empirical.human_session_outcomes ?? 0)}<br>${escape(context.t("validation.session.SYNTHETIC_EXERCISE"))}: ${escape(empirical.synthetic_exercise_outcomes ?? 0)}</p>`,
    `<p>${escape(context.t("validation.noPromotion"))}</p>`,
    listOf(answer.omitted_sections).length > 0 ? `<h3>${escape(context.t("validation.omitted"))}</h3><ul>${answer.omitted_sections.map((item) => `<li>${escape(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul>` : "",
    `<details><summary>${escape(context.t("why.limits"))}</summary>${technical(answer.limits)}</details>`,
  ].join("");
}

function walkthrough(result, context) {
  const answer = objectOf(result.answer);
  if (!result.answer) {
    return "";
  }
  return [
    `<h3>${escape(objectOf(answer.scenario).title)}</h3>${reference(answer.reference, context)}`,
    `<h4>${escape(context.t("validation.questionOrTask"))}</h4>${answer.task ? verbatim(answer.task) : `<p>${escape(context.t("validation.taskUnavailable"))}</p>`}`,
    `<ol class="validation-steps">${listOf(answer.steps).map((value) => { const step = objectOf(value); return `<li value="${escape(step.number)}">${verbatim(step.text)}${listOf(step.observe).length > 0 ? `<h4>${escape(context.t("validation.observe"))}</h4><ul>${step.observe.map((value) => `<li>${escape(value)}</li>`).join("")}</ul>` : ""}${listOf(step.anchors).length > 0 ? `<ul>${nodes(step.anchors, context)}</ul>` : ""}${gaps(step.gaps, context)}</li>`; }).join("")}</ol>`,
    answer.expected_outcome ? `<h4>${escape(context.t("validation.expected"))}</h4>${verbatim(answer.expected_outcome)}` : "",
    `<h4>${escape(context.t("validation.anchorCandidates"))} (${listOf(answer.anchor_candidates).length})</h4><p>${escape(context.t("validation.anchorNote"))}</p><ul>${nodes(answer.anchor_candidates, context)}</ul>`,
    gaps(answer.gaps, context),
    `<details><summary>${escape(context.t("validation.provenance"))}</summary><h4>${escape(context.t("validation.twins"))}</h4><ul>${nodes(answer.twin_references, context)}</ul><h4>${escape(context.t("validation.design"))}</h4><ul>${nodes(answer.design_references, context)}</ul>${technical(answer.limits)}</details>`,
    `<p>${escape(context.t("validation.softwareLimit"))}</p>`,
  ].join("");
}

function resultStatus(result, context) {
  if (result.status === "OK") {
    return `<p class="note">${escape(context.t(result.source === "STUDIO" ? "validation.studio" : "validation.offline"))}</p>`;
  }
  if (!result.status) {
    return "";
  }
  const key = result.status === "LOADING" ? "loading" : result.status === "UNAVAILABLE" ? "unavailable" : result.status === "FOLDER_NOT_VERIFIED" ? "folderUnverified" : result.status === "VALIDATION_INPUT_INVALID" ? "invalid" : "failed";
  return `<p role="status">${escape(context.t(`validation.${key}`))}</p>`;
}

function validationSection(state, context, result = {}, path = {}) {
  const catalog = listOf(objectOf(state.why).items);
  const local = { ...context, catalog, whyKeys: new Set(catalog.map((item) => item.key)) };
  const scenarios = catalog.filter((item) => item.kind === "SCENARIO");
  return [
    '<section aria-labelledby="validation-title">',
    `<h2 id="validation-title">${escape(context.t("validation.title"))}</h2>`,
    `<p>${escape(context.t("validation.readOnly"))}</p>`,
    `<div class="actions"><button type="button" class="action" data-command="validation" data-mode="offline">${escape(context.t("validation.readLocal"))}</button><button type="button" class="action" data-command="validation" data-mode="studio">${escape(context.t("validation.readStudio"))}</button></div>`,
    resultStatus(result, local),
    overview(result, local),
    `<details id="validation-walkthrough"${path.answer || path.status ? " open" : ""}><summary>${escape(context.t("validation.walkthrough"))}</summary>`,
    `<form id="validation-walkthrough-form">`,
    scenarios.length === 0 ? "" : `<label for="validation-scenario-selector">${escape(context.t("validation.scenarios"))}</label><select id="validation-scenario-selector"><option value="">${escape(context.t("validation.scenarioSelect"))}</option>${scenarios.map((node) => `<option value="${escape(node.key)}">${escape(node.title)} · ${escape(node.code)} · v${escape(objectOf(node.reference).version_number ?? "—")} · ${escape(context.t(node.current ? "why.current" : "validation.previous"))}</option>`).join("")}</select>`,
    `<label for="validation-scenario">${escape(context.t("validation.scenarioKey"))}</label><input id="validation-scenario" maxlength="2048" autocomplete="off" spellcheck="false" required value="${escape(path.code ?? "")}">`,
    `<label for="validation-alternative">${escape(context.t("validation.alternativeOptional"))}</label><input id="validation-alternative" maxlength="2048" autocomplete="off" spellcheck="false" value="${escape(path.alternative ?? "")}">`,
    `<label for="validation-document-hash">${escape(context.t("validation.documentHashOptional"))}</label><input id="validation-document-hash" maxlength="64" autocomplete="off" spellcheck="false" value="${escape(path.documentHash ?? "")}">`,
    `<label for="validation-mode">${escape(context.t("validation.readFrom"))}</label><select id="validation-mode"><option value="offline">${escape(context.t("validation.readLocal"))}</option><option value="studio"${path.mode === "studio" ? " selected" : ""}>${escape(context.t("validation.readStudio"))}</option></select>`,
    `<button type="submit" class="action">${escape(context.t("validation.walkthrough"))}</button></form>`,
    resultStatus(path, local),
    walkthrough(path, local),
    "</details>",
    "</section>",
  ].join("");
}

module.exports = { validationSection };
