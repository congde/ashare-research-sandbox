import { useState, useEffect } from "react";
import { Statistic, Table, Tag, Button, Modal, InputNumber, Input, Form, App, Row, Col, Spin, Tabs, Typography, Tooltip, Switch, Popconfirm } from "antd";
import GlowCard from "../../components/GlowCard";
import { WalletOutlined, PlusCircleOutlined, LinkOutlined, ThunderboltOutlined, CopyOutlined, SyncOutlined } from "@ant-design/icons";
import { walletApi } from "../../api/services";
import type { Wallet, WalletTransaction, OnchainSettlement, OnchainAddress } from "../../api/services";
import type { ColumnsType } from "antd/es/table";

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

const ONCHAIN_TYPE_LABEL: Record<string, string> = {
  x402_inbound: "x402 收款",
  x402_outbound: "x402 付款",
  revenue_split: "收益分账",
  platform_fee: "平台手续费",
};

const CHAIN_NAME: Record<number, string> = {
  84532: "Base Sepolia",
  8453: "Base",
  1: "Ethereum",
};

export default function WalletPage() {
  const { message: msg } = App.useApp();
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [transactions, setTransactions] = useState<WalletTransaction[]>([]);
  const [onchainSettlements, setOnchainSettlements] = useState<OnchainSettlement[]>([]);
  const [walletLoading, setWalletLoading] = useState(true);
  const [txLoading, setTxLoading] = useState(false);
  const [onchainLoading, setOnchainLoading] = useState(false);
  const [depositOpen, setDepositOpen] = useState(false);
  const [depositing, setDepositing] = useState(false);
  const [onchainAddr, setOnchainAddr] = useState<OnchainAddress | null>(null);
  const [addrLoading, setAddrLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [form] = Form.useForm();

  const loadWallet = async () => {
    setWalletLoading(true);
    try {
      const res = await walletApi.get();
      setWallet(res.data);
    } catch {
      msg.error("加载钱包失败");
    } finally {
      setWalletLoading(false);
    }
  };

  const loadTransactions = async () => {
    setTxLoading(true);
    try {
      const res = await walletApi.listTransactions({ limit: 100 });
      setTransactions(res.data.items ?? []);
    } catch {
      // non-fatal
    } finally {
      setTxLoading(false);
    }
  };

  const loadOnchainSettlements = async () => {
    setOnchainLoading(true);
    try {
      const res = await walletApi.listOnchainSettlements({ limit: 100 });
      setOnchainSettlements(res.data.items ?? []);
    } catch {
      // non-fatal
    } finally {
      setOnchainLoading(false);
    }
  };

  // Initial load: skip USDC balance (avoids slow external RPC call on page load)
  const loadOnchainAddr = async (refreshBalance = false) => {
    setAddrLoading(true);
    try {
      const res = await walletApi.getOnchainAddress(refreshBalance);
      setOnchainAddr(res.data);
    } catch {
      // non-fatal
    } finally {
      setAddrLoading(false);
    }
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await walletApi.generateOnchainAddress();
      msg.success("链上地址已生成");
      await loadOnchainAddr(false); // address only; user can refresh balance manually
    } catch {
      msg.error("生成失败，请稍后重试");
    } finally {
      setGenerating(false);
    }
  };

  const handlePayoutToggle = async (checked: boolean) => {
    try {
      const res = await walletApi.updatePayoutMethod(checked ? "onchain" : "credits");
      setOnchainAddr(res.data);
      msg.success(checked ? "已切换为链上收款" : "已切换为 Credits 收款");
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      msg.error(err?.response?.data?.detail || "切换失败");
    }
  };

  useEffect(() => {
    loadWallet();
    loadTransactions();
    loadOnchainSettlements();
    loadOnchainAddr();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDeposit = async (values: { amount: number; note?: string }) => {
    setDepositing(true);
    try {
      await walletApi.deposit(String(values.amount), values.note);
      msg.success("充值成功");
      setDepositOpen(false);
      form.resetFields();
      loadWallet();
      loadTransactions();
    } catch {
      msg.error("充值失败");
    } finally {
      setDepositing(false);
    }
  };

  const columns: ColumnsType<WalletTransaction> = [
    {
      title: "类型",
      dataIndex: "tx_type",
      render: (t) => (
        <Tag color={TX_TYPE_COLOR[t] ?? "default"}>{TX_TYPE_LABEL[t] ?? t}</Tag>
      ),
    },
    {
      title: "金额",
      dataIndex: "amount",
      render: (v) => {
        const n = Number(v);
        return (
          <span style={{ color: n >= 0 ? "var(--success)" : "#ff4d4f" }}>
            {n >= 0 ? "+" : ""}{n.toFixed(2)}
          </span>
        );
      },
    },
    {
      title: "余额（变后）",
      dataIndex: "balance_after",
      render: (v) => Number(v).toFixed(2),
    },
    {
      title: "关联类型",
      dataIndex: "reference_type",
      render: (v) => v || "—",
    },
    {
      title: "备注",
      dataIndex: "note",
      render: (v) => v || "—",
      ellipsis: true,
    },
    {
      title: "时间",
      dataIndex: "created_at",
      render: (v) => new Date(v).toLocaleString(),
    },
  ];

  if (walletLoading) return <Spin style={{ display: "block", margin: "40px auto" }} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>
          <WalletOutlined /> 我的钱包
        </h2>
        <Button
          type="primary"
          icon={<PlusCircleOutlined />}
          onClick={() => setDepositOpen(true)}
        >
          充值
        </Button>
      </div>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <GlowCard color="cyan">
            <Statistic
              title="可用余额"
              value={Number(wallet?.balance ?? 0).toFixed(2)}
              suffix="积分"
              valueStyle={{ color: "var(--primary)" }}
            />
          </GlowCard>
        </Col>
        <Col span={6}>
          <GlowCard color="cyan">
            <Statistic
              title="托管中（冻结）"
              value={Number(wallet?.frozen_amount ?? 0).toFixed(2)}
              suffix="积分"
              valueStyle={{ color: "#fa8c16" }}
            />
          </GlowCard>
        </Col>
        <Col span={6}>
          <GlowCard color="cyan">
            <Statistic
              title="累计收入"
              value={Number(wallet?.total_earned ?? 0).toFixed(2)}
              suffix="积分"
              valueStyle={{ color: "var(--success)" }}
            />
          </GlowCard>
        </Col>
        <Col span={6}>
          <GlowCard color="cyan">
            <Statistic
              title="累计支出"
              value={Number(wallet?.total_spent ?? 0).toFixed(2)}
              suffix="积分"
              valueStyle={{ color: "#ff4d4f" }}
            />
          </GlowCard>
        </Col>
      </Row>

      {/* On-chain Address Card */}
      <GlowCard color="purple" style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <ThunderboltOutlined style={{ fontSize: 18, color: "var(--purple)" }} />
            <span style={{ fontWeight: 600, fontSize: 15 }}>链上钱包地址</span>
            <Tag color="purple" style={{ marginLeft: 4 }}>Base Network</Tag>
          </div>
          {addrLoading ? (
            <Spin size="small" />
          ) : onchainAddr?.wallet_address ? (
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <Typography.Text
                style={{ fontFamily: "monospace", fontSize: 13, color: "var(--text-1)" }}
                copyable={{ icon: <CopyOutlined />, tooltips: ["复制地址", "已复制"] }}
              >
                {onchainAddr.wallet_address}
              </Typography.Text>
              {onchainAddr.usdc_balance && (
                <Tag color="cyan" style={{ fontFamily: "monospace" }}>
                  {onchainAddr.usdc_balance}
                </Tag>
              )}
              <Tooltip title="刷新 USDC 余额">
                <Button
                  size="small"
                  icon={<SyncOutlined />}
                  onClick={() => loadOnchainAddr(true)}
                  loading={addrLoading}
                />
              </Tooltip>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 12, color: "var(--text-3)" }}>收款方式：</span>
                <Popconfirm
                  title={onchainAddr.payout_method === "onchain"
                    ? "切换为 Credits 内部结算？"
                    : "切换为链上 USDC 直接收款？"}
                  onConfirm={() => handlePayoutToggle(onchainAddr.payout_method !== "onchain")}
                  okText="确认"
                  cancelText="取消"
                >
                  <Switch
                    size="small"
                    checked={onchainAddr.payout_method === "onchain"}
                    checkedChildren="链上"
                    unCheckedChildren="积分"
                  />
                </Popconfirm>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: "var(--text-3)", fontSize: 13 }}>尚未生成链上地址</span>
              <Button
                type="primary"
                size="small"
                icon={<ThunderboltOutlined />}
                loading={generating}
                onClick={handleGenerate}
                style={{ background: "linear-gradient(135deg, #a855f7 0%, #6366f1 100%)", border: "none" }}
              >
                生成链上地址
              </Button>
            </div>
          )}
        </div>
        {onchainAddr?.wallet_address && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-3)" }}>
            <LinkOutlined style={{ marginRight: 4 }} />
            <a
              href={`https://basescan.org/address/${onchainAddr.wallet_address}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "var(--text-3)" }}
            >
              在 Basescan 查看
            </a>
          </div>
        )}
      </GlowCard>

      <Tabs
        items={[
          {
            key: "credits",
            label: "积分交易明细",
            children: (
              <GlowCard color="cyan">
                <Table
                  rowKey="id"
                  columns={columns}
                  dataSource={transactions}
                  loading={txLoading}
                  pagination={{ pageSize: 20 }}
                />
              </GlowCard>
            ),
          },
          {
            key: "onchain",
            label: `链上结算记录（${onchainSettlements.length}）`,
            children: (() => {
              const onchainColumns: ColumnsType<OnchainSettlement> = [
                {
                  title: "类型",
                  dataIndex: "settlement_type",
                  render: (t) => <Tag color="geekblue">{ONCHAIN_TYPE_LABEL[t] ?? t}</Tag>,
                },
                {
                  title: "金额（USDC）",
                  dataIndex: "amount_usdc",
                  render: (v) => (
                    <span style={{ color: "var(--success)", fontWeight: 600 }}>
                      +{Number(v).toFixed(6)}
                    </span>
                  ),
                },
                {
                  title: "状态",
                  dataIndex: "status",
                  render: (s) => {
                    const COLOR: Record<string, string> = { pending: "warning", confirmed: "success", failed: "error" };
                    const LABEL: Record<string, string> = { pending: "待确认", confirmed: "已确认", failed: "失败" };
                    return <Tag color={COLOR[s] ?? "default"}>{LABEL[s] ?? s}</Tag>;
                  },
                },
                {
                  title: "网络",
                  dataIndex: "chain_id",
                  render: (id) => <Tag color="cyan">{CHAIN_NAME[id] ?? `Chain ${id}`}</Tag>,
                },
                {
                  title: "交易哈希",
                  dataIndex: "tx_hash",
                  render: (hash, row) =>
                    hash ? (
                      <Typography.Text
                        copyable={{ text: hash }}
                        style={{ fontFamily: "monospace", fontSize: 12 }}
                      >
                        <a
                          href={`https://${row.chain_id === 8453 ? "" : "sepolia."}basescan.org/tx/${hash}`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {hash.slice(0, 10)}…{hash.slice(-6)} <LinkOutlined />
                        </a>
                      </Typography.Text>
                    ) : "—",
                },
                {
                  title: "确认时间",
                  dataIndex: "confirmed_at",
                  render: (v) => v ? new Date(v).toLocaleString() : "—",
                },
                {
                  title: "创建时间",
                  dataIndex: "created_at",
                  render: (v) => new Date(v).toLocaleString(),
                },
              ];
              return (
                <GlowCard color="cyan">
                  <Table
                    rowKey="id"
                    columns={onchainColumns}
                    dataSource={onchainSettlements}
                    loading={onchainLoading}
                    pagination={{ pageSize: 20 }}
                    locale={{ emptyText: "暂无链上结算记录（链上功能启用后自动同步）" }}
                  />
                </GlowCard>
              );
            })(),
          },
        ]}
      />

      <Modal
        title="充值"
        open={depositOpen}
        onCancel={() => setDepositOpen(false)}
        onOk={() => form.submit()}
        okText="确认充值"
        cancelText="取消"
        confirmLoading={depositing}
      >
        <Form form={form} layout="vertical" onFinish={handleDeposit}>
          <Form.Item
            name="amount"
            label="充值金额（积分）"
            rules={[{ required: true, message: "请输入金额" }]}
          >
            <InputNumber min={1} max={9999999} step={100} style={{ width: "100%" }} placeholder="输入充值金额（最大 9,999,999）" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input style={{ width: "100%" }} placeholder="可选备注" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
