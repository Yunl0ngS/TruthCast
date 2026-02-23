'use client';

import Link from 'next/link';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { ChatMessage } from '@/stores/chat-store';
import {
  DetectResultCard,
  ClaimsResultCard,
  EvidenceResultCard,
  ReportResultCard,
  SimulationStageResultCard,
  PipelineProgressCard,
  type DetectCardMeta,
  type ClaimsCardMeta,
  type EvidenceCardMeta,
  type ReportCardMeta,
  type SimulationStageCardMeta,
  type PipelineProgressMeta,
} from '@/components/features/chat-workbench/pipeline-result-card';

type MetaBlock =
  | {
      kind: 'section';
      title: string;
      items: string[];
      collapsed?: boolean;
    }
  | {
      kind: 'links';
      title: string;
      links: Array<{ title: string; href: string; description?: string }>;
      collapsed?: boolean;
    }
  | {
      kind: 'comparison';
      title: string;
      records: Array<{
        record_id: string;
        risk_label?: string;
        risk_score?: number;
        scenario?: string;
      }>;
    }
  | {
      kind: 'evidence_stats';
      title: string;
      stance_distribution: Record<string, number>;
      unique_sources: number;
    }
  | {
      kind: 'claims_analysis';
      title: string;
      focus_index?: number;
      total_claims: number;
    };

