import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Row, Col, Tag, Button, Spin, Empty, App, Progress, Input, Select,
  Collapse, Drawer, Descriptions, Timeline, DatePicker, Tooltip,
} from "antd";
import {
  ArrowLeftOutlined, FundOutlined, LockOutlined, ClockCircleOutlined,
  ProjectOutlined, SearchOutlined, FilterOutlined, RobotOutlined,
  DollarOutlined, CheckCircleOutlined, BellOutlined, ShopOutlined,
  CarryOutOutlined, FileTextOutlined, HistoryOutlined,
} from "@ant-design/icons";
import GlowCard from "../../components/GlowCard";
import api from "../../api/client";
import { walletApi } from "../../api/services";
import type { Settlement } from "../../api/services";
import { useCurrentUser } from "../../contexts/UserContext";
import dayjs from "dayjs";

const { RangePicker } = DatePicker;

// ── Employer types ──
interface EscrowItem {
  id: string;
  title: string;
  project_name: string;
  project_id?: string;
  task_name?: string;
  task_id?: string;
  agent_name?: string;
  amount: number;
  released_amount?: number;
  status: string;
  created_at: string;
}

interface EscrowDetail {
  total_escrow: number;
  frozen: number;
  pending_release: number;
  project_count: number;
  items: EscrowItem[];
}

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  locked: { label: "进行中", cls: "neon-tag-cyan" },
  partially_released: { label: "待支付", cls: "neon-tag-orange" },
  fully_released: { label: "已支付", cls: "neon-tag-green" },
  refunded: { label: "已退款", cls: "neon-tag-gray" },
  disputed: { label: "争议中", cls: "neon-tag-red" },
};

// ── Employee settlement types ──
interface SettlementExt extends Settlement {
  project_name?: string;
  project_id?: string;
  task_name?: string;
  employer_name?: string;
  expected_at?: string;
}

const SETTLE_STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: "待验收", cls: "neon-tag-orange" },
  processing: { label: "处理中", cls: "neon-tag-cyan" },
  completed: { label: "已结算", cls: "neon-tag-green" },
  failed: { label: "失败", cls: "neon-tag-red" },
  revision: { label: "待修改", cls: "neon-tag-purple" },
};

