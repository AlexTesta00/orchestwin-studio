import type { JourneyStep } from "@/api/executionLaunch";

export type JourneyLocale = "it" | "en";

export function journeySentence(step: JourneyStep, locale: JourneyLocale): string {
  const it = locale === "it";
  const label = step.element_label;
  const value = step.action.value ?? "";
  switch (step.action.kind) {
    case "fill":
      return it ? `Compila «${label}» con «${value}»` : `Fill “${label}” with “${value}”`;
    case "click":
      return it ? `Premi «${label}»` : `Press “${label}”`;
    case "press":
      return it
        ? `Attiva «${label}» da tastiera (${value})`
        : `Activate “${label}” from the keyboard (${value})`;
    case "expect_text":
      return it
        ? `Verifica che «${label}» mostri «${value}»`
        : `Check that “${label}” shows “${value}”`;
    case "expect_contains":
      return it
        ? `Verifica che «${label}» contenga «${value}»`
        : `Check that “${label}” contains “${value}”`;
    default:
      return it
        ? `Verifica che «${label}» non mostri più «${value}»`
        : `Check that “${label}” no longer shows “${value}”`;
  }
}
