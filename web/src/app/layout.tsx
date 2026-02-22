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
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen bg-background`}
      >
        <Header />
        <PipelineHydrator />
        <main className="container mx-auto py-4 md:py-6 max-w-7xl px-2 sm:px-4">{children}</main>
        <Toaster />
      </body>
    </html>
  );
}
