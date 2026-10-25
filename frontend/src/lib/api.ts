export interface ClaimRef {
  claim_id: string;
  metric_path?: string;
}

export interface ToolEnvelope<T> {
  schema_version: string;
  tool_name: string;
  result_status: string;
  business_as_of_date: string;
  generated_at: string;
  data_versions: Record<string, string>;
  normalized_input: Record<string, unknown>;
  summary: string;
  data: T;
  claim_refs: ClaimRef[];
  warnings: string[];
  error?: { code: string; message: string } | null;
}

export interface OrderRecord {
  order_id: string;
  customer: string;
  product: string;
  category: string;
  pieces: number;
  due_date: string;
  status: string;
  current_stage: string;
  last_activity_date: string;
}

export interface OrderSearchData {
  match_count: number;
  matched_total_pieces: number;
  orders: OrderRecord[];
  pagination: { limit: number | null; offset: number; returned_count: number; has_more: boolean };
  clarification: null | {
    question: string;
    candidate_order_ids: string[];
    suggested_fields: string[];
  };
}

export interface StageSummary {
  stage: string;
  coverage_status: string;
  observed_days: number;
  total_pieces: number | null;
  average_per_operating_day: number | null;
  totals_scope: string;
}

export interface ProductionData {
  requested_range: { start_date: string; end_date: string };
  coverage_status: string;
  missing_keys: Array<{ date: string; stage: string }>;
  daily_output: Array<{ date: string; stage: string; pieces_completed: number; is_closed_day: boolean }>;
  stage_summaries: StageSummary[];
}

export interface BriefFinding {
  finding_id: string;
  category: string;
  priority: number;
  severity: "CRITICAL" | "WARNING" | "INFO";
  summary: string;
  recommended_next_step: string;
  claim_id: string;
  status: string;
}

export interface BriefData {
  run_id: string;
  as_of_date: string;
  data_cutoff_time: string;
  data_quality: string;
  overview: {
    finding_count: number;
    published_count: number;
    observation_count: number;
    not_shown_count?: number;
    severity_counts: Record<string, number>;
  };
  findings: BriefFinding[];
  observation_findings: BriefFinding[];
  not_shown_findings?: { summary: string; severity: string; priority: number; claim_id: string | null }[];
  assumptions: string[];
}

export interface FeasibilityData {
  classification: string;
  requested_due_date: string;
  available_working_days: number;
  estimated_completion_range: { earliest: string | null; latest: string | null };
  bottleneck_stage: string | null;
  internal_scenario: Record<string, unknown>;
  workshop_scenarios: Array<Record<string, unknown>>;
  excluded_workshops: Array<Record<string, unknown>>;
  assumptions: string[];
  limitations: string[];
  confidence: string;
}

export interface TraceData {
  claim_id: string;
  claim_text: string;
  generated_by: string;
  rule_version: string;
  generated_at: string;
  as_of_date: string;
  status: string;
  source_refs: Array<Record<string, unknown>>;
  source_rows: Array<Record<string, unknown>>;
  calculation_steps: Array<Record<string, unknown>>;
  verification?: {
    result: string;
    old_value: unknown;
    new_value: unknown;
    likely_cause?: string | null;
  };
}

export interface ActionAuditRecord {
  requester: string;
  action_type: string;
  target: string;
  confirmation_token: string;
  preview: { payload?: Record<string, unknown>; [key: string]: unknown };
  claim_ids: string[];
  status: string;
  prepared_at: string;
  completed_at: string | null;
  recorded_effect: Record<string, unknown> | null;
}

export type AIProviderId = "chatgpt" | "claude" | "gemini" | "deepseek";

export interface AIProviderCatalog {
  providers: {
    id: AIProviderId;
    label: string;
    models: { id: string; label: string }[];
  }[];
}

export interface AISettings {
  provider: AIProviderId;
  model: string;
  has_api_key: boolean;
  encryption_ready: boolean;
  updated_at: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  metadata: { tool_events?: ChatToolEvent[]; pending_actions?: PendingAction[] };
  created_at: string;
}

export interface ChatToolEvent {
  tool_name: string;
  result_status: string;
  summary: string;
  data: Record<string, any> | null;
  claim_ids: string[];
  requires_clarification: boolean;
}

export interface ChatConversation {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
}

export interface ChatConversationSummary {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatTurnResponse {
  conversation_id: string;
  assistant_message: string;
  tool_events: ChatToolEvent[];
  claim_refs: string[];
  clarification: Record<string, any> | null;
  pending_action: PendingAction | null;
  pending_actions?: PendingAction[];
  status: string;
}

export interface PendingAction {
  confirmation_token: string;
  prepared_at: string;
  preview: {
    action_type: "add_order_note" | "create_reminder" | "draft_chase_up_message";
    target: string;
    payload: { note?: string; message?: string; remind_at?: string };
    claim_ids: string[];
  };
}

export type ReminderDueState = "OVERDUE" | "DUE_SOON" | "UPCOMING" | "DONE" | "CANCELLED";

export interface Reminder {
  reminder_id: string;
  order_id: string;
  note: string;
  remind_at: string;
  status: "ACTIVE" | "DONE" | "CANCELLED";
  source: string;
  due_state: ReminderDueState;
  created_at: string;
  updated_at: string;
}

export interface ChatMemory {
  memory_id: string;
  content: string;
  created_at: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("API is unreachable. Start the local backend and try again.", 0);
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null && "detail" in payload
      ? (payload as { detail: unknown }).detail
      : payload;
    // Tool errors arrive as a full result envelope; show its readable error message, not the raw JSON.
    const toolMessage = (detail as { error?: { message?: unknown } } | null)?.error?.message;
    const message = typeof detail === "string"
      ? detail
      : typeof toolMessage === "string"
        ? toolMessage
        : JSON.stringify(detail ?? response.statusText);
    throw new ApiError(message, response.status);
  }
  return payload as T;
}

