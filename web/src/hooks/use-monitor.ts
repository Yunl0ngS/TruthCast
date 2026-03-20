import useSWR from 'swr';
import {
  acknowledgeMonitorAlert,
  createMonitorSubscription,
  deleteMonitorSubscription,
  getMonitorAlerts,
  getMonitorHotItems,
  getMonitorStatus,
  getMonitorSubscriptions,
  triggerMonitorScan,
  updateMonitorSubscription,
} from '@/services/api';
import type {
  MonitorAlert,
  MonitorHotItem,
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

export const monitorActions = {
  createSubscription: (payload: MonitorSubscriptionCreate) => createMonitorSubscription(payload),
  updateSubscription: (id: string, payload: Partial<MonitorSubscriptionCreate> & { is_active?: boolean }) =>
    updateMonitorSubscription(id, payload),
  deleteSubscription: (id: string) => deleteMonitorSubscription(id),
  triggerScan: (platforms?: string[]) => triggerMonitorScan(platforms),
  acknowledgeAlert: (id: string) => acknowledgeMonitorAlert(id),
};
