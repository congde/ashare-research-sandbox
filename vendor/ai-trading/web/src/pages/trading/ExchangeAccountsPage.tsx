import {
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  exchangeAccountApi,
  type ExchangeAccountCreate,
  type ExchangeAccountResponse,
  type ExchangeName,
} from "../../api/services";
import {
  MetricTile,
  QuantGlowCard,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";
import { accountPlaceholders } from "./tradingData";

interface AccountRow {
  id: string;
  exchange: string;
  label: string;
  fingerprint: string;
  permissions: string;
  mode: string;
  state: string;
  verifiedAt: string;
  source: "api" | "placeholder";
}

const EXCHANGE_OPTIONS: { label: string; value: ExchangeName }[] = [
  { label: "Binance", value: "binance" },
  { label: "OKX", value: "okx" },
  { label: "Bybit", value: "bybit" },
  { label: "Coinbase", value: "coinbase" },
  { label: "Hyperliquid", value: "hyperliquid" },
];

// `withdraw` is a hard product/security red line — the backend rejects it
// outright, so it is intentionally not offered as a togglable permission.
const PERMISSION_OPTIONS: { label: string; value: "spot" | "futures" | "margin" }[] = [
  { label: "现货 spot", value: "spot" },
  { label: "合约 futures", value: "futures" },
  { label: "杠杆 margin", value: "margin" },
];

interface CreateFormValues {
  exchange: ExchangeName;
  label: string;
  api_key: string;
  api_secret: string;
  api_passphrase?: string;
  permissions: ("spot" | "futures" | "margin")[];
  is_testnet: boolean;
}

function formatPermissions(permissions: Record<string, boolean>) {
  const enabled = Object.entries(permissions)
    .filter(([, active]) => active)
    .map(([key]) => key);
  return enabled.length ? enabled.join(" / ") : "readonly";
}

export default function ExchangeAccountsPage() {
  const [accounts, setAccounts] = useState<ExchangeAccountResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<CreateFormValues>();

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await exchangeAccountApi.list({ limit: 50 });
      setAccounts(response.data.items);
    } catch {
      setLoadError("交易账户接口暂不可用，当前显示本地占位账户。");
      setAccounts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  const closeCreate = useCallback(() => {
    setCreateOpen(false);
    form.resetFields();
  }, [form]);

  const handleCreate = useCallback(async () => {
    let values: CreateFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return; // antd renders inline field errors
    }

    const selected = values.permissions ?? [];
    const payload: ExchangeAccountCreate = {
      exchange: values.exchange,
      label: values.label.trim(),
      api_key: values.api_key.trim(),
      api_secret: values.api_secret.trim(),
      api_passphrase: values.api_passphrase?.trim() || undefined,
      permissions: {
        spot: selected.includes("spot"),
        futures: selected.includes("futures"),
        margin: selected.includes("margin"),
        withdraw: false,
      },
      is_testnet: values.is_testnet,
    };

    setSubmitting(true);
    try {
      await exchangeAccountApi.create(payload);
      message.success(
        `已新增 ${payload.exchange.toUpperCase()} 账户「${payload.label}」`,
      );
      setCreateOpen(false);
      form.resetFields();
      await loadAccounts();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      message.error(detail || "新增账户失败，请检查 API Key 与权限设置。");
    } finally {
      setSubmitting(false);
    }
  }, [form, loadAccounts]);

  const rows: AccountRow[] = useMemo(() => {
    if (accounts.length > 0) {
      return accounts.map((account) => ({
        id: account.id,
        exchange: account.exchange,
        label: account.label,
        fingerprint: account.fingerprint || "****",
        permissions: formatPermissions(account.permissions),
        mode: account.is_testnet ? "Testnet" : "Live",
        state: account.last_verified_at ? "已验证" : "待验证",
        verifiedAt: account.last_verified_at ?? "-",
        source: "api",
      }));
    }

    return accountPlaceholders.map((account, index) => ({
      id: `placeholder-${index}`,
      exchange: account.exchange,
      label: account.label,
      fingerprint: account.fingerprint,
      permissions: account.permissions,
      mode: account.state,
      state: "占位",
      verifiedAt: "-",
      source: "placeholder",
    }));
  }, [accounts]);

  const columns: ColumnsType<AccountRow> = [
    {
      title: "交易所",
      dataIndex: "exchange",
      render: (value, row) => (
        <Space direction="vertical" size={2}>
          <strong>{value.toUpperCase()}</strong>
          <span style={{ color: "var(--qa-text-2)", fontSize: 12 }}>{row.label}</span>
        </Space>
      ),
    },
    {
      title: "Key 指纹",
      dataIndex: "fingerprint",
    },
    {
      title: "权限",
      dataIndex: "permissions",
      render: (value: string) => <StatusPill tone={value.includes("withdraw") ? "loss" : "profit"}>{value}</StatusPill>,
    },
    {
      title: "模式",
      dataIndex: "mode",
      render: (value: string) => <StatusPill tone={value === "Live" ? "loss" : "neutral"}>{value}</StatusPill>,
    },
    {
      title: "状态",
      dataIndex: "state",
      render: (value: string, row) => (
        <StatusPill tone={row.source === "api" ? "profit" : "ai"}>{value}</StatusPill>
      ),
    },
    {
      title: "最近验证",
      dataIndex: "verifiedAt",
    },
  ];

  return (
    <TradingPageShell
      eyebrow="Exchange Accounts"
      title="交易账户"
      description="集中管理交易所 API Key、权限边界和 testnet/live 状态。默认禁止提现，实盘执行必须先通过风控审批。"
      actions={
        <>
          <Button onClick={loadAccounts} loading={loading}>
            <ReloadOutlined /> 同步账户
          </Button>
          <Button
            className="btn-gradient"
            type="primary"
            onClick={() => setCreateOpen(true)}
          >
            <PlusOutlined /> 新增账户
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          title={<SectionHeader title="权限护栏" description="账户接入默认最小权限" />}
          badge={<SafetyCertificateOutlined style={{ color: "var(--qa-profit)" }} />}
        >
          <div className="trading-list">
            <SignalRow title="提现权限" meta="永不启用，保存时强制校验" badge={<StatusPill tone="profit">disabled</StatusPill>} />
            <SignalRow title="Testnet 优先" meta="新策略先进入 paper/testnet" badge={<StatusPill tone="neutral">default</StatusPill>} />
            <SignalRow title="Key 加密" meta="后端 KMS 密文存储，前端只展示指纹" badge={<StatusPill tone="ai">sealed</StatusPill>} />
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <div className="trading-metric-grid">
            <MetricTile label="已接账户" value={rows.length} />
            <MetricTile label="API 来源" value={accounts.length > 0 ? "后端" : "占位"} tone={accounts.length > 0 ? "profit" : "ai"} />
            <MetricTile label="Live 账户" value={rows.filter((row) => row.mode === "Live").length} tone="loss" />
            <MetricTile label="提现权限" value="0" tone="profit" subtle="必须保持关闭" />
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-12"
          title={<SectionHeader title="账户列表" description="已有 exchange-accounts API 可接入真实数据" />}
        >
          {loadError && <Alert type="warning" message={loadError} showIcon style={{ marginBottom: 14 }} />}
          <Table
            className="trading-ant-table"
            columns={columns}
            dataSource={rows}
            loading={loading}
            pagination={false}
            rowKey="id"
            scroll={{ x: 860 }}
          />
        </QuantGlowCard>
      </section>

      <Modal
        title="新增交易账户"
        open={createOpen}
        onOk={handleCreate}
        onCancel={closeCreate}
        confirmLoading={submitting}
        okText="保存账户"
        cancelText="取消"
        okButtonProps={{ className: "btn-gradient" }}
        maskClosable={!submitting}
      >
        <Alert
          type="info"
          showIcon
          message="API Key 由后端 KMS 密文存储"
          description="提现权限永久禁用，前端只保留指纹。OKX / Coinbase 需额外填写 Passphrase。"
          style={{ marginBottom: 16 }}
        />
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            exchange: "binance",
            label: "default",
            is_testnet: true,
            permissions: ["spot"],
          }}
        >
          <Form.Item
            name="exchange"
            label="交易所"
            rules={[{ required: true, message: "请选择交易所" }]}
          >
            <Select options={EXCHANGE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="label"
            label="账户标签"
            rules={[
              { required: true, message: "请输入账户标签" },
              { max: 64, message: "标签不超过 64 字符" },
            ]}
          >
            <Input placeholder="例如 main / hedge / testnet-1" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            rules={[{ required: true, message: "请输入 API Key" }]}
          >
            <Input placeholder="交易所生成的 API Key" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="api_secret"
            label="API Secret"
            rules={[{ required: true, message: "请输入 API Secret" }]}
          >
            <Input.Password placeholder="交易所生成的 API Secret" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="api_passphrase"
            label="Passphrase（OKX / Coinbase 必填）"
          >
            <Input.Password placeholder="可选，部分交易所需要" autoComplete="off" />
          </Form.Item>
          <Form.Item name="permissions" label="权限范围">
            <Checkbox.Group options={PERMISSION_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="is_testnet"
            label="Testnet 模式"
            valuePropName="checked"
            extra="新接入账户默认进入 testnet，实盘需后续在风控审批后切换。"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </TradingPageShell>
  );
}
