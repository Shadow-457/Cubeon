'use strict';
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const codes = [403, 404, 429, 500, 502, 503];
const pages = new Map(codes.map(code => [code, readFileSync(join(__dirname, '../' + code + '.html'))]));
module.exports = function status(req, res) {
  const requested = Number(new URL(req.url, 'https://cubeon.invalid').searchParams.get('code'));
  const code = pages.has(requested) ? requested : 404;
  const body = pages.get(code);
  res.statusCode = code;
  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Content-Length', body.length);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Robots-Tag', 'noindex');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.end(req.method === 'HEAD' ? undefined : body);
};
