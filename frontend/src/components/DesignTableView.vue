<script setup lang="ts">
import { computed, useId } from "vue";

import ArtifactTable, { type ArtifactTableColumn } from "./ArtifactTable.vue";
import { useSurface } from "./UiSurface.vue";
import { choiceLabel, dimensionLabel } from "./visualLanguage";
import type {
  DeclarativePrototypePayload,
  DesignAlternativePayload,
  DesignPackagePayload,
  LayoutArchetype,
  UserTwinVersionReferencePayload,
} from "../types/design";
import type { RequirementsSpecificationPayload } from "../types/requirements";

type Locale = "en" | "it";

interface AlternativeColumn {
  id: string;
  code: string;
  title: string;
  chosen: boolean;
  recommended: boolean;
}

interface ComparisonCell {
  id: string;
  lines: string[];
}

interface ComparisonRow {
  key: string;
  label: string;
  list: boolean;
  cells: ComparisonCell[];
}

interface TransposedTable {
  key: string;
  title: string;
  description: string;
  corner: string;
  badges: boolean;
  columnClass: string;
  rows: ComparisonRow[];
}

interface TableSection {
  key: string;
  title: string;
  description: string;
  rowKey: string;
  columns: ArtifactTableColumn[];
  rows: Record<string, string>[];
}

const EM_DASH = "—";

const props = withDefaults(
  defineProps<{
    design: DesignPackagePayload;
    requirements?: RequirementsSpecificationPayload | null;
    locale?: Locale;
  }>(),
  { requirements: null, locale: "en" },
);

const palettes = {
  light: {
    title: "text-ink",
    text: "text-ink-2",
    muted: "text-ink-3",
    empty: "rounded-panel border-line-soft bg-surface-2 text-ink-2",
    region: "rounded-panel border-line bg-surface",
    head: "bg-surface-3",
    row: "border-line-soft even:bg-row-alt",
    cell: "text-ink-2",
    chosen: "border-ok-line bg-ok-bg text-ok-dark",
    recommended: "border-action-soft-line bg-action-soft text-action",
  },
  night: {
    title: "text-on-night",
    text: "text-on-night-2",
    muted: "text-on-night-3",
    empty: "rounded-tile border-night-line bg-night-raised text-on-night-2",
    region: "rounded-tile border-night-line bg-night-raised",
    head: "bg-on-night/3",
    row: "border-on-night/8",
    cell: "text-on-night",
    chosen: "border-petrol-on-night bg-petrol-on-night/16 text-petrol-on-night-2",
    recommended: "border-night-line-strong text-on-night-2",
  },
};

const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);

