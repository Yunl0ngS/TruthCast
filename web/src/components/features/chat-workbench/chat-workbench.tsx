'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { MessageList } from '@/components/features/chat-workbench/message-list';
import { Composer } from '@/components/features/chat-workbench/composer';
import { ContextPanel } from '@/components/features/chat-workbench/context-panel';
import { ActivePhaseProgressCard } from '@/components/features/chat-workbench/pipeline-result-card';
import { useChatStore } from '@/stores/chat-store';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';
import { Maximize2, Minimize2 } from 'lucide-react';
import {
  chatSessionStream,
  chatStream,
  createChatSession,
  getChatSessionDetail,
  listChatSessions,
  getHistoryDetail,
} from '@/services/api';

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
    setMessages,
    boundRecordId,
    setBoundRecordId,
  } = useChatStore();
  const {
    taskId,
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
    rawEvidences,
    evidences,
    report,
    simulation,
    simulationStage,
    simulationStageAt,
    content,
    recordId,
    error,
    setTaskId,
    hydrateFromLatest,
    reset,
  } = usePipelineStore();

  const stageMsgDedupRef = useRef<string | null>(null);
  const prevStageAtRef = useRef<number | null>(null);
  useEffect(() => {
    if (!simulationStage) return;
    const atIso = simulationStageAt ?? new Date().toISOString();
    const dedupKey = `${taskId ?? ''}_${simulationStage}_${atIso}`;
    if (stageMsgDedupRef.current === dedupKey) return;
    stageMsgDedupRef.current = dedupKey;

    const atMs = Number.isFinite(Date.parse(atIso)) ? Date.parse(atIso) : Date.now();
    const prevAt = prevStageAtRef.current;
    const durationMs = prevAt ? Math.max(0, atMs - prevAt) : null;
    prevStageAtRef.current = atMs;

    const stageLabel: Record<string, string> = {
      emotion: '情绪与立场分析',
      narratives: '叙事分支生成',
      flashpoints: '引爆点识别',
      suggestion: '应对建议生成',
    };

    const partial = (() => {
      if (!simulation) return null;
      if (simulationStage === 'emotion') {
        return {
          emotion_distribution: simulation.emotion_distribution,
          stance_distribution: simulation.stance_distribution,
          emotion_drivers: simulation.emotion_drivers,
          stance_drivers: simulation.stance_drivers,
        };
      }
      if (simulationStage === 'narratives') {
        return { narratives: simulation.narratives };
      }
      if (simulationStage === 'flashpoints') {
        return { flashpoints: simulation.flashpoints, timeline: simulation.timeline };
      }
      if (simulationStage === 'suggestion') {
        return { suggestion: simulation.suggestion };
      }
      return simulation;
    })();

    const id = addMessage('assistant', `${stageLabel[simulationStage] ?? simulationStage} 已完成（结果卡片如下）`);
    updateMessage(id, {
      meta: {
        type: 'simulation_stage',
        status: 'done',
        taskId: taskId ?? null,
        createdAt: atIso,
        stage: simulationStage,
        durationMs,
        simulation: partial,
      },
      actions: [{ type: 'link', label: '打开舆情预演', href: '/simulation' }],
    });
  }, [addMessage, simulation, simulationStage, simulationStageAt, taskId, updateMessage]);

  const isPipelineRunning = useMemo(
    () => Object.values(phases).some((s) => s === 'running'),
    [phases]
  );

  // ====== 网页全屏（沉浸式工作区） ======
  const [isFullscreen, setIsFullscreen] = useState(false);
  const prevBodyOverflowRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isFullscreen) return;
    try {
      prevBodyOverflowRef.current = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
    } catch {
      // ignore
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);

    return () => {
      window.removeEventListener('keydown', onKeyDown);
      try {
        document.body.style.overflow = prevBodyOverflowRef.current ?? '';
      } catch {
        // ignore
      }
    };
  }, [isFullscreen]);

  const PHASE_ORDER: Phase[] = ['detect', 'claims', 'evidence', 'report', 'simulation', 'content'];
  const activePhase = useMemo(() => {
    for (const p of PHASE_ORDER) {
      if (phases[p] === 'running') return p;
    }
    for (const p of PHASE_ORDER) {
      if (phases[p] === 'failed') return p;
    }
    for (const p of PHASE_ORDER) {
      if (phases[p] === 'canceled') return p;
    }
    return null;
  }, [phases]);

  const [lastEvent, setLastEvent] = useState<string | null>(null);

  // ====== 消息列表滚动控制（Chat Workbench V2） ======
  // 滚动容器 ref：对应消息列表外层可滚动 div
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  // 底部哨兵：用于 scrollIntoView
  const bottomSentinelRef = useRef<HTMLDivElement | null>(null);

  // “接近底部”阈值（px）：距离底部 <= threshold 视为用户在底部附近
  const NEAR_BOTTOM_THRESHOLD_PX = 120;

  // 跟随滚动开关：用户上滑浏览历史时关闭；回到底部/点击提示后开启
  const [isFollowing, setIsFollowing] = useState(true);
  const isFollowingRef = useRef(true);

  // 新消息提示：用户不在底部时，新的 token/message 到来显示“有新消息”按钮
  const [hasNewMessages, setHasNewMessages] = useState(false);

  // 记录最近一次滚动位置是否“接近底部”
  const isNearBottomRef = useRef(true);

  // 避免 token 追加时频繁触发多次 scroll：用 rAF 合并
  const scrollRafRef = useRef<number | null>(null);

  const computeDistanceToBottom = () => {
    const el = scrollContainerRef.current;
    if (!el) return 0;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    return Math.max(0, distance);
  };

  const scheduleScrollToBottom = (behavior: ScrollBehavior) => {
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = window.requestAnimationFrame(() => {
      scrollRafRef.current = null;
      // DOM 渲染完成后再滚动；优先使用 bottom sentinel
      if (bottomSentinelRef.current) {
        bottomSentinelRef.current.scrollIntoView({ behavior, block: 'end' });
        return;
      }
      const el = scrollContainerRef.current;
      if (el) {
        el.scrollTo({ top: el.scrollHeight, behavior });
      }
    });
  };

  const enableFollowingAndScrollBottom = (behavior: ScrollBehavior) => {
    setIsFollowing(true);
    isFollowingRef.current = true;
    setHasNewMessages(false);
    isNearBottomRef.current = true;
    scheduleScrollToBottom(behavior);
  };

  // 1) 首次进入页面 / 切换会话：默认定位到最新消息（底部），并重置状态
  useEffect(() => {
    setHasNewMessages(false);
    setIsFollowing(true);
    isFollowingRef.current = true;
    isNearBottomRef.current = true;
    // 使用 auto 避免切换会话时出现明显跳动
    scheduleScrollToBottom('auto');

    return () => {
      if (scrollRafRef.current !== null) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session_id]);

  // 2) 新消息到达时：
  // - 若用户在底部/接近底部（且处于跟随模式），平滑滚动到最新
  // - 若用户已上滑，则不强制滚动，展示“有新消息”提示
  useLayoutEffect(() => {
    // messages 数组引用变化即代表新增/更新（包括 token 追加导致 content 变化）
    const distance = computeDistanceToBottom();
    const nearBottom = distance <= NEAR_BOTTOM_THRESHOLD_PX;
    isNearBottomRef.current = nearBottom;

    if (isFollowingRef.current && nearBottom) {
      scheduleScrollToBottom('smooth');
      return;
    }

    // 用户不在底部：只提示，不强制滚动
    if (!nearBottom) {
      setHasNewMessages(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages]);

// V2：优先创建后端会话（独立会话DB）。失败时不阻塞：仍可回退到旧 /chat/stream。
  const bootstrappedSessionRef = useRef(false);
  useEffect(() => {
    if (bootstrappedSessionRef.current) return;
    bootstrappedSessionRef.current = true;

    createChatSession()
      .then((s) => {
        if (s?.session_id) {
          setSessionId(s.session_id);
          // 约定：chat 会话的 session_id 作为 pipeline-state 的 task_id
          setTaskId(s.session_id);
          // 若数据库里已有该 task_id 的快照，则按需恢复（静默，不打 toast）
          return hydrateFromLatest({ taskId: s.session_id, silent: true, force: true });
        }
      })
      .then(() => {
        // 恢复完成后，同步 prevPhasesRef，避免后续 useEffect 误触发消息
        prevPhasesRef.current = { ...phases };
      })
      .catch((err) => {
        console.warn('[chat] create session failed, fallback to legacy stream:', err);
      });
  }, [hydrateFromLatest, setSessionId, setTaskId, phases]);

  // 将 pipeline 各阶段产物“回灌”到对话区：当阶段从 running -> done/failed 时追加一条 assistant 消息。
  // 注意：pipeline-store 负责模块化结果；chat-store 不会自动订阅，因此需要在 UI 层桥接。
  const prevPhasesRef = useRef(phases);
  useEffect(() => {
    const prev = prevPhasesRef.current;

    // 记录“最近一次阶段变更事件”，用于进度卡片展示（只做提示，不写入消息流）
    const changed: Array<{ phase: Phase; status: string }> = [];
    (Object.keys(phases) as Phase[]).forEach((p) => {
      if (prev[p] !== phases[p]) changed.push({ phase: p, status: phases[p] });
    });
    if (changed.length > 0) {
      const last = changed[changed.length - 1];
      setLastEvent(`${last.phase} -> ${last.status}`);
    }

    const emit = (phase: Phase, status: string) => {
      // 只在阶段完成或失败时提示，避免 idle/running 噪音
      if (status !== 'done' && status !== 'failed') return;
      // 必须是从 running -> done/failed 的转换，避免恢复历史状态时误触发
      if (prev[phase] !== 'running') return;

      switch (phase) {
        case 'detect': {
          if (status === 'failed') {
            const id = addMessage('assistant', '风险快照失败（结果卡片如下）');
            updateMessage(id, {
              meta: {
                type: 'detect',
                status: 'failed',
                taskId: taskId ?? null,
                createdAt: new Date().toISOString(),
                inputLength: text.length,
                inputPreview: text.length > 120 ? `${text.slice(0, 120)}…` : text,
                phases,
                error: error ?? '未知错误',
                detectData: detectData ?? null,
              },
              actions: [{ type: 'command', label: '重试失败阶段', command: '/retry_failed' }],
            });
            return;
          }
          const id = addMessage('assistant', '风险快照已完成（结果卡片如下）');
          updateMessage(id, {
            meta: {
              type: 'detect',
              status: 'done',
              taskId: taskId ?? null,
              createdAt: new Date().toISOString(),
              inputLength: text.length,
              inputPreview: text.length > 120 ? `${text.slice(0, 120)}…` : text,
              phases,
              detectData: detectData ?? null,
            },
            actions: [{ type: 'link', label: '打开检测结果', href: '/result' }],
          });
          return;
        }
        case 'claims': {
          const id = addMessage(
            'assistant',
            status === 'done' ? '主张抽取已完成（结果卡片如下）' : '主张抽取失败（结果卡片如下）'
          );
          updateMessage(id, {
            meta: {
              type: 'claims',
              status: status as any,
              taskId: taskId ?? null,
              createdAt: new Date().toISOString(),
              inputLength: text.length,
              inputPreview: text.length > 120 ? `${text.slice(0, 120)}…` : text,
              claims: Array.isArray(claims) ? claims : [],
              error: status === 'failed' ? error ?? '未知错误' : null,
            },
            actions:
              status === 'failed'
                ? [{ type: 'command', label: '重试失败阶段', command: '/retry_failed' }]
                : [{ type: 'link', label: '打开检测结果', href: '/result' }],
          });
          return;
        }
        case 'evidence': {
          const id = addMessage(
            'assistant',
            status === 'done' ? '证据处理已完成（结果卡片如下）' : '证据处理失败（结果卡片如下）'
          );
          updateMessage(id, {
            meta: {
              type: 'evidence',
              status: status as any,
              taskId: taskId ?? null,
              createdAt: new Date().toISOString(),
              claims: Array.isArray(claims) ? claims : [],
              rawEvidences: Array.isArray(rawEvidences) ? rawEvidences : [],
              evidences: Array.isArray(evidences) ? evidences : [],
              error: status === 'failed' ? error ?? '未知错误' : null,
            },
            actions:
              status === 'failed'
                ? [{ type: 'command', label: '重试失败阶段', command: '/retry_failed' }]
                : [{ type: 'link', label: '打开检测结果', href: '/result' }],
          });
          return;
        }
        case 'report': {
          if (status === 'done' && recordId) {
            setBoundRecordId(recordId);
          }
          const id = addMessage(
            'assistant',
            status === 'done' ? '综合报告已完成（结果卡片如下）' : '综合报告失败（结果卡片如下）'
          );
          updateMessage(id, {
            meta: {
              type: 'report',
              status: status as any,
              taskId: taskId ?? null,
              createdAt: new Date().toISOString(),
              recordId: recordId ?? null,
              inputText: text,
              report: report ?? null,
              error: status === 'failed' ? error ?? '未知错误' : null,
            },
            actions: [
              { type: 'link', label: '打开检测结果', href: '/result' },
              ...(recordId
                ? ([
                    {
                      type: 'command',
                      label: '加载本次记录到上下文',
                      command: `/load_history ${recordId}`,
                    },
                  ] as const)
                : []),
              ...(status === 'failed'
                ? ([{ type: 'command', label: '重试失败阶段', command: '/retry_failed' }] as const)
                : []),
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
    updateMessage,
    error,
    claims.length,
    detectData?.label,
    detectData?.score,
    rawEvidences.length,
    evidences.length,
    phases,
    recordId,
    report?.risk_label,
    report?.risk_score,
    taskId,
    text,
    setBoundRecordId,
  ]);

  const quickActions = useMemo(
    () => [
      {
        label: '新建会话',
        onClick: () => {
          addMessage('assistant', '正在创建新会话…');
          createChatSession()
            .then((s) => {
              setSessionId(s.session_id);
              setMessages([]);
              setBoundRecordId(null);
              addMessage('assistant', `已创建新会话：${s.session_id}`);
            })
            .catch((err) => {
              addMessage(
                'assistant',
                `创建会话失败：${err instanceof Error ? err.message : '未知错误'}（将继续使用当前会话）`
              );
            });
        },
      },
      {
        label: '加载最近会话',
        onClick: () => {
          addMessage('assistant', '正在加载最近会话…');
          listChatSessions(10)
            .then((res) => {
              const latest = res.sessions?.[0];
              if (!latest?.session_id) {
                addMessage('assistant', '未找到可恢复的会话。');
                return;
              }
              setSessionId(latest.session_id);
              setTaskId(latest.session_id);
              hydrateFromLatest({ taskId: latest.session_id, silent: true, force: true });
              return getChatSessionDetail(latest.session_id, 200);
            })
            .then((detail) => {
              if (!detail) return;
              const mapped = (detail.messages ?? []).map((m) => ({
                id: m.id ?? `${Date.now()}_${Math.random().toString(16).slice(2)}`,
                role: m.role,
                content: m.content,
                created_at: m.created_at ?? new Date().toISOString(),
                actions: m.actions,
                references: m.references,
                meta: m.meta,
              }));
              setMessages(mapped as any);
              addMessage('assistant', `已恢复会话：${detail.session.session_id}（${mapped.length} 条消息）`);
            })
            .catch((err) => {
              addMessage(
                'assistant',
                `加载会话失败：${err instanceof Error ? err.message : '未知错误'}`
              );
            });
        },
      },
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
          runPipeline({ taskId: session_id ?? null });
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
    [addMessage, interruptPipeline, isPipelineRunning, retryFailed, runPipeline, setMessages, setSessionId, setBoundRecordId, text]
  );

  const handleScroll = () => {
    const distance = computeDistanceToBottom();
    const nearBottom = distance <= NEAR_BOTTOM_THRESHOLD_PX;
    isNearBottomRef.current = nearBottom;

    if (nearBottom) {
      // 用户回到底部附近：恢复跟随并清除提示
      if (!isFollowingRef.current) {
        setIsFollowing(true);
        isFollowingRef.current = true;
      }
      if (hasNewMessages) setHasNewMessages(false);
      return;
    }

    // 用户主动向上滚动：关闭跟随（避免被拉回底部）
    if (isFollowingRef.current) {
      setIsFollowing(false);
      isFollowingRef.current = false;
    }
  };

  const runCommand = async (command: string) => {
    await onSend(command);
  };

  const onSend = async (input: string) => {
    // 允许对命令做轻量“补全/规范化”，但保留用户原始输入在聊天记录中
    let normalizedInput = input;
    addMessage('user', input);

    // 0) /load_history <record_id>
    const loadHistoryRecordId = parseLoadHistoryRecordId(input);
    if (loadHistoryRecordId !== null) {
      if (!loadHistoryRecordId) {
        addMessage('assistant', '用法：/load_history <record_id>');
        return;
      }
      addMessage('assistant', `正在从历史记录加载：${loadHistoryRecordId}`);
      try {
        const detail = await getHistoryDetail(loadHistoryRecordId);
        loadFromHistory(detail);
        setBoundRecordId(loadHistoryRecordId);
        addMessage('assistant', `已加载到前端上下文（当前绑定: ${loadHistoryRecordId}），可直接打开结果页查看。`, {
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

    // 0.5) /why (无参数) ：若已绑定 record_id，则自动补全
    // 诉求：用户执行过分析或 /load_history 后，可直接输入 /why 继续追问。
    const trimmed = input.trim();
    const effectiveRecordId = boundRecordId || recordId;
    if ((trimmed === '/why' || trimmed === '/explain') && effectiveRecordId) {
      normalizedInput = `/why ${effectiveRecordId}`;
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
      runPipeline({ taskId: session_id ?? null });
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

    // 4) 默认：如果是长文本且不是命令，直接当做待分析输入
    // 注意：像 `/why <record_id>`、`/list 20` 这类命令本身可能也很长，不能误触发自动分析。
    if (!input.trim().startsWith('/') && input.length >= 20) {
      setText(input);
      addMessage('assistant', '检测到你输入的是待分析文本，已自动启动分析。');
      runPipeline({ taskId: session_id ?? null });
      return;
    }

    // 5) 其它短输入：走后端 /chat（V0 占位编排），返回 actions 与 references
    try {
      setStreaming(true);
      const assistantMsgId = addMessage('assistant', '');

      const onEvent = (event: any) => {
        if (event?.data?.session_id) {
          setSessionId(event.data.session_id);
        }

        if (event.type === 'stage') {
          // 目前不做 UI 展示，仅保留兼容（后续可用于进度条/引用卡片）
          return;
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
            meta: event.data.message.meta,
          });
          return;
        }

        if (event.type === 'error') {
          updateMessage(assistantMsgId, {
            content: `后端对话流式返回错误：${event.data.message}`,
          });
          return;
        }
      };

      // 优先走会话化 V2 SSE；若失败则回退到旧 /chat/stream
      try {
        await chatSessionStream(
          session_id,
          {
            text: normalizedInput,
            context: {
              phases,
              record_id: recordId ?? null,
              recordId: recordId ?? null,
            },
          },
          onEvent
        );
      } catch (err) {
        console.warn('[chat] session stream failed, fallback to legacy stream:', err);
        await chatStream(
          {
            session_id,
            text: normalizedInput,
            context: {
              phases,
              record_id: recordId ?? null,
              recordId: recordId ?? null,
            },
          },
          onEvent
        );
      }
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
        {activePhase ? (
          <div className="shrink-0 pb-1">
            <ActivePhaseProgressCard
              taskId={taskId}
              phase={activePhase}
              status={phases[activePhase]}
              lastEvent={lastEvent}
              error={error}
            />
          </div>
        ) : null}
        {/* 消息列表：内部滚动，避免撑开页面 */}
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="flex-1 min-h-0 overflow-y-auto pr-1 relative"
        >
          <MessageList messages={messages} onCommand={runCommand} />
          {/* 底部哨兵：用于把视图滚动到最新 */}
          <div ref={bottomSentinelRef} className="h-1" />

          {/* 新消息提示（用户上滑浏览时显示） */}
          {hasNewMessages && !isFollowing && (
            <div className="sticky bottom-2 w-full flex justify-center pointer-events-none">
              <button
                type="button"
                className="pointer-events-auto rounded-full border bg-background/95 backdrop-blur px-3 py-1 text-xs shadow-sm hover:bg-muted"
                onClick={() => enableFollowingAndScrollBottom('smooth')}
              >
                有新消息，点击回到底部
              </button>
            </div>
          )}
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
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">上下文</CardTitle>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-md border px-2 py-1 text-xs hover:bg-muted"
            onClick={() => setIsFullscreen((v) => !v)}
            aria-label={isFullscreen ? '退出全屏' : '进入全屏'}
            title={isFullscreen ? '退出全屏 (Exit fullscreen)' : '进入全屏 (Enter fullscreen)'}
          >
            {isFullscreen ? (
              <>
                <Minimize2 className="h-4 w-4" />
                <span className="ml-1">退出全屏</span>
              </>
            ) : (
              <>
                <Maximize2 className="h-4 w-4" />
                <span className="ml-1">全屏</span>
              </>
            )}
          </button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col flex-1 min-h-0 gap-3 overflow-y-auto pr-1 px-4">
        {boundRecordId && (
          <div className="text-xs text-muted-foreground bg-muted/50 rounded px-2 py-1">
            当前绑定: <span className="font-mono">{boundRecordId}</span>
          </div>
        )}
        <div className="text-sm text-muted-foreground space-y-1">
          <div>风险快照：{phases.detect}</div>
          <div>主张抽取：{phases.claims}</div>
          <div>证据处理：{phases.evidence}</div>
          <div>综合报告：{phases.report}</div>
          <div>舆情预演：{phases.simulation}</div>
          <div>应对内容：{phases.content}</div>
        </div>
        <ContextPanel
          taskId={taskId}
          recordId={recordId}
          phases={phases}
          detectData={detectData}
          report={report}
          simulation={simulation}
          content={content}
          onClearContext={() => {
            reset();
            setBoundRecordId(null);
            addMessage('assistant', '已清空前端上下文（pipeline-store）。');
          }}
          onCommand={runCommand}
        />
      </CardContent>
    </Card>
  );

  return (
    <div
      className={
        isFullscreen
          ? 'fixed inset-0 z-50 bg-background p-2 md:p-4'
          : 'h-full min-h-0'
      }
    >
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
    </div>
  );
}

