<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import UiClaimLabel from "@/components/UiClaimLabel.vue";
import UiSurface from "@/components/UiSurface.vue";
import { useAuthStore } from "@/stores/auth";

const twinKeys = ["brief", "critique", "proof"] as const;
const stepKeys = ["brief", "team", "twins", "requirements", "design", "package"] as const;

type RevealKind = "up" | "zoom" | "rise";

const pictures = {
  hero: "/home/hero.webp",
  rule: "/home/bento.webp",
  closing: "/home/pacchetto.webp",
} as const;

const twinPictures = {
  brief: { src: "/home/brief.webp", position: "object-[center_62%]", sticky: "md:top-24" },
  critique: { src: "/home/critica.webp", position: "object-[center_66%]", sticky: "md:top-30" },
  proof: { src: "/home/prova.webp", position: "object-[center_62%]", sticky: "md:top-36" },
} as const;

const timelineGrid =
  "grid grid-cols-[92px_minmax(0,1fr)] gap-4 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] sm:gap-6";

const hiddenTransforms: Record<RevealKind, string> = {
  up: "translateY(32px)",
  zoom: "scale(1.1)",
  rise: "translateY(105%)",
};

const messages = {
  it: {
    lead: "L'AI ti accompagna dal brief al dossier e guarda il progetto dalle prospettive che gli servono. Ogni passo si chiude con la tua approvazione.",
    heroAlt:
      "Un twin di vetro traslucido accanto al suo gemello pieno, due robot da compagnia su un pavimento scuro",
    hypothesis: "Ipotesi dell'AI",
    claimsLabel: "Un'ipotesi dell'AI diventa una decisione solo quando la confermi tu",
    whatTitle: "Che cos'è OrchesTwin Studio?",
    discover: "Scopri il percorso",
    ruleTwoText:
      "Le opinioni dei twin, i requisiti e le critiche sono proposte, mai prove. Diventano decisioni solo quando le approvi.",
    ownershipLabel: "Sempre tuo",
    ownershipTitle: "Prove e decisioni restano con te",
    ownershipText: "Prove, decisioni e provenienza restano tue, esportabili in ogni momento.",
    legend: "Due tipi di contenuto, sempre distinguibili in ogni schermata dello Studio.",
    twinAlts: {
      brief:
        "Un foglio di carta che si sfilaccia in fili tratteggiati e diventa tre piccole figure di vetro",
      critique:
        "Tre piccoli robot osservano due schermi luminosi; uno ha un punto interrogativo sul viso",
      proof:
        "Un robot di vetro traslucido accanto allo stesso robot pieno, inquadrato da una griglia di misura",
    },
    before: "Prima",
    beforeText: "Un'idea raccontata in due righe, con parole tue.",
    decision: "Tua decisione:",
    decisions: {
      brief: "Approva il brief",
      team: "Approva le prospettive",
      twins: "Conferma i twin",
      requirements: "Approva i requisiti",
      design: "Scegli e approva il design",
      package: "Scarica la cartella",
    },
    after: "Dopo",
    afterText: "Realizzi l'applicazione con i tuoi strumenti, partendo dalla cartella.",
    closingAlt: "Una scatola color petrolio con un piccolo robot bianco appoggiato accanto",
    author: "Dott. Alex Testa",
  },
  en: {
    lead: "AI guides you from the brief to the dossier and looks at the project from the perspectives it needs. Every step closes with your approval.",
    heroAlt:
      "A translucent glass twin next to its solid sibling, two companion robots on a dark floor",
    hypothesis: "AI hypothesis",
    claimsLabel: "An AI hypothesis becomes a decision only when you confirm it",
    whatTitle: "What is OrchesTwin Studio?",
    discover: "Discover the path",
    ruleTwoText:
      "The twins' opinions, the requirements and the critiques are proposals, never proof. They become decisions only when you approve them.",
    ownershipLabel: "Always yours",
    ownershipTitle: "Evidence and decisions stay with you",
    ownershipText: "Evidence, decisions and provenance remain yours, exportable at any time.",
    legend: "Two kinds of content, always distinguishable on every screen of the Studio.",
    twinAlts: {
      brief: "A sheet of paper fraying into dotted threads that become three small glass figures",
      critique:
        "Three small robots look at two glowing screens; one has a question mark on its face",
      proof:
        "A translucent glass robot next to the same robot in solid form, framed by a measuring grid",
    },
    before: "Before",
    beforeText: "An idea told in two lines, in your own words.",
    decision: "Your decision:",
    decisions: {
      brief: "Approve the brief",
      team: "Approve the perspectives",
      twins: "Confirm the twins",
      requirements: "Approve the requirements",
      design: "Choose and approve the design",
      package: "Download the folder",
    },
    after: "After",
    afterText: "You build the application with your own tools, starting from the folder.",
    closingAlt: "A petrol-coloured box with a small white robot leaning against it",
    author: "Alex Testa",
  },
} as const;

