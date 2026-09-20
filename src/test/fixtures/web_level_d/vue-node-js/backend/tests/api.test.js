import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { app } from '../src/app.js';

let server;
let baseUrl;
beforeAll(async () => {
  server = app.listen(0, '127.0.0.1');
  await new Promise((resolve, reject) => { server.once('listening', resolve); server.once('error', reject); });
  baseUrl = 'http://127.0.0.1:' + (server.address()).port;
});
afterAll(async () => {
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
});
describe('actual HTTP counter API', () => {
  it('reports readiness as JSON', async () => {
    const response = await fetch(baseUrl + '/health');
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('application/json');
    expect(await response.json()).toEqual({ status: 'ok' });
  });
  it('increments a supplied count by exactly one', async () => {
    const response = await fetch(baseUrl + '/api/next?value=4');
    expect(response.status).toBe(200);
    expect(await response.json(), 'LEVEL_D_NEGATIVE_CONTROL').toEqual({ count: 5 });
  });
  it('rejects invalid input without claiming a successful increment', async () => {
    for (const value of ['no', '-1', '1.5', '']) {
      const response = await fetch(baseUrl + '/api/next?value=' + value);
      expect(response.status).toBe(400);
      expect(await response.json()).toHaveProperty('error');
    }
  });
});
