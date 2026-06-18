"""Add reviewed external research notes to every publishable chapter."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAPTER_DIR = ROOT / "docs" / "v2"
MARKER = "<!-- external-research-sources -->"

SOURCES = {
    "econometrics": ("Campbell、Lo 与 MacKinlay，《The Econometrics of Financial Markets》", "https://press.princeton.edu/books/hardcover/9780691043012/the-econometrics-of-financial-markets", "建立收益、可预测性和实证检验的计量框架；统计显著性不能直接解释为可交易利润。"),
    "afml": ("López de Prado，《Advances in Financial Machine Learning》", "https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086", "讨论金融机器学习中的标签、交叉验证与回测过拟合；书中方法仍需按本书数据重新验证。"),
    "tsay": ("Tsay，《Analysis of Financial Time Series》", "https://www.wiley.com/en-us/Analysis+of+Financial+Time+Series%2C+3rd+Edition-p-9780470414354", "解释收益率、波动率和时间序列诊断；不能假设收益分布始终稳定或服从正态分布。"),
    "fpp": ("Hyndman 与 Athanasopoulos，《Forecasting: Principles and Practice》", "https://otexts.com/fpp3/", "说明时间序列拆分、滚动评估和预测误差；预测准确度不等于策略盈利能力。"),
    "reality": ("White (2000), A Reality Check for Data Snooping", "https://doi.org/10.1111/1468-0262.00152", "说明反复尝试策略会放大偶然优势；单次留出测试也不能完全消除数据窥探。"),
    "pbo": ("Bailey et al., The Probability of Backtest Overfitting", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253", "解释多重试验和选择偏差如何制造漂亮回测；PBO 是诊断工具，不是收益保证。"),
    "dsr": ("Bailey 与 López de Prado, The Deflated Sharpe Ratio", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551", "修正非正态收益和多次试验对夏普比率的夸大；仍需同时报告回撤、换手和成本。"),
    "technical": ("Sullivan、Timmermann 与 White (1999), Data-Snooping and Technical Trading Rules", "https://doi.org/10.1111/0022-1082.00163", "提醒技术规则比较必须控制数据窥探；一个指标在一个窗口有效不代表存在稳定优势。"),
    "event": ("MacKinlay (1997), Event Studies in Economics and Finance", "https://doi.org/10.1257/jel.35.1.13", "区分事件、估计窗口、异常收益和检验窗口；不能把相关性直接写成因果关系。"),
    "phrasebank": ("Malo et al. (2014), Good Debt or Bad Debt", "https://aclanthology.org/L14-1250/", "说明金融文本标签需要领域定义和标注一致性；数据集结果不能自动迁移到实时交易文本。"),
    "finbert": ("Araci (2019), FinBERT", "https://arxiv.org/abs/1908.10063", "说明领域预训练对金融情绪分类的价值；分类准确率不等于方向预测准确率。"),
    "bloomberggpt": ("Wu et al. (2023), BloombergGPT", "https://arxiv.org/abs/2303.17564", "说明金融领域语料与通用能力的权衡；论文基准不能替代本书任务上的独立评测。"),
    "fingpt": ("Yang et al. (2023), FinGPT", "https://arxiv.org/abs/2306.06031", "讨论金融 LLM 的数据流水线与适配；开源可复现不等于信号具有经济价值。"),
    "helm": ("Liang et al. (2022), Holistic Evaluation of Language Models", "https://arxiv.org/abs/2211.09110", "把准确性、鲁棒性、校准和效率分开评估；单一总分会掩盖关键失败。"),
    "datasheets": ("Gebru et al. (2018), Datasheets for Datasets", "https://arxiv.org/abs/1803.09010", "记录数据来源、用途、限制和维护责任；数据说明书不能代替对数据本身的检查。"),
    "modelcards": ("Mitchell et al. (2018), Model Cards for Model Reporting", "https://arxiv.org/abs/1810.03993", "记录模型适用范围、指标和限制；模型卡不是合规或安全认证。"),
    "nist": ("NIST, AI Risk Management Framework", "https://www.nist.gov/itl/ai-risk-management-framework", "组织治理、测量、管理和持续监控；通用框架仍需转换为具体审批门与停止线。"),
    "genai": ("NIST AI 600-1, Generative AI Profile", "https://doi.org/10.6028/NIST.AI.600-1", "识别生成式 AI 的虚构、信息完整性和人机配置风险；风险清单不能替代系统测试。"),
    "owasp": ("OWASP, Top 10 for Large Language Model Applications", "https://owasp.org/www-project-top-10-for-large-language-model-applications/", "识别提示注入、信息泄漏和过度代理风险；条目需要转化为可执行测试。"),
    "ddia": ("Kleppmann，《Designing Data-Intensive Applications》", "https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/", "解释数据系统的可靠性、可扩展性和可维护性；工程可靠性不等于研究结论有效。"),
    "agents": ("OpenAI Codex 文档：AGENTS.md", "https://developers.openai.com/codex/guides/agents-md", "校准仓库级持久指令的职责；项目约定仍需通过实际命令验证。"),
    "skills": ("OpenAI Codex 文档：Agent Skills", "https://developers.openai.com/codex/skills", "校准 Skill 的用途和结构；Skill 不能替代产品代码或研究判断。"),
    "automations": ("OpenAI Codex 文档：Automations", "https://developers.openai.com/codex/app/automations", "校准自动化任务的边界；定时运行不意味着允许无人审批地扩大交易动作。"),
}

DEFAULTS = {
    1: ["econometrics", "tsay", "nist"],
    2: ["datasheets", "tsay", "ddia"],
    3: ["phrasebank", "finbert", "bloomberggpt", "fingpt", "helm"],
    4: ["afml", "reality", "pbo", "dsr", "technical", "fpp"],
    5: ["ddia", "modelcards", "owasp", "nist"],
    6: ["skills", "automations", "helm", "nist", "owasp"],
    7: ["modelcards", "nist", "ddia", "pbo", "helm"],
}

OVERRIDES = {
    2: ["econometrics", "event", "reality"], 4: ["econometrics", "tsay", "dsr"],
    8: ["datasheets", "tsay", "ddia"], 9: ["technical", "tsay", "reality"],
    11: ["bloomberggpt", "fingpt", "finbert", "genai"],
    12: ["datasheets", "phrasebank", "finbert"],
    13: ["finbert", "modelcards", "helm", "genai"],
    14: ["genai", "owasp", "datasheets"], 15: ["helm", "modelcards", "phrasebank", "finbert"],
    18: ["afml", "ddia", "fpp"], 19: ["dsr", "econometrics", "tsay"],
    20: ["reality", "pbo", "technical", "afml"], 21: ["fpp", "pbo", "dsr"],
    22: ["afml", "dsr", "nist"], 28: ["skills", "agents", "modelcards"],
    29: ["automations", "nist", "genai"], 30: ["nist", "genai", "owasp"],
    31: ["helm", "modelcards", "pbo"], 32: ["nist", "ddia", "modelcards"],
}


def part(chapter: int) -> int:
    return 1 if chapter <= 5 else 2 if chapter <= 10 else 3 if chapter <= 15 else 4 if chapter <= 22 else 5 if chapter <= 27 else 6 if chapter <= 32 else 7


def build_section(chapter: int) -> str:
    return ""


def main() -> None:
    changed = 0
    for path in sorted(CHAPTER_DIR.glob("*.md")):
        prefix = path.name.split("-", 1)[0]
        if not prefix.isdigit() or not 1 <= int(prefix) <= 35:
            continue
        text = path.read_text(encoding="utf-8").split(MARKER, 1)[0].rstrip()
        path.write_text(text + build_section(int(prefix)), encoding="utf-8")
        changed += 1
    print(f"removed inline external research notes from {changed} chapters")


if __name__ == "__main__":
    main()
