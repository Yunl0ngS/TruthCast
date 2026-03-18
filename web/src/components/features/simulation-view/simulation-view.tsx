'use client';

import dynamic from 'next/dynamic';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { zhEmotion, zhSimulationStance, zhText } from '@/lib/i18n';
import type { SimulateResponse } from '@/types';

const ReactECharts = dynamic(() => import('echarts-for-react'), { ssr: false });

interface SimulationViewProps {
  simulation: SimulateResponse | null;
  isLoading: boolean;
}

function StageSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  );
}

function hasEmotionData(simulation: SimulateResponse | null): boolean {
  return !!simulation && Object.keys(simulation.emotion_distribution || {}).length > 0;
}

function hasNarrativesData(simulation: SimulateResponse | null): boolean {
  return !!simulation && (simulation.narratives?.length || 0) > 0;
}

function hasFlashpointsData(simulation: SimulateResponse | null): boolean {
  return !!simulation && (simulation.flashpoints?.length || 0) > 0;
}

function hasSuggestionData(simulation: SimulateResponse | null): boolean {
  return !!simulation && !!simulation.suggestion?.summary;
}

const PRIORITY_STYLES: Record<string, string> = {
  urgent: 'bg-red-100 text-red-800 border-red-300',
  high: 'bg-orange-100 text-orange-800 border-orange-300',
  medium: 'bg-blue-100 text-blue-800 border-blue-300',
};

const PRIORITY_LABELS: Record<string, string> = {
  urgent: '紧急',
  high: '高',
  medium: '中',
};

const CATEGORY_LABELS: Record<string, string> = {
  official: '官方回应',
  media: '媒体沟通',
  platform: '平台协调',
  user: '用户互动',
};

const chartCardClassName =
  'border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.82),rgba(243,248,251,0.80))] shadow-[0_16px_36px_rgba(26,54,78,0.08)]';