const messages = {
  en: {
    alternatives: {
      title: "Alternatives side by side",
      description:
        "Each column is one design alternative and each row compares the same aspect across them.",
    },
    visual: {
      title: "Visual choices",
      description:
        "The look picked from the style catalog for each alternative, one row per choice, named as in the catalog.",
    },
    workflows: {
      title: "Workflows",
      description: "The steps a person follows in each alternative, one row per step.",
    },
    screens: {
      title: "Screens and elements",
      description: "What each screen of the mockup contains, one row per element.",
    },
    transitions: {
      title: "Transitions",
      description: "How a person moves from one screen to the next and what happens then.",
    },
    concerns: {
      title: "Concerns",
      description: "Weak points found in the design and how to reduce them.",
    },
    aspect: "Aspect",
    choice: "Choice",
    chosen: "Chosen by you",
    recommended: "Recommended",
    summary: "Summary",
    layout: "Layout",
    productName: "Product name",
    why: "Why",
    advantages: "Advantages",
    tradeOffs: "Trade-offs",
    requirementsCovered: "Requirements covered",
    people: "People",
    workflowCodes: "Workflows",
    alternative: "Alternative",
    flow: "Flow",
    title: "Title",
    step: "Step",
    whatHappens: "What happens",
    requirements: "Requirements",
    screen: "Screen",
    state: "State",
    element: "Element",
    kind: "Kind",
    content: "Content",
    code: "Code",
    from: "From",
    to: "To",
    through: "Through",
    result: "Result",
    concern: "Concern",
    mitigation: "Mitigation",
    alternativeCodes: "Alternatives",
    empty: "Nothing to show yet.",
    emptyCell: "empty",
    states: {
      DEFAULT: "Default",
      EMPTY: "Empty",
      ERROR: "Error",
      SUCCESS: "Success",
    },
    kinds: {
      HEADING: "Heading",
      TEXT: "Text",
      TEXT_INPUT: "Text field",
      SELECT: "Choice",
      BUTTON: "Button",
      LINK: "Link",
      LIST: "List",
      CARD: "Card",
      STATUS: "Status",
    },
  },
  it: {
    alternatives: {
      title: "Alternative a confronto",
      description:
        "Ogni colonna è un'alternativa di design e ogni riga confronta lo stesso aspetto tra le alternative.",
    },
    visual: {
      title: "Scelte visive",
      description:
        "L'aspetto scelto dal catalogo degli stili per ogni alternativa, una riga per scelta.",
    },
    workflows: {
      title: "Flussi",
      description: "I passi che una persona segue in ogni alternativa, una riga per passo.",
    },
    screens: {
      title: "Schermate ed elementi",
      description: "Cosa contiene ogni schermata del mockup, una riga per elemento.",
    },
    transitions: {
      title: "Passaggi tra schermate",
      description: "Come si passa da una schermata all'altra e che cosa succede dopo.",
    },
    concerns: {
      title: "Criticità",
      description: "I punti deboli trovati nel design e come ridurli.",
    },
    aspect: "Aspetto",
    choice: "Scelta",
    chosen: "Scelta da te",
    recommended: "Consigliata",
    summary: "Sintesi",
    layout: "Impostazione",
    productName: "Nome del prodotto",
    why: "Perché",
    advantages: "Vantaggi",
    tradeOffs: "Compromessi",
    requirementsCovered: "Requisiti coperti",
    people: "Persone",
    workflowCodes: "Flussi",
    alternative: "Alternativa",
    flow: "Flusso",
    title: "Titolo",
    step: "Passo",
    whatHappens: "Cosa succede",
    requirements: "Requisiti",
    screen: "Schermata",
    state: "Stato",
    element: "Elemento",
    kind: "Tipo",
    content: "Contenuto",
    code: "Codice",
    from: "Da",
    to: "A",
    through: "Tramite",
    result: "Risultato",
    concern: "Criticità",
    mitigation: "Mitigazione",
    alternativeCodes: "Alternative",
    empty: "Ancora nulla da mostrare.",
    emptyCell: "vuoto",
    states: {
      DEFAULT: "Predefinito",
      EMPTY: "Vuoto",
      ERROR: "Errore",
      SUCCESS: "Successo",
    },
    kinds: {
      HEADING: "Titolo",
      TEXT: "Testo",
      TEXT_INPUT: "Campo di testo",
      SELECT: "Scelta",
      BUTTON: "Pulsante",
      LINK: "Link",
      LIST: "Elenco",
      CARD: "Scheda",
      STATUS: "Stato",
    },
  },
} as const;

const uid = useId();
const copy = computed(() => messages[props.locale]);

const requirementCodes = computed(
  () => new Map((props.requirements?.requirements ?? []).map((item) => [item.id, item.code])),
);

const alternativeCodes = computed(
  () => new Map(props.design.alternatives.map((alternative) => [alternative.id, alternative.code])),
);

const alternativeColumns = computed<AlternativeColumn[]>(() =>
  props.design.alternatives.map((alternative) => ({
    id: alternative.id,
    code: alternative.code,
    title: alternative.title,
    chosen: alternative.id === props.design.owner_selected_alternative_id,
    recommended: alternative.id === props.design.recommended_alternative_id,
  })),
);

