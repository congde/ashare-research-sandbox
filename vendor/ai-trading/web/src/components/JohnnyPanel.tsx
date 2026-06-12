import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Button, Input, Spin, Tooltip, Drawer, Form, Checkbox, Typography, message as antMessage, Select, Popconfirm, Tag, Empty, Tabs } from "antd";
import {
  UserOutlined,
  SendOutlined,
  DeleteOutlined,
  LoadingOutlined,
  SettingOutlined,
  CloseOutlined,
  SwapOutlined,
  RobotOutlined,
  BulbOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
  DownOutlined,
  UpOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { assistantApi, agentApi, skillApi, type AssistantConfig } from "../api/services";
import { authStorage } from "../utils/auth-storage";
import type { RoleSkill } from "../types";
import { useCurrentUser } from "../contexts/UserContext";

const { TextArea } = Input;
const { Text } = Typography;

const MIN_WIDTH = 320;
const MAX_WIDTH = 780;
const DEFAULT_WIDTH = 420;

const ALL_TOOLS: { name: string; label: string }[] = [
  { name: "get_wallet_balance", label: "查询钱包余额" },
  { name: "get_transactions", label: "获取交易记录" },
  { name: "list_tasks", label: "获取任务列表" },
  { name: "get_contracts", label: "查询合约" },
  { name: "list_projects", label: "查看项目列表" },
  { name: "create_task", label: "创建任务" },
  { name: "get_analytics", label: "平台数据统计" },
  { name: "list_my_agents", label: "Agent 列表" },
  { name: "update_task", label: "更新任务" },
  { name: "delete_task", label: "删除任务" },
  { name: "update_contract", label: "操作合约" },
];

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  tool_calls_made?: string[];
  thinking?: string[];
  streaming?: boolean;
}

const QUICK_ACTIONS: Record<string, string[]> = {
  admin: ["查看平台统计", "查我的余额", "列出最近任务", "我的合约"],
  employer: ["查我的余额", "列出我的项目", "最近任务状态", "查合约"],
  operator: ["我的 Agent 列表", "查我的余额", "最近任务状态", "平台统计"],
  default: ["查我的余额", "最近任务状态", "查合约"],
};

function getQuickActions(roles: string[]): string[] {
  if (roles.includes("admin")) return QUICK_ACTIONS.admin;
  if (roles.includes("employer")) return QUICK_ACTIONS.employer;
  if (roles.includes("operator")) return QUICK_ACTIONS.operator;
  return QUICK_ACTIONS.default;
}

const WELCOME: Message = {
  role: "assistant",
  content:
    "你好！我是 Johnny，你的智能平台助手 👋\n\n我可以帮你查询账户余额、管理任务和项目、查看合约及结算记录。试着问我一些问题吧！",
};

/** Johnny avatar */
function JohnnyAvatar({ size = 36 }: { size?: number }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        flexShrink: 0,
        boxShadow: `0 0 ${size / 2}px rgba(0,212,255,0.45)`,
        overflow: "hidden",
        border: "1.5px solid rgba(0,212,255,0.4)",
      }}
    >
      <img
        src="/johnny-avatar-2.png"
        alt="Johnny"
        style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "center top" }}
      />
    </div>
  );
}

interface JohnnyPanelProps {
  /** Controlled mode: parent manages open state */
  open?: boolean;
  onClose?: () => void;
  /** Uncontrolled mode: panel manages its own state (default) */
  defaultOpen?: boolean;
}

interface AgentOption {
  id: string;
  name: string;
  role_type?: string;
}

