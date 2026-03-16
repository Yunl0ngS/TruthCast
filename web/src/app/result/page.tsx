'use client';

import { useState } from 'react';
import { ProgressTimeline } from '@/components/layout';
import { RiskOverview, ClaimList, EvidenceChain, ReportCard, ExportButton } from '@/components/features';
import { ErrorBoundary } from '@/components/ui/error-boundary';
import { resolveApiUrl } from '@/services/api';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';
import { CheckCircle2 } from 'lucide-react';

export default function ResultPage() {
  const [showFullInput, setShowFullInput] = useState(false);
  const {
    text,
    enhancedText,
    detectData,
    images,
    ocrResults,
    fusionReport,
    claims,
    rawEvidences,
    evidences,
    report,
    simulation,
    content,
    phases,
    retryPhase,
    interruptPipeline,
  } = usePipelineStore();

  const hasReport = report !== null;
  const hasInputText = text.trim().length > 0;
  const shouldClampInput = text.length > 800;
  const inputPreview = showFullInput || !shouldClampInput ? text : `${text.slice(0, 800)}...`;
  const allDone =
    phases.detect === 'done' &&
    phases.claims === 'done' &&
    phases.evidence === 'done' &&
    phases.report === 'done';

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div className="space-y-6 px-2 md:px-0">
      {/* 进度时间线 + 导出按钮 */}
      <div className="flex flex-col items-center gap-4">
        <ProgressTimeline
          phases={phases}
          onRetry={handleRetry}
          onAbort={interruptPipeline}
          showRetry={true}
          mobileMode="collapsible"
          rememberExpandedKey="timeline_result"
        />
        <div className="w-full space-y-3">
          {hasReport && (
            <div className="flex justify-center">
              <ExportButton
                data={{
                  inputText: text,
                  detectData,
                  claims,
                  evidences,
                  report,
                  simulation,
                  content: content ?? null,
                  exportedAt: new Date().toLocaleString('zh-CN'),
                }}
              />
            </div>
          )}

          <div className="rounded-lg border bg-background p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h1 className="font-semibold text-foreground">输入新闻原文</h1>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="text-xs px-2 py-1 rounded border hover:bg-muted"
                  onClick={async () => {
                    if (!hasInputText) return;
                    try {
                      await navigator.clipboard.writeText(text);
                    } catch {
                      // ignore
                    }
                  }}
                  disabled={!hasInputText}
                >
                  复制原文
                </button>
                {shouldClampInput && (
                  <button
                    type="button"
                    className="text-xs px-2 py-1 rounded border hover:bg-muted"
                    onClick={() => setShowFullInput((prev) => !prev)}
                  >
                    {showFullInput ? '收起' : '展开'}
                  </button>
                )}
              </div>
            </div>

            {hasInputText ? (
              <div className="text-sm whitespace-pre-wrap break-words text-muted-foreground max-h-72 overflow-auto">
                {inputPreview}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">当前无可展示的输入新闻</div>
            )}
          </div>

          {(images.length > 0 || fusionReport || ocrResults.length > 0) && (
            <div className="rounded-lg border bg-background p-4 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold text-foreground">多模态输入摘要</h2>
                {images.length > 0 && (
                  <span className="text-xs rounded-full border px-2 py-1 text-muted-foreground">
                    已上传 {images.length} 张图片
                  </span>
                )}
              </div>

              {images.length > 0 && (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {images.map((image) => (
                    <div key={image.file_id} className="overflow-hidden rounded-md border bg-muted/30">
                      <div className="aspect-[4/3] bg-background">
                        {resolveApiUrl(image.public_url) ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={resolveApiUrl(image.public_url) ?? ''}
                            alt={image.filename}
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
                            无法预览
                          </div>
                        )}
                      </div>
                      <div className="space-y-1 px-3 py-2">
                        <div className="text-sm font-medium text-foreground truncate">{image.filename}</div>
                        <div className="text-xs text-muted-foreground">
                          {image.mime_type} · {(image.size / 1024).toFixed(1)} KB
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {enhancedText && enhancedText !== text && (
                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground">增强文本摘要</div>
                  <div className="text-sm whitespace-pre-wrap break-words text-muted-foreground rounded-md bg-muted/30 p-3 max-h-48 overflow-auto">
                    {enhancedText}
                  </div>
                </div>
              )}

              {ocrResults.length > 0 && (
                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground">OCR 提字结果</div>
                  <div className="space-y-2">
                    {ocrResults.map((item, index) => (
                      <div key={`${item.file_id ?? index}_ocr`} className="rounded-md border bg-muted/20 px-3 py-2 text-sm">
                        <div className="font-medium text-foreground">{item.file_id ?? `图片${index + 1}`}</div>
                        <div className="text-muted-foreground whitespace-pre-wrap break-words">{item.ocr_text}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {fusionReport && (
                <div className="space-y-2 rounded-md border bg-muted/20 p-3">
                  <div className="text-sm font-medium text-foreground">多模态融合摘要</div>
                  <div className="text-sm text-muted-foreground">{fusionReport.fusion_summary}</div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span className="rounded-full border px-2 py-1">一致性：{fusionReport.multimodal_consistency}</span>
                    <span className="rounded-full border px-2 py-1">图像证据：{fusionReport.image_evidence_status}</span>
                    <span className="rounded-full border px-2 py-1">建议直接进入预演：{fusionReport.should_simulate ? '是' : '否'}</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 分析完成庆祝 banner */}
      {allDone && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-green-50 border border-green-200 text-green-800 text-sm animate-in fade-in duration-700">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-green-600" />
          <span className="font-medium">分析完成！</span>
          <span className="text-green-700">全链路核查已结束，请查看下方各模块结果。</span>
        </div>
      )}

      {/* 风险概览 + 主张抽取 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
        <ErrorBoundary title="风险概览加载失败">
          <RiskOverview data={detectData} isLoading={phases.detect === 'running'} />
        </ErrorBoundary>
        <ErrorBoundary title="主张抽取加载失败">
          <ClaimList claims={claims} isLoading={phases.claims === 'running'} />
        </ErrorBoundary>
      </div>

      {/* 证据链 */}
      <ErrorBoundary title="证据链加载失败">
        <EvidenceChain
          rawEvidences={rawEvidences}
          evidences={evidences}
          claims={claims}
          report={report}
          isLoading={phases.evidence === 'running'}
        />
      </ErrorBoundary>

      {/* 综合报告 */}
      <ErrorBoundary title="综合报告加载失败">
        <ReportCard report={report} isLoading={phases.report === 'running'} />
      </ErrorBoundary>
    </div>
  );
}
