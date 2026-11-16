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


def refuses_modification(question: str) -> bool:
    return bool(MODIFICATION_RE.search(question))


def needs_guide_only(answer: str) -> bool:
    return bool(REPAIR_ACTION_RE.search(answer))
