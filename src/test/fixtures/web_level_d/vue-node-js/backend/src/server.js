import { app } from './app.js';
const server = app.listen(3000, '0.0.0.0');
server.on('error', error => { console.error(error); process.exitCode = 1; });
