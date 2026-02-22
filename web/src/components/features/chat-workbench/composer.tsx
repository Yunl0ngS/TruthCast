'use client';

import { useCallback, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

export function Composer({
  disabled,
  onSend,
  placeholder,
  quickActions,
}: {
  disabled?: boolean;
  onSend: (text: string) => void;
  placeholder?: string;
  quickActions?: Array<{ label: string; onClick: () => void }>; 
}) {
  const [value, setValue] = useState('');

  const send = useCallback(() => {
    const t = value.trim();
    if (!t) return;
    onSend(t);
    setValue('');
  }, [onSend, value]);

  return (
    <div className="space-y-2">
      {quickActions && quickActions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {quickActions.map((a) => (
            <Button
              key={a.label}
              type="button"
              variant="secondary"
              size="sm"
              onClick={a.onClick}
              disabled={disabled}
            >
              {a.label}
            </Button>
          ))}
        </div>
      )}

      {/* 输入框 + 发送按钮：始终同一行（不换行） */}
      <div className="flex flex-nowrap items-center gap-2">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder ?? '输入文本或命令，例如 /analyze <文本>'}
          rows={2}
          className={cn(
            // Textarea 组件自带 w-full，这里覆写为 w-auto + flex 伸缩，确保与按钮同行
            'resize-none flex-1 min-w-0 w-auto',
            disabled && 'opacity-70'
          )}
          disabled={disabled}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              send();
            }
          }}
        />
        <Button
          type="button"
          onClick={send}
          disabled={disabled || !value.trim()}
          className="shrink-0 whitespace-nowrap"
        >
          发送
        </Button>
      </div>
      <div className="text-xs text-muted-foreground">
        Ctrl 或 Cmd + Enter 发送。支持 /analyze、/retry_failed、/retry &lt;phase&gt;。
      </div>
    </div>
  );
}

