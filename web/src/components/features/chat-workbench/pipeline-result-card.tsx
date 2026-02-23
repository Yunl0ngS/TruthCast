'use client';

import { useMemo, useState, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  FileText,
  Info,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  ShieldX,
} from 'lucide-react';
import { zhEmotion, zhRiskLabel, zhSimulationStance, zhText } from '@/lib/i18n';
import type { ClaimItem, DetectResponse, EvidenceItem, PhaseState, ReportResponse } from '@/types';
import type { SimulationStage } from '@/services/api';

const ReactECharts = dynamic(() => import('echarts-for-react'), { ssr: false });

function safeStringify(v: unknown) {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // 兜底：旧浏览器
    try {
      const el = document.createElement('textarea');
      el.value = text;
      el.style.position = 'fixed';
      el.style.opacity = '0';
      document.body.appendChild(el);
      el.focus();
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      return true;
    } catch {
      return false;
    }
  }
}

type CardStatus = 'running' | 'done' | 'failed' | 'canceled' | 'idle';

function statusVariant(status: CardStatus) {
  if (status === 'done') return 'default' as const;
  if (status === 'running') return 'secondary' as const;
  if (status === 'failed') return 'destructive' as const;
  return 'outline' as const;
}

function statusLabel(status: CardStatus) {
  switch (status) {
    case 'running':
      return '进行中';
    case 'done':
      return '已完成';
    case 'failed':
      return '失败';
    case 'canceled':
      return '已中断';
    case 'idle':
    default:
      return '未开始';
  }
}

function StatusIcon({ status }: { status: CardStatus }) {
  const cls = 'h-3.5 w-3.5';
  if (status === 'running') return <Loader2 className={`${cls} animate-spin`} aria-hidden />;
  if (status === 'done') return <CheckCircle2 className={cls} aria-hidden />;
  if (status === 'failed') return <AlertCircle className={cls} aria-hidden />;
  if (status === 'canceled') return <ShieldX className={cls} aria-hidden />;
  return <Info className={cls} aria-hidden />;
}

function riskLabelClass(label?: string | null) {
  switch (label) {
    case 'credible':
      return 'bg-green-500 text-white';
    case 'suspicious':
      return 'bg-yellow-500 text-black';
    case 'high_risk':
      return 'bg-orange-500 text-white';
    case 'needs_context':
      return 'bg-blue-500 text-white';
    case 'likely_misinformation':
      return 'bg-red-500 text-white';
    default:
      return 'bg-gray-500 text-white';
  }
}

function RiskIcon({ label }: { label?: string | null }) {
  const cls = 'h-4 w-4';
  switch (label) {
    case 'credible':
      return <ShieldCheck className={cls} aria-hidden />;
    case 'suspicious':
      return <ShieldAlert className={cls} aria-hidden />;
    case 'high_risk':
      return <ShieldAlert className={cls} aria-hidden />;
    case 'needs_context':
      return <ShieldQuestion className={cls} aria-hidden />;
    case 'likely_misinformation':
      return <ShieldX className={cls} aria-hidden />;
    default:
      return <FileText className={cls} aria-hidden />;
  }
}

function downloadTextFile(filename: string, content: string) {
  try {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch {
    // ignore
  }
}

function ResultCardShell({
  title,
  status,
  badges,
  actions,
  children,
}: {
  title: string;
  status: CardStatus;
  badges?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="py-4 gap-4 bg-muted/10 border shadow-sm">
      <CardHeader className="px-4 pb-0">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="text-sm truncate">{title}</CardTitle>
          </div>
          <div className="shrink-0 flex flex-wrap items-center gap-2">
            <Badge
              variant={statusVariant(status)}
              className="inline-flex items-center gap-1"
              aria-label={`状态：${statusLabel(status)}`}
              title={`状态：${statusLabel(status)}`}
            >
              <StatusIcon status={status} />
              {statusLabel(status)}
            </Badge>
            {badges}
          </div>
        </div>
        {actions ? <div className="pt-2 flex flex-wrap gap-2">{actions}</div> : null}
      </CardHeader>
      <CardContent className="px-4 space-y-3">{children}</CardContent>
    </Card>
  );
}

function JsonDialogButton({
  title,
  description,
  jsonText,
  fileName,
  triggerLabel = 'JSON',
}: {
  title: string;
  description?: string;
  jsonText: string;
  fileName?: string;
  triggerLabel?: string;
}) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" aria-label="展开 JSON">
          {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>
        <pre className="text-xs whitespace-pre-wrap break-words max-h-[60vh] overflow-auto rounded-md border bg-muted/20 p-3">
          {jsonText}
        </pre>
        <div className="flex flex-wrap justify-end gap-2">
          {fileName ? (
            <Button
              variant="secondary"
              onClick={() => downloadTextFile(fileName, jsonText)}
              aria-label="下载 JSON"
            >
              下载
            </Button>
          ) : null}
          <Button
            variant="secondary"
            onClick={async () => {
              const ok = await copyToClipboard(jsonText);
              if (!ok) alert('复制失败：当前环境不支持剪贴板');
            }}
            aria-label="复制 JSON"
          >
            复制 JSON
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function KpiTile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-md border bg-background p-2" title={hint}>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold break-words">{value}</div>
    </div>
  );
}

