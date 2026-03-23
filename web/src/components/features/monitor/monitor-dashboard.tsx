'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Activity, Clock3, ExternalLink, Gauge, RadioTower, RefreshCcw, ShieldAlert, TimerReset } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useLatestMonitorWindow, useMonitorStatus, useMonitorWindowHistory, monitorActions } from '@/hooks/use-monitor';
import { toast } from '@/lib/toast';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { MonitorAnalysisResult, MonitorScanWindowDetail, MonitorWindowItem } from '@/types';
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

function analysisStageLabel(stage: string) {
  const map: Record<string, string> = {
    hot_item: '已入监测',
    crawl: '链接核查',
    risk_snapshot: '风险初判',
    report: '综合报告',
    simulation: '舆情预演',
    content: '公关响应',
    completed: '流程完成',
  };
  return map[stage] ?? stage;
}

function simulationTone(status: string) {
  if (status === 'done') return 'border-emerald-200 bg-emerald-500/10 text-emerald-700';
  if (status === 'skipped') return 'border-slate-200 bg-slate-500/10 text-slate-700';
  return 'border-amber-200 bg-amber-500/10 text-amber-700';
}

function analysisStatusLabel(status: string) {
  const map: Record<string, string> = {
    pending: '未检测',
    running: '检测中',
    done: '检测完成',
    failed: '检测失败',
  };
  return map[status] ?? status;
}

function analysisStatusTone(status: string) {
  if (status === 'done') return 'border-emerald-200 bg-emerald-500/10 text-emerald-700';
  if (status === 'running') return 'border-sky-200 bg-sky-500/10 text-sky-700';
  if (status === 'failed') return 'border-rose-200 bg-rose-500/10 text-rose-700';
  return 'border-slate-200 bg-slate-500/10 text-slate-700';
}

function formatWindowRange(start: string, end: string) {
  const startDate = new Date(start);
  const endDate = new Date(end);
  return `${startDate.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })} - ${endDate.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}`;
}

function formatGroupedWindowRange(start: Date, end: Date) {
  return `${start.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })} - ${end.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}`;
}

function filterWindowItems(detail: MonitorScanWindowDetail | null | undefined, platformFilter: string) {
  if (!detail) return [];
  if (platformFilter === 'all') return detail.items;
  return detail.items.filter((item) => item.platform === platformFilter);
}

function collectPlatforms(enabledPlatforms: Array<{ key: string; display_name: string }> | undefined) {
  return [
    { key: 'all', label: '全部平台' },
    ...((enabledPlatforms ?? []).map((item) => ({ key: item.key, label: item.display_name }))),
  ];
}

function filterEnabledItems(
  detail: MonitorScanWindowDetail | null | undefined,
  enabledPlatformKeys: Set<string>,
  platformFilter: string
) {
  if (!detail) return [];
  const enabledItems = detail.items.filter((item) => enabledPlatformKeys.has(item.platform));
  if (platformFilter === 'all') return enabledItems;
  return enabledItems.filter((item) => item.platform === platformFilter);
}

function groupHistoryWindows(
  windows: MonitorScanWindowDetail[],
  hours: number
): Array<{
  key: string;
  label: string;
  items: MonitorWindowItem[];
  fetchedCount: number;
  deduplicatedCount: number;
  analyzedCount: number;
  duplicateCount: number;
}> {
  const groupCount = 6;
  const bucketSize = Math.max(1, Math.floor(hours / groupCount));
  const grouped: Array<{
    key: string;
    label: string;
    items: MonitorWindowItem[];
    fetchedCount: number;
    deduplicatedCount: number;
    analyzedCount: number;
    duplicateCount: number;
  }> = [];

  for (let index = 0; index < groupCount; index += 1) {
    const chunk = windows.slice(index * bucketSize, (index + 1) * bucketSize);
    if (!chunk.length) continue;
    const start = new Date(chunk[chunk.length - 1].window.window_start);
    const end = new Date(chunk[0].window.window_end);
    grouped.push({
      key: `${start.toISOString()}-${end.toISOString()}`,
      label: formatGroupedWindowRange(start, end),
      items: chunk.flatMap((window) => window.items),
      fetchedCount: chunk.reduce((sum, window) => sum + window.window.fetched_count, 0),
      deduplicatedCount: chunk.reduce((sum, window) => sum + window.window.deduplicated_count, 0),
      analyzedCount: chunk.reduce((sum, window) => sum + window.window.analyzed_count, 0),
      duplicateCount: chunk.reduce((sum, window) => sum + window.window.duplicate_count, 0),
    });
  }

  return grouped;
}

