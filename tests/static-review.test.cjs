const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function controller() {
  const elements = new Map();
  const requests = new Map();
  const state = { runId: null, reviewBusy: false, snapshot: null, loadGeneration: 0 };
  const context = vm.createContext({
    state,
    $(id) {
      if (!elements.has(id)) elements.set(id, { value: '', innerHTML: '', textContent: '', dataset: {}, children: [], addEventListener() {}, replaceChildren() { this.children = []; }, append(child) { this.children.push(child); }, setAttribute() {} });
      return elements.get(id);
    },
    Option: function (label, value) { this.label = label; this.value = value; },
    localStorage: { getItem() { return null; } },
    closeEventSource() {}, connectRunStream() {},
    renderSnapshot(snapshot) { state.snapshot = snapshot; state.runId = snapshot.run_id; },
    getJson(url) {
      if (url === '/api/reviews') return Promise.resolve([]);
      return new Promise((resolve, reject) => requests.set(url, { resolve, reject }));
    },
    document: { querySelectorAll() { return []; }, createElement() { return { dataset: {}, addEventListener() {}, setAttribute() {} }; } },
    escapeHtml(value) { return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'); },
    evidenceAnchorId(value) { return /^E\d+$/.test(value) ? `evidence-${value}` : null; },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../marketmind_ai/web/static/claim-evidence.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../marketmind_ai/web/static/revision-comparison.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../marketmind_ai/web/static/human-review.js'), 'utf8'), context);
  return { context, state, requests, elements };
}

test('static review shows quotations, saved context and reproducible financial inputs', () => {
  const { context, elements } = controller();
  context.renderHumanReview(require('./claim-evidence-fixture.json'));
  const html = elements.get('reviewEvidenceBody').innerHTML;
  for (const value of ['claim-run-claim-check-1', 'claim-run-calculation-1', 'Quoted evidence',
    'Nearby context', 'Revenue 110', '10.0%', '2025-03-31', '110000000', '1000000']) {
    assert.ok(html.includes(value), value);
  }
  assert.match(html, /&lt;script&gt;source text&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test('saving a human review disables data refresh until the write finishes', () => {
  const { context, state, elements } = controller();
  state.snapshot = { status: 'completed' };
  state.reviewBusy = true;
  context.updateReviewControls();
  assert.equal(elements.get('refreshDataBtn').disabled, true);
  state.reviewBusy = false;
  context.updateReviewControls();
  assert.equal(elements.get('refreshDataBtn').disabled, false);
});

test('a pending research start prevents report switches, reviews and revision launches', async () => {
  const { context, state, elements } = controller();
  state.snapshot = {run_id:'original',status:'completed',provider:'offline',review:{status:'changes_requested',version:1,report_hash:'old'}};
  state.startingRun = true;
  const paths = [];
  context.getJson = async path => { paths.push(path); return {}; };
  context.updateReviewControls();
  assert.equal(elements.get('reviseReportBtn').disabled,true);
  assert.equal(elements.get('reviewForm').disabled,true);
  await context.openReviewedRun('another');
  await context.generateRevision();
  await context.submitHumanReview('approve');
  assert.deepEqual(paths,[]);
});

test('switching revisions discards the previous comparison response and allows retry', async () => {
  const {context,requests,elements} = controller();
  const report = id => ({run_id:id,status:'completed',review:{
    status:'pending',version:2,report_hash:id+'-hash',parent_run_id:'parent-'+id,history:[],
  }});
  const result = id => ({status:'available',current:{run_id:id,version:2,report_hash:id+'-hash'},
    previous:{run_id:'parent-'+id,version:1,report_hash:'parent-hash'},
    data_snapshot:'same', changed_fields:[{label:'Executive summary',before:'Old '+id,after:'New '+id}],
    added_evidence:[],removed_evidence:[],unchanged_evidence_count:2});
  context.renderSnapshot(report('old'));
  context.renderRevisionComparison(report('old'));
  const first = context.loadRevisionComparison();
  context.renderSnapshot(report('latest'));
  context.renderRevisionComparison(report('latest'));
  const latest = context.loadRevisionComparison();
  requests.get('/api/runs/latest/comparison').resolve(result('latest'));
  await latest;
  requests.get('/api/runs/old/comparison').resolve(result('old'));
  await first;
  assert.match(elements.get('revisionComparisonBody').innerHTML,/New latest/);
  assert.doesNotMatch(elements.get('revisionComparisonBody').innerHTML,/New old/);
  const failed = context.loadRevisionComparison();
  requests.get('/api/runs/latest/comparison').reject(new Error('Connection interrupted'));
  await failed;
  assert.match(elements.get('revisionComparisonStatus').textContent,/Connection interrupted/);
  const retry = context.loadRevisionComparison();
  requests.get('/api/runs/latest/comparison').resolve(result('latest'));
  await retry;
  assert.match(elements.get('revisionComparisonBody').innerHTML,/New latest/);
});
test('the latest saved report selection wins when responses arrive out of order', async () => {
  const { context, state, requests } = controller();
  const oldLoad = context.openReviewedRun('old');
  const latestLoad = context.openReviewedRun('latest');
  requests.get('/api/runs/latest').resolve({ run_id: 'latest', status: 'completed' });
  await latestLoad;
  requests.get('/api/runs/old').resolve({ run_id: 'old', status: 'completed' });
  await oldLoad;
  assert.equal(state.snapshot.run_id, 'latest');
});

test('a stale failed report load does not replace the latest successful selection with an error', async () => {
  const { context, state, requests } = controller();
  const oldLoad = context.openReviewedRun('old');
  const latestLoad = context.openReviewedRun('latest');
  requests.get('/api/runs/latest').resolve({ run_id: 'latest', status: 'completed' });
  await latestLoad;
  requests.get('/api/runs/old').reject(new Error('Old request failed'));
  await assert.doesNotReject(oldLoad);
  assert.equal(state.snapshot.run_id, 'latest');
});


test('recent reports can be searched by ticker or date and filtered by review status', async () => {
  const { context, state, elements } = controller();
  context.getJson = async () => [
    { run_id: 'nvda', ticker: 'NVDA', analysis_date: '2026-10-26', review: { version: 2, status: 'pending' } },
    { run_id: 'aapl', ticker: 'AAPL', analysis_date: '2026-10-25', review: { version: 1, status: 'approved' } },
  ];
  await context.refreshReviews();
  assert.equal(typeof context.renderReviewQueue, 'function');
  assert.equal(elements.get('reviewQueue').children.length, 2);
  assert.match(elements.get('reviewQueue').children[0].innerHTML, /NVDA/);
  assert.match(elements.get('reviewQueue').children[0].innerHTML, /v2/);
  elements.get('reviewSearch').value = '2026-10-25';
  context.renderReviewQueue();
  assert.equal(elements.get('reviewQueue').children.length, 1);
  assert.match(elements.get('reviewQueue').children[0].innerHTML, /AAPL/);
  elements.get('reviewSearch').value = '';
  elements.get('reviewStatusFilter').value = 'pending';
  context.renderReviewQueue();
  assert.equal(elements.get('reviewQueue').children.length, 1);
  assert.match(elements.get('reviewQueue').children[0].innerHTML, /NVDA/);
});

test('a stale recent-report refresh cannot overwrite the latest list', async () => {
  const { context, state } = controller();
  const pending = [];
  context.getJson = () => new Promise(resolve => pending.push(resolve));
  const first = context.refreshReviews();
  const second = context.refreshReviews();
  pending[1]([{ run_id: 'new', ticker: 'NEW', review: { status: 'pending', version: 1 } }]);
  await second;
  pending[0]([{ run_id: 'old', ticker: 'OLD', review: { status: 'pending', version: 1 } }]);
  await first;
  assert.equal(state.recentReviews[0].run_id, 'new');
});

test('starting a revision clears the previous version decision and evidence while queued', async () => {
  const { context, state } = controller();
  state.snapshot = { run_id: 'original', provider: 'offline', status: 'completed', review: { status: 'changes_requested', version: 1, report_hash: 'hash' }, final_structured_decision: { executive_summary: 'Previous decision' }, evidence_ledger: [{ evidence_id: 'old' }], report_verification: { status: 'pass' }, report_quality: { score: 99 } };
  context.getJson = async () => ({ run_id: 'revision', report_url: '/runs/revision/report' });
  await context.generateRevision();
  assert.equal(state.snapshot.final_structured_decision, null);
  assert.equal(state.snapshot.report_verification, null);
  assert.equal(state.snapshot.report_quality, null);
  assert.equal(state.snapshot.evidence_ledger.length, 0);
});
