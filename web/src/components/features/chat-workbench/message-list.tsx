'use client';

import Link from 'next/link';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import type { ChatMessage } from '@/stores/chat-store';

export function MessageList({
  messages,
  onCommand,
}: {
  messages: ChatMessage[];
  onCommand?: (command: string) => void;
}) {
  return (
    <div className="space-y-3">
      {messages.map((m) => (
        <div
          key={m.id}
          className={cn(
            'rounded-lg border px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap',
            m.role === 'user' && 'bg-primary text-primary-foreground border-primary/30',
            m.role === 'assistant' && 'bg-background',
            m.role === 'system' && 'bg-muted'
          )}
        >
          <div className="text-xs opacity-70 mb-1">
            {m.role === 'user' ? '你' : m.role === 'assistant' ? '助手' : '系统'} ·{' '}
            {new Date(m.created_at).toLocaleString('zh-CN')}
          </div>
          <div>{m.content}</div>

          {m.references && m.references.length > 0 && (
            <div className="mt-2 rounded-md border bg-muted/40 p-2 space-y-1">
              <div className="text-xs font-medium text-muted-foreground">引用</div>
              {m.references.map((r) => (
                <div key={r.href} className="text-xs">
                  <Link href={r.href} className="underline">
                    {r.title}
                  </Link>
                  {r.description ? (
                    <div className="text-muted-foreground">{r.description}</div>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          {m.actions && m.actions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {m.actions.map((a, idx) => {
                if (a.type === 'link') {
                  return (
                    <Button key={`${a.href}_${idx}`} asChild size="sm" variant="secondary">
                      <Link href={a.href}>{a.label}</Link>
                    </Button>
                  );
                }
                return (
                  <Button
                    key={`${a.command}_${idx}`}
                    size="sm"
                    variant="outline"
                    onClick={() => onCommand?.(a.command)}
                    disabled={!onCommand}
                  >
                    {a.label}
                  </Button>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

