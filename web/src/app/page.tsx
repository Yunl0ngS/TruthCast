'use client';

import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { PageHero, PageSection } from '@/components/layout';
import { deleteMultimodalImage, resolveApiUrl, uploadMultimodalImage } from '@/services/api';
import { useIsLoading, usePipelineStore } from '@/stores/pipeline-store';
import type { StoredImage } from '@/types';
import {
  AlertCircle,
  FileCheck2,
  FileText,
  Globe,
  ImagePlus,
  Layers3,
  Loader2,
  Radar,
  Search,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
} from 'lucide-react';

const capabilityCards = [
  {
    title: '风险初判',
    description: '先给出初步风险等级和复杂度判断，决定后续核查深度。',
    icon: Radar,
  },
  {
    title: '证据链路',
    description: '抽取主张、检索证据、做对齐与综合判断，不停留在单点打分。',
    icon: FileCheck2,
  },
  {
    title: '传播预演',
    description: '预测舆情走势、引爆点和建议动作，便于提前响应。',
    icon: Layers3,
  },
];

const roleStories = [
  {
    title: '侦测者',
    description: '识别文本、链接、图片中的异常信号，完成风险初判与任务分流。',
    icon: Search,
    accent: '发现异常',
  },
  {
    title: '考据者',
    description: '拆解核心主张，检索外部证据，核对来源与上下文，补齐事实依据。',
    icon: FileCheck2,
    accent: '追索依据',
  },
  {
    title: '裁决者',
    description: '汇总证据与对齐结果，给出风险结论、可信边界和综合判断。',
    icon: FileText,
    accent: '形成判断',
  },
  {
    title: '推演者',
    description: '预测情绪变化、立场分化、传播路径与引爆点，提前看见后续走势。',
    icon: ShieldCheck,
    accent: '预见扩散',
  },
  {
    title: '响应者',
    description: '基于研判结果生成公关响应、澄清稿、FAQ 与多平台表达方案。',
    icon: Layers3,
    accent: '组织发声',
  },
];

