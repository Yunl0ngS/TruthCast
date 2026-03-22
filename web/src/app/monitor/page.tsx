'use client';

import { Activity, Radar } from 'lucide-react';
import { MonitorDashboard } from '@/components/features';
import { PageHero, PageSection } from '@/components/layout';

export default function MonitorPage() {
  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="Monitoring"
        title="实时监测台"
        meta={
          <>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              热榜追踪 / 入口分发
            </div>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              调度观测 / 结果跳转
            </div>
          </>
        }
        actions={
          <div className="rounded-[1.25rem] border border-white/60 bg-white/70 px-4 py-3 shadow-[0_14px_28px_rgba(26,54,78,0.08)]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--muted-strong)]">
              页面角色
            </div>
            <div className="mt-1 text-sm font-medium text-foreground">前哨雷达 / 工作流入口</div>
          </div>
        }
      />

      <PageSection
        title="热榜信号与调度健康度"
        description="把扫描、预警、平台脉搏和自动研判入口放在一个屏幕里，先看哪里有信号，再决定跳到哪一页深入处理。"
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <Radar className="h-3.5 w-3.5 text-primary" />
            信号塔视角
          </div>
        }
      >
        <MonitorDashboard />
      </PageSection>

      <PageSection
        title="工作方式"
        muted
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/72 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)]">
            <Activity className="h-3.5 w-3.5 text-primary" />
            扫描链路
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">1. 热榜拉取</div>
            <p className="mt-2 leading-6">聚合多平台热榜，识别新增、升温和消退信号。</p>
          </div>
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">2. 风险判断</div>
            <p className="mt-2 leading-6">对候选热点进行风险打分，并把满足条件的结果送入 TruthCast 检测链路。</p>
          </div>
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">3. 跳转处理</div>
            <p className="mt-2 leading-6">从监测台直接进入检测结果、舆情预演或应对内容页，继续人工判断和手动触发。</p>
          </div>
        </div>
      </PageSection>
    </div>
  );
}
