"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { agentsState } = require("./agents");

const LOCAL_FOLDER = ".orchestwin";
const KNOWLEDGE_FOLDER = "orchestwin";
const STAGES = Object.freeze([
  "brief",
  "team",
  "twins",
  "requirements",
  "design",
]);
const VERDICTS = Object.freeze([
  "ALIGNED",
  "CODE_DRIFT",
  "DESIGN_OUTDATED",
  "REQUIREMENTS_OUTDATED",
]);
const DECISIONS = Object.freeze([
  "ALIGNED",
  "DESIGN_CHANGE",
  "REQUIREMENTS_CHANGE",
  "CODE_TASKS",
  "DISMISSED",
]);
const CRITIQUE_VERDICTS = Object.freeze(["FINE", "CONCERN", "DRIFT"]);
const TASK_ORIGINS = Object.freeze(["CODE_CHANGE", "TEST_RUN", "OWNER"]);
const LEARNING_SOURCES = Object.freeze(["TWIN_CRITIQUE", "OWNER"]);
const PROBLEM_STATUSES = Object.freeze(["FAILED", "BLOCKED"]);
const LATEST_LEARNED = 3;
const LOCAL_FILES = Object.freeze({
  link: ".orchestwin/project.json",
  tests: ".orchestwin/tests/latest.json",
  code: ".orchestwin/code/latest.json",
});
const TESTS_FOLDER = ".orchestwin/tests";
const RUN_FILE = "run.json";
const FOLDER_FILES = Object.freeze({
  manifest: "orchestwin.json",
  state: "state/state.json",
  twins: "twins/twins.json",
  changes: "twins/feedback/changes.json",
  tests: "twins/feedback/tests.json",
  learned: "twins/feedback/learned.json",
  requirements: "requirements/requirements.json",
  evidence: "twins/evidence.json",
});
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const FORBIDDEN_FOLDER_CHARACTERS = /[/\\:*?"<>|\0]/;
const LABEL = /^\d+\.\d+$/;

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function objectOf(value) {
  return isObject(value) ? value : {};
}

function listOf(value) {
  return Array.isArray(value) ? value : [];
}

function textOf(value) {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function countOf(value) {
  return Number.isInteger(value) && value >= 0 ? value : null;
}

function oneOf(value, allowed) {
  return typeof value === "string" && allowed.includes(value) ? value : null;
}

function firstLine(value) {
  const found = textOf(value);
  if (found === null) {
    return null;
  }
  const line = found.split(/\r?\n/, 1)[0].trim();
  return line === "" ? null : line;
}

function knowledgeFolderName(value) {
  if (
    typeof value !== "string" ||
    value.trim() === "" ||
    value !== value.trim() ||
    value === "." ||
    value === ".." ||
    FORBIDDEN_FOLDER_CHARACTERS.test(value)
  ) {
    return KNOWLEDGE_FOLDER;
  }
  return value;
}

function readJson(root, relative) {
  const file = path.join(root, ...relative.split("/"));
  let content;
  try {
    content = fs.readFileSync(file, "utf8");
  } catch (error) {
    const missing =
      error && (error.code === "ENOENT" || error.code === "ENOTDIR");
    return { status: missing ? "MISSING" : "UNREADABLE", value: null };
  }
  try {
    return { status: "OK", value: JSON.parse(content.replace(/^﻿/, "")) };
  } catch {
    return { status: "INVALID", value: null };
  }
}

function createReader(root) {
  const notices = [];
  function read(relative) {
    const found = readJson(root, relative);
    if (found.status === "OK" && !isObject(found.value)) {
      notices.push({ file: relative, problem: "UNEXPECTED" });
      return { status: "UNEXPECTED", value: null };
    }
    if (found.status === "INVALID") {
      notices.push({ file: relative, problem: "INVALID_JSON" });
    } else if (found.status === "UNREADABLE") {
      notices.push({ file: relative, problem: "UNREADABLE" });
    }
    return found;
  }
  return { notices, read };
}

function emptyFolder(knowledge) {
  return {
    available: false,
    problem: "MISSING",
    path: knowledge,
    name: null,
    language: null,
    version: null,
    publishedAt: null,
    approved: [],
    pending: null,
    complete: false,
  };
}

function emptyDevelopment(problem) {
  return {
    available: false,
    problem,
    aligned: null,
    recorded: 0,
    pending: 0,
    staleKnown: false,
    stale: 0,
    staleCommits: [],
    latest: null,
  };
}

function emptyTasks(problem) {
  return { available: false, problem, open: [], done: 0, dropped: 0 };
}

function emptyTests(problem) {
  return { available: false, problem, runs: 0, latest: null, report: null };
}

function emptyTwins(problem) {
  return { available: false, problem, learning: false, items: [] };
}

function emptyState(root) {
  return {
    root,
    linked: false,
    project: null,
    notices: [],
    folder: emptyFolder(KNOWLEDGE_FOLDER),
    reference: { requirements: null, design: null, alternative: null },
    development: emptyDevelopment("MISSING"),
    tasks: emptyTasks("MISSING"),
    tests: emptyTests("MISSING"),
    twins: emptyTwins("MISSING"),
    code: null,
    agents: agentsState(root),
  };
}

function approvedStages(manifest) {
  const progress = objectOf(manifest.progress);
  if (Array.isArray(progress.approved)) {
    return STAGES.filter((stage) => progress.approved.includes(stage));
  }
  const stages = objectOf(manifest.stages);
  return STAGES.filter((stage) => isObject(stages[stage]));
}

function folderOf(manifest, knowledge) {
  if (manifest.status !== "OK") {
    return { ...emptyFolder(knowledge), problem: manifest.status };
  }
  const document = manifest.value;
  const project = objectOf(document.project);
  const publication = objectOf(document.package);
  const approved = approvedStages(document);
  return {
    available: true,
    problem: null,
    path: knowledge,
    name: textOf(project.name),
    language: textOf(project.language),
    version: countOf(publication.version_number),
    publishedAt: textOf(publication.created_at),
    approved,
    pending: STAGES.find((stage) => !approved.includes(stage)) ?? null,
    complete: STAGES.every((stage) => approved.includes(stage)),
  };
}

function referenceOf(stateDocument) {
  if (stateDocument.status !== "OK") {
    return { requirements: null, design: null, alternative: null };
  }
  const reference = objectOf(stateDocument.value.reference);
  const requirements = objectOf(reference.requirements);
  const design = objectOf(reference.design);
  return {
    requirements: countOf(requirements.version_number),
    design: countOf(design.version_number),
    alternative: textOf(design.alternative_code),
  };
}

function currentReference(reference) {
  if (reference.requirements === null || reference.design === null) {
    return null;
  }
  return {
    requirements_version_number: reference.requirements,
    design_version_number: reference.design,
    alternative_code: reference.alternative,
  };
}

function isStale(reference, current) {
  if (current === null || !isObject(reference)) {
    return false;
  }
  return (
    reference.requirements_version_number !==
      current.requirements_version_number ||
    reference.design_version_number !== current.design_version_number ||
    reference.alternative_code !== current.alternative_code
  );
}

function changeOf(change) {
  const review = isObject(change.review) ? change.review : null;
  const decision = isObject(change.decision) ? change.decision : null;
  return {
    commit: textOf(change.commit),
    subject: firstLine(change.message),
    committedAt: textOf(change.committed_at),
    verdict: review === null ? null : oneOf(review.verdict, VERDICTS),
    reviewedAt: review === null ? null : textOf(review.reviewed_at),
    stale: review !== null && review.stale === true,
    decision: decision === null ? null : oneOf(decision.kind, DECISIONS),
  };
}

function developmentOf(stateDocument, manifest) {
  if (stateDocument.status !== "OK") {
    return emptyDevelopment(stateDocument.status);
  }
  const document = stateDocument.value;
  const changes = listOf(document.changes).filter(isObject);
  const alignedDocument = objectOf(document.aligned);
  const alignedCommit = textOf(alignedDocument.commit);
  const aligned =
    alignedCommit === null
      ? null
      : {
          commit: alignedCommit,
          decidedAt: textOf(alignedDocument.decided_at),
        };
  let pending = 0;
  for (const change of changes) {
    if (aligned !== null && change.commit === aligned.commit) {
      break;
    }
    pending += 1;
  }
  const pendingChanges = changes.slice(0, pending);
  const flagged = changes.some(
    (change) => typeof objectOf(change.review).stale === "boolean",
  );
  const counted = countOf(objectOf(manifest.state).stale_reviews);
  const staleChanges = pendingChanges.filter(
    (change) => objectOf(change.review).stale === true,
  );
  return {
    available: true,
    problem: null,
    aligned,
    recorded: changes.length,
    pending,
    staleKnown: flagged || counted !== null,
    stale: flagged ? staleChanges.length : (counted ?? 0),
    staleCommits: staleChanges
      .map((change) => textOf(change.commit))
      .filter(Boolean),
    latest: changes.length > 0 ? changeOf(changes[0]) : null,
  };
}

function originOf(task) {
  const origin = objectOf(task.origin);
  const kind = oneOf(origin.kind, TASK_ORIGINS);
  if (kind !== null) {
    return {
      kind,
      commit: textOf(origin.commit),
      testRunId: textOf(origin.test_run_id),
      twinName: textOf(origin.twin_name),
    };
  }
  const commit = textOf(task.from_commit);
  return {
    kind: commit === null ? null : "CODE_CHANGE",
    commit,
    testRunId: null,
    twinName: null,
  };
}

function taskOf(task) {
  const about = objectOf(task.about);
  return {
    code: textOf(task.code),
    text: textOf(task.text),
    createdAt: textOf(task.created_at),
    origin: originOf(task),
    criteria: listOf(about.criteria).filter((code) => textOf(code) !== null),
  };
}

function tasksOf(stateDocument) {
  if (stateDocument.status !== "OK") {
    return emptyTasks(stateDocument.status);
  }
  const items = listOf(stateDocument.value.tasks).filter(isObject);
  return {
    available: true,
    problem: null,
    open: items.filter((task) => task.status === "OPEN").map(taskOf),
    done: items.filter((task) => task.status === "DONE").length,
    dropped: items.filter((task) => task.status === "DROPPED").length,
  };
}

function statementsOf(requirementsDocument) {
  const statements = new Map();
  if (requirementsDocument.status !== "OK") {
    return statements;
  }
  const document = requirementsDocument.value;
  const criteria = Array.isArray(
    objectOf(document.specification).acceptance_criteria,
  )
    ? document.specification.acceptance_criteria
    : listOf(document.acceptance_criteria);
  for (const criterion of criteria.filter(isObject)) {
    const code = textOf(criterion.code);
    const statement = textOf(criterion.statement);
    if (code !== null && statement !== null) {
      statements.set(code, statement);
    }
  }
  return statements;
}

function critiqueOf(critique) {
  return {
    twinId: textOf(critique.twin_id),
    twinName: textOf(critique.twin_name),
    verdict: oneOf(critique.verdict, CRITIQUE_VERDICTS),
  };
}

function runOf(run, source, statements, current) {
  const summary = objectOf(run.summary);
  const critiques = listOf(run.critiques).filter(isObject).map(critiqueOf);
  const reviewedAt = textOf(run.reviewed_at);
  return {
    id: textOf(run.id),
    startedAt: textOf(run.started_at),
    finishedAt: textOf(run.finished_at),
    browsers: listOf(run.browsers)
      .filter(isObject)
      .map((browser) => ({
        name: textOf(browser.name),
        version: textOf(browser.version),
      }))
      .filter((browser) => browser.name !== null),
    summary: {
      passed: countOf(summary.passed) ?? 0,
      failed: countOf(summary.failed) ?? 0,
      blocked: countOf(summary.blocked) ?? 0,
      notCovered: countOf(summary.not_covered) ?? 0,
      notRun: countOf(summary.not_run) ?? 0,
    },
    problems: listOf(run.criteria)
      .filter(isObject)
      .filter((criterion) => PROBLEM_STATUSES.includes(criterion.status))
      .map((criterion) => ({
        code: textOf(criterion.code),
        status: criterion.status,
        statement: statements.get(criterion.code) ?? null,
      })),
    reviewed: critiques.length > 0 || reviewedAt !== null,
    reviewedAt,
    critiques,
    stale: isStale(run.reference, current),
    source,
  };
}

function localRun(reader, pointer, runs) {
  const runId = textOf(pointer.run_id);
  const folder = textOf(pointer.folder);
  if (runId === null || folder === null || !SAFE_NAME.test(folder)) {
    return null;
  }
  if (runs.some((run) => run.id === runId)) {
    return null;
  }
  const found = reader.read(`${TESTS_FOLDER}/${folder}/${RUN_FILE}`);
  if (found.status !== "OK" || found.value.id !== runId) {
    return null;
  }
  return found.value;
}

function reportOf(root, pointer) {
  const report = textOf(pointer.report);
  if (report === null) {
    return null;
  }
  const segments = report.split("/");
  if (segments.some((segment) => !SAFE_NAME.test(segment))) {
    return null;
  }
  const file = path.join(root, ...TESTS_FOLDER.split("/"), ...segments);
  try {
    return fs.statSync(file).isFile() ? file : null;
  } catch {
    return null;
  }
}

function testsOf(root, reader, documents, current) {
  const found = documents.tests;
  const broken = found.status !== "OK" && found.status !== "MISSING";
  const runs =
    found.status === "OK" ? listOf(found.value.runs).filter(isObject) : [];
  const latest = reader.read(LOCAL_FILES.tests);
  const pointer = latest.status === "OK" ? latest.value : null;
  const local = pointer === null ? null : localRun(reader, pointer, runs);
  const run = local ?? runs[0] ?? null;
  const statements = statementsOf(documents.requirements);
  return {
    available: !broken || local !== null,
    problem: broken && local === null ? found.status : null,
    runs: runs.length,
    latest:
      run === null
        ? null
        : runOf(run, local === null ? "FOLDER" : "LOCAL", statements, current),
    report: pointer === null ? null : reportOf(root, pointer),
  };
}

function twinsFromSnapshot(found) {
  if (found.status !== "OK") {
    return [];
  }
  return listOf(objectOf(found.value.snapshot).twin_versions)
    .filter(isObject)
    .map((version) => ({
      id: textOf(version.twin_id),
      name: textOf(objectOf(version.profile).name),
      profileVersion: countOf(version.version_number),
    }))
    .filter((twin) => twin.id !== null || twin.name !== null);
}

function twinsFromManifest(manifest) {
  return listOf(manifest.twins)
    .filter(isObject)
    .map((twin) => ({
      id: textOf(twin.twin_id),
      name: textOf(twin.name),
      profileVersion: countOf(twin.version_number),
    }))
    .filter((twin) => twin.id !== null || twin.name !== null);
}

function twinsFromLearning(entries) {
  return entries
    .map((entry) => ({
      id: textOf(entry.twin_id),
      name: textOf(entry.twin_name),
      profileVersion: countOf(entry.profile_version_number),
    }))
    .filter((twin) => twin.id !== null || twin.name !== null);
}

function matchesTwin(critique, twin) {
  const id = textOf(critique.twin_id);
  if (twin.id !== null && id !== null) {
    return id === twin.id;
  }
  return twin.name !== null && critique.twin_name === twin.name;
}

function latestCritique(runs, twin) {
  for (const run of runs) {
    const critique = listOf(run.critiques)
      .filter(isObject)
      .find((item) => matchesTwin(item, twin));
    if (critique !== undefined) {
      return { run, verdict: oneOf(critique.verdict, CRITIQUE_VERDICTS) };
    }
  }
  return null;
}

function labelOf(entry, profileVersion) {
  if (entry !== null) {
    const label = textOf(entry.label);
    if (label !== null && LABEL.test(label)) {
      return label;
    }
    const profile = countOf(entry.profile_version_number) ?? profileVersion;
    if (profile !== null) {
      return `${profile}.${countOf(entry.development_version_number) ?? 0}`;
    }
  }
  return profileVersion === null ? null : `${profileVersion}.0`;
}

function momentOf(value) {
  const moment = typeof value === "string" ? Date.parse(value) : Number.NaN;
  return Number.isNaN(moment) ? null : moment;
}

function latestObservations(entry) {
  const items = listOf(entry === null ? null : entry.observations)
    .filter(isObject)
    .map((observation, index) => ({
      observation,
      index,
      moment: momentOf(observation.approved_at),
    }));
  items.sort((left, right) => {
    if (
      left.moment !== null &&
      right.moment !== null &&
      left.moment !== right.moment
    ) {
      return right.moment - left.moment;
    }
    return right.index - left.index;
  });
  return items.slice(0, LATEST_LEARNED).map(({ observation }) => ({
    code: textOf(observation.code),
    statement: textOf(observation.statement),
    source: oneOf(observation.source, LEARNING_SOURCES),
    approvedAt: textOf(observation.approved_at),
  }));
}

function twinsOf(manifest, documents) {
  const learning = documents.learned.status === "OK";
  const entries = learning
    ? listOf(documents.learned.value.twins).filter(isObject)
    : [];
  let base = twinsFromSnapshot(documents.twins);
  if (base.length === 0) {
    base = twinsFromManifest(manifest);
  }
  if (base.length === 0) {
    base = twinsFromLearning(entries);
  }
  if (base.length === 0 && documents.twins.status !== "OK") {
    return emptyTwins(documents.twins.status);
  }
  const changeRuns =
    documents.changes.status === "OK"
      ? listOf(documents.changes.value.runs).filter(isObject)
      : [];
  const testRuns =
    documents.tests.status === "OK"
      ? listOf(documents.tests.value.runs).filter(isObject)
      : [];
  const items = base.map((twin) => {
    const entry =
      entries.find((item) =>
        twin.id !== null
          ? item.twin_id === twin.id
          : item.twin_name === twin.name,
      ) ?? null;
    const onCommit = latestCritique(changeRuns, twin);
    const onTest = latestCritique(testRuns, twin);
    const result = {
      id: twin.id,
      name: twin.name,
      profileVersion: twin.profileVersion,
      developmentVersion:
        entry === null ? null : countOf(entry.development_version_number),
      label: labelOf(entry, twin.profileVersion),
      learned:
        entry === null ? 0 : listOf(entry.observations).filter(isObject).length,
      observations: latestObservations(entry),
      commit:
        onCommit === null
          ? null
          : {
              verdict: onCommit.verdict,
              commit: textOf(onCommit.run.commit),
              reviewedAt: textOf(onCommit.run.reviewed_at),
            },
      test:
        onTest === null
          ? null
          : {
              verdict: onTest.verdict,
              runId: textOf(onTest.run.id),
              finishedAt: textOf(onTest.run.finished_at),
              reviewedAt: textOf(onTest.run.reviewed_at),
            },
    };
    const evidence = documents.evidence;
    if (
      evidence &&
      evidence.status === "OK" &&
      evidence.value.kind === "orchestwin.research-evidence" &&
      evidence.value.schema_version === 1
    ) {
      const sources = listOf(evidence.value.evidence).filter(isObject);
      result.evidence = listOf(evidence.value.citations)
        .filter(isObject)
        .filter((item) => item.twin_id === twin.id)
        .map((item) => {
          const citation = objectOf(item.citation);
          const source = sources.find(
            (entry) =>
              entry.id === citation.source_id &&
              entry.version === citation.source_version,
          );
          return {
            code: source ? textOf(source.code) : null,
            title: source ? textOf(source.title) : null,
            version: countOf(citation.source_version),
            status: textOf(item.status),
            effect: textOf(item.effect),
            field: textOf(item.field),
            quote: textOf(citation.quote),
            first: countOf(citation.start_line),
            last: countOf(citation.end_line),
            limitations: source ? textOf(source.limitations) : null,
          };
        });
    }
    return result;
  });
  return { available: true, problem: null, learning, items };
}

function agentOf(value) {
  if (typeof value === "string") {
    return textOf(value);
  }
  const agent = objectOf(value);
  return textOf(agent.name) ?? textOf(agent.label) ?? textOf(agent.program);
}

function codeOf(found) {
  if (found.status !== "OK") {
    return null;
  }
  const document = found.value;
  return {
    startedAt: textOf(document.started_at),
    finishedAt: textOf(document.finished_at),
    agent: agentOf(document.agent),
    exitStatus: Number.isInteger(document.exit_status)
      ? document.exit_status
      : textOf(document.exit_status),
    changedFiles: Array.isArray(document.changed_files)
      ? document.changed_files.length
      : null,
  };
}

function projectOf(link, knowledge) {
  return {
    id: textOf(link.project_id),
    name: textOf(link.project_name),
    language: textOf(link.language),
    mode: textOf(link.mode),
    knowledgeFolder: knowledge,
  };
}

function readLinkedProject(root) {
  const reader = createReader(root);
  const state = emptyState(root);
  const link = reader.read(LOCAL_FILES.link);
  if (link.status !== "OK") {
    state.notices = reader.notices;
    return state;
  }
  const knowledge = knowledgeFolderName(link.value.knowledge_folder);
  const inFolder = (name) => `${knowledge}/${name}`;
  state.linked = true;
  state.project = projectOf(link.value, knowledge);
  const manifest = reader.read(inFolder(FOLDER_FILES.manifest));
  state.folder = folderOf(manifest, knowledge);
  if (state.folder.available) {
    const documents = {
      state: reader.read(inFolder(FOLDER_FILES.state)),
      twins: reader.read(inFolder(FOLDER_FILES.twins)),
      changes: reader.read(inFolder(FOLDER_FILES.changes)),
      tests: reader.read(inFolder(FOLDER_FILES.tests)),
      learned: reader.read(inFolder(FOLDER_FILES.learned)),
      requirements: reader.read(inFolder(FOLDER_FILES.requirements)),
    };
    if (isObject(manifest.value.research_evidence)) {
      documents.evidence = reader.read(inFolder(FOLDER_FILES.evidence));
    }
    state.reference = referenceOf(documents.state);
    state.development = developmentOf(documents.state, manifest.value);
    state.tasks = tasksOf(documents.state);
    state.tests = testsOf(
      root,
      reader,
      documents,
      currentReference(state.reference),
    );
    state.twins = twinsOf(manifest.value, documents);
  } else {
    const problem = state.folder.problem;
    state.development = emptyDevelopment(problem);
    state.tasks = emptyTasks(problem);
    state.tests = emptyTests(problem);
    state.twins = emptyTwins(problem);
  }
  state.code = codeOf(reader.read(LOCAL_FILES.code));
  state.notices = reader.notices;
  return state;
}

function readProject(root) {
  if (typeof root !== "string" || root.trim() === "") {
    return emptyState(null);
  }
  try {
    return readLinkedProject(root);
  } catch {
    const state = emptyState(root);
    state.notices = [{ file: LOCAL_FILES.link, problem: "UNREADABLE" }];
    return state;
  }
}

module.exports = {
  FOLDER_FILES,
  KNOWLEDGE_FOLDER,
  LOCAL_FILES,
  STAGES,
  isStale,
  readProject,
};
