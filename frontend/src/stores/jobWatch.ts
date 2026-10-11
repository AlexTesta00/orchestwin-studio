import { getCurrentScope, onScopeDispose } from "vue";

import { ApiError } from "../api/client";
import { ApiRequestError } from "../api/requestError";
import type { GenerationJobStatus } from "../types/designMockups";

export const POLL_INTERVAL_MILLISECONDS = 3000;
export const POLL_LIMIT_MILLISECONDS = 20 * 60 * 1000;

export function errorCodeOf(error: unknown): string | null {
  if (error instanceof ApiRequestError) {
    return error.code;
  }

  return error instanceof ApiError ? error.detail : null;
}

export function errorStatusOf(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

export function isTransientError(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return true;
  }

  return error.status >= 500 || error.status === 408 || error.status === 429;
}

export function isFinishedStatus(status: GenerationJobStatus): boolean {
  return status === "SUCCEEDED" || status === "REJECTED" || status === "FAILED";
}

export function readSessionValue(key: string): unknown {
  try {
    const raw = globalThis.sessionStorage.getItem(key);

    return raw === null ? null : (JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

export function writeSessionValue(key: string, value: unknown): void {
  try {
    globalThis.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    return;
  }
}

export function pollingHolder(signal: AbortSignal | undefined): AbortSignal | undefined {
  if (signal !== undefined || getCurrentScope() === undefined) {
    return signal;
  }

  const controller = new AbortController();
  onScopeDispose(() => controller.abort());

  return controller.signal;
}

export class JobWatch {
  readonly jobId: string;
  private readonly tick: () => Promise<boolean>;
  private readonly expire: () => void;
  private readonly signals = new Set<AbortSignal>();
  private unbound = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private busy = false;
  private closed = false;
  private deadline = 0;

  constructor(jobId: string, tick: () => Promise<boolean>, expire: () => void) {
    this.jobId = jobId;
    this.tick = tick;
    this.expire = expire;
  }

  get isClosed(): boolean {
    return this.closed;
  }

  get isActive(): boolean {
    return !this.closed && (this.unbound || this.signals.size > 0);
  }

  hold(signal: AbortSignal | undefined): void {
    if (this.closed || signal?.aborted === true) {
      return;
    }

    if (!this.isActive) {
      this.deadline = Date.now() + POLL_LIMIT_MILLISECONDS;
    }

    if (signal === undefined) {
      this.unbound = true;
    } else if (!this.signals.has(signal)) {
      this.signals.add(signal);
      signal.addEventListener("abort", () => this.release(signal), { once: true });
    }

    this.schedule();
  }

  close(): void {
    this.closed = true;
    this.signals.clear();
    this.clearTimer();
  }

  private release(signal: AbortSignal): void {
    this.signals.delete(signal);

    if (!this.isActive) {
      this.clearTimer();
    }
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private schedule(): void {
    if (!this.isActive || this.timer !== null || this.busy) {
      return;
    }

    this.timer = setTimeout(() => {
      this.timer = null;
      void this.run();
    }, POLL_INTERVAL_MILLISECONDS);
  }

  private async run(): Promise<void> {
    if (!this.isActive) {
      return;
    }

    if (Date.now() >= this.deadline) {
      this.close();
      this.expire();
      return;
    }

    this.busy = true;
    const finished = await this.tick().catch(() => false);
    this.busy = false;

    if (finished) {
      this.close();
      return;
    }

    this.schedule();
  }
}
