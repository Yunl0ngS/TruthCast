import axios from 'axios';
import type { ExportData } from '@/lib/export';
import type {
  ClaimItem,
  ContentGenerateRequest,
  ContentGenerateResponse,
  ContentDraft,
  DetectResponse,
  EvidenceItem,
  ImageAnalysisResult,
  ImageInput,
  MultimodalDetectResponse,
  Phase,
  PhaseState,
  PhaseStatus,
  HistoryDetail,
  HistoryItem,
  MonitorAlert,
  MonitorAnalysisResult,
  MonitorHotItem,
  MonitorScanResponse,
  MonitorScanWindowDetail,
  MonitorStatus,
  MonitorSubscription,
  MonitorSubscriptionCreate,
  ReportResponse,
  SimulateResponse,
  StrategyConfig,
  UrlCrawlResponse,
  UrlDetectResponse,
} from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

export function resolveApiUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

function parseFilenameFromDisposition(disposition: string | null, fallback: string): string {
  if (!disposition) return fallback;
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? fallback;
}

async function downloadExportFile(endpoint: '/export/pdf' | '/export/word', payload: ExportData, fallback: string): Promise<void> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`导出失败: ${response.status}`);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const filename = parseFilenameFromDisposition(response.headers.get('content-disposition'), fallback);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function downloadPdfExport(payload: ExportData): Promise<void> {
  const dateText = new Date().toISOString().slice(0, 10);
  await downloadExportFile('/export/pdf', payload, `truthcast-report-${dateText}.pdf`);
}

export async function downloadWordExport(payload: ExportData): Promise<void> {
  const dateText = new Date().toISOString().slice(0, 10);
  await downloadExportFile('/export/word', payload, `truthcast-report-${dateText}.docx`);
}

export async function detect(text: string): Promise<DetectResponse> {
  const { data } = await api.post<DetectResponse>('/detect', { text });
  return data;
}

export async function getMonitorStatus(): Promise<MonitorStatus> {
  const { data } = await api.get<MonitorStatus>('/monitor/status');
  return data;
}

export async function getMonitorSubscriptions(isActive?: boolean): Promise<MonitorSubscription[]> {
  const { data } = await api.get<{ items: MonitorSubscription[] }>('/monitor/subscriptions', {
    params: { is_active: isActive },
  });
  return data.items;
}

export async function createMonitorSubscription(payload: MonitorSubscriptionCreate): Promise<MonitorSubscription> {
  const { data } = await api.post<MonitorSubscription>('/monitor/subscriptions', payload);
  return data;
}

export async function updateMonitorSubscription(
  id: string,
  payload: Partial<MonitorSubscriptionCreate> & { is_active?: boolean }
): Promise<MonitorSubscription> {
  const { data } = await api.patch<MonitorSubscription>(`/monitor/subscriptions/${id}`, payload);
  return data;
}

export async function deleteMonitorSubscription(id: string): Promise<void> {
  await api.delete(`/monitor/subscriptions/${id}`);
}

export async function getMonitorHotItems(limit = 20, platform?: string): Promise<MonitorHotItem[]> {
  const { data } = await api.get<{ items: MonitorHotItem[] }>('/monitor/hot-items', {
    params: { limit, platform },
  });
  return data.items;
}

export async function triggerMonitorScan(
  platforms?: string[],
  autoAnalyze?: boolean
): Promise<MonitorScanResponse> {
  const payload: { platforms: string[]; auto_analyze?: boolean } = {
    platforms: platforms ?? [],
  };
  if (typeof autoAnalyze === 'boolean') {
    payload.auto_analyze = autoAnalyze;
  }
  const { data } = await api.post<MonitorScanResponse>('/monitor/scan', payload);
  return data;
}

export async function getMonitorAlerts(limit = 50): Promise<MonitorAlert[]> {
  const { data } = await api.get<{ items: MonitorAlert[] }>('/monitor/alerts', {
    params: { limit },
  });
  return data.items;
}