// ═══════════════════════════════════════
//  Employee Earnings View
// ═══════════════════════════════════════
function EmployeeEarningsView() {
  const navigate = useNavigate();
  const { message: msg } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [settlements, setSettlements] = useState<SettlementExt[]>([]);
  const [settledHistory, setSettledHistory] = useState<SettlementExt[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [drawerItem, setDrawerItem] = useState<SettlementExt | null>(null);

  useEffect(() => {
    setLoading(true);
    const ctrl = new AbortController();
    walletApi.listSettlements({ limit: 500 })
      .then((res) => {
        if (ctrl.signal.aborted) return;
        const all = (res.data?.items ?? res.data ?? []) as SettlementExt[];
        setSettlements(all.filter((s) => ["pending", "processing", "revision"].includes(s.status)));
        setSettledHistory(all.filter((s) => ["completed", "failed"].includes(s.status)));
      })
      .catch(() => {})
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, []);  

  // Stats
  const stats = useMemo(() => {
    const totalAmount = settlements.reduce((s, i) => s + Number(i.amount || 0), 0);
    const projectIds = new Set(settlements.map((s) => s.project_id || s.contract_id).filter(Boolean));
    const taskCount = settlements.filter((s) => s.task_id).length;
    const earliest = settlements
      .filter((s) => s.expected_at)
      .sort((a, b) => new Date(a.expected_at!).getTime() - new Date(b.expected_at!).getTime())[0];
    return { totalAmount, projectCount: projectIds.size, taskCount, earliestDate: earliest?.expected_at };
  }, [settlements]);

  // Filter
  const filtered = useMemo(() => {
    let items = settlements;
    if (search) items = items.filter((i) =>
      (i.project_name || "").toLowerCase().includes(search.toLowerCase()) ||
      (i.task_name || "").toLowerCase().includes(search.toLowerCase()) ||
      (i.note || "").toLowerCase().includes(search.toLowerCase())
    );
    if (statusFilter) items = items.filter((i) => i.status === statusFilter);
    if (dateRange?.[0] && dateRange?.[1]) {
      const start = dateRange[0].startOf("day").valueOf();
      const end = dateRange[1].endOf("day").valueOf();
      items = items.filter((i) => {
        const t = new Date(i.created_at).getTime();
        return t >= start && t <= end;
      });
    }
    return items;
  }, [settlements, search, statusFilter, dateRange]);

  // Group by project
  const projectGroups = useMemo(() => {
    const groups = new Map<string, {
      name: string; projectId?: string; employer?: string;
      items: SettlementExt[]; total: number; accepted: number; taskTotal: number;
    }>();
    for (const item of filtered) {
      const key = item.project_name || item.contract_id || "未关联工作流";
      if (!groups.has(key)) {
        groups.set(key, {
          name: item.project_name || "未关联工作流",
          projectId: item.project_id,
          employer: item.employer_name,
          items: [], total: 0, accepted: 0, taskTotal: 0,
        });
      }
      const g = groups.get(key)!;
      g.items.push(item);
      g.total += Number(item.amount || 0);
      g.taskTotal += 1;
      if (item.status === "completed") g.accepted += 1;
    }
    return Array.from(groups.values());
  }, [filtered]);

  // Filtered settled history
  const filteredHistory = useMemo(() => {
    let items = settledHistory;
    if (search) items = items.filter((i) =>
      (i.project_name || "").toLowerCase().includes(search.toLowerCase()) ||
      (i.task_name || "").toLowerCase().includes(search.toLowerCase())
    );
    return items;
  }, [settledHistory, search]);

  // ``Date.now()`` is impure (return value depends on time of call),
  // which is what the React Compiler ``react-hooks/purity`` rule
  // flags. For an "overdue" UI badge driven by settlement age, this
  // is the right behaviour — the badge SHOULD reflect the most
  // recent wall clock at render time. Suppress the warning at the
  // call site rather than the function definition so future
  // accidental impure callers still surface.
  const isOverdue = (item: SettlementExt) => {
    if (item.status !== "pending") return false;
    // eslint-disable-next-line react-hooks/purity
    const diff = Date.now() - new Date(item.created_at).getTime();
    return diff > 48 * 60 * 60 * 1000;
  };

  if (loading) return <Spin style={{ display: "block", margin: "60px auto" }} />;

  return (
    <>
      {/* Stat cards */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        {[
          { label: "待结算总额", value: stats.totalAmount, color: "var(--cyan)", icon: <DollarOutlined />, isMoney: true, tip: "所有待验收和处理中的结算金额总和" },
          { label: "涉及工作流", value: stats.projectCount, color: "#a855f7", icon: <ProjectOutlined />, tip: "有待结算记录的工作流数量" },
          { label: "待结算任务", value: stats.taskCount, color: "#f59e0b", icon: <CarryOutOutlined />, tip: "等待验收或处理中的结算任务数" },
          { label: "预计最快到账", value: stats.earliestDate ? dayjs(stats.earliestDate).format("MM-DD") : "—", color: "var(--success)", icon: <ClockCircleOutlined />, isText: true, tip: "最近一笔结算的预计到账时间" },
        ].map((s) => (
          <Col span={6} key={s.label}>
            <Tooltip title={s.tip}>
              <div className="stat-card" style={{ "--stat-accent": s.color, cursor: "help" } as React.CSSProperties}>
                <div className="stat-value mono" style={{ color: s.color }}>
                  {s.icon}{" "}
                  {s.isMoney
                    ? `¥${Number(s.value).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`
                    : s.isText ? s.value : s.value}
                </div>
                <div className="stat-label">{s.label}</div>
              </div>
            </Tooltip>
          </Col>
        ))}
      </Row>

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        <FilterOutlined style={{ color: "var(--text-3)" }} />
        <Input placeholder="搜索工作流/任务名称" prefix={<SearchOutlined style={{ color: "var(--text-3)" }} />}
          value={search} onChange={(e) => setSearch(e.target.value)} allowClear style={{ width: 220 }} />
        <Select placeholder="状态筛选" allowClear style={{ width: 140 }}
          value={statusFilter} onChange={setStatusFilter}
          options={[
            { value: "pending", label: "待验收" },
            { value: "processing", label: "处理中" },
            { value: "revision", label: "待修改" },
          ]} />
        <RangePicker size="middle" style={{ width: 240 }}
          value={dateRange as [dayjs.Dayjs, dayjs.Dayjs] | null}
          onChange={(v) => setDateRange(v)} />
      </div>

      {/* Project groups — pending settlements */}
      {projectGroups.length === 0 ? (
        <GlowCard color="cyan" style={{ marginBottom: 24 }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无待结算收益" style={{ padding: 40 }}>
            <Button type="primary" className="btn-gradient" icon={<ShopOutlined />}
              onClick={() => navigate("/market")}>去接单</Button>
          </Empty>
        </GlowCard>
      ) : (
        <Collapse
          bordered={false}
          defaultActiveKey={projectGroups.map((g) => g.name)}
          style={{ background: "transparent", marginBottom: 24 }}
          items={projectGroups.map((group) => {
            const acceptPct = group.taskTotal > 0 ? Math.round((group.accepted / group.taskTotal) * 100) : 0;
            return {
              key: group.name,
              label: (
                <div style={{ display: "flex", alignItems: "center", gap: 16, width: "100%" }}>
                  <Button type="link" style={{ padding: 0, fontWeight: 600, fontSize: 14 }}
                    onClick={(e) => { e.stopPropagation(); if (group.projectId) navigate(`/projects/${group.projectId}`); }}>
                    <ProjectOutlined style={{ marginRight: 4 }} />{group.name}
                  </Button>
                  {group.employer && (
                    <span style={{ fontSize: 11, color: "var(--text-3)" }}>雇主: {group.employer}</span>
                  )}
                  <div style={{ flex: 1, maxWidth: 160 }}>
                    <Progress percent={acceptPct} size="small"
                      strokeColor={{ from: "#00d084", to: "#22d3ee" }}
                      format={() => `${group.accepted}/${group.taskTotal} 已验收`} />
                  </div>
                  <span className="mono" style={{ fontSize: 12, color: "var(--cyan)" }}>
                    ¥{group.total.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                  </span>
                  <Tag color="blue">{group.items.length} 笔</Tag>
                </div>
              ),
              children: (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {group.items.map((item) => {
                    const st = SETTLE_STATUS[item.status] ?? { label: item.status, cls: "neon-tag-gray" };
                    const overdue = isOverdue(item);
                    return (
                      <div key={item.id} onClick={() => setDrawerItem(item)}
                        style={{
                          display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                          borderRadius: 8,
                          background: overdue ? "rgba(255,77,79,0.06)" : "rgba(255,255,255,0.03)",
                          border: overdue ? "1px solid rgba(255,77,79,0.15)" : "1px solid rgba(255,255,255,0.06)",
                          cursor: "pointer", transition: "background 0.2s",
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(34,211,238,0.06)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = overdue ? "rgba(255,77,79,0.06)" : "rgba(255,255,255,0.03)"; }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 500, fontSize: 13, color: "var(--text-1)" }}>
                            {item.task_name || item.note || `结算 #${item.id.slice(0, 8)}`}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>
                            提交: {dayjs(item.created_at).format("MM-DD HH:mm")}
                            {item.expected_at && <> | 预计结算: {dayjs(item.expected_at).format("MM-DD")}</>}
                          </div>
                        </div>
                        <span className="mono" style={{ fontSize: 13, color: "var(--cyan)", minWidth: 100, textAlign: "right" }}>
                          ¥{Number(item.amount).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                        </span>
                        <span className={st.cls} style={{ fontSize: 11, minWidth: 50, textAlign: "center" }}>{st.label}</span>
                        {item.task_id && (
                          <Button type="link" size="small" style={{ fontSize: 11, padding: 0 }}
                            onClick={(e) => { e.stopPropagation(); navigate(`/tasks/${item.task_id}`); }}>
                            <FileTextOutlined /> 查看任务
                          </Button>
                        )}
                        {overdue && (
                          <Button size="small" danger type="text"
                            icon={<BellOutlined />}
                            onClick={(e) => { e.stopPropagation(); msg.success("已发送催办通知"); }}
                            style={{ fontSize: 11, animation: "pulse 2s infinite" }}>
                            催办
                          </Button>
                        )}
                      </div>
                    );
                  })}
                </div>
              ),
            };
          })}
        />
      )}

      {/* Settled history */}
      {filteredHistory.length > 0 && (
        <Collapse
          bordered={false}
          style={{ background: "transparent", marginBottom: 24 }}
          items={[{
            key: "history",
            label: (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <HistoryOutlined style={{ color: "var(--success)" }} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>已结算历史</span>
                <Tag color="green">{filteredHistory.length} 笔</Tag>
                <span className="mono" style={{ fontSize: 12, color: "var(--success)" }}>
                  ¥{filteredHistory.reduce((s, i) => s + Number(i.amount || 0), 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                </span>
              </div>
            ),
            children: (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {filteredHistory.slice(0, 20).map((item) => {
                  const st = SETTLE_STATUS[item.status] ?? { label: item.status, cls: "neon-tag-gray" };
                  return (
                    <div key={item.id} onClick={() => setDrawerItem(item)}
                      style={{
                        display: "flex", alignItems: "center", gap: 12, padding: "8px 14px",
                        borderRadius: 8, background: "rgba(255,255,255,0.02)",
                        border: "1px solid rgba(255,255,255,0.05)", cursor: "pointer",
                        transition: "background 0.2s",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(0,208,132,0.06)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}>
                      <CheckCircleOutlined style={{ color: "var(--success)", fontSize: 14 }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <span style={{ fontSize: 13, color: "var(--text-1)" }}>
                          {item.task_name || item.note || `结算 #${item.id.slice(0, 8)}`}
                        </span>
                        {item.project_name && (
                          <span style={{ fontSize: 11, color: "var(--text-3)", marginLeft: 8 }}>{item.project_name}</span>
                        )}
                      </div>
                      <span className="mono" style={{ fontSize: 13, color: "var(--success)", minWidth: 100, textAlign: "right" }}>
                        +¥{Number(item.amount).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                      </span>
                      <span className={st.cls} style={{ fontSize: 11 }}>{st.label}</span>
                      <span style={{ fontSize: 11, color: "var(--text-3)", minWidth: 80 }}>
                        {dayjs(item.updated_at || item.created_at).format("MM-DD")}
                      </span>
                    </div>
                  );
                })}
                {filteredHistory.length > 20 && (
                  <div style={{ textAlign: "center", padding: 8, fontSize: 12, color: "var(--text-3)" }}>
                    仅显示最近 20 条，共 {filteredHistory.length} 条
                  </div>
                )}
              </div>
            ),
          }]}
        />
      )}

      {/* Earnings detail Drawer */}
      <Drawer title="收益详情" open={!!drawerItem} onClose={() => setDrawerItem(null)} width={420}>
        {drawerItem && (
          <>
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 20 }}>
              <Descriptions.Item label="流水号">
                <span className="mono" style={{ fontSize: 11 }}>{drawerItem.id.slice(0, 16).toUpperCase()}</span>
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {dayjs(drawerItem.created_at).format("YYYY-MM-DD HH:mm:ss")}
              </Descriptions.Item>
              {drawerItem.project_name && (
                <Descriptions.Item label="关联工作流">{drawerItem.project_name}</Descriptions.Item>
              )}
              {drawerItem.task_name && (
                <Descriptions.Item label="关联任务">
                  <Button type="link" size="small" style={{ padding: 0, fontSize: 12 }}
                    onClick={() => { if (drawerItem.task_id) navigate(`/tasks/${drawerItem.task_id}`); }}>
                    {drawerItem.task_name}
                  </Button>
                </Descriptions.Item>
              )}
              {drawerItem.employer_name && (
                <Descriptions.Item label="雇主">{drawerItem.employer_name}</Descriptions.Item>
              )}
              {drawerItem.contract_id && (
                <Descriptions.Item label="合同">
                  <Button type="link" size="small" style={{ padding: 0, fontSize: 12 }}
                    onClick={() => navigate(`/contracts/${drawerItem.contract_id}`)}>
                    查看合同
                  </Button>
                </Descriptions.Item>
              )}
            </Descriptions>

            <GlowCard color="cyan" title="金额明细" style={{ marginBottom: 20 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text-2)" }}>任务报酬</span>
                  <span className="mono" style={{ color: "var(--cyan)", fontWeight: 600 }}>
                    ¥{Number(drawerItem.amount).toFixed(2)}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text-2)" }}>平台服务费</span>
                  <span className="mono" style={{ color: "var(--text-3)" }}>-¥0.00</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 }}>
                  <span style={{ color: "var(--text-1)", fontWeight: 600 }}>实际到账</span>
                  <span className="mono" style={{ color: "var(--success)", fontWeight: 600 }}>
                    ¥{Number(drawerItem.amount).toFixed(2)}
                  </span>
                </div>
              </div>
            </GlowCard>

            <GlowCard color="green" title="结算流程">
              <Timeline
                items={[
                  {
                    color: "cyan",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>任务提交</div>
                        <div style={{ fontSize: 11, color: "var(--text-3)" }}>
                          {dayjs(drawerItem.created_at).format("YYYY-MM-DD HH:mm")}
                        </div>
                      </div>
                    ),
                  },
                  {
                    color: drawerItem.status === "pending" ? "gray" : "blue",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>
                          {drawerItem.status === "pending" ? "等待雇主验收..." : drawerItem.status === "revision" ? "雇主要求修改" : "雇主已验收"}
                        </div>
                        {isOverdue(drawerItem) && (
                          <div style={{ fontSize: 11, color: "var(--error)", marginTop: 2 }}>
                            已超过 48 小时未验收
                          </div>
                        )}
                      </div>
                    ),
                  },
                  {
                    color: drawerItem.status === "processing" ? "blue" : drawerItem.status === "completed" ? "green" : "gray",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>
                          {drawerItem.status === "processing" ? "结算处理中..." : drawerItem.status === "completed" ? "结算完成" : "等待结算"}
                        </div>
                      </div>
                    ),
                  },
                  {
                    color: drawerItem.status === "completed" ? "green" : "gray",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>
                          {drawerItem.status === "completed" ? "资金已到账" : "等待到账"}
                        </div>
                        {drawerItem.status === "completed" && drawerItem.updated_at && (
                          <div style={{ fontSize: 11, color: "var(--text-3)" }}>
                            {dayjs(drawerItem.updated_at).format("YYYY-MM-DD HH:mm")}
                          </div>
                        )}
                      </div>
                    ),
                  },
                ]}
              />
            </GlowCard>

            {drawerItem.note && (
              <GlowCard color="blue" title="备注" style={{ marginTop: 16 }}>
                <div style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.6 }}>{drawerItem.note}</div>
              </GlowCard>
            )}
          </>
        )}
      </Drawer>
    </>
  );
}