const auth = useAuthStore();
const { t, locale } = useI18n({ useScope: "global" });

const copy = computed(() => messages[locale.value === "it" ? "it" : "en"]);
const entryTarget = computed(() => (auth.isAuthenticated ? "/projects" : "/register"));

const reducedMotion =
  typeof window === "undefined" ||
  typeof window.matchMedia !== "function" ||
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const root = ref<HTMLElement | null>(null);
const pending = new Map<Element, HTMLElement>();
let observer: IntersectionObserver | null = null;
let frame = 0;
let fallback: ReturnType<typeof setTimeout> | undefined;

function revealKind(element: HTMLElement): RevealKind {
  const kind = element.dataset.reveal;
  return kind === "zoom" || kind === "rise" ? kind : "up";
}

function transitionOf(kind: RevealKind, delay: number): string {
  return kind === "zoom"
    ? `opacity 1.2s ease ${delay}ms, transform 2.4s cubic-bezier(0.16, 0.8, 0.2, 1) ${delay}ms`
    : `opacity 0.9s cubic-bezier(0.2, 0.7, 0.2, 1) ${delay}ms, transform 1.1s cubic-bezier(0.2, 0.8, 0.2, 1) ${delay}ms`;
}

function show(watched: Element): void {
  const element = pending.get(watched);
  pending.delete(watched);
  observer?.unobserve(watched);
  if (element === undefined) return;
  element.style.opacity = "1";
  element.style.transform = "none";
}

function hideUntilSeen(container: HTMLElement, watcher: IntersectionObserver): void {
  for (const element of container.querySelectorAll<HTMLElement>("[data-reveal]")) {
    const kind = revealKind(element);
    const delay = Number(element.dataset.delay ?? "0") || 0;
    const watched = kind === "rise" ? (element.parentElement ?? element) : element;
    element.style.opacity = "0";
    element.style.transform = hiddenTransforms[kind];
    element.style.transition = transitionOf(kind, delay);
    pending.set(watched, element);
    watcher.observe(watched);
  }
}

function showWhatIsInView(): void {
  for (const watched of [...pending.keys()]) {
    if (watched.getBoundingClientRect().top < window.innerHeight) show(watched);
  }
}

function follow(): void {
  frame = 0;
  const container = root.value;
  if (container === null) return;
  const height = window.innerHeight;
  for (const element of container.querySelectorAll<HTMLElement>("[data-parallax]")) {
    const rect = (element.parentElement ?? element).getBoundingClientRect();
    if (rect.bottom < -200 || rect.top > height + 200) continue;
    const factor = Number(element.dataset.parallax) || 0;
    const offset = -(rect.top + rect.height / 2 - height / 2) * factor;
    element.style.setProperty("translate", `0 ${offset.toFixed(1)}px`);
  }
  const rows = [...container.querySelectorAll<HTMLElement>("[data-timeline]")];
  let active: HTMLElement | null = null;
  let distance = Number.POSITIVE_INFINITY;
  for (const row of rows) {
    const rect = row.getBoundingClientRect();
    const gap = Math.abs(rect.top + rect.height / 2 - height * 0.52);
    if (gap < distance) {
      distance = gap;
      active = row;
    }
  }
  for (const row of rows) row.style.opacity = row === active ? "1" : "0.62";
}

function schedule(): void {
  if (frame === 0) frame = window.requestAnimationFrame(follow);
}

