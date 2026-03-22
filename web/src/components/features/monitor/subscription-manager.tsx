'use client';

import { useMemo, useState } from 'react';
import { BellPlus, BellRing, Filter, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useMonitorSubscriptions, monitorActions } from '@/hooks/use-monitor';
import { toast } from '@/lib/toast';
import type { MonitorNotifyChannel, MonitorTriggerMode, MonitorSubscriptionCreate } from '@/types';

const PLATFORM_OPTIONS = ['weibo', 'zhihu', 'douyin', 'bilibili', 'xiaohongshu'];
const CHANNEL_OPTIONS: { value: MonitorNotifyChannel; label: string }[] = [
  { value: 'webhook', label: 'Webhook' },
  { value: 'wecom', label: '企微' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'feishu', label: '飞书' },
  { value: 'email', label: '邮件' },
];
const TRIGGER_OPTIONS: { value: MonitorTriggerMode; label: string }[] = [
  { value: 'threshold', label: '阈值触发' },
  { value: 'hit', label: '命中即触发' },
  { value: 'smart', label: '智能触发' },
];

export function SubscriptionManager() {
  const { items, isLoading, refresh } = useMonitorSubscriptions();
  const [name, setName] = useState('');
  const [keywords, setKeywords] = useState('');
  const [excludeKeywords, setExcludeKeywords] = useState('');
  const [riskThreshold, setRiskThreshold] = useState('70');
  const [triggerMode, setTriggerMode] = useState<MonitorTriggerMode>('threshold');
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['weibo']);
  const [selectedChannels, setSelectedChannels] = useState<MonitorNotifyChannel[]>(['webhook']);
  const [submitting, setSubmitting] = useState(false);

  const stats = useMemo(() => {
    return {
      total: items.length,
      active: items.filter((item) => item.is_active).length,
      muted: items.filter((item) => !item.is_active).length,
    };
  }, [items]);

  const togglePlatform = (value: string) => {
    setSelectedPlatforms((prev) => (prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value]));
  };

  const toggleChannel = (value: MonitorNotifyChannel) => {
    setSelectedChannels((prev) => (prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value]));
  };

  const resetForm = () => {
    setName('');
    setKeywords('');
    setExcludeKeywords('');
    setRiskThreshold('70');
    setTriggerMode('threshold');
    setSelectedPlatforms(['weibo']);
    setSelectedChannels(['webhook']);
  };

  const handleCreate = async () => {
    const payload: MonitorSubscriptionCreate = {
      name: name.trim(),
      type: 'keyword',
      keywords: keywords.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
      match_mode: 'any',
      platforms: selectedPlatforms,
      exclude_keywords: excludeKeywords.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
      trigger_mode: triggerMode,
      risk_threshold: Number(riskThreshold) || 70,
      notify_channels: selectedChannels,
      notify_config: {},
    };

    if (!payload.name || payload.keywords.length === 0) {
      toast.warning('订阅信息不完整', '请至少填写订阅名称和一个关键词');
      return;
    }

    setSubmitting(true);
    try {
      await monitorActions.createSubscription(payload);
      await refresh();
      resetForm();
      toast.success('订阅创建成功', '新的监测规则已加入前哨列表');
    } catch (error) {
      console.error('Create subscription failed:', error);
      toast.error('订阅创建失败', '请检查后端接口和输入内容');
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleActive = async (id: string, nextActive: boolean) => {
    try {
      await monitorActions.updateSubscription(id, { is_active: nextActive });
      await refresh();
      toast.success(nextActive ? '订阅已启用' : '订阅已停用');
    } catch (error) {
      console.error('Toggle subscription failed:', error);
      toast.error('状态更新失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await monitorActions.deleteSubscription(id);
      await refresh();
      toast.success('订阅已删除');
    } catch (error) {
      console.error('Delete subscription failed:', error);
      toast.error('删除失败');
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      <Card className="border-white/70 bg-[linear-gradient(150deg,rgba(255,255,255,0.82),rgba(241,247,251,0.82))]">
        <CardHeader className="border-b border-border/70">
          <div className="flex items-center gap-2">
            <BellPlus className="h-5 w-5 text-primary" />
            <CardTitle>新建订阅</CardTitle>
          </div>
          <CardDescription>关键词、平台、触发策略和通知渠道决定了你的监测半径。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pt-6">
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">订阅名称</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：医疗谣言 / 突发事件 / 财经波动" />
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">关键词</div>
            <Input value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="多个关键词用逗号分隔" />
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">排除词</div>
            <Input value={excludeKeywords} onChange={(e) => setExcludeKeywords(e.target.value)} placeholder="例如：辟谣、官方通报" />
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">监测平台</div>
            <div className="flex flex-wrap gap-2">
              {PLATFORM_OPTIONS.map((platform) => (
                <Button
                  key={platform}
                  type="button"
                  size="sm"
                  variant={selectedPlatforms.includes(platform) ? 'default' : 'outline'}
                  onClick={() => togglePlatform(platform)}
                  className="rounded-full"
                >
                  {platform}
                </Button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">触发模式</div>
            <div className="flex flex-wrap gap-2">
              {TRIGGER_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  size="sm"
                  variant={triggerMode === option.value ? 'default' : 'outline'}
                  onClick={() => setTriggerMode(option.value)}
                  className="rounded-full"
                >
                  {option.label}
                </Button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">风险阈值</div>
            <Input type="number" min={0} max={100} value={riskThreshold} onChange={(e) => setRiskThreshold(e.target.value)} />
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground">通知渠道</div>
            <div className="flex flex-wrap gap-2">
              {CHANNEL_OPTIONS.map((channel) => (
                <Button
                  key={channel.value}
                  type="button"
                  size="sm"
                  variant={selectedChannels.includes(channel.value) ? 'default' : 'outline'}
                  onClick={() => toggleChannel(channel.value)}
                  className="rounded-full"
                >
                  {channel.label}
                </Button>
              ))}
            </div>
          </div>
          <Button onClick={handleCreate} disabled={submitting} className="w-full rounded-2xl">
            {submitting ? '创建中...' : '创建监测订阅'}
          </Button>
        </CardContent>
      </Card>

      <Card className="border-white/70 bg-[linear-gradient(155deg,rgba(255,255,255,0.82),rgba(245,249,252,0.82))]">
        <CardHeader className="border-b border-border/70">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>订阅编排</CardTitle>
              <CardDescription>启停、删除和观察当前监测规则的覆盖面。</CardDescription>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="outline">{stats.total} 总数</Badge>
              <Badge variant="outline" className="border-emerald-200 bg-emerald-500/10 text-emerald-700">{stats.active} 启用</Badge>
              <Badge variant="outline" className="border-slate-200 bg-slate-500/10 text-slate-700">{stats.muted} 停用</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 pt-6">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-28 w-full rounded-[1.25rem]" />)
          ) : items.length === 0 ? (
            <div className="rounded-[1.25rem] border border-dashed border-border/70 bg-white/60 px-4 py-10 text-center text-sm text-muted-foreground">
              还没有订阅。先在左侧创建一条监测规则。
            </div>
          ) : (
            items.map((item) => (
              <div key={item.id} className="rounded-[1.25rem] border border-white/70 bg-white/78 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={item.is_active ? 'default' : 'outline'}>
                        <BellRing className="h-3 w-3" />
                        {item.is_active ? '启用中' : '已停用'}
                      </Badge>
                      <Badge variant="outline" className="border-sky-200 bg-sky-500/10 text-sky-700">
                        {item.trigger_mode}
                      </Badge>
                      <Badge variant="outline" className="border-white/70 bg-[color:var(--panel-soft)]">
                        阈值 {item.risk_threshold}
                      </Badge>
                    </div>
                    <div className="text-base font-medium text-foreground">{item.name}</div>
                    <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span>关键词：{item.keywords.join('、')}</span>
                      <span>平台：{item.platforms.join('、') || '全部'}</span>
                    </div>
                    {item.exclude_keywords.length > 0 ? (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Filter className="h-3.5 w-3.5" />
                        排除：{item.exclude_keywords.join('、')}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={item.is_active ? 'outline' : 'default'}
                      onClick={() => handleToggleActive(item.id, !item.is_active)}
                    >
                      {item.is_active ? '停用' : '启用'}
                    </Button>
                    <Button type="button" size="sm" variant="outline" onClick={() => handleDelete(item.id)}>
                      <Trash2 className="mr-2 h-4 w-4" />
                      删除
                    </Button>
                  </div>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
