'use client';

import { ProgressTimeline } from '@/components/layout';
import { ExportButton } from '@/components/features';
import { ChatWorkbench } from '@/components/features/chat-workbench';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';

export default function ChatPage() {
  const { text, detectData, claims, evidences, report, simulation, content, phases, retryPhase, interruptPipeline } =
    usePipelineStore();

  const hasReport = report !== null;

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div
      className={
        "flex flex-col gap-4 overflow-hidden " +
        // 让聊天工作台尽量接近满屏：抵消 RootLayout main 的 padding，并用视口高度约束整体
        "-mx-2 sm:-mx-4 -my-4 md:-my-6 px-2 sm:px-4 py-4 md:py-6 " +
        "h-[calc(100dvh-3.5rem)] min-h-0"
      }
    >
      <div className="flex flex-col items-center gap-3 shrink-0">
        <ProgressTimeline
          phases={phases}
          onRetry={handleRetry}
          onAbort={interruptPipeline}
          showRetry={true}
          mobileMode="collapsible"
          rememberExpandedKey="timeline_chat"
        />
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
      </div>

      <div className="flex-1 min-h-0">
        <ChatWorkbench />
      </div>
    </div>
  );
}

