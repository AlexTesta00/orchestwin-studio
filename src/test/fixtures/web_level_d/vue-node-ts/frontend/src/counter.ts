export function countFromPayload(payload: unknown): number {
  if (typeof payload !== 'object' || payload === null || !('count' in payload) || !Number.isInteger(payload.count) || Number(payload.count) < 0) {
    throw new Error('Invalid counter response');
  }
  return Number(payload.count);
}
