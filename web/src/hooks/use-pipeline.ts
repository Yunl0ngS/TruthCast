import { usePipelineStore } from '@/stores/pipeline-store';

export function usePipeline() {
  const {
    text,
    error,
    detectData,
    claims,
    evidences,
    report,
    simulation,
    phases,
    setText,
    runPipeline,
    reset,
  } = usePipelineStore();

  const isLoading = Object.values(phases).some((status) => status === 'running');

  return {
    text,
    error,
    detectData,
    claims,
    evidences,
    report,
    simulation,
    phases,
    isLoading,
    setText,
    runPipeline,
    reset,
  };
}
