"use strict";

const { execFile } = require("node:child_process");
const { bareProgram } = require("./commands");
const { validSelector } = require("./why");

const STATES = ["TO_VERIFY", "CONFIRMED", "REFUTED", "UNCERTAIN", "CONTESTED"];
const OUTCOMES = ["CONFIRMED", "REFUTED", "UNCERTAIN"];
const SOURCES = ["ACTIVE", "RETIRED", "SOURCE_UNAVAILABLE"];
const SESSIONS = ["HUMAN_SESSION", "SYNTHETIC_EXERCISE"];
const ERRORS = new Set([
  "FOLDER_NOT_VERIFIED",
  "PROJECT_NOT_LINKED",
  "PROJECT_NOT_FOUND",
  "NOT_SIGNED_IN",
  "STUDIO_UNREACHABLE",
  "VALIDATION_INPUT_INVALID",
  "VALIDATION_CONTEXT_CHANGED",
]);

function objectOf(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function validNode(value) {
  const node = objectOf(value);
  return validSelector(node.key) && typeof node.title === "string";
}

function validOverview(answer, projectId) {
  return (
    answer.kind === "orchestwin.human-validation" &&
    answer.schema_version === 1 &&
    answer.project_id === projectId &&
    Number.isInteger(answer.candidate_count) &&
    answer.candidate_count >= 0 &&
    Array.isArray(answer.candidates) &&
    answer.candidate_count === answer.candidates.length &&
    answer.candidates.every(validNode) &&
    Array.isArray(answer.hypotheses) &&
    answer.hypotheses.every((item) => STATES.includes(objectOf(item).state)) &&
    Array.isArray(answer.outcomes) &&
    answer.outcomes.every((item) => {
      const outcome = objectOf(item);
      return (
        OUTCOMES.includes(outcome.outcome) &&
        SESSIONS.includes(outcome.session_kind) &&
        SOURCES.includes(outcome.effective_status)
      );
    }) &&
    Object.keys(objectOf(answer.summary)).length > 0 &&
    Object.keys(objectOf(answer.empirical_summary)).length > 0 &&
    Array.isArray(answer.omitted_sections) &&
    Array.isArray(answer.limits)
  );
}

function validWalkthrough(answer, projectId) {
  return (
    answer.kind === "orchestwin.scenario-walkthrough" &&
    answer.schema_version === 1 &&
    answer.project_id === projectId &&
    validNode(answer.scenario) &&
    objectOf(answer.scenario).kind === "SCENARIO" &&
    Array.isArray(answer.steps) &&
    answer.steps.every((step) => {
      const value = objectOf(step);
      return (
        Number.isInteger(value.number) &&
        value.number > 0 &&
        typeof value.text === "string" &&
        Array.isArray(value.anchors) &&
        value.anchors.every(validNode) &&
        Array.isArray(value.observe) &&
        Array.isArray(value.gaps)
      );
    }) &&
    Array.isArray(answer.twin_references) &&
    answer.twin_references.every(validNode) &&
    Array.isArray(answer.design_references) &&
    answer.design_references.every(validNode) &&
    Array.isArray(answer.anchor_candidates) &&
    answer.anchor_candidates.every(validNode) &&
    Array.isArray(answer.gaps) &&
    Array.isArray(answer.limits)
  );
}

function read(root, program, args, projectId, offline, validate, execute) {
  return new Promise((resolve) => {
    const finish = (error, stdout, stderr) => {
      if (error) {
        let status = error.code === "ENOENT" ? "UNAVAILABLE" : "FAILED";
        for (const line of String(stderr ?? "").split(/\r?\n/).reverse()) {
          try {
            const code = objectOf(objectOf(JSON.parse(line)).error).code;
            if (ERRORS.has(code)) {
              status = code;
              break;
            }
          } catch {}
        }
        resolve({ status, answer: null });
        return;
      }
      let answer;
      try {
        answer = objectOf(JSON.parse(stdout));
      } catch {
        resolve({ status: "INVALID", answer: null });
        return;
      }
      if (!validate(answer, projectId)) {
        resolve({ status: "INVALID", answer: null });
        return;
      }
      const fallback = /(?:Verified local Dossier|Dossier locale verificato) \(/.test(
        String(stderr ?? ""),
      );
      resolve({ status: "OK", answer, source: offline || fallback ? "OFFLINE" : "STUDIO" });
    };
    try {
      execute(
        bareProgram(program),
        [...args, ...(offline ? ["--offline"] : []), "--json"],
        {
          cwd: root,
          shell: false,
          windowsHide: true,
          timeout: 30000,
          maxBuffer: 32 * 1024 * 1024,
          encoding: "utf8",
        },
        finish,
      );
    } catch {
      resolve({ status: "FAILED", answer: null });
    }
  });
}

function readValidation(root, program, projectId, { offline = true } = {}, execute = execFile) {
  return read(root, program, ["validation"], projectId, offline, validOverview, execute);
}

function readWalkthrough(root, program, scenario, projectId, options = {}, execute = execFile) {
  const { offline = true, alternative = "", documentHash = "" } = options;
  if (
    !validSelector(scenario) ||
    scenario.startsWith("-") ||
    typeof alternative !== "string" ||
    (alternative !== "" && (!validSelector(alternative) || alternative.startsWith("-"))) ||
    typeof documentHash !== "string" ||
    (documentHash !== "" && !/^[a-f0-9]{64}$/.test(documentHash))
  ) {
    return Promise.resolve({ status: "VALIDATION_INPUT_INVALID", answer: null });
  }
  const args = [
    "validation",
    "walkthrough",
    scenario,
    ...(alternative === "" ? [] : ["--alternative", alternative]),
    ...(documentHash === "" ? [] : ["--document-hash", documentHash]),
  ];
  return read(root, program, args, projectId, offline, validWalkthrough, execute);
}

module.exports = { readValidation, readWalkthrough };
