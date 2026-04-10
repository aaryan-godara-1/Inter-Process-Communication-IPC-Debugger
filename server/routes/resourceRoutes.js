const express = require('express');

function createResourceRoutes(runner) {
  const router = express.Router();

  router.post('/resource', (req, res) => {
    try {
      const resource = runner.createResource(req.body || {});
      res.status(201).json({ success: true, resource, state: runner.getState() });
    } catch (error) {
      res.status(400).json({ success: false, error: error.message });
    }
  });

  return router;
}

module.exports = createResourceRoutes;
