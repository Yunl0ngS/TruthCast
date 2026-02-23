'use client';

import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { toast as sonnerToast } from 'sonner';

import { usePipelineStore } from '@/stores/pipeline-store';


/**
 * 全局初始化：探测“是否存在可恢复的上一次分析任务”。
 *
 * 约束：默认不自动恢复。
 * - 仅在首页（/）提示恢复
 * - 用户点击“继续恢复”才触发 hydrate
 * - 用户点击“取消”后，本次浏览器会话（sessionStorage）不再提示
 */
export function PipelineHydrator() {
  const pathname = usePathname();
  const probeLatestRestorable = usePipelineStore((s) => s.probeLatestRestorable);
  const hydrateFromLatest = usePipelineStore((s) => s.hydrateFromLatest);
  const restorableTaskId = usePipelineStore((s) => s.restorableTaskId);
  const restorableUpdatedAt = usePipelineStore((s) => s.restorableUpdatedAt);

  const shownRef = useRef(false);
  const toastIdRef = useRef<string | number | null>(null);

  useEffect(() => {
    if (pathname !== '/') return;
    // 仅探测，不恢复
    probeLatestRestorable();
  }, [pathname, probeLatestRestorable]);

  useEffect(() => {
    if (pathname !== '/') return;
    if (!restorableTaskId) return;
    if (shownRef.current) return;

    try {
      const disabled = sessionStorage.getItem('truthcast_restore_disabled') === '1';
      if (disabled) return;

      shownRef.current = true;
      toastIdRef.current = sonnerToast(
        '检测到可恢复的上一次分析进度（默认不自动恢复）',
        {
          description: restorableUpdatedAt ? `更新时间：${restorableUpdatedAt}` : undefined,
          duration: 12000,
          action: {
            label: '继续恢复',
            onClick: () => {
              void hydrateFromLatest({ taskId: restorableTaskId, force: true });
            },
          },
          cancel: {
            label: '取消',
            onClick: () => {
              sessionStorage.setItem('truthcast_restore_disabled', '1');
            },
          },
        }
      );
    } catch (err) {
      // sessionStorage 在极端环境可能不可用；忽略即可
      console.warn('[pipeline hydrator] restore prompt failed:', err);
    }

    return () => {
      if (toastIdRef.current != null) {
        sonnerToast.dismiss(toastIdRef.current);
        toastIdRef.current = null;
      }
    };
  }, [hydrateFromLatest, pathname, restorableTaskId, restorableUpdatedAt]);

  return null;
}

