'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { zhText, zhEmotion, zhSimulationStance } from '@/lib/i18n';
import dynamic from 'next/dynamic';

const ReactECharts = dynamic(() => import('echarts-for-react'), { ssr: false });

import type { SimulateResponse } from '@/types';

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

export function SimulationView({ simulation, isLoading }: SimulationViewProps) {
  const showEmotion = hasEmotionData(simulation);
  const showNarratives = hasNarrativesData(simulation);
  const showFlashpoints = hasFlashpointsData(simulation);
  const showSuggestion = hasSuggestionData(simulation);

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
          borderRadius: 10,
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
          borderRadius: 10,
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
      <Card>
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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>情绪分布</CardTitle>
            <CardDescription>预测的情绪反应分布</CardDescription>
          </CardHeader>
          <CardContent>
            {showEmotion ? (
              <ReactECharts option={emotionChartOption} style={{ height: '300px' }} />
            ) : (
              <StageSkeleton />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>立场分布</CardTitle>
            <CardDescription>预测的立场分布</CardDescription>
          </CardHeader>
          <CardContent>
            {showEmotion ? (
              <ReactECharts option={stanceChartOption} style={{ height: '300px' }} />
            ) : (
              <StageSkeleton />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>叙事分支</CardTitle>
          <CardDescription>可能的舆论走向预测</CardDescription>
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
                    <div key={index} className="border rounded-lg p-4">
                      <div className="flex items-start justify-between gap-4 mb-2">
                        <h4 className="font-medium">{zhText(narrative.title)}</h4>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{zhSimulationStance(narrative.stance)}</Badge>
                          <Badge>{((narrative.probability || 0) * 100).toFixed(0)}%</Badge>
                        </div>
                      </div>
                      <p className="text-sm text-muted-foreground mb-2">
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

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>引爆点</CardTitle>
            <CardDescription>高风险传播节点</CardDescription>
          </CardHeader>
          <CardContent>
            {showFlashpoints ? (
              <ul className="space-y-8">
                {simulation!.flashpoints.map((point, index) => (
                  <li key={index} className="flex items-start gap-2 text-sm">
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

        <Card>
          <CardHeader>
            <CardTitle>时间线</CardTitle>
            <CardDescription>预测的事件发展时间线</CardDescription>
          </CardHeader>
          <CardContent>
            {simulation?.timeline && simulation.timeline.length > 0 ? (
              <div className="space-y-4">
                {simulation.timeline.map((item, index) => (
                  <div key={index} className="flex gap-4">
                    <div className="flex flex-col items-center">
                      <div className="h-3 w-3 rounded-full bg-primary" />
                      {index < simulation.timeline!.length - 1 && (
                        <div className="h-full w-0.5 bg-border" />
                      )}
                    </div>
                    <div className="pb-4">
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

      <Card>
        <CardHeader>
          <CardTitle>应对建议</CardTitle>
          <CardDescription>针对性策略建议</CardDescription>
        </CardHeader>
        <CardContent>
          {showSuggestion ? (
            <div className="space-y-4">
              <p className="text-sm font-medium text-foreground">
                {zhText(simulation!.suggestion.summary)}
              </p>
              {simulation!.suggestion.actions.length > 0 && (
                <div className="space-y-3">
                  {simulation!.suggestion.actions.map((action, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-3 p-3 rounded-lg border bg-card"
                    >
                      <span
                        className={`px-2 py-0.5 text-xs font-medium rounded border ${
                          PRIORITY_STYLES[action.priority] || PRIORITY_STYLES.medium
                        }`}
                      >
                        {PRIORITY_LABELS[action.priority] || action.priority}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-medium">{zhText(action.action)}</span>
                          {action.category && (
                            <Badge variant="outline" className="text-xs">
                              {CATEGORY_LABELS[action.category] || action.category}
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-4 text-xs text-muted-foreground">
                          {action.timeline && (
                            <span>时间: {action.timeline}</span>
                          )}
                          {action.responsible && (
                            <span>责任方: {action.responsible}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <StageSkeleton />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
