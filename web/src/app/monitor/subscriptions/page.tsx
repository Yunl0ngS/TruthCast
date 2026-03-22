'use client';

import { BellRing, Filter } from 'lucide-react';
import { SubscriptionManager } from '@/components/features';
import { PageHero, PageSection } from '@/components/layout';

export default function MonitorSubscriptionsPage() {
  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="Subscriptions"
        title="订阅编排与监测规则"
        meta={
          <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
            关键词 / 平台 / 触发策略
          </div>
        }
      />

      <PageSection
        title="订阅创建与启停"
        description="在这里设定你的监测半径，决定哪些关键词、哪些平台和哪些风险阈值会触发行动。"
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <BellRing className="h-3.5 w-3.5 text-primary" />
            规则工作台
          </div>
        }
      >
        <SubscriptionManager />
      </PageSection>

      <PageSection
        title="订阅设计建议"
        muted
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/72 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)]">
            <Filter className="h-3.5 w-3.5 text-primary" />
            调参建议
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">高噪音话题</div>
            <p className="mt-2 leading-6">建议配置排除词，例如“辟谣”“通报”“澄清”，减少误报。</p>
          </div>
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">高价值线索</div>
            <p className="mt-2 leading-6">如果你更在意先知先觉，使用“命中即触发”而不是高阈值触发。</p>
          </div>
          <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 text-sm text-muted-foreground">
            <div className="text-sm font-medium text-foreground">团队协作</div>
            <p className="mt-2 leading-6">同一主题可以拆成不同平台订阅，分配给不同通知渠道和责任人。</p>
          </div>
        </div>
      </PageSection>
    </div>
  );
}
