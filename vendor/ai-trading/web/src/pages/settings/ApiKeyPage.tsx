import { useState, useEffect } from "react";
import {
  Table, Button, Modal, Form, Input, InputNumber,
  Typography, Space, Tag, App, Tooltip, Popconfirm,
} from "antd";
import {
  PlusOutlined, CopyOutlined, DeleteOutlined, EditOutlined,
  KeyOutlined, CheckCircleOutlined, StopOutlined,
} from "@ant-design/icons";
import GlowCard from "../../components/GlowCard";
import { apiKeyApi } from "../../api/services";
import type { ApiKeyRecord } from "../../api/services";
import dayjs from "dayjs";

const { Title, Text, Paragraph } = Typography;

export default function ApiKeyPage() {
  const { message, modal } = App.useApp();

  const [keys, setKeys] = useState<ApiKeyRecord[]>([]);
  const [loading, setLoading] = useState(false);

  // create modal
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [creating, setCreating] = useState(false);

  // edit modal
  const [editKey, setEditKey] = useState<ApiKeyRecord | null>(null);
  const [editForm] = Form.useForm();
  const [editing, setEditing] = useState(false);

  const fetchKeys = async () => {
    setLoading(true);
    try {
      const { data } = await apiKeyApi.list();
      setKeys(data.items);
    } catch {
      setKeys([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchKeys(); }, []);

  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields();
      setCreating(true);
      const { data } = await apiKeyApi.create(values);

      // Show raw key exactly ONCE
      modal.success({
        title: "API Key 已创建",
        width: 560,
        content: (
          <div>
            <Paragraph type="warning" style={{ marginBottom: 8 }}>
              请立即复制并保存此 Key，关闭后将无法再次查看。
            </Paragraph>
            <div style={{
              background: "#000000",
              border: "1px solid rgba(0,212,255,0.3)",
              borderRadius: 6,
              padding: "10px 14px",
              fontFamily: "monospace",
              fontSize: 13,
              wordBreak: "break-all",
              color: "#00d4ff",
              display: "flex",
              alignItems: "center",
              gap: 10,
            }}>
              <span style={{ flex: 1 }}>{data.key}</span>
              <Tooltip title="复制">
                <Button
                  type="text"
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => {
                    navigator.clipboard.writeText(data.key ?? "");
                    message.success("已复制");
                  }}
                />
              </Tooltip>
            </div>
          </div>
        ),
        okText: "我已保存",
      });

      setCreateOpen(false);
      createForm.resetFields();
      fetchKeys();
    } catch {
      // validation
    } finally {
      setCreating(false);
    }
  };

  const handleEdit = async () => {
    if (!editKey) return;
    try {
      const values = await editForm.validateFields();
      setEditing(true);
      await apiKeyApi.update(editKey.id, values);
      message.success("已更新");
      setEditKey(null);
      fetchKeys();
    } catch {
      // validation
    } finally {
      setEditing(false);
    }
  };

  const handleToggleActive = async (key: ApiKeyRecord) => {
    try {
      await apiKeyApi.update(key.id, { is_active: !key.is_active });
      message.success(key.is_active ? "已禁用" : "已启用");
      fetchKeys();
    } catch {
      message.error("操作失败");
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await apiKeyApi.delete(id);
      message.success("已删除");
      fetchKeys();
    } catch {
      message.error("删除失败");
    }
  };

  const openEdit = (key: ApiKeyRecord) => {
    setEditKey(key);
    editForm.setFieldsValue({
      name: key.name,
      description: key.description,
      rate_limit_rpm: key.rate_limit_rpm,
    });
  };

  const columns = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      render: (name: string, record: ApiKeyRecord) => (
        <Space>
          <KeyOutlined style={{ color: "var(--cyan)", opacity: 0.7 }} />
          <Text strong>{name}</Text>
          {!record.is_active && <Tag color="default">已禁用</Tag>}
        </Space>
      ),
    },
    {
      title: "Key 前缀",
      dataIndex: "key_prefix",
      key: "key_prefix",
      render: (v: string) => (
        <Text style={{ fontFamily: "monospace", fontSize: 12, color: "var(--text-2)" }}>{v}</Text>
      ),
    },
    {
      title: "描述",
      dataIndex: "description",
      key: "description",
      render: (v?: string) => v ? <Text type="secondary">{v}</Text> : <Text type="secondary">—</Text>,
    },
    {
      title: "限速 (RPM)",
      dataIndex: "rate_limit_rpm",
      key: "rate_limit_rpm",
      width: 110,
      render: (v?: number) => v != null ? <Tag>{v}</Tag> : <Text type="secondary">默认</Text>,
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      width: 80,
      render: (active: boolean) => active
        ? <Tag icon={<CheckCircleOutlined />} color="green">活跃</Tag>
        : <Tag icon={<StopOutlined />} color="default">禁用</Tag>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 150,
      render: (d: string) => dayjs(d).format("YYYY-MM-DD HH:mm"),
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_: unknown, record: ApiKeyRecord) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            icon={record.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
            onClick={() => handleToggleActive(record)}
          >
            {record.is_active ? "禁用" : "启用"}
          </Button>
          <Popconfirm title="确认删除此 Key？" onConfirm={() => handleDelete(record.id)} okText="删除" cancelText="取消">
            <Button type="link" danger size="small" icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4}>API Key 管理</Title>
      <Paragraph type="secondary" style={{ marginBottom: 20, maxWidth: 600 }}>
        外部系统通过 A2A 协议调用本平台 Agent 时，需在请求头中携带：
        <Text code style={{ marginLeft: 6, fontSize: 12 }}>Authorization: Bearer &lt;key&gt;</Text>
      </Paragraph>

      <GlowCard color="cyan">
        <div style={{ marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Text type="secondary">共 {keys.length} 个 Key</Text>
          <Button icon={<PlusOutlined />} type="primary" onClick={() => setCreateOpen(true)}>
            创建 API Key
          </Button>
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={keys}
          loading={loading}
          pagination={false}
          locale={{ emptyText: "暂无 API Key，点击右上角创建" }}
        />
      </GlowCard>

      {/* Create Modal */}
      <Modal
        title="创建 API Key"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="例：Google ADK 测试客户端" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} placeholder="用途说明" />
          </Form.Item>
          <Form.Item name="rate_limit_rpm" label="限速（每分钟请求数，留空使用全局默认）">
            <InputNumber min={1} max={10000} style={{ width: "100%" }} placeholder="默认 60" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Edit Modal */}
      <Modal
        title="编辑 API Key"
        open={!!editKey}
        onOk={handleEdit}
        onCancel={() => setEditKey(null)}
        okText="保存"
        cancelText="取消"
        confirmLoading={editing}
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="rate_limit_rpm" label="限速（每分钟请求数）">
            <InputNumber min={1} max={10000} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
