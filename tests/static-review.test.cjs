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
    escapeHtml: String,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../marketmind_ai/web/static/human-review.js'), 'utf8'), context);
  return { context, state, requests, elements };
}

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
