'use client';

import { useState, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ExternalLink } from 'lucide-react';
import { zhStance, zhSourceType, zhDomain, zhText, zhClaimId } from '@/lib/i18n';
import { cn } from '@/lib/utils';
import type { EvidenceItem, ReportResponse, ClaimItem } from '@/types';

interface EvidenceChainProps {
  evidences: EvidenceItem[];
  rawEvidences: EvidenceItem[];
  claims: ClaimItem[];
  report: ReportResponse | null;
  isLoading: boolean;
}

type ViewMode = 'summary' | 'raw';

const stanceColors: Record<string, string> = {
  support: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  refute: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  insufficient: 'bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200',
  doubt: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  mixed: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  neutral: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
};

export function EvidenceChain({ evidences, rawEvidences, claims, report, isLoading }: EvidenceChainProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('summary');

  const claimTextMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of claims) {
      map.set(item.claim_id, item.claim_text);
    }
    return map;
  }, [claims]);

  const groupedEvidences = useMemo(() => {
    // 检索证据模式：显示原始检索结果
    if (viewMode === 'raw') {
      const grouped = new Map<string, EvidenceItem[]>();
      for (const item of rawEvidences) {
        const key = item.claim_id || 'unknown';
        const rows = grouped.get(key) ?? [];
        rows.push(item);
        grouped.set(key, rows);
      }
      return Array.from(grouped.entries()).map(([claimId, items]) => ({
        claimId,
        claimText: claimTextMap.get(claimId) ?? '未关联到具体主张',
        items,
        mode: 'raw' as const,
      }));
    }

    // 聚合证据模式：优先显示报告中的证据，否则显示已对齐的 evidences
    if (report) {
      return report.claim_reports.map((row) => {
        const summarized = row.evidences.filter((ev) => ev.source_type === 'web_summary');
        const rawItems = evidences.filter((ev) => ev.claim_id === row.claim.claim_id);
        const useSummary = summarized.length > 0;
        const picked = useSummary ? summarized : rawItems;

        if (summarized.length === 0 && rawItems.length > 0) {
          console.log(`[EvidenceChain] ${row.claim.claim_id} 无聚合证据，回退检索证据。rawItems source_type:`, rawItems.map(e => e.source_type));
        }

        return {
          claimId: row.claim.claim_id,
          claimText: row.claim.claim_text,
          items: picked,
          mode: useSummary ? 'summary' : 'summary_fallback',
        } as const;
      });
    }

    // 没有报告但有已对齐证据：按主张分组显示，使用 'summary' 模式显示实际立场
    const grouped = new Map<string, EvidenceItem[]>();
    for (const item of evidences) {
      const key = item.claim_id || 'unknown';
      const rows = grouped.get(key) ?? [];
      rows.push(item);
      grouped.set(key, rows);
    }
    return Array.from(grouped.entries()).map(([claimId, items]) => ({
      claimId,
      claimText: claimTextMap.get(claimId) ?? '未关联到具体主张',
      items,
      mode: 'summary' as const,
    }));
  }, [evidences, rawEvidences, claims, report, viewMode, claimTextMap]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-24" />
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  const displayEvidences = viewMode === 'raw' ? rawEvidences : evidences;
  if (displayEvidences.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>证据链</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">暂无证据结果。</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>证据链</CardTitle>
            <CardDescription>基于主张的证据检索与对齐结果</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={viewMode === 'summary' ? 'default' : 'outline'}
              onClick={() => setViewMode('summary')}
            >
              聚合证据
            </Button>
            <Button
              size="sm"
              variant={viewMode === 'raw' ? 'default' : 'outline'}
              onClick={() => setViewMode('raw')}
            >
              检索证据
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {groupedEvidences.map((group) => (
          <div key={group.claimId} className="space-y-3">
            <div className="flex items-start gap-2">
              <Badge variant="secondary">{zhClaimId(group.claimId)}</Badge>
              <p className="text-sm font-medium">{group.claimText}</p>
            </div>

            {group.mode === 'summary' && (
              <p className="text-xs text-muted-foreground">当前展示聚合证据（已对齐）</p>
            )}
            {group.mode === 'summary_fallback' && (
              <p className="text-xs text-muted-foreground">该主张暂无聚合证据，已回退对齐后证据</p>
            )}
            {group.mode === 'raw' && (
              <p className="text-xs text-muted-foreground">当前展示检索证据（标签为候选状态，不代表最终对齐结论）</p>
            )}

            <div className="grid gap-3">
              {group.items.map((item) => (
                <div
                  key={`${group.claimId}-${item.evidence_id}-${item.url}`}
                  className="border rounded-lg p-3 space-y-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge className={cn('text-xs', stanceColors[item.stance] ?? '')}>
                          {group.mode === 'raw' || item.alignment_confidence === undefined
                            ? '待对齐候选'
                            : zhStance(item.stance)}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {zhSourceType(item.source_type)}
                        </Badge>
                        {item.is_authoritative && (
                          <Badge variant="outline" className="text-xs bg-amber-50">
                            权威来源
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm font-medium">
                        {item.source_type === 'web_summary' && item.summary
                          ? zhText(item.summary)
                          : zhText(item.title)}
                      </p>
                    </div>
                    {item.source_type !== 'web_summary' && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    )}
                  </div>

                  <div className="text-xs text-muted-foreground space-y-1">
                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                      <span>来源: {item.source}</span>
                      <span>权重: {item.source_weight.toFixed(2)}</span>
                      {item.domain && <span>领域: {zhDomain(item.domain)}</span>}
                    </div>
                    {item.summary && item.source_type !== 'web_summary' && (
                      <p className="mt-1">摘要: {zhText(item.summary)}</p>
                    )}
                    {item.alignment_confidence !== undefined && item.alignment_confidence !== null && (
                      <p>对齐置信度: {item.alignment_confidence.toFixed(2)}</p>
                    )}
                    {item.alignment_rationale && (
                      <p>对齐理由: {zhText(item.alignment_rationale)}</p>
                    )}
                    {item.source_type === 'web_summary' && item.source_urls && item.source_urls.length > 0 && (
                      <div className="mt-2">
                        <span className="text-muted-foreground">来源链接 ({item.source_urls.length}条): </span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {item.source_urls.map((linkUrl, linkIdx) => (
                            <a
                              key={linkIdx}
                              href={linkUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-0.5 text-primary hover:underline"
                            >
                              <ExternalLink className="h-3 w-3" />
                              <span>{linkIdx + 1}</span>
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
