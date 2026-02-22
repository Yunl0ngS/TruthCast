'use client';

import { useEffect } from 'react';

import { usePipelineStore } from '@/stores/pipeline-store';


/**
 * 全局初始化：尝试从后端 /pipeline/load-latest 恢复上一次分析进度。
 * - 不阻塞 UI
 * - 若当前已有进度（用户刚开始分析）则不覆盖
 */
export function PipelineHydrator() {
  const hydrateFromLatest = usePipelineStore((s) => s.hydrateFromLatest);

  useEffect(() => {
    hydrateFromLatest();
  }, [hydrateFromLatest]);

  return null;
}

