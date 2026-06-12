import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Form, Input, Button, App, Typography, Steps, Divider } from "antd";
import {
  UserOutlined, LockOutlined, MailOutlined,
  PhoneOutlined, KeyOutlined, TeamOutlined, SafetyOutlined,
} from "@ant-design/icons";
import api from "../api/client";
import { useCurrentUser } from "../contexts/UserContext";
import { authStorage } from "../utils/auth-storage";

const { Text } = Typography;

export default function RegisterPage() {
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [activeRole, setActiveRole] = useState<string>("employer");
  const navigate = useNavigate();
  const { message: msg } = App.useApp();
  const { reload } = useCurrentUser();
  const [form] = Form.useForm();

  const handleNext = async () => {
    try {
      if (step === 0) {
        await form.validateFields(["invite_code"]);
      } else if (step === 1) {
        // activeRole always has a value, no validation needed
      } else if (step === 2) {
        await form.validateFields(["username", "phone", "email", "password", "confirm_password"]);
      }
      setStep((s) => s + 1);
    } catch {
      // validation errors shown inline
    }
  };

  const handleRegister = async () => {
    if (step !== 2) return;
    try {
      await form.validateFields(["username", "phone", "email", "password", "confirm_password"]);
    } catch { return; }

    const values = form.getFieldsValue(true);
    setLoading(true);
    try {
      const res = await api.post<{ access_token: string; refresh_token: string }>(
        "/auth/register",
        {
          username: values.username,
          email: values.email,
          password: values.password,
          display_name: values.username,
          roles: [activeRole],
          invite_code: values.invite_code ?? "",
        }
      );
      authStorage.setToken(res.data.access_token);
      authStorage.setRefresh(res.data.refresh_token);
      authStorage.setRole(activeRole);
      reload();
      msg.success("注册成功，欢迎加入！");
      navigate("/dashboard", { replace: true });
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      msg.error(detail || "注册失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  const steps = [
    { title: "邀请码" },
    { title: "选择角色" },
    { title: "账户信息" },
  ];

  const roleStyle = (role: string) => ({
    padding: "24px",
    borderRadius: 16,
    border: `2px solid ${activeRole === role ? "#22d3ee" : "rgba(255,255,255,0.10)"}`,
    background: activeRole === role ? "rgba(34,211,238,0.08)" : "rgba(255,255,255,0.03)",
    cursor: "pointer",
    transition: "all 0.2s",
    flex: 1,
  });

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "#000",
      backgroundImage:
        "radial-gradient(circle at 20% 20%, rgba(22,163,184,0.15) 0%, transparent 35%)," +
        "radial-gradient(circle at 80% 80%, rgba(34,211,238,0.10) 0%, transparent 35%)",
      padding: "24px 16px",
    }}>
      <div style={{
        width: 520,
        borderRadius: 20,
        border: "1px solid rgba(255,255,255,0.12)",
        background: "rgba(255,255,255,0.05)",
        backdropFilter: "blur(20px)",
        padding: "40px 36px",
      }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{
            fontSize: 26, fontWeight: 700, color: "#22d3ee",
            letterSpacing: 0, marginBottom: 6,
          }}>
            注册 AI Trading
          </div>
          <Text style={{ fontSize: 13, color: "rgba(255,255,255,0.5)" }}>
            构建你的 AI 量化交易工作台
          </Text>
        </div>

        <Steps
          current={step}
          items={steps}
          size="small"
          style={{ marginBottom: 32 }}
        />

        <Form form={form} layout="vertical" requiredMark={false}>

          {/* Step 0: 邀请码 */}
          {step === 0 && (
            <Form.Item
              name="invite_code"
              label={<span style={{ color: "#e2e8f0" }}>邀请码</span>}
              rules={[
                // Presence only — validity is checked server-side at
                // /auth/register (the old hard-coded WORKDAO2026 check
                // was browser-only and trivially bypassable).
                { required: true, message: "请输入邀请码" },
              ]}
              extra={<a href="/home#invite" style={{ color: "#22d3ee", fontSize: 12 }}>点击获取邀请码</a>}
            >
              <Input
                prefix={<KeyOutlined style={{ color: "#22d3ee" }} />}
                placeholder="请输入邀请码"
                size="large"
                style={{ borderRadius: 12 }}
              />
            </Form.Item>
          )}

          {/* Step 1: 选择角色 */}
          {step === 1 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div style={roleStyle("employer")} onClick={() => setActiveRole("employer")}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 12,
                    background: "rgba(34,211,238,0.1)", border: "1px solid rgba(34,211,238,0.2)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <TeamOutlined style={{ color: "#22d3ee", fontSize: 18 }} />
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: "#e2e8f0" }}>雇主</div>
                  {activeRole === "employer" && <SafetyOutlined style={{ color: "#22d3ee", marginLeft: "auto" }} />}
                </div>
                <div style={{ fontSize: 14, color: "rgba(255,255,255,0.55)", lineHeight: 1.7 }}>
                  我有需求，我要招聘 Agent 数字员工。
                </div>
              </div>

              <div style={roleStyle("operator")} onClick={() => setActiveRole("operator")}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 12,
                    background: "rgba(0,208,132,0.1)", border: "1px solid rgba(0,208,132,0.2)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <UserOutlined style={{ color: "#00d084", fontSize: 18 }} />
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: "#e2e8f0" }}>雇员</div>
                  {activeRole === "operator" && <SafetyOutlined style={{ color: "#00d084", marginLeft: "auto" }} />}
                </div>
                <div style={{ fontSize: 14, color: "rgba(255,255,255,0.55)", lineHeight: 1.7 }}>
                  我有技能，我要创建 Agent 数字分身为我赚钱。
                </div>
              </div>
              <div style={{ padding: "10px 14px", background: "rgba(34,211,238,0.06)", borderRadius: 10, border: "1px solid rgba(34,211,238,0.15)", fontSize: 13, color: "rgba(34,211,238,0.7)", marginTop: 4 }}>
                注册后自动拥有雇主和雇员双重身份，此处选择登录后的默认视角。可随时通过右上角头像切换角色。
              </div>
            </div>
          )}

          {/* Step 2: 账户信息 */}
          {step === 2 && (
            <>
              <Form.Item
                name="username"
                label={<span style={{ color: "#e2e8f0" }}>用户名</span>}
                rules={[
                  { required: true, message: "请输入用户名" },
                  { max: 20, message: "不超过 20 个字符" },
                  { pattern: /^[a-zA-Z0-9_\u4e00-\u9fa5]{2,20}$/, message: "支持中英文、数字、下划线，2~20 位" },
                ]}
              >
                <Input prefix={<UserOutlined style={{ color: "#22d3ee" }} />} placeholder="不超过20个字符" size="large" style={{ borderRadius: 12 }} />
              </Form.Item>

              <Form.Item
                name="phone"
                label={<span style={{ color: "#e2e8f0" }}>手机号</span>}
                rules={[
                  { required: true, message: "请输入手机号" },
                  { pattern: /^1[3-9]\d{9}$/, message: "请输入正确的手机号" },
                ]}
              >
                <Input prefix={<PhoneOutlined style={{ color: "#22d3ee" }} />} placeholder="11位手机号" size="large" style={{ borderRadius: 12 }} />
              </Form.Item>

              <Form.Item
                name="email"
                label={<span style={{ color: "#e2e8f0" }}>邮箱</span>}
                rules={[
                  { required: true, message: "请输入邮箱" },
                  { type: "email", message: "邮箱格式不正确" },
                ]}
              >
                <Input prefix={<MailOutlined style={{ color: "#22d3ee" }} />} placeholder="your@email.com" size="large" style={{ borderRadius: 12 }} />
              </Form.Item>

              <Form.Item
                name="password"
                label={<span style={{ color: "#e2e8f0" }}>密码</span>}
                rules={[
                  { required: true, message: "请设置密码" },
                  { min: 8, message: "至少 8 个字符" },
                  {
                    pattern: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z0-9]).{8,}$/,
                    message: "需包含大小写字母、数字和特殊字符",
                  },
                ]}
              >
                <Input.Password prefix={<LockOutlined style={{ color: "#22d3ee" }} />} placeholder="8位以上，含大小写+数字+特殊字符" size="large" style={{ borderRadius: 12 }} />
              </Form.Item>

              <Form.Item
                name="confirm_password"
                label={<span style={{ color: "#e2e8f0" }}>确认密码</span>}
                dependencies={["password"]}
                rules={[
                  { required: true, message: "请再次输入密码" },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue("password") === value) return Promise.resolve();
                      return Promise.reject(new Error("两次密码不一致"));
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined style={{ color: "#22d3ee" }} />} placeholder="再次输入密码" size="large" style={{ borderRadius: 12 }} />
              </Form.Item>
            </>
          )}
        </Form>

        <Divider style={{ margin: "20px 0", borderColor: "rgba(255,255,255,0.08)" }} />

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            {step > 0 && (
              <Button
                onClick={() => setStep((s) => s - 1)}
                style={{ borderRadius: 10, borderColor: "rgba(255,255,255,0.15)" }}
              >
                上一步
              </Button>
            )}
          </div>
          <div>
            {step < 2 ? (
              <Button
                type="primary"
                size="large"
                onClick={handleNext}
                style={{
                  borderRadius: 10,
                  background: "#fff", color: "#000",
                  fontWeight: 600, border: "none",
                  padding: "0 32px", height: 44,
                }}
              >
                下一步
              </Button>
            ) : (
              <Button
                type="primary"
                size="large"
                loading={loading}
                onClick={handleRegister}
                style={{
                  borderRadius: 10,
                  background: "#fff", color: "#000",
                  fontWeight: 600, border: "none",
                  padding: "0 32px", height: 44,
                }}
              >
                完成注册
              </Button>
            )}
          </div>
        </div>

        <div style={{ textAlign: "center", marginTop: 16 }}>
          <Text style={{ fontSize: 13, color: "rgba(255,255,255,0.45)" }}>
            已有账号？<Link to="/login" style={{ color: "#22d3ee" }}>立即登录</Link>
          </Text>
        </div>
      </div>
    </div>
  );
}
