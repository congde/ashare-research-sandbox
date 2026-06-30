"""Generate and insert one Lark-compatible PNG teaching diagram per chapter."""

from __future__ import annotations

from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

from rewrite_quant_course import CHAPTERS


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "v2"
ASSETS = DOCS / "assets" / "generated"
MARKER = "<!-- chapter-visual-and-code -->"


FONT_REGULAR = Path("C:/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("C:/Windows/Fonts/msyhbd.ttc")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    if path.exists():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def fit_text(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def centered_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    text_font: ImageFont.ImageFont,
    fill: str,
) -> None:
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=text_font)
    draw.text((x - (bbox[2] - bbox[0]) / 2, y), text, font=text_font, fill=fill)


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: str = "#334155",
    width: int = 4,
) -> None:
    draw.line([start, end], fill=fill, width=width)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 >= x1 else -1
        points = [(x2, y2), (x2 - 16 * direction, y2 - 8), (x2 - 16 * direction, y2 + 8)]
    else:
        direction = 1 if y2 >= y1 else -1
        points = [(x2, y2), (x2 - 8, y2 - 16 * direction), (x2 + 8, y2 - 16 * direction)]
    draw.polygon(points, fill=fill)


def draw_png(chapter: dict[str, object], path: Path) -> None:
    n = int(chapter["num"])
    title = str(chapter["title"])
    artifact = str(chapter["artifact"])
    method = str(chapter["method"])
    failure = str(chapter["failure"])

    image = Image.new("RGB", (1200, 560), "#f7f9fc")
    draw = ImageDraw.Draw(image)
    draw.text((60, 50), f"第 {n} 章：{fit_text(title, 34)}", font=font(30, True), fill="#14213d")
    draw.text((60, 100), "从输入证据到可复核交付物的教学路径", font=font(18), fill="#4b5563")

    boxes = [
        ((60, 165, 300, 295), "#dbeafe", "#2563eb", "输入与假设", "冻结来源、时间与版本", "#1e3a8a"),
        ((360, 165, 660, 295), "#dcfce7", "#16a34a", "方法与实现", fit_text(method, 20), "#14532d"),
        ((720, 165, 960, 295), "#fef3c7", "#d97706", "验证与失败注入", fit_text(failure, 16), "#78350f"),
        ((750, 370, 1110, 490), "#ede9fe", "#7c3aed", "交付物", fit_text(artifact, 22), "#4c1d95"),
        ((90, 370, 590, 490), "#fee2e2", "#dc2626", "停止线", "证据不足、未来信息、越权动作或关键失败", "#7f1d1d"),
    ]
    for rect, fill, outline, heading, subheading, text_fill in boxes:
        draw.rounded_rectangle(rect, radius=16, fill=fill, outline=outline, width=3)
        cx = (rect[0] + rect[2]) // 2
        centered_text(draw, (cx, rect[1] + 42), heading, font(23, True), text_fill)
        centered_text(draw, (cx, rect[1] + 84), subheading, font(16), "#1f2937")

    draw_arrow(draw, (300, 230), (360, 230))
    draw_arrow(draw, (660, 230), (720, 230))
    draw.line([(840, 295), (840, 340), (930, 340), (930, 370)], fill="#334155", width=4)
    draw.polygon([(930, 370), (922, 354), (938, 354)], fill="#334155")
    draw.line([(720, 260), (650, 320), (570, 350), (500, 370)], fill="#dc2626", width=4)
    draw.polygon([(500, 370), (518, 368), (506, 354)], fill="#dc2626")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def code_example(chapter: dict[str, object]) -> str:
    n = int(chapter["num"])
    part = int(chapter["part"])
    failure = str(chapter["failure"])
    artifact = str(chapter["artifact"])
    if part == 1:
        return f'''from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchHypothesis:
    trigger: str
    benchmark: str
    metric: str
    reject_when: str


hypothesis = ResearchHypothesis(
    trigger="short_ma crosses above long_ma",
    benchmark="buy_and_hold",
    metric="risk_adjusted_return",
    reject_when="candidate does not beat benchmark",
)
assert hypothesis.reject_when
'''
    if part == 2:
        return f'''def validate_market_row(row: dict) -> list[str]:
    errors = []
    if not row.get("source") or not row.get("observed_at"):
        errors.append("missing provenance")
    if row.get("close", 0) <= 0:
        errors.append("invalid close")
    return errors


sample = {{"source": "fixture-v1", "observed_at": "2026-06-14", "close": 63620.6}}
assert validate_market_row(sample) == []
'''
    if part == 3:
        return f'''ALLOWED_SIGNALS = {{"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}}


def gate_llm_signal(result: dict) -> str:
    if result.get("signal") not in ALLOWED_SIGNALS:
        return "REJECT"
    if not result.get("evidence") or result.get("uses_future_data"):
        return "STOP"
    return "RESEARCH_ONLY"


candidate = {{"signal": "HOLD", "evidence": ["technical=-20"], "uses_future_data": False}}
assert gate_llm_signal(candidate) == "RESEARCH_ONLY"
'''
    if part == 4:
        return f'''def strategy_return(position: float, next_return: float, turnover: float, fee: float) -> float:
    """信号先变成仓位，再扣除换手成本。"""
    return position * next_return - turnover * fee


gross_signal = 1.0
net_return = strategy_return(gross_signal, next_return=0.012, turnover=1.0, fee=0.001)
assert round(net_return, 3) == 0.011
'''
    if part == 5:
        return f'''def signal_view_model(result: dict) -> dict:
    """页面必须同时展示方向、来源和降级状态。"""
    return {{
        "signal": result["signal"],
        "source": result["engineMeta"]["source"],
        "degraded": result["engineMeta"].get("fallback", False),
        "evidence": result.get("evidence", {{}}),
    }}


view = signal_view_model({{"signal": "HOLD", "engineMeta": {{"source": "rule", "fallback": True}}}})
assert view["degraded"] is True
'''
    if part == 6:
        return f'''def eval_decision(scores: list[float], critical_failures: int) -> str:
    """关键失败不能被平均分抵消。"""
    if critical_failures:
        return "REJECT"
    return "PROMOTE" if min(scores) >= 0.8 else "REVIEW"


assert eval_decision([0.95, 0.91, 0.88], critical_failures=0) == "PROMOTE"
assert eval_decision([0.99, 0.99, 0.99], critical_failures=1) == "REJECT"
'''
    return f'''STAGES = ("data", "signal", "strategy", "backtest", "risk", "web")


def advance(completed: set[str], failed: set[str]) -> str:
    if failed:
        return "STOP"
    missing = [stage for stage in STAGES if stage not in completed]
    return missing[0] if missing else "ACCEPT_FOR_RESEARCH"


assert advance({{"data", "signal"}}, set()) == "strategy"
assert advance(set(STAGES), {{"risk"}}) == "STOP"
'''


