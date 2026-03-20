'use client';

import { useMemo, useState } from 'react';
import { Activity, BellRing, Gauge, RadioTower, RefreshCcw, ShieldAlert, TimerReset } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useMonitorHotItems, useMonitorStatus, monitorActions } from '@/hooks/use-monitor';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';

function statusTone(running: boolean) {
  return running ? 'bg-emerald-500/12 text-emerald-700 border-emerald-200/80' : 'bg-slate-500/12 text-slate-700 border-slate-200/80';
}

function riskVariant(riskScore?: number | null): 'riskLow' | 'riskMedium' | 'riskHigh' | 'riskCritical' {
  if ((riskScore ?? 0) >= 85) return 'riskCritical';
  if ((riskScore ?? 0) >= 70) return 'riskHigh';
  if ((riskScore ?? 0) >= 50) return 'riskMedium';
  return 'riskLow';
}

function trendLabel(trend: string) {
  const map: Record<string, string> = {
    new: '新上榜',
    rising: '升温中',
    stable: '稳定',
    falling: '降温中',
  };
  return map[trend] ?? trend;
}

export function MonitorDashboard() {
  const [platformFilter, setPlatformFilter] = useState<string>('all');
  const { status, isLoading: statusLoading, refresh: refreshStatus } = useMonitorStatus();
  const { items, isLoading: hotLoading, refresh: refreshHotItems } = useMonitorHotItems(
    18,
    platformFilter === 'all' ? undefined : platformFilter
  );

  const platforms = useMemo(() => {
    const set = new Set<string>();
    items.forEach((item) => set.add(item.platform));
    Object.keys(status?.platform_intervals ?? {}).forEach((platform) => set.add(platform));
    return ['all', ...Array.from(set)];
  }, [items, status?.platform_intervals]);

  const highRiskCount = items.filter((item) => (item.risk_score ?? 0) >= 70).length;

  const handleScan = async () => {
    const toastId = toast.loading('正在执行热榜扫描', '将拉取热榜、检测增量并触发预警判断');
    try {
      await monitorActions.triggerScan(platformFilter === 'all' ? undefined : [platformFilter]);
      await Promise.all([refreshStatus(), refreshHotItems()]);
      toast.success('扫描完成', platformFilter === 'all' ? '已更新全平台监测状态' : `已更新 ${platformFilter} 平台`);
    } catch (error) {
      console.error('Monitor scan failed:', error);
      toast.error('扫描失败', '请检查后端监测服务与热榜数据源状态');
    } finally {
      toast.dismiss(toastId);
    }
  };

  return (
    <div className="space-y-4 md:space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {statusLoading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-40 w-full rounded-[1.6rem]" />)
        ) : (
          <>
            <Card className="border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.84),rgba(240,247,251,0.82))]">
              <CardHeader className="gap-3">
                <div className="flex items-center justify-between">
                  <Badge className={cn('border', statusTone(Boolean(status?.running)))} variant="outline">
                    <RadioTower className="h-3 w-3" />
                    {status?.running ? '调度运行中' : '调度未启用'}
                  </Badge>
                  <Activity className="h-5 w-5 text-[color:var(--muted-strong)]" />
                </div>
                <CardTitle>监测调度</CardTitle>
                <CardDescription>查看当前调度器是否启用，以及自适应频率是否生效。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <div className="flex items-center justify-between rounded-2xl bg-white/76 px-3 py-2">
                  <span>默认周期</span>
                  <span className="font-medium text-foreground">{status?.default_interval_minutes ?? '--'} 分钟</span>
                </div>
                <div className="flex items-center justify-between rounded-2xl bg-white/76 px-3 py-2">
                  <span>当前生效</span>
                  <span className="font-medium text-foreground">{status?.effective_interval_minutes ?? '--'} 分钟</span>
                </div>
              </CardContent>
            </Card>

            <Card className="border-white/70 bg-[linear-gradient(165deg,rgba(255,255,255,0.82),rgba(245,249,252,0.84))]">
              <CardHeader className="gap-3">
                <div className="flex items-center justify-between">
                  <Badge variant="riskHigh">
                    <BellRing className="h-3 w-3" />
                    风险候选
                  </Badge>
                  <ShieldAlert className="h-5 w-5 text-[color:var(--muted-strong)]" />
                </div>
                <CardTitle>热点风险密度</CardTitle>
                <CardDescription>当前热榜中达到高风险阈值的热点数量。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-4xl font-semibold tracking-[-0.04em] text-foreground">{highRiskCount}</div>
                <p className="mt-3 text-sm text-muted-foreground">总热榜样本 {items.length} 条，适合判断当前告警压力。</p>
              </CardContent>
            </Card>

            <Card className="border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.80),rgba(247,250,252,0.84))]">
              <CardHeader className="gap-3">
                <div className="flex items-center justify-between">
                  <Badge variant="outline" className="border-amber-200 bg-amber-500/10 text-amber-700">
                    <Gauge className="h-3 w-3" />
                    失败观测
                  </Badge>
                  <TimerReset className="h-5 w-5 text-[color:var(--muted-strong)]" />
                </div>
                <CardTitle>扫描健康度</CardTitle>
                <CardDescription>失败次数、最近错误和平台级异常是判断监测稳定性的入口。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex items-center justify-between rounded-2xl bg-white/76 px-3 py-2">
                  <span className="text-muted-foreground">累计失败</span>
                  <span className="font-medium text-foreground">{status?.failure_count ?? 0}</span>
                </div>
                <div className="rounded-2xl bg-white/76 px-3 py-2 text-muted-foreground">
                  <div className="text-xs uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">最近错误</div>
                  <div className="mt-1 line-clamp-2 text-sm text-foreground">
                    {status?.last_error ? `${status.last_error.platform}: ${status.last_error.message}` : '暂无错误'}
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.82),rgba(243,248,251,0.84))]">
              <CardHeader className="gap-3">
                <div className="flex items-center justify-between">
                  <Badge variant="outline" className="border-sky-200 bg-sky-500/10 text-sky-700">
                    <Activity className="h-3 w-3" />
                    性能节奏
                  </Badge>
                  <RefreshCcw className="h-5 w-5 text-[color:var(--muted-strong)]" />
                </div>
                <CardTitle>扫描耗时</CardTitle>
                <CardDescription>看最近一次扫描耗时，确认监测链路是否变慢。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="text-4xl font-semibold tracking-[-0.04em] text-foreground">
                  {status?.last_scan_duration_ms ?? 0}
                  <span className="ml-1 text-base font-medium text-muted-foreground">ms</span>
                </div>
                <div className="text-muted-foreground">
                  最近扫描：{status?.last_scan_at ? new Date(status.last_scan_at).toLocaleString('zh-CN') : '暂无'}
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="border-white/70 bg-[linear-gradient(155deg,rgba(255,255,255,0.82),rgba(244,249,252,0.82))]">
          <CardHeader className="border-b border-border/70">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div className="space-y-2">
                <CardTitle>热榜雷达</CardTitle>
                <CardDescription>扫描后优先看这里，判断哪些平台在升温、哪些热点需要补充评估。</CardDescription>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {platforms.map((platform) => (
                  <Button
                    key={platform}
                    type="button"
                    size="sm"
                    variant={platformFilter === platform ? 'default' : 'outline'}
                    onClick={() => setPlatformFilter(platform)}
                    className="rounded-full"
                  >
                    {platform === 'all' ? '全部平台' : platform}
                  </Button>
                ))}
                <Button type="button" size="sm" onClick={handleScan} className="rounded-full">
                  <RefreshCcw className="mr-2 h-4 w-4" />
                  立即扫描
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {hotLoading ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-28 w-full rounded-[1.3rem]" />)
            ) : items.length === 0 ? (
              <div className="rounded-[1.3rem] border border-dashed border-border/70 bg-white/60 px-4 py-10 text-center text-sm text-muted-foreground">
                还没有热榜数据。先执行一次扫描，把监测信号拉进工作台。
              </div>
            ) : (
              items.map((item) => (
                <div
                  key={item.id}
                  className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 shadow-[0_14px_30px_rgba(26,54,78,0.06)]"
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="border-white/70 bg-[color:var(--panel-soft)] text-[color:var(--muted-strong)]">
                          {item.platform}
                        </Badge>
                        <Badge variant={riskVariant(item.risk_score)}>
                          风险 {item.risk_score ?? 0}
                        </Badge>
                        <Badge variant="outline" className="border-sky-200 bg-sky-500/10 text-sky-700">
                          {trendLabel(item.trend)}
                        </Badge>
                      </div>
                      <div className="text-base font-medium leading-7 text-foreground">{item.title}</div>
                      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                        <span>热度 {item.hot_value}</span>
                        <span>排名 #{item.rank}</span>
                        <span>更新时间 {new Date(item.last_seen_at).toLocaleString('zh-CN')}</span>
                      </div>
                    </div>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center rounded-full border border-white/70 bg-white/84 px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent"
                    >
                      查看来源
                    </a>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-white/70 bg-[linear-gradient(155deg,rgba(255,255,255,0.84),rgba(240,247,251,0.82))]">
          <CardHeader className="border-b border-border/70">
            <CardTitle>平台扫描脉搏</CardTitle>
            <CardDescription>这里直观看各平台当前间隔、最近吞吐和异常分布。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {statusLoading ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-24 w-full rounded-[1.2rem]" />)
            ) : Object.keys(status?.last_scan_summary ?? {}).length === 0 ? (
              <div className="rounded-[1.25rem] border border-dashed border-border/70 bg-white/60 px-4 py-10 text-center text-sm text-muted-foreground">
                暂无平台扫描摘要。
              </div>
            ) : (
              Object.entries(status?.last_scan_summary ?? {}).map(([platform, summary]) => (
                <div key={platform} className="rounded-[1.25rem] border border-white/70 bg-white/78 p-4">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium text-foreground">{platform}</div>
                    <Badge variant="outline" className="border-white/70 bg-[color:var(--panel-soft)]">
                      {status?.platform_intervals?.[platform] ?? status?.default_interval_minutes ?? '--'} 分钟
                    </Badge>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <div className="rounded-xl bg-[color:var(--panel-soft)]/70 px-3 py-2">拉取 {summary.fetched}</div>
                    <div className="rounded-xl bg-[color:var(--panel-soft)]/70 px-3 py-2">候选 {summary.alert_candidates}</div>
                    <div className="rounded-xl bg-[color:var(--panel-soft)]/70 px-3 py-2">失败 {status?.platform_failures?.[platform] ?? 0}</div>
                    <div className="rounded-xl bg-[color:var(--panel-soft)]/70 px-3 py-2">
                      耗时 {status?.platform_durations_ms?.[platform] ?? 0}ms
                    </div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
