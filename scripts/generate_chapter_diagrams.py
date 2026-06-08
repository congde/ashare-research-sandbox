from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/v2/assets"
ASSETS.mkdir(parents=True, exist_ok=True)

W, H, SCALE = 1600, 900, 2
COLORS = ["#2563eb", "#0891b2", "#0d9488", "#f59e0b", "#f97316", "#7c3aed"]
FILLS = ["#dbeafe", "#cffafe", "#ccfbf1", "#fef3c7", "#ffedd5", "#ede9fe"]

DIAGRAMS = [
    (2, "验收证据矩阵", "把“感觉不错”变成机器检查、人工复查和人工放行",
     [("机器检查", "结构、字段、文件、命令"), ("人工复查", "来源、推理、风险"), ("人工放行", "迁移、采购、发布"), ("拒绝条件", "缺证据、越界、未知被隐藏")]),
    (3, "入口选择与工作区说明", "入口提供能力，工作区说明约束能力",
     [("任务依赖", "本地文件、网页、命令"), ("交互方式", "高频确认或后台推进"), ("权限风险", "登录、敏感资料、审批"), ("稳定说明", "材料、产物、检查、禁止事项")]),
    (4, "调研证据链", "每条建议都应该能向前追溯",
     [("事实", "来源直接支持"), ("推断", "事实结合用户约束"), ("建议", "明确下一步动作"), ("未知", "当前不能确认")]),
    (5, "可发版四重审查", "流畅只是起点，责任边界才决定是否可发",
     [("事实审查", "不新增无依据内容"), ("受众审查", "对方需要什么决策信息"), ("承诺审查", "建议不能写成决定"), ("风险审查", "未知和依赖不能被隐藏")]),
    (6, "可执行计划结构", "计划管理不确定性，而不是制造待办",
     [("目标行为", "试点要验证什么"), ("里程碑", "何时进入下一阶段"), ("依赖与风险", "什么会阻塞或失败"), ("停止与交接", "何时回滚、如何继续")]),
    (7, "外部工具上下文分层", "工具可用，不等于信息应该读取",
     [("必需读取", "没有它无法完成"), ("按需读取", "特定问题出现时访问"), ("禁止读取", "敏感或与任务无关"), ("失败降级", "报告未知，不凭记忆补齐")]),
    (8, "浏览器证据链", "证明用户路径，而不是只展示最终截图",
     [("起始状态", "地址、账号、初始页面"), ("操作步骤", "实际点击和输入"), ("状态变化", "关键文本和页面反馈"), ("结果与异常", "预期、实际、失败位置")]),
    (9, "技能沉淀判断", "重复、稳定、可解释、可验收，才值得做成技能",
     [("适用场景", "什么时候触发"), ("输入边界", "需要哪些材料"), ("执行步骤", "按什么顺序完成"), ("输出与验收", "产物结构和检查方式")]),
    (10, "自动化安全边界", "先设计停止条件，再设计触发器",
     [("触发条件", "何时运行"), ("低风险动作", "收集、整理、生成草稿"), ("人工审批", "发布、合并、修改重要资料"), ("失败降级", "输入不足或权限失败就停止")]),
    (11, "数据处理可复查链路", "保护原始输入，让计算路径能够复算",
     [("保护原始数据", "只读、备份、输出分离"), ("说明计算口径", "空值、重复、日期范围"), ("运行与记录", "命令、脚本、结果摘要"), ("样本复算", "抽查结果并报告异常")]),
    (12, "工程护栏四层结构", "把“不要乱改”变成能改变行为的边界",
     [("项目说明", "结构、职责、禁止事项"), ("权限与沙箱", "读写范围和审批"), ("流程检查", "修改前后必须执行什么"), ("人工放行", "删除、联网、生产变更")]),
    (13, "代码库勘察地图", "地图要回答：改这里会影响哪里",
     [("入口与职责", "项目从哪里启动"), ("调用与数据流", "行为如何穿过系统"), ("测试覆盖", "哪些检查证明行为"), ("风险与未知", "隐式契约和未确认项")]),
    (14, "热修复闭环", "先证明问题存在，再证明修复有效",
     [("复现失败", "看到目标问题变红"), ("定位根因", "确认影响范围"), ("最小修改", "不夹带无关重构"), ("验收与审查", "由红变绿、检查差异")]),
    (15, "长任务检查点", "每个阶段都能独立审查、验收和回滚",
     [("用户行为竖切", "本阶段交付什么行为"), ("范围边界", "修改哪些文件和模块"), ("阶段验收", "如何判断可以继续"), ("回滚与下一步", "失败退回哪里")]),
    (16, "PR 与代码审查闭环", "降低审查成本，并把拒绝变成改进输入",
     [("PR 说明", "背景、范围、证据、风险"), ("审查意见", "可定位、可验证、可处理"), ("处理决定", "修改、解释、拆分或拒绝"), ("拒绝复盘", "改 Brief、验收或设计")]),
    (17, "并行与 CI 恢复", "并行前划分所有权，失败后先分类",
     [("任务隔离", "分支、工作树、文件边界"), ("所有权", "谁负责什么结果"), ("失败分类", "环境、偶发、测试、回归"), ("交接说明", "已做、未做、风险、下一步")]),
    (18, "评测改进循环", "从一次成功走向可重复改进",
     [("执行轨迹", "输入、工具、决策、输出"), ("评分标准", "什么叫好、一般、不合格"), ("评测样本", "正常、失败、边界"), ("改进工作流", "修改 Brief、工具或验收")]),
    (19, "毕业交付包", "混合任务要分阶段留证据，最后完整交接",
     [("Brief", "目标、背景、边界、验收"), ("阶段产物", "调研、实现、文档"), ("验收证据", "来源、命令、截图、复算"), ("风险与交接", "未知、放行、下一步")]),
    (20, "工作手册推广路径", "个人经验先试点和评测，再成为团队规则",
     [("个人实践", "记录成功与失败"), ("提炼决策卡", "入口、Brief、验收、停止"), ("小范围试点", "用样本评测风险"), ("团队推广", "负责人、版本、更新机制")]),
]


