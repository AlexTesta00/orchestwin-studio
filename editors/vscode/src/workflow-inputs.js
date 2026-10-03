"use strict";

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const DECISIONS = "workflow/decisions.json";
const PROTOTYPES = "design/provided-prototypes.json";
const LIMITS = Object.freeze([
  "PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE",
  "PROVIDED_PROTOTYPE_CODE_UNAVAILABLE",
  "PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE",
  "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE",
  "PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE",
]);
const TARGETS = Object.freeze(["BRIEF", "TEAM", "USER_TWINS", "EVIDENCE", "SCENARIOS", "NEEDS", "REQUIREMENTS", "JOURNEYS", "DESIGN", "EVALUATION", "PACKAGE"]);

function objectOf(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function validHash(record) {
  const copy = { ...record };
  delete copy.content_hash;
  return /^[a-f0-9]{64}$/.test(record.content_hash) && crypto.createHash("sha256").update(canonical(copy), "utf8").digest("hex") === record.content_hash;
}

function readInside(folder, relative) {
  const file = path.join(folder, ...relative.split("/"));
  const resolved = path.relative(fs.realpathSync(folder), fs.realpathSync(file));
  if (resolved === "" || resolved === ".." || resolved.startsWith(`..${path.sep}`) || path.isAbsolute(resolved)) throw new Error("outside folder");
  return JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
}

function readWorkflowInputs(root, knowledge, manifest, projectId) {
  const declared = objectOf(manifest.workflow_inputs);
  const folder = path.join(root, knowledge);
  const present = [DECISIONS, PROTOTYPES].some((relative) => fs.existsSync(path.join(folder, ...relative.split("/"))));
  if (!Object.hasOwn(manifest, "workflow_inputs") && !present) return null;
  try {
    if (declared.schema_version !== 1 || declared.decisions_document !== DECISIONS || declared.prototypes_document !== PROTOTYPES || !Array.isArray(declared.limits)) throw new Error("manifest");
    const decisions = readInside(folder, DECISIONS).decisions;
    const source = readInside(folder, PROTOTYPES);
    const prototypes = source.prototypes;
    if (!Array.isArray(decisions) || !Array.isArray(prototypes)) throw new Error("arrays");
    for (const item of [...decisions, ...prototypes]) {
      if (!item || item.project_id !== projectId || !validHash(item)) throw new Error("record");
    }
    if (decisions.some((item, index) => !TARGETS.includes(item.target) || !["DECLARE_MISSING", "RESOLVE_MISSING"].includes(item.action) || typeof item.reason !== "string" || !Number.isSafeInteger(item.sequence) || item.sequence < 1 || (index > 0 && item.sequence <= decisions[index - 1].sequence))) throw new Error("decisions");
    if (prototypes.some((item) => typeof item.title !== "string" || !/^PRT-[0-9]{3,6}$/.test(item.code) || objectOf(objectOf(item.mockup).mockup).design_alternative_id !== item.id)) throw new Error("prototypes");
    const limits = prototypes.length > 0 ? LIMITS : [];
    if (canonical(declared.limits) !== canonical(limits) || canonical(source.approved_prototype ?? null) !== canonical(declared.approved_prototype ?? null)) throw new Error("limits or approved reference");
    if (declared.approved_prototype) {
      const ref = declared.approved_prototype;
      if (ref.gate_status !== "APPROVED" || !prototypes.some((item) => item.id === ref.artifact_id && item.version_number === ref.version_number && item.content_hash === ref.content_hash)) throw new Error("approved reference");
    }
    return { available: true, problem: null, decisions, prototypes, limits, approved: declared.approved_prototype ?? null };
  } catch {
    return { available: false, problem: "INVALID", decisions: [], prototypes: [], limits: [] };
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

function workflowSection(state, context) {
  const records = state.workflowInputs;
  if (!records) return "";
  if (!records.available) return `<section><h2>${escapeHtml(context.t("workflow.title"))}</h2><p>${escapeHtml(context.t("workflow.invalid"))}</p></section>`;
  return [
    '<section aria-labelledby="workflow-title" id="workflow-inputs">',
    `<h2 id="workflow-title">${escapeHtml(context.t("workflow.title"))}</h2>`,
    `<label for="workflow-filter">${escapeHtml(context.t("workflow.filter"))}</label><select id="workflow-filter"><option value="all">${escapeHtml(context.t("workflow.all"))}</option><option value="gaps">${escapeHtml(context.t("workflow.gaps"))}</option><option value="owner">${escapeHtml(context.t("workflow.owner"))}</option></select>`,
    '<ul class="cards">',
    ...records.decisions.map((item) => `<li class="card" data-workflow-kind="${item.action === "DECLARE_MISSING" ? "gap" : "owner"}"><strong>${escapeHtml(item.target)}</strong><p>${escapeHtml(context.t(item.action === "DECLARE_MISSING" ? "workflow.missing" : "workflow.resolved"))}</p><p class="why-verbatim">${escapeHtml(item.reason)}</p><code>${escapeHtml(item.content_hash)}</code></li>`),
    ...records.prototypes.map((item) => `<li class="card" data-workflow-kind="owner"><strong>${escapeHtml(item.code)} · ${escapeHtml(item.title)}</strong><p>${escapeHtml(context.t("workflow.supplied"))} · v${escapeHtml(item.version_number)}</p>${item.declared_origin ? `<p>${escapeHtml(context.t("workflow.origin"))}: ${escapeHtml(item.declared_origin)}</p>` : ""}<code>${escapeHtml(item.content_hash)}</code></li>`),
    "</ul>",
    `<ul>${records.limits.map((code) => `<li>${escapeHtml(context.t(`workflow.limit.${code}`))} <code>${escapeHtml(code)}</code></li>`).join("")}</ul>`,
    "</section>",
  ].join("\n");
}

module.exports = { LIMITS, canonical, readWorkflowInputs, workflowSection };