export function SimulationView({ simulation, isLoading }: SimulationViewProps) {
  const showEmotion = hasEmotionData(simulation);
  const showNarratives = hasNarrativesData(simulation);
  const showFlashpoints = hasFlashpointsData(simulation);
  const showSuggestion = hasSuggestionData(simulation);
  const timelineItems = simulation?.timeline ?? [];

  const emotionChartData = showEmotion
    ? Object.entries(simulation!.emotion_distribution).map(([name, value]) => ({
        name: zhEmotion(name),
        value,
      }))
    : [];

  const stanceChartData = showEmotion
    ? Object.entries(simulation!.stance_distribution).map(([name, value]) => ({
        name: zhSimulationStance(name),
        value,
      }))
    : [];

  const emotionChartOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left' },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 12,
          borderColor: '#fff',
          borderWidth: 2,
        },
        label: {
          show: true,
          formatter: '{b}\n{d}%',
          fontSize: 12,
        },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' },
        },
        labelLine: {
          show: true,
          length: 10,
          length2: 10,
        },
        data: emotionChartData,
      },
    ],
  };

  const stanceChartOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left' },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 12,
          borderColor: '#fff',
          borderWidth: 2,
        },
        label: {
          show: true,
          formatter: '{b}\n{d}%',
          fontSize: 12,
        },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' },
        },
        labelLine: {
          show: true,
          length: 10,
          length2: 10,
        },
        data: stanceChartData,
      },
    ],
  };

  if (!simulation && !isLoading) {
    return (
      <Card className={chartCardClassName}>
        <CardHeader>
          <CardTitle>舆情预演</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">请先完成文本分析以获取舆情预演结果。</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card className={chartCardClassName}>
        <CardHeader>
          <CardTitle>传播预测</CardTitle>
          <CardDescription>用情绪和立场图表判断整体传播走势，作为预演页的第一层。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card className="border-white/60 bg-white/72 shadow-[0_10px_24px_rgba(26,54,78,0.05)]">
              <CardHeader>
                <CardTitle>情绪分布</CardTitle>
                <CardDescription>预测的情绪反应分布</CardDescription>
              </CardHeader>
              <CardContent>
                {showEmotion ? (
                  <ReactECharts option={emotionChartOption} style={{ height: '280px' }} />
                ) : (
                  <StageSkeleton />
                )}
              </CardContent>
            </Card>

            <Card className="border-white/60 bg-white/72 shadow-[0_10px_24px_rgba(26,54,78,0.05)]">
              <CardHeader>
                <CardTitle>立场分布</CardTitle>
                <CardDescription>预测的立场分布</CardDescription>
              </CardHeader>
              <CardContent>
                {showEmotion ? (
                  <ReactECharts option={stanceChartOption} style={{ height: '280px' }} />
                ) : (
                  <StageSkeleton />
                )}
              </CardContent>
            </Card>
          </div>
        </CardContent>
      </Card>

      <Card className={chartCardClassName}>
        <CardHeader>
          <CardTitle>叙事分支</CardTitle>
          <CardDescription>可能的舆论走向预测，作为传播预测后的第二层阅读内容。</CardDescription>
        </CardHeader>
        <CardContent>
          {showNarratives ? (
            <div className="space-y-4">
              {[...simulation!.narratives]
                .sort((a, b) => b.probability - a.probability)
                .map((narrative, index) => {
                  const rawKeywords = narrative.trigger_keywords as string[] | string | undefined;
                  const keywords: string[] = Array.isArray(rawKeywords)
                    ? rawKeywords
                    : typeof rawKeywords === 'string'
                    ? rawKeywords.split(/[,，]/).map((k: string) => k.trim()).filter(Boolean)
                    : [];

                  return (
                    <div
                      key={index}
                      className="rounded-[1.2rem] border border-white/60 bg-white/82 p-4 shadow-[0_8px_18px_rgba(26,54,78,0.04)]"
                    >
                      <div className="mb-2 flex items-start justify-between gap-4">
                        <h4 className="font-medium">{zhText(narrative.title)}</h4>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{zhSimulationStance(narrative.stance)}</Badge>
                          <Badge>{((narrative.probability || 0) * 100).toFixed(0)}%</Badge>
                        </div>
                      </div>
                      <p className="mb-2 text-sm text-muted-foreground">
                        {zhText(narrative.sample_message)}
                      </p>
                      {keywords.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {keywords.map((keyword: string, idx: number) => (
                            <Badge key={idx} variant="secondary" className="text-xs">
                              {keyword}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          ) : (
            <StageSkeleton />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[0.88fr_1.12fr]">
        <Card className={chartCardClassName}>
          <CardHeader>
            <CardTitle>引爆点</CardTitle>
            <CardDescription>需要重点监测的高风险传播节点</CardDescription>
          </CardHeader>
          <CardContent>
            {showFlashpoints ? (
              <ul className="space-y-4">
                {simulation!.flashpoints.map((point, index) => (
                  <li
                    key={index}
                    className="flex items-start gap-3 rounded-[1.2rem] border border-white/60 bg-white/76 px-4 py-3 text-sm shadow-[0_8px_18px_rgba(26,54,78,0.04)]"
                  >
                    <span className="text-red-500">⚠</span>
                    {zhText(point)}
                  </li>
                ))}
              </ul>
            ) : (
              <StageSkeleton />
            )}
          </CardContent>
        </Card>

        <Card className={chartCardClassName}>
          <CardHeader>
            <CardTitle>时间线</CardTitle>
            <CardDescription>预测的事件发展时间线</CardDescription>
          </CardHeader>
          <CardContent>
            {timelineItems.length > 0 ? (
              <div className="space-y-4">
                {timelineItems.map((item, index) => (
                  <div key={index} className="flex gap-4 rounded-[1.2rem] border border-white/60 bg-white/76 px-4 py-4 shadow-[0_8px_18px_rgba(26,54,78,0.04)]">
                    <div className="flex flex-col items-center">
                      <div className="h-3 w-3 rounded-full bg-primary" />
                      {index < timelineItems.length - 1 && (
                        <div className="h-full w-0.5 bg-border" />
                      )}
                    </div>
                    <div className="pb-1">
                      <p className="text-sm font-medium">第 {item.hour} 小时</p>
                      <p className="text-sm">{zhText(item.event)}</p>
                      <p className="text-xs text-muted-foreground">{zhText(item.expected_reach)}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <StageSkeleton />
            )}
          </CardContent>
        </Card>
      </div>

      <Card
        className="overflow-hidden border-white/70 text-[color:var(--panel-strong-foreground)] shadow-[0_22px_46px_rgba(24,53,76,0.20)]"
        data-panel="strong"
      >
        <CardHeader>
          <CardTitle className="text-[color:var(--panel-strong-foreground)]">应对建议</CardTitle>
          {/* <CardDescription className="text-white/76">
            最后一层再回答“现在该做什么”，与上面的传播判断形成收束。
          </CardDescription> */}
        </CardHeader>
        <CardContent className="space-y-5">
          {showSuggestion ? (
            <>
              <div className="rounded-[1.35rem] border border-white/12 bg-white/8 px-4 py-4 text-sm leading-7 text-white/88 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
                {zhText(simulation!.suggestion.summary)}
              </div>
              {simulation!.suggestion.actions.length > 0 && (
                <div className="space-y-3">
                  {simulation!.suggestion.actions.map((action, idx) => (
                    <div
                      key={idx}
                      className="rounded-[1.2rem] border border-white/12 bg-white/8 p-4 shadow-[0_10px_24px_rgba(8,18,29,0.16)]"
                    >
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                            PRIORITY_STYLES[action.priority] || PRIORITY_STYLES.medium
                          }`}
                        >
                          {PRIORITY_LABELS[action.priority] || action.priority}
                        </span>
                        {action.category && (
                          <Badge variant="outline" className="border-white/15 bg-white/8 text-white/78">
                            {CATEGORY_LABELS[action.category] || action.category}
                          </Badge>
                        )}
                      </div>
                      <div className="text-sm font-medium text-white">{zhText(action.action)}</div>
                      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-white/68">
                        {action.timeline ? <span>时间: {action.timeline}</span> : null}
                        {action.responsible ? <span>责任方: {action.responsible}</span> : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <StageSkeleton />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
