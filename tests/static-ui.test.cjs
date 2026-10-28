const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function app() {
  const elements = new Map();
  function element() {
    return { value: '', textContent: '', innerHTML: '', hidden: false, dataset: {}, children: [], listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
      appendChild(child) { this.children.push(child); if (!this.value && child.value) this.value = child.value; },
      append(child) { this.appendChild(child); }, replaceChildren(...children) { this.children = children; },
      setAttribute(key, value) { this[key] = value; },
    };
  }
  function $(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }
  const requests = [], sources = [], alerts = [];
  const context = vm.createContext({ $, document: { getElementById: $, createElement: element, querySelectorAll: () => [] },
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve(payload) { resolve({ ok: true, text: async () => JSON.stringify(payload) }); }, reject })),
    EventSource: class { constructor(url) { this.url = url; this.listeners = {}; sources.push(this); } addEventListener(type, fn) { this.listeners[type] = fn; } close() { this.closed = true; } },
    localStorage: { setItem() {} }, alert: message => alerts.push(message),
    window: { setTimeout() {}, clearTimeout() {}, setInterval() { return 1; }, clearInterval() {} },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../marketmind_ai/web/static/app.js'), 'utf8').replace(/bootstrap\(\);\s*$/, ''), context);
  vm.runInContext(`state.providers = [{ value: 'openai', label: 'OpenAI', requires_api_key: true, quick_models: [{ value: 'a', label: 'A' }], deep_models: [{ value: 'b', label: 'B' }] }, { value: 'offline', label: 'Offline', requires_api_key: false, quick_models: [{ value: 'fixture', label: 'Fixture' }], deep_models: [{ value: 'fixture', label: 'Fixture' }] }];`, context);
  $('providerSelect').value = 'openai'; $('quickModelSelect').value = 'a'; $('deepModelSelect').value = 'b';
  context.bindEvents();
  return { context, $, requests, sources, alerts };
}

test('switching providers clears credentials and the previous connection result', () => {
  const { $, context } = app();
  $('apiKeyInput').value = 'previous-provider-secret'; $('providerStatus').textContent = 'Connected';
  $('providerSelect').value = 'offline'; $('providerSelect').listeners.change();
  assert.equal($('apiKeyInput').value, '');
  assert.notEqual($('providerStatus').textContent, 'Connected');
  assert.match($('apiKeyHelpText').textContent, /fixture|demo/i);
});

test('credential, URL and model edits invalidate connection status while model changes preserve a custom URL', () => {
  const { $ } = app();
  for (const [id, event] of [['apiKeyInput', 'input'], ['baseUrlInput', 'input'], ['quickModelCustomInput', 'input'], ['deepModelCustomInput', 'input'], ['quickModelSelect', 'change'], ['deepModelSelect', 'change']]) {
    $('providerStatus').textContent = 'Connected'; $('baseUrlInput').value = 'https://custom.example/v1';
    if (event === 'input') assert.equal(typeof $(id).listeners.input, 'function', id);
    $(id).listeners[event]();
    assert.notEqual($('providerStatus').textContent, 'Connected', id);
    assert.equal($('baseUrlInput').value, 'https://custom.example/v1');
  }
});

test('stale provider validation cannot apply after credentials change', async () => {
  const { context, $, requests, alerts } = app();
  $('apiKeyInput').value = 'old';
  const old = context.validateProvider();
  $('apiKeyInput').value = 'new'; $('apiKeyInput').listeners.input?.();
  const latest = context.validateProvider();
  requests[1].resolve({ message: 'Current connection verified' }); await latest;
  requests[0].resolve({ message: 'Stale connection verified' }); await old;
  assert.equal($('providerStatus').textContent, 'Current connection verified');
  assert.deepEqual(alerts, []);
});

test('stream transport errors show reconnecting without treating the run as failed', () => {
  const { context, $, sources, alerts } = app();
  vm.runInContext(`state.runId = 'run';`, context);
  context.connectRunStream('run'); sources[0].listeners.error({});
  assert.equal(sources[0].closed, undefined);
  assert.match($('streamStatus').textContent, /reconnect/i);
  sources[0].listeners.run_error({ data: JSON.stringify({ message: 'Model run failed' }) });
  assert.equal(sources[0].closed, true);
  assert.match($('streamStatus').textContent, /Model run failed/);
  assert.deepEqual(alerts, []);
});

test('readable report formatting escapes HTML before adding headings, lists and bold', () => {
  const { context } = app();
  assert.equal(typeof context.renderReportText, 'function');
  const html = context.renderReportText('# Outlook\n\n- **Growth** remains strong\n- <img src=x onerror=alert(1)>\n\n<script>alert(1)</script>');
  assert.match(html, /<h4>Outlook<\/h4>/);
  assert.match(html, /<strong>Growth<\/strong>/);
  assert.match(html, /<ul>/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img|<script/);
});

