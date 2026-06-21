"""Generate focused Chinese teaching figures for chapters 26 through 32."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "v2" / "assets" / "generated"
FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


TITLE = font(42)
HEAD = font(29)
BODY = font(24)
SMALL = font(20)

BG = "#F7F9FC"
INK = "#111827"
MUTED = "#64748B"
BLUE = "#2563EB"
TEAL = "#0F9B8E"
ORANGE = "#F59E0B"
RED = "#DC2626"
GREEN = "#15803D"
PANEL = "#FFFFFF"


def rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    body: str,
    color: str,
    fill: str = PANEL,
) -> None:
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=color, width=4)
    x1, y1, _, _ = box
    draw.text((x1 + 24, y1 + 20), title, font=HEAD, fill=color)
    draw.multiline_text((x1 + 24, y1 + 72), body, font=BODY, fill=INK, spacing=8)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = MUTED) -> None:
    draw.line([start, end], fill=color, width=5)
    ex, ey = end
    sx, sy = start
    if abs(ex - sx) >= abs(ey - sy):
        sign = 1 if ex >= sx else -1
        pts = [(ex, ey), (ex - sign * 18, ey - 11), (ex - sign * 18, ey + 11)]
    else:
        sign = 1 if ey >= sy else -1
        pts = [(ex, ey), (ex - 11, ey - sign * 18), (ex + 11, ey - sign * 18)]
    draw.polygon(pts, fill=color)


def save_flow(name: str, title: str, subtitle: str, steps: list[tuple[str, str]], note: str) -> None:
    img = Image.new("RGB", (1600, 920), BG)
    draw = ImageDraw.Draw(img)
    draw.text((70, 48), title, font=TITLE, fill=INK)
    draw.text((70, 108), subtitle, font=BODY, fill=MUTED)
    boxes = [
        (70, 260, 330, 430),
        (425, 260, 685, 430),
        (780, 260, 1040, 430),
        (1135, 205, 1510, 370),
        (1135, 485, 1510, 650),
    ]
    colors = [BLUE, TEAL, ORANGE, GREEN, RED]
    fills = [PANEL, PANEL, PANEL, "#ECFDF5", "#FEF2F2"]
    for box, color, fill, (head, body) in zip(boxes, colors, fills, steps):
        rounded_box(draw, box, head, body, color, fill)
    arrow(draw, (330, 345), (425, 345))
    arrow(draw, (685, 345), (780, 345))
    arrow(draw, (1040, 320), (1135, 285), GREEN)
    arrow(draw, (1040, 380), (1135, 565), RED)
    draw.rounded_rectangle((190, 715, 1410, 845), radius=18, fill="#FFFFFF", outline=BLUE, width=4)
    draw.text((235, 740), "读图要点", font=HEAD, fill=BLUE)
    draw.text((235, 795), note, font=BODY, fill=INK)
    img.save(OUT / name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    figures = [
        (
            "chapter-26-backtest-risk-center.png",
            "第 26 讲：回测与风险中心联动",
            "回测结果必须能追到成本假设、审计指标和风险拒绝记录。",
            [
                ("回测请求", "策略、参数\n成本预设"),
                ("审计结果", "DSR、PBO\nCPCV 路径"),
                ("风险记录", "rule_id\nreason"),
                ("继续比较", "指标一致\n风险可追"),
                ("停止修正", "口径不一致\n拒绝缺失"),
            ],
            "风险中心不是独立页面；它必须能解释回测结果里的每一次拒绝和风险状态。",
        ),
        (
            "chapter-27-browser-research-path.png",
            "第 27 讲：浏览器验证研究路径",
            "验证不是看单页截图，而是走完一条可复查的用户路径。",
            [
                ("打开入口", "行情总览\n候选列表"),
                ("执行路径", "K 线信号\n回测风险"),
                ("截图与 trace", "正常状态\n异常出口"),
                ("验收通过", "可见、可追\n可复查"),
                ("退回修复", "状态缺失\n路径断裂"),
            ],
            "浏览器验收要同时留下路径、字段、截图和失败说明，不能只说“页面看起来正常”。",
        ),
        (
            "chapter-28-skill-evidence-contract.png",
            "第 28 讲：Skill 证据合同",
            "Skill 复用的是检查流程，不是自动替人发布结论。",
            [
                ("输入材料", "报告、命令\n样本口径"),
                ("检查清单", "来源、假设\n失败记录"),
                ("输出建议", "通过\n修改\n拒绝"),
                ("人工发布", "复核后采用"),
                ("禁止越权", "自动实盘执行\n跳过复核"),
            ],
            "可复用流程要写清输入、输出和禁止事项；Skill 的结论仍要交给人工发布责任。",
        ),
        (
            "chapter-29-snapshot-draft-path.png",
            "第 29 讲：快照到研究草稿",
            "自动草稿只能使用已经冻结、可追溯、可说明新鲜度的市场快照。",
            [
                ("生成快照", "来源、时间\n数据状态"),
                ("冻结输入", "snapshot_id\n文件路径"),
                ("生成草稿", "只引用快照\n保留缺失"),
                ("继续编辑", "证据完整"),
                ("停止草稿", "快照过旧\n来源缺失"),
            ],
            "自动化先保存证据，再写草稿；不能把草稿写成实时市场判断。",
        ),
        (
            "chapter-30-approval-stop-gate.png",
            "第 30 讲：审批门与停止线",
            "高风险动作必须先分类、再审批，触发停止线时不能继续。",
            [
                ("动作分类", "数据写入\n风险修改"),
                ("审批检查", "权限、范围\n回滚路径"),
                ("停止条件", "真实交易\n破坏证据"),
                ("允许执行", "审批可追\n范围受限"),
                ("立即停止", "越权\n不可回滚"),
            ],
            "审批门不是礼貌确认，而是防止高风险动作越过研究边界的硬约束。",
        ),
        (
            "chapter-31-eval-version-decision.png",
            "第 31 讲：Eval 版本决策",
            "比较提示词、模型或策略版本前，必须先冻结评测样本和关键失败规则。",
            [
                ("固定 Eval", "样本、权重\n失败项"),
                ("运行候选", "版本 A/B\n同口径"),
                ("比较证据", "平均分\n关键失败"),
                ("提升版本", "证据更强"),
                ("拒绝复测", "关键失败\n分数不足"),
            ],
            "平均分只能说明总体表现；关键失败出现时，版本不能靠均值晋级。",
        ),
        (
            "chapter-32-failure-audit-loop.png",
            "第 32 讲：失败降级与审计闭环",
            "失败、降级和恢复都要留痕；恢复不能覆盖失败现场。",
            [
                ("发现失败", "数据、模型\n代码、环境"),
                ("降级运行", "fallback\n快照兜底"),
                ("恢复验证", "重试\n对账"),
                ("关闭事件", "记录完整"),
                ("继续阻断", "原因不明\n证据缺失"),
            ],
            "监控的价值不是报错，而是让失败原因、降级动作和恢复证据都能被复查。",
        ),
    ]
    for item in figures:
        save_flow(*item)
        print(OUT / item[0])


if __name__ == "__main__":
    main()
