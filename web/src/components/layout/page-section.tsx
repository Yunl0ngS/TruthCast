import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface PageSectionProps {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  muted?: boolean;
}

export function PageSection({
  title,
  description,
  actions,
  children,
  className,
  contentClassName,
  muted = false,
}: PageSectionProps) {
  return (
    <section
      className={cn(
        'rounded-[1.75rem] border px-4 py-5 shadow-[0_18px_40px_rgba(26,54,78,0.08)] sm:px-5 md:px-6 md:py-6',
        muted
          ? 'border-white/45 bg-white/58 backdrop-blur-lg'
          : 'border-white/65 bg-white/78 backdrop-blur-xl',
        className
      )}
    >
      {title || description || actions ? (
        <div className="mb-5 flex flex-col gap-4 border-b border-border/70 pb-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            {title ? (
              <h2 className="text-lg font-semibold tracking-[-0.02em] text-foreground md:text-[1.35rem]">
                {title}
              </h2>
            ) : null}
            {description ? (
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <div className={cn('space-y-4', contentClassName)}>{children}</div>
    </section>
  );
}