def s(value):
    return int(round(value * SCALE))


def rect(*values):
    return tuple(s(value) for value in values)


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc"
        if bold
        else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, s(size), index=0)
        except OSError:
            continue
    return ImageFont.load_default()


FONTS = {
    "title": font(52, True),
    "subtitle": font(24),
    "card_title": font(28, True),
    "card_text": font(20),
    "number": font(34, True),
    "footer": font(20, True),
}


def add_shadow(image, draw, bounds, fill):
    x1, y1, x2, y2 = bounds
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        rect(x1, y1 + 10, x2, y2 + 10),
        radius=s(26),
        fill=(15, 23, 42, 30),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(s(12)))
    image = Image.alpha_composite(image.convert("RGBA"), shadow).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(rect(*bounds), radius=s(26), fill=fill)
    return image, draw


def draw_diagram(chapter, title, subtitle, cards):
    image = Image.new("RGB", (W * SCALE, H * SCALE), "#f8fbff")
    draw = ImageDraw.Draw(image)
    for y in range(H * SCALE):
        ratio = y / (H * SCALE - 1)
        color = (
            int(248 * (1 - ratio) + 255 * ratio),
            int(251 * (1 - ratio) + 248 * ratio),
            int(255 * (1 - ratio) + 237 * ratio),
        )
        draw.line([(0, y), (W * SCALE, y)], fill=color)

    draw.ellipse(rect(1160, -80, 1490, 250), fill="#fef3c7")
    draw.ellipse(rect(-100, 650, 250, 1000), fill="#e0f2fe")
    draw.text((s(90), s(70)), f"第 {chapter} 讲：{title}", font=FONTS["title"], fill="#0f172a")
    draw.text((s(92), s(136)), subtitle, font=FONTS["subtitle"], fill="#475569")
    draw.rectangle(rect(90, 172, 1510, 180), fill="#2563eb")

    positions = [(100, 270), (475, 270), (850, 270), (1225, 270)]
    for index, ((card_title, card_text), (x, y)) in enumerate(zip(cards, positions)):
        image, draw = add_shadow(image, draw, (x, y, x + 285, y + 330), FILLS[index])
        draw.rounded_rectangle(
            rect(x + 28, y + 28, x + 98, y + 98),
            radius=s(20),
            fill=COLORS[index],
        )
        draw.text(
            (s(x + 51), s(y + 43)),
            str(index + 1),
            font=FONTS["number"],
            fill="#ffffff",
        )
        draw.text(
            (s(x + 32), s(y + 130)),
            card_title,
            font=FONTS["card_title"],
            fill="#0f172a",
        )
        lines = card_text.split("、")
        for line_index, line in enumerate(lines):
            draw.text(
                (s(x + 32), s(y + 188 + line_index * 38)),
                line,
                font=FONTS["card_text"],
                fill="#334155",
            )
        if index < len(cards) - 1:
            x1, x2, arrow_y = x + 295, positions[index + 1][0] - 10, y + 165
            draw.line(
                [(s(x1), s(arrow_y)), (s(x2), s(arrow_y))],
                fill="#64748b",
                width=s(5),
            )
            draw.line(
                [
                    (s(x2 - 20), s(arrow_y - 16)),
                    (s(x2), s(arrow_y)),
                    (s(x2 - 20), s(arrow_y + 16)),
                ],
                fill="#64748b",
                width=s(5),
                joint="curve",
            )

    draw.text(
        (s(100), s(730)),
        f"本讲核心：{subtitle}",
        font=FONTS["footer"],
        fill="#475569",
    )
    output = ASSETS / f"chapter-{chapter:02d}-diagram.png"
    image.resize((W, H), Image.Resampling.LANCZOS).save(output)


