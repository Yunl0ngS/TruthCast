'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  FileSearch,
  History,
  LineChart,
  Home,
  Menu,
  FileText,
  MessageSquare,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
} from '@/components/ui/sheet';

const navItems = [
  { href: '/chat', label: '对话工作台', icon: MessageSquare },
  { href: '/', label: '任务输入', icon: Home },
  { href: '/result', label: '检测结果', icon: FileSearch },
  { href: '/simulation', label: '舆情预演', icon: LineChart },
  { href: '/content', label: '应对内容', icon: FileText },
  { href: '/history', label: '历史记录', icon: History },
];

export function Header() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const currentItem = navItems.find((item) => item.href === pathname);

  return (
    <header className="sticky top-0 z-50 w-full px-2.5 py-3 sm:px-4 md:px-5">
      <div className="mx-auto flex w-full max-w-[1680px] items-center justify-between gap-4 rounded-[1.6rem] border border-white/60 bg-[linear-gradient(135deg,rgba(255,255,255,0.80),rgba(245,249,252,0.64))] px-4 py-3 shadow-[0_18px_36px_rgba(26,54,78,0.10)] backdrop-blur-xl">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/" className="flex items-center gap-3 shrink-0 group">
            <div className="flex size-11 items-center justify-center rounded-2xl bg-[color:var(--panel-strong)] text-[color:var(--panel-strong-foreground)] shadow-[0_16px_32px_rgba(24,53,76,0.24)] transition-transform duration-200 group-hover:-translate-y-0.5">
              <FileSearch className="h-5 w-5" />
            </div>
            <div className="space-y-1">
              <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[color:var(--muted-strong)]">
                Response Cockpit
              </div>
              <div className="font-semibold tracking-[-0.03em] text-foreground">TruthCast</div>
            </div>
          </Link>
          <div className="hidden min-w-0 lg:block">
            <div className="text-xl font-medium text-foreground">
              {currentItem?.label ?? '智能研判工作台'}
            </div>
            {/* <div className="truncate text-xs text-muted-foreground">
              围绕风险判断、证据依据与舆情应对的统一工作台
            </div> */}
          </div>
        </div>

        <nav className="hidden lg:flex items-center gap-1 rounded-2xl border border-white/60 bg-white/56 p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.4)]">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'bg-[color:var(--panel-strong)] text-[color:var(--panel-strong-foreground)] shadow-[0_10px_24px_rgba(24,53,76,0.20)]'
                    : 'text-muted-foreground hover:bg-white/80 hover:text-foreground'
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="hidden md:flex items-center gap-2">
          <div className="rounded-2xl border border-white/60 bg-white/58 px-3 py-2 text-right shadow-[0_10px_24px_rgba(26,54,78,0.08)]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--muted-strong)]">
              当前页面
            </div>
            <div className="text-sm font-medium text-foreground">
              {currentItem?.label ?? '任务输入'}
            </div>
          </div>
        </div>

        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild className="lg:hidden">
            <Button variant="outline" size="icon" className="shrink-0">
              <Menu className="h-5 w-5" />
              <span className="sr-only">打开菜单</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="right" className="w-[300px] border-white/60 bg-[linear-gradient(180deg,rgba(246,250,252,0.96),rgba(236,243,247,0.94))] pt-12 backdrop-blur-xl">
            <SheetTitle className="sr-only">导航菜单</SheetTitle>
            <div className="mb-6 flex items-center gap-3 px-4">
              <div className="flex size-10 items-center justify-center rounded-2xl bg-[color:var(--panel-strong)] text-[color:var(--panel-strong-foreground)] shadow-[0_16px_32px_rgba(24,53,76,0.22)]">
                <FileSearch className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[color:var(--muted-strong)]">
                  Response Cockpit
                </div>
                <div className="font-semibold tracking-[-0.03em] text-foreground">TruthCast</div>
              </div>
            </div>
            <nav className="flex flex-col space-y-2">
              {navItems.map((item) => {
                const Icon = item.icon;
                const isActive = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={isActive ? 'page' : undefined}
                    onClick={() => setOpen(false)}
                    className={cn(
                      'mx-2 flex items-center gap-3 rounded-2xl px-4 py-3 text-base font-medium transition-all duration-200',
                      isActive
                        ? 'bg-[color:var(--panel-strong)] text-[color:var(--panel-strong-foreground)] shadow-[0_14px_28px_rgba(24,53,76,0.18)]'
                        : 'text-foreground/76 hover:bg-white/76'
                    )}
                  >
                    <Icon className="h-5 w-5" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  );
}