def code_notes(chapter: dict[str, object]) -> tuple[str, str, str]:
    part = int(chapter["part"])
    notes = {
        1: ("可证伪研究假设示例", "把研究想法写成可证伪对象", "`reject_when` 明确允许研究得到不成立的结论，避免只写成功条件。"),
        2: ("市场数据合同验证示例", "把来源、时间与字段范围写成数据合同", "缺少来源、观察时间或合法价格时，数据必须在进入指标和 LLM 前被拒绝。"),
        3: ("结构化 LLM 信号门示例", "把结构、证据与未来信息检查写成信号门", "合法枚举只是最低要求；缺少证据或使用未来数据时，信号必须停止。"),
        4: ("含交易成本的策略收益示例", "把信号转换为仓位并扣除交易成本", "策略收益取决于仓位、下一期收益、换手和费用，不能由信号方向直接替代。"),
        5: ("带来源与降级状态的页面模型示例", "把来源与降级状态纳入页面展示对象", "页面不能只展示方向；来源、降级状态和证据必须与信号同时可见。"),
        6: ("关键失败优先的 Eval 决策示例", "把关键失败门写进版本评测", "关键失败不能被高平均分抵消；没有关键失败时仍要检查最低样本得分。"),
        7: ("端到端阶段停止与推进示例", "把端到端阶段和停止状态写成可检查流程", "流程只推进到下一个未完成阶段；任一阶段失败都必须先停止，而不是继续包装结果。"),
    }
    return notes[part]


def block(chapter: dict[str, object]) -> str:
    n = int(chapter["num"])
    title = str(chapter["title"])
    code_title, code_purpose, code_reading = code_notes(chapter)
    return f"""
{MARKER}
### 配套图解与代码示例

图 {n}-1 将“{title}”的教学路径画成输入、方法、验证、停止线与交付物五个节点。阅读时先
沿实线检查正常证据链，再沿红色虚线检查关键失败是否会让流程停止，完整路径见图 {n}-1。

![第 {n} 章证据链与停止线路径](assets/generated/chapter-{n:02d}-evidence-flow.png)

**图 {n}-1　第 {n} 章证据链与停止线路径**

图 {n}-1 不是系统运行时序图，也不能证明方法有效；它用于帮助读者定位每一步需要保存的
证据，以及失败应在哪里被阻断。真正结论仍须回到本章实验、代码实现和实际输出。

代码 {n}-1 用最小可运行示例{code_purpose}。它不代替仓库产品
代码，而是让读者能够修改输入版本、方法版本和失败状态，观察发布决定如何变化，见代码 {n}-1。

```python
{code_example(chapter).rstrip()}
```

**代码 {n}-1　{code_title}**

代码 {n}-1 的阅读重点是：{code_reading} 修改示例中的正常值和边界值后，应先预测程序
行为，再运行代码核对；若实际行为与研究合同不一致，应修正规则或实现，而不是改写解释。
"""


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    for chapter in CHAPTERS:
        n = int(chapter["num"])
        asset = ASSETS / f"chapter-{n:02d}-evidence-flow.png"
        draw_png(chapter, asset)

        paths = list(DOCS.glob(f"{n:02d}-*.md"))
        if len(paths) != 1:
            raise RuntimeError(f"expected one chapter {n}, found {paths}")
        path = paths[0]
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            rf"\n{re.escape(MARKER)}\n.*?(?=\n(?:<!-- quant-rigor-section -->|## {n}\.\d+ 量化严谨性检查|## {n}\.\d+ 本章总结)\n)",
            "\n",
            text,
            flags=re.DOTALL,
        )
        insertion = re.search(
            rf"\n(?:<!-- quant-rigor-section -->\n)?## {n}\.\d+ (?:量化严谨性检查|本章总结)\n",
            text,
        )
        if insertion is None:
            raise RuntimeError(f"missing insertion marker in {path}")
        text = text[: insertion.start()] + "\n" + block(chapter) + text[insertion.start() :]
        path.write_text(text, encoding="utf-8")
        print(f"added visual and code example to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
