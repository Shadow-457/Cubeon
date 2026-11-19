'use strict';
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const body = readFileSync(join(__dirname, '../404.html'));
module.exports = function retired(req, res) {
  res.statusCode = 410;
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Content-Length', body.length);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Robots-Tag', 'noindex');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.end(req.method === 'HEAD' ? undefined : body);
};
