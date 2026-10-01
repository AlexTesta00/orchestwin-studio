"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { after, before, describe, it } = require("node:test");
const fixtures = require("./fixtures");
const { costOf } = require("../src/commands");
const { plural, text } = require("../src/messages");
const { readProject } = require("../src/project");
const { escapeHtml, nextStep, renderPanel } = require("../src/view");

const NONCE = "0123456789abcdef0123456789abcdef";
const CSP_SOURCE = "https://file+.vscode-resource.vscode-cdn.net";
const LANGUAGES = ["en", "it"];
const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" };

function render(state, language, extra = {}) {
  return renderPanel(state, {
    language,
    nonce: NONCE,
    cspSource: CSP_SOURCE,
    timeZone: "UTC",
    ...extra,
  });
}

function decode(value) {
  return value.replace(/&(amp|lt|gt|quot|#39);/g, (entity) => ENTITIES[entity]);
}

function plain(html) {
  const visible = html
    .replace(/<script[\s\S]*?<\/script>/g, " ")
    .replace(/<style[\s\S]*?<\/style>/g, " ")
    .replace(/<\/?code>/g, "")
    .replace(/<[^>]+>/g, " ");
  return decode(visible).replace(/\s+/g, " ").trim();
}

function sentence(language, key, values) {
  return text(language, key, values).replace(/`/g, "");
}

function counted(language, key, count, values) {
  return plural(language, key, count, values).replace(/`/g, "");
}

function titles(html) {
  return [...html.matchAll(/<h2 id="[^"]+">([^<]*)<\/h2>/g)].map((match) => decode(match[1]));
}

function buttons(html) {
  return [
    ...html.matchAll(
      /<button type="button" class="([^"]*)" data-command="([^"]+)">([\s\S]*?)<\/button>/g,
    ),
  ].map((match) => ({
    primary: match[1].split(" ").includes("primary"),
    command: match[2],
    text: plain(match[3]),
  }));
}

function sectionTitles(language, keys) {
  return keys.map((key) => text(language, key));
}

describe("renderPanel", () => {
  let base;
  const states = {};

  before(() => {
    base = fixtures.makeTemporaryFolder();
    const at = (name) => path.join(base, name);
    states.complete = readProject(fixtures.writeCompleteProject(at("complete"), "new"));
    states.old = readProject(fixtures.writeCompleteProject(at("old"), "old"));
    states.partial = readProject(fixtures.writePartialProject(at("partial")));
    states.unlinked = readProject(fixtures.writeUnlinkedFolder(at("unlinked")));
    states.broken = readProject(fixtures.writeBrokenProject(at("broken")));
    states.none = readProject(null);
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  it("writes a whole document with one h1, in the language asked", () => {
    for (const state of Object.values(states)) {
      for (const language of LANGUAGES) {
        const html = render(state, language);
        assert.ok(html.startsWith("<!DOCTYPE html>\n"));
        assert.ok(html.includes(`<html lang="${language}">`));
        assert.equal(html.match(/<h1>/g).length, 1);
        assert.ok(html.trimEnd().endsWith("</html>"));
      }
    }
  });

  it("shows the sections that each state has", () => {
    const complete = [
      "next.title",
      "development.title",
      "tasks.title",
      "tests.title",
      "twins.title",
      "agents.title",
    ];
    for (const language of LANGUAGES) {
      assert.deepEqual(
        titles(render(states.complete, language)),
        sectionTitles(language, complete),
      );
      assert.deepEqual(titles(render(states.old, language)), sectionTitles(language, complete));
      assert.deepEqual(titles(render(states.broken, language)), sectionTitles(language, complete));
      assert.deepEqual(
        titles(render(states.partial, language)),
        sectionTitles(language, ["next.title", "development.title", "twins.title", "agents.title"]),
      );
      assert.deepEqual(titles(render(states.unlinked, language)), [text(language, "next.title")]);
      assert.deepEqual(titles(render(states.none, language)), [text(language, "next.title")]);
    }
  });

  it("says where a complete project stands", () => {
    for (const language of LANGUAGES) {
      const page = plain(render(states.complete, language));
      const expected = [
        "Tip calculator for waiters",
        sentence(language, "header.folderPublished", { version: 12, date: "" }).replace(/\s+$/, ""),
        counted(language, "next.recheck", 1),
        `${text(language, "development.stale")} 1 · 3c3d3e3`,
        `${text(language, "development.pending")} 2`,
        `${text(language, "development.aligned")} 1a1b1c1 · `,
        `${text(language, "verdict.CODE_DRIFT")} ${text(language, "chip.stale")}`,
        [
          counted(language, "tasks.open", 3),
          counted(language, "tasks.done", 1),
          counted(language, "tasks.dropped", 1),
        ].join(" · "),
        "Keep the chosen percentage selected after New calculation, as in the approved design.",
        sentence(language, "origin.twinCommit", { twin: "Head waiter", commit: "2b2c2d2" }),
        counted(language, "origin.twinTestCriteria", 1, {
          twin: "Seasonal waiters",
          criteria: "AC-003",
        }),
        text(language, "origin.owner"),
        `${text(language, "code.outcome")} ${text(language, "code.exitOk")}`,
        `${text(language, "code.agent")} ${text(language, "code.agent.claude")}`,
        `${text(language, "code.files")} 3`,
        `${text(language, "tests.browsers")} Chrome 151 · Firefox 157`,
        counted(language, "tests.PASSED", 3),
        counted(language, "tests.FAILED", 1),
        counted(language, "tests.BLOCKED", 1),
        counted(language, "tests.NOT_COVERED", 1),
        counted(language, "tests.NOT_RUN", 0),
        `AC-003 ${text(language, "status.FAILED")} ${fixtures.STATEMENTS["AC-003"]}`,
        `AC-004 ${text(language, "status.BLOCKED")} ${fixtures.STATEMENTS["AC-004"]}`,
        `Head waiter ${text(language, "critique.CONCERN")}`,
        `Seasonal waiters ${text(language, "critique.DRIFT")}`,
        `Head waiter ${text(language, "twins.version", { label: "1.3" })}`,
        `Seasonal waiters ${text(language, "twins.version", { label: "1.0" })}`,
        counted(language, "twins.learned", 4),
        text(language, "twins.learnedNone"),
        `OBS-005 Asks the waiters to check the tip before showing it to the guests. · ${text(language, "source.OWNER")}`,
        `${sentence(language, "twins.onCommit", { commit: "3c3d3e3" })} ${text(language, "critique.DRIFT")}`,
        sentence(language, "agents.intro"),
        text(language, "agents.MISSING"),
        sentence(language, "footer.note"),
      ];
      for (const item of expected) {
        assert.ok(page.includes(item), `${language}: ${item}`);
      }
      assert.ok(!page.includes("OBS-001"), "only the three newest observations");
      assert.ok(!page.includes(sentence(language, "tests.local")));
    }
  });

  it("writes dates in the words of each language", () => {
    const english = plain(render(states.complete, "en"));
    const italian = plain(render(states.complete, "it"));
    assert.ok(english.includes("Latest run 30 Sep 2026, 09:05"));
    assert.ok(english.includes("Reviewed by the twins on 30 Sep 2026, 09:06"));
    assert.ok(english.includes("On the test run of 30 Sep 2026"));
    assert.ok(italian.includes("Ultima verifica 30 set 2026, 09:05"));
    assert.ok(italian.includes("Commentata dai twin il 30 set 2026, 09:06"));
    assert.ok(italian.includes("Sulla verifica del 30 set 2026"));
  });

  it("keeps the Italian page free of English sentences", () => {
    const italian = plain(render(states.complete, "it"));
    for (const key of [
      "next.title",
      "development.title",
      "tasks.title",
      "tests.title",
      "agents.title",
      "cost.SPENDS",
      "origin.owner",
      "footer.note",
    ]) {
      assert.ok(!italian.includes(sentence("en", key)), key);
    }
  });

  it("reads the shapes of sprint 27 without flags or learning", () => {
    for (const language of LANGUAGES) {
      const page = plain(render(states.old, language));
      assert.ok(page.includes(counted(language, "next.code", 2)));
      assert.ok(page.includes(sentence(language, "origin.verdictCommit", { commit: "2b2c2d2" })));
      assert.ok(page.includes(sentence(language, "origin.verdictCommit", { commit: "3c3d3e3" })));
      assert.ok(!page.includes(`${text(language, "development.stale")} `));
      assert.ok(page.includes(`Head waiter ${text(language, "twins.version", { label: "1.0" })}`));
      assert.ok(!page.includes(text(language, "code.title")));
    }
  });

  it("shortens long lists and names what is left out", () => {
    const state = structuredClone(states.complete);
    const [task] = state.tasks.open;
    state.tasks.open = Array.from({ length: 10 }, (_, index) => ({
      ...task,
      code: `TSK-${String(index + 10).padStart(3, "0")}`,
    }));
    const [problem] = state.tests.latest.problems;
    state.tests.latest.problems = Array.from({ length: 8 }, (_, index) => ({
      ...problem,
      code: `AC-${String(index + 10).padStart(3, "0")}`,
    }));
    for (const language of LANGUAGES) {
      const page = plain(render(state, language));
      assert.ok(page.includes("TSK-017"));
      assert.ok(!page.includes("TSK-018"));
      assert.ok(page.includes(counted(language, "tasks.more", 2)));
      assert.ok(page.includes("AC-015"));
      assert.ok(!page.includes("AC-016"));
      assert.ok(page.includes(counted(language, "tests.moreProblems", 2)));
    }
  });

  it("says when the latest run is only on this computer or was made on an earlier design", () => {
    const state = structuredClone(states.complete);
    state.tests.latest.source = "LOCAL";
    state.tests.latest.stale = true;
    state.tests.latest.reviewed = false;
    state.tests.latest.critiques = [];
    state.tests.report = null;
    for (const language of LANGUAGES) {
      const html = render(state, language);
      const page = plain(html);
      assert.ok(page.includes(text(language, "tests.local")));
      assert.ok(page.includes(text(language, "tests.stale")));
      assert.ok(page.includes(text(language, "tests.notReviewed")));
      assert.ok(!buttons(html).some((button) => button.command === "openReport"));
    }
  });

  it("describes the latest work of the coding agent in words", () => {
    const state = structuredClone(states.complete);
    state.code = {
      startedAt: "2026-09-30T08:10:00+00:00",
      finishedAt: null,
      agent: "custom",
      exitStatus: 2,
      changedFiles: null,
    };
    for (const language of LANGUAGES) {
      const page = plain(render(state, language));
      assert.ok(page.includes(`${text(language, "code.when")} 30 `));
      assert.ok(
        page.includes(`${text(language, "code.agent")} ${text(language, "code.agent.custom")}`),
      );
      assert.ok(
        page.includes(
          `${text(language, "code.outcome")} ${text(language, "code.exitStatus", { status: 2 })}`,
        ),
      );
      assert.ok(!page.includes(text(language, "code.files")));
    }
    state.code = {
      startedAt: null,
      finishedAt: null,
      agent: null,
      exitStatus: null,
      changedFiles: null,
    };
    assert.ok(!plain(render(state, "en")).includes(text("en", "code.title")));
  });

  it("says that the development starts after the design in a partial folder", () => {
    for (const language of LANGUAGES) {
      const page = plain(render(states.partial, language));
      assert.ok(page.includes(text(language, "header.partial")));
      assert.ok(page.includes(text(language, "development.notYet")));
      assert.ok(page.includes(sentence(language, "twins.notYet")));
      assert.ok(
        page.includes(sentence(language, "next.init", { stage: text(language, "stage.team") })),
      );
      assert.ok(
        page.includes(`${text(language, "stage.brief")} , ${text(language, "stage.approved")}`),
      );
      assert.ok(
        page.includes(`${text(language, "stage.design")} , ${text(language, "stage.pending")}`),
      );
    }
  });

  it("names the steps as the Studio names them", () => {
    const names = {
      en: ["Brief", "Perspectives", "User Twin", "Definition", "Design & Evaluation"],
      it: ["Brief", "Prospettive", "User Twin", "Definizione", "Design e valutazione"],
    };
    for (const language of LANGUAGES) {
      const html = render(states.partial, language);
      const list = html.match(/<ol class="steps"[^>]*>([\s\S]*?)<\/ol>/)[1];
      const shown = [...list.matchAll(/<span>([^<]*)<\/span>/g)].map((match) => decode(match[1]));
      assert.deepEqual(shown, names[language]);
      assert.ok(
        plain(html).includes(sentence(language, "next.init", { stage: names[language][1] })),
      );
    }
  });

  it("names a broken file and says that its parts are not available", () => {
    for (const language of LANGUAGES) {
      const page = plain(render(states.broken, language));
      assert.ok(
        page.includes(
          sentence(language, "notice.INVALID_JSON", { file: "orchestwin/state/state.json" }),
        ),
      );
      assert.equal(page.split(sentence(language, "part.unavailable")).length - 1, 2);
      assert.ok(page.includes(sentence(language, "next.folderBroken")));
    }
  });

  it("tells a folder that is not linked to launch ut init, without buttons", () => {
    for (const language of LANGUAGES) {
      const html = render(states.unlinked, language);
      assert.ok(plain(html).includes(sentence(language, "next.notLinked")));
      assert.deepEqual(buttons(html), []);
      const empty = render(states.none, language);
      assert.ok(plain(empty).includes(sentence(language, "next.noFolder")));
      assert.deepEqual(buttons(empty), []);
    }
  });

  it("puts real buttons with their command in every section", () => {
    const expected = {
      complete: [
        "recheck",
        "align",
        "recheck",
        "code",
        "tasks",
        "test",
        "openReport",
        "twinsUpdate",
        "connectAgents",
        "status",
      ],
      old: [
        "code",
        "align",
        "code",
        "tasks",
        "test",
        "openReport",
        "twinsUpdate",
        "connectAgents",
        "status",
      ],
      partial: ["init", "connectAgents", "status"],
      broken: ["publish", "test", "openReport", "twinsUpdate", "connectAgents", "status"],
      unlinked: [],
      none: [],
    };
    for (const [name, commands] of Object.entries(expected)) {
      for (const language of LANGUAGES) {
        const html = render(states[name], language);
        const found = buttons(html);
        assert.deepEqual(
          found.map((button) => button.command),
          commands,
          `${name} ${language}`,
        );
        assert.equal(
          found.filter((button) => button.primary).length,
          commands.length === 0 ? 0 : 1,
        );
        assert.equal(html.match(/<button/g)?.length ?? 0, commands.length);
      }
    }
  });

  it("says next to every button whether it may spend", () => {
    for (const state of Object.values(states)) {
      for (const language of LANGUAGES) {
        for (const button of buttons(render(state, language))) {
          const cost = costOf(button.command);
          if (cost === null) {
            assert.ok(button.text.includes(text(language, `detail.${button.command}`)));
            assert.ok(!button.text.includes(text(language, "cost.SPENDS")));
          } else {
            assert.ok(button.text.includes(text(language, `cost.${cost}`)), button.command);
          }
          if (
            ["test", "align", "recheck", "twinsUpdate", "init", "design"].includes(button.command)
          ) {
            assert.equal(cost, "SPENDS");
          }
        }
      }
    }
  });

  it("escapes every text that comes from a file", () => {
    const state = structuredClone(states.complete);
    state.folder.name = "<b>Tip</b> & co";
    state.tasks.open[0].text = '<script>alert("task")</script>';
    state.twins.items[0].name = '"Head" <waiter>';
    state.tests.latest.problems[0].statement = "<img src=x onerror=alert(1)>";
    state.notices = [{ file: "orchestwin/<x>.json", problem: "INVALID_JSON" }];
    const html = render(state, "en", { status: "<i>sent</i>" });
    assert.ok(!html.includes("<script>alert"));
    assert.ok(!html.includes("<b>Tip</b>"));
    assert.ok(!html.includes("<img"));
    assert.ok(!html.includes("<waiter>"));
    assert.ok(!html.includes("<i>sent</i>"));
    assert.ok(html.includes("&lt;script&gt;alert(&quot;task&quot;)&lt;/script&gt;"));
    assert.ok(html.includes("&lt;b&gt;Tip&lt;/b&gt; &amp; co"));
    assert.ok(html.includes("&quot;Head&quot; &lt;waiter&gt;"));
    assert.ok(html.includes("orchestwin/&lt;x&gt;.json"));
    assert.equal(html.match(/<script/g).length, 1);
    assert.equal(
      escapeHtml(`<a href="x">'&'</a>`),
      "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;",
    );
  });

  it("holds the content security policy with one nonce for the style and the script", () => {
    for (const state of Object.values(states)) {
      for (const language of LANGUAGES) {
        const html = render(state, language);
        assert.ok(
          html.includes(
            `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${NONCE}'; script-src 'nonce-${NONCE}';">`,
          ),
        );
        const nonces = [...html.matchAll(/nonce="([^"]*)"/g)].map((match) => match[1]);
        assert.deepEqual(nonces, [NONCE, NONCE]);
        assert.equal(html.match(/<style nonce=/g).length, 1);
        assert.equal(html.match(/<script nonce=/g).length, 1);
        assert.ok(!/\sstyle="/.test(html));
        assert.ok(!/\son[a-z]+="/.test(html));
      }
    }
  });

  it("loads nothing and names no external address", () => {
    for (const state of Object.values(states)) {
      for (const language of LANGUAGES) {
        const html = render(state, language);
        assert.ok(!/https?:/i.test(html));
        assert.ok(!html.includes("vscode-cdn"));
        assert.ok(!/\s(src|href|srcset|action)=/i.test(html));
        assert.ok(!/url\(/i.test(html));
        assert.ok(!/@import/i.test(html));
      }
    }
  });

  it("has a polite status region with the latest message", () => {
    const html = render(states.complete, "en", { status: "Written in the terminal: ut test" });
    assert.ok(
      html.includes(
        '<p id="status" class="status" role="status" aria-live="polite">Written in the terminal: ut test</p>',
      ),
    );
    assert.ok(
      render(states.none, "it").includes(
        '<p id="status" class="status" role="status" aria-live="polite"></p>',
      ),
    );
  });

  it("sends only the command of the pressed button from its script", () => {
    const html = render(states.complete, "en");
    const script = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1];
    assert.ok(script.includes('closest("button[data-command]")'));
    assert.ok(script.includes('api.postMessage({ command: target.getAttribute("data-command") })'));
    assert.ok(script.includes('typeof acquireVsCodeApi === "function"'));
  });

  it("never throws, whatever it is given", () => {
    for (const odd of [undefined, null, {}, { root: 5 }, { root: "x", linked: true }, []]) {
      const html = renderPanel(odd, { language: "it", nonce: NONCE });
      assert.ok(html.includes("</html>"));
    }
    for (const options of [undefined, null, "it", { language: 3, nonce: 7 }]) {
      assert.ok(renderPanel(states.complete, options).includes('<html lang="en">'));
    }
    const broken = render({ root: "x", linked: true, folder: { available: true } }, "en");
    assert.ok(plain(broken).includes(sentence("en", "panel.error")));
  });
});

describe("nextStep", () => {
  let base;
  let complete;

  before(() => {
    base = fixtures.makeTemporaryFolder();
    complete = readProject(fixtures.writeCompleteProject(path.join(base, "complete"), "new"));
  });

  after(() => {
    fixtures.removeFolder(base);
  });

  function changed(change) {
    const state = structuredClone(complete);
    change(state);
    return state;
  }

  function step(state) {
    const found = nextStep(state);
    return [found.kind, found.command, found.count];
  }

  it("follows the order of the specification", () => {
    const noStale = (state) => {
      state.development.stale = 0;
    };
    const noTasks = (state) => {
      noStale(state);
      state.tasks.open = [];
    };
    const noProblems = (state) => {
      noTasks(state);
      state.tests.latest.summary.failed = 0;
      state.tests.latest.summary.blocked = 0;
    };
    const noPending = (state) => {
      noProblems(state);
      state.development.pending = 0;
    };
    assert.deepEqual(step(complete), ["RECHECK", "recheck", 1]);
    assert.deepEqual(step(changed(noStale)), ["CODE", "code", 3]);
    assert.deepEqual(step(changed(noTasks)), ["TASKS_FROM_TEST", "tasksFromTest", 2]);
    assert.deepEqual(step(changed(noProblems)), ["ALIGN", "align", 2]);
    assert.deepEqual(step(changed(noPending)), ["TEST", "test", null]);
    assert.deepEqual(
      step(
        changed((state) => {
          noPending(state);
          state.tests.latest = null;
        }),
      ),
      ["FIRST_TEST", "test", null],
    );
  });

  it("asks first for what the development needs before it starts", () => {
    assert.deepEqual(step(readProject(null)), ["NO_FOLDER", null, null]);
    assert.deepEqual(step(changed((state) => (state.linked = false))), ["NOT_LINKED", null, null]);
    assert.deepEqual(
      step(
        changed((state) => {
          state.folder.available = false;
          state.folder.problem = "MISSING";
        }),
      ),
      ["FOLDER_MISSING", "status", null],
    );
    assert.deepEqual(
      step(
        changed((state) => {
          state.folder.available = false;
          state.folder.problem = "INVALID";
        }),
      ),
      ["FOLDER_BROKEN", "publish", null],
    );
    assert.deepEqual(
      step(
        changed((state) => (state.folder.approved = ["brief", "team", "twins", "requirements"])),
      ),
      ["DESIGN", "design", null],
    );
    const init = nextStep(changed((state) => (state.folder.approved = ["brief", "team"])));
    assert.deepEqual([init.kind, init.command, init.stage], ["INIT", "init", "twins"]);
    assert.deepEqual(step(changed((state) => (state.development.available = false))), [
      "FOLDER_BROKEN",
      "publish",
      null,
    ]);
    assert.deepEqual(step(changed((state) => (state.tests.available = false))), [
      "FOLDER_BROKEN",
      "publish",
      null,
    ]);
  });

  it("puts the command of the next step on the first, primary button", () => {
    for (const language of LANGUAGES) {
      const state = changed((item) => {
        item.development.stale = 0;
        item.tasks.open = [];
      });
      const html = render(state, language);
      assert.ok(html.includes('data-step="TASKS_FROM_TEST"'));
      const [first] = buttons(html);
      assert.deepEqual([first.command, first.primary], ["tasksFromTest", true]);
      assert.ok(first.text.includes("ut tasks from-test"));
      assert.ok(plain(html).includes(counted(language, "next.tasksFromTest", 2)));
    }
  });
});
