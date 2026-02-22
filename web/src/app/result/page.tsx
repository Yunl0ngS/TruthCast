'use client';

import { ProgressTimeline } from '@/components/layout';
import { RiskOverview, ClaimList, EvidenceChain, ReportCard, ExportButton } from '@/components/features';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';

export default function ResultPage() {
  const { text, detectData, claims, rawEvidences, evidences, report, simulation, phases, retryPhase } = usePipelineStore();

  const hasReport = report !== null;
  
  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div className="space-y-6 px-2 md:px-0">
      <div className="flex flex-col items-center gap-4">
        <ProgressTimeline 
          phases={phases} 
          onRetry={handleRetry}
          showRetry={true}
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
              exportedAt: new Date().toLocaleString('zh-CN'),
            }}
          />
        )}
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
        <RiskOverview data={detectData} isLoading={phases.detect === 'running'} />
        <ClaimList claims={claims} isLoading={phases.claims === 'running'} />
      </div>

      <EvidenceChain
        rawEvidences={rawEvidences}
        evidences={evidences}
        claims={claims}
        report={report}
        isLoading={phases.evidence === 'running'}
      />

      <ReportCard report={report} isLoading={phases.report === 'running'} />
    </div>
  );
}
