'use client';

import { PageHero, PageSection, ProgressTimeline } from '@/components/layout';
import { ExportButton } from '@/components/features';
import { ChatWorkbench } from '@/components/features/chat-workbench';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';
import { MessageSquareMore } from 'lucide-react';

export default function ChatPage() {
  const { text, detectData, claims, evidences, report, simulation, content, phases, retryPhase, interruptPipeline } =
    usePipelineStore();

  const hasReport = report !== null;

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div className="flex min-h-0 flex-col gap-6 md:gap-8 lg:h-[calc(100dvh-7rem)] lg:overflow-hidden">
      <PageHero
        eyebrow="Chat Workbench"
        title="对话工作台"
        // description="围绕当前分析任务继续追问、比较、深挖和生成补充解释。这里保持聊天感，但整体仍属于同一套决策工作台。"
        meta={
          <>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              会话式追问
            </div>
            <div className="rounded-full border border-[color:var(--border-strong)] bg-white/70 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
              基于当前任务上下文
            </div>
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
                rememberExpandedKey="timeline_chat"
              />
            </div>
            {hasReport && (
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
            )}
          </>
        }
      />

      <PageSection
        title="会话主界面"
        actions={
          <div className="inline-flex items-center gap-2 rounded-full border border-white/60 bg-white/74 px-3 py-1.5 text-xs font-medium text-[color:var(--muted-strong)] shadow-[0_10px_24px_rgba(26,54,78,0.06)]">
            <MessageSquareMore className="h-3.5 w-3.5 text-primary" />
            会话工作流
          </div>
        }
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
        contentClassName="min-h-0 flex-1 overflow-hidden"
      >
        <div className="h-full min-h-0 flex-1 overflow-hidden">
          <ChatWorkbench />
        </div>
      </PageSection>
    </div>
  );
}
