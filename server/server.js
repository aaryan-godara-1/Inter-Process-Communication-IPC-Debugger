const express = require('express');
const http = require('http');
const path = require('path');
const WebSocket = require('ws');

const { createSimulationRunner } = require('./simulation/simulationRunner');
const { createLiveTelemetryStream } = require('./live/liveTelemetry');
const createProcessRoutes = require('./routes/processRoutes');
const createResourceRoutes = require('./routes/resourceRoutes');
const createSimulationRoutes = require('./routes/simulationRoutes');

const app = express();
const server = http.createServer(app);
const clientDir = path.join(__dirname, '..', 'client');
const frontendDir = path.join(__dirname, '..', 'frontend');
const liveSubscribers = new Set();

app.use(express.json({ limit: '1mb' }));
app.use(express.static(clientDir));

app.get('/app.js', (req, res) => {
  res.sendFile(path.join(frontendDir, 'app.js'));
});

app.get('/favicon.ico', (req, res) => {
  res.status(204).end();
});

const wss = new WebSocket.Server({ server, path: '/ws' });

const broadcast = (message) => {
  const payload = JSON.stringify(message);
  for (const client of wss.clients) {
    if (client.readyState !== WebSocket.OPEN) {
      continue;
    }

    if (message && message.type === 'live:update' && !liveSubscribers.has(client)) {
      continue;
    }

    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  }
};

const runner = createSimulationRunner(broadcast);
const liveStream = createLiveTelemetryStream({ broadcast });

app.use('/api', createProcessRoutes(runner));
app.use('/api', createResourceRoutes(runner));
app.use('/api', createSimulationRoutes(runner));

app.get('/', (req, res) => {
  res.sendFile(path.join(clientDir, 'index.html'));
});

wss.on('connection', (socket) => {
  socket.send(JSON.stringify({ type: 'state:update', payload: runner.getState() }));
  socket.send(JSON.stringify({ type: 'live:update', payload: liveStream.getSnapshot() }));

  socket.on('message', (raw) => {
    try {
      const msg = JSON.parse(String(raw || '{}'));
      if (msg && msg.type === 'live:mode') {
        const enabled = msg.enabled === true || msg.enabled === 'true' || msg.enabled === 1;
        if (enabled) {
          liveSubscribers.add(socket);
        } else {
          liveSubscribers.delete(socket);
        }
        liveStream.setSubscribers(liveSubscribers.size);
      }
    } catch {
      // Ignore malformed websocket payloads from clients.
    }
  });

  socket.on('close', () => {
    liveSubscribers.delete(socket);
    liveStream.setSubscribers(liveSubscribers.size);
  });
});

const port = process.env.PORT || 3000;
server.listen(port, () => {
  console.log(`IPC Debugger Simulator running on http://localhost:${port}`);
});
