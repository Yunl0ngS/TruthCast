'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { zhClaimId } from '@/lib/i18n';
import type { ClaimItem } from '@/types';

interface ClaimListProps {
  claims: ClaimItem[];
  isLoading: boolean;
}

export function ClaimList({ claims, isLoading }: ClaimListProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-24" />
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (claims.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>主张抽取</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground">暂无主张结果。</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>主张抽取</CardTitle>
        <CardDescription>从文本中提取的可核查主张</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {claims.map((claim) => (
            <li key={claim.claim_id} className="border rounded-lg p-3">
              <div className="flex items-start gap-2">
                <Badge variant="outline" className="shrink-0">
                  {zhClaimId(claim.claim_id)}
                </Badge>
                <p className="text-sm">{claim.claim_text}</p>
              </div>
              {(claim.entity || claim.time || claim.location || claim.value) && (
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  {claim.entity && <span>实体: {claim.entity}</span>}
                  {claim.time && <span>时间: {claim.time}</span>}
                  {claim.location && <span>地点: {claim.location}</span>}
                  {claim.value && <span>数值: {claim.value}</span>}
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