export default function HomePage() {
  const router = useRouter();
  const {
    text,
    error,
    setText,
    images,
    setImages,
    runPipeline,
    crawlUrl,
    restorableTaskId,
    restorableUpdatedAt,
    hydrateFromLatest,
  } = usePipelineStore();
  const isLoading = useIsLoading();

  const [url, setUrl] = useState('');
  const [restoreDisabled, setRestoreDisabled] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragActive, setIsDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    try {
      setRestoreDisabled(sessionStorage.getItem('truthcast_restore_disabled') === '1');
    } catch {
      setRestoreDisabled(false);
    }
  }, []);

  const handleRun = async () => {
    if (!text.trim() && images.length === 0) {
      toast.warning('请输入待分析的文本或至少上传一张图片');
      return;
    }
    router.push('/result');
    runPipeline();
  };

  const uploadFiles = async (fileList: File[]) => {
    if (fileList.length === 0) return;
    setIsUploading(true);
    try {
      const uploaded: StoredImage[] = [];
      for (const file of fileList) {
        if (!file.type.startsWith('image/')) {
          throw new Error(`仅支持图片上传：${file.name}`);
        }
        const item = await uploadMultimodalImage(file);
        uploaded.push(item);
      }
      setImages([...images, ...uploaded]);
      toast.success(`已上传 ${uploaded.length} 张图片，可直接开始多模态分析`);
    } catch (err) {
      toast.error(`图片上传失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setIsUploading(false);
    }
  };

  const handleUploadFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(event.target.files ?? []);
    await uploadFiles(fileList);
    event.target.value = '';
  };

  const handleRemoveImage = async (fileId: string) => {
    try {
      await deleteMultimodalImage(fileId);
    } catch (err) {
      toast.error(`删除图片失败：${err instanceof Error ? err.message : '未知错误'}`);
      return;
    }
    setImages(images.filter((item) => item.file_id !== fileId));
  };

  const handleClearImages = async () => {
    try {
      await Promise.all(images.map((image) => deleteMultimodalImage(image.file_id).catch(() => null)));
    } finally {
      setImages([]);
    }
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!isUploading && !isLoading) {
      setIsDragActive(true);
    }
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragActive(false);
  };

  const handleDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragActive(false);
    if (isUploading || isLoading) return;
    const fileList = Array.from(event.dataTransfer.files ?? []);
    await uploadFiles(fileList);
  };

  const handleCrawl = () => {
    if (!url.trim()) {
      toast.warning('请输入待分析的网页链接');
      return;
    }
    if (!url.startsWith('http')) {
      toast.warning('请输入有效的 URL（以 http:// 或 https:// 开头）');
      return;
    }

    router.push('/result');
    crawlUrl(url).catch(() => {});
  };

  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="TruthCast / Response Cockpit"
        title="TruthCast 事实核查与舆情推演系统"
        // description="输入文本、链接或图片后，系统会依次给出风险初判、主张抽取、证据链、综合结论与舆情预演。首页既保留直接开工的效率，也提供清晰的产品价值说明。"
        meta={
          <>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              五阶段闭环核查
            </div>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              证据驱动，不做绝对判定
            </div>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              支持多模态输入
            </div>
          </>
        }
        actions={
          <>
            <div className="rounded-[1.25rem] border border-white/60 bg-white/66 px-4 py-3 shadow-[0_14px_28px_rgba(26,54,78,0.08)]">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--muted-strong)]">
                当前状态
              </div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {restorableTaskId ? '存在可恢复任务' : '准备开始新任务'}
              </div>
            </div>
            <Button size="lg" onClick={handleRun} disabled={isLoading || isUploading}>
              {isLoading ? '分析中...' : '快速开始分析'}
            </Button>
          </>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <Card className="overflow-hidden border-white/70 bg-[linear-gradient(160deg,rgba(255,255,255,0.84),rgba(244,249,252,0.82))]">
          <CardHeader className="border-b border-border/60 pb-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-2">
                <div className="inline-flex items-center gap-2 rounded-full border border-[color:var(--border-strong)] bg-white/72 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--muted-strong)]">
                  <Sparkles className="h-3.5 w-3.5" />
                  任务入口
                </div>
                <CardTitle className="text-2xl md:text-[2rem]">开始一次研判任务</CardTitle>
                <CardDescription>
                  支持文本核查、链接抓取与图片多模态分析。这里保持原有工作流，但会把最重要的输入入口放在同一张一级卡中。
                </CardDescription>
              </div>
              <div className="rounded-[1.25rem] border border-white/70 bg-[color:var(--panel-strong)] px-4 py-3 text-[color:var(--panel-strong-foreground)] shadow-[0_18px_36px_rgba(24,53,76,0.22)]">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/72">
                  输入模式
                </div>
                <div className="mt-1 text-sm font-medium">文本 / 链接 / 图片</div>
              </div>
            </div>
          </CardHeader>

          <CardContent className="space-y-6 pt-6">
            <Tabs defaultValue="text" className="w-full">
              <TabsList className="grid w-full grid-cols-2 rounded-2xl border border-white/60 bg-white/65 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.45)]">
                <TabsTrigger value="text" className="flex items-center gap-2 rounded-xl">
                  <FileText className="h-4 w-4" />
                  文本分析
                </TabsTrigger>
                <TabsTrigger value="url" className="flex items-center gap-2 rounded-xl">
                  <Globe className="h-4 w-4" />
                  链接核查
                </TabsTrigger>
              </TabsList>

              <TabsContent value="text" className="space-y-5 pt-5">
                <Textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="请输入待分析的新闻文本，也可以只上传图片进行多模态分析。"
                  rows={8}
                  className="resize-none rounded-[1.35rem] border-white/60 bg-white/74 px-4 py-3 text-base shadow-[0_10px_24px_rgba(26,54,78,0.06)]"
                />

                <div
                  className={[
                    'space-y-4 rounded-[1.5rem] border border-dashed p-4 transition-colors md:p-5',
                    isDragActive
                      ? 'border-primary bg-primary/8 shadow-[0_14px_30px_rgba(24,53,76,0.08)]'
                      : 'border-border/80 bg-[color:var(--panel-soft)]/72 hover:bg-[color:var(--panel-soft)]/90',
                  ].join(' ')}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <ImagePlus className="h-4 w-4 text-primary" />
                        图片上传（多模态分析）
                      </div>
                      <p className="text-xs leading-6 text-muted-foreground">
                        上传后会自动进入 OCR 与语义分析链路。适合截图、海报、聊天记录等含图内容的快速核查。
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {images.length > 0 ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={handleClearImages}
                          disabled={isUploading || isLoading}
                        >
                          清空图片
                        </Button>
                      ) : null}
                      <label className="inline-flex">
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept="image/*"
                          multiple
                          className="hidden"
                          onChange={handleUploadFiles}
                          disabled={isUploading || isLoading}
                        />
                        <span className="inline-flex cursor-pointer items-center justify-center rounded-xl border border-white/60 bg-white px-3 py-2 text-sm font-medium shadow-[0_10px_24px_rgba(26,54,78,0.08)] transition-colors hover:bg-accent hover:text-accent-foreground">
                          {isUploading ? (
                            <span className="inline-flex items-center gap-2">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              上传中...
                            </span>
                          ) : (
                            '选择图片'
                          )}
                        </span>
                      </label>
                    </div>
                  </div>

                  <button
                    type="button"
                    className={[
                      'group w-full rounded-[1.35rem] border border-dashed px-4 py-7 text-left transition-all md:px-5',
                      isDragActive
                        ? 'border-primary bg-primary/10'
                        : 'border-border/80 bg-white/72 hover:border-primary/50 hover:bg-white',
                    ].join(' ')}
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading || isLoading}
                  >
                    <div className="flex flex-col items-center justify-center gap-3 text-center">
                      <div className="flex h-14 w-14 items-center justify-center rounded-full border border-white/70 bg-white shadow-[0_12px_28px_rgba(26,54,78,0.10)]">
                        {isUploading ? (
                          <Loader2 className="h-5 w-5 animate-spin text-primary" />
                        ) : (
                          <UploadCloud className="h-5 w-5 text-primary" />
                        )}
                      </div>
                      <div className="space-y-1">
                        <div className="text-sm font-medium text-foreground">
                          {isDragActive ? '松开鼠标即可上传图片' : '点击选择图片，或将图片拖拽到此处'}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          支持多张图片；上传后会自动接入多模态 detect 链路。
                        </div>
                      </div>
                    </div>
                  </button>

                  {images.length > 0 ? (
                    <div className="grid gap-3 sm:grid-cols-2">
                      {images.map((image) => (
                        <div
                          key={image.file_id}
                          className="flex items-center gap-3 rounded-[1.15rem] border border-white/70 bg-white/78 px-3 py-3 shadow-[0_10px_24px_rgba(26,54,78,0.06)]"
                        >
                          <div className="h-16 w-16 shrink-0 overflow-hidden rounded-xl border bg-muted/30">
                            {resolveApiUrl(image.public_url) ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={resolveApiUrl(image.public_url) ?? ''}
                                alt={image.filename}
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
                                无预览
                              </div>
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium text-foreground">{image.filename}</p>
                            <p className="text-xs text-muted-foreground">
                              {image.mime_type} · {(image.size / 1024).toFixed(1)} KB
                            </p>
                            <p className="truncate text-[11px] text-muted-foreground/80">{image.file_id}</p>
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-9 w-9 shrink-0"
                            onClick={() => void handleRemoveImage(image.file_id)}
                            disabled={isUploading || isLoading}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground">
                      尚未上传图片。你可以直接进行文本分析，也可以补充多张图片一起进入多模态核查。
                    </div>
                  )}
                </div>

                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-sm text-muted-foreground">
                    文本、图片可组合输入；没有文本时，也支持纯图片启动分析。
                  </div>
                  <Button
                    size="lg"
                    onClick={handleRun}
                    disabled={isLoading || isUploading || (!text.trim() && images.length === 0)}
                    className="sm:min-w-52"
                  >
                    {isLoading ? '分析中...' : '开始分析'}
                  </Button>
                </div>
              </TabsContent>

              <TabsContent value="url" className="space-y-5 pt-5">
                <div className="space-y-3 rounded-[1.35rem] border border-white/70 bg-white/76 p-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
                  <Input
                    type="url"
                    placeholder="请输入新闻或网页链接（http://...）"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    className="h-12 rounded-xl border-white/60 bg-white text-base"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleCrawl();
                    }}
                  />
                  <p className="text-xs leading-6 text-muted-foreground">
                    系统会自动抓取网页正文、标题、发布日期等关键信息，再进入分析流水线。
                  </p>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-sm text-muted-foreground">
                    适合核查新闻链接、公众号文章或其他已发布页面。
                  </div>
                  <Button
                    size="lg"
                    onClick={handleCrawl}
                    disabled={isLoading || !url.trim()}
                    className="sm:min-w-52"
                  >
                    {isLoading ? '抓取中...' : '抓取并核查'}
                  </Button>
                </div>
              </TabsContent>
            </Tabs>

            {error ? (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            {restorableTaskId && restoreDisabled ? (
              <div className="flex flex-col items-start gap-3 rounded-[1.25rem] border border-white/60 bg-white/72 px-4 py-3 text-sm text-muted-foreground shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
                <div>
                  已关闭自动恢复提示（本次会话内生效）。
                  {restorableUpdatedAt ? ` 可恢复任务更新时间：${restorableUpdatedAt}` : ''}
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    try {
                      sessionStorage.removeItem('truthcast_restore_disabled');
                    } catch {
                      // ignore
                    }
                    setRestoreDisabled(false);
                    void hydrateFromLatest({ taskId: restorableTaskId, force: true });
                  }}
                >
                  恢复上一次分析
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <PageSection
            title="五大智能体角色"
            description="TruthCast 不是单点工具，而是一套由五个智能体协同驱动的事实核查与传播响应系统。它从输入信号出发，完成侦测、考据、裁决、推演与响应的闭环。"
          >
            <div className="space-y-4">
              <div className="rounded-[1.5rem] bg-[linear-gradient(160deg,rgba(255,255,255,0.95),rgba(244,249,252,0.92))] p-6 shadow-[0_18px_36px_rgba(24,53,76,0.18)]">
                <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:items-start">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--muted-strong)]">
                      智能体编队
                    </div>
                    <div className="mt-2 text-xl font-semibold text-foreground">
                      从输入信号到行动输出的协同链
                    </div>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      当一条信息进入系统，真正启动的不是单一模型，而是一支协同工作的智能体编队。侦测者负责发现异常，考据者负责追索依据，裁决者负责形成判断，推演者负责预见传播，响应者负责组织对外表达。
                    </p>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                      它们共同把“看到一条消息”推进为“完成一次研判”，把事实核查、传播推演与公关响应连成一条可执行链路。
                    </p>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
                    <div className="rounded-[1.2rem] border border-white/70 bg-white/72 px-4 py-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
                      <div className="flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-primary" />
                        <span className="text-sm font-medium text-foreground">异常先被发现</span>
                      </div>
                    </div>
                    <div className="rounded-[1.2rem] border border-white/70 bg-white/72 px-4 py-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
                      <div className="flex items-center gap-2">
                        <Layers3 className="h-4 w-4 text-primary" />
                        <span className="text-sm font-medium text-foreground">证据、结论与传播走势被统一串联</span>
                      </div>
                    </div>
                    <div className="rounded-[1.2rem] border border-white/70 bg-white/72 px-4 py-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
                      <div className="flex items-center gap-2">
                        <Radar className="h-4 w-4 text-primary" />
                        <span className="text-sm font-medium text-foreground">最终输出直达公关响应与行动执行</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
                {roleStories.map((role) => (
                  <div
                    key={role.title}
                    className="rounded-[1.35rem] border border-white/65 bg-white/76 p-5 shadow-[0_10px_24px_rgba(26,54,78,0.08)]"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.16em] text-[color:var(--muted-strong)]">
                        <role.icon className="h-4 w-4 text-primary" />
                        {role.accent}
                      </div>
                      <div className="text-xs text-muted-foreground">智能体角色</div>
                    </div>
                    <div className="mt-3 text-base font-medium text-foreground">{role.title}</div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">{role.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </PageSection>

          <PageSection
            title="核心能力"
            // description="沿用现有后端闭环能力，但在首页先用更容易理解的方式说明出来。"
            muted
          >
            <div className="grid gap-3">
              {capabilityCards.map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.title}
                    className="flex items-start gap-3 rounded-[1.35rem] border border-white/60 bg-white/74 p-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]"
                  >
                    <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-foreground">{item.title}</div>
                      <p className="text-sm leading-6 text-muted-foreground">{item.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </PageSection>
        </div>
      </div>
    </div>
  );
}
