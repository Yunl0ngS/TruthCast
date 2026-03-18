'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ShieldAlert } from 'lucide-react';
import { zhRiskLabel, zhText } from '@/lib/i18n';
import type { DetectResponse } from '@/types';

interface RiskOverviewProps {
  data: DetectResponse | null;
  isLoading: boolean;
}

// 精细化骨架屏
function RiskOverviewSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-4 w-32 mt-1" />
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 标签行 */}
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-20 rounded-full" />
          <Skeleton className="h-4 w-14" />
          <Skeleton className="h-4 w-16" />
        </div>
        {/* 理由列表 */}
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-4/6" />
        </div>
      </CardContent>
    </Card>
  );
}

// 空状态
function RiskOverviewEmpty() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>风险概览</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center gap-2 py-6 text-muted-foreground">
          <ShieldAlert className="h-8 w-8 opacity-30" />
          <p className="text-sm">等待风险快照结果…</p>
          <p className="text-xs opacity-60">提交文本后系统将自动评估</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function RiskOverview({ data, isLoading }: RiskOverviewProps) {
  if (isLoading) {
    return <RiskOverviewSkeleton />;
  }

  if (!data) {
    return <RiskOverviewEmpty />;
  }

  const reasons = Array.isArray(data.reasons) ? data.reasons : [];

  const labelVariants: Record<string, "riskLow" | "riskMedium" | "riskHigh" | "riskCritical"> = {
    credible: "riskLow",
    suspicious: "riskMedium",
    high_risk: "riskHigh",
    needs_context: "riskLow",
    likely_misinformation: "riskCritical",
  };

  const scoreBarColor: Record<string, string> = {
    credible: 'bg-[var(--risk-low)]',
    suspicious: 'bg-[var(--risk-medium)]',
    high_risk: 'bg-[var(--risk-high)]',
    needs_context: 'bg-[var(--risk-low)]',
    likely_misinformation: 'bg-[var(--risk-critical)]',
  };

  return (
    <Card className="h-full border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.80),rgba(241,247,251,0.78))] transition-opacity duration-500 animate-in fade-in">
      <CardHeader>
        <CardTitle>风险概览</CardTitle>
        <CardDescription>快速风险快照评估</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={labelVariants[data.label] ?? "default"}>
            {zhRiskLabel(data.label)}
          </Badge>
          <div className="rounded-full border border-white/65 bg-white/76 px-3 py-1 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_8px_20px_rgba(26,54,78,0.06)]">
            风险分数 {data.score}
          </div>
          <div className="rounded-full border border-white/65 bg-white/76 px-3 py-1 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_8px_20px_rgba(26,54,78,0.06)]">
            置信度 {(data.confidence * 100).toFixed(0)}%
          </div>
        </div>

        {/* 风险评分进度条 */}
        <div className="space-y-2 rounded-[1.25rem] border border-white/65 bg-white/74 p-3 shadow-[0_10px_24px_rgba(26,54,78,0.05)]">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>安全</span>
            <span>高危</span>
          </div>
          <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${scoreBarColor[data.label] ?? 'bg-gray-400'}`}
              style={{ width: `${Math.min(100, Math.max(0, data.score))}%` }}
            />
          </div>
        </div>

        <ul className="space-y-2 text-sm">
          {reasons.length > 0 ? (
            reasons.map((reason, index) => (
              <li key={index} className="flex items-start gap-2 rounded-[1.15rem] border border-white/60 bg-white/74 px-3 py-2.5 shadow-[0_8px_18px_rgba(26,54,78,0.04)]">
                <span className="mt-0.5 text-muted-foreground">•</span>
                <span>{zhText(reason)}</span>
              </li>
            ))
          ) : (
            <li className="text-muted-foreground">暂无具体原因（可能是历史恢复数据不包含 reasons 字段）</li>
          )}
        </ul>
      </CardContent>
    </Card>
  );
}