function TextClamp({
  text,
  collapsedChars = 240,
  className,
}: {
  text: string;
  collapsedChars?: number;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const shouldClamp = text.length > collapsedChars;
  const shown = !shouldClamp || open ? text : `${text.slice(0, collapsedChars)}…`;
  return (
    <div className={className}>
      <div className="text-sm whitespace-pre-wrap break-words">{shown}</div>
      {shouldClamp ? (
        <div className="pt-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label={open ? '收起文本' : '展开文本'}
          >
            {open ? '收起' : '展开'}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export type DetectCardMeta = {
  type: 'detect';
  taskId?: string | null;
  createdAt?: string | null;
  inputPreview?: string | null;
  inputLength?: number | null;
  phases?: PhaseState | null;
  status?: 'running' | 'done' | 'failed' | 'canceled' | 'idle';
  error?: string | null;
  detectData?: DetectResponse | null;
};

export type ClaimsCardMeta = {
  type: 'claims';
  taskId?: string | null;
  createdAt?: string | null;
  inputPreview?: string | null;
  inputLength?: number | null;
  status?: 'running' | 'done' | 'failed' | 'canceled' | 'idle';
  error?: string | null;
  claims?: ClaimItem[] | null;
};

export type EvidenceCardMeta = {
  type: 'evidence';
  taskId?: string | null;
  createdAt?: string | null;
  status?: 'running' | 'done' | 'failed' | 'canceled' | 'idle';
  error?: string | null;
  claims?: ClaimItem[] | null;
  rawEvidences?: EvidenceItem[] | null;
  evidences?: EvidenceItem[] | null;
};

export type ReportCardMeta = {
  type: 'report';
  taskId?: string | null;
  createdAt?: string | null;
  status?: 'running' | 'done' | 'failed' | 'canceled' | 'idle';
  error?: string | null;
  recordId?: string | null;
  inputText?: string | null;
  report?: ReportResponse | null;
};

export type SimulationStageCardMeta = {
  type: 'simulation_stage';
  taskId?: string | null;
  createdAt?: string | null;
  status?: 'running' | 'done' | 'failed' | 'canceled' | 'idle';
  error?: string | null;
  stage: SimulationStage;
  simulation?: Partial<import('@/types').SimulateResponse> | null;
  durationMs?: number | null;
};

export type PipelineProgressMeta = {
  type: 'pipeline_progress';
  taskId?: string | null;
  status?: 'running' | 'done' | 'failed' | 'canceled' | 'idle';
  lastEvent?: string | null;
  phases?: PhaseState | null;
};

export type ActivePhaseProgressProps = {
  taskId?: string | null;
  phase: keyof PhaseState;
  status: PhaseState[keyof PhaseState];
  lastEvent?: string | null;
  error?: string | null;
};

const PHASE_LABEL: Record<keyof PhaseState, string> = {
  detect: '风险快照',
  claims: '主张抽取',
  evidence: '证据处理',
  report: '综合报告',
  simulation: '舆情预演',
  content: '应对内容',
};

export function PipelineProgressCard({ meta }: { meta: PipelineProgressMeta }) {
  const phases = meta.phases ?? ({} as PhaseState);
  const status = meta.status ?? 'idle';

  const variantFor = (s: string) => {
    if (s === 'done') return 'default' as const;
    if (s === 'running') return 'secondary' as const;
    if (s === 'failed') return 'destructive' as const;
    return 'outline' as const;
  };

  return (
    <Card className="bg-muted/10">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">流水线进度</CardTitle>
          <Badge variant={variantFor(status)}>{status}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {meta.taskId ? (
          <div className="text-xs text-muted-foreground">
            任务ID：<span className="font-mono break-all">{meta.taskId}</span>
          </div>
        ) : null}

        {meta.lastEvent ? (
          <Alert>
            <AlertTitle>最新事件</AlertTitle>
            <AlertDescription className="whitespace-pre-wrap">{meta.lastEvent}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-wrap gap-2">
          {(Object.keys(PHASE_LABEL) as Array<keyof PhaseState>).map((p) => (
            <Badge key={p} variant={variantFor((phases as any)?.[p] ?? 'idle')}>
              {PHASE_LABEL[p]}：{(phases as any)?.[p] ?? 'idle'}
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function ActivePhaseProgressCard({ taskId, phase, status, lastEvent, error }: ActivePhaseProgressProps) {
  const variantFor = (s: string) => {
    if (s === 'done') return 'default' as const;
    if (s === 'running') return 'secondary' as const;
    if (s === 'failed') return 'destructive' as const;
    return 'outline' as const;
  };

  const phaseTitle = (PHASE_LABEL as any)?.[phase] ?? String(phase);

  const shortTaskId = (() => {
    if (!taskId) return null;
    const s = String(taskId);
    if (s.length <= 18) return s;
    return `${s.slice(0, 8)}…${s.slice(-4)}`;
  })();

  return (
    <Card className="bg-muted/10">
      <CardContent className="px-3 py-1 space-y-1">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">当前阶段：{phaseTitle}</div>
          </div>
          <Badge className="shrink-0" variant={variantFor(status)}>
            {status}
          </Badge>
        </div>

        <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <div className="min-w-0 truncate">
            {lastEvent ? `事件：${lastEvent}` : '事件：—'}
          </div>
          {shortTaskId ? <div className="shrink-0 font-mono">{shortTaskId}</div> : null}
        </div>

        {status === 'failed' && error ? (
          <div className="text-[11px] text-destructive whitespace-pre-wrap max-h-12 overflow-auto">
            错误：{error}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DetectResultCard({ meta }: { meta: DetectCardMeta }) {
  const data = meta.detectData ?? null;
  const reasons = Array.isArray(data?.reasons) ? data!.reasons : [];
  const confidencePct =
    typeof data?.confidence === 'number' ? `${Math.round(data.confidence * 100)}%` : 'N/A';

  const shortTaskId = (() => {
    const s = meta.taskId ? String(meta.taskId) : '';
    if (!s) return null;
    if (s.length <= 14) return s;
    return `${s.slice(0, 8)}…${s.slice(-4)}`;
  })();

  const md = useMemo(() => {
    const title = '### 风险快照（对话工作台）';
    const lines: string[] = [title, ''];
    if (meta.taskId) lines.push(`- 任务ID：\`${meta.taskId}\``);
    if (meta.createdAt) lines.push(`- 时间：${meta.createdAt}`);
    if (data) {
      lines.push(`- 结论：${zhRiskLabel(data.label)}（label=${data.label}）`);
      lines.push(`- 风险分数：${data.score}（分数越高=风险越高）`);
      lines.push(`- 置信度：${confidencePct}`);
      if (data.truncated) lines.push(`- 截断：是（长文本已截断）`);
      if (reasons.length) {
        lines.push('', '#### 关键原因');
        for (const r of reasons) lines.push(`- ${zhText(r)}`);
      }
    }
    if (meta.error) {
      lines.push('', '#### 错误');
      lines.push(meta.error);
    }
    return lines.join('\n');
  }, [confidencePct, data, meta.createdAt, meta.error, meta.taskId, reasons]);

  const jsonText = useMemo(() => safeStringify({ meta, detectData: data }), [data, meta]);
  const status: CardStatus = meta.status ?? (meta.error ? 'failed' : data ? 'done' : 'idle');

  const riskLabel = data?.label ?? null;
  const riskScore = typeof data?.score === 'number' ? String(data.score) : '—';
  const conf = confidencePct === 'N/A' ? '—' : confidencePct;

  return (
    <ResultCardShell
      title={shortTaskId ? `风险快照 · ${shortTaskId}` : '风险快照'}
      status={status}
      badges={null}
      actions={null}
    >
      {status === 'failed' && meta.error ? (
        <Alert variant="destructive">
          <AlertTitle>风险快照失败</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{meta.error}</AlertDescription>
        </Alert>
      ) : null}

      {status === 'running' ? (
        <Alert>
          <AlertTitle>进行中</AlertTitle>
          <AlertDescription>正在生成风险快照…</AlertDescription>
        </Alert>
      ) : null}

      {/* 核心指标：同一行三列；窄屏自动折行 */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <div className="rounded-md border bg-background p-2">
          <div className="text-[11px] text-muted-foreground">是否可信</div>
          <div className="pt-1">
            {riskLabel ? (
              <Badge
                className={`${riskLabelClass(riskLabel)} inline-flex items-center gap-1`}
                aria-label={`是否可信：${zhRiskLabel(riskLabel)}`}
                title={`是否可信：${zhRiskLabel(riskLabel)}`}
              >
                <RiskIcon label={riskLabel} />
                {zhRiskLabel(riskLabel)}
              </Badge>
            ) : (
              <Badge variant="outline" aria-label="是否可信：无数据">
                —
              </Badge>
            )}
          </div>
        </div>

        <KpiTile label="风险分数" value={<span className="font-mono">{riskScore}</span>} hint="分数越高=风险越高" />
        <KpiTile label="置信度" value={<span className="font-mono">{conf}</span>} />
      </div>

      {/* 风险点：直接列表（不含上下文/建议） */}
      <div className="rounded-md border bg-background p-2">
        <div className="text-xs font-medium text-muted-foreground mb-2">风险点</div>
        {reasons.length > 0 ? (
          <div className="space-y-1">
            {reasons.slice(0, 12).map((r, i) => (
              <div key={i} className="text-sm break-words">
                {i + 1}. {zhText(r)}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">暂无风险点</div>
        )}
      </div>

      {/* Footer actions：按钮靠左 */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            const ok = await copyToClipboard(md);
            if (!ok) alert('复制失败：当前环境不支持剪贴板');
          }}
          aria-label="复制 Markdown"
        >
          复制 Markdown
        </Button>
        <JsonDialogButton
          title="风险快照 JSON"
          description="用于调试/留存，不影响正常阅读。"
          jsonText={jsonText}
          fileName="truthcast_detect.json"
          triggerLabel="显示 JSON"
        />
      </div>
    </ResultCardShell>
  );
}

export function ClaimsResultCard({ meta }: { meta: ClaimsCardMeta }) {
  const claims = Array.isArray(meta.claims) ? meta.claims : [];
  const status = meta.status ?? (meta.error ? 'failed' : claims.length ? 'done' : 'idle');

  const md = useMemo(() => {
    const lines: string[] = ['### 主张抽取（对话工作台）', ''];
    if (meta.taskId) lines.push(`- 任务ID：\`${meta.taskId}\``);
    if (meta.createdAt) lines.push(`- 时间：${meta.createdAt}`);
    if (claims.length) {
      lines.push('', '#### 主张列表');
      for (const c of claims) {
        lines.push(`- ${c.claim_id}: ${c.claim_text}`);
      }
    }
    if (meta.error) {
      lines.push('', '#### 错误');
      lines.push(meta.error);
    }
    return lines.join('\n');
  }, [claims, meta.createdAt, meta.error, meta.inputLength, meta.inputPreview, meta.taskId]);

  const jsonText = useMemo(() => safeStringify({ meta, claims }), [claims, meta]);

  const clamp2Style: React.CSSProperties = {
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  };

  return (
    <ResultCardShell
      title="主张抽取"
      status={status as CardStatus}
      badges={null}
      actions={null}
    >
      {status === 'failed' && meta.error ? (
        <Alert variant="destructive">
          <AlertTitle>主张抽取失败</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{meta.error}</AlertDescription>
        </Alert>
      ) : null}

      {status === 'running' ? (
        <div className="space-y-2" aria-label="主张抽取进行中">
          <Alert>
            <AlertTitle>进行中</AlertTitle>
            <AlertDescription>正在抽取主张…</AlertDescription>
          </Alert>
          <div className="rounded-md border bg-background p-2">
            <div className="space-y-2 animate-pulse">
              <div className="h-4 bg-muted rounded" />
              <div className="h-4 bg-muted rounded" />
              <div className="h-4 bg-muted rounded" />
            </div>
          </div>
        </div>
      ) : null}

      {/* 主体：主张列表（按顺序编号；每条最多两行；无展开/无附加字段） */}
      {status !== 'running' ? (
        <div className="rounded-md border bg-background p-2">
          {claims.length > 0 ? (
            <div className="space-y-2 max-h-80 overflow-auto">
              {claims.map((c, idx) => (
                <div key={c.claim_id ?? String(idx)} className="text-sm break-words" style={clamp2Style}>
                  主张 {idx + 1}  {c.claim_text}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">暂无主张</div>
          )}
        </div>
      ) : null}

      {/* Footer actions：左下角固定 */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            const ok = await copyToClipboard(md);
            if (!ok) alert('复制失败：当前环境不支持剪贴板');
          }}
          aria-label="复制Markdown"
        >
          复制Markdown
        </Button>
        <JsonDialogButton
          title="主张抽取 JSON"
          description="用于调试/留存，不影响正常阅读。"
          jsonText={jsonText}
          fileName="truthcast_claims.json"
          triggerLabel="显示 JSON"
        />
      </div>
    </ResultCardShell>
  );
}

export function EvidenceResultCard({ meta }: { meta: EvidenceCardMeta }) {
  const claims = Array.isArray(meta.claims) ? meta.claims : [];
  const claimMap = useMemo(() => {
    const m = new Map<string, ClaimItem>();
    for (const c of claims) m.set(c.claim_id, c);
    return m;
  }, [claims]);

  const raw = Array.isArray(meta.rawEvidences) ? meta.rawEvidences : [];
  const aligned = Array.isArray(meta.evidences) ? meta.evidences : [];
  const status = meta.status ?? (meta.error ? 'failed' : aligned.length || raw.length ? 'done' : 'idle');

  const md = useMemo(() => {
    const lines: string[] = ['### 证据处理（对话工作台）', ''];
    if (meta.taskId) lines.push(`- 任务ID：\`${meta.taskId}\``);
    if (meta.createdAt) lines.push(`- 时间：${meta.createdAt}`);
    lines.push(`- 检索证据数：${raw.length}`);
    lines.push(`- 对齐/聚合证据数：${aligned.length}`);
    if (aligned.length) {
      lines.push('', '#### 对齐后证据（前10条）');
      for (const ev of aligned.slice(0, 10)) {
        lines.push(`- [${ev.claim_id}] ${ev.title} (${ev.stance}) ${ev.url}`);
      }
    }
    if (meta.error) {
      lines.push('', '#### 错误');
      lines.push(meta.error);
    }
    return lines.join('\n');
  }, [aligned, meta.createdAt, meta.error, meta.taskId, raw.length]);

  const jsonText = useMemo(() => safeStringify({ meta, rawEvidences: raw, evidences: aligned }), [aligned, meta, raw]);

  const groupByClaim = (items: EvidenceItem[]) => {
    const grouped = new Map<string, EvidenceItem[]>();
    for (const ev of items) {
      const cid = ev.claim_id || 'unknown';
      const list = grouped.get(cid) ?? [];
      list.push(ev);
      grouped.set(cid, list);
    }
    // 维持 claims 顺序优先；否则按 claim_id 排序
    const orderedClaimIds = claims.length
      ? claims.map((c) => c.claim_id)
      : Array.from(grouped.keys()).sort();

    return {
      grouped,
      orderedClaimIds: orderedClaimIds.filter((id) => grouped.has(id)).concat(
        Array.from(grouped.keys()).filter((id) => !orderedClaimIds.includes(id))
      ),
    };
  };

  const stanceKey = (stanceRaw: string | null | undefined) => {
    const s = String(stanceRaw ?? '').toLowerCase();
    if (s.includes('support') || s.includes('支持')) return 'support';
    // 反对/反驳/质疑 等都归入 oppose（用于“反对计数”）
    if (
      s.includes('oppose') ||
      s.includes('refute') ||
      s.includes('doubt') ||
      s.includes('skeptic') ||
      s.includes('反对') ||
      s.includes('反驳') ||
      s.includes('质疑')
    )
      return 'oppose';
    if (s.includes('insufficient') || s.includes('证据不足')) return 'insufficient_evidence';
    return 'unknown';
  };

  const stanceVariant = (k: string) => {
    switch (k) {
      case 'support':
        return 'default' as const;
      case 'oppose':
        return 'destructive' as const;
      case 'insufficient_evidence':
        return 'secondary' as const;
      default:
        return 'outline' as const;
    }
  };

  const zhDomain = (d?: string | null) => {
    const key = String(d ?? '').trim();
    if (!key) return '综合';
    const map: Record<string, string> = {
      health: '健康',
      governance: '政务治理',
      security: '公共安全',
      media: '媒体辟谣',
      technology: '科技',
      education: '教育',
      general: '综合',
    };
    return map[key] ?? key;
  };

  const linkGroup = (ev: EvidenceItem) => {
    const urls: string[] = [];
    if (Array.isArray(ev.source_urls)) {
      for (const u of ev.source_urls) {
        if (u && !urls.includes(u)) urls.push(u);
      }
    }
    if (ev.url && !urls.includes(ev.url)) urls.push(ev.url);
    return urls.slice(0, 10);
  };

  return (
    <Card className="bg-muted/20">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">证据处理</CardTitle>
          <Badge
            variant={statusVariant(status as CardStatus)}
            className="inline-flex items-center gap-1"
            aria-label={`状态：${statusLabel(status as CardStatus)}`}
            title={`状态：${statusLabel(status as CardStatus)}`}
          >
            <StatusIcon status={status as CardStatus} />
            {statusLabel(status as CardStatus)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {status === 'failed' && meta.error ? (
          <Alert variant="destructive">
            <AlertTitle>证据处理失败</AlertTitle>
            <AlertDescription className="whitespace-pre-wrap">{meta.error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="grid grid-cols-2 gap-2">
          <KpiTile label="检索证据" value={raw.length} />
          <KpiTile label="对齐后证据" value={aligned.length} />
        </div>

        <Tabs defaultValue="aligned" className="w-full">
          <TabsList className="w-full grid grid-cols-2">
            <TabsTrigger value="aligned">对齐/聚合证据</TabsTrigger>
            <TabsTrigger value="raw">检索证据</TabsTrigger>
          </TabsList>

          <TabsContent value="aligned" className="mt-3">
            {(() => {
              const { grouped, orderedClaimIds } = groupByClaim(aligned);
              if (orderedClaimIds.length === 0) {
                return <div className="text-xs text-muted-foreground">暂无对齐/聚合证据</div>;
              }
              return (
                <div className="rounded-md border p-2 max-h-80 overflow-auto space-y-4">
                  {orderedClaimIds.map((cid) => {
                    const claim = claimMap.get(cid);
                    const items = grouped.get(cid) ?? [];
                    const stanceCounts: Record<string, number> = {
                      support: 0,
                      oppose: 0,
                      insufficient_evidence: 0,
                      unknown: 0,
                    };
                    let authoritativeCount = 0;
                    for (const ev of items) {
                      stanceCounts[stanceKey(ev.stance)]++;
                      if (ev.is_authoritative) authoritativeCount++;
                    }
                    return (
                      <div key={cid} className="space-y-2">
                        <div className="text-sm font-semibold break-words">
                          {claim ? `${claim.claim_id}：${claim.claim_text}` : `主张：${cid}`}
                        </div>
                        <div className="text-xs text-muted-foreground flex flex-wrap gap-2">
                          <span>覆盖证据 {items.length} 条</span>
                          <span>支持 {stanceCounts.support}</span>
                          <span>反对 {stanceCounts.oppose}</span>
                          <span>不足 {stanceCounts.insufficient_evidence}</span>
                          <span>权威 {authoritativeCount}</span>
                        </div>
                        <Separator />

                        <div className="space-y-2">
                          {items.map((ev) => {
                            const sk = stanceKey(ev.stance);
                            return (
                              <div key={ev.evidence_id} className="rounded-md border bg-background p-2 space-y-1">
                                <div className="flex flex-wrap items-start justify-between gap-2">
                                  <div className="min-w-0">
                                    <div className="font-medium text-xs break-words">
                                      {ev.url ? (
                                        <a
                                          href={ev.url}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="underline"
                                        >
                                          {ev.title}
                                        </a>
                                      ) : (
                                        ev.title
                                      )}
                                    </div>
                                  </div>
                                  <div className="shrink-0 flex flex-wrap gap-1">
                                    <Badge variant={stanceVariant(sk)}>{zhText(ev.stance)}</Badge>
                                    {ev.is_authoritative ? <Badge variant="secondary">权威</Badge> : null}
                                    {ev.domain ? <Badge variant="outline">{zhDomain(ev.domain)}</Badge> : null}
                                  </div>
                                </div>

                                <div className="text-[11px] text-muted-foreground flex flex-wrap gap-2">
                                  {ev.source ? <span>来源：{ev.source}</span> : null}
                                  {ev.published_at ? <span>时间：{ev.published_at}</span> : null}
                                  {ev.source_type ? <span>类型：{ev.source_type}</span> : null}
                                  {typeof ev.alignment_confidence === 'number' ? (
                                    <span>对齐置信度：{ev.alignment_confidence.toFixed(2)}</span>
                                  ) : null}
                                </div>

                                {ev.summary ? (
                                  <div className="text-xs whitespace-pre-wrap break-words">摘要：{ev.summary}</div>
                                ) : null}
                                {ev.alignment_rationale ? (
                                  <div className="text-xs whitespace-pre-wrap break-words">对齐理由：{ev.alignment_rationale}</div>
                                ) : null}

                                {(() => {
                                  const urls = linkGroup(ev);
                                  if (urls.length === 0) return null;
                                  return (
                                    <div className="pt-1 flex flex-wrap items-center gap-2 text-xs">
                                      <span className="text-muted-foreground">来源链接：</span>
                                      <div className="flex flex-wrap gap-2">
                                        {urls.map((linkUrl, linkIdx) => (
                                          <a
                                            key={linkIdx}
                                            href={linkUrl}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="inline-flex items-center gap-0.5 text-primary hover:underline"
                                            aria-label={`打开来源链接 ${linkIdx + 1}`}
                                            title={linkUrl}
                                          >
                                            <ExternalLink className="h-3 w-3" />
                                            <span>{linkIdx + 1}</span>
                                          </a>
                                        ))}
                                      </div>
                                    </div>
                                  );
                                })()}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })()}
          </TabsContent>

          <TabsContent value="raw" className="mt-3">
            {(() => {
              const { grouped, orderedClaimIds } = groupByClaim(raw);
              if (orderedClaimIds.length === 0) {
                return <div className="text-xs text-muted-foreground">暂无检索证据</div>;
              }
              return (
                <div className="rounded-md border p-2 max-h-80 overflow-auto space-y-4">
                  {orderedClaimIds.map((cid) => {
                    const claim = claimMap.get(cid);
                    const items = grouped.get(cid) ?? [];
                    return (
                      <div key={cid} className="space-y-2">
                        <div className="text-sm font-semibold break-words">
                          {claim ? `${claim.claim_id}：${claim.claim_text}` : `主张：${cid}`}
                        </div>
                        <div className="text-xs text-muted-foreground">覆盖证据 {items.length} 条</div>
                        <Separator />

                        <div className="space-y-2">
                          {items.map((ev) => (
                            <div key={ev.evidence_id} className="rounded-md border bg-background p-2 space-y-1">
                              <div className="font-medium text-xs break-words">
                                {ev.url ? (
                                  <a href={ev.url} target="_blank" rel="noreferrer" className="underline">
                                    {ev.title}
                                  </a>
                                ) : (
                                  ev.title
                                )}
                              </div>
                              <div className="text-[11px] text-muted-foreground flex flex-wrap gap-2">
                                {ev.source ? <span>来源：{ev.source}</span> : null}
                                {ev.published_at ? <span>时间：{ev.published_at}</span> : null}
                                {ev.source_type ? <span>类型：{ev.source_type}</span> : null}
                                {ev.domain ? <span>领域：{zhDomain(ev.domain)}</span> : null}
                              </div>
                              {ev.raw_snippet ? (
                                <div className="text-xs whitespace-pre-wrap break-words">片段：{ev.raw_snippet}</div>
                              ) : null}
                              {ev.summary ? (
                                <div className="text-xs whitespace-pre-wrap break-words">摘要：{ev.summary}</div>
                              ) : null}

                              {(() => {
                                const urls = linkGroup(ev);
                                if (urls.length === 0) return null;
                                return (
                                  <div className="pt-1 flex flex-wrap items-center gap-2 text-xs">
                                    <span className="text-muted-foreground">来源链接：</span>
                                    <div className="flex flex-wrap gap-2">
                                      {urls.map((linkUrl, linkIdx) => (
                                        <a
                                          key={linkIdx}
                                          href={linkUrl}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="inline-flex items-center gap-0.5 text-primary hover:underline"
                                          aria-label={`打开来源链接 ${linkIdx + 1}`}
                                          title={linkUrl}
                                        >
                                          <ExternalLink className="h-3 w-3" />
                                          <span>{linkIdx + 1}</span>
                                        </a>
                                      ))}
                                    </div>
                                  </div>
                                );
                              })()}
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })()}
          </TabsContent>
        </Tabs>

        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={async () => {
            const ok = await copyToClipboard(md);
            if (!ok) alert('复制失败：当前环境不支持剪贴板');
          }}>
            复制 Markdown
          </Button>
          <JsonDialogButton
            title="证据处理 JSON"
            description="用于调试/留存，不影响正常阅读。"
            jsonText={jsonText}
            fileName="truthcast_evidence.json"
            triggerLabel="显示 JSON"
          />
        </div>

        {/* 不在卡片中直接展示 JSON（完整数据），避免信息噪音；保留“复制 JSON”用于调试/留存 */}
      </CardContent>
    </Card>
  );
}

export function ReportResultCard({ meta }: { meta: ReportCardMeta }) {
  const report = meta.report ?? null;
  const status = meta.status ?? (meta.error ? 'failed' : report ? 'done' : 'idle');

  const md = useMemo(() => {
    const lines: string[] = ['### 综合报告（对话工作台）', ''];
    if (meta.taskId) lines.push(`- 任务ID：\`${meta.taskId}\``);
    if (meta.createdAt) lines.push(`- 时间：${meta.createdAt}`);
    if (meta.recordId) lines.push(`- 记录ID：\`${meta.recordId}\``);

    if (meta.inputText) {
      lines.push('', '#### 原始新闻文本', meta.inputText);
    }
    if (report) {
      lines.push(`- 风险结论：${report.risk_label}（score=${report.risk_score}）`);
      if (report.detected_scenario) lines.push(`- 场景：${report.detected_scenario}`);
      if (Array.isArray(report.evidence_domains) && report.evidence_domains.length)
        lines.push(`- 证据域：${report.evidence_domains.join(', ')}`);
      if (report.summary) {
        lines.push('', '#### 摘要', report.summary);
      }
      if (Array.isArray(report.suspicious_points) && report.suspicious_points.length) {
        lines.push('', '#### 可疑点');
        for (const p of report.suspicious_points) lines.push(`- ${p}`);
      }

      if (Array.isArray(report.claim_reports) && report.claim_reports.length) {
        lines.push('', '#### 主张级结论');
        for (const cr of report.claim_reports) {
          lines.push('', `**${cr.claim.claim_id}：${cr.claim.claim_text}**`);
          lines.push(`- 最终立场：${cr.final_stance}`);
          if (Array.isArray(cr.notes) && cr.notes.length) {
            lines.push('- 要点：');
            for (const n of cr.notes) lines.push(`  - ${n}`);
          }
          if (Array.isArray(cr.evidences) && cr.evidences.length) {
            lines.push('- 证据（节选）：');
            for (const ev of cr.evidences.slice(0, 10)) {
              lines.push(`  - ${ev.title}（${ev.stance}） ${ev.url}`);
            }
          }
        }
      }
    }
    if (meta.error) {
      lines.push('', '#### 错误');
      lines.push(meta.error);
    }
    return lines.join('\n');
  }, [meta.createdAt, meta.error, meta.inputText, meta.recordId, meta.taskId, report]);

  const jsonText = useMemo(() => safeStringify({ meta, report }), [meta, report]);

  const [activeSection, setActiveSection] = useState<'tldr' | 'findings' | 'risks'>('tldr');

  const riskLabelZh = (label?: string | null) => {
    const raw = String(label ?? '').trim();
    const map: Record<string, string> = {
      credible: '可信',
      suspicious: '可疑',
      high_risk: '高风险',
      needs_context: '需要补充语境',
      likely_misinformation: '疑似不实信息',
    };
    return map[raw] ?? (raw || '—');
  };

  const zhDomain = (d?: string | null) => {
    const key = String(d ?? '').trim();
    if (!key) return '综合';
    const map: Record<string, string> = {
      health: '健康',
      governance: '政务治理',
      security: '公共安全',
      media: '媒体辟谣',
      technology: '科技',
      education: '教育',
      general: '综合',
    };
    return map[key] ?? key;
  };

  return (
    <ResultCardShell
      title="综合报告"
      status={status as CardStatus}
      badges={null}
      actions={null}
    >
      {status === 'failed' && meta.error ? (
        <Alert variant="destructive">
          <AlertTitle>综合报告失败</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{meta.error}</AlertDescription>
        </Alert>
      ) : null}

      {status === 'running' ? (
        <Alert>
          <AlertTitle>进行中</AlertTitle>
          <AlertDescription>正在汇总证据并生成综合报告…</AlertDescription>
        </Alert>
      ) : null}

      {report ? (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <KpiTile label="风险结论" value={riskLabelZh(report.risk_label)} />
            <KpiTile label="风险分数" value={report.risk_score} hint="分数越高=风险越高" />

            <div className="rounded-md border bg-background p-2">
              <div className="text-[11px] text-muted-foreground">证据域覆盖</div>
              {Array.isArray(report.evidence_domains) && report.evidence_domains.length ? (
                <div className="pt-1 flex flex-wrap gap-1">
                  {report.evidence_domains.slice(0, 12).map((d) => (
                    <Badge key={d} variant="outline">
                      {zhDomain(d)}
                    </Badge>
                  ))}
                </div>
              ) : (
                <div className="text-sm font-semibold">—</div>
              )}
            </div>

            <KpiTile label="主张条数" value={Array.isArray(report.claim_reports) ? report.claim_reports.length : 0} />
          </div>

          <Tabs value={activeSection} onValueChange={(v) => setActiveSection(v as any)} className="w-full">
            <TabsList className="w-full grid grid-cols-3">
              <TabsTrigger value="tldr">TL;DR</TabsTrigger>
              <TabsTrigger value="findings">发现</TabsTrigger>
              <TabsTrigger value="risks">风险</TabsTrigger>
            </TabsList>

            <TabsContent value="tldr" className="mt-3">
              <div className="rounded-md border bg-background p-3">
                {report.summary ? (
                  <TextClamp text={report.summary} collapsedChars={360} />
                ) : (
                  <div className="text-sm text-muted-foreground">暂无摘要</div>
                )}
              </div>
            </TabsContent>

            <TabsContent value="findings" className="mt-3 space-y-2">
              <div className="rounded-md border bg-background p-3">
                <div className="text-xs font-medium text-muted-foreground mb-2">主张级结论（可展开）</div>
                <div className="space-y-2 max-h-80 overflow-auto">
                  {report.claim_reports?.length ? (
                    report.claim_reports.map((cr) => (
                      <details key={cr.claim.claim_id} className="rounded-md border bg-muted/10 p-2">
                        <summary className="cursor-pointer select-none">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="text-sm font-medium break-words">
                                <span className="font-mono mr-1">{cr.claim.claim_id}</span>
                                {cr.claim.claim_text}
                              </div>
                              <div className="pt-1 flex flex-wrap gap-1">
                                <Badge variant="outline">立场：{zhText(cr.final_stance)}</Badge>
                                <Badge variant="secondary">证据 {cr.evidences?.length ?? 0}</Badge>
                              </div>
                            </div>
                            <Button
                              size="sm"
                              variant="outline"
                              className="shrink-0"
                              onClick={async (e) => {
                                e.preventDefault();
                                const ok = await copyToClipboard(`${cr.claim.claim_id}: ${cr.claim.claim_text}`);
                                if (!ok) alert('复制失败：当前环境不支持剪贴板');
                              }}
                              aria-label="复制主张"
                            >
                              复制
                            </Button>
                          </div>
                        </summary>
                        <div className="pt-2 space-y-2">
                          {cr.notes?.length ? (
                            <div className="rounded-md border bg-background p-2">
                              <div className="text-xs font-medium text-muted-foreground mb-1">要点/备注</div>
                              <div className="text-sm space-y-1">
                                {cr.notes.slice(0, 6).map((n, i) => (
                                  <div key={i} className="break-words">
                                    - {n}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          <div className="text-xs text-muted-foreground">
                            证据详情请在“检测结果页”查看证据链与对齐理由。
                          </div>
                        </div>
                      </details>
                    ))
                  ) : (
                    <div className="text-sm text-muted-foreground">暂无主张级结论</div>
                  )}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="risks" className="mt-3 space-y-2">
              <div className="rounded-md border bg-background p-3">
                <div className="text-xs font-medium text-muted-foreground mb-2">可疑点（Top）</div>
                {report.suspicious_points?.length ? (
                  <div className="space-y-1">
                    {report.suspicious_points.slice(0, 8).map((p, i) => (
                      <div key={i} className="text-sm break-words">
                        - {p}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">暂无可疑点列表</div>
                )}
              </div>
            </TabsContent>

          </Tabs>

          {/* Footer actions：左下角固定 */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                const ok = await copyToClipboard(md);
                if (!ok) alert('复制失败：当前环境不支持剪贴板');
              }}
              aria-label="复制Markdown"
            >
              复制Markdown
            </Button>
            <JsonDialogButton
              title="综合报告 JSON"
              description="用于调试/留存，不影响正常阅读。"
              jsonText={jsonText}
              fileName="truthcast_report.json"
              triggerLabel="显示 JSON"
            />
            {/* <Button
              size="sm"
              variant="outline"
              onClick={() => downloadTextFile('truthcast_full_report.md', md)}
              aria-label="导出完整报告"
            >
              导出
            </Button> */}
          </div>
        </>
      ) : (
        <div className="text-sm text-muted-foreground">暂无报告数据</div>
      )}
    </ResultCardShell>
  );
}

function stageLabel(stage: SimulationStage) {
  switch (stage) {
    case 'emotion':
      return '阶段 1/4：情绪与立场';
    case 'narratives':
      return '阶段 2/4：叙事分支';
    case 'flashpoints':
      return '阶段 3/4：引爆点';
    case 'suggestion':
      return '阶段 4/4：应对建议';
    default:
      return stage;
  }
}

function formatDuration(durationMs?: number | null) {
  if (!durationMs || durationMs <= 0) return null;
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function topDistribution(dist?: Record<string, number> | null, topN = 6) {
  const entries = Object.entries(dist ?? {});
  entries.sort((a, b) => b[1] - a[1]);
  return entries.slice(0, topN);
}

export function SimulationStageResultCard({ meta }: { meta: SimulationStageCardMeta }) {
  const status: CardStatus = meta.status ?? (meta.error ? 'failed' : 'done');
  const sim = meta.simulation ?? null;
  const durationText = formatDuration(meta.durationMs);

  const jsonText = useMemo(() => safeStringify(meta), [meta]);

  const md = useMemo(() => {
    const lines: string[] = [`### ${stageLabel(meta.stage)}（对话工作台）`, ''];
    if (meta.taskId) lines.push(`- 任务ID：\`${meta.taskId}\``);
    if (meta.createdAt) lines.push(`- 时间：${meta.createdAt}`);
    if (durationText) lines.push(`- 耗时：${durationText}`);
    if (meta.error) {
      lines.push('', '#### 错误', meta.error);
    }

    if (meta.stage === 'emotion' && sim) {
      const emo = (sim as any).emotion_distribution as Record<string, number> | undefined;
      const stance = (sim as any).stance_distribution as Record<string, number> | undefined;
      const topE = topDistribution(emo, 10);
      const topS = topDistribution(stance, 10);
      if (topE.length) {
        lines.push('', '#### 情绪分布');
        for (const [k, v] of topE) lines.push(`- ${zhEmotion(k)}：${Math.round(v * 100)}%`);
      }
      if (topS.length) {
        lines.push('', '#### 立场分布');
        for (const [k, v] of topS) lines.push(`- ${zhSimulationStance(k)}：${Math.round(v * 100)}%`);
      }
    }

    if (meta.stage === 'narratives' && sim) {
      const narratives = (sim as any).narratives as Array<any> | undefined;
      if (Array.isArray(narratives) && narratives.length) {
        lines.push('', '#### 叙事分支');
        for (const n of narratives.slice(0, 10)) {
          lines.push('', `**${n.title ?? '未命名叙事'}**`);
          if (n.stance) lines.push(`- 立场：${n.stance}`);
          if (typeof n.probability === 'number') lines.push(`- 概率：${Math.round(n.probability * 100)}%`);
          if (Array.isArray(n.trigger_keywords) && n.trigger_keywords.length)
            lines.push(`- 触发关键词：${n.trigger_keywords.slice(0, 12).join('、')}`);
          if (n.sample_message) lines.push('', n.sample_message);
        }
      }
    }

    if (meta.stage === 'flashpoints' && sim) {
      const flashpoints = (sim as any).flashpoints as string[] | undefined;
      const timeline = (sim as any).timeline as Array<any> | undefined;
      if (Array.isArray(flashpoints) && flashpoints.length) {
        lines.push('', '#### 引爆点（Top）');
        for (const f of flashpoints.slice(0, 10)) lines.push(`- ${f}`);
      }
      if (Array.isArray(timeline) && timeline.length) {
        lines.push('', '#### 时间线（节选）');
        for (const t of timeline.slice(0, 8)) {
          lines.push(`- +${t.hour}h ${t.event}（预计触达：${t.expected_reach}）`);
        }
      }
    }

    if (meta.stage === 'suggestion' && sim) {
      const sug = (sim as any).suggestion as any;
      if (sug?.summary) {
        lines.push('', '#### 建议摘要', String(sug.summary));
      }
      if (Array.isArray(sug?.actions) && sug.actions.length) {
        lines.push('', '#### 行动清单（节选）');
        for (const a of sug.actions.slice(0, 12)) {
          lines.push(`- [${a.priority ?? ''}/${a.category ?? ''}] ${a.action ?? ''}`.trim());
          if (a.timeline) lines.push(`  - 时间：${a.timeline}`);
          if (a.responsible) lines.push(`  - 责任方：${a.responsible}`);
        }
      }
    }

    return lines.join('\n');
  }, [durationText, meta.createdAt, meta.error, meta.stage, meta.taskId, sim]);

  const emotionOption = useMemo(() => {
    if (meta.stage !== 'emotion') return null;
    const dist = (sim as any)?.emotion_distribution as Record<string, number> | undefined;
    if (!dist || Object.keys(dist).length === 0) return null;
    const data = Object.entries(dist).map(([name, value]) => ({ name: zhEmotion(name), value }));
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { show: false },
      series: [
        {
          type: 'pie',
          radius: ['35%', '70%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 8 },
          label: { show: true, formatter: '{b} {d}%', fontSize: 12 },
          labelLine: { show: true, length: 12, length2: 10 },
          data,
        },
      ],
    } as const;
  }, [meta.stage, sim]);

  const stanceOption = useMemo(() => {
    if (meta.stage !== 'emotion') return null;
    const dist = (sim as any)?.stance_distribution as Record<string, number> | undefined;
    if (!dist || Object.keys(dist).length === 0) return null;
    const data = Object.entries(dist).map(([name, value]) => ({ name: zhSimulationStance(name), value }));
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { show: false },
      series: [
        {
          type: 'pie',
          radius: ['35%', '70%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 8 },
          label: { show: true, formatter: '{b} {d}%', fontSize: 12 },
          labelLine: { show: true, length: 12, length2: 10 },
          data,
        },
      ],
    } as const;
  }, [meta.stage, sim]);

  return (
    <ResultCardShell
      title={stageLabel(meta.stage)}
      status={status}
      badges={
        <>
          {durationText ? <Badge variant="outline">耗时 {durationText}</Badge> : null}
          <Badge variant="secondary">舆情预演</Badge>
        </>
      }
      actions={
        meta.stage === 'emotion' ||
        meta.stage === 'narratives' ||
        meta.stage === 'flashpoints' ||
        meta.stage === 'suggestion'
          ? null
          : (
        <>
          <JsonDialogButton
            title="舆情预演阶段 JSON"
            description="用于调试/留存，不影响正常阅读。"
            jsonText={jsonText}
            fileName={`truthcast_simulation_${meta.stage}.json`}
          />
        </>
      )}
    >
      {status === 'failed' && meta.error ? (
        <Alert variant="destructive">
          <AlertTitle>阶段失败</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{meta.error}</AlertDescription>
        </Alert>
      ) : null}

      {meta.stage === 'emotion' ? (
        <div className="space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div className="rounded-md border bg-background p-2">
              <div className="text-xs font-medium text-muted-foreground mb-2">情绪分布（饼图）</div>
              {emotionOption ? (
                <ReactECharts option={emotionOption as any} style={{ height: 240 }} />
              ) : (
                <div className="text-sm text-muted-foreground">暂无</div>
              )}
            </div>
            <div className="rounded-md border bg-background p-2">
              <div className="text-xs font-medium text-muted-foreground mb-2">立场分布（饼图）</div>
              {stanceOption ? (
                <ReactECharts option={stanceOption as any} style={{ height: 240 }} />
              ) : (
                <div className="text-sm text-muted-foreground">暂无</div>
              )}
            </div>
          </div>
          <div className="text-xs text-muted-foreground">提示：该阶段用于判断舆论基调，不等同于事实真伪结论。</div>

          {/* Footer actions（左下角固定） */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                const ok = await copyToClipboard(md);
                if (!ok) alert('复制失败：当前环境不支持剪贴板');
              }}
              aria-label="复制 Markdown"
            >
              复制 Markdown
            </Button>
            <JsonDialogButton
              title="舆情预演阶段 JSON"
              description="用于调试/留存，不影响正常阅读。"
              jsonText={jsonText}
              fileName={`truthcast_simulation_${meta.stage}.json`}
              triggerLabel="显示 JSON"
            />
          </div>
        </div>
      ) : null}

      {meta.stage === 'narratives' ? (
        <div className="space-y-2">
          {Array.isArray(sim?.narratives) && sim!.narratives.length ? (
            <div className="space-y-2">
              {sim!.narratives.slice(0, 6).map((n, idx) => (
                <div key={`${n.title}_${idx}`} className="rounded-md border bg-background p-2">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="text-sm font-medium break-words">{n.title}</div>
                    <div className="flex flex-wrap gap-1">
                      <Badge variant="outline">{zhText(n.stance)}</Badge>
                      <Badge variant="secondary">概率 {Math.round((n.probability ?? 0) * 100)}%</Badge>
                    </div>
                  </div>
                  {Array.isArray(n.trigger_keywords) && n.trigger_keywords.length ? (
                    <div className="pt-2 flex flex-wrap gap-1">
                      {n.trigger_keywords.slice(0, 10).map((k) => (
                        <Badge key={k} variant="outline">
                          {k}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                  {n.sample_message ? (
                    <div className="pt-2">
                      <div className="text-xs font-medium text-muted-foreground">舆论导向</div>
                      <div className="rounded-md border bg-muted/10 p-2">
                        <TextClamp text={n.sample_message} collapsedChars={220} />
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">暂无叙事分支</div>
          )}

          {/* Footer actions（左下角固定） */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                const ok = await copyToClipboard(md);
                if (!ok) alert('复制失败：当前环境不支持剪贴板');
              }}
              aria-label="复制 Markdown"
            >
              复制 Markdown
            </Button>
            <JsonDialogButton
              title="舆情预演阶段 JSON"
              description="用于调试/留存，不影响正常阅读。"
              jsonText={jsonText}
              fileName={`truthcast_simulation_${meta.stage}.json`}
              triggerLabel="显示 JSON"
            />
          </div>
        </div>
      ) : null}

      {meta.stage === 'flashpoints' ? (
        <div className="space-y-2">
          {Array.isArray(sim?.flashpoints) && sim!.flashpoints.length ? (
            <div className="rounded-md border bg-background p-2">
              <div className="text-xs font-medium text-muted-foreground mb-2">高风险引爆点（Top）</div>
              <div className="space-y-1 text-sm">
                {sim!.flashpoints.slice(0, 10).map((f, i) => (
                  <div key={i} className="break-words">
                    - {f}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">暂无引爆点</div>
          )}

          {Array.isArray(sim?.timeline) && sim!.timeline.length ? (
            <div className="rounded-md border bg-background p-2">
              <div className="text-xs font-medium text-muted-foreground mb-2">时间线（节选）</div>
              <div className="space-y-1 text-sm">
                {sim!.timeline.slice(0, 8).map((t, i) => (
                  <div key={i} className="flex items-start justify-between gap-2">
                    <span className="shrink-0 font-mono">+{t.hour}h</span>
                    <span className="flex-1 break-words">{t.event}</span>
                    <span className="shrink-0 text-muted-foreground">{t.expected_reach}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Footer actions（左下角固定） */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                const ok = await copyToClipboard(md);
                if (!ok) alert('复制失败：当前环境不支持剪贴板');
              }}
              aria-label="复制 Markdown"
            >
              复制 Markdown
            </Button>
            <JsonDialogButton
              title="舆情预演阶段 JSON"
              description="用于调试/留存，不影响正常阅读。"
              jsonText={jsonText}
              fileName={`truthcast_simulation_${meta.stage}.json`}
              triggerLabel="显示 JSON"
            />
          </div>
        </div>
      ) : null}

      {meta.stage === 'suggestion' ? (
        <div className="space-y-2">
          {(() => {
            const priorityZh: Record<string, string> = {
              urgent: '紧急',
              high: '高',
              medium: '中',
            };
            const categoryZh: Record<string, string> = {
              official: '官方回应',
              media: '媒体沟通',
              platform: '平台协调',
              user: '用户互动',
            };
            const zhPriority = (v: unknown) => priorityZh[String(v ?? '')] ?? String(v ?? '');
            const zhCategory = (v: unknown) => categoryZh[String(v ?? '')] ?? String(v ?? '');

            return (
              <>
          {sim?.suggestion?.summary ? (
            <div className="rounded-md border bg-background p-2">
              <div className="text-xs font-medium text-muted-foreground mb-2">建议摘要</div>
              <TextClamp text={String(sim.suggestion.summary)} collapsedChars={320} />
            </div>
          ) : null}

          {Array.isArray(sim?.suggestion?.actions) && sim!.suggestion.actions.length ? (
            <div className="rounded-md border bg-background p-2">
              <div className="text-xs font-medium text-muted-foreground mb-2">行动清单（节选）</div>
              <div className="space-y-2 max-h-80 overflow-auto">
                {sim!.suggestion.actions.slice(0, 10).map((a, i) => (
                  <div key={i} className="rounded-md border bg-muted/10 p-2">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="text-sm font-medium break-words">{a.action}</div>
                      <div className="flex flex-wrap gap-1">
                        <Badge variant={a.priority === 'urgent' ? 'destructive' : a.priority === 'high' ? 'default' : 'secondary'}>
                          {zhPriority(a.priority)}
                        </Badge>
                        <Badge variant="outline">{zhCategory(a.category)}</Badge>
                      </div>
                    </div>
                    <div className="pt-1 text-xs text-muted-foreground flex flex-wrap gap-2">
                      {a.timeline ? <span>时间：{a.timeline}</span> : null}
                      {a.responsible ? <span>责任方：{a.responsible}</span> : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">暂无行动清单</div>
          )}

          {/* Footer actions（左下角固定） */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={async () => {
                const ok = await copyToClipboard(md);
                if (!ok) alert('复制失败：当前环境不支持剪贴板');
              }}
              aria-label="复制 Markdown"
            >
              复制 Markdown
            </Button>
            <JsonDialogButton
              title="舆情预演阶段 JSON"
              description="用于调试/留存，不影响正常阅读。"
              jsonText={jsonText}
              fileName={`truthcast_simulation_${meta.stage}.json`}
              triggerLabel="显示 JSON"
            />
          </div>
              </>
            );
          })()}
        </div>
      ) : null}
    </ResultCardShell>
  );
}

