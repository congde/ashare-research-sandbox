import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Tabs,
  Table,
  Tag,
  Button,
  Form,
  Input,
  Switch,
  Row,
  Col,
  Spin,
  App,
  Empty,
  Segmented,
  Select,
  Divider,
  Popconfirm,
  Modal,
  InputNumber,
  DatePicker,
  Upload,
  Avatar,
  Checkbox,
  Steps,
  Tooltip,
} from "antd";
import {
  WalletOutlined,
  FileTextOutlined,
  SettingOutlined,
  UserOutlined,
  BellOutlined,
  LockOutlined,
  PlusCircleOutlined,
  SafetyOutlined,
  DeleteOutlined,
  RightOutlined,
  DollarOutlined,
  LaptopOutlined,
  CameraOutlined,
  MailOutlined,
  MobileOutlined,
  SendOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  DesktopOutlined,
  HistoryOutlined,
  ExclamationCircleOutlined,
  QrcodeOutlined,
  SaveOutlined,
  BankOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import GlowCard from "../../components/GlowCard";
import { useCurrentUser } from "../../contexts/UserContext";
import { walletApi, contractApi, paymentMethodApi } from "../../api/services";
import api from "../../api/client";
import type {
  Wallet,
  WalletTransaction,
  Contract,
  PaymentMethodResponse,
  PaymentMethodType,
} from "../../api/services";
import type { ColumnsType } from "antd/es/table";

// ── Wallet Tab Constants ──
const TX_TYPE_LABEL: Record<string, string> = {
  deposit: "充值",
  withdraw: "提现",
  escrow_lock: "托管锁定",
  escrow_release: "托管释放",
  settlement: "结算",
};

const TX_TYPE_COLOR: Record<string, string> = {
  deposit: "success",
  withdraw: "error",
  escrow_lock: "warning",
  escrow_release: "processing",
  settlement: "success",
};

const REF_TYPE_LABEL: Record<string, string> = {
  deposit: "充值入账",
  withdraw: "提现到账",
  contract: "合约",
  settlement: "结算",
  project: "工作流",
  escrow: "托管",
};

const PM_TYPE_LABEL: Record<PaymentMethodType, string> = {
  alipay: "支付宝",
  wechat: "微信",
  bank_card: "银行卡",
};

// ── Wallet Tab ──
function WalletTab() {
  const { message: msg } = App.useApp();
  const { activeRole } = useCurrentUser();
  const navigate = useNavigate();
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [transactions, setTransactions] = useState<WalletTransaction[]>([]);
  const [walletLoading, setWalletLoading] = useState(true);
  const [txLoading, setTxLoading] = useState(false);
  // Action modals
  const [depositOpen, setDepositOpen] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [actionAmount, setActionAmount] = useState<number | null>(null);
  const [actionNote, setActionNote] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [paymentMethod, setPaymentMethod] = useState("alipay");
  // 收款方式 (payment methods)
  const [pmModalOpen, setPmModalOpen] = useState(false);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethodResponse[]>([]);
  const [pmLoading, setPmLoading] = useState(false);
  const [pmType, setPmType] = useState<PaymentMethodType>("alipay");
  const [pmAccount, setPmAccount] = useState("");
  const [pmHolder, setPmHolder] = useState("");
  const [pmSubmitting, setPmSubmitting] = useState(false);
  // Filters
  const [txTypeFilter, setTxTypeFilter] = useState<string | undefined>(undefined);
  const [txStatusFilter, setTxStatusFilter] = useState<string | undefined>(undefined);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);

  // Escrow summary
  const [, setEscrowSummary] = useState<{
    total_escrow: number;
    pending_payment: number;
    frozen: number;
  } | null>(null);
  // Employee: pending earnings from active contracts
  const [pendingEarnings, setPendingEarnings] = useState(0);

  const loadWallet = () => {
    walletApi.get().then((r) => setWallet(r.data)).catch(() => msg.error("加载钱包失败"));
  };
  const loadTransactions = () => {
    setTxLoading(true);
    walletApi.listTransactions({ limit: 200 })
      .then((r) => {
        setTransactions(r.data.items ?? []);
      })
      .catch(() => {
        msg.error("加载交易记录失败");
      })
      .finally(() => setTxLoading(false));
  };

  useEffect(() => {
    setWalletLoading(true);
    Promise.all([
      walletApi.get().then((r) => setWallet(r.data)).catch(() => msg.error("加载钱包失败")),
      walletApi.listTransactions({ limit: 200 }).then((r) => {
        setTransactions(r.data.items ?? []);
      }).catch(() => { /* non-fatal: list view degrades gracefully */ }),
      api.get("/dashboard/employer-summary").then((r) => {
        const d = r.data;
        setEscrowSummary({ total_escrow: Number(d.total_escrow ?? 0), pending_payment: Number(d.pending_payment ?? 0), frozen: Number(d.frozen ?? 0) });
      }).catch(() => {}),
      // Employee: sum active contract budgets as pending earnings
      contractApi.list({ status: "active", limit: 200 }).then((r) => {
        const total = (r.data.items ?? []).reduce((s: number, c: { budget_amount?: string | number }) => s + Number(c.budget_amount ?? 0), 0);
        setPendingEarnings(total);
      }).catch(() => {}),
    ]).finally(() => setWalletLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Client-side filtering
  const filteredTransactions = useMemo(() => {
    let list = transactions;
    if (txTypeFilter) list = list.filter((t) => t.tx_type === txTypeFilter);
    if (txStatusFilter) list = list.filter((t) => (t as unknown as Record<string, unknown>).status === txStatusFilter);
    if (dateRange && dateRange[0] && dateRange[1]) {
      const start = dateRange[0].startOf("day");
      const end = dateRange[1].endOf("day");
      list = list.filter((t) => {
        const d = dayjs(t.created_at);
        return d.isAfter(start) && d.isBefore(end);
      });
    }
    return list;
  }, [transactions, txTypeFilter, txStatusFilter, dateRange]);

  const handleDeposit = async () => {
    if (!actionAmount || actionAmount <= 0) return;
    setActionLoading(true);
    try {
      await walletApi.deposit(String(actionAmount), actionNote || `${paymentMethod}充值`);
      msg.success("充值成功");
      setDepositOpen(false);
      setActionAmount(null);
      setActionNote("");
      loadWallet();
      loadTransactions();
    } catch { msg.error("充值失败"); }
    finally { setActionLoading(false); }
  };

  const handleWithdraw = async () => {
    if (!actionAmount || actionAmount <= 0) return;
    setActionLoading(true);
    try {
      await walletApi.withdraw(String(actionAmount), actionNote || "提现");
      msg.success("提现成功");
      setWithdrawOpen(false);
      setActionAmount(null);
      setActionNote("");
      loadWallet();
      loadTransactions();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      msg.error(detail || "提现失败");
    } finally { setActionLoading(false); }
  };

  const loadPaymentMethods = async () => {
    setPmLoading(true);
    try {
      const res = await paymentMethodApi.list();
      setPaymentMethods(res.data.items);
    } catch {
      msg.error("加载收款方式失败");
      setPaymentMethods([]);
    } finally {
      setPmLoading(false);
    }
  };

  const openPaymentMethods = () => {
    setPmModalOpen(true);
    void loadPaymentMethods();
  };

  const handleBindPaymentMethod = async () => {
    if (!pmAccount.trim() || !pmHolder.trim()) {
      msg.error("请填写账号和持有人姓名");
      return;
    }
    setPmSubmitting(true);
    try {
      await paymentMethodApi.create({
        method_type: pmType,
        account: pmAccount.trim(),
        holder_name: pmHolder.trim(),
      });
      msg.success("收款方式已绑定");
      setPmAccount("");
      setPmHolder("");
      await loadPaymentMethods();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      msg.error(detail || "绑定失败");
    } finally {
      setPmSubmitting(false);
    }
  };

  const handleUnbindPaymentMethod = async (id: string) => {
    try {
      await paymentMethodApi.remove(id);
      msg.success("已解绑");
      await loadPaymentMethods();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      msg.error(detail || "解绑失败");
    }
  };

  const txColumns: ColumnsType<WalletTransaction> = [
    {
      title: "时间",
      dataIndex: "created_at",
      width: 170,
      render: (v) => new Date(v).toLocaleString(),
    },
    {
      title: "类型",
      dataIndex: "tx_type",
      width: 100,
      render: (t) => (
        <Tag color={TX_TYPE_COLOR[t] ?? "default"}>
          {TX_TYPE_LABEL[t] ?? t}
        </Tag>
      ),
    },
    {
      title: "交易对象",
      key: "reference",
      ellipsis: true,
      render: (_, r) => {
        const refLabel = REF_TYPE_LABEL[r.reference_type ?? ""] ?? r.reference_type;
        if (r.note && r.reference_type) {
          return <span>{refLabel} · {r.note}</span>;
        }
        return <span>{r.note || refLabel || "—"}</span>;
      },
    },
    {
      title: "金额",
      dataIndex: "amount",
      width: 120,
      render: (v) => {
        const n = Number(v);
        return (
          <span style={{ color: n >= 0 ? "var(--success)" : "#ff4d4f", fontWeight: 600 }}>
            {n >= 0 ? "+¥" : "-¥"}
            {Math.abs(n).toFixed(2)}
          </span>
        );
      },
    },
    {
      title: "状态",
      key: "status",
      width: 80,
      render: () => <Tag color="success">成功</Tag>,
    },
    {
      title: "余额",
      dataIndex: "balance_after",
      width: 110,
      render: (v) => <span className="mono">¥{Number(v).toFixed(2)}</span>,
    },
  ];

  if (walletLoading) {
    return <Spin style={{ display: "block", margin: "40px auto" }} />;
  }

  // Employer stats: balance / frozen / spent
  // Employee stats: balance / pending / earned
  const isTrader = activeRole === "trader";

  return (
    <div>
      {/* Asset overview — 4 columns */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {[
          { label: "账户余额", value: Number(wallet?.balance ?? 0), color: "var(--cyan)", prefix: "¥", tip: "可用余额，可提现或用于支付" },
          isTrader
            ? { label: "托管资金", value: Number(wallet?.frozen_amount ?? 0), color: "#fa8c16", prefix: "¥", link: "/account/funds", tip: "已锁定在合约中的资金，合约完成后释放给雇员" }
            : { label: "签约收益", value: pendingEarnings, color: "#fa8c16", prefix: "¥", link: "/account/funds", tip: "进行中合约的预算总额，任务完成验收后结算到账" },
          { label: "累计支出", value: Number(wallet?.total_spent ?? 0), color: "#ff4d4f", prefix: "¥", tip: isTrader ? "历史所有合约的支出总额" : "历史所有提现和扣款总额" },
          { label: "累计收入", value: Number(wallet?.total_earned ?? 0), color: "var(--success)", prefix: "¥", tip: isTrader ? "历史所有充值和退款总额" : "历史所有结算到账总额" },
        ].map((s) => (
          <Col span={6} key={s.label}>
            <Tooltip title={s.tip}>
              <div className="stat-card" style={{ "--stat-accent": s.color, cursor: s.link ? "pointer" : "help" } as React.CSSProperties}
                onClick={s.link ? () => navigate(s.link!) : undefined}>
                <div className="stat-value mono" style={{ fontSize: 28, color: s.color }}>
                  {s.prefix}{s.value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="stat-label">{s.label}{s.link ? " >" : ""}</div>
              </div>
            </Tooltip>
          </Col>
        ))}
      </Row>

      {/* Quick actions */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
        <Button type="primary" className="btn-gradient" icon={<PlusCircleOutlined />}
          onClick={() => { setActionAmount(null); setActionNote(""); setPaymentMethod("alipay"); setDepositOpen(true); }}>
          充值
        </Button>
        <Button icon={<WalletOutlined />}
          onClick={() => { setActionAmount(null); setActionNote(""); setWithdrawOpen(true); }}>
          提现
        </Button>
        <Button icon={<SettingOutlined />}
          onClick={() => navigate("/account/funds")}>
          资金详情
        </Button>
        <Button icon={<WalletOutlined />}
          onClick={() => navigate("/wallet")}>
          收款设置
        </Button>
        <Button icon={<BankOutlined />}
          onClick={openPaymentMethods}>
          绑定收款方式
        </Button>
      </div>

      {/* Transaction filters */}
      <div style={{ display: "flex", gap: 12, marginBottom: 12, alignItems: "center" }}>
        <Select placeholder="交易类型" allowClear style={{ width: 140 }}
          value={txTypeFilter} onChange={setTxTypeFilter}
          options={Object.entries(TX_TYPE_LABEL).map(([value, label]) => ({ value, label }))} />
        <Select placeholder="状态" allowClear style={{ width: 110 }}
          value={txStatusFilter} onChange={setTxStatusFilter}
          options={[
            { value: "success", label: "成功" },
            { value: "processing", label: "处理中" },
            { value: "failed", label: "失败" },
          ]} />
        <DatePicker.RangePicker
          value={dateRange}
          onChange={(dates) => setDateRange(dates as [dayjs.Dayjs | null, dayjs.Dayjs | null] | null)}
          placeholder={["开始日期", "结束日期"]}
          allowClear
          style={{ width: 260 }}
        />
        {(txTypeFilter || txStatusFilter || dateRange) && (
          <span style={{ fontSize: 12, color: "var(--text-3)" }}>
            共 {filteredTransactions.length} 条
          </span>
        )}
      </div>

      {/* Transaction list */}
      <GlowCard color="blue" title="资金流水记录">
        <Table
          rowKey="id"
          columns={txColumns}
          dataSource={filteredTransactions}
          loading={txLoading}
          pagination={{ pageSize: 10 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无交易记录"
              />
            ),
          }}
        />
      </GlowCard>

      {/* Deposit Modal */}
      <Modal title="充值" open={depositOpen} onCancel={() => setDepositOpen(false)}
        onOk={handleDeposit} confirmLoading={actionLoading}
        okText="确认充值" cancelText="取消" okButtonProps={{ disabled: !actionAmount || actionAmount <= 0 }}>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 4 }}>充值金额</div>
          <InputNumber min={1} max={9999999} style={{ width: "100%" }} placeholder="请输入充值金额"
            value={actionAmount} onChange={(v) => setActionAmount(v)} prefix="¥" />
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 4 }}>支付方式</div>
          <Segmented value={paymentMethod} onChange={(v) => setPaymentMethod(v as string)} options={[
            { value: "alipay", label: "支付宝" },
            { value: "wechat", label: "微信" },
            { value: "bank", label: "银行转账" },
          ]} />
        </div>
        <div>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 4 }}>备注（可选）</div>
          <Input placeholder="充值备注" value={actionNote} onChange={(e) => setActionNote(e.target.value)} />
        </div>
      </Modal>

      {/* Withdraw Modal */}
      <Modal title="提现" open={withdrawOpen} onCancel={() => setWithdrawOpen(false)}
        onOk={handleWithdraw} confirmLoading={actionLoading}
        okText="确认提现" cancelText="取消" okButtonProps={{ disabled: !actionAmount || actionAmount <= 0 }}>
        <div style={{
          padding: "8px 12px", borderRadius: 8, marginBottom: 16,
          background: "rgba(34,211,238,0.06)", border: "1px solid rgba(34,211,238,0.12)",
          fontSize: 12, color: "var(--text-2)",
        }}>
          可用余额：<span className="mono" style={{ color: "var(--cyan)", fontWeight: 600 }}>
            ¥{(Number(wallet?.balance ?? 0) - Number(wallet?.frozen_amount ?? 0)).toFixed(2)}
          </span>
        </div>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 4 }}>提现金额</div>
          <InputNumber min={1} max={Number(wallet?.balance ?? 0) - Number(wallet?.frozen_amount ?? 0)}
            style={{ width: "100%" }} placeholder="请输入提现金额"
            value={actionAmount} onChange={(v) => setActionAmount(v)} prefix="¥" />
        </div>
        <div>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 4 }}>备注（可选）</div>
          <Input placeholder="提现备注" value={actionNote} onChange={(e) => setActionNote(e.target.value)} />
        </div>
      </Modal>

      {/* Payment methods (收款方式) Modal */}
      <Modal title="收款方式" open={pmModalOpen} onCancel={() => setPmModalOpen(false)}
        footer={<Button onClick={() => setPmModalOpen(false)}>关闭</Button>} width={560}>
        <Spin spinning={pmLoading}>
          {paymentMethods.length === 0 ? (
            <Empty description="还没有绑定收款方式" style={{ margin: "12px 0" }} />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
              {paymentMethods.map((pm) => (
                <div key={pm.id} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "10px 12px", borderRadius: 8,
                  border: "1px solid var(--border)", background: "rgba(255,255,255,0.02)",
                }}>
                  <div>
                    <div style={{ fontWeight: 500 }}>
                      {PM_TYPE_LABEL[pm.method_type]}
                      {pm.is_default && <Tag color="cyan" style={{ marginLeft: 8 }}>默认</Tag>}
                    </div>
                    <div className="mono" style={{ fontSize: 12, color: "var(--text-3)" }}>
                      {pm.account} · {pm.holder_name}
                    </div>
                  </div>
                  <Popconfirm title="确认解绑此收款方式？" onConfirm={() => handleUnbindPaymentMethod(pm.id)}
                    okText="解绑" cancelText="取消" okButtonProps={{ danger: true }}>
                    <Button danger size="small" icon={<DeleteOutlined />}>解绑</Button>
                  </Popconfirm>
                </div>
              ))}
            </div>
          )}
          <Divider style={{ margin: "12px 0" }}>新增收款方式</Divider>
          <Form layout="vertical">
            <Form.Item label="类型" style={{ marginBottom: 12 }}>
              <Select value={pmType} onChange={setPmType} options={[
                { label: "支付宝", value: "alipay" },
                { label: "微信", value: "wechat" },
                { label: "银行卡", value: "bank_card" },
              ]} />
            </Form.Item>
            <Form.Item label="账号" style={{ marginBottom: 12 }}>
              <Input placeholder="支付宝/微信账号或银行卡号" value={pmAccount}
                onChange={(e) => setPmAccount(e.target.value)} />
            </Form.Item>
            <Form.Item label="持有人姓名" style={{ marginBottom: 12 }}>
              <Input placeholder="收款人真实姓名" value={pmHolder}
                onChange={(e) => setPmHolder(e.target.value)} />
            </Form.Item>
            <Button type="primary" className="btn-gradient" block
              loading={pmSubmitting} onClick={handleBindPaymentMethod}>
              绑定
            </Button>
          </Form>
        </Spin>
      </Modal>
    </div>
  );
}

