import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it, vi } from "vitest";

import ArtifactTable, { type ArtifactTableColumn } from "./ArtifactTable.vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import UiSurface from "./UiSurface.vue";
import { whyContextKey } from "./whyContext";
import { activitySignalKey } from "@/stores/activityJournal";
import { expectAccessible } from "@/test/axe";
import { whyAnswer, whyNode } from "@/test/whyFixtures";

const COLUMNS: ArtifactTableColumn[] = [
  { key: "code", label: "Code", sortable: true },
  { key: "title", label: "Title", sortable: true },
  { key: "note", label: "Note" },
  { key: "size", label: "Size", numeric: true },
];

const LONG_NOTE = "The first line is long enough to wrap inside the column\nSecond line";

const ROWS: Record<string, string>[] = [
  { code: "REQ-2", title: "book a room", note: LONG_NOTE, size: "12" },
  { code: "REQ-10", title: "Export the calendar", note: "", size: "3" },
  { code: "REQ-1", title: "Cancel a booking", note: "Short", size: "7" },
];

function mounted(
  rows: Record<string, string>[] = ROWS,
  locale: "en" | "it" = "en",
  columns: ArtifactTableColumn[] = COLUMNS,
  rowKey = "code",
) {
  return mount(ArtifactTable, {
    props: { caption: "Planned work", columns, rows, rowKey, locale },
    attachTo: document.body,
  });
}

const WHY_LOOK = [
  "rounded-field",
  "border",
  "border-current/15",
  "text-sm",
  "min-h-11",
  "px-3",
  "font-sans",
  "font-semibold",
];

function whyApi() {
  const explain = vi.fn((_project: string, code: string) => {
    const target = whyNode({ key: `REQUIREMENT:${code}`, code, title: `Reason for ${code}` });
    return Promise.resolve(whyAnswer(target));
  });
  return { explain, document: vi.fn() };
}

function whyContext(api: ReturnType<typeof whyApi>) {
  return {
    projectId: () => "project",
    api,
    authorize: <T>(request: (token: string) => Promise<T>) => request("token"),
  };
}

function whyMounted(locale: "en" | "it" = "en") {
  const api = whyApi();
  const signal = { whyOpened: vi.fn(), mockupOpened: vi.fn() };
  const wrapper = mount(ArtifactTable, {
    props: {
      caption: "Planned work",
      columns: COLUMNS,
      rows: ROWS,
      rowKey: "code",
      locale,
      why: true,
    },
    attachTo: document.body,
    global: {
      provide: {
        [whyContextKey as symbol]: whyContext(api),
        [activitySignalKey as symbol]: signal,
      },
    },
  });
  return { wrapper, api, signal };
}

function whyCommand(wrapper: VueWrapper, code: string) {
  return wrapper.get(`tr[data-row-key="${code}"] [data-testid="why-open"]`);
}

function whyRow(wrapper: VueWrapper, code: string) {
  return wrapper.get(`tr[data-why-row="${code}"]`);
}

function stripes(wrapper: VueWrapper): boolean[] {
  const rows = wrapper.findAll("tbody tr[data-row-key]");
  return rows.map((row) => row.classes().includes("bg-row-alt"));
}

