const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const ts = require('../frontend/node_modules/typescript');

function loadModule(relative) {
  const filename = path.join(__dirname, '../frontend', relative);
  const source = fs.readFileSync(filename, 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const module = { exports: {} };
  const localRequire = createRequire(filename);
  const componentRequire = (id) => {
    if (id.startsWith('.')) {
      const base = path.resolve(path.dirname(filename), id);
      const target = [base, `${base}.ts`, `${base}.tsx`].find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
      if (target && /\.tsx?$/.test(target)) return loadModule(path.relative(path.join(__dirname, '../frontend'), target));
    }
    return localRequire(id);
  };
  vm.runInNewContext(output, { module, exports: module.exports, require: componentRequire, process }, { filename });
  return module.exports;
}

const provider = (value = 'openai') => ({ value, label: value, base_url: `https://${value}.example`,
  requires_api_key: true, supports_custom_models: true,
  quick_models: [{ value: 'quick-one', label: 'Quick one' }, { value: 'quick-two', label: 'Quick two' }],
  deep_models: [{ value: 'deep-one', label: 'Deep one' }] });

function configured(api) {
  let state = api.providerSettingsReducer(api.initialProviderSettings, { type: 'select', provider: provider() });
  return api.providerSettingsReducer(state, { type: 'edit', field: 'apiKey', value: 'test-key' });
}

test('switching providers clears the previous key and connection result', () => {
  const api = loadModule('lib/provider-settings.ts');
  let state = configured(api);
  state = api.providerSettingsReducer(state, { type: 'validation-finished', revision: state.revision,
    result: { valid: true, provider: 'openai', model: 'quick-one', message: 'Connected' } });
  state = api.providerSettingsReducer(state, { type: 'select', provider: provider('anthropic') });
  assert.equal(state.apiKey, '');
  assert.equal(state.validationResult, null);
  assert.equal(state.baseUrl, 'https://anthropic.example');
  assert.equal(state.provider, 'anthropic');
});

test('key, endpoint and model edits invalidate a previous connection check', () => {
  const api = loadModule('lib/provider-settings.ts');
  for (const field of ['apiKey', 'baseUrl', 'quickModel', 'deepModel', 'quickCustom', 'deepCustom']) {
    let state = configured(api);
    state = api.providerSettingsReducer(state, { type: 'validation-finished', revision: state.revision,
      result: { valid: true, provider: 'openai', model: 'quick-one', message: 'Connected' } });
    const oldRevision = state.revision;
    state = api.providerSettingsReducer(state, { type: 'edit', field, value: 'changed' });
    assert.equal(state.validationResult, null, field);
    assert.ok(state.revision > oldRevision, field);
  }
});

test('changing models preserves a custom endpoint', () => {
  const api = loadModule('lib/provider-settings.ts');
  let state = configured(api);
  state = api.providerSettingsReducer(state, { type: 'edit', field: 'baseUrl', value: 'http://localhost:9000/v1' });
  state = api.providerSettingsReducer(state, { type: 'edit', field: 'quickModel', value: 'quick-two' });
  state = api.providerSettingsReducer(state, { type: 'edit', field: 'deepModel', value: 'custom' });
  assert.equal(state.baseUrl, 'http://localhost:9000/v1');
});

test('an old successful connection response cannot validate a newly edited key', () => {
  const api = loadModule('lib/provider-settings.ts');
  let state = configured(api);
  const revision = state.revision;
  state = api.providerSettingsReducer(state, { type: 'validation-started', revision });
  state = api.providerSettingsReducer(state, { type: 'edit', field: 'apiKey', value: 'different-key' });
  state = api.providerSettingsReducer(state, { type: 'validation-finished', revision,
    result: { valid: true, provider: 'openai', model: 'quick-one', message: 'Connected' } });
  assert.equal(state.validationResult, null);
  assert.equal(state.isValidatingKey, false);
});

test('progress follows actual agents, and completion means waiting for human review', () => {
  const { researchPhase } = loadModule('lib/research-view.ts');
  assert.equal(researchPhase({ status: 'running', current_agent: 'News Analyst', agents: [] }).index, 1);
  assert.equal(researchPhase({ status: 'running', current_agent: 'Bear Researcher', agents: [] }).index, 2);
  assert.equal(researchPhase({ status: 'running', current_agent: 'Portfolio Manager', agents: [] }).index, 3);
  assert.equal(researchPhase({ status: 'completed', review: { status: 'pending' } }).label, 'Awaiting review');
  assert.equal(researchPhase({ status: 'completed', review: { status: 'approved' } }).label, 'Approved');
});

test('an analysis failure is kept separate from an unavailable progress connection', () => {
  const { researchPhase } = loadModule('lib/research-view.ts');
  assert.equal(researchPhase({ status: 'error', current_agent: 'Trader' }).failed, true);
  assert.equal(researchPhase({ status: 'running', current_agent: 'Trader' }).failed, false);
});

test('history filters by review status and searches ticker, date and version', () => {
  const { filterReviews } = loadModule('lib/research-view.ts');
  const rows = [
    { run_id: 'one', ticker: 'NVDA', analysis_date: '2026-10-25', review: { status: 'pending', version: 2 } },
    { run_id: 'two', ticker: 'AAPL', analysis_date: '2026-10-24', review: { status: 'approved', version: 1 } },
  ];
  assert.equal(filterReviews(rows, 'pending', '').length, 1);
  assert.equal(filterReviews(rows, 'all', 'nvda')[0].run_id, 'one');
  assert.equal(filterReviews(rows, 'approved', 'nvda').length, 0);
  assert.equal(filterReviews(rows, 'all', 'v2')[0].run_id, 'one');
});

test('report text renders useful formatting while keeping raw HTML inert', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ReportText } = loadModule('components/report-text.tsx');
  const html = renderToStaticMarkup(React.createElement(ReportText, {
    text: '# Findings\n\n**Evidence matters**\n\n- Check E1\n- Unresolved E9\n\n<script>alert(1)</script>',
    evidenceIds: ['E1'], evidencePrefix: 'run-one',
  }));
  assert.match(html, /<h4[^>]*>Findings<\/h4>/);
  assert.match(html, /<strong>Evidence matters<\/strong>/);
  assert.match(html, /<ul>/);
  assert.match(html, /href="#run-one-evidence-E1"/);
  assert.doesNotMatch(html, /href="[^"]*E9/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test('structured research summary shows the conclusion and risks before review', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchReport } = loadModule('components/research-report.tsx');
  const html = renderToStaticMarkup(React.createElement(ResearchReport, {
    snapshot: { run_id: 'one', ticker: 'NVDA', status: 'completed', review: { status: 'pending', version: 1 },
      final_signal: 'No Recommendation', final_decision: 'Legacy report',
      final_structured_decision: { decision_status: 'No Recommendation', executive_summary: 'Wait for stronger evidence.',
        key_risks: ['Evidence is incomplete.'], evidence_gap: 'Need a current filing.',
        core_claims: [{ claim: 'Sales improved.', evidence_ids: ['E1'] }] },
      evidence_ledger: [{ evidence_id: 'E1' }] },
    onOpenReport() {}, onExport() {},
  }));
  assert.match(html, /Wait for stronger evidence/);
  assert.match(html, /Evidence is incomplete/);
  assert.match(html, /Need a current filing/);
  assert.match(html, /Awaiting review/);
  assert.doesNotMatch(html, /Approve report/);
});


