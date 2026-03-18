import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';
import { Header } from '@/components/layout';
import { PipelineHydrator } from '@/components/layout/pipeline-hydrator';
import { Toaster } from '@/components/ui/toaster';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'TruthCast 智能研判台',
  description: '虚假新闻检测 + 舆情预演智能体',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${geistSans.variable} ${geistMono.variable} min-h-screen bg-background font-sans text-foreground antialiased`}
      >
        <div className="relative min-h-screen overflow-x-clip">
          <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top_left,rgba(145,172,191,0.28),transparent_32%),radial-gradient(circle_at_top_right,rgba(28,64,92,0.08),transparent_26%),linear-gradient(180deg,rgba(248,251,253,0.94),rgba(236,243,247,0.92))]" />
          <Header />
          <PipelineHydrator />
          <main className="mx-auto flex w-full max-w-[1680px] flex-1 flex-col px-2.5 py-5 sm:px-4 md:px-5 md:py-8 xl:px-6">
            {children}
          </main>
          <Toaster />
        </div>
      </body>
    </html>
  );
}