// ── Settings Tab ──
function SettingsTab() {
  const { message: msg } = App.useApp();
  const { currentUser } = useCurrentUser();
  const [saving, setSaving] = useState(false);
  const [displayName, setDisplayName] = useState(currentUser?.display_name ?? "");
  const [email, setEmail] = useState(currentUser?.email ?? "");
  const [phone, setPhone] = useState("");
  const [bio, setBio] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  // Password modal
  const [pwdOpen, setPwdOpen] = useState(false);
  const [oldPwd, setOldPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [pwdLoading, setPwdLoading] = useState(false);

  // Delete account modal (4 steps)
  const [deleteStep, setDeleteStep] = useState(0);
  const [deletePwd, setDeletePwd] = useState("");
  const [deleteWallet, setDeleteWallet] = useState<{ balance: number; frozen: number } | null>(null);
  const [deleteContracts, setDeleteContracts] = useState<Contract[]>([]);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Notification channels
  const [notifChannels, setNotifChannels] = useState<string[]>(["inbox", "email"]);

  // Notification sub-items
  const [notifSubs, setNotifSubs] = useState<Record<string, boolean>>({
    project_task_submit: true,
    project_accept_result: true,
    contract_pending_sign: true,
    contract_signed: true,
    fund_deposit: true,
    fund_withdraw: true,
    talent_org_invite: false,
    talent_agent_msg: false,
    system_announcements: true,
  });

  // Security
  const [twoFactor, setTwoFactor] = useState(false);
  const [twoFaCode, setTwoFaCode] = useState("");
  const [twoFaBound, setTwoFaBound] = useState(false);
  const [showDevices, setShowDevices] = useState(false);

  // Privacy
  const [profileVisibility, setProfileVisibility] = useState("public");
  const [searchable, setSearchable] = useState(true);
  const [historyPublic, setHistoryPublic] = useState(true);

  // Mock devices
  const devices = [
    { id: "1", name: "macOS — Chrome 122", type: "desktop", ip: "223.104.xx.xx", time: dayjs().subtract(5, "minute").format("YYYY-MM-DD HH:mm"), current: true },
    { id: "2", name: "iPhone 15 Pro — Safari", type: "mobile", ip: "120.229.xx.xx", time: dayjs().subtract(2, "day").format("YYYY-MM-DD HH:mm"), current: false },
    { id: "3", name: "Windows 11 — Edge 120", type: "desktop", ip: "59.56.xx.xx", time: dayjs().subtract(7, "day").format("YYYY-MM-DD HH:mm"), current: false },
  ];

  // Mock audit log
  const auditLogs = [
    { action: "登录成功", time: dayjs().subtract(5, "minute").format("MM-DD HH:mm"), ip: "223.104.xx.xx", status: "success" },
    { action: "修改密码", time: dayjs().subtract(3, "day").format("MM-DD HH:mm"), ip: "223.104.xx.xx", status: "success" },
    { action: "提现 ¥500.00", time: dayjs().subtract(5, "day").format("MM-DD HH:mm"), ip: "120.229.xx.xx", status: "success" },
    { action: "登录失败（密码错误）", time: dayjs().subtract(8, "day").format("MM-DD HH:mm"), ip: "59.56.xx.xx", status: "failed" },
    { action: "修改邮箱", time: dayjs().subtract(15, "day").format("MM-DD HH:mm"), ip: "223.104.xx.xx", status: "success" },
  ];

  const handleAvatarChange = (info: { file: { originFileObj?: File } }) => {
    const file = info.file?.originFileObj;
    if (file) {
      const reader = new FileReader();
      reader.onload = (e) => setAvatarUrl(e.target?.result as string);
      reader.readAsDataURL(file);
      msg.success("头像已更新（本地预览）");
    }
  };

  const handleProfileSave = async () => {
    setSaving(true);
    try {
      await api.patch("/auth/profile", { display_name: displayName || undefined, phone: phone || undefined, bio: bio || undefined });
      msg.success("个人信息已保存");
    } catch {
      msg.error("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handlePasswordChange = async () => {
    if (newPwd !== confirmPwd) { msg.error("两次密码不一致"); return; }
    setPwdLoading(true);
    try {
      await api.post("/auth/change-password", { old_password: oldPwd, new_password: newPwd });
      msg.success("密码已修改");
      setPwdOpen(false);
      setOldPwd(""); setNewPwd(""); setConfirmPwd("");
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      msg.error(detail || "修改失败");
    } finally {
      setPwdLoading(false);
    }
  };

  const handleNotifSubToggle = (key: string, checked: boolean) => {
    setNotifSubs((prev) => ({ ...prev, [key]: checked }));
    msg.success("通知设置已更新");
  };

  const handle2faVerify = () => {
    if (twoFaCode.length === 6) {
      setTwoFaBound(true);
      setTwoFaCode("");
      msg.success("二次验证已绑定");
    } else {
      msg.error("请输入 6 位验证码");
    }
  };

  const handle2faUnbind = () => {
    setTwoFaBound(false);
    setTwoFactor(false);
    msg.success("二次验证已解绑");
  };

  // 4-step deletion
  const startDeleteFlow = async () => {
    setDeleteStep(1);
  };

  const loadDeleteChecks = async () => {
    setDeleteLoading(true);
    try {
      const [walletRes, contractRes] = await Promise.all([
        walletApi.get(),
        contractApi.list({ status: "active", limit: 50 }),
      ]);
      setDeleteWallet({
        balance: Number(walletRes.data?.balance ?? 0),
        frozen: Number(walletRes.data?.frozen_amount ?? 0),
      });
      setDeleteContracts(contractRes.data?.items ?? []);
    } catch {
      setDeleteWallet({ balance: 0, frozen: 0 });
      setDeleteContracts([]);
    } finally {
      setDeleteLoading(false);
    }
  };

  useEffect(() => {
    if (deleteStep === 2) loadDeleteChecks();
  }, [deleteStep]);  

  const handleDeleteAccount = () => {
    msg.warning("账户注销请求已提交，工作人员将在 3 个工作日内处理");
    setDeleteStep(0);
    setDeletePwd("");
  };

  // Sub-item render helper
  const notifSubRow = (key: string, label: string) => (
    <div key={key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingLeft: 24 }}>
      <span style={{ fontSize: 12, color: "var(--text-2)" }}>{label}</span>
      <Switch size="small" checked={notifSubs[key]} onChange={(v) => handleNotifSubToggle(key, v)} />
    </div>
  );

  return (
    <div style={{ maxWidth: 680 }}>
      {/* ═══ Section 1: Profile ═══ */}
      <GlowCard color="blue" title={<span><UserOutlined style={{ marginRight: 6 }} />个人资料</span>} style={{ marginBottom: 24 }}>
        {/* Avatar */}
        <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 20 }}>
          <Upload showUploadList={false} accept="image/*" beforeUpload={() => false}
            onChange={handleAvatarChange as (info: unknown) => void}>
            <div style={{ position: "relative", cursor: "pointer" }}>
              <Avatar size={72} src={avatarUrl} icon={<UserOutlined />}
                style={{ background: "linear-gradient(135deg, rgba(34,211,238,0.3), rgba(168,85,247,0.3))", border: "2px solid rgba(34,211,238,0.3)" }} />
              <div style={{
                position: "absolute", bottom: 0, right: 0, width: 24, height: 24, borderRadius: "50%",
                background: "var(--cyan)", display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <CameraOutlined style={{ fontSize: 12, color: "#000" }} />
              </div>
            </div>
          </Upload>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15, color: "var(--text-1)" }}>{currentUser?.display_name || currentUser?.username}</div>
            <div style={{ fontSize: 12, color: "var(--text-3)" }}>点击头像更换照片</div>
          </div>
        </div>

        <Form layout="vertical">
          <Form.Item label="显示名称">
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="输入显示名称" />
          </Form.Item>
          <Form.Item label="邮箱">
            <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="输入邮箱"
              prefix={<MailOutlined style={{ color: "var(--text-3)" }} />}
              suffix={
                <Button type="link" size="small" icon={<SendOutlined />} style={{ fontSize: 11, padding: 0 }}
                  onClick={() => msg.info("验证码已发送至邮箱")}>发送验证码</Button>
              } />
          </Form.Item>
          <Form.Item label="手机号">
            <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="输入手机号"
              prefix={<MobileOutlined style={{ color: "var(--text-3)" }} />}
              suffix={
                <Button type="link" size="small" icon={<SendOutlined />} style={{ fontSize: 11, padding: 0 }}
                  onClick={() => msg.info("验证码已发送至手机")}>发送验证码</Button>
              } />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="组织（选填）">
                <Input placeholder="所在组织名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="职位（选填）">
                <Input placeholder="职位/头衔" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="个人简介">
            <Input.TextArea rows={3} value={bio} onChange={(e) => setBio(e.target.value)} placeholder="介绍一下自己..." />
          </Form.Item>
          <Form.Item>
            <Button type="primary" className="btn-gradient" loading={saving} onClick={handleProfileSave}>
              <SaveOutlined /> 保存修改
            </Button>
          </Form.Item>
        </Form>
      </GlowCard>

      <Divider style={{ borderColor: "var(--border)" }} />

      {/* ═══ Section 2: Notification Settings ═══ */}
      <GlowCard color="cyan" title={<span><BellOutlined style={{ marginRight: 6 }} />通知设置</span>} style={{ marginBottom: 24 }}>
        {/* Notification channels */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--cyan)", marginBottom: 8 }}>通知渠道</div>
          <Checkbox.Group value={notifChannels} onChange={(v) => { setNotifChannels(v as string[]); msg.success("渠道已更新"); }}
            options={[
              { label: "站内信", value: "inbox" },
              { label: "邮件", value: "email" },
              { label: "短信", value: "sms" },
            ]} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Project progress */}
          <div>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>工作流进展</div>
            {notifSubRow("project_task_submit", "任务提交通知")}
            {notifSubRow("project_accept_result", "验收结果通知")}
          </div>

          {/* Contract updates */}
          <div>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>合约动态</div>
            {notifSubRow("contract_pending_sign", "待签署提醒")}
            {notifSubRow("contract_signed", "签署成功通知")}
          </div>

          {/* Fund changes */}
          <div>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>资金变动</div>
            {notifSubRow("fund_deposit", "充值成功通知")}
            {notifSubRow("fund_withdraw", "提现到账通知")}
          </div>

          {/* Talent updates */}
          <div>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>人才动态</div>
            {notifSubRow("talent_org_invite", "组织邀约申请")}
            {notifSubRow("talent_agent_msg", "Agent 消息通知")}
          </div>

          {/* System announcements */}
          <div>
            <div style={{ fontWeight: 500, marginBottom: 6 }}>系统公告</div>
            {notifSubRow("system_announcements", "平台维护与功能更新")}
          </div>
        </div>
      </GlowCard>

      <Divider style={{ borderColor: "var(--border)" }} />

      {/* ═══ Section 3: Security Settings ═══ */}
      <GlowCard color="purple" title={<span><LockOutlined style={{ marginRight: 6 }} />安全设置</span>} style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Password change */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontWeight: 500 }}>修改密码</div>
              <div style={{ fontSize: 12, color: "var(--text-3)" }}>定期修改密码以保障账户安全</div>
            </div>
            <Button icon={<LockOutlined />} onClick={() => setPwdOpen(true)}>修改密码</Button>
          </div>

          {/* Two-factor auth */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 500 }}>
                  二次验证 (2FA)
                  {twoFaBound && <span className="neon-tag-green" style={{ fontSize: 10, marginLeft: 8 }}>已绑定</span>}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-3)" }}>使用 Google Authenticator 或短信进行两步验证</div>
              </div>
              {twoFaBound ? (
                <Popconfirm title="确认解绑二次验证？" onConfirm={handle2faUnbind} okText="解绑" cancelText="取消" okButtonProps={{ danger: true }}>
                  <Button danger size="small">解绑</Button>
                </Popconfirm>
              ) : (
                <Switch checked={twoFactor} onChange={(v) => setTwoFactor(v)} checkedChildren={<SafetyOutlined />} />
              )}
            </div>
            {twoFactor && !twoFaBound && (
              <div style={{
                marginTop: 12, padding: "16px", borderRadius: 10,
                background: "rgba(168,85,247,0.04)", border: "1px solid rgba(168,85,247,0.12)",
              }}>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>
                  请使用 Google Authenticator 扫描以下二维码：
                </div>
                <div style={{
                  width: 140, height: 140, margin: "0 auto 12px", borderRadius: 8,
                  background: "rgba(255,255,255,0.08)", border: "1px dashed rgba(255,255,255,0.15)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <QrcodeOutlined style={{ fontSize: 48, color: "var(--text-3)" }} />
                </div>
                <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                  <Input value={twoFaCode} onChange={(e) => setTwoFaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="输入 6 位验证码" style={{ width: 160, textAlign: "center" }} className="mono" maxLength={6} />
                  <Button type="primary" onClick={handle2faVerify} disabled={twoFaCode.length !== 6}>验证</Button>
                </div>
              </div>
            )}
          </div>

          {/* Device management */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontWeight: 500 }}>登录设备管理</div>
                <div style={{ fontSize: 12, color: "var(--text-3)" }}>查看和管理已登录的设备</div>
              </div>
              <Button type="link" icon={<LaptopOutlined />} onClick={() => setShowDevices(!showDevices)}
                style={{ color: "var(--cyan)" }}>
                {showDevices ? "收起" : "管理设备"} {showDevices ? null : <RightOutlined />}
              </Button>
            </div>
            {showDevices && (
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                {devices.map((d) => (
                  <div key={d.id} style={{
                    display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                    borderRadius: 8, background: d.current ? "rgba(34,211,238,0.04)" : "rgba(255,255,255,0.03)",
                    border: d.current ? "1px solid rgba(34,211,238,0.12)" : "1px solid rgba(255,255,255,0.06)",
                  }}>
                    {d.type === "mobile" ? <MobileOutlined style={{ fontSize: 18, color: "var(--text-3)" }} /> :
                      <DesktopOutlined style={{ fontSize: 18, color: "var(--text-3)" }} />}
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-1)" }}>
                        {d.name}
                        {d.current && <span className="neon-tag-green" style={{ fontSize: 9, marginLeft: 8 }}>当前设备</span>}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-3)" }}>
                        IP: {d.ip} | {d.time}
                      </div>
                    </div>
                    {!d.current && (
                      <Button size="small" danger type="text" onClick={() => msg.success("设备已下线")}>下线</Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Operation audit log */}
          <div>
            <div style={{ fontWeight: 500, marginBottom: 10 }}>
              <HistoryOutlined style={{ marginRight: 6 }} />操作日志
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {auditLogs.map((log, idx) => (
                <div key={idx} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
                  borderRadius: 6, background: "rgba(255,255,255,0.02)", fontSize: 12,
                }}>
                  {log.status === "success"
                    ? <CheckCircleOutlined style={{ color: "var(--success)", fontSize: 13 }} />
                    : <CloseCircleOutlined style={{ color: "var(--error)", fontSize: 13 }} />}
                  <span style={{ flex: 1, color: "var(--text-2)" }}>{log.action}</span>
                  <span className="mono" style={{ color: "var(--text-3)", fontSize: 11 }}>{log.ip}</span>
                  <span style={{ color: "var(--text-3)", fontSize: 11, minWidth: 80 }}>{log.time}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </GlowCard>

      <Divider style={{ borderColor: "var(--border)" }} />

      {/* ═══ Section 4: Privacy ═══ */}
      <GlowCard color="cyan" title={<span><SafetyOutlined style={{ marginRight: 6 }} />隐私设置</span>} style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontWeight: 500 }}>个人主页可见性</div>
              <div style={{ fontSize: 12, color: "var(--text-3)" }}>控制谁可以查看你的个人主页</div>
            </div>
            <Select value={profileVisibility} onChange={setProfileVisibility} style={{ width: 140 }}
              options={[{ value: "public", label: "公开" }, { value: "partners", label: "仅合作方" }, { value: "private", label: "私密" }]} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontWeight: 500 }}>搜索可发现</div>
              <div style={{ fontSize: 12, color: "var(--text-3)" }}>是否允许在 Agent 人才市场中被搜索发现</div>
            </div>
            <Switch checked={searchable} onChange={setSearchable} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontWeight: 500 }}>合作历史公开</div>
              <div style={{ fontSize: 12, color: "var(--text-3)" }}>是否公开展示过往合作记录和评价</div>
            </div>
            <Switch checked={historyPublic} onChange={setHistoryPublic} />
          </div>
          <div style={{ paddingTop: 8 }}>
            <Button type="primary" className="btn-gradient" icon={<SaveOutlined />}
              onClick={() => msg.success("隐私设置已保存")}>保存隐私设置</Button>
          </div>
        </div>
      </GlowCard>

      <Divider style={{ borderColor: "var(--border)" }} />

      {/* ═══ Section 5: Account Management ═══ */}
      <GlowCard color="blue" title={<span><SettingOutlined style={{ marginRight: 6 }} />账户管理</span>}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontWeight: 500, color: "#ff4d4f" }}>注销账户</div>
            <div style={{ fontSize: 12, color: "var(--text-3)" }}>注销后账户数据将被永久删除，此操作不可撤销</div>
          </div>
          <Button danger icon={<DeleteOutlined />} onClick={startDeleteFlow}>注销账户</Button>
        </div>
      </GlowCard>

      {/* Password change modal */}
      <Modal title="修改密码" open={pwdOpen} onCancel={() => { setPwdOpen(false); setOldPwd(""); setNewPwd(""); setConfirmPwd(""); }}
        onOk={handlePasswordChange} confirmLoading={pwdLoading} okText="确认修改" cancelText="取消"
        okButtonProps={{ disabled: !oldPwd || !newPwd || newPwd.length < 6 || newPwd !== confirmPwd }}>
        <Form layout="vertical">
          <Form.Item label="原密码"><Input.Password value={oldPwd} onChange={(e) => setOldPwd(e.target.value)} placeholder="输入原密码" /></Form.Item>
          <Form.Item label="新密码"><Input.Password value={newPwd} onChange={(e) => setNewPwd(e.target.value)} placeholder="输入新密码（至少6位）" /></Form.Item>
          <Form.Item label="确认新密码"><Input.Password value={confirmPwd} onChange={(e) => setConfirmPwd(e.target.value)} placeholder="再次输入新密码" /></Form.Item>
          {newPwd && confirmPwd && newPwd !== confirmPwd && (
            <div style={{ color: "#ff4d4f", fontSize: 12 }}>两次密码不一致</div>
          )}
        </Form>
      </Modal>

      {/* Account deletion 4-step modal */}
      <Modal title="注销账户" open={deleteStep > 0} width={520}
        onCancel={() => { setDeleteStep(0); setDeletePwd(""); }}
        footer={[
          <Button key="cancel" onClick={() => { if (deleteStep === 1) setDeleteStep(0); else setDeleteStep(deleteStep - 1); }}>
            {deleteStep === 1 ? "取消" : "上一步"}
          </Button>,
          deleteStep < 4 ? (
            <Button key="next" danger onClick={() => setDeleteStep(deleteStep + 1)}
              loading={deleteStep === 2 && deleteLoading}
              disabled={deleteStep === 2 && deleteLoading}>
              {deleteStep === 1 ? "我已阅读，继续" : "下一步"}
            </Button>
          ) : (
            <Button key="confirm" danger disabled={!deletePwd} onClick={handleDeleteAccount}>确认注销</Button>
          ),
        ]}>
        <Steps current={deleteStep - 1} size="small" style={{ marginBottom: 20 }}
          items={[
            { title: "注销须知" },
            { title: "资产清算" },
            { title: "合约检查" },
            { title: "身份验证" },
          ]} />

        {deleteStep === 1 && (
          <div style={{ lineHeight: 2, fontSize: 13 }}>
            <div style={{ fontWeight: 600, color: "#ff4d4f", marginBottom: 8 }}>
              <ExclamationCircleOutlined style={{ marginRight: 4 }} />注销须知
            </div>
            <ul style={{ paddingLeft: 16, color: "var(--text-2)" }}>
              <li>注销后，所有个人数据、项目记录、合约记录将被永久删除</li>
              <li>进行中的合约将自动终止，托管资金将退回原账户</li>
              <li>已完成的结算不受影响</li>
              <li>此操作不可撤销</li>
            </ul>
          </div>
        )}

        {deleteStep === 2 && (
          <div style={{ fontSize: 13 }}>
            <div style={{ fontWeight: 600, color: "#f59e0b", marginBottom: 12 }}>
              <DollarOutlined style={{ marginRight: 4 }} />资产清算检查
            </div>
            {deleteLoading ? <Spin style={{ display: "block", margin: "20px auto" }} /> : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{
                  padding: "10px 14px", borderRadius: 8,
                  background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
                  display: "flex", justifyContent: "space-between",
                }}>
                  <span style={{ color: "var(--text-2)" }}>账户余额</span>
                  <span className="mono" style={{ color: (deleteWallet?.balance ?? 0) > 0 ? "#f59e0b" : "var(--success)" }}>
                    ¥{(deleteWallet?.balance ?? 0).toFixed(2)}
                  </span>
                </div>
                <div style={{
                  padding: "10px 14px", borderRadius: 8,
                  background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
                  display: "flex", justifyContent: "space-between",
                }}>
                  <span style={{ color: "var(--text-2)" }}>冻结金额</span>
                  <span className="mono" style={{ color: (deleteWallet?.frozen ?? 0) > 0 ? "var(--error)" : "var(--success)" }}>
                    ¥{(deleteWallet?.frozen ?? 0).toFixed(2)}
                  </span>
                </div>
                {(deleteWallet?.balance ?? 0) > 0 && (
                  <div style={{ fontSize: 12, color: "#f59e0b", padding: "6px 0" }}>
                    <ExclamationCircleOutlined style={{ marginRight: 4 }} />
                    建议先提现剩余资金，注销后余额将无法取回
                  </div>
                )}
                {(deleteWallet?.frozen ?? 0) > 0 && (
                  <div style={{ fontSize: 12, color: "var(--error)", padding: "6px 0" }}>
                    <ExclamationCircleOutlined style={{ marginRight: 4 }} />
                    您有冻结中的资金，注销后将自动退回对方账户
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {deleteStep === 3 && (
          <div style={{ fontSize: 13 }}>
            <div style={{ fontWeight: 600, color: "#a855f7", marginBottom: 12 }}>
              <FileTextOutlined style={{ marginRight: 4 }} />进行中合约检查
            </div>
            {deleteContracts.length === 0 ? (
              <div style={{
                padding: "16px", borderRadius: 8, textAlign: "center",
                background: "rgba(0,208,132,0.04)", border: "1px solid rgba(0,208,132,0.12)",
              }}>
                <CheckCircleOutlined style={{ fontSize: 20, color: "var(--success)", marginBottom: 6 }} />
                <div style={{ color: "var(--success)" }}>无进行中合约</div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ fontSize: 12, color: "var(--error)", marginBottom: 4 }}>
                  <ExclamationCircleOutlined style={{ marginRight: 4 }} />
                  以下 {deleteContracts.length} 份合约将自动终止：
                </div>
                {deleteContracts.map((c) => (
                  <div key={c.id} style={{
                    display: "flex", justifyContent: "space-between", padding: "8px 12px",
                    borderRadius: 6, background: "rgba(255,77,79,0.04)", border: "1px solid rgba(255,77,79,0.10)",
                    fontSize: 12,
                  }}>
                    <span style={{ color: "var(--text-1)" }}>{c.title}</span>
                    <span className="mono" style={{ color: "var(--text-3)" }}>¥{Number(c.budget_amount).toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {deleteStep === 4 && (
          <div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 12 }}>请输入登录密码以确认身份：</div>
            <Input.Password value={deletePwd} onChange={(e) => setDeletePwd(e.target.value)} placeholder="输入密码确认" />
          </div>
        )}
      </Modal>
    </div>
  );
}

// ── Main Account Page ──
export default function AccountPage() {
  const { currentUser } = useCurrentUser();

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <h2 style={{ margin: 0 }}>
          <UserOutlined style={{ marginRight: 8, color: "var(--cyan)" }} />
          我的账户
          {currentUser && (
            <span
              style={{
                fontSize: 14,
                color: "var(--text-3)",
                fontWeight: 400,
                marginLeft: 12,
              }}
            >
              @{currentUser.username}
            </span>
          )}
        </h2>
      </div>

      <Tabs
        defaultActiveKey="wallet"
        items={[
          {
            key: "wallet",
            label: (
              <span>
                <WalletOutlined /> 钱包
              </span>
            ),
            children: <WalletTab />,
          },
          {
            key: "settings",
            label: (
              <span>
                <SettingOutlined /> 设置
              </span>
            ),
            children: <SettingsTab />,
          },
        ]}
      />
    </div>
  );
}
