'use client';

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DetectResponse, ReportResponse, SimulateResponse, ContentDraft } from '@/types';

export function ContextPanel({
  detectData,
  report,
  simulation,
  content,
}: {
  detectData: DetectResponse | null;
  report: ReportResponse | null;
  simulation: SimulateResponse | null;
  content: ContentDraft | null;
}) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">快捷跳转</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild variant="secondary" size="sm">
            <Link href="/result">检测结果</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <Link href="/simulation">舆情预演</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <Link href="/content">应对内容</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <Link href="/history">历史记录</Link>
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">当前上下文摘要</CardTitle>
        </CardHeader>
        <CardContent className="text-sm space-y-2">
          <div>
            <span className="text-muted-foreground">风险快照：</span>
            {detectData ? `${detectData.label}（${detectData.score}）` : '未生成'}
          </div>
          <div>
            <span className="text-muted-foreground">综合报告：</span>
            {report ? `${report.risk_label}（${report.risk_score}）` : '未生成'}
          </div>
          <div>
            <span className="text-muted-foreground">舆情预演：</span>
            {simulation ? `叙事分支 ${simulation.narratives?.length ?? 0} 条` : '未生成'}
          </div>
          <div>
            <span className="text-muted-foreground">应对内容：</span>
            {content ? '已生成草稿' : '未生成'}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

