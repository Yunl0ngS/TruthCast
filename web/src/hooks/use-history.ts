import useSWR from 'swr';
import { getHistory, getHistoryDetail, submitHistoryFeedback } from '@/services/api';
import type { HistoryItem, HistoryDetail } from '@/types';

export function useHistoryList(limit = 20) {
  const { data, error, isLoading, mutate } = useSWR<HistoryItem[]>(
    ['history', limit],
    () => getHistory(limit),
    { revalidateOnFocus: false }
  );

  return {
    items: data ?? [],
    isLoading,
    error,
    refresh: mutate,
  };
}

export function useHistoryDetail(recordId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<HistoryDetail>(
    recordId ? ['history-detail', recordId] : null,
    () => getHistoryDetail(recordId!),
    { revalidateOnFocus: false }
  );

  return {
    detail: data,
    isLoading,
    error,
    refresh: mutate,
  };
}

export function useSubmitFeedback() {
  return async (recordId: string, status: 'accurate' | 'inaccurate' | 'evidence_irrelevant', note = '') => {
    await submitHistoryFeedback(recordId, status, note);
  };
}
