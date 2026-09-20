import { ApiError } from "./client";

/** One HTTP error contract lets authentication refresh every domain client. */
export class ApiRequestError extends ApiError {
  readonly code: string | null;
  readonly payload: unknown;

  constructor(message: string, options: { status: number; code: string | null; payload: unknown }) {
    super(options.status, options.code ?? message);
    this.name = new.target.name;
    this.message = message;
    this.code = options.code;
    this.payload = options.payload;
  }
}
