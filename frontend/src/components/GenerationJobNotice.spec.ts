import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import GenerationJobNotice from "./GenerationJobNotice.vue";
import type { GenerationRequestJob } from "../api/generationJobs";
import { expectAccessible } from "../test/axe";

const STARTED_AT = "2026-09-28T10:00:00+00:00";

function job(overrides: Partial<GenerationRequestJob> = {}): GenerationRequestJob {
  return {
    job_id: "00000000-0000-4000-8000-0000000000aa",
    kind: "REQUEST",
    operation: "REQUIREMENTS_PROPOSAL",
    status: "RUNNING",
    stage: "GENERATING",
    attempt: 1,
    started_at: STARTED_AT,
    finished_at: null,
    alternative_id: null,
    failure: null,
    response: null,
    ...overrides,
  };
}

describe("GenerationJobNotice", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("says what is being generated, since when, and that the page can be left", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(Date.parse(STARTED_AT) + 5000));
    const wrapper = mount(GenerationJobNotice, { props: { job: job(), locale: "it" } });

    const notice = wrapper.get("[data-testid='generation-job-notice']");
    expect(notice.attributes("data-operation")).toBe("REQUIREMENTS_PROPOSAL");
    expect(wrapper.get("[role='status']").text()).toBe("Lo Studio sta generando i requisiti.");
    expect(wrapper.get("[data-testid='generation-job-since']").text()).toMatch(
      /^Iniziata alle .+, pochi secondi fa\.$/,
    );
    expect(notice.text()).toContain(
      "Puoi lasciare questa pagina e tornare più tardi: la generazione continua",
    );

    await vi.advanceTimersByTimeAsync(40_000);
    expect(wrapper.get("[data-testid='generation-job-since']").text()).toMatch(/45 secondi fa\.$/);

    await vi.advanceTimersByTimeAsync(80_000);
    expect(wrapper.get("[data-testid='generation-job-since']").text()).toMatch(/2 minuti fa\.$/);
    wrapper.unmount();
  });

  it("names every operation in plain English words", () => {
    const wrapper = mount(GenerationJobNotice, {
      props: { job: job({ operation: "DESIGN_EVALUATION" }), locale: "en" },
    });

    expect(wrapper.get("[role='status']").text()).toBe(
      "The Studio is generating the twins' review of the design.",
    );
    expect(wrapper.text()).toContain("You can leave this page and come back later");
  });

  it("names the review of a commit started from the terminal in both languages", () => {
    const english = mount(GenerationJobNotice, {
      props: { job: job({ operation: "CODE_CHANGE_REVIEW" }), locale: "en" },
    });
    const italian = mount(GenerationJobNotice, {
      props: {
        job: null,
        failure: { operation: "CODE_CHANGE_REVIEW", code: "PROVIDER_UNAVAILABLE", lost: false },
        locale: "it",
      },
    });

    expect(english.get("[data-testid='generation-job-notice']").attributes("data-operation")).toBe(
      "CODE_CHANGE_REVIEW",
    );
    expect(english.get("[role='status']").text()).toBe(
      "The Studio is generating the twins' review of a commit.",
    );
    expect(italian.get("[data-testid='generation-job-failure']").text()).toContain(
      "La generazione della revisione dei twin su un commit non è riuscita.",
    );
    english.unmount();
    italian.unmount();
  });

  it("says in plain words that an interrupted generation can be started again", async () => {
    const wrapper = mount(GenerationJobNotice, {
      props: {
        job: null,
        failure: { operation: "DESIGN_PROPOSAL", code: "GENERATION_JOB_NOT_FOUND", lost: true },
        locale: "it",
      },
    });

    const failure = wrapper.get("[data-testid='generation-job-failure']");
    expect(failure.attributes("role")).toBe("alert");
    expect(failure.attributes("data-lost")).toBe("true");
    expect(failure.text()).toContain(
      "La generazione delle alternative di design si è interrotta, forse perché lo Studio è stato riavviato.",
    );
    expect(failure.text()).toContain("puoi avviarla di nuovo quando vuoi");

    await wrapper.get("[data-testid='generation-job-dismiss']").trigger("click");
    expect(wrapper.emitted("dismiss")).toHaveLength(1);
  });

  it("explains why a generation did not succeed", () => {
    const wrapper = mount(GenerationJobNotice, {
      props: {
        job: null,
        failure: { operation: "DISCUSSION_ROUND", code: "PROVIDER_UNAVAILABLE", lost: false },
        locale: "en",
      },
    });

    expect(wrapper.text()).toContain(
      "The generation of the new round of the discussion did not succeed.",
    );
    expect(wrapper.text()).toContain("The AI assistant cannot be reached.");
  });

  it("tells that a very long generation may still be ready later", () => {
    const wrapper = mount(GenerationJobNotice, {
      props: {
        job: null,
        failure: {
          operation: "USER_TWIN_GENERATION",
          code: "GENERATION_POLL_TIMEOUT",
          lost: false,
        },
        locale: "it",
      },
    });

    expect(wrapper.text()).toContain(
      "La generazione dei twin degli utenti dura da più di venti minuti.",
    );
    expect(wrapper.text()).toContain("ricarica la pagina per vedere se è pronta");
  });

  it("shows the running generation before an older failure and nothing without either", async () => {
    const wrapper = mount(GenerationJobNotice, {
      props: {
        job: job(),
        failure: { operation: "REQUIREMENTS_PROPOSAL", code: "TIMEOUT", lost: false },
      },
    });

    expect(wrapper.find("[data-testid='generation-job-notice']").exists()).toBe(true);
    expect(wrapper.find("[data-testid='generation-job-failure']").exists()).toBe(false);

    await wrapper.setProps({ job: null, failure: null });
    expect(wrapper.html()).toBe("<!--v-if-->");
  });

  it("lets the agent at work say what it is doing, with the time and a note of the page", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(Date.parse(STARTED_AT) + 90_000));
    const wrapper = mount(GenerationJobNotice, {
      props: {
        job: job({ operation: "REQUIREMENTS_CHANGE" }),
        locale: "it",
        agent: {
          role: "Analista delle esigenze",
          avatar: "/team/an.webp",
          message: "Sto riscrivendo i requisiti con la tua richiesta.",
        },
      },
      slots: { default: "<blockquote>Aggiungi la ricerca per nome.</blockquote>" },
    });

    const notice = wrapper.get("[data-testid='generation-job-notice']");
    expect(notice.attributes("data-operation")).toBe("REQUIREMENTS_CHANGE");
    const agent = notice.get("[data-testid='agent-message']");
    expect(agent.get("img").attributes("src")).toBe("/team/an.webp");
    expect(agent.text()).toContain("Analista delle esigenze");
    expect(wrapper.get("[role='status']").text()).toBe(
      "Sto riscrivendo i requisiti con la tua richiesta.",
    );
    expect(wrapper.text()).not.toContain("Lo Studio sta generando");
    expect(wrapper.get("[data-testid='generation-job-since']").text()).toMatch(/1 minuto fa\.$/);
    expect(notice.text()).toContain("Puoi lasciare questa pagina e tornare più tardi");
    expect(notice.get("blockquote").text()).toBe("Aggiungi la ricerca per nome.");
    wrapper.unmount();
  });

  it("uses the sentences of the requirements for a change asked in words", () => {
    const wrapper = mount(GenerationJobNotice, {
      props: {
        job: null,
        failure: { operation: "REQUIREMENTS_CHANGE", code: "GENERATION_JOB_NOT_FOUND", lost: true },
        locale: "it",
      },
    });

    expect(wrapper.text()).toContain(
      "La generazione dei requisiti si è interrotta, forse perché lo Studio è stato riavviato.",
    );
    expect(wrapper.text()).toContain("puoi avviarla di nuovo quando vuoi");
  });

  it("is accessible while it runs and when it fails", async () => {
    const running = mount(GenerationJobNotice, { props: { job: job() }, attachTo: document.body });
    await expectAccessible(running.element);
    running.unmount();

    const failed = mount(GenerationJobNotice, {
      props: {
        job: null,
        failure: { operation: "REQUIREMENTS_PROPOSAL", code: "TIMEOUT", lost: false },
      },
      attachTo: document.body,
    });
    await expectAccessible(failed.element);
    failed.unmount();

    const spoken = mount(GenerationJobNotice, {
      props: {
        job: job({ operation: "REQUIREMENTS_CHANGE" }),
        agent: {
          role: "Needs analyst",
          avatar: "/team/an.webp",
          message: "I am writing the requirements again with your request.",
        },
      },
      attachTo: document.body,
    });
    await expectAccessible(spoken.element);
    spoken.unmount();
  });
});