function BlockCard({ block }: { block: MetaBlock }) {
  if (block.kind === 'section') {
    return (
      <details className="rounded-md border bg-muted/30 p-2" open={!block.collapsed}>
        <summary className="cursor-pointer text-xs font-medium text-muted-foreground select-none">
          {block.title}
        </summary>
        <div className="mt-2 text-xs space-y-1">
          {block.items.map((it, i) => (
            <div key={i} className="leading-relaxed">
              - {it}
            </div>
          ))}
        </div>
      </details>
    );
  }

  if (block.kind === 'links') {
    return (
      <details className="rounded-md border bg-muted/30 p-2" open={!block.collapsed}>
        <summary className="cursor-pointer text-xs font-medium text-muted-foreground select-none">
          {block.title}
        </summary>
        <div className="mt-2 text-xs space-y-1">
          {block.links.map((r) => (
            <div key={r.href}>
              <Link href={r.href} className="underline hover:text-primary" target="_blank" rel="noopener noreferrer">
                {r.title}
              </Link>
              {r.description ? <div className="text-muted-foreground">{r.description}</div> : null}
            </div>
          ))}
        </div>
      </details>
    );
  }

  if (block.kind === 'comparison') {
    return (
      <div className="rounded-md border bg-muted/30 p-2">
        <div className="text-xs font-medium text-muted-foreground mb-2">{block.title}</div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          {block.records.map((rec, idx) => (
            <div key={rec.record_id} className="rounded border bg-background p-2 space-y-1">
              <div className="font-medium truncate">记录 {idx + 1}</div>
              <div className="text-muted-foreground truncate">{rec.record_id}</div>
              <div className="flex items-center gap-1">
                <Badge variant={rec.risk_score && rec.risk_score >= 70 ? 'destructive' : rec.risk_score && rec.risk_score >= 40 ? 'default' : 'secondary'} className="text-[10px]">
                  {rec.risk_label || '未知'}
                </Badge>
                <span className="text-muted-foreground">{rec.risk_score ?? '-'}</span>
              </div>
              {rec.scenario && <div className="text-muted-foreground truncate">场景: {rec.scenario}</div>}
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (block.kind === 'evidence_stats') {
    const stanceLabels: Record<string, string> = {
      support: '支持',
      oppose: '反对',
      insufficient_evidence: '证据不足',
    };
    return (
      <div className="rounded-md border bg-muted/30 p-2">
        <div className="text-xs font-medium text-muted-foreground mb-2">{block.title}</div>
        <div className="flex items-center gap-3 text-xs">
          {Object.entries(block.stance_distribution).map(([stance, count]) => (
            <div key={stance} className="flex items-center gap-1">
              <Badge
                variant={stance === 'support' ? 'default' : stance === 'oppose' ? 'destructive' : 'secondary'}
                className="text-[10px]"
              >
                {stanceLabels[stance] || stance}
              </Badge>
              <span>{count}</span>
            </div>
          ))}
          <div className="text-muted-foreground">| 来源: {block.unique_sources}</div>
        </div>
      </div>
    );
  }

  if (block.kind === 'claims_analysis') {
    return (
      <div className="rounded-md border bg-muted/30 p-2">
        <div className="text-xs font-medium text-muted-foreground mb-2">{block.title}</div>
        <div className="text-xs text-muted-foreground">
          共 {block.total_claims} 条主张
          {block.focus_index !== undefined && ` · 聚焦第 ${block.focus_index + 1} 条`}
        </div>
      </div>
    );
  }

  return null;
}

export function MessageList({
  messages,
  onCommand,
}: {
  messages: ChatMessage[];
  onCommand?: (command: string) => void;
}) {
  return (
    <div className="space-y-3">
      {messages.map((m) => (
        <div
          key={m.id}
          className={cn(
            'rounded-lg border px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap',
            m.role === 'user' && 'bg-primary text-primary-foreground border-primary/30',
            m.role === 'assistant' && 'bg-background',
            m.role === 'system' && 'bg-muted'
          )}
        >
          <div className="text-xs opacity-70 mb-1">
            {m.role === 'user' ? '你' : m.role === 'assistant' ? '助手' : '系统'} ·{' '}
            <span
              suppressHydrationWarning
              title={m.created_at}
            >
              {new Intl.DateTimeFormat('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false,
                timeZone: 'Asia/Hong_Kong',
              }).format(new Date(m.created_at))}
            </span>
          </div>
          <div>{m.content}</div>

          {(m.meta as any)?.type === 'pipeline_progress' ? (
            <div className="mt-2">
              <PipelineProgressCard meta={(m.meta as any) as PipelineProgressMeta} />
            </div>
          ) : null}

          {(m.meta as any)?.type === 'detect' ? (
            <div className="mt-2">
              <DetectResultCard meta={(m.meta as any) as DetectCardMeta} />
            </div>
          ) : null}

          {(m.meta as any)?.type === 'claims' ? (
            <div className="mt-2">
              <ClaimsResultCard meta={(m.meta as any) as ClaimsCardMeta} />
            </div>
          ) : null}

          {(m.meta as any)?.type === 'evidence' ? (
            <div className="mt-2">
              <EvidenceResultCard meta={(m.meta as any) as EvidenceCardMeta} />
            </div>
          ) : null}

          {(m.meta as any)?.type === 'report' ? (
            <div className="mt-2">
              <ReportResultCard meta={(m.meta as any) as ReportCardMeta} />
            </div>
          ) : null}

          {(m.meta as any)?.type === 'simulation_stage' ? (
            <div className="mt-2">
              <SimulationStageResultCard meta={(m.meta as any) as SimulationStageCardMeta} />
            </div>
          ) : null}

          {Array.isArray((m.meta as any)?.blocks) && (m.meta as any).blocks.length > 0 && (
            <div className="mt-2 space-y-2">
              {((m.meta as any).blocks as MetaBlock[]).map((b, idx) => (
                <BlockCard key={`${b.kind}_${idx}`} block={b} />
              ))}
            </div>
          )}

          {m.references && m.references.length > 0 && (
            <div className="mt-2 rounded-md border bg-muted/40 p-2 space-y-1">
              <div className="text-xs font-medium text-muted-foreground">引用</div>
              {m.references.map((r) => (
                <div key={r.href} className="text-xs">
                  <Link href={r.href} className="underline">
                    {r.title}
                  </Link>
                  {r.description ? (
                    <div className="text-muted-foreground">{r.description}</div>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          {m.actions && m.actions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {m.actions.map((a, idx) => {
                if (a.type === 'link') {
                  return (
                    <Button key={`${a.href}_${idx}`} asChild size="sm" variant="secondary">
                      <Link href={a.href}>{a.label}</Link>
                    </Button>
                  );
                }
                return (
                  <Button
                    key={`${a.command}_${idx}`}
                    size="sm"
                    variant="outline"
                    onClick={() => onCommand?.(a.command)}
                    disabled={!onCommand}
                  >
                    {a.label}
                  </Button>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