const transposedTables = computed<TransposedTable[]>(() => {
  const text = copy.value;
  const tables: TransposedTable[] = [
    {
      key: "alternatives",
      ...text.alternatives,
      corner: text.aspect,
      badges: true,
      columnClass: "min-w-64",
      rows: comparisonRows(),
    },
  ];

  if (props.design.alternatives.some((alternative) => Boolean(alternative.visual_language))) {
    tables.push({
      key: "visual",
      ...text.visual,
      corner: text.choice,
      badges: false,
      columnClass: "min-w-80",
      rows: visualRows(),
    });
  }

  return tables;
});

const tableSections = computed<TableSection[]>(() => {
  const text = copy.value;
  const prototype = props.design.prototype;
  const sections: TableSection[] = [
    {
      key: "workflows",
      ...text.workflows,
      rowKey: "row",
      columns: [
        { key: "alternative", label: text.alternative },
        { key: "flow", label: text.flow },
        { key: "title", label: text.title },
        { key: "step", label: text.step, numeric: true },
        { key: "text", label: text.whatHappens },
        { key: "requirements", label: text.requirements },
      ],
      rows: workflowRows(),
    },
  ];

  if (prototype) {
    sections.push(
      {
        key: "screens",
        ...text.screens,
        rowKey: "row",
        columns: [
          { key: "screen", label: text.screen },
          { key: "title", label: text.title },
          { key: "state", label: text.state },
          { key: "element", label: text.element },
          { key: "kind", label: text.kind },
          { key: "content", label: text.content },
          { key: "requirements", label: text.requirements },
        ],
        rows: screenRows(prototype),
      },
      {
        key: "transitions",
        ...text.transitions,
        rowKey: "code",
        columns: [
          { key: "code", label: text.code },
          { key: "from", label: text.from },
          { key: "to", label: text.to },
          { key: "through", label: text.through },
          { key: "result", label: text.result },
        ],
        rows: transitionRows(prototype),
      },
    );
  }

  sections.push({
    key: "concerns",
    ...text.concerns,
    rowKey: "code",
    columns: [
      { key: "code", label: text.code },
      { key: "summary", label: text.concern },
      { key: "mitigation", label: text.mitigation },
      { key: "alternatives", label: text.alternativeCodes },
      { key: "requirements", label: text.requirements },
    ],
    rows: props.design.concerns.map((concern) => ({
      code: concern.code,
      summary: concern.summary,
      mitigation: concern.mitigation,
      alternatives: referenceCodes(concern.design_alternative_ids, alternativeCodes.value).join(
        "\n",
      ),
      requirements: requirementText(concern.requirement_ids),
    })),
  });

  return sections;
});

function comparisonRows(): ComparisonRow[] {
  const text = copy.value;
  const row = (
    key: string,
    label: string,
    list: boolean,
    lines: (alternative: DesignAlternativePayload) => readonly string[],
  ): ComparisonRow => ({
    key,
    label,
    list,
    cells: props.design.alternatives.map((alternative) => ({
      id: alternative.id,
      lines: lines(alternative).filter((line) => line.trim().length > 0),
    })),
  });

  return [
    row("summary", text.summary, false, (alternative) => [alternative.summary]),
    row("layout", text.layout, false, (alternative) =>
      alternative.visual_language
        ? [layoutLabel(alternative.visual_language.choices.archetype)]
        : [],
    ),
    row("product", text.productName, false, (alternative) => [
      alternative.visual_language?.product_name ?? "",
    ]),
    row("why", text.why, false, (alternative) => [alternative.rationale]),
    row("advantages", text.advantages, true, (alternative) => alternative.advantages),
    row("trade-offs", text.tradeOffs, true, (alternative) => alternative.trade_offs),
    row("requirements", text.requirementsCovered, true, (alternative) =>
      referenceCodes(alternative.requirement_ids, requirementCodes.value),
    ),
    row("people", text.people, true, (alternative) => twinNames(alternative.user_twin_references)),
    row("workflows", text.workflowCodes, true, (alternative) =>
      sortedCodes(alternative.workflows.map((workflow) => workflow.code)),
    ),
  ];
}

