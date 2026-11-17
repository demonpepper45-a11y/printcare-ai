"""Streamlit chat and knowledge-management UI.

Run::

    $env:PYTHONPATH='src'
    streamlit run src/printcare/web/app.py

The page talks to the FastAPI service over HTTP.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.environ.get("PRINTCARE_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 120
MACHINES = [("a1", "拓竹 A1"), ("a1_mini", "拓竹 A1 mini")]
MACHINE_LABELS = dict(MACHINES)
STATUS_LABELS = {
    "answered": "✅ 有依据的回答",
    "needs_clarification": "❓ 需要补充信息",
    "insufficient_evidence": "⚠️ 资料不足",
    "refused": "⛔ 无法回答",
}


def _request(method: str, path: str, **kwargs) -> httpx.Response | None:
    try:
        # The UI always talks to the configured local API; do not route
        # 127.0.0.1 through a system HTTP proxy.
        return httpx.request(method, f"{API_URL}{path}", timeout=TIMEOUT, trust_env=False, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"无法连接 API：{type(exc).__name__}")
        return None


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return f"请求失败（HTTP {response.status_code}）"


def _render_ticket(ticket: dict, expanded: bool) -> None:
    with st.expander("故障单", expanded=expanded):
        rows = [
            ("机型", MACHINE_LABELS.get(ticket.get("machine"), ticket.get("machine"))),
            ("现象", ticket.get("symptom")),
            ("错误码", ticket.get("error_code")),
            ("耗材", ticket.get("filament")),
            ("供料方式", ticket.get("feed_method")),
            ("发生阶段", ticket.get("stage")),
            (
                "已经尝试",
                "；".join(ticket.get("attempted_steps") or []),
            ),
        ]
        for label, value in rows:
            st.markdown(f"**{label}**：{value or '待确认'}")


def _render_answer(payload: dict, message_key: str) -> None:
    ticket = payload.get("fault_ticket")
    if ticket:
        _render_ticket(ticket, expanded=payload.get("status") == "needs_clarification")
    st.caption(STATUS_LABELS.get(payload["status"], payload["status"]))
    st.markdown(payload["answer"] or "_（没有正文）_")
    if payload.get("follow_up_question"):
        st.info(payload["follow_up_question"])
    if payload.get("refusal_reason"):
        st.warning(f"拒答原因：{payload['refusal_reason']}")
    for index, citation in enumerate(payload.get("citations") or [], start=1):
        heading = " > ".join(citation.get("section_path") or []) or "-"
        label = citation.get("source_label") or f"#{index}"
        title = f"[{label}] {citation['title']} · {heading}"
        with st.expander(title):
            st.write(citation["quote"])
            st.markdown(f"[打开官方原文]({citation['source_url']})")
            st.caption(f"官方更新时间：{citation.get('official_updated_at') or '未知'}")
    session_id = payload.get("session_id")
    if session_id:
        columns = st.columns(2)
        if columns[0].button("解决了", key=f"solved_{message_key}"):
            _send_feedback(session_id, True)
        if columns[1].button("没解决", key=f"unsolved_{message_key}"):
            _send_feedback(session_id, False)


def _send_feedback(session_id: str, solved: bool) -> None:
    response = _request(
        "POST",
        "/api/v1/feedback",
        json={"session_id": session_id, "solved": solved},
    )
    if response is not None and response.status_code == 200:
        st.success("感谢反馈，已记录。")
    elif response is not None:
        st.error(_error_message(response))


def _render_knowledge_status(admin_token: str) -> None:
    health = _request("GET", "/api/v1/health")
    if health is not None and health.status_code == 200:
        data = health.json()
        st.metric("文档", data["documents"])
        st.metric("片段", data["chunks"])
        st.caption(f"模型：{data['model']}")
    else:
        st.warning("API 未连接")

    if st.button("刷新首批资料（5 篇）", use_container_width=True):
        response = _request(
            "POST",
            "/api/v1/admin/refresh",
            json={"limit": 5},
            headers={"X-Admin-Token": admin_token},
        )
        if response is None:
            return
        if response.status_code == 200:
            result = response.json()
            st.success(
                f"解析 {result['parsed']}，新增 {result['inserted']}，"
                f"更新 {result['updated']}，失败 {result['failed']}"
            )
        else:
            st.error(_error_message(response))

    with st.expander("资料状态"):
        response = _request(
            "GET",
            "/api/v1/admin/documents",
            headers={"X-Admin-Token": admin_token},
        )
        if response is None:
            return
        if response.status_code == 200:
            documents = response.json()
            st.dataframe(
                [
                    {
                        "机型": ",".join(item["machines"]),
                        "路径": item["canonical_path"],
                        "标题": item["title"],
                        "片段": item["chunk_count"],
                        "启用": item["enabled"],
                        "官方更新": item["official_updated_at"],
                    }
                    for item in documents
                ],
                use_container_width=True,
            )
        else:
            st.error(_error_message(response))


st.set_page_config(page_title="PrintCare AI", page_icon="🛠️", layout="wide")
st.title("PrintCare AI · A1 / A1 mini 售后助手")
st.caption("答案只依据官方资料；资料不足时会说明，不会编造维护步骤。")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "machine" not in st.session_state:
    st.session_state.machine = "a1"

with st.sidebar:
    st.header("设置")
    selected = st.selectbox("机型", options=MACHINES, format_func=lambda item: item[1], index=0)
    machine = selected[0]
    if machine != st.session_state.machine:
        st.session_state.machine = machine
        st.session_state.session_id = None
        st.session_state.messages = []
        st.info("已切换机型，开始新会话。")
    admin_token = st.text_input("管理令牌（可选）", type="password")
    st.divider()
    st.subheader("知识库状态")
    _render_knowledge_status(admin_token)
    st.divider()
    if st.button("清空对话"):
        st.session_state.messages = []
        st.session_state.session_id = None
        st.rerun()

for index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        if message["role"] == "assistant" and message.get("payload"):
            _render_answer(message["payload"], f"{index}")
        else:
            st.markdown(message["content"])

prompt = st.chat_input("描述你的问题，例如：A1 mini 挤出机堵料怎么清理？")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    body = {"question": prompt, "machine": st.session_state.machine}
    if st.session_state.session_id:
        body["session_id"] = st.session_state.session_id
    response = _request("POST", "/api/v1/chat", json=body)

    with st.chat_message("assistant"):
        if response is None:
            st.error("请求失败，请确认 API 已启动。")
        elif response.status_code != 200:
            st.error(_error_message(response))
        else:
            payload = response.json()
            st.session_state.session_id = payload["session_id"]
            st.session_state.messages.append(
                {"role": "assistant", "content": payload["answer"], "payload": payload}
            )
            _render_answer(payload, str(len(st.session_state.messages) - 1))
