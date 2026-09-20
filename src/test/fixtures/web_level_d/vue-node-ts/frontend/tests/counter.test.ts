import { describe, expect, it } from 'vitest';
import { countFromPayload } from '../src/counter';

describe('counter response validation', () => {
  it('reads the actual numeric count', () => { expect(countFromPayload({ count: 7 })).toBe(7); });
  it('rejects missing, textual and negative counts', () => {
    for (const value of [null, {}, { count: '7' }, { count: -1 }]) {
      expect(() => countFromPayload(value)).toThrow('Invalid counter response');
    }
  });
});