// ═══════════════════════════════════════
//  Employer Escrow View (existing)
// ═══════════════════════════════════════
function EmployerEscrowView() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [drawerItem, setDrawerItem] = useState<EscrowItem | null>(null);

  // RFC 0011 Phase F: replaced manual ``useEffect + setLoading + setState``
  // pattern with React Query. AbortController unwound — React Query's
  // queryClient handles cancellation via its built-in signal forwarded
  // to fetch (axios respects AbortSignal natively).
  const { data: escrowData, isLoading: loading } = useQuery({
    queryKey: ["wallet", "escrow-detail"],
    queryFn: async ({ signal }) => {
      const r = await api.get<EscrowDetail>("/wallet/escrow-detail", { signal });
      return r.data;
    },
  });
  const data: EscrowDetail | null = escrowData ?? null;

  const projectGroups = useMemo(() => {
    if (!data?.items) return [];
    let items = data.items;
    if (search) items = items.filter((i) => i.project_name?.toLowerCase().includes(search.toLowerCase()) || i.title?.toLowerCase().includes(search.toLowerCase()));
    if (statusFilter) items = items.filter((i) => i.status === statusFilter);
    if (dateRange?.[0] && dateRange?.[1]) {
      const start = dateRange[0].startOf("day").valueOf();
      const end = dateRange[1].endOf("day").valueOf();
      items = items.filter((i) => {
        const t = new Date(i.created_at).getTime();
        return t >= start && t <= end;
      });
    }

    const groups = new Map<string, { name: string; projectId?: string; items: EscrowItem[]; total: number; released: number }>();
    for (const item of items) {
      const key = item.project_name || "未关联工作流";
      if (!groups.has(key)) {
        groups.set(key, { name: key, projectId: item.project_id, items: [], total: 0, released: 0 });
      }
      const g = groups.get(key)!;
      g.items.push(item);
      g.total += Number(item.amount || 0);
      g.released += Number(item.released_amount || 0);
    }
    return Array.from(groups.values());
  }, [data, search, statusFilter, dateRange]);

  if (loading) return <Spin style={{ display: "block", margin: "60px auto" }} />;

  return (
    <>
      {/* Summary cards */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        {[
          { label: "总托管资金", value: data?.total_escrow ?? 0, color: "var(--cyan)", icon: <FundOutlined />, tip: "所有合约锁定的资金总额 = 冻结中 + 待释放" },
          { label: "冻结中", value: data?.frozen ?? 0, color: "#f59e0b", icon: <LockOutlined />, tip: "合约进行中，资金锁定不可动" },
          { label: "待释放", value: data?.pending_release ?? 0, color: "#a855f7", icon: <ClockCircleOutlined />, tip: "合约已完成或部分完成，等待结算释放给雇员" },
          { label: "涉及工作流", value: data?.project_count ?? 0, color: "var(--success)", icon: <ProjectOutlined />, isCnt: true, tip: "有托管资金的工作流数量" },
        ].map((s) => (
          <Col span={6} key={s.label}>
            <Tooltip title={s.tip}>
              <div className="stat-card" style={{ "--stat-accent": s.color, cursor: "help" } as React.CSSProperties}>
                <div className="stat-value mono" style={{ color: s.color }}>
                  {s.icon} {s.isCnt ? s.value : `¥${Number(s.value).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`}
                </div>
                <div className="stat-label">{s.label}</div>
              </div>
            </Tooltip>
          </Col>
        ))}
      </Row>

      {/* Filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <FilterOutlined style={{ color: "var(--text-3)" }} />
        <Input placeholder="搜索工作流名称" prefix={<SearchOutlined style={{ color: "var(--text-3)" }} />}
          value={search} onChange={(e) => setSearch(e.target.value)} allowClear style={{ width: 220 }} />
        <Select placeholder="状态筛选" allowClear style={{ width: 140 }}
          value={statusFilter} onChange={setStatusFilter}
          options={Object.entries(STATUS_MAP).map(([value, { label }]) => ({ value, label }))} />
        <RangePicker size="middle" style={{ width: 240 }}
          value={dateRange as [dayjs.Dayjs, dayjs.Dayjs] | null}
          onChange={(v) => setDateRange(v)} />
      </div>

      {/* Project groups */}
      {projectGroups.length === 0 ? (
        <GlowCard color="cyan">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无托管资金记录" style={{ padding: 40 }} />
        </GlowCard>
      ) : (
        <Collapse
          bordered={false}
          style={{ background: "transparent" }}
          items={projectGroups.map((group) => {
            const pct = group.total > 0 ? Math.round((group.released / group.total) * 100) : 0;
            return {
              key: group.name,
              label: (
                <div style={{ display: "flex", alignItems: "center", gap: 16, width: "100%" }}>
                  <Button type="link" style={{ padding: 0, fontWeight: 600, fontSize: 14 }}
                    onClick={(e) => { e.stopPropagation(); if (group.projectId) navigate(`/projects/${group.projectId}`); }}>
                    <ProjectOutlined style={{ marginRight: 4 }} />{group.name}
                  </Button>
                  <div style={{ flex: 1, maxWidth: 200 }}>
                    <Progress percent={pct} size="small"
                      strokeColor={{ from: "#22d3ee", to: "#a855f7" }}
                      format={(p) => `${p}%`} />
                  </div>
                  <span className="mono" style={{ fontSize: 12, color: "var(--text-2)" }}>
                    已支付 ¥{group.released.toLocaleString()} / 总托管 ¥{group.total.toLocaleString()}
                  </span>
                  <Tag color="blue">{group.items.length} 笔</Tag>
                </div>
              ),
              children: (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {group.items.map((item) => {
                    const st = STATUS_MAP[item.status] ?? { label: item.status, cls: "neon-tag-gray" };
                    return (
                      <div key={item.id} onClick={() => setDrawerItem(item)}
                        style={{
                          display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                          borderRadius: 8, background: "rgba(255,255,255,0.03)",
                          border: "1px solid rgba(255,255,255,0.06)", cursor: "pointer",
                          transition: "background 0.2s",
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(34,211,238,0.06)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.03)"; }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 500, fontSize: 13, color: "var(--text-1)" }}>{item.title}</div>
                          {item.task_name && (
                            <span style={{ fontSize: 11, color: "var(--text-3)" }}>
                              任务：<Button type="link" size="small" style={{ padding: 0, fontSize: 11 }}
                                onClick={(e) => { e.stopPropagation(); if (item.task_id) navigate(`/tasks/${item.task_id}`); }}>
                                {item.task_name}
                              </Button>
                            </span>
                          )}
                        </div>
                        {item.agent_name && (
                          <span style={{ fontSize: 11, color: "var(--text-3)" }}>
                            <RobotOutlined style={{ marginRight: 3 }} />{item.agent_name}
                          </span>
                        )}
                        <span className="mono" style={{ fontSize: 13, color: "var(--cyan)", minWidth: 100, textAlign: "right" }}>
                          ¥{Number(item.amount).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                        </span>
                        <span className={st.cls} style={{ fontSize: 11, minWidth: 50, textAlign: "center" }}>{st.label}</span>
                        <span style={{ fontSize: 11, color: "var(--text-3)", minWidth: 90 }}>
                          {item.created_at ? new Date(item.created_at).toLocaleDateString() : "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              ),
            };
          })}
        />
      )}

      {/* Fund detail drawer */}
      <Drawer title="资金流转详情" open={!!drawerItem} onClose={() => setDrawerItem(null)} width={420}>
        {drawerItem && (
          <>
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 20 }}>
              <Descriptions.Item label="流水号">
                <span className="mono" style={{ fontSize: 11 }}>{drawerItem.id.slice(0, 16).toUpperCase()}</span>
              </Descriptions.Item>
              <Descriptions.Item label="交易时间">
                {drawerItem.created_at ? new Date(drawerItem.created_at).toLocaleString() : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="关联工作流">{drawerItem.project_name}</Descriptions.Item>
              {drawerItem.task_name && (
                <Descriptions.Item label="关联任务">{drawerItem.task_name}</Descriptions.Item>
              )}
              {drawerItem.agent_name && (
                <Descriptions.Item label="对方账户">{drawerItem.agent_name}（Agent）</Descriptions.Item>
              )}
            </Descriptions>

            <GlowCard color="cyan" title="金额信息" style={{ marginBottom: 20 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text-2)" }}>托管金额</span>
                  <span className="mono" style={{ color: "var(--cyan)", fontWeight: 600 }}>
                    ¥{Number(drawerItem.amount).toFixed(2)}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text-2)" }}>手续费</span>
                  <span className="mono">¥0.00</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 }}>
                  <span style={{ color: "var(--text-1)", fontWeight: 600 }}>实际支付</span>
                  <span className="mono" style={{ color: "var(--success)", fontWeight: 600 }}>
                    ¥{Number(drawerItem.amount).toFixed(2)}
                  </span>
                </div>
              </div>
            </GlowCard>

            <GlowCard color="purple" title="资金流转">
              <Timeline
                items={[
                  {
                    color: "cyan",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>雇主托管</div>
                        <div style={{ fontSize: 11, color: "var(--text-3)" }}>
                          {drawerItem.created_at ? new Date(drawerItem.created_at).toLocaleDateString() : "—"}
                        </div>
                      </div>
                    ),
                  },
                  {
                    color: drawerItem.status === "locked" ? "gray" : "blue",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>任务执行{drawerItem.status === "locked" ? "中..." : "完成"}</div>
                      </div>
                    ),
                  },
                  {
                    color: ["fully_released", "partially_released"].includes(drawerItem.status) ? "green" : "gray",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>
                          {drawerItem.status === "fully_released" ? "雇主验收通过" : drawerItem.status === "disputed" ? "产生争议" : "待验收"}
                        </div>
                      </div>
                    ),
                  },
                  {
                    color: drawerItem.status === "fully_released" ? "green" : "gray",
                    children: (
                      <div>
                        <div style={{ fontWeight: 500 }}>
                          {drawerItem.status === "fully_released" ? "资金已支付" : "等待支付"}
                        </div>
                      </div>
                    ),
                  },
                ]}
              />
            </GlowCard>

            {drawerItem.status === "disputed" && (
              <div style={{
                marginTop: 16, padding: "10px 14px", borderRadius: 8,
                background: "rgba(255,77,79,0.08)", border: "1px solid rgba(255,77,79,0.2)",
                fontSize: 12, color: "rgba(255,255,255,0.7)",
              }}>
                该笔资金处于争议状态，资金已冻结。如需协助处理，请联系客服：support@aitrading.ai
              </div>
            )}
          </>
        )}
      </Drawer>
    </>
  );
}

// ═══════════════════════════════════════
//  Main component — role switch
// ═══════════════════════════════════════
export default function FundDetail() {
  const navigate = useNavigate();
  const { isTrader } = useCurrentUser();

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}
          style={{ color: "var(--text-2)" }}>返回</Button>
        <span style={{
          fontSize: 18, fontWeight: 800,
          background: "linear-gradient(135deg, #22d3ee, #a855f7)",
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
        }}>{isTrader ? "托管资金详情" : "待结算收益详情"}</span>
        <div style={{ height: 1, flex: 1, background: "linear-gradient(90deg, rgba(34,211,238,0.40), transparent)" }} />
      </div>

      {isTrader ? <EmployerEscrowView /> : <EmployeeEarningsView />}
    </div>
  );
}
