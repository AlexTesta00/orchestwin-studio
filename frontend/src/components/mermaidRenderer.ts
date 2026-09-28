export interface DiagramRenderer {
  render(id: string, source: string): Promise<string>;
}

interface MermaidModule {
  initialize(configuration: Record<string, unknown>): void;
  render(id: string, source: string, container?: Element): Promise<{ svg: string }>;
}

export type MermaidLoader = () => Promise<{ default: MermaidModule }>;

export const DIAGRAM_SANDBOX_ATTRIBUTE = "data-diagram-sandbox";

const DIAGRAM_FONT = '"Libre Franklin", ui-sans-serif, system-ui, sans-serif';

export const MERMAID_CONFIGURATION = {
  startOnLoad: false,
  securityLevel: "strict",
  theme: "base",
  fontFamily: DIAGRAM_FONT,
  flowchart: { useMaxWidth: false, htmlLabels: true },
  state: { useMaxWidth: false },
  requirement: { useMaxWidth: false },
  usecase: {
    useMaxWidth: false,
    actorFontFamily: DIAGRAM_FONT,
    usecaseFontFamily: DIAGRAM_FONT,
  },
  themeVariables: {
    fontSize: "14px",
    primaryColor: "#edf2fb",
    primaryBorderColor: "#0a5fba",
    primaryTextColor: "#1c1c1e",
    secondaryColor: "#f7f7fa",
    secondaryBorderColor: "#c9c9d1",
    secondaryTextColor: "#1c1c1e",
    tertiaryColor: "#ffffff",
    tertiaryBorderColor: "#dedee4",
    tertiaryTextColor: "#1c1c1e",
    lineColor: "#48484f",
    textColor: "#1c1c1e",
    mainBkg: "#edf2fb",
    nodeBorder: "#0a5fba",
    clusterBkg: "#f7f7fa",
    clusterBorder: "#dedee4",
    edgeLabelBackground: "#ffffff",
    titleColor: "#1c1c1e",
  },
} as const;

const defaultLoader: MermaidLoader = () =>
  import("mermaid") as unknown as Promise<{ default: MermaidModule }>;

function diagramSandbox(): HTMLElement {
  const existing = document.querySelector<HTMLElement>(`[${DIAGRAM_SANDBOX_ATTRIBUTE}]`);

  if (existing !== null) {
    return existing;
  }

  const element = document.createElement("div");
  element.setAttribute(DIAGRAM_SANDBOX_ATTRIBUTE, "");
  element.setAttribute("aria-hidden", "true");
  document.body.append(element);
  return element;
}

export function createMermaidRenderer(loader: MermaidLoader = defaultLoader): DiagramRenderer {
  let ready: Promise<MermaidModule> | null = null;
  let queue: Promise<unknown> = Promise.resolve();

  function mermaid(): Promise<MermaidModule> {
    ready ??= loader()
      .then((module) => {
        module.default.initialize({ ...MERMAID_CONFIGURATION });
        return module.default;
      })
      .catch((error: unknown) => {
        ready = null;
        throw error;
      });
    return ready;
  }

  return {
    render(id, source) {
      const result = queue.then(async () => {
        const engine = await mermaid();
        const { svg } = await engine.render(id, source, diagramSandbox());
        return svg;
      });
      queue = result.catch(() => undefined);
      return result;
    },
  };
}

export const mermaidRenderer = createMermaidRenderer();
