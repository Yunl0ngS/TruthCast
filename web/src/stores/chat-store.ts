import { create } from 'zustand';

export type ChatRole = 'user' | 'assistant' | 'system';

export type ChatAction =
  | {
      type: 'link';
      label: string;
      href: string;
    }
  | {
      type: 'command';
      label: string;
      command: string;
    };

export type ChatReference = {
  title: string;
  href: string;
  description?: string;
};

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  created_at: string;
  actions?: ChatAction[];
  references?: ChatReference[];
}

interface ChatState {
  session_id: string;
  messages: ChatMessage[];
  is_streaming: boolean;
  setStreaming: (value: boolean) => void;
  setSessionId: (sessionId: string) => void;
  addMessage: (
    role: ChatRole,
    content: string,
    extra?: Pick<ChatMessage, 'actions' | 'references'>
  ) => string;
  updateMessage: (id: string, patch: Partial<Pick<ChatMessage, 'content' | 'actions' | 'references'>>) => void;
  appendToMessage: (id: string, delta: string) => void;
  reset: () => void;
}

function newSessionId() {
  return `chat_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function newMessageId() {
  return `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export const useChatStore = create<ChatState>((set) => ({
  session_id: newSessionId(),
  messages: [
    {
      id: newMessageId(),
      role: 'assistant',
      content:
        '这里是“对话工作台”首版：支持用命令快速驱动现有分析流水线。\n\n- 直接输入待分析文本并发送：会自动启动分析\n- 或使用 /analyze <文本>\n- /retry_failed 重试失败阶段\n- /retry <phase> 例如 /retry report\n\n后续会接入后端对话编排与真正的流式回答。',
      created_at: new Date().toISOString(),
      actions: [
        { type: 'link', label: '打开检测结果', href: '/result' },
        { type: 'link', label: '打开舆情预演', href: '/simulation' },
        { type: 'link', label: '打开应对内容', href: '/content' },
        { type: 'command', label: '重试失败阶段', command: '/retry_failed' },
      ],
    },
  ],
  is_streaming: false,
  setStreaming: (value) => set({ is_streaming: value }),
  setSessionId: (sessionId) => set({ session_id: sessionId }),
  addMessage: (role, content, extra) => {
    const id = newMessageId();
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id,
          role,
          content,
          created_at: new Date().toISOString(),
          ...(extra ?? {}),
        },
      ],
    }));
    return id;
  },
  updateMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    })),
  appendToMessage: (id, delta) =>
    set((state) => ({
      messages: state.messages.map((m) => (m.id === id ? { ...m, content: m.content + delta } : m)),
    })),
  reset: () =>
    set({
      session_id: newSessionId(),
      messages: [],
      is_streaming: false,
    }),
}));

