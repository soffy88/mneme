"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { chatTurn, getStudentId, getToken, redirectToLogin } from "@/lib/mcp";
import { SaveToNotebook } from "@/components/SaveToNotebook";
import {
  OCard,
  OCardHeader,
  OCardTitle,
  OButton,
  OInput,
  OSelect,
  OSelectContent,
  OSelectItem,
  OSelectTrigger,
  OSelectValue,
  OAvatar,
  OBadge,
} from "@helios/blocks";

interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  kc_id?: string;
  question?: string;
}

interface ChatTurnReq {
  student_id: string;
  message: string;
  history: ChatMessage[];
  persona_slug?: string;
  kc_ids?: string[];
}

interface ChatTurnRes {
  reply: string;
  status?: string;
  action?: "goto_mastery_path" | "continue";
  kc_hint?: string;
  kc_ids?: string[];
  tools_used?: string[];
  metadata?: Record<string, unknown>;
}

const PERSONAS = [
  { slug: "encouraging-buddy", name: "鼓励型伙伴", description: "耐心温和，多鼓励" },
  { slug: "brisk-coach", name: "干脆型教练", description: "简洁明快，注重准确" },
  { slug: "curious-explorer", name: "好奇探索者", description: "爱打比方，爱提问" },
];

function formatTime(date: Date) {
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "你好！我是你的学习助手。有什么想聊的吗？" },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [persona, setPersona] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage: ChatMessage = { role: "user", content: input.trim() };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      // Get student ID from localStorage or auth context
      const studentId = getStudentId();
      if (!getToken() || !studentId) {
        redirectToLogin();
        throw new Error("未登录，请先登录");
      }

      const reqBody: ChatTurnReq = {
        student_id: studentId,
        message: userMessage.content,
        history: messages.map((m) => ({ role: m.role, content: m.content })),
        persona_slug: persona,
      };

      const data = await chatTurn<ChatTurnRes>(reqBody);

      // Add assistant response
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply,
          kc_id: data.kc_ids?.[0] ?? data.kc_hint ?? undefined,
          question: userMessage.content,
        },
      ]);

      // Handle practice redirect
      if (data.action === "goto_mastery_path" && data.kc_hint) {
        const confirmRedirect = window.confirm(
          `检测到你想练习「${data.kc_hint}」，是否跳转到练习页面？`
        );
        if (confirmRedirect) {
          window.location.href = `/studio/learn?kc=${encodeURIComponent(data.kc_hint)}`;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto max-w-2xl h-[calc(100vh-120px)] flex flex-col" data-testid="chat-root">
      {/* Header with persona selector */}
      <div className="flex items-center justify-between mb-4 p-4 border-b">
        <h1 className="text-xl font-semibold">对话</h1>
        <div className="relative">
          <OSelect
            value={persona ?? ""}
            onValueChange={(v) => setPersona(v || undefined)}
          >
            <OSelectTrigger className="w-40">
              <OSelectValue placeholder="选择人格" />
            </OSelectTrigger>
            <OSelectContent>
              {PERSONAS.map((p) => (
                <OSelectItem key={p.slug} value={p.slug}>
                  {p.name}
                </OSelectItem>
              ))}
            </OSelectContent>
          </OSelect>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollAreaRef}
        className="flex-1 overflow-y-auto p-4 space-y-4"
        style={{ scrollBehavior: "smooth" }}
      >
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] px-4 py-2 rounded-2xl ${
                msg.role === "user"
                  ? "bg-blue-600 text-white rounded-tr-none"
                  : "bg-gray-100 text-gray-900 rounded-tl-none"
              }`}
            >
              <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
              {msg.role === "assistant" && (
                <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                  <OAvatar
                    size="xs"
                    src="/logo.png"
                    name="Aria"
                    className="rounded-full"
                  />
                  <span className="font-medium">Aria</span>
                  {msg.role === "assistant" && (
                    <OBadge variant="outline" className="text-xs">
                      AI
                    </OBadge>
                  )}
                </div>
              )}
              {msg.role === "assistant" && idx > 0 && msg.content.trim() && (
                <div className="mt-2">
                  <SaveToNotebook
                    record={{
                      source_type: "chat",
                      content: msg.content,
                      title: msg.question ? msg.question.slice(0, 60) : null,
                      kc_id: msg.kc_id ?? null,
                      metadata: persona ? { persona } : {},
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Error toast */}
      {error && (
        <div className="mx-4 mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-2 text-red-500 hover:text-red-700 font-medium"
          >
            关闭
          </button>
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t">
        <div className="flex gap-2">
          <OInput
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入消息..."
            className="flex-1"
            disabled={loading}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e as unknown as React.FormEvent);
              }
            }}
          />
          <OButton type="submit" disabled={loading || !input.trim()}>
            {loading ? "发送中..." : "发送"}
          </OButton>
        </div>
        <p className="text-xs text-gray-500 mt-2 text-center">
          按 Enter 发送，Shift+Enter 换行
        </p>
      </form>
    </main>
  );
}
