'use client';

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DetectResponse, ReportResponse, SimulateResponse, ContentDraft } from '@/types';
import type { Phase, PhaseState } from '@/types';
import { zhRiskLabel } from '@/lib/i18n';

const PHASE_LABEL: Record<Phase, string> = {
  detect: '风险快照',
  claims: '主张抽取',
  evidence: '证据检索',
  report: '综合报告',
  simulation: '舆情预演',
  content: '应对内容',
};

function phaseBadgeVariant(state: PhaseState[Phase]): 'default' | 'secondary' | 'outline' | 'destructive' {
  switch (state) {
    case 'done':
      return 'default';
    case 'running':
      return 'secondary';
    case 'failed':
      return 'destructive';
    default:
      return 'outline';
  }
}

export function ContextPanel({
  taskId,
  recordId,
  phases,
  detectData,
  report,
  simulation,
  content,
  onClearContext,
  onCommand,
}: {
  taskId?: string | null;
  recordId: string | null;
  phases: PhaseState;
  detectData: DetectResponse | null;
  report: ReportResponse | null;
  simulation: SimulateResponse | null;
  content: ContentDraft | null;
  onClearContext?: () => void;
  onCommand?: (command: string) => void;
}) {
  const phaseOrder: Phase[] = ['detect', 'claims', 'evidence', 'report', 'simulation', 'content'];
  const nextRunnablePhase = (() => {
    for (const p of phaseOrder) {
      if (phases[p] === 'failed' || phases[p] === 'canceled') return p;
      if (phases[p] === 'idle') {
        // 仅当上游全部 done 时，才认为是“可继续”的下一阶段
        const idx = phaseOrder.indexOf(p);
        const upstreamOk = phaseOrder.slice(0, idx).every((u) => phases[u] === 'done');
        if (upstreamOk) return p;
      }
    }
    return null;
  })();

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
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <span className="text-muted-foreground">任务ID：</span>
              <span className="font-mono text-xs break-all">{taskId ?? '未绑定'}</span>
            </div>
            <div className="shrink-0 flex gap-2">
              {nextRunnablePhase && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onCommand?.(`/retry ${nextRunnablePhase}`)}
                  disabled={!onCommand}
                >
                  继续：{PHASE_LABEL[nextRunnablePhase]}
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={() => onCommand?.('/retry_failed')}
                disabled={!onCommand}
              >
                重试失败
              </Button>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <span className="text-muted-foreground">绑定记录：</span>
              <span className="font-mono text-xs break-all">{recordId ?? '未绑定'}</span>
            </div>
            <div className="shrink-0 flex gap-2">
              <Button size="sm" variant="outline" onClick={() => onCommand?.('/list')} disabled={!onCommand}>
                /list
              </Button>
              <Button size="sm" variant="destructive" onClick={onClearContext} disabled={!onClearContext}>
                清空
              </Button>
            </div>
          </div>

          <div>
            <span className="text-muted-foreground">风险快照：</span>
            {detectData ? `${zhRiskLabel(detectData.label)}（${detectData.score}）` : '未生成'}
          </div>
          <div>
            <span className="text-muted-foreground">综合报告：</span>
            {report ? `${zhRiskLabel(report.risk_label)}（${report.risk_score}）` : '未生成'}
          </div>
          <div>
            <span className="text-muted-foreground">舆情预演：</span>
            {simulation ? `叙事分支 ${simulation.narratives?.length ?? 0} 条` : '未生成'}
          </div>
          <div>
            <span className="text-muted-foreground">应对内容：</span>
            {content ? '已生成草稿' : '未生成'}
          </div>

          <div className="pt-1">
            <div className="text-muted-foreground mb-1">阶段状态：</div>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(PHASE_LABEL) as Phase[]).map((p) => (
                <Badge key={p} variant={phaseBadgeVariant(phases[p])}>
                  {PHASE_LABEL[p]}：{phases[p]}
                </Badge>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

