'use client';

import { ProgressTimeline } from '@/components/layout';
import { SimulationView } from '@/components/features';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';

export default function SimulationPage() {
  const { simulation, phases, retryPhase } = usePipelineStore();

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-center">
        <ProgressTimeline 
          phases={phases} 
          onRetry={handleRetry}
          showRetry={true}
        />
      </div>
      <SimulationView simulation={simulation} isLoading={phases.simulation === 'running'} />
    </div>
  );
}
