import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Form, Input, Button, App, Typography } from "antd";
import { UserOutlined, LockOutlined } from "@ant-design/icons";
import api from "../api/client";
import { useCurrentUser } from "../contexts/UserContext";
import { authStorage } from "../utils/auth-storage";

const { Text } = Typography;

interface LoginForm {
  username: string;
  password: string;
}

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { message: msg } = App.useApp();
  const { reload } = useCurrentUser();

  const handleLogin = async (values: LoginForm) => {
    setLoading(true);
    try {
      const res = await api.post<{ access_token: string; refresh_token: string }>(
        "/auth/login",
        { username: values.username, password: values.password }
      );
      authStorage.setToken(res.data.access_token);
      authStorage.setRefresh(res.data.refresh_token);
      // Parse roles from JWT to set correct default role
      try {
        const payload = JSON.parse(atob(res.data.access_token.split(".")[1]));
        const roles: string[] = payload.roles ?? [];
        const activeRole = payload.active_role || (roles.includes("employer") ? "employer" : roles.includes("operator") ? "operator" : "employer");
        authStorage.setRole(activeRole);
      } catch {
        // role will be resolved by UserContext on fetchUser
      }
      reload();
      navigate("/", { replace: true });
    } catch {
      msg.error("用户名或密码错误");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--bg-base)",
      position: "relative",
      overflow: "hidden",
      padding: "24px 16px",
    }}>
      {/* Animated orbs */}
      <div className="orb orb-1" style={{ top: "-10%", left: "-5%" }} />
      <div className="orb orb-2" style={{ bottom: "5%", right: "10%" }} />
      <div className="orb orb-3" style={{ top: "50%", right: "-8%" }} />

      <div className="glass-card" style={{
        width: 420,
        borderRadius: "var(--radius-lg)",
        border: "1px solid rgba(34,211,238,0.25)",
        padding: "40px 36px",
        position: "relative",
        zIndex: 1,
      }}>
        {/* Logo / Title */}
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div className="gradient-text" style={{ fontSize: 26, fontWeight: 800, letterSpacing: 0, marginBottom: 6 }}>
            AI Trading
          </div>
          <Text style={{ fontSize: 13, color: "var(--text-2)" }}>AI 量化交易工作台</Text>
        </div>

        <Form layout="vertical" onFinish={handleLogin} autoComplete="off">
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined style={{ color: "var(--text-2)" }} />} placeholder="用户名" size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password prefix={<LockOutlined style={{ color: "var(--text-2)" }} />} placeholder="密码" size="large" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={loading}
              className="btn-gradient"
            >
              登录
            </Button>
          </Form.Item>
          <div style={{ textAlign: "center", marginTop: 14 }}>
            <Text style={{ fontSize: 13, color: "var(--text-2)" }}>
              没有账号？<Link to="/register" style={{ color: "var(--primary-light)" }}>免费注册</Link>
            </Text>
          </div>
        </Form>

      </div>
    </div>
  );
}
