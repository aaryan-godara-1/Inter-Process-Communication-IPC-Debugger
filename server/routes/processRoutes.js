const express = require('express');

function createProcessRoutes(runner) {
  const router = express.Router();

  router.post('/process', (req, res) => {
    try {
      const process = runner.createProcess(req.body || {});
      res.status(201).json({ success: true, process, state: runner.getState() });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  return router;
}

module.exports = createProcessRoutes;