export async function getMonitorAnalysisResults(limit = 20): Promise<MonitorAnalysisResult[]> {
  const { data } = await api.get<{ items: MonitorAnalysisResult[] }>('/monitor/analysis-results', {
    params: { limit },
  });
  return data.items;
}

export async function getLatestMonitorWindow(): Promise<MonitorScanWindowDetail> {
  const { data } = await api.get<MonitorScanWindowDetail>('/monitor/windows/latest');
  return data;
}

export async function getMonitorWindowHistory(hours = 6, limit = 24): Promise<MonitorScanWindowDetail[]> {
  const { data } = await api.get<{ windows: MonitorScanWindowDetail[] }>('/monitor/windows/history', {
    params: { hours, limit },
  });
  return data.windows;
}

export async function getMonitorAnalysisResult(resultId: string): Promise<MonitorAnalysisResult> {
  const { data } = await api.get<MonitorAnalysisResult>(`/monitor/analysis-results/${resultId}`);
  return data;
}

export async function generateMonitorAnalysisContent(resultId: string): Promise<{ status: string; result_id: string }> {
  const { data } = await api.post<{ status: string; result_id: string }>(
    `/monitor/analysis-results/${resultId}/generate-content`
  );
  return data;
}

export async function analyzeMonitorWindowItem(
  itemId: string
): Promise<{ analysis_result: MonitorAnalysisResult }> {
  const { data } = await api.post<{ analysis_result: MonitorAnalysisResult }>(
    `/monitor/window-items/${itemId}/analyze`
  );
  return data;
}

export async function acknowledgeMonitorAlert(id: string): Promise<void> {
  await api.post(`/monitor/alerts/${id}/ack`);
}

export async function detectWithSignal(text: string, signal?: AbortSignal): Promise<DetectResponse> {
  const { data } = await api.post<DetectResponse>('/detect', { text }, { signal });
  return data;
}

export async function uploadMultimodalImage(file: File): Promise<{
  file_id: string;
  filename: string;
  mime_type: string;
  size: number;
  public_url?: string | null;
}> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${API_BASE}/multimodal/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    throw new Error(`多模态上传失败: ${response.status}`);
  }
  return response.json();
}

export async function deleteMultimodalImage(fileId: string): Promise<{ file_id: string; deleted: boolean }> {
  const { data } = await api.delete<{ file_id: string; deleted: boolean }>(`/multimodal/files/${fileId}`);
  return data;
}

export async function detectMultimodalWithSignal(
  text?: string,
  images?: ImageInput[],
  signal?: AbortSignal
): Promise<MultimodalDetectResponse> {
  const { data } = await api.post<MultimodalDetectResponse>(
    '/multimodal/detect',
    {
      text,
      images,
      force: true,
    },
    { signal }
  );
  return data;
}

export async function analyzeMultimodalImagesWithSignal(
  text: string | undefined,
  images: ImageInput[],
  signal?: AbortSignal
): Promise<ImageAnalysisResult[]> {
  const { data } = await api.post<{ image_analyses: ImageAnalysisResult[] }>(
    '/multimodal/analyze-images',
    { text, images },
    { signal }
  );
  return data.image_analyses;
}

export async function detectUrl(url: string, signal?: AbortSignal): Promise<UrlDetectResponse> {
  const { data } = await api.post<UrlDetectResponse>('/detect/url', { url }, { signal });
  return data;
}

export async function crawlNewsUrl(url: string, signal?: AbortSignal): Promise<UrlCrawlResponse> {
  const { data } = await api.post<UrlCrawlResponse>('/detect/url/crawl', { url }, { signal });
  return data;
}

export async function detectUrlRisk(
  payload: { url: string; title: string; content: string },
  signal?: AbortSignal
): Promise<DetectResponse> {
  const { data } = await api.post<DetectResponse>('/detect/url/risk', payload, { signal });
  return data;
}

