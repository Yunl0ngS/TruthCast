'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { PageHero, PageSection, ProgressTimeline } from '@/components/layout';
import { 
  ClarificationCard, 
  FAQList, 
  PlatformScripts
} from '@/components/features/content-view';
import { ExportButton } from '@/components/features/export/export-button';
import { generateClarification, generateFAQ, generatePlatformScripts, updateHistoryContent } from '@/services/api';
import { usePipelineStore } from '@/stores/pipeline-store';
import { 
  ClarificationStyle, 
  Platform,
  ContentGenerateRequest,
  ContentDraft,
  ClarificationContent,
  ClarificationVariant,
  PlatformScript,
  FAQItem,
  Phase
} from '@/types';
import { toast } from 'sonner';

function createVariantId(style: ClarificationStyle) {
  return `clar_${style}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

const STYLE_OPTIONS: { value: ClarificationStyle; label: string }[] = [
  { value: 'formal', label: '正式严肃' },
  { value: 'friendly', label: '亲切友好' },
  { value: 'neutral', label: '中性客观' },
];

const PLATFORM_OPTIONS: { value: Platform; label: string; icon: string }[] = [
  { value: 'weibo', label: '微博', icon: '📱' },
  { value: 'wechat', label: '微信公众号', icon: '💬' },
  { value: 'xiaohongshu', label: '小红书', icon: '📕' },
  { value: 'douyin', label: '抖音', icon: '🎵' },
  { value: 'kuaishou', label: '快手', icon: '⚡' },
  { value: 'bilibili', label: 'B站', icon: '📺' },
  { value: 'short_video', label: '短视频口播', icon: '🎬' },
  { value: 'news', label: '新闻通稿', icon: '📰' },
  { value: 'official', label: '官方声明', icon: '📋' },
];

function formatDateTime(value?: string | null): string {
  if (!value) return '未知时间';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '未知时间';
  return d.toLocaleString('zh-CN');
}

type ContentMergePayload = Partial<ContentDraft> & {
  clarification_variant?: ClarificationVariant;
};

export default function ContentPage() {
  const router = useRouter();
  const {
    text: inputText,
    detectData,
    claims,
    evidences,
    report,
    simulation,
    content,
    setContent,
    phases,
    setPhase,
    retryPhase,
    interruptPipeline,
    recordId,
  } = usePipelineStore();

  const hasReport = report !== null;
  
  const [loadingAll, setLoadingAll] = useState(false);
  const [loadingClarification, setLoadingClarification] = useState(false);
  const [loadingFaq, setLoadingFaq] = useState(false);
  const [loadingScripts, setLoadingScripts] = useState(false);
  const [style, setStyle] = useState<ClarificationStyle>('neutral');
  const [selectedPlatforms, setSelectedPlatforms] = useState<Platform[]>([
    'weibo', 
    'wechat', 
    'xiaohongshu'
  ]);
  const [includeFaq, setIncludeFaq] = useState(true);
  const [faqCount, setFaqCount] = useState(5);

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  // 如果没有必要数据，重定向到首页
  useEffect(() => {
    if (!inputText || !report) {
      toast.error('请先完成新闻检测');
      router.push('/');
    }
  }, [inputText, report, router]);

  const buildRequest = (): ContentGenerateRequest => ({
    text: inputText,
    report: report!,
    simulation,
    // 若已生成澄清稿，后端可直接复用，避免多平台话术重复生成澄清稿
    clarification:
      (content?.clarifications?.find((v) => v.id === content?.primary_clarification_id)?.content ??
        content?.clarification ??
        null),
    style,
    platforms: selectedPlatforms,
    include_faq: includeFaq,
    faq_count: faqCount,
  });

  const mergeContent = (partial: ContentMergePayload) => {
    const now = new Date().toISOString();
    const basedOn = {
      style,
      platforms: selectedPlatforms,
      include_faq: includeFaq,
      faq_count: faqCount,
      has_simulation: Boolean(simulation),
      text_length: inputText.length,
    };

    // 重要：不能用闭包里的 content（异步分阶段生成会导致 content 读取陈旧，从而覆盖前面已生成的模块）
    const latest: ContentDraft = usePipelineStore.getState().content ?? {};

    // 特殊合并：澄清稿版本增量追加（同风格多版本并存）
    const incomingClarification = partial.clarification as ClarificationContent | undefined;
    const incomingClarificationVariant = partial.clarification_variant;
    const incomingPrimaryId = partial.primary_clarification_id;
    let mergedClarifications: ClarificationVariant[] | undefined;
    let primaryClarificationId: string | undefined;
    if (incomingClarificationVariant || incomingClarification) {
      const existing = latest.clarifications ?? [];
      mergedClarifications = Array.isArray(existing) ? [...existing] : [];

      if (incomingClarificationVariant) {
        mergedClarifications.push(incomingClarificationVariant);
        primaryClarificationId = incomingClarificationVariant.id;
      } else if (incomingClarification) {
        const v = {
          id: createVariantId(style),
          style,
          content: incomingClarification,
          generated_at: new Date().toISOString(),
        };
        mergedClarifications.push(v);
        primaryClarificationId = v.id;
      }
    }

    // 若仅更新主稿 ID（不新增澄清稿内容），也要同步主稿
    if (!primaryClarificationId && incomingPrimaryId) {
      primaryClarificationId = incomingPrimaryId;
    }

    // 特殊合并：平台话术按 platform 维度覆盖更新（保留未参与本次生成的平台话术）
    const incomingScripts = partial.platform_scripts as PlatformScript[] | undefined;
    const existingScripts = latest.platform_scripts;
    let mergedPlatformScripts: PlatformScript[] | undefined;
    if (incomingScripts) {
      const map = new Map<string, PlatformScript>();
      for (const s of existingScripts ?? []) {
        if (s?.platform) map.set(String(s.platform), s);
      }
      for (const s of incomingScripts) {
        if (s?.platform) map.set(String(s.platform), s);
      }
      // 保持顺序：先按已有顺序输出，再补充新增平台
      const ordered: PlatformScript[] = [];
      const seen = new Set<string>();
      for (const s of existingScripts ?? []) {
        const key = String(s?.platform ?? '');
        const val = map.get(key);
        if (key && val && !seen.has(key)) {
          ordered.push(val);
          seen.add(key);
        }
      }
      for (const [key, val] of map.entries()) {
        if (!seen.has(key)) {
          ordered.push(val);
          seen.add(key);
        }
      }
      mergedPlatformScripts = ordered;
    }

    const next: ContentDraft = {
      ...latest,
      ...partial,
      generated_at: latest.generated_at ?? now,
      based_on: latest.based_on ?? basedOn,
    };

    // 写入澄清稿版本列表与主稿
    if (mergedClarifications) {
      next.clarifications = mergedClarifications;
    }
    if (primaryClarificationId) {
      next.primary_clarification_id = primaryClarificationId;
      // 同时兼容旧字段：将主稿内容同步到 content.clarification
      const primary = (next.clarifications ?? latest.clarifications ?? []).find(
        (v) => v.id === primaryClarificationId
      );
      if (primary?.content) {
        next.clarification = primary.content;
      }
    }

    if (mergedPlatformScripts) {
      next.platform_scripts = mergedPlatformScripts;
    }

    setContent(next);

    // 若存在历史 recordId（来自 /detect/report 落库 或 历史回放 record_id），则把应对内容写回历史记录
    // 允许“从历史记录加载后再生成/调整应对内容”并持久化到同一条记录
    if (recordId) {
      updateHistoryContent(recordId, next).catch((err) => {
        console.warn('写入历史 content 失败:', err);
      });
    }
  };

  const handleGenerateAll = async () => {
    if (!inputText || !report) {
      toast.error('缺少必要数据');
      return;
    }

    setLoadingAll(true);
    setPhase('content', 'running');
    // 不清空旧结果：保留已生成内容，后续分阶段生成会按模块覆盖/补全
    mergeContent({
      generated_at: new Date().toISOString(),
      based_on: {
        style,
        platforms: selectedPlatforms,
        include_faq: includeFaq,
        faq_count: faqCount,
        has_simulation: Boolean(simulation),
        text_length: inputText.length,
      },
    });

    try {
      const request = buildRequest();

      // 半并发策略：澄清稿与 FAQ 并发；待澄清稿完成后再生成多平台话术（复用澄清稿提高一致性）
      setLoadingClarification(true);
      const clarificationPromise = generateClarification(request)
        .then((clarification) => {
          mergeContent({ clarification });
          return clarification;
        })
        .finally(() => setLoadingClarification(false));

      let faqPromise: Promise<FAQItem[] | null>;
      if (includeFaq) {
        setLoadingFaq(true);
        faqPromise = generateFAQ(request)
          .then((faq) => {
            mergeContent({ faq });
            return faq;
          })
          .finally(() => setLoadingFaq(false));
      } else {
        mergeContent({ faq: null });
        faqPromise = Promise.resolve(null);
      }

      // 平台话术依赖澄清稿：等待澄清稿完成，并把结果显式注入请求，避免因为 state 更新时序导致后端未复用主稿
      const clarification = await clarificationPromise;
      const scriptsRequest = {
        ...request,
        clarification,
      };

      setLoadingScripts(true);
      const platform_scripts = await generatePlatformScripts(scriptsRequest);
      mergeContent({ platform_scripts });
      setLoadingScripts(false);

      // 等待 FAQ 也完成后再宣告“一键生成完成”
      await faqPromise;

      setPhase('content', 'done');
      toast.success('一键生成完成');
    } catch (error) {
      console.error('生成失败:', error);
      toast.error('生成失败，请重试');
      setPhase('content', 'failed');
    } finally {
      setLoadingAll(false);
      setLoadingClarification(false);
      setLoadingFaq(false);
      setLoadingScripts(false);
    }
  };

  const handleGenerateClarificationOnly = async () => {
    if (!inputText || !report) {
      toast.error('缺少必要数据');
      return;
    }

    setLoadingClarification(true);
    setPhase('content', 'running');
    try {
      const clarification = await generateClarification(buildRequest());
      mergeContent({ clarification });
      setPhase('content', 'done');
      toast.success('澄清稿已生成');
    } catch (error) {
      console.error('澄清稿生成失败:', error);
      toast.error('澄清稿生成失败');
      setPhase('content', 'failed');
    } finally {
      setLoadingClarification(false);
    }
  };

  const handleGenerateFaqOnly = async () => {
    if (!inputText || !report) {
      toast.error('缺少必要数据');
      return;
    }
    if (!includeFaq) {
      toast.error('请先勾选“生成 FAQ”');
      return;
    }

    setLoadingFaq(true);
    setPhase('content', 'running');
    try {
      const faq = await generateFAQ(buildRequest());
      mergeContent({ faq });
      setPhase('content', 'done');
      toast.success('FAQ 已生成');
    } catch (error) {
      console.error('FAQ 生成失败:', error);
      toast.error('FAQ 生成失败');
      setPhase('content', 'failed');
    } finally {
      setLoadingFaq(false);
    }
  };

  const handleGenerateScriptsOnly = async () => {
    if (!inputText || !report) {
      toast.error('缺少必要数据');
      return;
    }
    if (selectedPlatforms.length === 0) {
      toast.error('请至少选择一个平台');
      return;
    }

    setLoadingScripts(true);
    setPhase('content', 'running');
    try {
      const platform_scripts = await generatePlatformScripts(buildRequest());
      mergeContent({ platform_scripts });
      setPhase('content', 'done');
      toast.success('多平台话术已生成');
    } catch (error) {
      console.error('多平台话术生成失败:', error);
      toast.error('多平台话术生成失败');
      setPhase('content', 'failed');
    } finally {
      setLoadingScripts(false);
    }
  };

  const togglePlatform = (platform: Platform) => {
    setSelectedPlatforms(prev => 
      prev.includes(platform)
        ? prev.filter(p => p !== platform)
        : [...prev, platform]
    );
  };

  // 加载中骨架屏
  if (!inputText || !report) {
    return (
      <div className="space-y-6 md:space-y-8">
        <PageHero
          eyebrow="Content Studio"
          title="应对内容生成"
          description="基于已完成的分析结果生成澄清稿、FAQ 和多平台话术。"
        />
        <Skeleton className="h-12 w-full mb-6" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="Content Studio"
        title="应对内容生成"
        // description="这里把分析结果转成可发布、可解释、可分发的内容产物。页面定位是内容工作台，而不是简单的表单输出页。"
        meta={
          <>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              澄清稿 / FAQ / 平台话术
            </div>
            {/* <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              基于报告结果生成
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
                rememberExpandedKey="timeline_content"
              />
            </div>
            {hasReport && (
              <ExportButton
                data={{
                  inputText: inputText,
                  detectData,
                  claims,
                  evidences,
                  report,
                  simulation,
                  content: content ?? null,
                  exportedAt: new Date().toLocaleString('zh-CN'),
                }}
              />
            )}
          </>
        }
      />

      <PageSection
        title="生成设置"
        description="设置澄清稿风格、FAQ 条数和目标平台；这块是内容工作台的操作区。"
      >
      <Card className="mb-0 border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.82),rgba(243,248,251,0.80))]">
        <CardHeader className="pb-3 flex flex-row items-center justify-between gap-4">
          <CardTitle className="text-lg">生成设置</CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setContent(null)}
            disabled={loadingAll || loadingClarification || loadingFaq || loadingScripts}
          >
            清空生成结果
          </Button>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* 澄清稿风格 + 仅生成澄清稿 */}
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2 flex-1">
              <label className="text-sm font-medium">澄清稿风格</label>
              <div className="flex flex-wrap gap-2">
                {STYLE_OPTIONS.map(opt => (
                  <Button
                    key={opt.value}
                    variant={style === opt.value ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setStyle(opt.value)}
                  >
                    {opt.label}
                  </Button>
                ))}
              </div>
            </div>
            <div className="pt-6 shrink-0">
              <Button
                variant="secondary"
                onClick={handleGenerateClarificationOnly}
                disabled={loadingAll || loadingClarification}
                className="w-44"
              >
                {loadingClarification ? '生成澄清稿中...' : '生成澄清稿'}
              </Button>
            </div>
          </div>

          {/* FAQ 设置 + 仅生成FAQ */}
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2 flex-1">
              <label className="text-sm font-medium">FAQ</label>
              <div className="flex flex-wrap items-center gap-4">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={includeFaq}
                    onChange={(e) => setIncludeFaq(e.target.checked)}
                    className="rounded"
                  />
                  <span className="text-sm">生成 FAQ</span>
                </label>
                {includeFaq && (
                  <div className="flex items-center gap-2">
                    <label className="text-sm">条目数：</label>
                    <select
                      value={faqCount}
                      onChange={(e) => setFaqCount(Number(e.target.value))}
                      className="border rounded px-2 py-1 text-sm"
                    >
                      {[3, 4, 5, 6, 7, 8, 9, 10].map(n => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            </div>
            <div className="pt-6 shrink-0">
              <Button
                variant="secondary"
                onClick={handleGenerateFaqOnly}
                disabled={loadingAll || loadingFaq || !includeFaq}
                className="w-44"
              >
                {loadingFaq ? '生成 FAQ 中...' : '生成 FAQ'}
              </Button>
            </div>
          </div>

          {/* 平台选择 + 仅生成多平台话术 */}
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2 flex-1">
              <label className="text-sm font-medium">目标平台（可多选）</label>
              <div className="flex flex-wrap gap-2">
                {PLATFORM_OPTIONS.map(opt => (
                  <Button
                    key={opt.value}
                    variant={selectedPlatforms.includes(opt.value) ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => togglePlatform(opt.value)}
                    className="gap-1"
                  >
                    <span>{opt.icon}</span>
                    {opt.label}
                  </Button>
                ))}
              </div>
            </div>
            <div className="pt-6 shrink-0">
              <Button
                variant="secondary"
                onClick={handleGenerateScriptsOnly}
                disabled={loadingAll || loadingScripts || selectedPlatforms.length === 0}
                className="w-44"
              >
                {loadingScripts ? '生成多平台话术中...' : '生成多平台话术'}
              </Button>
            </div>
          </div>

          {/* 底部一键生成（居中） */}
          <div className="pt-2 flex justify-center">
            <Button
              onClick={handleGenerateAll}
              disabled={loadingAll || loadingClarification || loadingFaq || loadingScripts || selectedPlatforms.length === 0}
              className="w-full md:w-[520px] bg-primary hover:bg-primary/90"
            >
              {loadingAll ? '一键生成中...' : '一键生成（澄清稿 + FAQ + 多平台话术）'}
            </Button>
          </div>
        </CardContent>
      </Card>
      </PageSection>

      {/* 生成结果 */}
      {content && (
        <PageSection
          title="生成结果"
          description="内容结果继续沿用现有生成逻辑，但整体容器和页面层级已经统一到新的工作台风格。"
          muted
        >
        <div className="space-y-6">
          {/* 澄清稿 */}
          {content.clarifications && content.clarifications.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">澄清稿（多风格版本）</h2>
                <div className="text-xs text-muted-foreground">
                  点击“设为主稿”将影响导出与历史记录默认版本
                </div>
              </div>

              {[...content.clarifications]
                .sort((a, b) => (b.generated_at || '').localeCompare(a.generated_at || ''))
                .map((v) => {
                  const isPrimary = v.id === content.primary_clarification_id;
                  return (
                    <ClarificationCard
                      key={v.id}
                      clarification={v.content}
                      style={v.style}
                      title={isPrimary ? '澄清稿（主稿）' : '澄清稿'}
                      meta={formatDateTime(v.generated_at)}
                      extraActions={
                        <Button
                          variant={isPrimary ? 'default' : 'outline'}
                          size="sm"
                          onClick={() => {
                            mergeContent({ primary_clarification_id: v.id });
                            toast.success('已设为主稿');
                          }}
                        >
                          {isPrimary ? '主稿' : '设为主稿'}
                        </Button>
                      }
                    />
                  );
                })}
            </div>
          )}

          {/* FAQ */}
          {content.faq && content.faq.length > 0 && (
            <FAQList faq={content.faq} />
          )}

          {/* 多平台话术 */}
          {content.platform_scripts && content.platform_scripts.length > 0 && (
            <PlatformScripts scripts={content.platform_scripts} />
          )}

          {/* 元数据 */}
          {content.generated_at && (
            <div className="text-xs text-muted-foreground text-center">
              生成时间：{formatDateTime(content.generated_at)}
            </div>
          )}
        </div>
        </PageSection>
      )}
    </div>
  );
}