def add_drawio_page(mxfile, chapter, title, subtitle, cards):
    diagram = ET.SubElement(mxfile, "diagram", {"name": f"{chapter:02d} {title}"})
    model = ET.SubElement(
        diagram,
        "mxGraphModel",
        {
            "dx": "1600",
            "dy": "900",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1600",
            "pageHeight": "900",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    def vertex(cell_id, value, style, x, y, width, height):
        cell = ET.SubElement(
            root,
            "mxCell",
            {
                "id": cell_id,
                "value": value,
                "style": style,
                "vertex": "1",
                "parent": "1",
            },
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {
                "x": str(x),
                "y": str(y),
                "width": str(width),
                "height": str(height),
                "as": "geometry",
            },
        )

    vertex(
        "title",
        f"第 {chapter} 讲：{title}<br><font style='font-size:20px'>{subtitle}</font>",
        "text;html=1;strokeColor=none;fillColor=none;fontSize=40;fontStyle=1;fontColor=#0f172a;",
        80,
        60,
        1200,
        100,
    )
    for index, (card_title, card_text) in enumerate(cards):
        x = 100 + index * 375
        vertex(
            f"card-{index}",
            f"{index + 1}. {card_title}<br><br>{card_text}",
            f"rounded=1;whiteSpace=wrap;html=1;arcSize=14;strokeColor={COLORS[index]};fillColor={FILLS[index]};fontColor=#0f172a;fontSize=22;fontStyle=1;spacing=16;",
            x,
            280,
            285,
            300,
        )
        if index:
            edge = ET.SubElement(
                root,
                "mxCell",
                {
                    "id": f"edge-{index}",
                    "style": "endArrow=block;html=1;rounded=0;strokeWidth=3;strokeColor=#64748b;",
                    "edge": "1",
                    "parent": "1",
                    "source": f"card-{index - 1}",
                    "target": f"card-{index}",
                },
            )
            ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})


def main():
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-06-08T00:00:00.000Z",
            "agent": "Codex",
            "version": "24.7.17",
            "type": "device",
        },
    )
    for diagram in DIAGRAMS:
        draw_diagram(*diagram)
        add_drawio_page(mxfile, *diagram)
    ET.indent(mxfile, space="  ")
    ET.ElementTree(mxfile).write(
        ASSETS / "chapters-02-20-diagrams.drawio",
        encoding="utf-8",
        xml_declaration=True,
    )


if __name__ == "__main__":
    main()