export async function detectClaims(text: string, strategy?: StrategyConfig | null): Promise<ClaimItem[]> {
  const { data } = await api.post<{ claims: ClaimItem[] }>('/detect/claims', { text, strategy });
  return data.claims;
}

export async function detectClaimsWithSignal(
  text: string,
  strategy?: StrategyConfig | null,
  signal?: AbortSignal
): Promise<ClaimItem[]> {
  const { data } = await api.post<{ claims: ClaimItem[] }>('/detect/claims', { text, strategy }, { signal });
  return data.claims;
}

export async function detectEvidence(
  text: string,
  claims: ClaimItem[],
  strategy?: StrategyConfig | null
): Promise<EvidenceItem[]> {
  const { data } = await api.post<{ evidences: EvidenceItem[] }>('/detect/evidence', {
    text,
    claims,
    strategy,
  });
  return data.evidences;
}

export async function detectEvidenceWithSignal(
  text: string,
  claims: ClaimItem[],
  strategy?: StrategyConfig | null,
  signal?: AbortSignal
): Promise<EvidenceItem[]> {
  const { data } = await api.post<{ evidences: EvidenceItem[] }>(
    '/detect/evidence',
    {
      text,
      claims,
      strategy,
    },
    { signal }
  );
  return data.evidences;
}

export interface DetectReportResult {
  record_id: string;
  risk_score: number;
  risk_level: string;
  risk_label: string;
  detected_scenario: string;
  evidence_domains: string[];
  source_url?: string | null;
  source_title?: string | null;
  source_publish_date?: string | null;
  summary: string;
  suspicious_points: string[];
  claim_reports: Array<{
    claim: ClaimItem;
    evidences: EvidenceItem[];
    final_stance: string;
    notes: string[];
  }>;
  multimodal?: Record<string, unknown> | null;
}

export async function alignEvidence(
  claims: ClaimItem[],
  evidences: EvidenceItem[],
  strategy?: StrategyConfig | null
): Promise<EvidenceItem[]> {
  const { data } = await api.post<{ evidences: EvidenceItem[] }>('/detect/evidence/align', {
    claims,
    evidences,
    strategy,
  });
  return data.evidences;
}

export async function alignEvidenceWithSignal(
  claims: ClaimItem[],
  evidences: EvidenceItem[],
  strategy?: StrategyConfig | null,
  signal?: AbortSignal
): Promise<EvidenceItem[]> {
  const { data } = await api.post<{ evidences: EvidenceItem[] }>(
    '/detect/evidence/align',
    {
      claims,
      evidences,
      strategy,
    },
    { signal }
  );
  return data.evidences;
}

export async function detectReport(
  text: string,
  claims?: ClaimItem[],
  evidences?: EvidenceItem[],
  detectData?: DetectResponse | null,
  strategy?: StrategyConfig | null,
  sourceMeta?: { source_url?: string | null; source_title?: string | null; source_publish_date?: string | null } | null,
  multimodal?: Record<string, unknown> | null,
): Promise<DetectReportResult> {
  const { data } = await api.post<DetectReportResult>('/detect/report', {
    text,
    claims,
    evidences,
    detect_data: detectData,
    strategy,
    source_url: sourceMeta?.source_url,
    source_title: sourceMeta?.source_title,
    source_publish_date: sourceMeta?.source_publish_date,
    multimodal,
  });
  return data;
}

export async function detectReportWithSignal(
  text: string,
  claims?: ClaimItem[],
  evidences?: EvidenceItem[],
  detectData?: DetectResponse | null,
  strategy?: StrategyConfig | null,
  sourceMeta?: { source_url?: string | null; source_title?: string | null; source_publish_date?: string | null } | null,
  signal?: AbortSignal,
  multimodal?: Record<string, unknown> | null,
): Promise<DetectReportResult> {
  const { data } = await api.post<DetectReportResult>(
    '/detect/report',
    {
      text,
      claims,
      evidences,
      detect_data: detectData,
      strategy,
      source_url: sourceMeta?.source_url,
      source_title: sourceMeta?.source_title,
      source_publish_date: sourceMeta?.source_publish_date,
      multimodal,
    },
    { signal }
  );
  return data;
}

