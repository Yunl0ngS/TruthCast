'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { ClipboardList } from 'lucide-react';
import { cn } from '@/lib/utils';
import { zhClaimId } from '@/lib/i18n';
import type { ClaimItem } from '@/types';

interface ClaimListProps {
  claims: ClaimItem[];
  isLoading: boolean;
  activeClaimId?: string | null;
  onSelectClaim?: (claimId: string) => void;
  evidenceStats?: Record<string, { aligned: number; raw: number }>;
}

function ClaimListSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-4 w-36 mt-1" />
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="border rounded-lg p-3 space-y-2">
              <div className="flex items-start gap-2">
                <Skeleton className="h-5 w-12 rounded-full shrink-0" />
                <Skeleton className="h-4 w-full" />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function ClaimListEmpty() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>主张抽取</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center gap-2 py-6 text-muted-foreground">
          <ClipboardList className="h-8 w-8 opacity-30" />
          <p className="text-sm">暂未抽取到可核查主张</p>
          <p className="text-xs opacity-60">文本可能较短，或内容尚在分析中</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function ClaimList({
  claims,
  isLoading,
  activeClaimId,
  onSelectClaim,
  evidenceStats,
}: ClaimListProps) {
  if (isLoading) {
    return <ClaimListSkeleton />;
  }

  if (claims.length === 0) {
    return <ClaimListEmpty />;
  }

  return (
    <Card className="transition-opacity duration-500 animate-in fade-in xl:sticky xl:top-24">
      <CardHeader>
        <CardTitle>主张导航</CardTitle>
        <CardDescription>选择一条主张，右侧只查看该主张的证据链</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span className="rounded-full border bg-muted/40 px-2.5 py-1">共 {claims.length} 条主张</span>
          {activeClaimId ? (
            <span className="rounded-full border bg-muted/40 px-2.5 py-1">
              当前：{zhClaimId(activeClaimId)}
            </span>
          ) : null}
        </div>
        <ul className="space-y-3">
          {claims.map((claim) => (
            <li key={claim.claim_id}>
              <Button
                type="button"
                variant="ghost"
                className={cn(
                  'h-auto w-full justify-start rounded-[1rem] border p-0 text-left whitespace-normal hover:bg-muted/40',
                  activeClaimId === claim.claim_id && 'border-primary/40 bg-primary/5 hover:bg-primary/10'
                )}
                onClick={() => onSelectClaim?.(claim.claim_id)}
              >
                <div className="w-full space-y-3 p-3">
                  <div className="flex items-start gap-2">
                    <Badge variant={activeClaimId === claim.claim_id ? 'default' : 'outline'} className="shrink-0">
                      {zhClaimId(claim.claim_id)}
                    </Badge>
                    <p className="text-sm leading-6">{claim.claim_text}</p>
                  </div>

                  {evidenceStats?.[claim.claim_id] ? (
                    <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                      <span className="rounded-full border bg-background px-2 py-1">
                        对齐证据 {evidenceStats[claim.claim_id].aligned}
                      </span>
                      <span className="rounded-full border bg-background px-2 py-1">
                        检索证据 {evidenceStats[claim.claim_id].raw}
                      </span>
                    </div>
                  ) : null}
                </div>
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
