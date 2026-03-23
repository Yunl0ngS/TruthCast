export type StrategyConfig = {
  max_claims: number;
  complexity_level: string;
  complexity_reason: string;
  evidence_per_claim: number;
  risk_level: string;
  risk_reason: string;
  summary_target_min: number;
  summary_target_max: number;
  enable_summarization: boolean;
  is_news: boolean;
  news_confidence: number;
  detected_text_type: string;
  news_reason: string;
};

export type DetectResponse = {
  label: string;
  confidence: number;
  score: number;
  reasons: string[];
  strategy?: StrategyConfig | null;
  truncated?: boolean;
};

export type ImageInput = {
  file_id?: string | null;
  url?: string | null;
  filename?: string | null;
};

export type StoredImage = {
  file_id: string;
  filename: string;
  mime_type: string;
  size: number;
  public_url?: string | null;
};

export type OCRBlock = {
  text: string;
  confidence: number;
  bbox?: number[] | null;
};

export type ImageOCRResult = {
  file_id?: string | null;
  source_url?: string | null;
  ocr_text: string;
  blocks: OCRBlock[];
  confidence: number;
  extraction_source: string;
  status: string;
  error_message?: string | null;
};

export type ImageAnalysisResult = {
  file_id?: string | null;
  source_url?: string | null;
  image_summary: string;
  relevance_score: number;
  relevance_reason: string;
  key_elements: string[];
  matched_claims: string[];
  semantic_conflicts: string[];
  image_credibility_label: string;
  image_credibility_score: number;
  status: string;
  error_message?: string | null;
};

export type MultimodalFusionReport = {
  final_risk_score: number;
  final_risk_label: string;
  multimodal_consistency: string;
  conflict_points: string[];
  fusion_summary: string;
  should_simulate: boolean;
  image_evidence_status: string;
};

export type UrlDetectRequest = {
  url: string;
};

export type UrlCommentItem = {
  username: string;
  content: string;
  publish_time: string;
};

export type UrlDetectResponse = {
  url: string;
  title: string;
  content: string;
  publish_date: string;
  comments: UrlCommentItem[];
  risk: DetectResponse | null;
  success: boolean;
  error_msg?: string;
};

export type UrlCrawlResponse = {
  url: string;
  title: string;
  content: string;
  publish_date: string;
  comments: UrlCommentItem[];
  success: boolean;
  error_msg?: string;
};

export type ClaimItem = {
  claim_id: string;
  claim_text: string;
  entity?: string | null;
  time?: string | null;
  location?: string | null;
  value?: string | null;
  source_sentence: string;
};

export type EvidenceItem = {
  evidence_id: string;
  claim_id: string;
  title: string;
  source: string;
  url: string;
  published_at: string;
  summary: string;
  stance: string;
  source_weight: number;
  source_type?: string;
  retrieved_at?: string | null;
  domain?: string | null;
  is_authoritative?: boolean | null;
  raw_snippet?: string | null;
  alignment_rationale?: string | null;
  alignment_confidence?: number | null;
  source_urls?: string[];
};

export type ClaimReport = {
  claim: ClaimItem;
  evidences: EvidenceItem[];
  final_stance: string;
  notes: string[];
};

export type ReportResponse = {
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
  claim_reports: ClaimReport[];
  multimodal?: Record<string, unknown> | null;
};

export type MultimodalDetectResponse = {
  raw_text: string;
  enhanced_text: string;
  images: StoredImage[];
  ocr_results: ImageOCRResult[];
  image_analyses: ImageAnalysisResult[];
  detect_data?: DetectResponse | null;
  claims: ClaimItem[];
  evidences: EvidenceItem[];
  report?: ReportResponse | null;
  fusion_report?: MultimodalFusionReport | null;
  record_id?: string | null;
};

export type NarrativeItem = {
  title: string;
  stance: string;
  probability: number;
  trigger_keywords: string[];
  sample_message: string;
};

export type TimelineItem = {
  hour: number;
  event: string;
  expected_reach: string;
};

export type ActionItem = {
  priority: 'urgent' | 'high' | 'medium';
  category: 'official' | 'media' | 'platform' | 'user';
  action: string;
  timeline: string;
  responsible?: string;
};

export type SuggestionData = {
  summary: string;
  actions: ActionItem[];
};

