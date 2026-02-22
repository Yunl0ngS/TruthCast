'use client';

import { useEffect, useMemo, useRef } from 'react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { MessageList } from '@/components/features/chat-workbench/message-list';
import { Composer } from '@/components/features/chat-workbench/composer';
import { ContextPanel } from '@/components/features/chat-workbench/context-panel';
import { useChatStore } from '@/stores/chat-store';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';
import { chatStream, getHistoryDetail } from '@/services/api';

function parseRetryPhase(text: string): Phase | null {
  const phase = text.trim().toLowerCase();
  const allowed: Phase[] = ['detect', 'claims', 'evidence', 'report', 'simulation', 'content'];
  return (allowed as string[]).includes(phase) ? (phase as Phase) : null;
}

function parseLoadHistoryRecordId(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith('/load_history')) return null;
  const parts = trimmed.split(/\s+/);
  if (parts.length < 2) return '';
  return parts[1];
}

export function ChatWorkbench() {
  const {
    session_id,
    setSessionId,
    messages,
    is_streaming,
    setStreaming,
    addMessage,
    updateMessage,
    appendToMessage,
  } = useChatStore();
  const {
    text,
    setText,
    runPipeline,
    interruptPipeline,
    retryFailed,
    retryPhase,
    phases,
    loadFromHistory,
    detectData,
    claims,
    evidences,
    report,
    simulation,
    content,
    recordId,
  } = usePipelineStore();

  const isPipelineRunning = useMemo(
    () => Object.values(phases).some((s) => s === 'running'),
    [phases]
  );

  // 将 pipeline 各阶段产物“回灌”到对话区：当阶段从 running -> done/failed 时追加一条 assistant 消息。
  // 注意：pipeline-store 负责模块化结果；chat-store 不会自动订阅，因此需要在 UI 层桥接。
  const prevPhasesRef = useRef(phases);
  useEffect(() => {
    const prev = prevPhasesRef.current;

    const emit = (phase: Phase, status: string) => {
      // 只在阶段完成或失败时提示，避免 idle/running 噪音
      if (status !== 'done' && status !== 'failed') return;
      if (prev[phase] === status) return;

      if (status === 'failed') {
        addMessage('assistant', `阶段失败：${phase}`);
        return;
      }

      switch (phase) {
        case 'detect': {
          const label = detectData?.label ?? '未知';
          const score = detectData?.score ?? 'N/A';
          addMessage('assistant', `风险快照完成：${label}（score=${score}）`, {
            actions: [{ type: 'link', label: '打开检测结果', href: '/result' }],
          });
          return;
        }
        case 'claims': {
          addMessage('assistant', `主张抽取完成：共 ${claims.length} 条。`, {
            actions: [{ type: 'link', label: '打开检测结果', href: '/result' }],
          });
          return;
        }
        case 'evidence': {
          addMessage('assistant', `证据处理完成：对齐后证据共 ${evidences.length} 条。`, {
            actions: [{ type: 'link', label: '打开检测结果', href: '/result' }],
          });
          return;
        }
        case 'report': {
          const risk = report?.risk_label ?? '未知';
          const score = report?.risk_score ?? 'N/A';
          addMessage('assistant', `综合报告完成：${risk}（score=${score}）。`, {
            actions: [
              { type: 'link', label: '打开检测结果', href: '/result' },
              ...(recordId ? [{ type: 'command', label: '加载本次记录到上下文', command: `/load_history ${recordId}` } as const] : []),
            ],
          });
          return;
        }
        case 'simulation': {
          addMessage('assistant', '舆情预演完成（已生成情绪/立场/叙事/引爆点/建议）。', {
            actions: [{ type: 'link', label: '打开舆情预演', href: '/simulation' }],
          });
          return;
        }
        case 'content': {
          addMessage('assistant', '应对内容生成完成。', {
            actions: [{ type: 'link', label: '打开应对内容', href: '/content' }],
          });
          return;
        }
      }
    };

    (Object.keys(phases) as Phase[]).forEach((p) => emit(p, phases[p]));
    prevPhasesRef.current = phases;
  }, [
    addMessage,
    claims.length,
    detectData?.label,
    detectData?.score,
    evidences.length,
    phases,
    recordId,
    report?.risk_label,
    report?.risk_score,
  ]);

  const quickActions = useMemo(
    () => [
      {
        label: '开始分析',
        onClick: () => {
          if (!text.trim()) {
            toast.warning('请先在输入框填入待分析文本，或在下方对话框输入文本');
            return;
          }
          // 不跳转到 /result：保留用户在“对话工作台”中观察阶段产出（phase 完成后会回灌到对话区）。
          addMessage('assistant', '已开始分析（复用现有流水线）。阶段完成后会在此对话区追加摘要；也可随时打开结果页查看模块化结果。', {
            actions: [{ type: 'link', label: '打开检测结果', href: '/result' }],
          });
          runPipeline();
        },
      },
      ...(isPipelineRunning
        ? [
            {
              label: '中断分析',
              onClick: () => {
                addMessage('assistant', '正在中断分析…');
                interruptPipeline();
              },
            },
          ]
        : []),
      {
        label: '重试失败阶段',
        onClick: () => {
          addMessage('assistant', '正在重试失败阶段。');
          retryFailed();
        },
      },
    ],
    [addMessage, interruptPipeline, isPipelineRunning, retryFailed, runPipeline, text]
  );

  const runCommand = async (command: string) => {
    await onSend(command);
  };

  const onSend = async (input: string) => {
    addMessage('user', input);

    // 0) /load_history <record_id>
    const recordId = parseLoadHistoryRecordId(input);
    if (recordId !== null) {
      if (!recordId) {
        addMessage('assistant', '用法：/load_history <record_id>');
        return;
      }
      addMessage('assistant', `正在从历史记录加载：${recordId}`);
      try {
        const detail = await getHistoryDetail(recordId);
        loadFromHistory(detail);
        addMessage('assistant', '已加载到前端上下文，可直接打开结果页查看。', {
          actions: [{ type: 'link', label: '打开检测结果', href: '/result' }],
        });
      } catch (err) {
        addMessage(
          'assistant',
          `加载历史记录失败：${err instanceof Error ? err.message : '未知错误'}`
        );
      }
      return;
    }

    // 1) /analyze <text>
    if (input.startsWith('/analyze')) {
      const payload = input.replace('/analyze', '').trim();
      if (!payload) {
        addMessage('assistant', '用法：/analyze <待分析文本>');
        return;
      }
      setText(payload);
      addMessage('assistant', '已收到文本，开始分析。');
      runPipeline();
      return;
    }

    // 2) /retry_failed
    if (input.trim() === '/retry_failed') {
      addMessage('assistant', '正在重试失败阶段。');
      retryFailed();
      return;
    }

    // 3) /retry <phase>
    if (input.startsWith('/retry ')) {
      const phaseText = input.replace('/retry', '').trim();
      const phase = parseRetryPhase(phaseText);
      if (!phase) {
        addMessage('assistant', '用法：/retry <phase>，例如 /retry report。可选：detect claims evidence report simulation content');
        return;
      }
      addMessage('assistant', `正在重试阶段：${phase}`);
      retryPhase(phase);
      return;
    }

    // 4) 默认：如果是长文本，直接当做待分析输入
    if (input.length >= 20) {
      setText(input);
      addMessage('assistant', '检测到你输入的是待分析文本，已自动启动分析。');
      runPipeline();
      return;
    }

    // 5) 其它短输入：走后端 /chat（V0 占位编排），返回 actions 与 references
    try {
      setStreaming(true);
      const assistantMsgId = addMessage('assistant', '');

      await chatStream(
        {
          session_id,
          text: input,
          context: {
            phases,
          },
        },
        (event) => {
          if (event?.data?.session_id) {
            setSessionId(event.data.session_id);
          }

          if (event.type === 'token') {
            appendToMessage(assistantMsgId, event.data.content);
            return;
          }

          if (event.type === 'message') {
            updateMessage(assistantMsgId, {
              content: event.data.message.content,
              actions: event.data.message.actions,
              references: event.data.message.references,
            });
            return;
          }

          if (event.type === 'error') {
            updateMessage(assistantMsgId, {
              content: `后端对话流式返回错误：${event.data.message}`,
            });
            return;
          }
        }
      );
    } catch (err) {
      addMessage(
        'assistant',
        `后端对话编排调用失败：${err instanceof Error ? err.message : '未知错误'}\n\n你仍可使用 /analyze 或直接粘贴长文本触发分析。`
      );
    } finally {
      setStreaming(false);
    }
  };

  const ChatCard = (
    <Card className="flex flex-col h-full min-h-0 py-4 gap-1">
      <CardHeader className="pb-0 shrink-0 px-4">
        <CardTitle className="text-base">对话工作台</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col flex-1 min-h-0 gap-1 px-4">
        {/* 消息列表：内部滚动，避免撑开页面 */}
        <div className="flex-1 min-h-0 overflow-y-auto pr-1">
          <MessageList messages={messages} onCommand={runCommand} />
        </div>

        {/* 输入框固定在底部，不随消息滚动 */}
        <div className="shrink-0">
          <Composer
            onSend={onSend}
            disabled={is_streaming}
            quickActions={quickActions}
            placeholder="输入待分析文本，或输入命令：/analyze <文本>"
          />
        </div>
      </CardContent>
    </Card>
  );

  const ContextCard = (
    <Card className="flex flex-col h-full min-h-0 py-4 gap-4">
      <CardHeader className="pb-2 shrink-0 px-4">
        <CardTitle className="text-base">上下文</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col flex-1 min-h-0 gap-3 overflow-y-auto pr-1 px-4">
        <div className="text-sm text-muted-foreground space-y-1">
          <div>风险快照：{phases.detect}</div>
          <div>主张抽取：{phases.claims}</div>
          <div>证据处理：{phases.evidence}</div>
          <div>综合报告：{phases.report}</div>
          <div>舆情预演：{phases.simulation}</div>
          <div>应对内容：{phases.content}</div>
        </div>
        <ContextPanel
          detectData={detectData}
          report={report}
          simulation={simulation}
          content={content}
        />
      </CardContent>
    </Card>
  );

  return (
    <>
      {/* Mobile */}
      <div className="lg:hidden h-full min-h-0">
        <Tabs defaultValue="chat" className="h-full min-h-0 overflow-hidden">
          <TabsList className="w-full shrink-0">
            <TabsTrigger value="chat" className="flex-1">
              对话
            </TabsTrigger>
            <TabsTrigger value="context" className="flex-1">
              上下文
            </TabsTrigger>
          </TabsList>
          <TabsContent value="chat" className="min-h-0">
            <div className="h-full min-h-0">{ChatCard}</div>
          </TabsContent>
          <TabsContent value="context" className="min-h-0">
            <div className="h-full min-h-0">{ContextCard}</div>
          </TabsContent>
        </Tabs>
      </div>

      {/* Desktop */}
      <div className="hidden lg:flex gap-3 h-full min-h-0">
        <div className="flex-[2] min-h-0">{ChatCard}</div>
        <div className="flex-[1] min-h-0">{ContextCard}</div>
      </div>
    </>
  );
}

