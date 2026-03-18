'use client';

import { PageHero, PageSection, ProgressTimeline } from '@/components/layout';
import { SimulationView, ExportButton } from '@/components/features';
import { ErrorBoundary } from '@/components/ui/error-boundary';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';
import { Radar } from 'lucide-react';

export default function SimulationPage() {
  const {
    text,
    detectData,
    claims,
    evidences,
    report,
    simulation,
    content,
    phases,
    retryPhase,
    interruptPipeline,
  } = usePipelineStore();

  const hasReport = report !== null;

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="Simulation"
        title="舆情预演与响应"
        // description="这一页优先回答两件事：接下来会怎么传播，以及现在该做什么。图表、引爆点和时间线都服务于这两个核心问题。"
        meta={
          <>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              {hasReport ? '已具备预演上下文' : '等待综合报告'}
            </div>
            {/* <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              纵向阅读
            </div> */}
          </>
        }
        actions={
          <>
            <div className="w-full min-w-0 lg:mr-82 lg:w-[500px] xl:mr-84 xl:w-[520px]">
              <ProgressTimeline
                phases={phases}
                onRetry={handleRetry}
                onAbort={interruptPipeline}
                showRetry={true}
                mobileMode="collapsible"
                rememberExpandedKey="timeline_simulation"
              />
            </div>
            {hasReport ? (
              <ExportButton
                data={{
                  inputText: text,
                  detectData,
                  claims,
                  evidences,
                  report,
                  simulation,
                  content: content ?? null,
                  exportedAt: new Date().toLocaleString('zh-CN'),
                }}
              />
            ) : null}
          </>
        }
      />

      <PageSection
        title="传播预测到应对建议"
        // description="恢复为从上到下的阅读顺序：传播预测、叙事分支、引爆点/时间线，最后再看应对建议。"
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <Radar className="h-3.5 w-3.5 text-primary" />
            纵向排布
          </div>
        }
      >
        <ErrorBoundary title="舆情预演加载失败">
          <SimulationView simulation={simulation} isLoading={phases.simulation === 'running'} />
        </ErrorBoundary>
      </PageSection>

      {/* <PageSection
        title="阅读方式"
        description="这一页现在默认按照“传播预测 -> 叙事分支 -> 引爆点/时间线 -> 应对建议”的顺序组织内容。"
        muted
      >
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-[1.2rem] border border-white/65 bg-white/76 p-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">
              第一步
            </div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">看情绪、立场和叙事分支，判断传播走势。</p>
          </div>
          <div className="rounded-[1.2rem] border border-white/65 bg-white/76 p-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">
              第二步
            </div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">看叙事分支，判断可能的舆论演化路径。</p>
          </div>
          <div className="rounded-[1.2rem] border border-white/65 bg-white/76 p-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">
              第三步
            </div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">看引爆点和时间线，再结合应对建议安排后续动作。</p>
          </div>
        </div>
      </PageSection> */}
    </div>
  );
}
