import { describe, expect, it } from 'vitest';
import { increment } from '../src/counter';

describe('counter increment', () => {
  it('advances zero by exactly one', () => { expect(increment(0), 'LEVEL_D_NEGATIVE_CONTROL').toBe(1); });
  it('preserves accumulated values', () => { expect(increment(41), 'LEVEL_D_NEGATIVE_CONTROL').toBe(42); });
});