export type SimulateResponse = {
  emotion_distribution: Record<string, number>;
  stance_distribution: Record<string, number>;
  narratives: NarrativeItem[];
  flashpoints: string[];
  suggestion: SuggestionData;
  timeline?: TimelineItem[];
  emotion_drivers?: Record<string, string[]>;
  stance_drivers?: Record<string, string[]>;
};

export type HistoryItem = {
  id: string;
  created_at: string;
  input_preview: string;
  risk_label: string;
  risk_score: number;
  detected_scenario: string;
  evidence_domains: string[];
  feedback_status?: string | null;
};

export type HistoryDetail = {
  id: string;
  created_at: string;
  input_text: string;
  risk_label: string;
  risk_score: number;
  detected_scenario: string;
  evidence_domains: string[];
  report: ReportResponse;
  detect_data?: DetectResponse | null;
  simulation?: SimulateResponse | null;
  content?: ContentDraft | null;
  feedback_status?: string | null;
  feedback_note?: string | null;
};

export type MonitorNotifyChannel = 'webhook' | 'wecom' | 'dingtalk' | 'feishu' | 'email';
export type MonitorTriggerMode = 'threshold' | 'hit' | 'smart';
export type MonitorSubscriptionType = 'keyword' | 'topic';
export type MonitorAlertStatus = 'pending' | 'sent' | 'acknowledged' | 'ignored';
export type MonitorTrendDirection = 'rising' | 'stable' | 'falling' | 'new';

export type MonitorSubscription = {
  id: string;
  user_id: string;
  name: string;
  type: MonitorSubscriptionType;
  keywords: string[];
  match_mode: 'any' | 'all' | 'regex';
  platforms: string[];
  exclude_keywords: string[];
  trigger_mode: MonitorTriggerMode;
  risk_threshold: number;
  smart_threshold: Record<string, unknown>;
  notify_channels: MonitorNotifyChannel[];
  notify_config: Record<string, unknown>;
  notify_template?: string | null;
  quiet_hours?: Record<string, unknown> | null;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
};

export type MonitorSubscriptionCreate = {
  name: string;
  type: MonitorSubscriptionType;
  keywords: string[];
  match_mode: 'any' | 'all' | 'regex';
  platforms: string[];
  exclude_keywords: string[];
  trigger_mode: MonitorTriggerMode;
  risk_threshold: number;
  notify_channels: MonitorNotifyChannel[];
  notify_config: Record<string, unknown>;
  priority?: number;
};

export type MonitorHotItem = {
  id: string;
  platform: string;
  title: string;
  url: string;
  summary?: string | null;
  cover_image?: string | null;
  hot_value: number;
  rank: number;
  trend: MonitorTrendDirection;
  risk_score?: number | null;
  risk_level?: string | null;
  risk_assessed_at?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  last_hot_value: number;
  extra: Record<string, unknown>;
  raw_data: Record<string, unknown>;
};

export type MonitorAlert = {
  id: string;
  hot_item_id: string;
  trigger_reason: string;
  trigger_mode: MonitorTriggerMode;
  matched_subscriptions: string[];
  matched_keywords: string[];
  risk_score: number;
  risk_level: string;
  risk_summary?: string | null;
  hot_item_title: string;
  hot_item_url: string;
  hot_item_platform: string;
  hot_item_hot_value: number;
  hot_item_rank: number;
  status: MonitorAlertStatus;
  priority: number;
  notify_channels: MonitorNotifyChannel[];
  notify_results: Array<Record<string, unknown>>;
  created_at: string;
  sent_at?: string | null;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  cooldown_until?: string | null;
};

export type MonitorStatus = {
  running: boolean;
  adaptive_mode: boolean;
  manual_scan_auto_analyze_default: boolean;
  enabled_platforms: Array<{ key: string; display_name: string }>;
  default_interval_minutes: number | null;
  effective_interval_minutes: number | null;
  platform_intervals: Record<string, number>;
  last_scan_at?: string | null;
  last_scan_summary: Record<string, { fetched: number; new?: number; updated?: number; removed?: number; alert_candidates: number }>;
  failure_count: number;
  platform_failures: Record<string, number>;
  last_error?: { platform: string; message: string; at: string } | null;
  last_scan_duration_ms?: number | null;
  platform_durations_ms: Record<string, number>;
};

export type MonitorScanResponse = {
  scanned_platforms: string[];
  saved_count: number;
  total_fetched: number;
  window_id?: string | null;
  auto_analyze: boolean;
  analysis_scheduled: boolean;
};

