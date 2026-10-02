"use strict";

const { execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { bareProgram } = require("./commands");

const DOCUMENT_PATH = "traceability/why.json";
const SELECTOR = /^[A-Za-z0-9_.:/%@+\-]+$/;

function validSelector(value) {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 2048 &&
    value === value.trim() &&
    SELECTOR.test(value)
  );
}

function objectOf(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

function inside(root, file) {
  const relative = path.relative(fs.realpathSync(root), fs.realpathSync(file));
  return (
    relative !== "" &&
    !relative.startsWith(`..${path.sep}`) &&
    relative !== ".." &&
    !path.isAbsolute(relative)
  );
}

function readWhyCatalog(root, knowledge, manifest, projectId) {
  const entry = objectOf(manifest.why);
  const empty = { available: false, problem: "MISSING", items: [] };
  if (!Object.hasOwn(manifest, "why")) {
    return empty;
  }
  if (entry.document !== DOCUMENT_PATH || entry.schema_version !== 1) {
    return { ...empty, problem: "INVALID" };
  }
  try {
    const folder = path.join(root, knowledge);
    const file = path.join(folder, ...DOCUMENT_PATH.split("/"));
    if (!inside(root, folder) || !inside(folder, file)) {
      return { ...empty, problem: "INVALID" };
    }
    const document = JSON.parse(
      fs.readFileSync(file, "utf8").replace(/^\uFEFF/, ""),
    );
    if (
      document.kind !== "orchestwin.why" ||
      document.schema_version !== 1 ||
      document.project_id !== projectId ||
      !Array.isArray(document.nodes)
    ) {
      return { ...empty, problem: "INVALID" };
    }
    const items = document.nodes.map((node) => ({
      key: node.key,
      code: node.code,
      title: node.title,
      kind: node.kind,
      current: node.current === true,
      reference: objectOf(node.reference),
    }));
    if (
      items.some(
        (item) =>
          !validSelector(item.key) ||
          !validSelector(item.code) ||
          typeof item.title !== "string" ||
          typeof item.kind !== "string",
      ) ||
      new Set(items.map((item) => item.key)).size !== items.length
    ) {
      return { ...empty, problem: "INVALID" };
    }
    return { available: true, problem: null, items };
  } catch {
    return { ...empty, problem: "UNREADABLE" };
  }
}

function readWhyAnswer(root, program, code, projectId, execute = execFile) {
  if (!validSelector(code)) {
    return Promise.resolve({ status: "WHY_CODE_INVALID", answer: null });
  }
  return new Promise((resolve) => {
    const finish = (error, stdout, stderr) => {
      if (error) {
        let details = {};
        for (const line of String(stderr ?? "")
          .split(/\r?\n/)
          .reverse()) {
          try {
            const found = objectOf(JSON.parse(line)).error;
            if (found && typeof found === "object") {
              details = found;
              break;
            }
          } catch {}
        }
        resolve({
          status:
            typeof details.code === "string"
              ? details.code
              : error.code === "ENOENT"
                ? "UNAVAILABLE"
                : "FAILED",
          answer: null,
          candidates: Array.isArray(details.candidates)
            ? details.candidates.filter(validSelector)
            : [],
        });
        return;
      }
      let answer;
      try {
        answer = objectOf(JSON.parse(stdout));
      } catch {
        resolve({
          status: error && error.code === "ENOENT" ? "UNAVAILABLE" : "FAILED",
          answer: null,
        });
        return;
      }
      if (
        answer.kind !== "orchestwin.why-answer" ||
        answer.schema_version !== 1 ||
        answer.project_id !== projectId ||
        !validSelector(objectOf(answer.target).key) ||
        !Array.isArray(answer.upstream) ||
        !Array.isArray(answer.downstream) ||
        !Array.isArray(answer.links) ||
        !Array.isArray(answer.gaps) ||
        !Array.isArray(answer.human_validation) ||
        !Array.isArray(answer.limits)
      ) {
        resolve({ status: "INVALID", answer: null });
        return;
      }
      if (
        [
          answer.target,
          ...answer.upstream,
          ...answer.downstream,
          ...answer.human_validation,
        ].some((value) => !validSelector(objectOf(value).key)) ||
        answer.links.some(
          (value) =>
            !validSelector(objectOf(value).source) ||
            !validSelector(objectOf(value).target),
        )
      ) {
        resolve({ status: "INVALID", answer: null });
        return;
      }
      resolve({ status: "OK", answer });
    };
    try {
      execute(
        bareProgram(program),
        ["why", code, "--offline", "--json"],
        {
          cwd: root,
          shell: false,
          windowsHide: true,
          timeout: 30000,
          maxBuffer: 4 * 1024 * 1024,
          encoding: "utf8",
        },
        finish,
      );
    } catch {
      resolve({ status: "FAILED", answer: null });
    }
  });
}

module.exports = {
  DOCUMENT_PATH,
  readWhyAnswer,
  readWhyCatalog,
  validSelector,
};