test('phase progress reflects snapshot agents and verification rather than percentages', () => {
  const { context, $ } = app();
  assert.equal(typeof context.renderRunProgress, 'function');
  context.renderRunProgress({ status: 'running', started_at: new Date(Date.now() - 65000).toISOString(), current_agent: 'Market Analyst', agents: [{ label: 'Market Analyst', status: 'in_progress' }] });
  assert.match($('runPhase').textContent, /Market Analyst/);
  assert.match($('elapsedTime').textContent, /1m/);
  assert.doesNotMatch($('runPhase').textContent, /%/);
  context.renderRunProgress({ status: 'completed', agents: [], report_verification: { status: 'pass' } });
  assert.match($('runPhase').textContent, /review/i);
});

test('structured decision summary includes reasons, risks and evidence gap safely', () => {
  const { context, $ } = app();
  assert.equal(typeof context.renderDecisionSummary, 'function');
  context.renderDecisionSummary({ final_structured_decision: { executive_summary: 'A readable conclusion', investment_thesis: 'Growth supports value', key_risks: ['<script>risk</script>'], evidence_gap: 'Missing a current filing', confidence: 70, decision_status: 'Actionable' } });
  assert.equal($('finalSummary').textContent, 'A readable conclusion');
  assert.match($('decisionDetails').innerHTML, /Growth supports value/);
  assert.match($('decisionDetails').innerHTML, /&lt;script&gt;risk/);
  assert.match($('decisionDetails').innerHTML, /Missing a current filing/);
});

test('server error events with data are run failures, and terminal snapshots stop reconnecting', () => {
  const { context, $, sources } = app();
  vm.runInContext(`state.runId = 'run';`, context);
  context.connectRunStream('run');
  sources[0].listeners.error({ data: JSON.stringify({ message: 'Provider quota exhausted' }) });
  assert.equal(sources[0].closed, true);
  assert.match($('streamStatus').textContent, /Provider quota exhausted/);
  context.connectRunStream('run');
  sources[1].listeners.snapshot({ data: JSON.stringify({ run_id: 'run', status: 'error', error: 'Failed', agents: [] }) });
  assert.equal(sources[1].closed, true);
  sources[1].listeners.error({});
  assert.doesNotMatch($('streamStatus').textContent, /reconnect/i);
});

test('report citations link only evidence IDs present in the current ledger', () => {
  const { context } = app();
  const html = context.renderReportText('**Claim [E1]** and E2; unknown E99. <img src=x onerror=alert(1)>', ['E1', 'E2']);
  assert.match(html, /href="#evidence-E1"[^>]*>E1<\/a>/);
  assert.match(html, /href="#evidence-E2"[^>]*>E2<\/a>/);
  assert.doesNotMatch(html, /href="#evidence-E99"|<img/);
  assert.match(html, /unknown E99/);
});

test('supporting reasons link their valid evidence IDs to matching evidence table rows', () => {
  const { context, $ } = app();
  const snapshot = { run_id: 'run', status: 'completed', provider: 'offline', evidence_ledger: [{ evidence_id: 'E1', claim: 'Revenue grew' }], final_structured_decision: { core_claims: [{ claim: 'Growth supports value', evidence_ids: ['E1', 'E99'] }], key_risks: [] } };
  context.renderDecisionSummary(snapshot);
  assert.match($('decisionDetails').innerHTML, /Growth supports value/);
  assert.match($('decisionDetails').innerHTML, /href="#evidence-E1"/);
  assert.doesNotMatch($('decisionDetails').innerHTML, /href="#evidence-E99"/);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../marketmind_ai/web/static/human-review.js'), 'utf8'), context);
  vm.runInContext(`state.snapshot = ${JSON.stringify(snapshot)}`, context);
  context.renderHumanReview(snapshot);
  assert.match($('reviewEvidenceBody').innerHTML, /<tr id="evidence-E1" tabindex="-1">/);
});

test('clicking an evidence link opens its containing details then focuses and scrolls to the row', () => {
  const { context, $ } = app();
  let prevented = false, scrolled = false, focused = false;
  const outer = { open: false, parentElement: null };
  const details = { open: false, parentElement: { closest: () => outer } };
  $('evidence-E1').closest = () => details;
  $('evidence-E1').scrollIntoView = () => { scrolled = true; };
  $('evidence-E1').focus = () => { focused = true; };
  assert.equal(typeof $('reports').listeners.click, 'function');
  $('reports').listeners.click({ target: { closest: () => ({ dataset: { evidenceId: 'E1' } }) }, preventDefault() { prevented = true; } });
  assert.equal(details.open, true);
  assert.equal(outer.open, true);
  assert.equal(prevented && scrolled && focused, true);
});

test('human review phase remains current until a reviewer approves the report', () => {
  const { context, $ } = app();
  for (const status of ['pending', 'rejected', 'changes_requested']) {
    context.renderRunProgress({ status: 'completed', review: { status }, agents: [] });
    assert.match($('phaseSteps').innerHTML, /data-phase-status="In progress"><span>Human review<\/span>/, status);
    assert.doesNotMatch($('phaseSteps').innerHTML, /data-phase-status="Complete"><span>Human review<\/span>/, status);
  }
  context.renderRunProgress({ status: 'completed', review: { status: 'approved' }, agents: [] });
  assert.match($('phaseSteps').innerHTML, /data-phase-status="Complete"><span>Human review<\/span><small>Approved<\/small>/);
  assert.match($('runPhase').textContent, /approved/i);
});