function WindowNewsCard({
  item,
  onOpenAnalysis,
  onAnalyze,
  isAnalyzing,
}: {
  item: MonitorWindowItem;
  onOpenAnalysis: (result: MonitorAnalysisResult, target: '/result' | '/simulation' | '/content') => void;
  onAnalyze: (item: MonitorWindowItem) => Promise<void>;
  isAnalyzing: boolean;
}) {
  const analysis = item.analysis_result ?? null;
  const canOpenResult = Boolean(analysis && (analysis.risk_snapshot_score != null || analysis.report_data));
  const canOpenSimulation = Boolean(analysis?.report_data);
  const canOpenContent = Boolean(analysis?.report_data);

  return (
    <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 shadow-[0_14px_30px_rgba(26,54,78,0.06)]">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="border-white/70 bg-[color:var(--panel-soft)] text-[color:var(--muted-strong)]">
              {item.platform_display_name ?? item.platform}
            </Badge>
            <Badge variant="outline" className="border-sky-200 bg-sky-500/10 text-sky-700">
              {trendLabel(item.trend)}
            </Badge>
            {analysis ? (
              <Badge variant="outline" className="border-sky-200 bg-sky-500/10 text-sky-700">
                {analysisStageLabel(analysis.current_stage)}
              </Badge>
            ) : (
              <Badge variant="outline" className={cn('border', analysisStatusTone(item.analysis_status))}>
                {analysisStatusLabel(item.analysis_status)}
              </Badge>
            )}
            {analysis?.risk_snapshot_score != null ? (
              <Badge variant={riskVariant(analysis.risk_snapshot_score)}>
                初判 {analysis.risk_snapshot_score}
              </Badge>
            ) : null}
            {analysis ? (
              <Badge variant="outline" className={cn('border', simulationTone(analysis.simulation_status))}>
                预演 {analysis.simulation_status === 'done' ? '已完成' : analysis.simulation_status === 'skipped' ? '未触发' : '待执行'}
              </Badge>
            ) : null}
            {item.is_duplicate_across_windows ? (
              <Badge variant="outline" className="border-amber-200 bg-amber-500/10 text-amber-700">
                跨窗口延续
              </Badge>
            ) : null}
          </div>

          <div className="space-y-1">
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-start gap-2 text-base font-medium leading-7 text-foreground transition-colors hover:text-[color:var(--panel-strong)] hover:underline"
            >
              <span>{item.title}</span>
              <ExternalLink className="mt-1 h-4 w-4 shrink-0 opacity-70" />
            </a>
            <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
              <span>热度 {item.hot_value}</span>
              <span>排名 #{item.rank}</span>
              <span>进入窗口 {new Date(item.created_at).toLocaleString('zh-CN')}</span>
            </div>
          </div>

          <div className="grid gap-2 md:grid-cols-3">
            <div className="rounded-2xl bg-[color:var(--panel-soft)]/72 px-3 py-3 text-sm">
              <div className="text-xs uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">风险初判</div>
              <div className="mt-1 font-medium text-foreground">
                {analysis?.risk_snapshot_score ?? '--'}
                {analysis?.risk_snapshot_label ? ` / ${analysis.risk_snapshot_label}` : ''}
              </div>
            </div>
            <div className="rounded-2xl bg-[color:var(--panel-soft)]/72 px-3 py-3 text-sm">
              <div className="text-xs uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">综合报告</div>
              <div className="mt-1 font-medium text-foreground">
                {analysis?.report_score ?? '--'}
                {analysis?.report_level ? ` / ${analysis.report_level}` : ''}
              </div>
            </div>
            <div className="rounded-2xl bg-[color:var(--panel-soft)]/72 px-3 py-3 text-sm">
              <div className="text-xs uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">链接核查</div>
              <div className="mt-1 font-medium text-foreground">
                {analysis?.crawl_status ?? analysisStatusLabel(item.analysis_status)}
              </div>
            </div>
          </div>

          {analysis?.last_error ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-500/8 px-3 py-3 text-sm text-rose-700">
              最近错误：{analysis.last_error}
            </div>
          ) : null}
        </div>

        <div className="flex w-full flex-col gap-2 xl:w-auto">
          <Button
            type="button"
            size="sm"
            className="rounded-full"
            onClick={() => void onAnalyze(item)}
            disabled={isAnalyzing}
          >
            <RefreshCcw className="mr-2 h-4 w-4" />
            {isAnalyzing ? '检测中...' : analysis ? '重新检测' : '手动检测'}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="rounded-full"
            disabled={!canOpenResult}
            onClick={() => analysis && onOpenAnalysis(analysis, '/result')}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            查看检测结果
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="rounded-full"
            disabled={!canOpenSimulation}
            onClick={() => analysis && onOpenAnalysis(analysis, '/simulation')}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            查看舆情预演
          </Button>
          <Button
            type="button"
            size="sm"
            className="rounded-full"
            disabled={!canOpenContent}
            onClick={() => analysis && onOpenAnalysis(analysis, '/content')}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            {analysis?.content_generation_status === 'done' ? '查看公关响应' : '生成公关响应'}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function MonitorDashboard() {
  const router = useRouter();
  const [platformFilter, setPlatformFilter] = useState<string>('all');
  const [historyHours, setHistoryHours] = useState<number>(6);
  const [historyGroupIndex, setHistoryGroupIndex] = useState<number>(0);
  const [analyzingItemId, setAnalyzingItemId] = useState<string | null>(null);
  const { status, isLoading: statusLoading, refresh: refreshStatus } = useMonitorStatus();
  const { window: latestWindow, isLoading: latestLoading, refresh: refreshLatest } = useLatestMonitorWindow();
  const { windows: historyWindows, isLoading: historyLoading, refresh: refreshHistory } = useMonitorWindowHistory(historyHours, 24);
  const loadFromMonitorAnalysisResult = usePipelineStore((state) => state.loadFromMonitorAnalysisResult);
  const enabledPlatformKeys = useMemo(
    () => new Set((status?.enabled_platforms ?? []).map((item) => item.key)),
    [status?.enabled_platforms]
  );

  const platforms = useMemo(
    () => collectPlatforms(status?.enabled_platforms),
    [status?.enabled_platforms]
  );
  const latestItems = useMemo(
    () => filterEnabledItems(latestWindow, enabledPlatformKeys, platformFilter),
    [latestWindow, enabledPlatformKeys, platformFilter]
  );
  const filteredHistory = useMemo(
    () =>
      historyWindows.map((window) => ({
        ...window,
        items: filterEnabledItems(window, enabledPlatformKeys, platformFilter),
      })),
    [historyWindows, enabledPlatformKeys, platformFilter]
  );
  const groupedHistory = useMemo(
    () => groupHistoryWindows(filteredHistory.filter((window) => window.items.length > 0), historyHours),
    [filteredHistory, historyHours]
  );
  const activeHistoryGroup = groupedHistory[historyGroupIndex] ?? groupedHistory[0] ?? null;
  const latestHighRiskCount = latestItems.filter((item) => (item.analysis_result?.risk_snapshot_score ?? 0) >= 70).length;
  const manualScanAutoAnalyze = Boolean(status?.manual_scan_auto_analyze_default);

  const handleScan = async () => {
    const toastId = toast.loading(
      '正在执行窗口扫描',
      manualScanAutoAnalyze
        ? '将先拉取并展示新闻窗口，随后自动进入检测流程'
        : '将只拉取并展示新闻窗口，不自动进入检测流程'
    );
    try {
      const scanResult = await monitorActions.triggerScan(platformFilter === 'all' ? undefined : [platformFilter]);
      await Promise.all([refreshStatus(), refreshLatest(), refreshHistory()]);
      toast.success(
        '窗口扫描完成',
        scanResult.analysis_scheduled
          ? '新闻已展示，后台正在继续执行自动检测'
          : platformFilter === 'all'
            ? '最新窗口与历史窗口均已刷新'
            : `已刷新 ${platformFilter} 平台窗口数据`
      );
    } catch (error) {
      console.error('Monitor window scan failed:', error);
      toast.error('扫描失败', '请检查后端监测服务与 NewsNow 数据源状态');
    } finally {
      toast.dismiss(toastId);
    }
  };

  const openAnalysisTarget = (result: MonitorAnalysisResult, target: '/result' | '/simulation' | '/content') => {
    loadFromMonitorAnalysisResult(result);
    router.push(target);
  };

  const handleAnalyzeItem = async (item: MonitorWindowItem) => {
    const toastId = toast.loading('正在执行手动检测', `正在处理《${item.title}》`);
    setAnalyzingItemId(item.id);
    try {
      await monitorActions.analyzeWindowItem(item.id);
      await Promise.all([refreshLatest(), refreshHistory()]);
      toast.success('手动检测完成', '该新闻已更新到检测链路结果');
    } catch (error) {
      console.error('Manual monitor analyze failed:', error);
      toast.error('手动检测失败', '请检查后端检测链路和新闻正文抓取状态');
    } finally {
      setAnalyzingItemId(null);
      toast.dismiss(toastId);
    }
  };

  return (
    <div className="space-y-4 md:space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {statusLoading || latestLoading ? (
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
                <CardDescription>查看当前调度器是否启用，以及小时窗口是否持续更新。</CardDescription>
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
                  <Badge variant="outline" className="border-sky-200 bg-sky-500/10 text-sky-700">
                    <Clock3 className="h-3 w-3" />
                    最新窗口
                  </Badge>
                  <ShieldAlert className="h-5 w-5 text-[color:var(--muted-strong)]" />
                </div>
                <CardTitle>{latestWindow ? formatWindowRange(latestWindow.window.window_start, latestWindow.window.window_end) : '暂无窗口'}</CardTitle>
                <CardDescription>顶部区域固定展示最新完整小时窗口。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <div className="flex items-center justify-between rounded-2xl bg-white/76 px-3 py-2">
                  <span>抓取 / 去重后</span>
                  <span className="font-medium text-foreground">
                    {latestWindow?.window.fetched_count ?? 0} / {latestWindow?.window.deduplicated_count ?? 0}
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-2xl bg-white/76 px-3 py-2">
                  <span>新检测 / 复用历史</span>
                  <span className="font-medium text-foreground">
                    {latestWindow?.window.analyzed_count ?? 0} / {latestWindow?.window.duplicate_count ?? 0}
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card className="border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.80),rgba(247,250,252,0.84))]">
              <CardHeader className="gap-3">
                <div className="flex items-center justify-between">
                  <Badge variant="riskHigh">
                    <Gauge className="h-3 w-3" />
                    风险密度
                  </Badge>
                  <TimerReset className="h-5 w-5 text-[color:var(--muted-strong)]" />
                </div>
                <CardTitle>最新窗口风险</CardTitle>
                <CardDescription>优先看最新窗口内需要进一步人工处理的新闻数量。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-4xl font-semibold tracking-[-0.04em] text-foreground">{latestHighRiskCount}</div>
                <p className="mt-3 text-sm text-muted-foreground">最新窗口新闻 {latestItems.length} 条，适合决定先处理哪几条。</p>
              </CardContent>
            </Card>

            <Card className="border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.82),rgba(243,248,251,0.84))]">
              <CardHeader className="gap-3">
                <div className="flex items-center justify-between">
                  <Badge variant="outline" className="border-amber-200 bg-amber-500/10 text-amber-700">
                    <Activity className="h-3 w-3" />
                    失败观测
                  </Badge>
                  <RefreshCcw className="h-5 w-5 text-[color:var(--muted-strong)]" />
                </div>
                <CardTitle>扫描健康度</CardTitle>
                <CardDescription>通过失败次数、最近错误和耗时判断监测链路是否稳定。</CardDescription>
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
          </>
        )}
      </div>

      <Card className="border-white/70 bg-[linear-gradient(155deg,rgba(255,255,255,0.82),rgba(244,249,252,0.82))]">
        <CardHeader className="border-b border-border/70">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <CardTitle>最新检测窗口</CardTitle>
              <CardDescription>这里固定展示最新完整小时窗口内拉取并检测过的新闻。</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {platforms.map((platform) => (
                <Button
                  key={platform.key}
                  type="button"
                  size="sm"
                  variant={platformFilter === platform.key ? 'default' : 'outline'}
                  onClick={() => setPlatformFilter(platform.key)}
                  className="rounded-full"
                >
                  {platform.label}
                </Button>
              ))}
              <Button type="button" size="sm" onClick={handleScan} className="rounded-full">
                <RefreshCcw className="mr-2 h-4 w-4" />
                {manualScanAutoAnalyze ? '立即扫描（先展示后检测）' : '立即扫描（仅拉取）'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          {latestLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-40 w-full rounded-[1.35rem]" />
              ))}
            </div>
          ) : !latestWindow ? (
            <div className="rounded-[1.3rem] border border-dashed border-border/70 bg-white/60 px-4 py-10 text-center text-sm text-muted-foreground">
              还没有最新窗口数据。先执行一次扫描，把新闻拉进检测工作台。
            </div>
          ) : latestItems.length === 0 ? (
            <div className="rounded-[1.3rem] border border-dashed border-border/70 bg-white/60 px-4 py-10 text-center text-sm text-muted-foreground">
              当前筛选条件下，最新窗口没有新闻。
            </div>
          ) : (
            <div className="max-h-[42rem] space-y-3 overflow-y-auto pr-2">
              {latestItems.map((item) => (
                <WindowNewsCard
                  key={item.id}
                  item={item}
                  onOpenAnalysis={openAnalysisTarget}
                  onAnalyze={handleAnalyzeItem}
                  isAnalyzing={analyzingItemId === item.id}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-white/70 bg-[linear-gradient(155deg,rgba(255,255,255,0.84),rgba(242,248,251,0.82))]">
        <CardHeader className="border-b border-border/70">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <CardTitle>历史检测窗口</CardTitle>
              <CardDescription>按整点窗口回看之前每小时拉取并检测过的新闻，默认按时间倒序显示。</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {[6, 12, 24].map((hours) => (
                <Button
                  key={hours}
                  type="button"
                  size="sm"
                  variant={historyHours === hours ? 'default' : 'outline'}
                  onClick={() => {
                    setHistoryHours(hours);
                    setHistoryGroupIndex(0);
                  }}
                  className="rounded-full"
                >
                  最近 {hours} 小时
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          {historyLoading ? (
            <div className="space-y-4">
              {Array.from({ length: 3 }).map((_, index) => (
                <Skeleton key={index} className="h-52 w-full rounded-[1.35rem]" />
              ))}
            </div>
          ) : groupedHistory.length === 0 ? (
            <div className="rounded-[1.3rem] border border-dashed border-border/70 bg-white/60 px-4 py-10 text-center text-sm text-muted-foreground">
              当前时间范围内还没有历史窗口数据。
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {groupedHistory.map((group, index) => (
                  <Button
                    key={group.key}
                    type="button"
                    size="sm"
                    variant={historyGroupIndex === index ? 'default' : 'outline'}
                    onClick={() => setHistoryGroupIndex(index)}
                    className="rounded-full"
                  >
                    {group.label}
                  </Button>
                ))}
              </div>

              {activeHistoryGroup ? (
                <div className="rounded-[1.35rem] border border-white/70 bg-white/76 p-4 shadow-[0_14px_30px_rgba(26,54,78,0.06)]">
                  <div className="flex flex-col gap-3 border-b border-border/60 pb-4 md:flex-row md:items-center md:justify-between">
                    <div>
                      <div className="text-base font-medium text-foreground">
                        {activeHistoryGroup.label}
                      </div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        抓取 {activeHistoryGroup.fetchedCount} 条，去重后 {activeHistoryGroup.deduplicatedCount} 条，新检测 {activeHistoryGroup.analyzedCount} 条
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Badge variant="outline" className="border-white/70 bg-[color:var(--panel-soft)]">
                        复用历史 {activeHistoryGroup.duplicateCount}
                      </Badge>
                      <Badge variant="outline" className="border-white/70 bg-[color:var(--panel-soft)]">
                        {activeHistoryGroup.items.length} 条展示结果
                      </Badge>
                    </div>
                  </div>

                  <div className="mt-4 max-h-[48rem] space-y-3 overflow-y-auto pr-2">
                    {activeHistoryGroup.items.length === 0 ? (
                      <div className="rounded-[1.2rem] border border-dashed border-border/70 bg-white/60 px-4 py-8 text-center text-sm text-muted-foreground">
                        当前筛选条件下，这个时间段没有新闻。
                      </div>
                    ) : (
                      activeHistoryGroup.items.map((item) => (
                        <WindowNewsCard
                          key={`${activeHistoryGroup.key}-${item.id}`}
                          item={item}
                          onOpenAnalysis={openAnalysisTarget}
                          onAnalyze={handleAnalyzeItem}
                          isAnalyzing={analyzingItemId === item.id}
                        />
                      ))
                    )}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