function visualRows(): ComparisonRow[] {
  const choices = props.design.alternatives.map((alternative) => ({
    id: alternative.id,
    values: new Map<string, string>(
      Object.entries(alternative.visual_language?.choices ?? {}).map(([dimension, value]) => [
        dimension,
        String(value),
      ]),
    ),
  }));
  const dimensions = [...new Set(choices.flatMap((entry) => [...entry.values.keys()]))];

  return dimensions.map((dimension) => ({
    key: dimension,
    label: dimensionLabel(props.locale, dimension),
    list: false,
    cells: choices.map((entry) => {
      const value = entry.values.get(dimension) ?? "";

      return {
        id: entry.id,
        lines: value.length === 0 ? [] : [choiceLabel(props.locale, dimension, value)],
      };
    }),
  }));
}

function workflowRows(): Record<string, string>[] {
  return props.design.alternatives.flatMap((alternative) =>
    alternative.workflows.flatMap((workflow) => {
      const shared = {
        alternative: alternative.code,
        flow: workflow.code,
        title: workflow.title,
        requirements: requirementText(workflow.requirement_ids),
      };

      if (workflow.steps.length === 0) {
        return [{ ...shared, row: `${alternative.code}:${workflow.code}:0`, step: "", text: "" }];
      }

      return workflow.steps.map((step, index) => ({
        ...shared,
        row: `${alternative.code}:${workflow.code}:${index + 1}`,
        step: String(index + 1),
        text: step,
      }));
    }),
  );
}

function screenRows(prototype: DeclarativePrototypePayload): Record<string, string>[] {
  const text = copy.value;

  return prototype.screens.flatMap((screen) => {
    const shared = { screen: screen.code, title: screen.title, state: text.states[screen.state] };

    if (screen.elements.length === 0) {
      return [
        {
          ...shared,
          row: screen.code,
          element: "",
          kind: "",
          content: "",
          requirements: requirementText(screen.requirement_ids),
        },
      ];
    }

    return screen.elements.map((element) => ({
      ...shared,
      row: `${screen.code}:${element.code}`,
      element: element.code,
      kind: text.kinds[element.kind],
      content: element.content,
      requirements: requirementText(element.requirement_ids),
    }));
  });
}

function transitionRows(prototype: DeclarativePrototypePayload): Record<string, string>[] {
  const screens = new Map(prototype.screens.map((screen) => [screen.id, screen]));
  const elements = new Map(
    prototype.screens.flatMap((screen) =>
      screen.elements.map((element) => [element.id, element] as const),
    ),
  );
  const screenLabel = (id: string): string => {
    const screen = screens.get(id);

    return screen === undefined ? EM_DASH : `${screen.code} · ${screen.title}`;
  };

  return prototype.transitions.map((transition) => {
    const trigger = elements.get(transition.trigger_element_id);

    return {
      code: transition.code,
      from: screenLabel(transition.source_screen_id),
      to: screenLabel(transition.target_screen_id),
      through: trigger === undefined ? EM_DASH : `${trigger.code} · ${trigger.content}`,
      result: transition.outcome,
    };
  });
}

function compareCodes(left: string, right: string): number {
  return left.localeCompare(right, props.locale, { numeric: true, sensitivity: "base" });
}

function sortedCodes(codes: readonly string[]): string[] {
  return [...new Set(codes)].sort(compareCodes);
}

function referenceCodes(ids: readonly string[], lookup: ReadonlyMap<string, string>): string[] {
  const known = ids.flatMap((id) => {
    const code = lookup.get(id);

    return code === undefined ? [] : [code];
  });
  const codes = sortedCodes(known);

  return known.length === ids.length ? codes : [...codes, EM_DASH];
}

function requirementText(ids: readonly string[]): string {
  return referenceCodes(ids, requirementCodes.value).join("\n");
}

function twinNames(references: readonly UserTwinVersionReferencePayload[]): string[] {
  return [...new Set(references.map((reference) => reference.name))];
}

function layoutLabel(archetype: LayoutArchetype): string {
  return choiceLabel(props.locale, "archetype", archetype);
}
</script>