export type MonitorAnalysisStage =
  | 'hot_item'
  | 'crawl'
  | 'risk_snapshot'
  | 'report'
  | 'simulation'
  | 'content'
  | 'completed';

export type MonitorAnalysisResult = {
  id: string;
  hot_item_id: string;
  platform: string;
  source_url: string;
  crawl_status: string;
  crawl_title?: string | null;
  crawl_content?: string | null;
  crawl_publish_date?: string | null;
  risk_snapshot_score?: number | null;
  risk_snapshot_label?: string | null;
  risk_snapshot_reasons: string[];
  raw_evidences: EvidenceItem[];
  evidences: EvidenceItem[];
  current_stage: MonitorAnalysisStage;
  report_score?: number | null;
  report_level?: string | null;
  report_data?: ReportResponse | null;
  simulation_status: string;
  simulation_data?: SimulateResponse | null;
  content_generation_status: string;
  content_data?: ContentDraft | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

export type MonitorScanTriggerType = 'scheduled' | 'manual';
export type MonitorScanWindowStatus = 'running' | 'completed' | 'failed';

export type MonitorScanWindow = {
  id: string;
  window_start: string;
  window_end: string;
  trigger_type: MonitorScanTriggerType;
  status: MonitorScanWindowStatus;
  platforms: string[];
  fetched_count: number;
  deduplicated_count: number;
  analyzed_count: number;
  duplicate_count: number;
  created_at: string;
  updated_at: string;
};

export type MonitorWindowItem = {
  id: string;
  window_id: string;
  platform: string;
  platform_display_name?: string | null;
  hot_item_id?: string | null;
  analysis_result_id?: string | null;
  duplicate_of_analysis_result_id?: string | null;
  analysis_status: 'pending' | 'running' | 'done' | 'failed';
  dedupe_key: string;
  title: string;
  url: string;
  hot_value: number;
  rank: number;
  trend: MonitorTrendDirection;
  is_duplicate_across_windows: boolean;
  created_at: string;
  analysis_result?: MonitorAnalysisResult | null;
};

export type MonitorScanWindowDetail = {
  window: MonitorScanWindow;
  items: MonitorWindowItem[];
};

export type Phase = 'detect' | 'claims' | 'evidence' | 'report' | 'simulation' | 'content';
export type PhaseStatus = 'idle' | 'running' | 'done' | 'failed' | 'canceled';
export type PhaseState = Record<Phase, PhaseStatus>;

// ========== 应对内容生成类型 ==========

export type ClarificationStyle = 'formal' | 'friendly' | 'neutral';

export type Platform = 
  | 'weibo' 
  | 'wechat' 
  | 'short_video' 
  | 'news' 
  | 'official' 
  | 'xiaohongshu' 
  | 'douyin' 
  | 'kuaishou' 
  | 'bilibili';

export type FAQItem = {
  question: string;
  answer: string;
  category: string;
};

export type ClarificationContent = {
  short: string;
  medium: string;
  long: string;
};

export type ClarificationVariant = {
  id: string;
  style: ClarificationStyle;
  content: ClarificationContent;
  generated_at: string;
};

export type PlatformScript = {
  platform: Platform;
  content: string;
  tips: string[];
  hashtags?: string[] | null;
  estimated_read_time?: string | null;
};

export type ContentGenerateRequest = {
  text: string;
  report: ReportResponse;
  simulation?: SimulateResponse | null;
  clarification?: ClarificationContent | null;
  style?: ClarificationStyle;
  platforms?: Platform[];
  include_faq?: boolean;
  faq_count?: number;
};

export type ContentGenerateResponse = {
  clarification: ClarificationContent;
  faq: FAQItem[] | null;
  platform_scripts: PlatformScript[];
  generated_at: string;
  based_on: Record<string, unknown>;
};

// 前端内容生成的"草稿态"：允许按模块（澄清稿/FAQ/平台话术）逐步生成并即时展示
export type ContentDraft = {
  clarification?: ClarificationContent;
  // 支持澄清稿多风格/多版本并存
  clarifications?: ClarificationVariant[];
  primary_clarification_id?: string;
  faq?: FAQItem[] | null;
  platform_scripts?: PlatformScript[];
  generated_at?: string;
  based_on?: Record<string, unknown>;
};