function queryString(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const value = params.toString();
  return value ? `?${value}` : "";
}

export function getHealth() {
  return apiFetch<{ status: string }>("/health");
}

export function getOrders(filters: Record<string, string | number | undefined> = {}) {
  return apiFetch<ToolEnvelope<OrderSearchData>>(`/api/v1/orders${queryString(filters)}`);
}

export function getProduction(filters: {
  start: string;
  end: string;
  stage?: string;
}) {
  const params = new URLSearchParams({ start: filters.start, end: filters.end });
  if (filters.stage) params.set("stage", filters.stage);
  return apiFetch<ToolEnvelope<ProductionData>>(`/api/v1/production?${params.toString()}`);
}

export function getOrderRisk(orderId: string) {
  return apiFetch<ToolEnvelope<Record<string, any>>>(`/api/v1/orders/${encodeURIComponent(orderId)}/risk`);
}

export function getNormality(targetDate: string, stage: string) {
  return apiFetch<ToolEnvelope<Record<string, any>>>(
    `/api/v1/production/normality${queryString({ date: targetDate, stage })}`,
  );
}

export function generateBrief() {
  return apiFetch<ToolEnvelope<BriefData>>("/api/v1/brief", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function estimateFeasibility(input: {
  product: string;
  category: string;
  pieces: number;
  requested_due_date: string;
  allow_outsourcing: boolean;
}) {
  return apiFetch<ToolEnvelope<FeasibilityData>>("/api/v1/feasibility", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getClaim(claimId: string) {
  return apiFetch<TraceData>(`/api/v1/claims/${encodeURIComponent(claimId)}`);
}

export function verifyClaim(claimId: string) {
  return apiFetch<TraceData>(`/api/v1/claims/${encodeURIComponent(claimId)}/verify`, {
    method: "POST",
  });
}

export function prepareAction(input: {
  action_type: string;
  target: string;
  payload: Record<string, string>;
  claim_ids: string[];
}) {
  return apiFetch<{
    status: string;
    preview: Record<string, unknown>;
    confirmation_token: string;
    side_effect_executed: boolean;
  }>("/api/v1/actions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function confirmAction(token: string) {
  return apiFetch<Record<string, any>>(`/api/v1/actions/${encodeURIComponent(token)}/confirm`, {
    method: "POST",
  });
}

export function cancelAction(token: string) {
  return apiFetch<Record<string, any>>(`/api/v1/actions/${encodeURIComponent(token)}/cancel`, {
    method: "POST",
  });
}

export function getReminders(includeClosed = false) {
  return apiFetch<Reminder[]>(`/api/v1/reminders${includeClosed ? "?include_closed=true" : ""}`);
}

export function createReminder(input: { order_id: string; note: string; remind_at: string }) {
  return apiFetch<{ status: string; reminder: Reminder }>("/api/v1/reminders", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateReminder(
  reminderId: string,
  changes: Partial<{ order_id: string; note: string; remind_at: string; status: Reminder["status"] }>,
) {
  return apiFetch<{ status: string; reminder: Reminder }>(`/api/v1/reminders/${encodeURIComponent(reminderId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function getActionAudit() {
  return apiFetch<ActionAuditRecord[]>("/api/v1/actions");
}

export function getAISettings() {
  return apiFetch<AISettings>("/api/v1/settings/ai");
}

export function getAIProviderCatalog() {
  return apiFetch<AIProviderCatalog>("/api/v1/settings/ai/catalog");
}

export function saveAISettings(input: {
  provider: AIProviderId;
  model: string;
  api_key?: string;
}) {
  return apiFetch<AISettings>("/api/v1/settings/ai", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function testAIConnection() {
  return apiFetch<{ status: string; message: string }>("/api/v1/settings/ai/test", {
    method: "POST",
  });
}

export function deleteAICredential() {
  return apiFetch<AISettings>("/api/v1/settings/ai/credential", { method: "DELETE" });
}

export function getChatMemoryPreference() {
  return apiFetch<{ enabled: boolean }>("/api/v1/settings/chat-memory");
}

export function setChatMemoryPreference(enabled: boolean) {
  return apiFetch<{ enabled: boolean }>("/api/v1/settings/chat-memory", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

export function getChatMemories() {
  return apiFetch<ChatMemory[]>("/api/v1/chat/memories");
}

export function createChatMemory(content: string) {
  return apiFetch<ChatMemory>("/api/v1/chat/memories", {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function deleteChatMemory(memoryId: string) {
  return apiFetch<{ deleted: boolean }>(`/api/v1/chat/memories/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
  });
}

export function clearChatMemories() {
  return apiFetch<{ deleted_count: number }>("/api/v1/chat/memories", { method: "DELETE" });
}

export function createChatConversation(title: string) {
  return apiFetch<Omit<ChatConversation, "messages">>("/api/v1/chat/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function getChatConversations() {
  return apiFetch<ChatConversationSummary[]>("/api/v1/chat/conversations");
}

export function getChatConversation(conversationId: string) {
  return apiFetch<ChatConversation>(`/api/v1/chat/conversations/${encodeURIComponent(conversationId)}`);
}

export function deleteChatConversation(conversationId: string) {
  return apiFetch<{ deleted: boolean }>(`/api/v1/chat/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
  });
}

export function sendChatTurn(conversationId: string, message: string) {
  return apiFetch<ChatTurnResponse>(`/api/v1/chat/conversations/${encodeURIComponent(conversationId)}/turns`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}