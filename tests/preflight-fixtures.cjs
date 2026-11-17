const cutoff = {
  requested_date: '2026-07-04',
  effective_session_date: '2026-07-02',
  cutoff_at_local: '2026-07-02T16:00:00-04:00',
  market_timezone: 'America/New_York',
};

const statement = { required: true, available: true, provider: 'sec', period_end: '2026-03-31' };

const passed = {
  run_id: 'live-run', status: 'running', data_mode: 'live', research_cutoff: cutoff,
  data_availability: { can_recommend: true, ai_analysis_performed: false, missing: [], requirements: {
    instrument: { required: true, available: true },
    price_history: { required: true, available: true, valid_count: 63, minimum_count: 50, provider: 'yfinance' },
    income_statement: statement, balance_sheet: statement, cashflow: statement,
    news: { required: false, available: false, reason_codes: ['no_time_verified_news'] },
  } },
};

const blocked = {
  ...passed, run_id: 'blocked-run', status: 'completed',
  data_availability: { ...passed.data_availability, can_recommend: false, missing: ['cashflow'], requirements: {
    ...passed.data_availability.requirements,
    cashflow: { ...statement, available: false, reason_codes: ['missing_cashflow', '<unsafe reason>'] },
  } },
};

module.exports = { cutoff, passed, blocked };