function follows(first: Element, second: Element): boolean {
  return (first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
}

function itemKeys(wrapper: VueWrapper): (string | undefined)[] {
  return wrapper.findAll("tbody tr[data-row-key]").map((row) => row.attributes("data-row-key"));
}

function openWhyRows(wrapper: VueWrapper): (string | undefined)[] {
  const rows = wrapper.findAll('[data-testid="table-why-row"]');
  return rows.filter((row) => row.isVisible()).map((row) => row.attributes("data-why-row"));
}

function rowHeaders(wrapper: VueWrapper): string[] {
  return wrapper.findAll('tbody th[scope="row"]').map((cell) => cell.text());
}

function headerLabels(wrapper: VueWrapper): string[] {
  return wrapper.findAll("thead th").map((cell) => cell.text().replace(/[↑↓↕]/u, "").trim());
}

function sortStates(wrapper: VueWrapper): (string | undefined)[] {
  return wrapper.findAll("thead th").map((cell) => cell.attributes("aria-sort"));
}

describe("ArtifactTable", () => {
  it("renders the caption, the column headers and one row header per row", () => {
    const wrapper = mounted();
    const caption = wrapper.get("caption");

    expect(caption.text()).toBe("Planned work");
    expect(headerLabels(wrapper)).toEqual(["Code", "Title", "Note", "Size"]);
    expect(wrapper.findAll("thead th").every((cell) => cell.attributes("scope") === "col")).toBe(
      true,
    );
    expect(rowHeaders(wrapper)).toEqual(["REQ-2", "REQ-10", "REQ-1"]);
    expect(wrapper.findAll("tbody tr").map((row) => row.attributes("data-row-key"))).toEqual([
      "REQ-2",
      "REQ-10",
      "REQ-1",
    ]);
    expect(
      wrapper
        .findAll("tbody tr")[0]!
        .findAll("td")
        .map((cell) => cell.text()),
    ).toEqual(["book a room", LONG_NOTE, "12"]);
    expect(wrapper.get('tbody th[scope="row"]').classes()).toContain("whitespace-nowrap");
    expect(wrapper.get('tbody td[data-column="note"]').classes()).toEqual(
      expect.arrayContaining(["whitespace-pre-line", "min-w-44"]),
    );
    expect(wrapper.get('tbody td[data-column="title"]').classes()).toContain("whitespace-pre");
    expect(wrapper.get('tbody td[data-column="size"]').classes()).toEqual(
      expect.arrayContaining(["whitespace-nowrap", "text-right", "tabular-nums"]),
    );
    wrapper.unmount();
  });

  it("keeps short multi-line cells on their own lines without wrapping them", () => {
    const columns: ArtifactTableColumn[] = [
      { key: "code", label: "Code" },
      { key: "codes", label: "Linked" },
    ];
    const wrapper = mounted([{ code: "REQ-1", codes: "USR-001\nUSR-002" }], "en", columns);
    const cell = wrapper.get('td[data-column="codes"]');

    expect(cell.element.textContent).toBe("USR-001\nUSR-002");
    expect(cell.classes()).toContain("whitespace-pre");
    expect(cell.classes()).not.toContain("whitespace-pre-line");
    wrapper.unmount();
  });

  it("offers a scroll region that keyboard users can reach and that is named by the caption", () => {
    const wrapper = mounted();
    const region = wrapper.get('[role="region"]');

    expect(region.classes()).toContain("overflow-x-auto");
    expect(region.attributes("tabindex")).toBe("0");
    expect(region.attributes("aria-labelledby")).toBe(wrapper.get("caption").attributes("id"));
    (region.element as HTMLElement).focus();
    expect(document.activeElement).toBe(region.element);
    wrapper.unmount();
  });

  it("marks an empty cell with an em dash that assistive technology reads as empty", async () => {
    const wrapper = mounted();
    const dash = wrapper.findAll("tbody tr")[1]!.get('[role="img"]');

    expect(dash.text()).toBe("—");
    expect(dash.attributes("aria-label")).toBe("empty");

    await wrapper.setProps({ locale: "it" });

    expect(wrapper.findAll("tbody tr")[1]!.get('[role="img"]').attributes("aria-label")).toBe(
      "vuoto",
    );
    wrapper.unmount();
  });

  it("says how many rows are shown, in the singular and in the plural", async () => {
    const wrapper = mounted();
    const count = () => wrapper.get('[data-testid="artifact-table-count"]').text();

    expect(count()).toBe("3 rows");

    await wrapper.setProps({ rows: ROWS.slice(0, 1) });
    expect(count()).toBe("1 row");

    await wrapper.setProps({ locale: "it" });
    expect(count()).toBe("1 riga");

    await wrapper.setProps({ rows: ROWS });
    expect(count()).toBe("3 righe");
    wrapper.unmount();
  });

  it("replaces the table with a short text when there are no rows", async () => {
    const wrapper = mounted([]);

    expect(wrapper.find("table").exists()).toBe(false);
    expect(wrapper.find('[data-testid="artifact-table-count"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="artifact-table-empty"]').text()).toBe("Nothing to show yet.");

    await wrapper.setProps({ locale: "it" });
    expect(wrapper.get('[data-testid="artifact-table-empty"]').text()).toBe(
      "Ancora nulla da mostrare.",
    );

    await wrapper.setProps({ emptyText: "No risks were found." });
    expect(wrapper.get('[data-testid="artifact-table-empty"]').text()).toBe("No risks were found.");
    wrapper.unmount();
  });

  it("sorts ascending, then descending, then back to the original order", async () => {
    const wrapper = mounted();

    expect(sortStates(wrapper)).toEqual(["none", "none", undefined, undefined]);
    expect(wrapper.findAll("thead button").map((button) => button.attributes("type"))).toEqual([
      "button",
      "button",
    ]);

    await wrapper.get('[data-testid="sort-code"]').trigger("click");
    expect(sortStates(wrapper)).toEqual(["ascending", "none", undefined, undefined]);
    expect(rowHeaders(wrapper)).toEqual(["REQ-1", "REQ-2", "REQ-10"]);

    await wrapper.get('[data-testid="sort-code"]').trigger("click");
    expect(sortStates(wrapper)).toEqual(["descending", "none", undefined, undefined]);
    expect(rowHeaders(wrapper)).toEqual(["REQ-10", "REQ-2", "REQ-1"]);

    await wrapper.get('[data-testid="sort-code"]').trigger("click");
    expect(sortStates(wrapper)).toEqual(["none", "none", undefined, undefined]);
    expect(rowHeaders(wrapper)).toEqual(["REQ-2", "REQ-10", "REQ-1"]);

    await wrapper.get('[data-testid="sort-code"]').trigger("click");
    await wrapper.get('[data-testid="sort-title"]').trigger("click");
    expect(sortStates(wrapper)).toEqual(["none", "ascending", undefined, undefined]);
    expect(rowHeaders(wrapper)).toEqual(["REQ-2", "REQ-1", "REQ-10"]);
    wrapper.unmount();
  });

  it("orders a column by a hidden value when the column names one", async () => {
    const columns: ArtifactTableColumn[] = [
      { key: "code", label: "Code" },
      { key: "level", label: "Level", sortable: true, sortKey: "rank" },
    ];
    const rows = [
      { code: "A", level: "Could", rank: "3" },
      { code: "B", level: "Must", rank: "1" },
      { code: "C", level: "Should", rank: "2" },
    ];
    const wrapper = mounted(rows, "en", columns);

    await wrapper.get('[data-testid="sort-level"]').trigger("click");

    expect(rowHeaders(wrapper)).toEqual(["B", "C", "A"]);
    expect(wrapper.text()).not.toContain("rank");
    wrapper.unmount();
  });

  it("uses the first column as row header when the row key is not a shown column", () => {
    const columns: ArtifactTableColumn[] = [
      { key: "flow", label: "Flow" },
      { key: "step", label: "Step", numeric: true },
    ];
    const rows = [
      { key: "one:1", flow: "FLOW-001", step: "1" },
      { key: "two:1", flow: "FLOW-001", step: "1" },
    ];
    const wrapper = mounted(rows, "en", columns, "key");

    expect(rowHeaders(wrapper)).toEqual(["FLOW-001", "FLOW-001"]);
    expect(wrapper.findAll("tbody tr").map((row) => row.attributes("data-row-key"))).toEqual([
      "one:1",
      "two:1",
    ]);
    expect(wrapper.text()).not.toContain("one:1");
    wrapper.unmount();
  });

  it("keeps every line of a column on one line when the column asks for it", () => {
    const columns: ArtifactTableColumn[] = [
      { key: "code", label: "Code" },
      { key: "names", label: "Names", nowrap: true },
      { key: "note", label: "Note" },
    ];
    const wrapper = mounted(
      [
        {
          code: "REQ-1",
          names: "Volunteers at the lending desk\nLibrary readers",
          note: LONG_NOTE,
        },
      ],
      "en",
      columns,
    );

    expect(wrapper.get('td[data-column="names"]').classes()).toContain("whitespace-pre");
    expect(wrapper.get('td[data-column="names"]').classes()).not.toContain("min-w-36");
    expect(wrapper.get('td[data-column="note"]').classes()).toContain("whitespace-pre-line");
    wrapper.unmount();
  });

  it("writes a missing value in words and stresses the columns that ask for it", () => {
    const columns: ArtifactTableColumn[] = [
      { key: "code", label: "Code" },
      { key: "title", label: "Title", strong: true },
      { key: "check", label: "Check", missing: "Missing" },
    ];
    const wrapper = mounted(
      [
        { code: "REQ-1", title: "Book a room", check: "AC-1" },
        { code: "REQ-2", title: "", check: "" },
      ],
      "en",
      columns,
    );
    const checks = wrapper.findAll('td[data-column="check"]');

    expect(checks.map((cell) => cell.text())).toEqual(["AC-1", "Missing"]);
    expect(checks[1]!.get("[data-missing]").classes()).toContain("text-warn");
    expect(checks[1]!.find('[role="img"]').exists()).toBe(false);
    expect(wrapper.findAll('td[data-column="title"]')[0]!.classes()).toContain("font-semibold");
    expect(wrapper.findAll('td[data-column="title"]')[1]!.get('[role="img"]').text()).toBe("—");
    wrapper.unmount();
  });

  it("takes the colours of a dark surface", () => {
    const wrapper = mount({
      render: () =>
        h(UiSurface, { tone: "night" }, () =>
          h(ArtifactTable, {
            caption: "Planned work",
            columns: COLUMNS,
            rows: ROWS,
            rowKey: "code",
          }),
        ),
    });

    expect(wrapper.get('[data-testid="artifact-table"]').attributes("data-surface-context")).toBe(
      "night",
    );
    expect(wrapper.get('[role="region"]').classes()).toEqual(
      expect.arrayContaining(["bg-night-raised", "border-night-line", "rounded-tile"]),
    );
    expect(wrapper.get('tbody td[data-column="title"]').classes()).toContain("text-on-night");
    expect(wrapper.get("tbody tr").classes()).not.toContain("even:bg-row-alt");
    wrapper.unmount();
  });

  it("has no axe violations", async () => {
    const wrapper = mounted();

    await wrapper.get('[data-testid="sort-code"]').trigger("click");
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("keeps the label and the arrow of a sortable header together on one line", async () => {
    const wrapper = mounted();
    const sort = wrapper.get('[data-testid="sort-code"]');
    const path = () => sort.get("svg path").attributes("d");
    const hitArea = ["before:absolute", "before:-inset-y-3.5"];

    expect(sort.classes()).toEqual(
      expect.arrayContaining(["inline-flex", "items-center", "whitespace-nowrap", ...hitArea]),
    );
    expect(sort.text()).toBe("Code");
    expect(sort.get("svg").attributes("aria-hidden")).toBe("true");
    expect(sort.element.lastElementChild?.tagName.toLowerCase()).toBe("svg");

    const unsorted = path();
    await sort.trigger("click");
    const ascending = path();
    await sort.trigger("click");
    const descending = path();
    await sort.trigger("click");

    expect(new Set([unsorted, ascending, descending]).size).toBe(3);
    expect(path()).toBe(unsorted);
    wrapper.unmount();
  });

  it("puts a one-line Why command in the code cell with the look of the Why outside tables", async () => {
    const { wrapper, api } = whyMounted();
    const command = whyCommand(wrapper, "REQ-2");
    const outside = mount(ArtifactWhy, {
      props: { code: "REQ-2" },
      global: { provide: { [whyContextKey as symbol]: whyContext(api) } },
    });
    const look = [...WHY_LOOK, "bg-surface", "text-ink-2"];
    const oneLine = ["inline-flex", "whitespace-nowrap"];
    const outsideLook = [...outside.classes(), ...outside.get("summary").classes()];

    expect(command.element.tagName).toBe("BUTTON");
    expect(command.attributes("type")).toBe("button");
    expect(command.text()).toBe("Why?");
    expect(command.attributes("aria-label")).toBe("Why? book a room");
    expect(command.attributes("aria-expanded")).toBe("false");
    expect(command.classes()).toEqual(expect.arrayContaining([...look, ...oneLine]));
    expect(outsideLook).toEqual(expect.arrayContaining(look));
    expect(command.element.closest("th")?.getAttribute("scope")).toBe("row");
    expect(command.element.parentElement?.dataset.testid).toBe("table-why");
    expect(command.element.parentElement?.dataset.whyCode).toBe("REQ-2");

    const controlled = document.getElementById(command.attributes("aria-controls") ?? "");
    expect(controlled?.closest("tr")?.getAttribute("data-why-row")).toBe("REQ-2");
    expect(whyRow(wrapper, "REQ-2").isVisible()).toBe(false);
    expect(wrapper.find('[data-testid="why-content"]').exists()).toBe(false);
    expect(api.explain).not.toHaveBeenCalled();

    await wrapper.setProps({ locale: "it" });
    expect(command.text()).toBe("Perché?");
    expect(command.attributes("aria-label")).toBe("Perché? book a room");

    await wrapper.setProps({ why: false });
    expect(wrapper.find('[data-testid="why-open"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="table-why-row"]').exists()).toBe(false);
    outside.unmount();
    wrapper.unmount();
  });

  it("shows no Why command when nothing can explain the rows", () => {
    const wrapper = mount(ArtifactTable, {
      props: { caption: "Planned work", columns: COLUMNS, rows: ROWS, rowKey: "code", why: true },
    });
    const region = wrapper.get('[data-testid="artifact-table-region"]');

    expect(wrapper.find('[data-testid="why-open"]').exists()).toBe(false);
    expect(wrapper.findAll("tbody tr")).toHaveLength(ROWS.length);
    expect(region.classes()).not.toContain("@container");
    wrapper.unmount();
  });

  it("takes the colours of a dark surface for the Why command", () => {
    const api = whyApi();
    const wrapper = mount(
      {
        render: () =>
          h(UiSurface, { tone: "night" }, () =>
            h(ArtifactTable, {
              caption: "Planned work",
              columns: COLUMNS,
              rows: ROWS,
              rowKey: "code",
              why: true,
            }),
          ),
      },
      { global: { provide: { [whyContextKey as symbol]: whyContext(api) } } },
    );

    expect(wrapper.get('[data-testid="why-open"]').classes()).toEqual(
      expect.arrayContaining(["bg-night-panel", "text-on-night-2"]),
    );
    expect(stripes(wrapper)).toEqual([false, false, false]);
    wrapper.unmount();
  });

  it("opens the explanation in a full-width row under its item and closes it with the same command", async () => {
    const { wrapper, api } = whyMounted();
    const command = whyCommand(wrapper, "REQ-10");

    await command.trigger("click");
    await flushPromises();

    const item = wrapper.get('tr[data-row-key="REQ-10"]');
    const row = whyRow(wrapper, "REQ-10");
    const cell = row.get("td");
    const panel = row.get(`[id="${command.attributes("aria-controls")}"]`);
    const box = panel.get('[data-testid="table-why-panel"]');
    const region = wrapper.get('[data-testid="artifact-table-region"]');

    expect(command.attributes("aria-expanded")).toBe("true");
    expect(item.element.nextElementSibling).toBe(row.element);
    expect(row.isVisible()).toBe(true);
    expect(row.findAll("th, td")).toHaveLength(1);
    expect(cell.attributes("colspan")).toBe(String(COLUMNS.length));
    expect(cell.attributes("headers")).toBe(item.get('th[scope="row"]').attributes("id"));
    expect(panel.classes()).toEqual(expect.arrayContaining(["sticky", "left-0", "w-[100cqw]"]));
    expect(region.classes()).toContain("@container");
    expect(box.classes()).toEqual(expect.arrayContaining(["max-w-180", "break-words"]));
    expect(box.classes()).not.toContain("[overflow-wrap:anywhere]");
    expect(box.get('[data-testid="why-target-title"]').text()).toBe("Reason for REQ-10");
    expect(item.find('[data-testid="why-content"]').exists()).toBe(false);
    expect(api.explain).toHaveBeenCalledExactlyOnceWith("project", "REQ-10", "token");

    await command.trigger("click");

    expect(command.attributes("aria-expanded")).toBe("false");
    expect(row.isVisible()).toBe(false);

    await command.trigger("click");
    await flushPromises();

    expect(row.isVisible()).toBe(true);
    expect(box.get('[data-testid="why-target-title"]').text()).toBe("Reason for REQ-10");
    expect(api.explain).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("tells the study session the code once for every opening", async () => {
    const { wrapper, signal } = whyMounted();
    const command = whyCommand(wrapper, "REQ-2");

    await command.trigger("click");
    await flushPromises();
    await whyRow(wrapper, "REQ-2").get('[data-testid="why-details"]').trigger("toggle");

    expect(signal.whyOpened).toHaveBeenCalledExactlyOnceWith("REQ-2");

    await command.trigger("click");
    expect(signal.whyOpened).toHaveBeenCalledTimes(1);

    await command.trigger("click");
    await whyCommand(wrapper, "REQ-1").trigger("click");

    expect(signal.whyOpened.mock.calls).toEqual([["REQ-2"], ["REQ-2"], ["REQ-1"]]);
    expect(signal.mockupOpened).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps several explanations open at once, each under its own item", async () => {
    const { wrapper, api } = whyMounted();

    await whyCommand(wrapper, "REQ-2").trigger("click");
    await whyCommand(wrapper, "REQ-1").trigger("click");
    await flushPromises();

    expect(openWhyRows(wrapper)).toEqual(["REQ-2", "REQ-1"]);
    for (const code of ["REQ-2", "REQ-1"]) {
      const item = wrapper.get(`tr[data-row-key="${code}"]`);
      const title = whyRow(wrapper, code).get('[data-testid="why-target-title"]');
      expect(item.element.nextElementSibling).toBe(whyRow(wrapper, code).element);
      expect(title.text()).toBe(`Reason for ${code}`);
    }
    expect(api.explain.mock.calls.map((call) => call[1])).toEqual(["REQ-2", "REQ-1"]);

    const commands = wrapper.findAll('[data-testid="why-open"]');
    const controls = new Set(commands.map((command) => command.attributes("aria-controls")));
    expect(controls.size).toBe(ROWS.length);

    await whyCommand(wrapper, "REQ-2").trigger("click");

    expect(openWhyRows(wrapper)).toEqual(["REQ-1"]);
    wrapper.unmount();
  });

  it("keeps an open explanation under its item when the rows are sorted", async () => {
    const { wrapper, api } = whyMounted();

    await whyCommand(wrapper, "REQ-2").trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="sort-code"]').trigger("click");

    const item = wrapper.get('tr[data-row-key="REQ-2"]');
    const title = whyRow(wrapper, "REQ-2").get('[data-testid="why-target-title"]');

    expect(itemKeys(wrapper)).toEqual(["REQ-1", "REQ-2", "REQ-10"]);
    expect(item.element.nextElementSibling).toBe(whyRow(wrapper, "REQ-2").element);
    expect(openWhyRows(wrapper)).toEqual(["REQ-2"]);
    expect(title.text()).toBe("Reason for REQ-2");
    expect(stripes(wrapper)).toEqual([false, true, false]);
    expect(whyRow(wrapper, "REQ-2").classes()).toContain("bg-row-alt");
    expect(api.explain).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("opens and closes from the keyboard, keeps the focus on the command and reaches the explanation next", async () => {
    const { wrapper } = whyMounted("it");
    const command = whyCommand(wrapper, "REQ-2");

    (command.element as HTMLButtonElement).focus();
    expect(document.activeElement).toBe(command.element);

    await command.trigger("click");
    await flushPromises();

    const inside = whyRow(wrapper, "REQ-2").get('[data-testid="why-details"] > summary');
    const next = whyCommand(wrapper, "REQ-10");

    expect(command.attributes("aria-expanded")).toBe("true");
    expect(follows(command.element, inside.element)).toBe(true);
    expect(follows(inside.element, next.element)).toBe(true);

    await command.trigger("click");

    expect(command.attributes("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(command.element);
    wrapper.unmount();
  });

  it("stays a valid table without axe violations while explanations are open", async () => {
    const { wrapper } = whyMounted("it");

    await expectAccessible(wrapper.element);
    await whyCommand(wrapper, "REQ-2").trigger("click");
    await whyCommand(wrapper, "REQ-1").trigger("click");
    await flushPromises();

    expect(wrapper.findAll('tbody th[scope="row"]')).toHaveLength(ROWS.length);
    expect(wrapper.get('[data-testid="artifact-table-count"]').text()).toBe("3 righe");
    for (const row of wrapper.findAll('[data-testid="table-why-row"]')) {
      const cell = row.get("td");
      const header = wrapper.get(`th[id="${cell.attributes("headers")}"]`);
      expect(row.findAll("th, td")).toHaveLength(1);
      expect(cell.attributes("colspan")).toBe(String(COLUMNS.length));
      expect(header.attributes("scope")).toBe("row");
    }
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
