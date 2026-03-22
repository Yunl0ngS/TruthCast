'use client';

import { BellOff, BellRing, Siren, ShieldAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useMonitorAlerts, monitorActions } from '@/hooks/use-monitor';
import { toast } from '@/lib/toast';
import type { MonitorAlert } from '@/types';

function alertStatusVariant(status: string): 'default' | 'outline' | 'riskHigh' | 'riskCritical' {
  if (status === 'acknowledged') return 'outline';
  if (status === 'sent') return 'riskHigh';
  return 'riskCritical';
}

function notifyResultSummary(alert: MonitorAlert) {
  const success = alert.notify_results.filter((item) => Boolean(item.success)).length;
  return `${success}/${alert.notify_results.length || alert.notify_channels.length} 成功`;
}

export function AlertsList() {
  const { items, isLoading, refresh } = useMonitorAlerts();

  const handleAcknowledge = async (id: string) => {
    try {
      await monitorActions.acknowledgeAlert(id);
      await refresh();
      toast.success('预警已确认');
    } catch (error) {
      console.error('Acknowledge alert failed:', error);
      toast.error('确认失败');
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-white/70 bg-[linear-gradient(150deg,rgba(255,255,255,0.82),rgba(241,247,251,0.82))]">
          <CardHeader className="gap-3">
            <div className="flex items-center justify-between">
              <Badge variant="riskCritical">
                <Siren className="h-3 w-3" />
                全部预警
              </Badge>
              <ShieldAlert className="h-5 w-5 text-[color:var(--muted-strong)]" />
            </div>
            <CardTitle>预警总量</CardTitle>
          </CardHeader>
          <CardContent className="text-4xl font-semibold tracking-[-0.04em] text-foreground">
            {items.length}
          </CardContent>
        </Card>
        <Card className="border-white/70 bg-[linear-gradient(150deg,rgba(255,255,255,0.82),rgba(245,249,252,0.82))]">
          <CardHeader className="gap-3">
            <div className="flex items-center justify-between">
              <Badge variant="riskHigh">
                <BellRing className="h-3 w-3" />
                待处理
              </Badge>
              <ShieldAlert className="h-5 w-5 text-[color:var(--muted-strong)]" />
            </div>
            <CardTitle>未确认</CardTitle>
          </CardHeader>
          <CardContent className="text-4xl font-semibold tracking-[-0.04em] text-foreground">
            {items.filter((item) => item.status !== 'acknowledged').length}
          </CardContent>
        </Card>
        <Card className="border-white/70 bg-[linear-gradient(150deg,rgba(255,255,255,0.82),rgba(247,250,252,0.82))]">
          <CardHeader className="gap-3">
            <div className="flex items-center justify-between">
              <Badge variant="outline" className="border-emerald-200 bg-emerald-500/10 text-emerald-700">
                <BellOff className="h-3 w-3" />
                已消化
              </Badge>
              <ShieldAlert className="h-5 w-5 text-[color:var(--muted-strong)]" />
            </div>
            <CardTitle>已确认</CardTitle>
          </CardHeader>
          <CardContent className="text-4xl font-semibold tracking-[-0.04em] text-foreground">
            {items.filter((item) => item.status === 'acknowledged').length}
          </CardContent>
        </Card>
      </div>

      <Card className="border-white/70 bg-[linear-gradient(155deg,rgba(255,255,255,0.82),rgba(243,248,251,0.82))]">
        <CardHeader className="border-b border-border/70">
          <CardTitle>预警清单</CardTitle>
          <CardDescription>这里聚焦所有已触发的风险信号、触发原因和通知结果。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 pt-6">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-36 w-full rounded-[1.3rem]" />)
          ) : items.length === 0 ? (
            <div className="rounded-[1.25rem] border border-dashed border-border/70 bg-white/60 px-4 py-10 text-center text-sm text-muted-foreground">
              还没有触发过预警。等热榜扫描和订阅命中后，这里会开始积累信号。
            </div>
          ) : (
            items.map((alert) => (
              <div key={alert.id} className="rounded-[1.35rem] border border-white/70 bg-white/78 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={alertStatusVariant(alert.status)}>{alert.status}</Badge>
                      <Badge variant="riskCritical">风险 {alert.risk_score}</Badge>
                      <Badge variant="outline" className="border-white/70 bg-[color:var(--panel-soft)]">
                        {alert.hot_item_platform} · #{alert.hot_item_rank}
                      </Badge>
                    </div>
                    <div className="text-base font-medium leading-7 text-foreground">{alert.hot_item_title}</div>
                    <div className="text-sm text-muted-foreground">{alert.trigger_reason}</div>
                    <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                      <span>关键词：{alert.matched_keywords.join('、') || '无'}</span>
                      <span>渠道：{alert.notify_channels.join('、') || '无'}</span>
                      <span>发送结果：{notifyResultSummary(alert)}</span>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <a
                      href={alert.hot_item_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center rounded-full border border-white/70 bg-white/84 px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent"
                    >
                      查看来源
                    </a>
                    {alert.status !== 'acknowledged' ? (
                      <Button type="button" size="sm" onClick={() => handleAcknowledge(alert.id)}>
                        确认预警
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
