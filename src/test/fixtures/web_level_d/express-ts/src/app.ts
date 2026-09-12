import express from 'express';
import { increment } from './counter.js';

export const app = express();
app.disable('x-powered-by');
app.get('/health', (_request, response) => { response.json({ status: 'ok' }); });
app.get('/api/next', (request, response) => {
  const raw = request.query.value;
  const value = typeof raw === 'string' && raw.trim() !== '' ? Number(raw) : NaN;
  if (!Number.isSafeInteger(value) || value < 0 || value > 999999) {
    response.status(400).json({ error: 'A count from 0 to 999999 is required' });
    return;
  }
  response.json({ count: increment(value) });
});
