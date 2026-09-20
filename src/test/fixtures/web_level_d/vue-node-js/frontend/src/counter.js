export function countFromPayload(payload) {
  if (typeof payload !== 'object' || payload === null || !Number.isInteger(payload.count) || payload.count < 0) {
    throw new Error('Invalid counter response');
  }
  return payload.count;
}
