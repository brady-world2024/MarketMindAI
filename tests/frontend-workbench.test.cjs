const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const ts = require('../frontend/node_modules/typescript');
const preflight = require('./preflight-fixtures.cjs');

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

test('the progress card shows the saved cutoff and data coverage before AI starts', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchProgress } = loadModule('components/research-progress.tsx');
  const render = (snapshot, running, streamState = 'live') => renderToStaticMarkup(React.createElement(
    ResearchProgress, { snapshot, running, streamState, onReconnect() {} },
  ));
  assert.match(render(null, true), /Checking required data/);
  const passed = render(preflight.passed, true);
  for (const value of ['Data preflight passed', '2026-07-04', '2026-07-02', '16:00', 'America/New_York',
    '63 / 50 valid daily bars', 'Income statement', 'Balance sheet', 'Cash flow statement',
    '2026-03-31', 'SEC', 'Optional', 'No news with a verified publication time']) assert.ok(passed.includes(value), value);
  assert.doesNotMatch(passed, /No recommendation/);
  const blocked = render(preflight.blocked, false);
  assert.match(blocked, /Required data incomplete/);
  assert.match(blocked, /No recommendation/);
  assert.match(blocked, /Cash flow statement is missing/);
  assert.match(blocked, /href="#research-data-sources"/);
  assert.doesNotMatch(blocked, /<unsafe reason>/);
  const interrupted = render({ status: 'error', job_status: 'interrupted', research_cutoff: preflight.cutoff }, false);
  assert.match(interrupted, /Preflight result unavailable/);
  assert.doesNotMatch(interrupted, /Checking required data|Required data incomplete/);
  assert.match(render({ ...preflight.passed, data_mode: 'demo' }, true, 'reconnecting'), /Demo data/);
  const unsupported = render({ ...preflight.blocked, data_availability: {
    can_recommend: false, ai_analysis_performed: false, missing: ['instrument'],
    requirements: { instrument: { required: true, available: false, reason_codes: ['instrument_unverified'] } },
  } }, false);
  assert.match(unsupported, /Not checked/);
  assert.doesNotMatch(unsupported, /63 \/ 50/);
});

test('scope shown in progress and reports uses the saved optional selections', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchProgress } = loadModule('components/research-progress.tsx');
  const { ResearchReport } = loadModule('components/research-report.tsx');
  const { researchScopeFacts } = loadModule('lib/research-scope.ts');
  const snapshot = { ...preflight.blocked, ticker: 'ABC', analysis_date: '2026-07-04',
    research_objective: 'earnings', research_horizon: '6_to_12_months' };
  const progress = renderToStaticMarkup(React.createElement(ResearchProgress,
    {snapshot, running: false, streamState: 'finished', onReconnect() {}}));
  const report = renderToStaticMarkup(React.createElement(ResearchReport,
    {snapshot, onOpenReport() {}, onExport() {}}));
  for (const html of [progress, report]) {
    assert.match(html, /Earnings and financial results/);
    assert.match(html, /6–12 months/);
  }
  assert.deepEqual(Array.from(researchScopeFacts({})), []);
});

test('snapshot provenance distinguishes admitted, excluded and unverified sources with safe downloads', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { DataSourcesPanel } = loadModule('components/data-sources-panel.tsx');
  const html = renderToStaticMarkup(React.createElement(DataSourcesPanel, { apiBaseUrl: 'http://localhost:8000', snapshot: {
    research_cutoff: { requested_date: '2026-07-04', effective_session_date: '2026-07-02', cutoff_at: '2026-07-02T20:00:00Z', cutoff_at_local: '2026-07-02T16:00:00-04:00', market_timezone: 'America/New_York' },
    data_snapshot: { snapshot_id: 'snap1', manifest_sha256: 'hash1', policy_version: 'p2', processing_version: 'v2' },
    source_records: ['included', 'excluded', 'unverified'].map((admissibility, i) => ({ record_id: `r${i}`, method: 'statement', provider: 'aggregator', publisher: 'SEC', admissibility, reason_codes: i ? ['public_time_unverified'] : [], published_at: i ? null : '2026-07-01T12:00:00Z', period_end: '2026-03-31', accession: '0001', source_url: 'https://sec.example/filing', raw_sha256: 'hash' })),
  } }));
  for (const value of ['2026-07-04', '2026-07-02', 'America/New_York', 'hash1', 'p2', 'v2', 'Included', 'Excluded', 'Unverified', 'public_time_unverified', 'aggregator', 'SEC', '2026-03-31', '0001']) assert.ok(html.includes(value), value);
  assert.match(html, /http:\/\/localhost:8000\/api\/snapshots\/snap1\/sources\/r0/);
  const legacy = renderToStaticMarkup(React.createElement(DataSourcesPanel, { snapshot: {} }));
  assert.match(legacy, /Snapshot provenance: Unverified/);
});

