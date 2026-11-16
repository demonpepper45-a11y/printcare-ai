"""Conservative application rules for the currently unverified repair workflows."""

import re

MODIFICATION_RE = re.compile(
    r"(加装|安装|改装|自制|增加).{0,20}(腔体加热|加热腔体)|"
    r"(绕过|关闭|禁用|取消|屏蔽).{0,12}(安全保护|温控保护|热失控保护)|"
    r"(install|add|build).{0,30}(chamber heater|heated chamber)|"
    r"(bypass|disable).{0,25}(thermal protection|thermal runaway)",
    re.I,
)
REPAIR_ACTION_RE = re.compile(
    r"拆卸|拆下|拆开|拆装|取下|取出|移除|拔出|拔插|断开.{0,12}(连接器|线缆|电缆)|"
    r"(重新连接|连接|插回).{0,15}(线|电缆|主板|接口|连接柱)|"
    r"(测量|测).{0,25}(电阻|阻值|接线柱|信号线引脚|板输出)|"
    r"拧紧|锁紧|拧松|加热至|加热到|热风枪|G29\.1|"
    r"(disconnect|reconnect|unplug|remove).{0,30}(cable|connector|nozzle|cover)|"
    r"measure.{0,25}(resistance|voltage)|heat.{0,15}\d+",
    re.I,
)

# Exempt only explicit non-operational mentions. Every positive match is still
# checked, so a disclaimer or quotation cannot hide a second actual request.
QUOTE_RE = re.compile(r'“[^”]*”|「[^」]*」|"[^"\n]*"')
NEGATED_INTENT_RE = re.compile(
    r"(?:不打算|不准备|不想|不需要|不会|不要|不应|禁止)\s*$|"
    r"(?:do not want to|don't want to|not planning to|will not)\s*$",
    re.I,
)
DOUBLE_NEGATION_RE = re.compile(r"(?:不是|并非|不代表).{0,4}(?:不想|不打算|不准备)\s*$")
REFERENCE_RE = re.compile(
    r"看到|有人写|文档|说法|含义|什么意思|风险|不是要这样做|quote|meaning", re.I
)
PROCEDURE_REQUEST_RE = re.compile(
    r"怎么做|如何操作|怎么操作|具体步骤|接线步骤|接线方法|怎么接线|如何接线|"
    r"给.{0,8}(步骤|方法)|告诉.{0,8}(步骤|方法)|"
    r"(?:怎么|如何|怎样)(?!理解|解释|看待|判断|评价|区分)|"
    r"教我|照着做|照做|按.{0,8}操作|操作方法|教程|想这样做|"
    r"how to|instructions|wiring",
    re.I,
)


def refuses_modification(question: str) -> bool:
    quotes = list(QUOTE_RE.finditer(question))
    outside_quotes = QUOTE_RE.sub("", question)
    asks_procedure = bool(PROCEDURE_REQUEST_RE.search(outside_quotes))
    for match in MODIFICATION_RE.finditer(question):
        clause_prefix = re.split(r"[，,。；;！？!?\n]", question[: match.start()])[-1]
        negated = NEGATED_INTENT_RE.search(clause_prefix)
        if negated and not DOUBLE_NEGATION_RE.search(clause_prefix) and not asks_procedure:
            continue
        quoted = any(q.start() < match.start() and match.end() < q.end() for q in quotes)
        if quoted and REFERENCE_RE.search(outside_quotes) and not asks_procedure:
            continue
        return True
    return False


def needs_guide_only(answer: str) -> bool:
    return bool(REPAIR_ACTION_RE.search(answer))


def is_definition_question(question: str) -> bool:
    """Recognize explanation requests conservatively, excluding mixed actions."""
    if not re.search(
        r"含义|定义|什么意思|什么故障|是什么|什么是|meaning|what does|what is", question, re.I
    ):
        return False
    # Split contrasts before removing explicitly declined actions. A following
    # "but tell me the steps" must survive the negative clause.
    clauses = re.split(r"[，,。；;！？!?\n]|但是|不过|而是|但|同时|另外", question)
    remaining = []
    for clause in clauses:
        if re.match(r"\s*(?:不要|不需要|不用|无需|不必)", clause):
            continue
        remaining.append(clause)
    request = " ".join(remaining)
    request = re.sub(r"(?:怎么|如何|怎样)(?=理解|解释)", "", request)
    if needs_guide_only(request):
        return False
    return not re.search(
        r"怎么|如何|怎样|步骤|操作|维修|修理|排查|检查|更换|安装|拆|接线|测量|"
        r"how (?:to|do)|steps|repair|replace|install|measure|instructions",
        request,
        re.I,
    )


SAFETY_CONTEXT_RE = re.compile(
    r"拆|装|换|清|维护|排查|检查|测量|接线|拔|插|脱开|接回|加热|温度|"
    r"喷嘴|热端|热床|皮带|润滑|堵|故障|步骤|操作|校准",
    re.I,
)


def needs_safety_context(question: str) -> bool:
    """Maintenance/how-to questions need the official safety and tool sections."""
    return bool(SAFETY_CONTEXT_RE.search(question)) and not is_definition_question(question)
