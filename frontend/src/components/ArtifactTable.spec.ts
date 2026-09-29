import { mount, type VueWrapper } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import ArtifactTable, { type ArtifactTableColumn } from "./ArtifactTable.vue";
import UiSurface from "./UiSurface.vue";
import { expectAccessible } from "@/test/axe";

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
});
