import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface PageHeroProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  meta?: ReactNode;
  className?: string;
}

export function PageHero({
  eyebrow,
  title,
  description,
  actions,
  meta,
  className,
}: PageHeroProps) {
  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-[2rem] border border-white/65 bg-[linear-gradient(135deg,rgba(255,255,255,0.92),rgba(244,249,252,0.84))] px-5 py-6 shadow-[0_18px_48px_rgba(26,54,78,0.10)] backdrop-blur-xl sm:px-6 md:px-8 md:py-8',
        className
      )}
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(133,170,196,0.18),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(24,53,76,0.10),transparent_28%)]" />
      <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-3xl space-y-4">
          {eyebrow ? (
            <div className="inline-flex items-center rounded-full border border-[color:var(--border-strong)] bg-white/72 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-[color:var(--muted-strong)] shadow-[0_10px_28px_rgba(26,54,78,0.08)]">
              {eyebrow}
            </div>
          ) : null}
          <div className="space-y-3">
            <h1 className="max-w-3xl text-3xl font-semibold tracking-[-0.04em] text-foreground md:text-4xl lg:text-[2.8rem] lg:leading-[1.05]">
              {title}
            </h1>
            {description ? (
              <p className="max-w-2xl text-sm leading-7 text-muted-foreground md:text-base">
                {description}
              </p>
            ) : null}
          </div>
          {meta ? <div className="flex flex-wrap items-center gap-3">{meta}</div> : null}
        </div>

        {actions ? (
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
            {actions}
          </div>
        ) : null}
      </div>
    </section>
  );
}
