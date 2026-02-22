'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Download, FileJson, FileText, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { downloadJson, downloadMarkdown, type ExportData } from '@/lib/export';

interface ExportButtonProps {
  data: ExportData;
}

export function ExportButton({ data }: ExportButtonProps) {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);

  const handleExport = async (format: 'json' | 'md') => {
    setExporting(format);
    try {
      const timestamp = new Date().toISOString().slice(0, 10);
      const filename = `truthcast-report-${timestamp}`;
      
      if (format === 'json') {
        downloadJson(data, `${filename}.json`);
      } else {
        downloadMarkdown(data, `${filename}.md`);
      }
      
      setOpen(false);
    } finally {
      setExporting(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Download className="h-4 w-4 mr-2" />
          导出报告
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>导出报告</DialogTitle>
          <DialogDescription>选择导出格式</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-4">
          <Button
            variant="outline"
            className="justify-start"
            onClick={() => handleExport('json')}
            disabled={exporting !== null}
          >
            {exporting === 'json' ? (
              <Loader2 className="h-4 w-4 mr-3 animate-spin" />
            ) : (
              <FileJson className="h-4 w-4 mr-3" />
            )}
            JSON 格式
            <span className="ml-auto text-muted-foreground text-xs">完整数据</span>
          </Button>
          <Button
            variant="outline"
            className="justify-start"
            onClick={() => handleExport('md')}
            disabled={exporting !== null}
          >
            {exporting === 'md' ? (
              <Loader2 className="h-4 w-4 mr-3 animate-spin" />
            ) : (
              <FileText className="h-4 w-4 mr-3" />
            )}
            Markdown 格式
            <span className="ml-auto text-muted-foreground text-xs">可读性高</span>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
