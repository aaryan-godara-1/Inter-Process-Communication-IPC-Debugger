const express = require('express');

function createSimulationRoutes(runner) {
  const router = express.Router();

  router.get('/health', (req, res) => {
    res.json({ status: 'ok', uptime: process.uptime() });
  });

  router.get('/state', (req, res) => {
    res.json(runner.getState());
  });

  router.post('/request', (req, res) => {
    try {
      const state = runner.requestResource(req.body || {});
      res.json({ success: true, state });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  router.post('/release', (req, res) => {
    try {
      const state = runner.releaseResource(req.body || {});
      res.json({ success: true, state });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  router.post('/start', (req, res) => {
    try {
      const state = runner.start(req.body || {});
      res.json({ success: true, state });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  router.post('/pause', (req, res) => {
    try {
      const state = runner.pause();
      res.json({ success: true, state });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  router.post('/step', (req, res) => {
    try {
      const state = runner.step();
      res.json({ success: true, state });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  router.post('/reset', (req, res) => {
    try {
      const state = runner.reset();
      res.json({ success: true, state });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  return router;
}

module.exports = createSimulationRoutes;
