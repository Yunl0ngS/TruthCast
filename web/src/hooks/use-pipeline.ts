import { usePipelineStore } from '@/stores/pipeline-store';

export function usePipeline() {
  const {
    text,
    error,
    enhancedText,
    detectData,
    claims,
    evidences,
    images,
    ocrResults,
    imageAnalyses,
    fusionReport,
    report,
    simulation,
    phases,
    setText,
    setImages,
    runPipeline,
    reset,
  } = usePipelineStore();

  const isLoading = Object.values(phases).some((status) => status === 'running');

  return {
    text,
    error,
    enhancedText,
    detectData,
    claims,
    evidences,
    images,
    ocrResults,
    imageAnalyses,
    fusionReport,
    report,
    simulation,
    phases,
    isLoading,
    setText,
    setImages,
    runPipeline,
    reset,
  };
}