export default function JohnnyPanel({ open: openProp, onClose, defaultOpen = false }: JohnnyPanelProps) {
  const { currentUser } = useCurrentUser();
  const roles = currentUser?.roles ?? [];

  const isControlled = openProp !== undefined;
  const [openState, setOpenState] = useState(defaultOpen);
  const open = isControlled ? openProp : openState;
  const setOpen = (v: boolean) => {
    if (!isControlled) setOpenState(v);
    if (!v) onClose?.();
  };
  const [panelWidth, setPanelWidth] = useState(MAX_WIDTH);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [config, setConfig] = useState<AssistantConfig | null>(null);
  const [configSaving, setConfigSaving] = useState(false);
  const [form] = Form.useForm();
  const bottomRef = useRef<HTMLDivElement>(null);
  const resizingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(DEFAULT_WIDTH);

  // Agent mode state
  const [selectedAgent, setSelectedAgent] = useState<AgentOption | null>(null);
  const [agentOptions, setAgentOptions] = useState<AgentOption[]>([]);
  const [agentMessages, setAgentMessages] = useState<Map<string, Message[]>>(new Map());

  // Memory/skill panel state (Agent mode only)
  const [infoPanelOpen, setInfoPanelOpen] = useState(false);
  const [memories, setMemories] = useState<{ episodic: Array<{ id: string; episode_type: string; title: string; content: string; importance: number; created_at: string | null }>; semantic: Array<{ id: string; category: string; title: string; content: string; created_at: string | null }> }>({ episodic: [], semantic: [] });
  const [skills, setSkills] = useState<RoleSkill[]>([]);
  const [memoriesLoading, setMemoriesLoading] = useState(false);
  const [skillsLoading, setSkillsLoading] = useState(false);

  // Load memories + skills when agent changes
  useEffect(() => {
    if (!selectedAgent) { setMemories({ episodic: [], semantic: [] }); setSkills([]); return; }
    setMemoriesLoading(true);
    agentApi.listMemories(selectedAgent.id)
      .then((r) => setMemories(r.data))
      .catch(() => setMemories({ episodic: [], semantic: [] }))
      .finally(() => setMemoriesLoading(false));

    setSkillsLoading(true);
    // Use agent's role_id to fetch skills — get agent detail first
    (async () => {
      try {
        const r = await agentApi.get(selectedAgent.id);
        const roleId = r.data.role_id;
        if (!roleId) {
          setSkills([]);
          return;
        }
        const sr = await skillApi.listByRole(roleId);
        setSkills(sr.data.items ?? []);
      } catch {
        setSkills([]);
      } finally {
        setSkillsLoading(false);
      }
    })();
  }, [selectedAgent?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDeleteMemory = async (memoryId: string) => {
    if (!selectedAgent) return;
    await agentApi.deleteMemory(selectedAgent.id, memoryId);
    setMemories((prev) => ({
      episodic: prev.episodic.filter((e) => e.id !== memoryId),
      semantic: prev.semantic.filter((s) => s.id !== memoryId),
    }));
  };

  const handleUnbindSkill = async (skillId: string) => {
    if (!selectedAgent) return;
    const agentData = await agentApi.get(selectedAgent.id);
    const roleId = agentData.data.role_id;
    if (roleId) {
      await skillApi.unbindFromRole(roleId, skillId);
      setSkills((prev) => prev.filter((s) => s.skill_id !== skillId));
    }
  };

  // Load history only when panel is first opened
  useEffect(() => {
    if (!open || historyLoaded) return;
    setHistoryLoaded(true);
    assistantApi.history({ limit: 30 }).then((res) => {
      const hist = res.data.messages;
      if (hist.length > 0) {
        setMessages([WELCOME, ...(hist as Message[])]);
      }
    }).catch(() => {});
  }, [open, historyLoaded]);

  // Load employee agents for agent selector — try employees first, fallback to all agents
  useEffect(() => {
    if (!open) return;
    agentApi.listEmployees({ limit: 200 })
      .then((r) => {
        const items = r.data?.items ?? [];
        if (items.length > 0) {
          setAgentOptions(items.map((a) => ({
            id: a.id, name: a.name,
            role_type: ((a.boot_config?.role_type as string) || ""),
          })));
        } else {
          // Fallback: load all agents
          agentApi.list({ limit: 50 })
            .then((r2) => {
              const all = r2.data?.items ?? [];
              setAgentOptions(all.map((a) => ({
                id: a.id, name: a.name,
                role_type: ((a.boot_config?.role_type as string) || ""),
              })));
            })
            .catch(() => {});
        }
      })
      .catch(() => {
        // employees endpoint failed, try all agents
        agentApi.list({ limit: 50 })
          .then((r2) => {
            const all = r2.data?.items ?? [];
            setAgentOptions(all.map((a) => ({
              id: a.id, name: a.name,
              role_type: ((a.boot_config?.role_type as string) || ""),
            })));
          })
          .catch(() => {});
      });
  }, [open]);

  // Get current messages based on mode. ``useMemo`` so the
  // useEffect below sees a stable reference (don't recompute on
  // every parent re-render).
  const currentMessages = useMemo(() => (
    selectedAgent
      ? (agentMessages.get(selectedAgent.id) ?? [
          { role: "assistant" as const, content: `你好，我是 ${selectedAgent.name}，有什么可以帮你的吗？` },
        ])
      : messages
  ), [selectedAgent, agentMessages, messages]);

  // Auto-scroll on new messages
  useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [currentMessages, open]);

  // Resize drag handlers
  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    resizingRef.current = true;
    startXRef.current = e.clientX;
    startWidthRef.current = panelWidth;
    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
  }, [panelWidth]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!resizingRef.current) return;
      const delta = startXRef.current - e.clientX;
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidthRef.current + delta));
      setPanelWidth(next);
    };
    const onMouseUp = () => {
      if (!resizingRef.current) return;
      resizingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) return;
    const userMsg: Message = { role: "user", content: text.trim() };
    setMessages((prev) => [...prev, userMsg, { role: "assistant", content: "", thinking: [], streaming: true }]);
    setInput("");
    setLoading(true);

    try {
      const token = authStorage.getToken() || "";
      const response = await fetch("/api/v1/assistant/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ message: text.trim() }),
      });

      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accContent = "";
      let thinking: string[] = [];

      setLoading(false);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop()!;

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "thinking") {
              thinking = [...thinking, event.content];
              setMessages((prev) => {
                const next = [...prev];
                next[next.length - 1] = { ...next[next.length - 1], thinking };
                return next;
              });
            } else if (event.type === "token") {
              accContent += event.content;
              setMessages((prev) => {
                const next = [...prev];
                next[next.length - 1] = { ...next[next.length - 1], content: accContent };
                return next;
              });
            } else if (event.type === "done") {
              setMessages((prev) => {
                const next = [...prev];
                next[next.length - 1] = {
                  ...next[next.length - 1],
                  content: accContent,
                  tool_calls_made: event.tool_calls_made ?? [],
                  thinking,
                  streaming: false,
                };
                return next;
              });
            } else if (event.type === "error") {
              setMessages((prev) => {
                const next = [...prev];
                next[next.length - 1] = { ...next[next.length - 1], content: event.content, streaming: false };
                return next;
              });
            }
          } catch { /* ignore parse errors */ }
        }
      }
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { ...last, content: "抱歉，出现了一个错误，请稍后重试。", streaming: false };
        }
        return next;
      });
    } finally {
      setLoading(false);
    }
  };

  const sendAgentMessage = async (text: string) => {
    if (!text.trim() || loading || !selectedAgent) return;
    const agentId = selectedAgent.id;
    const prev = agentMessages.get(agentId) ?? [{ role: "assistant" as const, content: `你好，我是 ${selectedAgent.name}，有什么可以帮你的吗？` }];
    const userMsg: Message = { role: "user", content: text.trim() };
    const updated = [...prev, userMsg];
    setAgentMessages((m) => new Map(m).set(agentId, [...updated, { role: "assistant", content: "", streaming: true }]));
    setInput("");
    setLoading(true);

    try {
      const histMsgs = updated
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.content }));

      const token = authStorage.getToken() || "";
      const response = await fetch(`/api/v1/agents/${agentId}/test-chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ messages: histMsgs }),
      });

      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let accContent = "";

      setLoading(false);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop()!;

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === "token") {
              accContent += event.content;
              setAgentMessages((m) => {
                const cur = m.get(agentId) ?? [];
                const next = [...cur];
                next[next.length - 1] = { ...next[next.length - 1], content: accContent };
                return new Map(m).set(agentId, next);
              });
            } else if (event.type === "done") {
              setAgentMessages((m) => {
                const cur = m.get(agentId) ?? [];
                const next = [...cur];
                next[next.length - 1] = { ...next[next.length - 1], content: accContent, streaming: false };
                return new Map(m).set(agentId, next);
              });
            } else if (event.type === "error") {
              setAgentMessages((m) => {
                const cur = m.get(agentId) ?? [];
                const next = [...cur];
                next[next.length - 1] = { ...next[next.length - 1], content: event.content, streaming: false };
                return new Map(m).set(agentId, next);
              });
            }
          } catch { /* ignore parse errors */ }
        }
      }
    } catch {
      setAgentMessages((m) => {
        const cur = m.get(agentId) ?? [];
        const next = [...cur];
        next[next.length - 1] = { role: "assistant", content: "抱歉，出现了一个错误，请稍后重试。", streaming: false };
        return new Map(m).set(agentId, next);
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSend = (text: string) => {
    if (selectedAgent) sendAgentMessage(text);
    else sendMessage(text);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(input);
    }
  };

  const handleClearHistory = async () => {
    await assistantApi.clearHistory();
    setMessages([WELCOME]);
  };

  const openConfig = async () => {
    setConfigOpen(true);
    if (!config) {
      const res = await assistantApi.getConfig();
      setConfig(res.data);
      form.setFieldsValue({
        personality: res.data.personality,
        model: res.data.model || "",
        temperature: res.data.temperature,
        tools_default: res.data.role_tools.default || [],
        tools_employer: res.data.role_tools.employer || [],
        tools_operator: res.data.role_tools.operator || [],
        tools_admin: res.data.role_tools.admin || [],
      });
    }
  };

  const saveConfig = async () => {
    const values = form.getFieldsValue();
    setConfigSaving(true);
    try {
      const res = await assistantApi.updateConfig({
        personality: values.personality,
        model: values.model || null,
        temperature: values.temperature,
        role_tools: {
          default: values.tools_default || [],
          employer: values.tools_employer || [],
          operator: values.tools_operator || [],
          admin: values.tools_admin || [],
        },
      });
      setConfig(res.data);
      antMessage.success("配置已保存");
      setConfigOpen(false);
    } catch {
      antMessage.error("保存失败，请重试");
    } finally {
      setConfigSaving(false);
    }
  };

  const quickActions = getQuickActions(roles);

  return (
    <>
      {/* Panel */}
      <div
        style={{
          position: "relative",
          width: open ? panelWidth : 0,
          height: "100%",
          flexShrink: 0,
          transition: resizingRef.current ? "none" : "width 0.25s cubic-bezier(0.4,0,0.2,1)",
          overflow: "hidden",
          background: "#141929",
          borderLeft: open ? "1px solid rgba(34,211,238,0.3)" : "none",
          boxShadow: open ? "-6px 0 40px rgba(0,0,0,0.55)" : "none",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Resize handle — always rendered so cursor appears on hover even during transition */}
        <div
          onMouseDown={onResizeMouseDown}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: 5,
            height: "100%",
            cursor: "ew-resize",
            zIndex: 10,
            background: "transparent",
            transition: "background 0.15s",
            display: open ? "block" : "none",
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = "rgba(0,212,255,0.2)"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
        />
        {open && (
          <>

            {/* Panel header */}
            <div
              style={{
                flexShrink: 0,
                padding: "12px 14px 12px 16px",
                borderBottom: "1px solid rgba(255,255,255,0.08)",
                display: "flex",
                flexDirection: "column",
                gap: 8,
                background: selectedAgent
                  ? "linear-gradient(180deg, rgba(168,85,247,0.12) 0%, transparent 100%)"
                  : "linear-gradient(180deg, rgba(34,211,238,0.12) 0%, transparent 100%)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {selectedAgent ? (
                  <div style={{
                    width: 38, height: 38, borderRadius: "50%", flexShrink: 0,
                    background: "linear-gradient(135deg, rgba(168,85,247,0.3), rgba(34,211,238,0.2))",
                    border: "1.5px solid rgba(168,85,247,0.4)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    boxShadow: "0 0 16px rgba(168,85,247,0.3)",
                  }}>
                    <RobotOutlined style={{ fontSize: 18, color: "#a855f7" }} />
                  </div>
                ) : (
                  <JohnnyAvatar size={38} />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 15, color: "#e8f0ff", lineHeight: 1.3 }}>
                    {selectedAgent ? selectedAgent.name : "Johnny · 平台助手"}
                  </div>
                  <div style={{ fontSize: 11, color: "rgba(200,220,255,0.55)", marginTop: 2 }}>
                    {selectedAgent ? "数字员工 · 直接对话" : "账户 · 任务 · 合约 · 数据"}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
                  {!selectedAgent && roles.includes("admin") && (
                    <Tooltip title="配置 Johnny">
                      <Button
                        size="small" type="text" icon={<SettingOutlined />}
                        onClick={openConfig}
                        style={{ color: "rgba(200,220,255,0.6)" }}
                      />
                    </Tooltip>
                  )}
                  <Tooltip title="清空对话">
                    <Button
                      size="small" type="text" icon={<DeleteOutlined />}
                      onClick={() => {
                        if (selectedAgent) {
                          setAgentMessages((m) => { const n = new Map(m); n.delete(selectedAgent.id); return n; });
                        } else {
                          handleClearHistory();
                        }
                      }}
                      style={{ color: "rgba(200,220,255,0.6)" }}
                    />
                  </Tooltip>
                  <Tooltip title="关闭">
                    <Button
                      size="small" type="text" icon={<CloseOutlined />}
                      onClick={() => setOpen(false)}
                      style={{ color: "rgba(200,220,255,0.6)" }}
                    />
                  </Tooltip>
                </div>
              </div>

              {/* Agent selector — always shown */}
              <Select
                value={selectedAgent?.id ?? "__johnny__"}
                onChange={(v) => {
                  if (v === "__johnny__") setSelectedAgent(null);
                  else {
                    const agent = agentOptions.find((a) => a.id === v);
                    if (agent) setSelectedAgent(agent);
                  }
                }}
                size="small"
                style={{ width: "100%" }}
                suffixIcon={<SwapOutlined style={{ color: "rgba(200,220,255,0.5)" }} />}
                options={[
                  { value: "__johnny__", label: "Johnny（平台助手）" },
                  ...(agentOptions.length > 0
                    ? agentOptions.map((a) => ({
                        value: a.id,
                        label: `${a.name}${a.role_type ? ` · ${a.role_type}` : ""}`,
                      }))
                    : [{ value: "__no_agents__", label: "暂无可用数字员工", disabled: true }]
                  ),
                ]}
                dropdownStyle={{ background: "#1a2035" }}
              />
            </div>

            {/* Memory/Skill panel (Agent mode only) */}
            {selectedAgent && (
              <div style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                <div
                  onClick={() => setInfoPanelOpen(!infoPanelOpen)}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "6px 14px", cursor: "pointer", fontSize: 12, color: "rgba(200,220,255,0.6)",
                    background: "rgba(255,255,255,0.02)",
                  }}
                >
                  <span><BulbOutlined style={{ marginRight: 4 }} />记忆 · 技能</span>
                  {infoPanelOpen ? <UpOutlined style={{ fontSize: 10 }} /> : <DownOutlined style={{ fontSize: 10 }} />}
                </div>
                {infoPanelOpen && (
                  <div style={{ maxHeight: 260, overflowY: "auto", padding: "0 10px 10px" }}>
                    <Tabs size="small" defaultActiveKey="memory" items={[
                      {
                        key: "memory",
                        label: <span><ClockCircleOutlined /> 记忆 ({memories.episodic.length + memories.semantic.length})</span>,
                        children: memoriesLoading ? <Spin size="small" style={{ display: "block", margin: "12px auto" }} /> : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            {memories.episodic.length === 0 && memories.semantic.length === 0 && (
                              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无记忆" style={{ padding: 8 }} />
                            )}
                            {memories.episodic.map((e) => (
                              <div key={e.id} style={{
                                display: "flex", alignItems: "flex-start", gap: 6, padding: "6px 8px",
                                borderRadius: 6, background: "rgba(34,211,238,0.04)", border: "1px solid rgba(34,211,238,0.08)",
                                fontSize: 11,
                              }}>
                                <Tag color="cyan" style={{ fontSize: 9, margin: 0, flexShrink: 0 }}>{e.episode_type}</Tag>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ color: "rgba(255,255,255,0.8)", fontWeight: 500 }}>{e.title || e.content.slice(0, 40)}</div>
                                  {e.created_at && <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10 }}>{e.created_at.slice(0, 10)}</div>}
                                </div>
                                <Popconfirm title="删除该记忆？" onConfirm={() => handleDeleteMemory(e.id)} okText="删除" cancelText="取消">
                                  <Button size="small" type="text" danger icon={<DeleteOutlined />} style={{ fontSize: 10, padding: 0, height: 18 }} />
                                </Popconfirm>
                              </div>
                            ))}
                            {memories.semantic.map((s) => (
                              <div key={s.id} style={{
                                display: "flex", alignItems: "flex-start", gap: 6, padding: "6px 8px",
                                borderRadius: 6, background: "rgba(168,85,247,0.04)", border: "1px solid rgba(168,85,247,0.08)",
                                fontSize: 11,
                              }}>
                                <Tag color="purple" style={{ fontSize: 9, margin: 0, flexShrink: 0 }}>{s.category}</Tag>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ color: "rgba(255,255,255,0.8)", fontWeight: 500 }}>{s.title}</div>
                                  {s.created_at && <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10 }}>{s.created_at.slice(0, 10)}</div>}
                                </div>
                                <Popconfirm title="删除该记忆？" onConfirm={() => handleDeleteMemory(s.id)} okText="删除" cancelText="取消">
                                  <Button size="small" type="text" danger icon={<DeleteOutlined />} style={{ fontSize: 10, padding: 0, height: 18 }} />
                                </Popconfirm>
                              </div>
                            ))}
                          </div>
                        ),
                      },
                      {
                        key: "skills",
                        label: <span><ThunderboltOutlined /> 技能 ({skills.length})</span>,
                        children: skillsLoading ? <Spin size="small" style={{ display: "block", margin: "12px auto" }} /> : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            {skills.length === 0 && (
                              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无绑定技能" style={{ padding: 8 }} />
                            )}
                            {skills.map((s) => (
                              <div key={s.skill_id} style={{
                                display: "flex", alignItems: "center", gap: 6, padding: "6px 8px",
                                borderRadius: 6, background: "rgba(0,208,132,0.04)", border: "1px solid rgba(0,208,132,0.08)",
                                fontSize: 11,
                              }}>
                                <ThunderboltOutlined style={{ color: "#00d084", flexShrink: 0 }} />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ color: "rgba(255,255,255,0.8)", fontWeight: 500 }}>{s.skill_name}</div>
                                  <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10 }}>{s.skill_category}</div>
                                </div>
                                <Popconfirm title={`卸载「${s.skill_name}」？`} onConfirm={() => handleUnbindSkill(s.skill_id)} okText="卸载" cancelText="取消">
                                  <Button size="small" type="text" danger style={{ fontSize: 10, padding: "0 4px", height: 18 }}>卸载</Button>
                                </Popconfirm>
                              </div>
                            ))}
                            <Button type="dashed" size="small" icon={<PlusOutlined />} block
                              style={{ marginTop: 4, fontSize: 11, color: "rgba(200,220,255,0.5)" }}
                              onClick={() => antMessage.info("挂载技能功能即将上线")}>挂载更多技能</Button>
                          </div>
                        ),
                      },
                    ]} />
                  </div>
                )}
              </div>
            )}

            {/* Messages area */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "16px 14px 8px",
                display: "flex",
                flexDirection: "column",
                gap: 14,
              }}
            >
              {currentMessages.map((msg, i) => (
                <MessageBubble key={i} msg={msg} />
              ))}
              {loading && (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <JohnnyAvatar size={28} />
                  <div
                    style={{
                      background: "rgba(255,255,255,0.05)",
                      border: "1px solid rgba(255,255,255,0.08)",
                      borderRadius: "0 10px 10px 10px",
                      padding: "7px 12px",
                    }}
                  >
                    <Spin size="small" />
                    <span style={{ marginLeft: 8, color: "rgba(200,220,255,0.5)", fontSize: 12 }}>
                      {selectedAgent ? `${selectedAgent.name} 正在回复...` : "Johnny 正在思考..."}
                    </span>
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            {/* Quick action chips — Johnny mode only */}
            {!selectedAgent && (
            <div
              style={{
                flexShrink: 0,
                padding: "8px 14px 6px",
                display: "flex",
                flexWrap: "wrap",
                gap: 6,
                borderTop: "1px solid rgba(255,255,255,0.06)",
              }}
            >
              {quickActions.map((action) => (
                <button
                  key={action}
                  onClick={() => handleSend(action)}
                  disabled={loading}
                  style={{
                    background: "rgba(34,211,238,0.1)",
                    border: "1px solid rgba(34,211,238,0.3)",
                    borderRadius: 16,
                    padding: "3px 11px",
                    fontSize: 11,
                    color: "#7aaeff",
                    cursor: "pointer",
                    transition: "background 0.15s, color 0.15s",
                    whiteSpace: "nowrap",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "rgba(34,211,238,0.22)";
                    (e.currentTarget as HTMLButtonElement).style.color = "#a0c4ff";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "rgba(34,211,238,0.1)";
                    (e.currentTarget as HTMLButtonElement).style.color = "#7aaeff";
                  }}
                >
                  {action}
                </button>
              ))}
            </div>
            )}

            {/* Input area */}
            <div
              style={{
                flexShrink: 0,
                padding: "8px 14px 14px",
                display: "flex",
                gap: 8,
                alignItems: "flex-end",
              }}
            >
              <TextArea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入消息... (Enter 发送)"
                autoSize={{ minRows: 1, maxRows: 4 }}
                disabled={loading}
                style={{ flex: 1, borderRadius: 8, resize: "none", fontSize: 13 }}
              />
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={() => handleSend(input)}
                disabled={!input.trim() || loading}
                className="btn-gradient"
                style={{ height: 36, borderRadius: 8, flexShrink: 0, paddingInline: 14 }}
              />
            </div>
          </>
        )}
      </div>

      {/* Admin Config Drawer */}
      <Drawer
        title="Johnny 配置"
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        width={480}
        footer={
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button onClick={() => setConfigOpen(false)}>取消</Button>
            <Button type="primary" loading={configSaving} onClick={saveConfig} className="btn-gradient">保存</Button>
          </div>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item label="人格设定 (Personality)" name="personality">
            <TextArea rows={5} placeholder="描述 Johnny 的角色定位和行为准则..."
              style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12 }} />
          </Form.Item>
          <Form.Item label="模型 (留空使用平台默认)" name="model">
            <Input placeholder="如: minimax/MiniMax-M2.5 或留空" />
          </Form.Item>
          <div style={{ marginBottom: 16 }}>
            <Text style={{ color: "var(--text-2)", fontSize: 13, fontWeight: 600 }}>工具权限配置</Text>
            <Text style={{ color: "var(--text-3)", fontSize: 12, display: "block", marginTop: 2 }}>
              每个角色可使用的工具（叠加在默认工具之上）
            </Text>
          </div>
          {[
            { key: "tools_default", label: "默认（所有用户）" },
            { key: "tools_employer", label: "雇主 (employer) 额外工具" },
            { key: "tools_operator", label: "雇员 (operator) 额外工具" },
            { key: "tools_admin", label: "管理员 (admin) 额外工具" },
          ].map(({ key, label }) => (
            <Form.Item key={key} label={label} name={key}>
              <Checkbox.Group style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {ALL_TOOLS.map((t) => (
                  <Checkbox key={t.name} value={t.name} style={{ color: "var(--text-2)" }}>
                    <span style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12, color: "var(--cyan)" }}>{t.name}</span>
                    <span style={{ color: "var(--text-3)", marginLeft: 6, fontSize: 12 }}>{t.label}</span>
                  </Checkbox>
                ))}
              </Checkbox.Group>
            </Form.Item>
          ))}
        </Form>
      </Drawer>
    </>
  );
}

/** Parse <think>...</think> blocks from content, return { thinkText, displayContent } */
function parseThinkBlocks(content: string): { thinkText: string; displayContent: string } {
  // Match completed think blocks
  const thinkParts: string[] = [];
  let remaining = content;
  const completedRe = /<think>([\s\S]*?)<\/think>/g;
  let match;
  while ((match = completedRe.exec(content)) !== null) {
    thinkParts.push(match[1].trim());
  }
  remaining = remaining.replace(completedRe, "");

  // Match unclosed <think>... (still streaming)
  const openIdx = remaining.indexOf("<think>");
  if (openIdx !== -1) {
    thinkParts.push(remaining.slice(openIdx + 7).trim());
    remaining = remaining.slice(0, openIdx);
  }

  return { thinkText: thinkParts.join("\n"), displayContent: remaining.trim() };
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  if (isSystem) {
    return <div style={{ textAlign: "center", fontSize: 11, color: "rgba(200,220,255,0.4)" }}>{msg.content}</div>;
  }

  // Parse think blocks from assistant content
  const { thinkText, displayContent } = !isUser ? parseThinkBlocks(msg.content) : { thinkText: "", displayContent: msg.content };

  return (
    <div style={{ display: "flex", flexDirection: isUser ? "row-reverse" : "row", alignItems: "flex-start", gap: 8 }}>
      {/* Avatar */}
      {isUser ? (
        <div style={{
          width: 28, height: 28, borderRadius: "50%",
          background: "rgba(255,255,255,0.1)",
          border: "1px solid rgba(255,255,255,0.15)",
          display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>
          <UserOutlined style={{ fontSize: 13, color: "rgba(200,220,255,0.8)" }} />
        </div>
      ) : (
        <JohnnyAvatar size={28} />
      )}

      {/* Bubble + thinking */}
      <div style={{ maxWidth: "78%", display: "flex", flexDirection: "column", gap: 4 }}>
        {/* Thinking steps (tool calls) */}
        {!isUser && msg.thinking && msg.thinking.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginBottom: 2 }}>
            {msg.thinking.map((step, i) => {
              const isLast = i === msg.thinking!.length - 1;
              const isActive = msg.streaming && isLast;
              return (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 5, fontSize: 10,
                  color: isActive ? "#00d4ff" : "rgba(200,220,255,0.35)",
                  transition: "color 0.3s",
                }}>
                  {isActive
                    ? <LoadingOutlined style={{ fontSize: 9, color: "#00d4ff" }} spin />
                    : <span style={{ fontSize: 9, color: "#4ade80" }}>✓</span>}
                  <span style={{ fontFamily: "var(--font-mono, monospace)" }}>
                    {isActive ? `正在${step}...` : `${step}完成`}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* LLM think block — separate bubble */}
        {!isUser && thinkText && (
          <div style={{
            background: "rgba(168,85,247,0.06)",
            border: "1px solid rgba(168,85,247,0.15)",
            borderRadius: "0 8px 8px 8px",
            padding: "6px 10px",
            fontSize: 11,
            color: "rgba(200,220,255,0.45)",
            lineHeight: 1.5,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}>
            <span style={{ fontSize: 10, color: "rgba(168,85,247,0.7)", fontWeight: 600, marginRight: 4 }}>
              {msg.streaming && !displayContent ? <><LoadingOutlined spin style={{ fontSize: 9, marginRight: 3 }} />思考中</> : "💭 思考"}
            </span>
            {thinkText}
          </div>
        )}

        {/* Message bubble */}
        {(displayContent || (!thinkText && msg.streaming)) && (
          <div style={{
            background: isUser ? "rgba(34,211,238,0.2)" : "rgba(255,255,255,0.05)",
            border: isUser ? "1px solid rgba(34,211,238,0.4)" : "1px solid rgba(255,255,255,0.08)",
            borderRadius: isUser ? "10px 0 10px 10px" : "0 10px 10px 10px",
            padding: "8px 12px",
            fontSize: 13,
            color: "#dce8ff",
            lineHeight: 1.65,
            wordBreak: "break-word",
          }}>
            {isUser ? (
              <span style={{ whiteSpace: "pre-wrap" }}>{displayContent}</span>
            ) : (
              <div className="md-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent}</ReactMarkdown>
                {msg.streaming && (
                  <span style={{
                    display: "inline-block", width: 2, height: "1em",
                    background: "#00d4ff", marginLeft: 2, verticalAlign: "text-bottom",
                    animation: "blink 0.8s step-end infinite",
                  }} />
                )}
              </div>
            )}
          </div>
        )}

        {/* Tool calls badge */}
        {msg.tool_calls_made && msg.tool_calls_made.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 2 }}>
            {msg.tool_calls_made.map((tc) => (
              <span key={tc} style={{
                fontSize: 10,
                background: "rgba(0,212,255,0.1)",
                border: "1px solid rgba(0,212,255,0.25)",
                borderRadius: 4, padding: "1px 5px",
                color: "#00d4ff",
                fontFamily: "var(--font-mono, monospace)",
              }}>{tc}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
