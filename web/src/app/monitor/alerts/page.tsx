'use client';

import { BellRing, ShieldAlert } from 'lucide-react';
import { AlertsList } from '@/components/features';
import { PageHero, PageSection } from '@/components/layout';

export default function MonitorAlertsPage() {
  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="Alerts"
        title="预警清单与处置节奏"
        meta={
          <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
            告警核对 / 处置确认
          </div>
        }
      />

      <PageSection
        title="已触发预警"
        description="把所有风险告警集中到一处，先看是否需要确认，再判断是否要进入后续核查和应对流程。"
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <BellRing className="h-3.5 w-3.5 text-primary" />
            预警队列
          </div>
        }
      >
        <AlertsList />
      </PageSection>

      <PageSection
        title="处置建议"
        muted
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/72 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)]">
            <ShieldAlert className="h-3.5 w-3.5 text-primary" />
            行动顺序
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">先确认</div>
            <p className="mt-2 leading-6">确认预警代表已接收，不代表问题已解决，适合团队协作流转。</p>
          </div>
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">再核查</div>
            <p className="mt-2 leading-6">高风险预警建议跳回检测链路，进一步看证据和报告是否支撑行动。</p>
          </div>
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">最后编排</div>
            <p className="mt-2 leading-6">当某类预警过密时，应该回到订阅页重新调整阈值和平台范围。</p>
          </div>
        </div>
      </PageSection>
    </div>
  );
}