test('replay preserves saved security, date and mode while isolating demo models and credentials', () => {
  const { buildReplayRequest } = loadModule('lib/snapshot-replay.ts');
  const saved = { ticker: 'NVDA', analysis_date: '2026-07-04', data_mode: 'demo', data_snapshot: { snapshot_id: 'saved' },
    selected_analysts: ['market'], output_language: 'English', research_objective: 'earnings', research_horizon: '1_to_3_months' };
  const live = { provider: 'openai', apiKey: 'secret', baseUrl: 'https://live.example', quickModel: 'q', deepModel: 'd', validationResult: { valid: true } };
  const replay = buildReplayRequest(saved, live);
  assert.equal(replay.ticker, 'NVDA'); assert.equal(replay.analysis_date, '2026-07-04');
  assert.equal(replay.snapshot_id, 'saved'); assert.equal(replay.llm_provider, 'offline');
  assert.equal(replay.research_objective, 'earnings'); assert.equal(replay.research_horizon, '1_to_3_months');
  assert.equal(replay.api_key, null); assert.equal(replay.base_url, null);
  assert.equal(replay.quick_model, 'heuristic-fast'); assert.equal(replay.deep_model, 'heuristic-deep');
  assert.throws(() => buildReplayRequest({ ...saved, data_mode: 'live' }, { ...live, provider: 'offline' }), /live.*connection/i);
  assert.throws(() => buildReplayRequest({ ...saved, data_mode: 'live' }, { ...live, validationResult: null }), /live.*connection/i);
  assert.equal(buildReplayRequest({ ...saved, data_mode: 'live' }, live).api_key, 'secret');
  assert.throws(() => buildReplayRequest({ ...saved, data_snapshot: null }, live), /snapshot.*unverified/i);
});

test('saved-data replay is available on complete and partial report source panels', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { DataSourcesPanel } = loadModule('components/data-sources-panel.tsx');
  const snapshot = { data_snapshot: {snapshot_id: 'saved'}, data_mode: 'demo' };
  const html = renderToStaticMarkup(React.createElement(DataSourcesPanel, {snapshot, onReplay() {}, replayBusy: false}));
  assert.match(html, /Replay saved data/);
  assert.match(html, /same saved evidence inputs/);
  const busy = renderToStaticMarkup(React.createElement(DataSourcesPanel, {snapshot, onReplay() {}, replayBusy: true}));
  assert.match(busy, /disabled=""/);
  const legacy = renderToStaticMarkup(React.createElement(DataSourcesPanel, {snapshot: {}, onReplay() {}}));
  assert.doesNotMatch(legacy, /Replay saved data/);
});

test('partial reports clearly show no AI analysis, missing requirements, and retained source material', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { DataSourcesPanel } = loadModule('components/data-sources-panel.tsx');
  const html = renderToStaticMarkup(React.createElement(DataSourcesPanel, { snapshot: {
    data_mode: 'live', data_availability: { can_recommend: false, ai_analysis_performed: false,
      missing: ['cashflow'], requirements: { cashflow: { required: true, available: false, reason_codes: ['provider_timeout'] } } },
    source_attempts: [{ method: 'get_cashflow', provider: 'alpha_vantage', status: 'timeout' }],
    source_materials: [{ method: 'get_balance_sheet', provider: 'yfinance', content: '<retained>' }],
  } }));
  assert.match(html, /No AI analysis/);
  assert.match(html, /cashflow/);
  assert.match(html, /alpha_vantage/);
  assert.match(html, /&lt;retained&gt;/);
  assert.doesNotMatch(html, /<retained>/);
  const phase = loadModule('lib/research-view.ts').researchPhase({status: 'completed', data_availability: {can_recommend: false}});
  assert.equal(phase.label, 'Data incomplete · No recommendation');
  const legacy = renderToStaticMarkup(React.createElement(DataSourcesPanel, { snapshot: {} }));
  assert.match(legacy, /Unknown/);
});

test('pre-rendered setup does not freeze the analysis date to the build day', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchWorkbench } = loadModule('components/research-workbench.tsx');
  const html = renderToStaticMarkup(React.createElement(ResearchWorkbench));
  assert.doesNotMatch(html, /type="date"[^>]*max="\d{4}-\d{2}-\d{2}"/);
});

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

test('research progress distinguishes stopping, cancellation and timeout', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchProgress } = loadModule('components/research-progress.tsx');
  const render = (job_status, status) => renderToStaticMarkup(React.createElement(ResearchProgress, {
    running: status === 'running', snapshot: {status, job_status}, streamState: 'live',
    onCancel() {}, onReconnect() {},
  }));
  assert.match(render(undefined, 'running'), /Cancel research/);
  assert.match(render('stopping', 'running'), /disabled=""[^>]*>Stopping/);
  assert.match(render('cancelled', 'error'), /Research cancelled/);
  assert.match(render('timed_out', 'error'), /Research timed out/);
  assert.doesNotMatch(render('timed_out', 'error'), /Cancel research/);
});

test('usage shows budget and distinguishes missing tokens from zero', () => {
  const React = require('../frontend/node_modules/react');
  const { renderToStaticMarkup } = require('../frontend/node_modules/react-dom/server');
  const { ResearchProgress } = loadModule('components/research-progress.tsx');
  const render = (total, limit) => renderToStaticMarkup(React.createElement(ResearchProgress, {
    running: false, streamState: 'finished',
    snapshot: {status: 'error', job_status: 'budget_exhausted', model_usage: {
      calls_started: 1, calls_failed: 0, calls_with_reported_total_tokens: total === null ? 0 : 1,
      model_call_limit: limit, reported_total_tokens: total, model_elapsed_ms: 1250,
    }},
  }));
  assert.match(render(null, 1), /Model call limit reached/);
  assert.match(render(null, 1), /Model calls 1 \/ 1/);
  assert.match(render(null, 1), /Provider-reported tokens Not reported/);
  assert.match(render(0, null), /Provider-reported tokens 0/);
  assert.match(render(0, null), /no limit/);
});
