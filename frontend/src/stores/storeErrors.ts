import { ApiError } from "../api/client";
import type { ApiRequestError } from "../api/requestError";

export interface StoreError {
  message: string;
  code: string | null;
  status: number | null;
}

export function storeErrorOf(
  error: unknown,
  ErrorClass: typeof ApiRequestError,
  fallback: string,
): StoreError {
  if (error instanceof ErrorClass) {
    return { message: error.message, code: error.code, status: error.status };
  }

  return { message: error instanceof Error ? error.message : fallback, code: null, status: null };
}

export function errorDetailOf(error: unknown): string {
  return error instanceof ApiError ? error.detail : "unexpected_error";
}

export function errorMessageOf(
  error: unknown,
  ErrorClass: typeof ApiRequestError,
  fallback: string,
): string {
  if (error instanceof ErrorClass) {
    return error.code ?? error.message;
  }

  return error instanceof Error ? error.message : fallback;
}

export async function optionalResource<T>(operation: () => Promise<T>): Promise<T | null> {
  try {
    return await operation();
  } catch (error: unknown) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }

    throw error;
  }
}