export async function simulate(
  text: string,
  claims?: ClaimItem[],
  evidences?: EvidenceItem[],
  report?: ReportResponse
): Promise<SimulateResponse> {
  const { data } = await api.post<SimulateResponse>('/simulate', {
    text,
    claims,
    evidences,
    report,
    time_window_hours: 24,
    platform: 'general',
    comments: [],
  });
  return data;
}

export type SimulationStage = 'emotion' | 'narratives' | 'flashpoints' | 'suggestion';

export interface SimulationStreamEvent {
  stage: SimulationStage;
  data: Partial<SimulateResponse>;
}

export async function simulateStream(
  text: string,
  onStage: (event: SimulationStreamEvent) => void,
  claims?: ClaimItem[],
  evidences?: EvidenceItem[],
  report?: ReportResponse,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_BASE}/simulate/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      text,
      claims,
      evidences,
      report,
      time_window_hours: 24,
      platform: 'general',
      comments: [],
    }),
  });

  if (!response.ok) {
    throw new Error(`Simulation stream failed: ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as SimulationStreamEvent;
          onStage(event);
        } catch {
          console.warn('Failed to parse SSE event:', line);
        }
      }
    }
  }
}

export async function getHistory(limit = 20): Promise<HistoryItem[]> {
  const { data } = await api.get<{ items: HistoryItem[] }>(`/history?limit=${limit}`);
  return data.items;
}

export async function getHistoryDetail(recordId: string): Promise<HistoryDetail> {
  const { data } = await api.get<HistoryDetail>(`/history/${recordId}`);
  return data;
}

export async function submitHistoryFeedback(
  recordId: string,
  status: 'accurate' | 'inaccurate' | 'evidence_irrelevant',
  note = ''
): Promise<void> {
  await api.post(`/history/${recordId}/feedback`, { status, note });
}

export async function updateHistorySimulation(
  recordId: string,
  simulation: SimulateResponse
): Promise<void> {
  await api.post(`/history/${recordId}/simulation`, simulation);
}

export async function updateHistoryContent(
  recordId: string,
  content: ContentDraft
): Promise<void> {
  await api.post(`/history/${recordId}/content`, content);
}

// ========== Pipeline State Persistence API ==========

export type PipelinePhaseSnapshot = {
  phase: Phase;
  status: PhaseStatus;
  updated_at: string;
  duration_ms?: number | null;
  error_message?: string | null;
  payload?: Record<string, unknown> | null;
};

export type PipelineStateUpsertRequest = {
  task_id: string;
  input_text: string;
  phases: PhaseState;
  phase: Phase;
  status: PhaseStatus;
  duration_ms?: number | null;
  error_message?: string | null;
  payload?: Record<string, unknown> | null;
  meta?: Record<string, unknown> | null;
};

export type PipelineStateUpsertResponse = {
  task_id: string;
  phase: Phase;
  status: PhaseStatus;
  updated_at: string;
};

export type PipelineStateLatestResponse = {
  task_id: string;
  input_text: string;
  phases: PhaseState;
  meta: Record<string, unknown>;
  updated_at: string;
  snapshots: PipelinePhaseSnapshot[];
};

export async function savePipelinePhaseSnapshot(
  payload: PipelineStateUpsertRequest
): Promise<PipelineStateUpsertResponse> {
  const { data } = await api.post<PipelineStateUpsertResponse>('/pipeline/save-phase', payload);
  return data;
}

export async function loadLatestPipelineState(taskId?: string | null): Promise<PipelineStateLatestResponse> {
  const url = taskId ? `/pipeline/load-latest?task_id=${encodeURIComponent(taskId)}` : '/pipeline/load-latest';
  const { data } = await api.get<PipelineStateLatestResponse>(url);
  return data;
}

// ========== 应对内容生成 API ==========

export async function generateContent(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse> {
  const { data } = await api.post<ContentGenerateResponse>('/content/generate', request);
  return data;
}

export async function generateClarification(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse['clarification']> {
  const { data } = await api.post<ContentGenerateResponse['clarification']>('/content/clarification', request);
  return data;
}

export async function generateFAQ(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse['faq']> {
  const { data } = await api.post<ContentGenerateResponse['faq']>('/content/faq', request);
  return data;
}

export async function generatePlatformScripts(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse['platform_scripts']> {
  const { data } = await api.post<ContentGenerateResponse['platform_scripts']>('/content/platform-scripts', request);
  return data;
}

// ========== Chat Workbench API ==========

export type ChatAction =
  | { type: 'link'; label: string; href: string }
  | { type: 'command'; label: string; command: string };

export type ChatReference = {
  title: string;
  href: string;
  description?: string;
};

export type ChatMessage = {
  role: 'user' | 'assistant' | 'system';
  content: string;
  actions?: ChatAction[];
  references?: ChatReference[];
  meta?: Record<string, unknown>;
};

export type ChatSendRequest = {
  session_id?: string | null;
  text: string;
  context?: Record<string, unknown> | null;
};

export type ChatSendResponse = {
  session_id: string;
  assistant_message: ChatMessage;
};

export type ChatSession = {
  session_id: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
  meta?: Record<string, unknown>;
};

export type ChatSessionListResponse = {
  sessions: ChatSession[];
};

export type ChatSessionDetailResponse = {
  session: ChatSession;
  messages: Array<ChatMessage & { id?: string; created_at?: string; meta?: Record<string, unknown> }>;
};

export async function createChatSession(payload?: {
  title?: string | null;
  meta?: Record<string, unknown> | null;
}): Promise<ChatSession> {
  const { data } = await api.post<ChatSession>('/chat/sessions', payload ?? {});
  return data;
}

export async function listChatSessions(limit = 20): Promise<ChatSessionListResponse> {
  const { data } = await api.get<ChatSessionListResponse>('/chat/sessions', { params: { limit } });
  return data;
}

export async function getChatSessionDetail(
  sessionId: string,
  limit = 50
): Promise<ChatSessionDetailResponse> {
  const { data } = await api.get<ChatSessionDetailResponse>(`/chat/sessions/${sessionId}`, {
    params: { limit },
  });
  return data;
}

export async function chatSend(payload: ChatSendRequest): Promise<ChatSendResponse> {
  const { data } = await api.post<ChatSendResponse>('/chat', payload);
  return data;
}

export type ChatStreamEvent =
  | { type: 'token'; data: { content: string; session_id: string } }
  | { type: 'stage'; data: { session_id: string; stage: string; status: string; message?: string } }
  | { type: 'message'; data: { session_id: string; message: ChatMessage } }
  | { type: 'done'; data: { session_id: string } }
  | { type: 'error'; data: { session_id: string; message: string } };

export async function chatStream(
  payload: ChatSendRequest,
  onEvent: (event: ChatStreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Chat stream failed: ${response.status}`);
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as ChatStreamEvent;
          onEvent(event);
        } catch {
          console.warn('Failed to parse chat SSE event:', line);
        }
      }
    }
  }
}

export type ChatSessionMessageStreamRequest = {
  text: string;
  context?: Record<string, unknown> | null;
};

export async function chatSessionStream(
  sessionId: string,
  payload: ChatSessionMessageStreamRequest,
  onEvent: (event: ChatStreamEvent) => void
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Chat session stream failed: ${response.status}`);
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as ChatStreamEvent;
          onEvent(event);
        } catch {
          console.warn('Failed to parse chat session SSE event:', line);
        }
      }
    }
  }
}
