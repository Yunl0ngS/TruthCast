'use client';

import { useState } from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';
import remarkGfm from 'remark-gfm';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { PlatformScript, Platform } from '@/types';

interface PlatformScriptsProps {
  scripts: PlatformScript[];
  onCopy?: (text: string) => void;
}

const PLATFORM_INFO: Record<Platform, { name: string; icon: string; color: string }> = {
  weibo: { name: '微博', icon: '📱', color: 'bg-orange-500/10 text-orange-600 border-orange-500/20' },
  wechat: { name: '微信公众号', icon: '💬', color: 'bg-green-500/10 text-green-600 border-green-500/20' },
  short_video: { name: '短视频口播', icon: '🎬', color: 'bg-purple-500/10 text-purple-600 border-purple-500/20' },
  news: { name: '新闻通稿', icon: '📰', color: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
  official: { name: '官方声明', icon: '📋', color: 'bg-red-500/10 text-red-600 border-red-500/20' },
  xiaohongshu: { name: '小红书', icon: '📕', color: 'bg-pink-500/10 text-pink-600 border-pink-500/20' },
  douyin: { name: '抖音', icon: '🎵', color: 'bg-slate-500/10 text-slate-600 border-slate-500/20' },
  kuaishou: { name: '快手', icon: '⚡', color: 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20' },
  bilibili: { name: 'B站', icon: '📺', color: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/20' },
};

const markdownComponents = {
  p: ({ children }: { children?: ReactNode }) => (
    <p className="m-0 break-words">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="list-disc list-inside space-y-1 m-0 pl-5">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="list-decimal list-inside space-y-1 m-0 pl-5">{children}</ol>
  ),
  li: ({ children }: { children?: ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  code: ({ inline, children }: { inline?: boolean; children?: ReactNode }) =>
    inline ? (
      <code className="font-mono bg-muted/40 px-1 py-0.5 rounded">{children}</code>
    ) : (
      <code className="font-mono block bg-muted/40 px-3 py-2 rounded w-full overflow-x-auto whitespace-pre">
        {children}
      </code>
    ),
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a
      className="text-blue-600 underline"
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      {children}
    </a>
  ),
};

function MarkdownRenderer({ content }: { content?: string | null }) {
  const normalized = content ?? '';
  if (!normalized.trim()) {
    return (
      <div className="rounded-md bg-muted/50 p-4 text-sm text-muted-foreground">
        暂无内容
      </div>
    );
  }

  return (
    <div className="rounded-md bg-muted/50 p-4 text-sm leading-relaxed text-foreground space-y-2">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={markdownComponents}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}

export function PlatformScripts({ scripts, onCopy }: PlatformScriptsProps) {
  const [selectedPlatform, setSelectedPlatform] = useState<Platform | null>(
    scripts[0]?.platform || null
  );
  const [copied, setCopied] = useState(false);

  const selectedScript = scripts.find(s => s.platform === selectedPlatform);

  const handleCopy = () => {
    if (selectedScript) {
      const textToCopy = selectedScript.content ?? '';
      navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      onCopy?.(textToCopy);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (!scripts || scripts.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">多平台话术</CardTitle>
          {selectedScript && (
            <Button 
              variant="outline" 
              size="sm" 
              onClick={handleCopy}
            >
              {copied ? '已复制 ✓' : '复制当前'}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {/* 平台选择 */}
        <div className="flex flex-wrap gap-2 mb-4">
          {scripts.map(script => {
            const info = PLATFORM_INFO[script.platform];
            const isSelected = selectedPlatform === script.platform;
            return (
              <Button
                key={script.platform}
                variant={isSelected ? 'default' : 'outline'}
                size="sm"
                className={`gap-1 ${isSelected ? '' : info?.color || ''}`}
                onClick={() => setSelectedPlatform(script.platform)}
              >
                <span>{info?.icon || '📝'}</span>
                {info?.name || script.platform}
              </Button>
            );
          })}
        </div>

        {/* 内容展示 */}
        {selectedScript && (
          <div className="space-y-3">
            {/* 内容 */}
            <MarkdownRenderer content={selectedScript.content} />

            {/* 话题标签 */}
            {selectedScript.hashtags && selectedScript.hashtags.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {selectedScript.hashtags.map((tag, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}

            {/* 发布建议 */}
            {selectedScript.tips && selectedScript.tips.length > 0 && (
              <div className="text-xs text-muted-foreground space-y-1">
                <div className="font-medium">发布建议：</div>
                <ul className="list-disc list-inside space-y-0.5">
                  {selectedScript.tips.map((tip, i) => (
                    <li key={i}>{tip}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* 预计阅读时间 */}
            {selectedScript.estimated_read_time && (
              <div className="text-xs text-muted-foreground">
                预计阅读时长：{selectedScript.estimated_read_time}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
