export type ModelOption = {
  label: string;
  value: string;
};

export type SymbolCandidate = {
  symbol: string;
  name: string;
  exchange?: string | null;
  region?: string | null;
  currency?: string | null;
  type?: string | null;
  provider?: string | null;
  match_score?: number | null;
};

export type ValidationFlags = {
  price_data: boolean;
  fundamental_data: boolean;
};

export type ResolvedTicker = {
  status: "RESOLVED" | "AMBIGUOUS" | "NOT_FOUND" | "INSUFFICIENT_DATA";
  original_input: string;
  normalized_query: string;
  resolved_symbol?: string | null;
  company_name?: string | null;
  exchange?: string | null;
  region?: string | null;
  currency?: string | null;
  confidence?: number | null;
  candidates: SymbolCandidate[];
  reason?: string | null;
  validation: ValidationFlags;
};

export type ProviderOption = {
  value: string;
  label: string;
  requires_api_key: boolean;
  supports_custom_models: boolean;
  custom_model_placeholder?: string | null;
  base_url?: string | null;
  quick_models: ModelOption[];
  deep_models: ModelOption[];
};

export type AgentStatus = {
  key: string;
  label: string;
  status: "pending" | "in_progress" | "completed" | "error";
};

export type MessageView = {
  id?: string;
  timestamp: string;
  kind: string;
  content: string;
};

export type ToolCallView = {
  id?: string;
  timestamp: string;
  name: string;
  args: string;
};

export type ReportSection = {
  key: string;
  label: string;
  content?: string | null;
};

export type RunSnapshot = {
  run_id: string;
  status: "queued" | "running" | "completed" | "error";
  original_input: string;
  ticker: string;
  resolved_from?: string | null;
  company_name?: string | null;
  exchange?: string | null;
  region?: string | null;
  currency?: string | null;
  ticker_resolution?: ResolvedTicker | null;
  analysis_date: string;
  provider: string;
  quick_model: string;
  deep_model: string;
  output_language: string;
  selected_analysts: string[];
  started_at: string;
  finished_at?: string | null;
  current_agent?: string | null;
  latest_update?: string | null;
  agents: AgentStatus[];
  messages: MessageView[];
  tool_calls: ToolCallView[];
  reports: ReportSection[];
  final_signal?: string | null;
  final_decision?: string | null;
  error?: string | null;
};

export type RunCreatedResponse = {
  run_id: string;
  stream_url: string;
  result_url: string;
  report_url: string;
  ticker_resolution?: ResolvedTicker | null;
};

export type SymbolSearchResponse = {
  query: string;
  candidates: SymbolCandidate[];
};

export type ValidateKeyResponse = {
  valid: boolean;
  provider: string;
  model: string;
  message: string;
};

export type ResolutionErrorResponse = {
  detail?: {
    status: string;
    message: string;
    resolution?: ResolvedTicker;
  };
};
