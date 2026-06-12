import { useEffect, useState } from "react";
import { Table, Tag, Button, Space, Modal, Checkbox, App } from "antd";
import GlowCard from "../../components/GlowCard";
import { UserOutlined, CrownOutlined } from "@ant-design/icons";
import { userApi } from "../../api/services";
import type { UserProfile } from "../../api/services";

const ROLE_CONFIG: Record<string, { label: string; color: string }> = {
  admin:    { label: "超级管理员", color: "red" },
  employer: { label: "雇主",       color: "blue" },
  operator: { label: "雇员", color: "green" },
};

const ALL_ROLES = ["admin", "employer", "operator"];

export default function UsersPage() {
  const { message: msg } = App.useApp();
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [editUser, setEditUser] = useState<UserProfile | null>(null);
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await userApi.list({ limit: 200 });
      setUsers(res.data.items ?? []);
    } catch {
      msg.error("加载用户列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSaveRoles = async () => {
    if (!editUser) return;
    setSaving(true);
    try {
      await userApi.updateRoles(editUser.id, selectedRoles);
      msg.success("角色已更新");
      setEditUser(null);
      load();
    } catch {
      msg.error("更新角色失败");
    } finally {
      setSaving(false);
    }
  };

  const columns = [
    {
      title: "用户",
      key: "user",
      render: (_: unknown, u: UserProfile) => (
        <Space>
          <UserOutlined style={{ color: "var(--primary)" }} />
          <div>
            <div style={{ fontWeight: 600 }}>{u.display_name}</div>
            <div style={{ fontSize: 12, color: "#8c8c8c" }}>@{u.username} · {u.email}</div>
          </div>
        </Space>
      ),
    },
    {
      title: "角色",
      dataIndex: "roles",
      render: (roles: string[]) => (
        <Space wrap>
          {roles.length === 0
            ? <Tag color="default">无角色</Tag>
            : roles.map((r) => (
                <Tag key={r} color={ROLE_CONFIG[r]?.color ?? "default"}>
                  {r === "admin" && <CrownOutlined style={{ marginRight: 4 }} />}
                  {ROLE_CONFIG[r]?.label ?? r}
                </Tag>
              ))
          }
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "is_active",
      render: (v: boolean) => <Tag color={v ? "success" : "error"}>{v ? "启用" : "停用"}</Tag>,
    },
    {
      title: "操作",
      render: (_: unknown, u: UserProfile) => (
        <Button
          size="small"
          onClick={() => { setEditUser(u); setSelectedRoles(u.roles); }}
        >
          编辑角色
        </Button>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}><CrownOutlined /> 用户管理</h2>
        <div style={{ color: "#8c8c8c", marginTop: 4, fontSize: 13 }}>
          管理平台用户的角色权限。每个用户可同时拥有多个角色。
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, marginBottom: 24 }}>
        {Object.entries(ROLE_CONFIG).map(([role, cfg]) => (
          <GlowCard key={role} color="blue" style={{ flex: 1 }}>
            <Tag color={cfg.color}>{cfg.label}</Tag>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 8 }}>
              {role === "admin" && "全部操作权限，包括用户管理、系统配置"}
              {role === "employer" && "发布项目、雇用 Agent、充值付款、验收交付"}
              {role === "operator" && "创建/上架 Agent、查看收益结算"}
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: "#8c8c8c" }}>
              {users.filter((u) => u.roles.includes(role)).length} 名用户
            </div>
          </GlowCard>
        ))}
      </div>

      <GlowCard color="blue">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={users}
          loading={loading}
          pagination={{ pageSize: 20 }}
        />
      </GlowCard>

      <Modal
        title={`编辑角色 — ${editUser?.display_name}`}
        open={!!editUser}
        onCancel={() => setEditUser(null)}
        onOk={handleSaveRoles}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
      >
        <div style={{ marginBottom: 12, color: "#8c8c8c", fontSize: 13 }}>
          选择该用户拥有的角色（可多选）：
        </div>
        <Checkbox.Group
          value={selectedRoles}
          onChange={(vals) => setSelectedRoles(vals as string[])}
          style={{ display: "flex", flexDirection: "column", gap: 12 }}
        >
          {ALL_ROLES.map((r) => (
            <Checkbox key={r} value={r}>
              <Tag color={ROLE_CONFIG[r].color}>{ROLE_CONFIG[r].label}</Tag>
              <span style={{ fontSize: 12, color: "var(--text-2)", marginLeft: 4 }}>
                {r === "admin" && "— 全部操作权限"}
                {r === "employer" && "— 发布项目、雇用 Agent、付款"}
                {r === "operator" && "— 管理 Agent、查看收益"}
              </span>
            </Checkbox>
          ))}
        </Checkbox.Group>
      </Modal>
    </div>
  );
}
