'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { zhRiskLabel, zhText } from '@/lib/i18n';
import type { DetectResponse } from '@/types';

interface RiskOverviewProps {
  data: DetectResponse | null;
  isLoading: boolean;
}

export function RiskOverview({ data, isLoading }: RiskOverviewProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-24" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>风险概览</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">暂无风险快照结果。</p>
        </CardContent>
      </Card>
    );
  }

  const labelColors: Record<string, string> = {
    credible: 'bg-green-500',
    suspicious: 'bg-yellow-500',
    high_risk: 'bg-orange-500',
    needs_context: 'bg-blue-500',
    likely_misinformation: 'bg-red-500',
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>风险概览</CardTitle>
        <CardDescription>快速风险快照评估</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-4">
          <Badge className={labelColors[data.label] ?? 'bg-gray-500'}>
            {zhRiskLabel(data.label)}
          </Badge>
          <span className="text-sm">分数: {data.score}</span>
          <span className="text-sm">置信度: {data.confidence}</span>
        </div>
        <ul className="space-y-1 text-sm">
          {data.reasons.map((reason, index) => (
            <li key={index} className="flex items-start gap-2">
              <span className="text-muted-foreground">•</span>
              {zhText(reason)}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
