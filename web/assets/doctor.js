/* Logs stay in page memory. File upload or Analyze explicitly starts AI analysis. */
(function () {
  'use strict';
  const D = window.CubeonDoctor;
  const $ = id => document.getElementById(id);
  // Consume the private fragment before any external request.
  const initialFragment = location.hash;
  if (initialFragment.startsWith('#report=')) history.replaceState(null, '', location.pathname + location.search);
  let revision = 0, controller = null, diagnosis = null;
  let context = {}, reading = false;
  const normalLabel = 'Analyze log →';
  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined) el.textContent = value;
    if (className) el.className = className;
    return el;
  }
  function status(message) { $('doctor-status').textContent = message; }
  function revealResult() {
    if (diagnosis) {
      $('doctor-result').scrollIntoView({behavior:'instant', block:'start'});
    }
  }
  function busy(value) {
    $('ai-check').disabled = value || reading;
    $('local-check').disabled = reading;
    $('cancel-check').hidden = !value;
    $('doctor-output').setAttribute('aria-busy', String(value));
  }
  function invalidate() {
    revision++;
    if (controller) controller.abort();
    controller = null;
    busy(false);
    $('ai-check').textContent = normalLabel;
  }
  function empty() {
    diagnosis = null;
    $('doctor-result').hidden = true;
    $('doctor-empty').hidden = false;
  }
  function preview(raw, label, truncated = false) {
    const redacted = D.redactLog(raw);
    $('log-text').value = D.excerpt(redacted);
    $('file-note').textContent = label + (truncated || redacted.length > D.MAX_LOG
      ? ' · Showing a redacted tail excerpt; keep the full log for any missing context.'
      : ' · Common private details redacted.');
  }
  function local() {
    const log = D.excerpt($('log-text').value);
    if (!log.trim()) { empty(); status('Choose a log file or paste the error first.'); return null; }
    preview($('log-text').value, 'Current log');
    const result = D.localDiagnosis(log);
    render(result);
    status('On-device instructions are ready.');
    return log;
  }
  // Render the supported Markdown subset as DOM nodes, never raw HTML.
  function inlineMarkdown(value) {
    const fragment = document.createDocumentFragment();
    const pattern = /\*\*([^*\n]+)\*\*|`([^`\n]+)`/g;
    let start = 0;
    for (const match of String(value).matchAll(pattern)) {
      fragment.append(document.createTextNode(value.slice(start, match.index)));
      fragment.append(node(match[1] === undefined ? 'code' : 'strong', match[1] ?? match[2]));
      start = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(value.slice(start)));
    return fragment;
  }
  function markdownParagraphs(value) {
    return String(value).split(/\n\s*\n/).map(text => {
      const p = node('p'); p.append(inlineMarkdown(text)); return p;
    });
  }
  function render(result) {
    diagnosis = result;
    $('doctor-empty').hidden = true;
    $('doctor-result').hidden = false;
    $('result-source').textContent = result.source === 'ai' ? 'AI analysis' : 'On-device check';
    $('result-cause').textContent = result.cause;
    $('result-evidence').replaceChildren(...(result.evidence.length
      ? result.evidence.map(line => node('pre', line))
      : [node('p', 'No clear error line found. Try the complete crash report.')]));
    $('result-verify').replaceChildren(inlineMarkdown(result.verify));
    $('result-rollback').replaceChildren(inlineMarkdown(result.rollback));
    $('guide-steps').replaceChildren(...result.steps.map(step => {
      const li = node('li'), title = node('h4');
      title.append(inlineMarkdown(step.title));
      li.append(title, ...markdownParagraphs(step.instruction));
      if (step.action === 'graphics') {
        const links = node('p', 'Official drivers: ', 'doc-external-links');
        [['NVIDIA', 'https://www.nvidia.com/Download/index.aspx'], ['AMD', 'https://www.amd.com/en/support'],
          ['Intel', 'https://www.intel.com/content/www/us/en/download-center/home.html']].forEach(([name, url], i) => {
            if (i) links.append(document.createTextNode(' · '));
            const a = node('a', name); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; links.append(a);
          });
        li.append(links);
      }
      return li;
    }));
  }
  async function file(file) {
    if (!file) return;
    reading = false;
    invalidate(); empty(); context = {};
    const run = revision;
    $('log-text').value = ''; $('file-note').textContent = '';
    if (file.size > 2 * 1024 * 1024) { status('This file is over 2 MB. Choose a smaller crash report or paste the error section.'); return; }
    if (!/\.(?:log|txt)$/i.test(file.name)) { status('Choose a plain .log or .txt file.'); return; }
    reading = true; busy(false); status('Reading the log on your device…');
    try {
      const value = await file.text();
      if (run !== revision) return;
      if (value.includes('\0')) throw new Error('binary');
      preview(value, file.name);
      const note = $('file-note').textContent;
      local(); $('file-note').textContent = note;
    } catch (_) { if (run === revision) status('This file could not be read as a text log. Try pasting the error.'); }
    finally { if (run === revision) { reading = false; busy(false); } }
    if (run === revision && diagnosis) await analyze();
  }
  async function analyze() {
    if (controller || reading) return;
    const note = $('file-note').textContent;
    const log = local(); if (!log) return;
    if (note) $('file-note').textContent = note;
    const run = revision;
    const current = new AbortController(); controller = current;
    busy(true); $('ai-check').textContent = 'Analyzing…';
    status('Analyzing your log… This can take up to a minute.');
    try {
      const result = await D.analyzeViaEndpoint(log, context, {signal:current.signal});
      if (run !== revision) return;
      render(result); status('Your instructions are ready.'); revealResult();
    } catch (error) {
      if (run !== revision) return;
      const code = String(error && error.message || '');
      const waitMinutes = Math.ceil((error.retryAfter || 1800)/60);
      const provider = error.provider === 'groq' ? 'Groq' : error.provider === 'kilo' ? 'Kilo' : 'The AI provider';
      const reasons = {
        ai_busy:'AI is busy right now. Try again shortly.',
        ai_not_configured:'AI is not configured on this server. The site owner needs to enable it for this deployment.',
        ai_credentials_invalid:provider + ' rejected the server’s API key. The site owner needs to check the server credential.',
        ai_quota_exhausted:provider + ' refused the request because account credits or quota are unavailable.',
        ai_request_rejected:provider + ' rejected Doctor’s request. The site owner needs to check the AI integration.',
        ai_timeout:provider + ' did not finish within the time limit. Try AI again later.',
        request_timeout:'The AI request timed out. Try AI again later.',
        ai_bad_response:provider + ' returned a response that could not be turned into reliable repair instructions. Try AI again later.',
        ai_provider_unavailable:provider + ' could not complete the request. Try AI again later.',
        request_failed:'The AI endpoint could not be reached on this site. The site owner needs to check the deployment.'
      };
      status(/cancelled/i.test(code) ? 'Analysis stopped. The on-device instructions are still below.'
        : code === 'rate_limited' && error.scope === 'visitor' ? 'You’ve used your 3 AI requests for this 30-minute window. Try again in ' + waitMinutes + ' minute' + (waitMinutes === 1 ? '' : 's') + '. On-device instructions are still available.'
        : /rate_limited/i.test(code) ? 'AI is busy. On-device instructions are below; try AI again later.'
        : Object.hasOwn(reasons,code) ? reasons[code] + ' On-device instructions are still below.'
        : 'AI is unavailable. On-device instructions are below; try AI again later.');
      revealResult();
    } finally {
      if (controller === current) {
        controller = null; busy(false); $('ai-check').textContent = normalLabel;
      }
    }
  }
  $('ai-check').addEventListener('click', analyze);
  $('cancel-check').addEventListener('click', () => { if (controller) controller.abort(); });
  $('local-check').addEventListener('click', () => { invalidate(); local(); revealResult(); });
  $('log-file').addEventListener('change', event => file(event.target.files[0]));
  ['dragenter', 'dragover'].forEach(name => $('drop-zone').addEventListener(name, event => {
    event.preventDefault(); $('drop-zone').classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach(name => $('drop-zone').addEventListener(name, event => {
    event.preventDefault(); $('drop-zone').classList.remove('dragging');
    if (name === 'drop') file(event.dataTransfer.files[0]);
  }));
  $('log-text').addEventListener('input', () => {
    reading = false; invalidate(); empty(); context = {};
    $('file-note').textContent = 'Edited log · Common private details will be redacted before analysis.';
    status('Log changed. Run a fresh check for this preview.');
  });
  $('log-text').addEventListener('paste', event => {
    const text = event.clipboardData && event.clipboardData.getData('text');
    if (text === undefined || text === null) return;
    event.preventDefault();
    const input = $('log-text');
    const value = input.value.slice(0,input.selectionStart) + text + input.value.slice(input.selectionEnd);
    reading = false; invalidate(); empty(); context = {}; preview(value, 'Pasted log');
    $('log-editor').open = true; status('Log ready. Choose Analyze log for your instructions.');
  });
  $('clear-log').addEventListener('click', () => {
    reading = false; invalidate(); empty(); context = {};
    $('log-text').value = ''; $('log-file').value = ''; $('log-editor').open = false;
    $('file-note').textContent = 'Common private details are removed before analysis.';
    status('Log cleared from this page.');
  });
  $('download-result').addEventListener('click', () => {
    if (!diagnosis) return;
    const lines = ['# Cubeon Doctor', '', diagnosis.cause, '', '## How to fix it'];
    diagnosis.steps.forEach((s, i) => lines.push('', (i+1) + '. **' + s.title + '**', '', ...s.instruction.split('\n').map(line => '   ' + line)));
    lines.push('', '## Check it worked', diagnosis.verify, '', '## Undo a change', diagnosis.rollback, '', '## Error lines', ...diagnosis.evidence.map(line => '> ' + line));
    const url = URL.createObjectURL(new Blob([lines.join('\n')], {type:'text/markdown;charset=utf-8'}));
    const a = node('a'); a.href = url; a.download = 'cubeon-doctor-guide.md'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  const examples = {
    memory: '[Render thread/ERROR]: java.lang.OutOfMemoryError: Java heap space',
    java: 'java.lang.UnsupportedClassVersionError: class file version 65.0, this runtime only recognizes up to 61.0',
    mods: "Mod 'Example Mod' requires fabric-api, which is missing!"
  };
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => {
    reading = false; invalidate(); context = {}; preview(examples[button.dataset.example], 'Example log'); local(); revealResult();
  }));
  async function importReport(fragment) {
    if (!fragment.startsWith('#report=')) return;
    const run = revision;
    reading = true; busy(false); status('Opening the launcher’s redacted report…');
    try {
      const encoded = fragment.slice(8);
      if (!/^[A-Za-z0-9_-]+$/.test(encoded) || encoded.length > 20000) throw new Error('invalid_report');
      if (!window.DecompressionStream) throw new Error('unsupported_browser');
      const bytes = Uint8Array.from(atob(encoded.replace(/-/g,'+').replace(/_/g,'/')), c => c.charCodeAt(0));
      const reader = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate')).getReader();
      const chunks = []; let total = 0;
      try {
        while (true) {
          const {value, done} = await reader.read(); if (done) break;
          total += value.byteLength;
          if (total > 280000) throw new Error('report_too_large');
          chunks.push(value);
        }
      } finally { await reader.cancel().catch(() => {}); }
      const report = JSON.parse(await new Blob(chunks).text());
      if (report.v !== 1 || typeof report.log !== 'string' || report.log.length > D.MAX_LOG) throw new Error('invalid_report');
      if (run !== revision) return;
      context = {version:D.redactLog(typeof report.version === 'string' ? report.version.slice(0,240) : '')};
      preview(report.log, 'From Cubeon' + (context.version ? ' · ' + context.version : ''), report.truncated === true);
      const note = $('file-note').textContent;
      local(); $('file-note').textContent = note;
      $('log-editor').open = true; status('Launcher log loaded. On-device instructions are below. Choose Analyze log for AI.');
      revealResult();
    } catch (_) {
      if (run === revision) status('The launcher report could not be opened in this browser. Use Copy log in Cubeon, then paste it here.');
    } finally { if (run === revision) { reading = false; busy(false); } }
  }
  window.addEventListener('hashchange', () => {
    const fragment = location.hash;
    if (!fragment.startsWith('#report=')) return;
    history.replaceState(null, '', location.pathname + location.search);
    reading = false; invalidate(); empty(); context = {};
    importReport(fragment);
  });
  importReport(initialFragment);
})();
