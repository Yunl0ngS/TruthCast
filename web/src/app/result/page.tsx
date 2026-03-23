'use client';

import { useMemo, useState } from 'react';
import { PageHero, PageSection, ProgressTimeline } from '@/components/layout';
import { RiskOverview, ClaimList, EvidenceChain, ReportCard, ExportButton } from '@/components/features';
import { ErrorBoundary } from '@/components/ui/error-boundary';
import { resolveApiUrl } from '@/services/api';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';
import { CheckCircle2, Layers3, ShieldCheck, Sparkles } from 'lucide-react';

export default function ResultPage() {
  const [showFullInput, setShowFullInput] = useState(false);
  const [preferredClaimId, setPreferredClaimId] = useState<string | null>(null);
  const {
    text,
    detectData,
    images,
    urlComments,
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

  const activeClaimId = useMemo(() => {
    if (claims.length === 0) return null;
    if (preferredClaimId && claims.some((claim) => claim.claim_id === preferredClaimId)) {
      return preferredClaimId;
    }
    return claims[0].claim_id;
  }, [claims, preferredClaimId]);

  const evidenceStats = useMemo(() => {
    const stats: Record<string, { aligned: number; raw: number }> = {};

    for (const claim of claims) {
      const alignedCount = report
        ? (report.claim_reports.find((row) => row.claim.claim_id === claim.claim_id)?.evidences.length ?? 0)
        : evidences.filter((item) => item.claim_id === claim.claim_id).length;
      const rawCount = rawEvidences.filter((item) => item.claim_id === claim.claim_id).length;
      stats[claim.claim_id] = { aligned: alignedCount, raw: rawCount };
    }

    return stats;
  }, [claims, evidences, rawEvidences, report]);

  return (
    <div className="space-y-6 md:space-y-8">
      <PageHero
        eyebrow="Analysis Result"
        title="可信研判结果"
        // description="这一页优先呈现综合判断、关键风险和行动方向，再向下展开主张、证据与补充输入，避免让用户自己在模块里找重点。"
        meta={
          <>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              {allDone ? '分析完成' : '分析进行中'}
            </div>
            {/* <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              先结论，后证据
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
                rememberExpandedKey="timeline_result"
              />
            </div>
            {hasReport ? (
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
            ) : null}
          </>
        }
      />

      {allDone && (
        <div className="flex items-center gap-3 rounded-[1.5rem] border border-primary/20 bg-primary/6 px-4 py-3 text-sm text-primary animate-in fade-in duration-700">
          <CheckCircle2 className="h-5 w-5 shrink-0" />
          <span className="font-medium">分析完成！</span>
          <span className="text-primary/80">全链路核查已结束，请查看下方各模块结果。</span>
        </div>
      )}

      <PageSection
        title="风险速览"
        // description="左侧保留原始输入和图片证据，右侧直接给出风险概览。综合报告下沉到证据链之后，便于先看输入上下文，再看主张和证据。"
        // actions={
        //   <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
        //     <ShieldCheck className="h-3.5 w-3.5 text-primary" />
        //     输入先于结论
        //   </div>
        // }
      >
        <div className="grid gap-4 xl:grid-cols-[1.16fr_0.84fr]">
          <div className="rounded-[1.5rem] border border-white/70 bg-white/76 p-4 shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold text-foreground">输入新闻</h2>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="rounded-xl border border-white/60 bg-white/78 px-3 py-1.5 text-xs font-medium shadow-[0_8px_20px_rgba(26,54,78,0.06)] transition-colors hover:bg-accent"
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
                    className="rounded-xl border border-white/60 bg-white/78 px-3 py-1.5 text-xs font-medium shadow-[0_8px_20px_rgba(26,54,78,0.06)] transition-colors hover:bg-accent"
                    onClick={() => setShowFullInput((prev) => !prev)}
                  >
                    {showFullInput ? '收起' : '展开'}
                  </button>
                )}
              </div>
            </div>

            {hasInputText ? (
              <div className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-[1.25rem] border border-white/60 bg-[color:var(--panel-soft)]/72 px-4 py-3 text-sm text-muted-foreground">
                {inputPreview}
              </div>
            ) : (
              <div className="mt-4 text-sm text-muted-foreground">当前无可展示的输入新闻</div>
            )}

            {images.length > 0 && (
              <div className="mt-5 space-y-3 border-t border-border/60 pt-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-foreground">图片输入</h3>
                  <span className="rounded-full border border-white/60 bg-white/76 px-2.5 py-1 text-xs text-muted-foreground">
                    已上传 {images.length} 张图片
                  </span>
                </div>

                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                  {images.map((image) => (
                    <div
                      key={image.file_id}
                      className="overflow-hidden rounded-[1.15rem] border border-white/65 bg-white/76 shadow-[0_10px_24px_rgba(26,54,78,0.06)]"
                    >
                      <div className="aspect-[16/10] bg-background">
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
                      <div className="space-y-0.5 px-3 py-2.5">
                        <div className="truncate text-xs font-medium text-foreground">{image.filename}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {image.mime_type} · {(image.size / 1024).toFixed(1)} KB
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* {urlComments.length > 0 && (
              <div className="mt-5 space-y-3 border-t border-border/60 pt-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-medium text-foreground">评论抓取</h3>
                  <span className="rounded-full border border-white/60 bg-white/76 px-2.5 py-1 text-xs text-muted-foreground">
                    共抓取 {urlComments.length} 条
                  </span>
                </div>
                <div className="space-y-3">
                  {urlComments.map((comment, index) => (
                    <div
                      key={`${comment.username}-${comment.publish_time}-${index}`}
                      className="rounded-[1.1rem] border border-white/60 bg-[color:var(--panel-soft)]/68 px-4 py-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{comment.username || '匿名用户'}</span>
                        <span>{comment.publish_time || '时间未知'}</span>
                      </div>
                      <div className="mt-2 whitespace-pre-wrap break-words text-sm text-muted-foreground">
                        {comment.content}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )} */}
          </div>
          <ErrorBoundary title="风险概览加载失败">
            <RiskOverview data={detectData} isLoading={phases.detect === 'running'} />
          </ErrorBoundary>
        </div>
      </PageSection>

      <PageSection
        title="主张与证据支撑"
        // description="左侧改为主张导航，右侧仅展示当前主张的证据，并通过内部滚动控制长证据列表，避免右栏过长把整个模块拉得失衡。"
      >
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[0.86fr_1.14fr]">
          <ErrorBoundary title="主张抽取加载失败">
            <ClaimList
              claims={claims}
              isLoading={phases.claims === 'running'}
              activeClaimId={activeClaimId}
              onSelectClaim={setPreferredClaimId}
              evidenceStats={evidenceStats}
            />
          </ErrorBoundary>
          <ErrorBoundary title="证据链加载失败">
            <EvidenceChain
              rawEvidences={rawEvidences}
              evidences={evidences}
              claims={claims}
              report={report}
              isLoading={phases.evidence === 'running'}
              selectedClaimId={activeClaimId}
            />
          </ErrorBoundary>
        </div>
      </PageSection>

      {fusionReport && (
        <PageSection
          title="融合补充结论"
          description="图文交叉判断作为综合报告前的补充材料展示，帮助理解图片输入对整体研判的影响。"
          muted
          actions={
            <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/72 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)]">
              <Layers3 className="h-3.5 w-3.5 text-primary" />
              报告补充层
            </div>
          }
        >
          <div className="relative overflow-hidden rounded-[1.6rem] border border-white/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.78),rgba(241,247,251,0.82))] p-5 shadow-[0_16px_36px_rgba(26,54,78,0.08)]">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(108,157,188,0.14),transparent_34%),radial-gradient(circle_at_bottom_left,rgba(24,53,76,0.08),transparent_28%)]" />
            <div className="relative space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/76 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
                    <Sparkles className="h-3.5 w-3.5 text-primary" />
                    融合结论
                  </div>
                  <h2 className="text-lg font-semibold text-foreground">多模态融合摘要</h2>
                  <p className="text-sm text-muted-foreground">
                    这是综合报告之后的图文交叉判断，用于补充说明图片输入对整体结论的影响。
                  </p>
                </div>
              </div>

              <div className="rounded-[1.3rem] border border-white/70 bg-white/78 p-4 text-sm leading-7 text-slate-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.38)]">
                {fusionReport.fusion_summary}
              </div>

              <div className="flex flex-wrap gap-2">
                <span className="inline-flex items-center rounded-full border border-white/70 bg-white/76 px-3 py-1 text-xs font-medium text-[color:var(--muted-strong)]">
                  一致性：{fusionReport.multimodal_consistency}
                </span>
                <span className="inline-flex items-center rounded-full border border-white/70 bg-white/76 px-3 py-1 text-xs font-medium text-[color:var(--muted-strong)]">
                  图像证据：{fusionReport.image_evidence_status}
                </span>
              </div>
            </div>
          </div>
        </PageSection>
      )}

      <PageSection
        title="综合报告"
        description="把主张与证据看完之后，再回到最终综合判断，适合作为结果页的收束区。"
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <ShieldCheck className="h-3.5 w-3.5 text-primary" />
            最终结论
          </div>
        }
      >
        <ErrorBoundary title="综合报告加载失败">
          <ReportCard report={report} isLoading={phases.report === 'running'} />
        </ErrorBoundary>
      </PageSection>
    </div>
  );
}
