'use client';

import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { deleteMultimodalImage, resolveApiUrl, uploadMultimodalImage } from '@/services/api';
import { usePipelineStore, useIsLoading } from '@/stores/pipeline-store';
import type { StoredImage } from '@/types';
import { FileSearch, AlertCircle, Globe, FileText, ImagePlus, Loader2, UploadCloud, X } from 'lucide-react';

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
    <div className="max-w-3xl mx-auto px-4">
      <Card>
        <CardHeader className="text-center">
          <div className="flex justify-center mb-4">
            <FileSearch className="h-10 w-10 md:h-12 md:w-12 text-primary" />
          </div>
          <CardTitle className="text-xl md:text-2xl">TruthCast 智能研判台</CardTitle>
          <CardDescription className="text-sm md:text-base">
            输入新闻文本或网页链接，系统将分阶段返回风险快照、主张抽取、证据链与综合报告。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Tabs defaultValue="text" className="w-full">
            <TabsList className="grid w-full grid-cols-2 mb-4">
              <TabsTrigger value="text" className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                文本分析
              </TabsTrigger>
              <TabsTrigger value="url" className="flex items-center gap-2">
                <Globe className="h-4 w-4" />
                链接核查
              </TabsTrigger>
            </TabsList>
            
            <TabsContent value="text" className="space-y-4">
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="请输入待分析的文本，也可只上传图片进行多模态分析..."
                rows={6}
                className="resize-none text-base"
              />

              <div
                className={[
                  'rounded-xl border border-dashed p-4 space-y-4 transition-colors',
                  isDragActive
                    ? 'border-primary bg-primary/5 shadow-sm'
                    : 'border-border bg-muted/30 hover:bg-muted/40',
                ].join(' ')}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <ImagePlus className="h-4 w-4 text-primary" />
                      图片上传（多模态分析）
                    </div>
                    <p className="text-xs text-muted-foreground">
                      支持先上传图片，再与文本一起触发多模态检测；当前版本将图片 OCR 与语义摘要接入分析链路。
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {images.length > 0 && (
                      <Button type="button" variant="ghost" size="sm" onClick={handleClearImages} disabled={isUploading || isLoading}>
                        清空图片
                      </Button>
                    )}
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
                      <span className="inline-flex items-center justify-center rounded-md border bg-background px-3 py-2 text-sm font-medium shadow-xs cursor-pointer hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50">
                        {isUploading ? (
                          <span className="inline-flex items-center gap-2">
                            <Loader2 className="h-4 w-4 animate-spin" /> 上传中...
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
                    'group w-full rounded-xl border border-dashed px-4 py-6 text-left transition-colors',
                    isDragActive
                      ? 'border-primary bg-primary/10'
                      : 'border-border/80 bg-background/80 hover:border-primary/60 hover:bg-background',
                  ].join(' ')}
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploading || isLoading}
                >
                  <div className="flex flex-col items-center justify-center gap-3 text-center">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full border bg-background shadow-sm">
                      {isUploading ? <Loader2 className="h-5 w-5 animate-spin text-primary" /> : <UploadCloud className="h-5 w-5 text-primary" />}
                    </div>
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-foreground">
                        {isDragActive ? '松开鼠标即可上传图片' : '点击选择图片，或将图片拖拽到此处'}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        支持多张图片；上传后会自动接入 OCR 与多模态分析链路。
                      </div>
                    </div>
                  </div>
                </button>

                {images.length > 0 ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {images.map((image) => (
                      <div
                        key={image.file_id}
                        className="flex items-center gap-3 rounded-lg border bg-background px-3 py-3"
                      >
                        <div className="h-16 w-16 shrink-0 overflow-hidden rounded-md border bg-muted/30">
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
                          className="h-8 w-8 shrink-0"
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
                    尚未上传图片。可直接文本分析，也可上传 1~N 张图片触发多模态 detect。
                  </div>
                )}
              </div>

              <div className="flex justify-center">
                <Button
                  size="lg"
                  onClick={handleRun}
                  disabled={isLoading || isUploading || (!text.trim() && images.length === 0)}
                  className="w-full sm:w-auto sm:min-w-48"
                >
                  {isLoading ? '分析中...' : '开始分析'}
                </Button>
              </div>
            </TabsContent>
            
            <TabsContent value="url" className="space-y-4">
              <div className="space-y-2">
                <Input
                  type="url"
                  placeholder="请输入新闻或网页链接 (http://...)"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  className="text-base h-12"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCrawl();
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  系统将自动抓取网页正文、发布日期等关键信息并进入分析流水线。
                </p>
              </div>
              <div className="flex justify-center">
                <Button
                  size="lg"
                  onClick={handleCrawl}
                  disabled={isLoading || !url.trim()}
                  className="w-full sm:w-auto sm:min-w-48"
                  variant="default"
                >
                  {isLoading ? '抓取中...' : '抓取并核查'}
                </Button>
              </div>
            </TabsContent>
          </Tabs>
          
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {restorableTaskId && restoreDisabled && (
            <div className="pt-2 flex flex-col items-center gap-2 text-sm text-muted-foreground">
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}
