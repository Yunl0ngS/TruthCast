'use client';

import { PageHero, PageSection } from '@/components/layout';
import { HistoryList } from '@/components/features';
import { History } from 'lucide-react';

export default function HistoryPage() {
  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="History"
        title="历史记录与任务回放"
        // description="这里保留任务浏览和回放能力，但整体风格收束到同一套工作台骨架里，不再像单独的一页列表工具。"
        meta={
          <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
            历史浏览 / 回放
          </div>
        }
        actions={
          <div className="rounded-[1.25rem] border border-white/60 bg-white/70 px-4 py-3 shadow-[0_14px_28px_rgba(26,54,78,0.08)]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--muted-strong)]">
              页面角色
            </div>
            <div className="mt-1 text-sm font-medium text-foreground">次级工作台页面</div>
          </div>
        }
      />

      <PageSection
        title="任务列表与详情"
        description="左侧浏览记录，右侧查看详情并跳转回分析结果或舆情预演。"
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <History className="h-3.5 w-3.5 text-primary" />
            历史任务管理
          </div>
        }
      >
        <HistoryList />
      </PageSection>
    </div>
  );
}
