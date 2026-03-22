import useSWR from 'swr';
import {
  acknowledgeMonitorAlert,
  analyzeMonitorWindowItem,
  createMonitorSubscription,
  deleteMonitorSubscription,
  getMonitorAlerts,
  getMonitorAnalysisResults,
  getMonitorHotItems,
  getLatestMonitorWindow,
  getMonitorWindowHistory,
  getMonitorStatus,
  getMonitorSubscriptions,
  generateMonitorAnalysisContent,
  triggerMonitorScan,
  updateMonitorSubscription,
} from '@/services/api';
import type {
  MonitorAlert,
  MonitorAnalysisResult,
  MonitorHotItem,
  MonitorScanWindowDetail,
  MonitorStatus,
  MonitorSubscription,
  MonitorSubscriptionCreate,
} from '@/types';

export function useMonitorStatus() {
  const { data, error, isLoading, mutate } = useSWR<MonitorStatus>(
    ['monitor-status'],
    () => getMonitorStatus(),
    { revalidateOnFocus: false, refreshInterval: 15000 }
  );

  return { status: data, error, isLoading, refresh: mutate };
}

export function useMonitorHotItems(limit = 20, platform?: string) {
  const { data, error, isLoading, mutate } = useSWR<MonitorHotItem[]>(
    ['monitor-hot-items', limit, platform ?? 'all'],
    () => getMonitorHotItems(limit, platform),
    { revalidateOnFocus: false, refreshInterval: 15000 }
  );

  return { items: data ?? [], error, isLoading, refresh: mutate };
}

export function useMonitorSubscriptions(isActive?: boolean) {
  const { data, error, isLoading, mutate } = useSWR<MonitorSubscription[]>(
    ['monitor-subscriptions', typeof isActive === 'boolean' ? String(isActive) : 'all'],
    () => getMonitorSubscriptions(isActive),
    { revalidateOnFocus: false }
  );

  return { items: data ?? [], error, isLoading, refresh: mutate };
}

export function useMonitorAlerts(limit = 50) {
  const { data, error, isLoading, mutate } = useSWR<MonitorAlert[]>(
    ['monitor-alerts', limit],
    () => getMonitorAlerts(limit),
    { revalidateOnFocus: false, refreshInterval: 15000 }
  );

  return { items: data ?? [], error, isLoading, refresh: mutate };
}

export function useMonitorAnalysisResults(limit = 20) {
  const { data, error, isLoading, mutate } = useSWR<MonitorAnalysisResult[]>(
    ['monitor-analysis-results', limit],
    () => getMonitorAnalysisResults(limit),
    { revalidateOnFocus: false, refreshInterval: 15000 }
  );

  return { items: data ?? [], error, isLoading, refresh: mutate };
}

export function useLatestMonitorWindow() {
  const { data, error, isLoading, mutate } = useSWR<MonitorScanWindowDetail>(
    ['monitor-window-latest'],
    () => getLatestMonitorWindow(),
    { revalidateOnFocus: false, refreshInterval: 15000 }
  );

  return { window: data, error, isLoading, refresh: mutate };
}

export function useMonitorWindowHistory(hours = 6, limit = 24) {
  const { data, error, isLoading, mutate } = useSWR<MonitorScanWindowDetail[]>(
    ['monitor-window-history', hours, limit],
    () => getMonitorWindowHistory(hours, limit),
    { revalidateOnFocus: false, refreshInterval: 15000 }
  );

  return { windows: data ?? [], error, isLoading, refresh: mutate };
}

export const monitorActions = {
  createSubscription: (payload: MonitorSubscriptionCreate) => createMonitorSubscription(payload),
  updateSubscription: (id: string, payload: Partial<MonitorSubscriptionCreate> & { is_active?: boolean }) =>
    updateMonitorSubscription(id, payload),
  deleteSubscription: (id: string) => deleteMonitorSubscription(id),
  triggerScan: (platforms?: string[], autoAnalyze?: boolean) => triggerMonitorScan(platforms, autoAnalyze),
  analyzeWindowItem: (itemId: string) => analyzeMonitorWindowItem(itemId),
  acknowledgeAlert: (id: string) => acknowledgeMonitorAlert(id),
  generateAnalysisContent: (id: string) => generateMonitorAnalysisContent(id),
};