<template>
  <div class="grid gap-8" data-testid="design-table-view" :data-surface-context="surface">
    <section
      v-for="table in transposedTables"
      :key="table.key"
      class="grid gap-3"
      :data-testid="`design-section-${table.key}`"
    >
      <div class="grid gap-1">
        <h4 :class="['m-0 text-base font-semibold tracking-block', palette.title]">
          {{ table.title }}
        </h4>
        <p :class="['m-0 text-sm leading-6', palette.text]">{{ table.description }}</p>
      </div>
      <p
        v-if="alternativeColumns.length === 0"
        :class="['m-0 border p-4 text-sm', palette.empty]"
        data-testid="design-table-empty"
      >
        {{ copy.empty }}
      </p>
      <div
        v-else
        :class="['overflow-x-auto border', palette.region]"
        role="region"
        tabindex="0"
        :aria-labelledby="`${uid}-${table.key}`"
        :data-testid="`design-table-${table.key}`"
      >
        <table class="w-full border-collapse text-left text-sm">
          <caption :id="`${uid}-${table.key}`" class="sr-only">
            {{
              table.title
            }}
          </caption>
          <thead :class="palette.head">
            <tr>
              <th
                scope="col"
                :class="[
                  'px-3 py-2.5 align-top text-[13px] font-semibold whitespace-nowrap',
                  palette.muted,
                ]"
              >
                {{ table.corner }}
              </th>
              <th
                v-for="column in alternativeColumns"
                :key="column.id"
                scope="col"
                class="px-3 py-2.5 align-top"
                :class="table.columnClass"
                :data-testid="`design-column-${column.code}`"
              >
                <span
                  :class="['block font-mono text-[11px] tracking-wide uppercase', palette.muted]"
                >
                  {{ column.code }}
                </span>
                <span :class="['mt-0.5 block text-[15px] leading-6 font-semibold', palette.title]">
                  {{ column.title }}
                </span>
                <span
                  v-if="table.badges && (column.chosen || column.recommended)"
                  class="mt-2 flex flex-wrap gap-1.5"
                >
                  <span
                    v-if="column.chosen"
                    :class="[
                      'rounded-pill border px-2.5 py-0.5 text-xs font-semibold',
                      palette.chosen,
                    ]"
                    data-testid="badge-chosen"
                  >
                    {{ copy.chosen }}
                  </span>
                  <span
                    v-if="column.recommended"
                    :class="[
                      'rounded-pill border px-2.5 py-0.5 text-xs font-semibold',
                      palette.recommended,
                    ]"
                    data-testid="badge-recommended"
                  >
                    {{ copy.recommended }}
                  </span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in table.rows"
              :key="row.key"
              :class="['border-t align-top', palette.row]"
              :data-testid="`design-row-${row.key}`"
            >
              <th
                scope="row"
                :class="['px-3 py-2.5 leading-6 font-semibold whitespace-nowrap', palette.title]"
              >
                {{ row.label }}
              </th>
              <td
                v-for="cell in row.cells"
                :key="cell.id"
                :class="['px-3 py-2.5 leading-6', palette.cell]"
              >
                <span v-if="cell.lines.length === 0" role="img" :aria-label="copy.emptyCell"
                  >—</span
                >
                <ul v-else-if="row.list" class="m-0 grid list-none gap-1 p-0">
                  <li v-for="(line, index) in cell.lines" :key="index">{{ line }}</li>
                </ul>
                <template v-else>{{ cell.lines[0] }}</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section
      v-for="section in tableSections"
      :key="section.key"
      class="grid gap-3"
      :data-testid="`design-section-${section.key}`"
    >
      <div class="grid gap-1">
        <h4 :class="['m-0 text-base font-semibold tracking-block', palette.title]">
          {{ section.title }}
        </h4>
        <p :class="['m-0 text-sm leading-6', palette.text]">{{ section.description }}</p>
      </div>
      <ArtifactTable
        :caption="section.title"
        :columns="section.columns"
        :rows="section.rows"
        :row-key="section.rowKey"
        :locale="locale"
      />
    </section>
  </div>
</template>
