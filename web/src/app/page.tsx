'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePipelineStore, useIsLoading } from '@/stores/pipeline-store';
import { FileSearch, AlertCircle, Globe, FileText } from 'lucide-react';

export default function HomePage() {
  const router = useRouter();
  const {
    text,
    error,
    setText,
    runPipeline,
    crawlUrl,
    restorableTaskId,
    restorableUpdatedAt,
    hydrateFromLatest,
  } = usePipelineStore();
  const isLoading = useIsLoading();

  const [url, setUrl] = useState('');
  const [restoreDisabled, setRestoreDisabled] = useState(false);
  
  useEffect(() => {
    try {
      setRestoreDisabled(sessionStorage.getItem('truthcast_restore_disabled') === '1');
    } catch {
      setRestoreDisabled(false);
    }
  }, []);

  const handleRun = async () => {
    if (!text.trim()) {
      toast.warning('请输入待分析的文本');
      return;
    }
    router.push('/result');
    runPipeline();
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
                placeholder="请输入待分析的文本..."
                rows={6}
                className="resize-none text-base"
              />
              <div className="flex justify-center">
                <Button
                  size="lg"
                  onClick={handleRun}
                  disabled={isLoading || !text.trim()}
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
