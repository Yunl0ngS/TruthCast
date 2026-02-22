'use client';

import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader2,
  Play,
  RotateCcw,
  Square,
  XCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { Phase, PhaseStatus } from '@/types';
import { toast } from 'sonner';

interface PhaseState {
  detect: PhaseStatus;
  claims: PhaseStatus;
  evidence: PhaseStatus;
  report: PhaseStatus;
  simulation: PhaseStatus;
  content: PhaseStatus;
}

const phaseLabels: Record<Phase, string> = {
  detect: '风险快照',
  claims: '主张抽取',
  evidence: '证据检索',
  report: '综合报告',
  simulation: '舆情预演',
  content: '应对内容',
};

const phaseShortLabels: Record<Phase, string> = {
  detect: '快照',
  claims: '主张',
  evidence: '证据',
  report: '报告',
  simulation: '预演',
  content: '应对',
};

const phaseOrder: Phase[] = ['detect', 'claims', 'evidence', 'report', 'simulation', 'content'];

interface ProgressTimelineProps {
  phases: PhaseState;
  onRetry?: (phase: Phase) => void;
  onAbort?: () => void;
  showRetry?: boolean;
  /** 移动端渲染模式：collapsible 为默认折叠摘要；expanded 为始终展开 */
  mobileMode?: 'collapsible' | 'expanded';
  /** 移动端摘要条是否 sticky（默认 true），用于减少首屏滚动成本 */
  stickyMobile?: boolean;
  /** 可选：记忆展开状态的 localStorage key；不传则不记忆 */
  rememberExpandedKey?: string;
}

function getCurrentPhase(phases: PhaseState): Phase {
  // running 优先
  for (const p of phaseOrder) {
    if (phases[p] === 'running') return p;
  }
  // failed 次优先
  for (const p of phaseOrder) {
    if (phases[p] === 'failed') return p;
  }
  // canceled 再次优先
  for (const p of phaseOrder) {
    if (phases[p] === 'canceled') return p;
  }
  // 第一个 idle
  for (const p of phaseOrder) {
    if (phases[p] === 'idle') return p;
  }
  return 'content';
}

function getFailedPhase(phases: PhaseState): Phase | null {
  for (const p of phaseOrder) {
    if (phases[p] === 'failed') return p;
  }
  return null;
}

function canStartPhase(phases: PhaseState, phase: Phase): boolean {
  const idx = phaseOrder.indexOf(phase);
  if (idx <= 0) return true;
  for (let i = 0; i < idx; i += 1) {
    if (phases[phaseOrder[i]] !== 'done') return false;
  }
  return true;
}

