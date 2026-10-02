import { flushPromises, mount } from "@vue/test-utils";
import { h } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import { expectAccessible } from "@/test/axe";
import UiCommandLine from "./UiCommandLine.vue";
import UiSurface from "./UiSurface.vue";

const COMMAND = "ut init --project 00000000-0000-4000-8000-000000000042 --mode design-code";
const LABELS = {
  copyLabel: "Copia",
  copiedLabel: "Copiato",
  failedLabel: "Copia non riuscita",
};

type CopyText = (text: string) => Promise<void>;

function mountLine(copyText?: CopyText) {
  return mount(UiCommandLine, {
    props: { command: COMMAND, ...LABELS, ...(copyText === undefined ? {} : { copyText }) },
    attachTo: document.body,
  });
}

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("command line", () => {
  it("shows the command as selectable text and names the command in its real button", () => {
    const wrapper = mountLine(vi.fn(() => Promise.resolve()));

    const text = wrapper.get("[data-testid='command-text']");
    expect(text.element.tagName).toBe("CODE");
    expect(text.text()).toBe(COMMAND);
    expect(text.classes()).toContain("font-mono");
    expect(text.classes()).not.toContain("select-none");
    const button = wrapper.get("[data-testid='command-copy']");
    expect(button.element.tagName).toBe("BUTTON");
    expect(button.attributes("type")).toBe("button");
    expect(button.attributes("aria-label")).toBe(`Copia: ${COMMAND}`);
    expect(button.text()).toBe("Copia");
    const status = wrapper.get("[data-testid='command-status']");
    expect(status.attributes("role")).toBe("status");
    expect(status.attributes("aria-live")).toBe("polite");
    expect(status.text()).toBe("");
    wrapper.unmount();
  });

  it("wraps a long command inside its box, beside the button aligned to the top, and copies it unchanged", async () => {
    const copyText = vi.fn<CopyText>(() => Promise.resolve());
    const wrapper = mountLine(copyText);

    const row = wrapper.get("[data-testid='command-line']");
    expect(row.classes()).toEqual(expect.arrayContaining(["flex", "items-start"]));
    expect(row.classes()).not.toContain("flex-wrap");
    const text = wrapper.get("[data-testid='command-text']");
    expect(text.classes()).toEqual(
      expect.arrayContaining([
        "min-w-0",
        "flex-1",
        "whitespace-pre-wrap",
        "wrap-anywhere",
        "py-3",
        "leading-5",
      ]),
    );
    expect(text.classes()).not.toContain("overflow-x-auto");
    expect(text.classes()).not.toContain("whitespace-pre");
    expect(text.element.textContent).toBe(COMMAND);
    const button = wrapper.get("[data-testid='command-copy']");
    expect(text.element.nextElementSibling).toBe(button.element);
    expect(button.classes()).toEqual(expect.arrayContaining(["shrink-0", "min-h-11"]));

    await button.trigger("click");
    await flushPromises();

    expect(copyText).toHaveBeenCalledTimes(1);
    expect(copyText.mock.calls[0]?.[0]).toBe(COMMAND);
    expect(copyText.mock.calls[0]?.[0]).not.toMatch(/[\r\n]/);
    wrapper.unmount();
  });

  it("copies the command, says so for two seconds and keeps the focus on the button", async () => {
    vi.useFakeTimers();
    const copyText = vi.fn(() => Promise.resolve());
    const wrapper = mountLine(copyText);
    const button = wrapper.get<HTMLButtonElement>("[data-testid='command-copy']");
    button.element.focus();

    await button.trigger("click");
    await flushPromises();

    expect(copyText).toHaveBeenCalledTimes(1);
    expect(copyText).toHaveBeenCalledWith(COMMAND);
    expect(button.text()).toBe("Copiato");
    expect(wrapper.get("[data-testid='command-status']").text()).toBe("Copiato");
    expect(button.attributes("aria-label")).toBe(`Copia: ${COMMAND}`);
    expect(document.activeElement).toBe(button.element);

    vi.advanceTimersByTime(1999);
    await flushPromises();
    expect(button.text()).toBe("Copiato");

    vi.advanceTimersByTime(1);
    await flushPromises();
    expect(button.text()).toBe("Copia");
    expect(wrapper.get("[data-testid='command-status']").text()).toBe("");
    expect(vi.getTimerCount()).toBe(0);
    expect(document.activeElement).toBe(button.element);
    wrapper.unmount();
  });

  it("counts the two seconds again from the latest copy", async () => {
    vi.useFakeTimers();
    const copyText = vi.fn(() => Promise.resolve());
    const wrapper = mountLine(copyText);
    const button = wrapper.get("[data-testid='command-copy']");

    await button.trigger("click");
    await flushPromises();
    vi.advanceTimersByTime(1500);
    await button.trigger("click");
    await flushPromises();
    vi.advanceTimersByTime(1500);
    await flushPromises();

    expect(copyText).toHaveBeenCalledTimes(2);
    expect(button.text()).toBe("Copiato");
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(500);
    await flushPromises();
    expect(button.text()).toBe("Copia");
    wrapper.unmount();
  });

  it("says when the copy fails and leaves the command to select by hand", async () => {
    const copyText = vi.fn<CopyText>(() => Promise.reject(new Error("permission refused")));
    const wrapper = mountLine(copyText);
    const button = wrapper.get<HTMLButtonElement>("[data-testid='command-copy']");
    button.element.focus();

    await button.trigger("click");
    await flushPromises();

    expect(button.text()).toBe("Copia non riuscita");
    expect(wrapper.get("[data-testid='command-status']").text()).toBe("Copia non riuscita");
    expect(wrapper.get("[data-testid='command-text']").text()).toBe(COMMAND);
    expect(document.activeElement).toBe(button.element);
    await expectAccessible(wrapper.element);

    copyText.mockImplementationOnce(() => Promise.resolve());
    await button.trigger("click");
    await flushPromises();
    expect(button.text()).toBe("Copiato");
    wrapper.unmount();
  });

  it("writes to the clipboard of the browser by default and fails without one", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    const clipboard = { writeText };
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
    try {
      const wrapper = mountLine();
      await wrapper.get("[data-testid='command-copy']").trigger("click");
      await flushPromises();

      expect(writeText).toHaveBeenCalledWith(COMMAND);
      expect(writeText.mock.contexts[0]).toBe(clipboard);
      expect(wrapper.get("[data-testid='command-copy']").text()).toBe("Copiato");
      wrapper.unmount();
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }

    const missing = mountLine();
    await missing.get("[data-testid='command-copy']").trigger("click");
    await flushPromises();
    expect(missing.get("[data-testid='command-copy']").text()).toBe("Copia non riuscita");
    missing.unmount();
  });

  it("forgets the result when the command changes or the line goes away", async () => {
    vi.useFakeTimers();
    let finish: (value: void) => void = () => undefined;
    const copyText = vi.fn<CopyText>(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const wrapper = mountLine(copyText);
    const button = wrapper.get("[data-testid='command-copy']");

    await button.trigger("click");
    await wrapper.setProps({ command: "code ." });
    finish();
    await flushPromises();
    expect(button.text()).toBe("Copia");
    expect(button.attributes("aria-label")).toBe("Copia: code .");

    copyText.mockImplementationOnce(() => Promise.resolve());
    await button.trigger("click");
    await flushPromises();
    expect(button.text()).toBe("Copiato");
    await wrapper.setProps({ command: "ut status" });
    expect(button.text()).toBe("Copia");
    expect(vi.getTimerCount()).toBe(0);

    copyText.mockImplementationOnce(() => Promise.resolve());
    await button.trigger("click");
    await flushPromises();
    expect(vi.getTimerCount()).toBe(1);
    wrapper.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("uses the look of the command chips on a dark surface", () => {
    const light = mountLine(vi.fn(() => Promise.resolve()));
    expect(light.get("[data-testid='command-line']").attributes("data-surface-context")).toBe(
      "light",
    );
    expect(light.get("[data-testid='command-text']").classes()).toContain("bg-surface-3");
    light.unmount();

    const night = mount(UiSurface, {
      slots: {
        default: () =>
          h(UiCommandLine, { command: COMMAND, ...LABELS, copyText: () => Promise.resolve() }),
      },
    });
    expect(night.get("[data-testid='command-line']").attributes("data-surface-context")).toBe(
      "night",
    );
    expect(night.get("[data-testid='command-text']").classes()).toEqual(
      expect.arrayContaining(["rounded-[4px]", "bg-on-night/8", "text-on-night"]),
    );
    expect(night.get("[data-testid='command-copy']").attributes("data-variant")).toBe("outline");
    expect(night.get("[data-testid='command-copy']").classes()).toContain("text-on-night");
    night.unmount();
  });

  it("has no axe violations before and after a copy", async () => {
    const wrapper = mountLine(vi.fn(() => Promise.resolve()));
    await expectAccessible(wrapper.element);
    await wrapper.get("[data-testid='command-copy']").trigger("click");
    await flushPromises();
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
