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
      if (!elements.has(id)) elements.set(id, { value: '', addEventListener() {}, replaceChildren() {}, add() {} });
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
    document: { querySelectorAll() { return []; } },
    escapeHtml: String,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../marketmind_ai/web/static/human-review.js'), 'utf8'), context);
  return { context, state, requests };
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