function scrollToSection(id: string): void {
  const section = document.getElementById(id);
  section?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  section?.focus({ preventScroll: true });
}

onMounted(() => {
  const container = root.value;
  if (reducedMotion || container === null) return;
  if (typeof window.IntersectionObserver === "function") {
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) if (entry.isIntersecting) show(entry.target);
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
    );
    hideUntilSeen(container, observer);
    fallback = setTimeout(showWhatIsInView, 1600);
  }
  if (typeof window.requestAnimationFrame === "function") {
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    schedule();
  }
});

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
  pending.clear();
  clearTimeout(fallback);
  window.removeEventListener("scroll", schedule);
  window.removeEventListener("resize", schedule);
  if (frame !== 0) window.cancelAnimationFrame(frame);
  frame = 0;
});
</script>

<template>
  <div ref="root" data-testid="home">
    <UiSurface
      as="section"
      tone="night"
      :padded="false"
      aria-labelledby="home-title"
      class="h-[clamp(540px,80vh,740px)] overflow-hidden"
    >
      <div data-parallax="0.12" class="absolute inset-x-0 -top-[12%] -bottom-[12%] -z-2">
        <img
          data-reveal="zoom"
          :src="pictures.hero"
          :alt="copy.heroAlt"
          class="block h-full w-full object-cover object-[68%_center]"
        />
      </div>
      <div
        class="absolute inset-0 -z-1 bg-[linear-gradient(180deg,rgba(15,17,18,0.55)_0%,rgba(15,17,18,0.8)_40%,rgba(15,17,18,0.92)_100%)] md:bg-[linear-gradient(90deg,rgba(15,17,18,0.94)_0%,rgba(15,17,18,0.72)_50%,rgba(15,17,18,0)_80%)] xl:bg-[linear-gradient(90deg,rgba(15,17,18,0.94)_0%,rgba(15,17,18,0.6)_40%,rgba(15,17,18,0)_64%)]"
        aria-hidden="true"
      />
      <div
        class="flex h-full max-w-[800px] flex-col items-start justify-center gap-[22px] px-[clamp(28px,5vw,72px)] pb-16 md:pb-10"
      >
        <span
          data-reveal="up"
          class="flex size-8 items-center justify-center rounded-full border-2 border-dashed border-violet"
          aria-hidden="true"
        >
          <span class="size-3 rounded-full bg-petrol" />
        </span>
        <h1
          id="home-title"
          data-reveal="up"
          data-delay="120"
          class="m-0 font-display text-[clamp(19px,5.4vw,24px)] leading-[1.14] font-extralight tracking-display text-balance uppercase md:text-[clamp(24px,3vw,44px)]"
        >
          {{ t("home.title") }}
        </h1>
        <p
          data-reveal="up"
          data-delay="260"
          class="m-0 max-w-[480px] border-l border-on-night/40 pl-4 text-[17px] leading-[1.55] text-on-night-2"
        >
          {{ copy.lead }}
        </p>
        <div data-reveal="up" data-delay="400" class="flex flex-wrap gap-2.5">
          <UiButton :to="entryTarget" variant="pill" size="lg" data-testid="home-enter">
            {{ t("home.enter") }}
          </UiButton>
          <UiButton
            variant="outline"
            size="lg"
            class="backdrop-blur-[10px]"
            data-testid="home-twins-link"
            @click="scrollToSection('twin')"
          >
            {{ t("home.twinsLink") }}
          </UiButton>
        </div>
      </div>
      <div
        data-reveal="up"
        data-delay="700"
        class="absolute inset-x-6 bottom-6 flex flex-wrap items-center gap-2"
        role="group"
        :aria-label="copy.claimsLabel"
      >
        <span
          class="inline-flex min-h-8 items-center gap-2 rounded-pill border border-dashed border-hypothesis bg-white/85 px-3.5 text-[13px] font-medium whitespace-nowrap text-hypothesis"
        >
          <span
            class="inline-block size-[9px] shrink-0 rounded-full border-[1.5px] border-hypothesis"
            aria-hidden="true"
          />
          {{ copy.hypothesis }}
        </span>
        <span class="text-on-night" aria-hidden="true">→</span>
        <UiClaimLabel kind="confirmed" surface="light" />
      </div>
    </UiSurface>

    <section
      class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,400px),1fr))] items-start gap-x-[72px] gap-y-8 px-2 pt-20 pb-16 md:pt-[120px]"
      aria-labelledby="home-what-title"
    >
      <div data-reveal="up">
        <h2
          id="home-what-title"
          class="m-0 mb-7 text-[clamp(36px,4.2vw,56px)] leading-[1.02] font-semibold tracking-[-0.04em]"
        >
          {{ copy.whatTitle }}
        </h2>
        <UiButton
          variant="pill"
          surface="light"
          data-testid="home-path-link"
          @click="scrollToSection('steps')"
        >
          {{ copy.discover }}
        </UiButton>
      </div>
      <p
        data-reveal="up"
        data-delay="120"
        class="m-0 text-[clamp(19px,1.75vw,24px)] leading-[1.42] tracking-[-0.012em] text-pretty text-ink"
      >
        {{ t("home.lead") }}
      </p>
    </section>

    <div class="flex flex-wrap gap-4">
      <article
        data-reveal="up"
        class="relative isolate flex min-h-[360px] flex-[2_1_480px] flex-col justify-between gap-6 overflow-hidden rounded-[24px] bg-night p-[30px] text-on-night"
        data-testid="home-rule"
      >
        <img
          :src="pictures.rule"
          alt=""
          class="absolute inset-0 -z-2 block h-full w-full object-cover object-right"
        />
        <div
          class="absolute inset-0 -z-1 bg-[linear-gradient(180deg,rgba(15,17,18,0.85)_0%,rgba(15,17,18,0.5)_45%,rgba(15,17,18,0.9)_100%)] sm:hidden"
          aria-hidden="true"
        />
        <div>
          <p class="m-0 mb-2.5 font-mono text-xs tracking-eyebrow text-petrol-on-night-2 uppercase">
            {{ t("home.rules.one.label") }}
          </p>
          <h3
            class="m-0 max-w-[320px] text-[clamp(24px,2.3vw,30px)] leading-[1.1] font-semibold tracking-card"
          >
            {{ t("home.rules.one.title") }}
          </h3>
        </div>
        <p class="m-0 max-w-[330px] text-[15px] leading-[1.55] text-on-night-2">
          {{ t("home.rules.one.text") }}
        </p>
      </article>
      <article
        data-reveal="up"
        data-delay="120"
        class="flex min-h-[360px] flex-[1_1_240px] flex-col justify-between gap-6 rounded-[24px] bg-ink p-[30px] text-white"
        data-testid="home-rule"
      >
        <div>
          <p class="m-0 mb-2.5 font-mono text-xs tracking-eyebrow text-on-night-3 uppercase">
            {{ t("home.rules.two.label") }}
          </p>
          <h3 class="m-0 text-[clamp(24px,2.1vw,28px)] leading-[1.12] font-semibold tracking-card">
            {{ t("home.rules.two.title") }}
          </h3>
        </div>
        <p class="m-0 text-[15px] leading-[1.55] text-on-night-2">{{ copy.ruleTwoText }}</p>
      </article>
      <article
        data-reveal="up"
        data-delay="240"
        class="flex min-h-[360px] flex-[1_1_240px] flex-col justify-between gap-6 rounded-[24px] bg-petrol p-[30px] text-white"
        data-testid="home-rule"
      >
        <div>
          <p class="m-0 mb-2.5 font-mono text-xs tracking-eyebrow text-petrol-soft/90 uppercase">
            {{ copy.ownershipLabel }}
          </p>
          <h3 class="m-0 text-[clamp(24px,2.1vw,28px)] leading-[1.12] font-semibold tracking-card">
            {{ copy.ownershipTitle }}
          </h3>
        </div>
        <p class="m-0 text-[15px] leading-[1.55] text-petrol-soft">{{ copy.ownershipText }}</p>
      </article>
    </div>

    <div
      data-reveal="up"
      class="flex flex-wrap items-center gap-x-8 gap-y-4 border-b border-line px-2 py-9"
      data-testid="home-legend"
    >
      <p class="m-0 max-w-[240px] text-[13px] leading-[1.45] text-ink-3">{{ copy.legend }}</p>
      <div class="flex flex-wrap items-center gap-2.5 sm:ml-auto">
        <UiClaimLabel kind="hypothesis" surface="light" />
        <UiClaimLabel kind="confirmed" surface="light" />
        <UiClaimLabel kind="proof" surface="light" />
      </div>
    </div>

    <section
      id="twin"
      tabindex="-1"
      class="flex scroll-mt-20 flex-wrap items-start gap-x-[72px] gap-y-10 px-2 pt-20 pb-6 outline-none md:pt-[120px]"
      aria-labelledby="home-twins-title"
    >
      <div data-reveal="up" class="flex-[1_1_320px] lg:sticky lg:top-28">
        <p class="m-0 mb-3.5 font-mono text-xs tracking-eyebrow text-ink-3 uppercase">
          {{ t("home.twins.eyebrow") }}
        </p>
        <h2
          id="home-twins-title"
          class="m-0 mb-5 text-[clamp(40px,4.8vw,66px)] leading-none font-semibold tracking-[-0.045em] text-balance"
        >
          {{ t("home.twins.title") }}
        </h2>
        <p class="m-0 max-w-[440px] text-base leading-[1.6] text-ink-2">
          {{ t("home.twins.lead") }}
        </p>
      </div>
      <div class="flex min-w-0 flex-[1.35_1_480px] flex-col gap-7 pb-10">
        <article
          v-for="key in twinKeys"
          :key="key"
          data-reveal="up"
          :class="[
            'overflow-hidden rounded-[24px] border border-line bg-surface shadow-lift md:sticky',
            twinPictures[key].sticky,
          ]"
          data-testid="home-twin"
        >
          <div
            class="grid items-start gap-x-6 gap-y-2 px-7 pt-7 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]"
          >
            <div>
              <p class="m-0 font-mono text-xs tracking-eyebrow text-ink-3 uppercase">
                {{ t(`home.twins.items.${key}.label`) }}
              </p>
              <h3
                class="m-0 mt-2 text-[clamp(24px,2.4vw,32px)] leading-[1.1] font-semibold tracking-card"
              >
                {{ t(`home.twins.items.${key}.title`) }}
              </h3>
            </div>
            <p class="m-0 text-[15px] leading-[1.55] text-ink-2">
              {{ t(`home.twins.items.${key}.text`) }}
            </p>
          </div>
          <div class="mt-6 h-[clamp(260px,30vw,380px)] overflow-hidden bg-night">
            <img
              data-parallax="0.06"
              :src="twinPictures[key].src"
              :alt="copy.twinAlts[key]"
              :class="['-mt-[9%] block h-[118%] w-full object-cover', twinPictures[key].position]"
            />
          </div>
        </article>
      </div>
    </section>

    <UiSurface
      id="steps"
      as="section"
      tone="panel"
      :padded="false"
      tabindex="-1"
      aria-labelledby="home-steps-title"
      class="mt-16 scroll-mt-20 overflow-hidden px-[clamp(24px,5vw,80px)] pt-[clamp(40px,6vw,88px)] pb-[clamp(40px,5vw,72px)] outline-none"
    >
      <div
        data-reveal="up"
        class="mb-10 grid gap-3 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] sm:gap-6"
      >
        <p class="m-0 self-end font-mono text-xs tracking-eyebrow text-petrol-on-night-2 uppercase">
          {{ t("home.steps.eyebrow") }}
        </p>
        <h2
          id="home-steps-title"
          class="m-0 text-[clamp(30px,3.4vw,44px)] leading-[1.05] font-semibold tracking-hero"
        >
          {{ t("home.steps.title") }}
        </h2>
      </div>
      <div :class="[timelineGrid, 'border-t border-on-night/14 pt-[18px] pb-[22px]']">
        <span aria-hidden="true" />
        <div>
          <p class="m-0 font-mono text-xs font-semibold tracking-eyebrow uppercase">
            {{ copy.before }}
          </p>
          <p class="m-0 mt-2 text-[15px] text-on-night-2">{{ copy.beforeText }}</p>
        </div>
      </div>
      <ol class="m-0 list-none p-0">
        <li
          v-for="(key, index) in stepKeys"
          :key="key"
          data-timeline
          :class="[timelineGrid, 'border-t border-on-night/14 transition-opacity duration-500']"
          data-testid="home-step"
        >
          <div class="h-[clamp(42px,8.2vw,134px)] self-end overflow-hidden" aria-hidden="true">
            <div
              data-reveal="rise"
              class="pt-[0.04em] font-display text-[clamp(56px,11vw,180px)] leading-[0.84] font-extralight tracking-numeral"
            >
              {{ String(index + 1).padStart(2, "0") }}
            </div>
          </div>
          <div class="pt-[22px] pb-[26px]">
            <h3 class="m-0 font-mono text-xs font-semibold tracking-eyebrow uppercase">
              {{ t(`home.steps.items.${key}.title`) }}
            </h3>
            <p class="m-0 mt-2.5 max-w-[440px] text-[15px] leading-[1.55] text-on-night-2">
              {{ t(`home.steps.items.${key}.text`) }}
            </p>
            <p class="m-0 mt-2.5 text-sm text-petrol-on-night-2">
              <span
                class="mr-2 inline-block size-[7px] rounded-full bg-petrol-on-night-2 align-middle"
                aria-hidden="true"
              />{{ copy.decision }} {{ copy.decisions[key] }}
            </p>
          </div>
        </li>
      </ol>
      <div :class="[timelineGrid, 'border-t border-on-night/14 pt-[18px]']">
        <span aria-hidden="true" />
        <div>
          <p class="m-0 font-mono text-xs font-semibold tracking-eyebrow uppercase">
            {{ copy.after }}
          </p>
          <p class="m-0 mt-2 mb-6 text-[15px] text-on-night-2">{{ copy.afterText }}</p>
          <RouterLink
            :to="entryTarget"
            class="inline-flex min-h-11 items-center font-mono text-xs font-semibold tracking-eyebrow text-on-night uppercase underline underline-offset-[6px] hover:text-petrol-on-night-2"
            data-testid="home-enter-path"
          >
            {{ t("home.enter") }}
          </RouterLink>
        </div>
      </div>
    </UiSurface>

    <UiSurface
      as="section"
      tone="night"
      :padded="false"
      data-reveal="up"
      aria-labelledby="home-closing-title"
      class="mt-16 flex min-h-[clamp(420px,52vw,560px)] items-center overflow-hidden"
    >
      <div data-parallax="0.1" class="absolute inset-x-0 -top-[10%] -bottom-[10%] -z-2">
        <img
          :src="pictures.closing"
          :alt="copy.closingAlt"
          class="block h-full w-full object-cover object-right"
        />
      </div>
      <div
        class="absolute inset-0 -z-1 bg-[linear-gradient(180deg,rgba(15,17,18,0.9)_0%,rgba(15,17,18,0.75)_60%,rgba(15,17,18,0.4)_100%)] md:bg-[linear-gradient(90deg,rgba(15,17,18,0.94)_0%,rgba(15,17,18,0.65)_40%,rgba(15,17,18,0)_68%)]"
        aria-hidden="true"
      />
      <div class="max-w-[600px] p-[clamp(32px,5vw,64px)]">
        <h2
          id="home-closing-title"
          class="m-0 mb-4 text-[clamp(34px,3.8vw,52px)] leading-[1.02] font-semibold tracking-[-0.04em] text-balance"
        >
          {{ t("home.closing.title") }}
        </h2>
        <p class="m-0 mb-7 max-w-[440px] text-[17px] leading-[1.55] text-on-night-2">
          {{ t("home.closing.text") }}
        </p>
        <UiButton :to="entryTarget" variant="pill" size="lg" data-testid="home-enter-closing">
          {{ t("home.enter") }}
        </UiButton>
      </div>
    </UiSurface>

    <footer
      class="mt-12 flex flex-wrap justify-between gap-4 border-t border-line px-2 pt-5 font-mono text-xs text-ink-3"
    >
      <span>{{ t("home.footer.thesis") }}</span>
      <span>{{ copy.author }}</span>
    </footer>
  </div>
</template>