export function ProgressTimeline({
  phases,
  onRetry,
  onAbort,
  showRetry = true,
  mobileMode = 'collapsible',
  stickyMobile = true,
  rememberExpandedKey,
}: ProgressTimelineProps) {
  const currentPhase = useMemo(() => getCurrentPhase(phases), [phases]);
  const failedPhase = useMemo(() => getFailedPhase(phases), [phases]);
  const doneCount = useMemo(
    () => phaseOrder.filter((p) => phases[p] === 'done').length,
    [phases]
  );

  const hasRunning = useMemo(() => phaseOrder.some((p) => phases[p] === 'running'), [phases]);
  const canAbortCurrent = !!onAbort && phases[currentPhase] === 'running';
  const [isAborting, setIsAborting] = useState(false);

  useEffect(() => {
    // 当不再有 running 阶段时，自动退出“正在中断”态
    if (!hasRunning) setIsAborting(false);
  }, [hasRunning]);

  useEffect(() => {
    if (!isAborting) return;
    // 超时回退：避免网络异常导致“中断中”一直锁死
    const t = window.setTimeout(() => setIsAborting(false), 8000);
    return () => window.clearTimeout(t);
  }, [isAborting]);

  const triggerAbort = () => {
    if (!onAbort) return;
    if (!canAbortCurrent) return;
    if (isAborting) return;
    setIsAborting(true);
    toast.info('正在中断…');
    onAbort();
  };

  const canCollapse = mobileMode === 'collapsible';
  // 重要：不要在初次渲染读取 localStorage（会导致 SSR/CSR 初始 HTML 不一致触发 hydration mismatch）
  const [expanded, setExpanded] = useState(mobileMode === 'expanded');

  useEffect(() => {
    if (!rememberExpandedKey) return;
    try {
      const raw = localStorage.getItem(rememberExpandedKey);
      if (raw === '1') setExpanded(true);
      if (raw === '0') setExpanded(false);
    } catch {
      // ignore
    }
  }, [rememberExpandedKey]);

  useEffect(() => {
    if (!rememberExpandedKey) return;
    try {
      localStorage.setItem(rememberExpandedKey, expanded ? '1' : '0');
    } catch {
      // ignore
    }
  }, [expanded, rememberExpandedKey]);

  const timelineId = rememberExpandedKey ? `timeline_${rememberExpandedKey}` : 'timeline_mobile';

  return (
    <>
      {/* Desktop: Horizontal */}
      <div className="hidden md:flex items-center justify-center gap-2 py-4 relative">
        {phaseOrder.map((phase, index) => (
          <div key={phase} className="flex items-center">
            <PhaseIndicator 
              phase={phase} 
              status={phases[phase]} 
              isCurrent={phase === currentPhase}
              canStart={canStartPhase(phases, phase)}
              canAbort={!!onAbort}
              isAborting={isAborting}
              onAbort={triggerAbort}
              onRetry={onRetry}
              showRetry={showRetry}
              compact={false}
            />
            {index < phaseOrder.length - 1 && (
              <div
                className={cn(
                  'mx-2 h-0.5 w-8',
                  phases[phase] === 'done' ? 'bg-green-500' : 'bg-muted'
                )}
              />
            )}
          </div>
        ))}
      </div>
      
      {/* Mobile: Collapsible summary + horizontal pills */}
      <div
        className={cn(
          'md:hidden w-full',
          stickyMobile &&
            'sticky top-14 z-20 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-b'
        )}
      >
        <div className="px-2 py-2">
          <div className="flex items-center justify-between gap-2 rounded-lg border bg-background px-2.5 py-2">
            <button
              type="button"
              className="flex items-center gap-2 min-w-0 text-left"
              onClick={() => {
                if (!canCollapse) return;
                setExpanded((v) => !v);
              }}
              aria-expanded={expanded}
              aria-controls={timelineId}
              disabled={!canCollapse}
            >
              {phases[currentPhase] === 'running' ? (
                <span
                  role={canAbortCurrent ? 'button' : undefined}
                  tabIndex={canAbortCurrent ? 0 : -1}
                  aria-label={canAbortCurrent ? '中断分析' : undefined}
                  aria-disabled={canAbortCurrent ? isAborting : undefined}
                  title={canAbortCurrent ? '点击中断分析' : undefined}
                  className={cn(
                    'relative inline-flex items-center justify-center rounded-full w-7 h-7 border shrink-0 group',
                    'bg-blue-50 border-blue-200',
                    canAbortCurrent && 'cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/40',
                    canAbortCurrent && !isAborting && 'hover:bg-blue-100/70',
                    canAbortCurrent && isAborting && 'opacity-60 cursor-not-allowed'
                  )}
                  onClick={(e) => {
                    if (!canAbortCurrent) return;
                    e.preventDefault();
                    e.stopPropagation();
                    triggerAbort();
                  }}
                  onKeyDown={(e) => {
                    if (!canAbortCurrent) return;
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      e.stopPropagation();
                      triggerAbort();
                    }
                  }}
                >
                  <Loader2 className="h-4 w-4 text-blue-600 animate-spin" />
                  <Square
                    className={cn(
                      'absolute h-3.5 w-3.5 text-red-600 transition-opacity',
                      isAborting ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                    )}
                  />
                </span>
              ) : (
                <span
                  className={cn(
                    'inline-flex items-center justify-center rounded-full w-7 h-7 border shrink-0',
                    phases[currentPhase] === 'done' && 'bg-green-50 border-green-200',
                    phases[currentPhase] === 'failed' && 'bg-red-50 border-red-200'
                  )}
                >
                  {phases[currentPhase] === 'done' ? (
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                  ) : phases[currentPhase] === 'failed' ? (
                    <XCircle className="h-4 w-4 text-red-600" />
                  ) : (
                    <Circle className="h-4 w-4 text-muted-foreground" />
                  )}
                </span>
              )}
              <div className="min-w-0">
                <div className="text-sm font-medium truncate">
                  当前：{phaseShortLabels[currentPhase]}（{phaseLabels[currentPhase]}）
                </div>
                <div className="text-xs text-muted-foreground">
                  已完成 {doneCount}/{phaseOrder.length}
                  {failedPhase ? ` · 失败：${phaseShortLabels[failedPhase]}` : ''}
                </div>
              </div>
            </button>

            <div className="shrink-0 flex items-center gap-1">
              {failedPhase && showRetry && onRetry && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => onRetry(failedPhase)}
                  title="重试失败阶段"
                >
                  <RotateCcw className="h-4 w-4" />
                </Button>
              )}
              {canCollapse && (
                <span className="text-muted-foreground">
                  {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                </span>
              )}
            </div>
          </div>

          {(expanded || !canCollapse) && (
            <div id={timelineId} className="mt-2">
              <div className="flex items-center gap-2 overflow-x-auto py-1.5 pr-1">
                {phaseOrder.map((phase) => (
                  <MobileStepPill
                    key={phase}
                    phase={phase}
                    status={phases[phase]}
                    isCurrent={phase === currentPhase}
                    canStart={canStartPhase(phases, phase)}
                    canAbort={!!onAbort}
                    isAborting={isAborting}
                    onAbort={triggerAbort}
                    onRetry={onRetry}
                    showRetry={showRetry}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function PhaseIndicator({ 
  phase, 
  status,
  isCurrent,
  canStart,
  canAbort,
  isAborting,
  onAbort,
  onRetry,
  showRetry,
  compact,
}: { 
  phase: Phase; 
  status: PhaseStatus;
  isCurrent: boolean;
  canStart: boolean;
  canAbort: boolean;
  isAborting: boolean;
  onAbort: () => void;
  onRetry?: (phase: Phase) => void;
  showRetry?: boolean;
  compact: boolean;
}) {
  const canAbortHere = canAbort && isCurrent && status === 'running';

  const runningIcon = <Loader2 className={cn(compact ? 'h-4 w-4' : 'h-5 w-5', 'text-blue-500 animate-spin')} />;

  const icons = {
    idle: <Circle className={cn(compact ? 'h-4 w-4' : 'h-5 w-5', 'text-muted-foreground')} />,
    running: runningIcon,
    done: <CheckCircle2 className={cn(compact ? 'h-4 w-4' : 'h-5 w-5', 'text-green-500')} />,
    failed: <XCircle className={cn(compact ? 'h-4 w-4' : 'h-5 w-5', 'text-red-500')} />,
    canceled: <Square className={cn(compact ? 'h-4 w-4' : 'h-5 w-5', 'text-amber-600')} />,
  };

  const handleRetry = () => {
    if (onRetry) {
      onRetry(phase);
    }
  };

  const label = compact ? phaseShortLabels[phase] : phaseLabels[phase];
  const canRetry = (status === 'done' || status === 'failed' || status === 'canceled') && !!onRetry && !!showRetry;
  const canRun = status === 'idle' && !!onRetry && !!showRetry && canStart;

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 rounded-full',
        compact ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm',
        status === 'running' && 'bg-blue-50 dark:bg-blue-950',
        status === 'done' && 'bg-green-50 dark:bg-green-950',
        status === 'failed' && 'bg-red-50 dark:bg-red-950',
        status === 'canceled' && 'bg-amber-50 dark:bg-amber-950'
      )}
    >
      {icons[status]}
      <span className="font-medium">{label}</span>

      {canAbortHere && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={cn(
            'text-red-600 hover:text-red-700 hover:bg-red-50/60',
            compact ? 'h-4 w-4 ml-0.5' : 'h-5 w-5 ml-1',
            isAborting && 'opacity-60 cursor-not-allowed'
          )}
          disabled={isAborting}
          onClick={(e) => {
            e.stopPropagation();
            onAbort();
          }}
          title="中断分析"
        >
          <Square className={compact ? 'h-2.5 w-2.5' : 'h-3 w-3'} />
        </Button>
      )}

      {canRun && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={cn(
            'text-muted-foreground hover:text-foreground',
            compact ? 'h-4 w-4 ml-0.5' : 'h-5 w-5 ml-1'
          )}
          onClick={(e) => {
            e.stopPropagation();
            onRetry?.(phase);
          }}
          title="继续执行"
        >
          <Play className={compact ? 'h-2.5 w-2.5' : 'h-3 w-3'} />
        </Button>
      )}
      {canRetry && (
        <Button
          variant="ghost"
          size="icon"
          className={cn(
            "text-muted-foreground hover:text-foreground",
            compact ? "h-4 w-4 ml-0.5" : "h-5 w-5 ml-1"
          )}
          onClick={handleRetry}
          title={status === 'failed' ? '重试' : status === 'canceled' ? '从中断处恢复' : '重新执行'}
        >
          <RotateCcw className={compact ? "h-2.5 w-2.5" : "h-3 w-3"} />
        </Button>
      )}
    </div>
  );
}

function MobileStepPill({
  phase,
  status,
  isCurrent,
  canStart,
  canAbort,
  isAborting,
  onAbort,
  onRetry,
  showRetry,
}: {
  phase: Phase;
  status: PhaseStatus;
  isCurrent: boolean;
  canStart: boolean;
  canAbort: boolean;
  isAborting: boolean;
  onAbort: () => void;
  onRetry?: (phase: Phase) => void;
  showRetry?: boolean;
}) {
  const canAbortHere = canAbort && isCurrent && status === 'running';

  const icon =
    status === 'done' ? (
      <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
    ) : status === 'running' ? (
      <Loader2 className="h-3.5 w-3.5 text-blue-600 animate-spin" />
    ) : status === 'failed' ? (
      <XCircle className="h-3.5 w-3.5 text-red-600" />
    ) : (
      <Circle className="h-3.5 w-3.5 text-muted-foreground" />
    );

  const canRetry = (status === 'done' || status === 'failed' || status === 'canceled') && !!onRetry && !!showRetry;
  const canRun = status === 'idle' && !!onRetry && !!showRetry && canStart;

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs whitespace-nowrap',
        isCurrent && 'ring-2 ring-primary/30 border-primary/40',
        status === 'running' && 'bg-blue-50 dark:bg-blue-950',
        status === 'done' && 'bg-green-50 dark:bg-green-950',
        status === 'failed' && 'bg-red-50 dark:bg-red-950',
        status === 'canceled' && 'bg-amber-50 dark:bg-amber-950'
      )}
    >
      {icon}
      <span className={cn('font-medium', isCurrent && 'text-foreground')}>{phaseShortLabels[phase]}</span>

      {canAbortHere && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={cn(
            'h-5 w-5 ml-0.5 text-red-600 hover:text-red-700 hover:bg-red-50/60',
            isAborting && 'opacity-60 cursor-not-allowed'
          )}
          disabled={isAborting}
          onClick={(e) => {
            e.stopPropagation();
            onAbort();
          }}
          title="中断分析"
        >
          <Square className="h-3 w-3" />
        </Button>
      )}

      {canRun && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-5 w-5 ml-0.5 text-muted-foreground hover:text-foreground"
          onClick={() => onRetry?.(phase)}
          title="继续执行"
        >
          <Play className="h-3 w-3" />
        </Button>
      )}
      {canRetry && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-5 w-5 ml-0.5 text-muted-foreground hover:text-foreground"
          onClick={() => onRetry?.(phase)}
          title={status === 'failed' ? '重试' : status === 'canceled' ? '从中断处恢复' : '重新执行'}
        >
          <RotateCcw className="h-3 w-3" />
        </Button>
      )}
    </div>
  );
}
