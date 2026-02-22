'use client';

import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { usePipelineStore, useIsLoading } from '@/stores/pipeline-store';
import { FileSearch, AlertCircle } from 'lucide-react';

export default function HomePage() {
  const router = useRouter();
  const { text, error, setText, runPipeline } = usePipelineStore();
  const isLoading = useIsLoading();

  const handleRun = async () => {
    if (!text.trim()) {
      toast.warning('请输入待分析的文本');
      return;
    }
    router.push('/result');
    runPipeline();
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
            输入新闻、帖子或话题文本，系统将分阶段返回风险快照、主张抽取、证据链与综合报告。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="请输入待分析的文本..."
            rows={6}
            className="resize-none text-base"
          />
          
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

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
        </CardContent>
      </Card>
    </div>
  );
}