test('workbench puts company and language before provider, with advanced settings collapsed', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchWorkbench } = loadModule('components/research-workbench.tsx');
  const html = renderToStaticMarkup(React.createElement(ResearchWorkbench));
  assert.ok(html.indexOf('Company or ticker') < html.indexOf('AI provider'));
  assert.ok(html.indexOf('Report language') < html.indexOf('AI provider'));
  assert.match(html, /<details class="advancedSettings">/);
  assert.doesNotMatch(html, /<details[^>]*class="advancedSettings"[^>]*open/);
  assert.match(html, /Saved reports/);
  assert.match(html, /Search saved reports/);
});

test('completed analysis leaves pending human review as the current stage', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchProgress } = loadModule('components/research-progress.tsx');
  const html = renderToStaticMarkup(React.createElement(ResearchProgress, {
    snapshot: {status: 'completed', review: {status: 'pending'}, started_at: '2026-10-27T01:00:00Z', finished_at: '2026-10-27T01:01:02Z'},
    running: false, streamState: 'finished', onReconnect() {},
  }));
  assert.match(html, /class=" current " aria-current="step"><span[^>]*>5<\/span>Human review/);
  assert.match(html, /1m 2s/);
});


test('legacy reports retain evidence and validation even without a human review record', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { HumanReviewPanel } = loadModule('components/human-review.tsx');
  const html = renderToStaticMarkup(React.createElement(HumanReviewPanel, {
    snapshot: {run_id: 'legacy', status: 'completed', final_decision: 'Research summary', review: null,
      report_verification: {status: 'pass'}, evidence_ledger: [{evidence_id: 'E1', claim: 'Current evidence'}]},
    apiBaseUrl: 'http://localhost', running: false, onOpenRun() {}, onSnapshot() {}, onRevision() {},
  }));
  assert.match(html, /id="legacy-evidence-E1"/);
  assert.match(html, /Current evidence/);
  assert.match(html, /Automated checks: pass/);
  assert.doesNotMatch(html, /Approve report/);
});
