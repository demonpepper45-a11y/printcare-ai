"""FastAPI application exposing the contract in ``docs/interfaces.md``."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from printcare.api.documents import counts, list_documents, set_enabled
from printcare.api.feedback import FeedbackStore
from printcare.api.schemas import (
    ChatRequest,
    ChatResponse,
    CitationModel,
    DocumentModel,
    DocumentPatch,
    ErrorDetail,
    ErrorResponse,
    FailureModel,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSummary,
    HealthResponse,
    MachineCheckModel,
    MachineModel,
    RefreshRequest,
    RefreshResponse,
    SessionModel,
    SessionPatch,
)
from printcare.api.sessions import SessionStore
from printcare.assistant.assistant import Assistant, ChatResult
from printcare.assistant.context import ModelOutputError
from printcare.assistant.provider import (
    DEFAULT_BASE_URL,
    DeepSeekProvider,
    ModelProvider,
    ProviderError,
)
from printcare.assistant.session import Session, SessionSummary
from printcare.ingestion.fetch import HttpFetcher
from printcare.ingestion.ids import canonical_path
from printcare.ingestion.inventory import fetch_inventory, select_refs
from printcare.ingestion.pipeline import run_ingestion
from printcare.ingestion.store import IngestStore
from printcare.retrieval.retriever import Retriever, UnsupportedMachineError
from printcare.settings import ConfigError, Settings, resolve_model_api_key

MACHINE_LABELS = {"a1": "拓竹 A1", "a1_mini": "拓竹 A1 mini"}
HTTP_CODE_MAP = {
    400: "invalid_request",
    401: "unauthorized",
    404: "not_found",
    413: "payload_too_large",
    422: "validation_failed",
    429: "rate_limited",
    503: "source_unavailable",
}


def create_app(
    *,
    db_path: str | Path | None = None,
    provider: ModelProvider | None = None,
    settings: Settings | None = None,
    inventory_fetcher=None,
    page_fetcher=None,
) -> FastAPI:
    resolved = settings or Settings.from_env()
    database = Path(db_path or resolved.database_path)
    if not database.is_file():
        raise RuntimeError(f"runtime database not found: {database}; run ingestion first")

    app = FastAPI(title="PrintCare AI API", version="1.0.0")
    app.state.settings = resolved
    app.state.db_path = database
    app.state.sessions = SessionStore()
    app.state.feedback = FeedbackStore(database)
    app.state.provider = provider or _build_provider(resolved)
    app.state.retriever = Retriever.from_sqlite(str(database))
    app.state.assistant = Assistant(app.state.retriever, app.state.provider)
    app.state.inventory_fetcher = inventory_fetcher or fetch_inventory
    app.state.page_fetcher = page_fetcher or HttpFetcher(delay=0.5)
    app.state.admin_token = resolved.admin_token

    _add_middleware(app)
    _add_routes(app)
    _add_handlers(app)
    return app


def _build_provider(settings: Settings) -> DeepSeekProvider:
    try:
        key = resolve_model_api_key(settings)
    except ConfigError as exc:
        raise RuntimeError(str(exc)) from exc
    return DeepSeekProvider(
        key,
        model=settings.model_name,
        base_url=settings.model_base_url or DEFAULT_BASE_URL,
    )


def _add_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


def _require_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    token = request.app.state.admin_token
    if not token:
        if request.app.state.settings.environment == "local":
            return
        raise HTTPException(
            status_code=503,
            detail={"code": "admin_not_configured", "message": "管理令牌未配置"},
        )
    if x_admin_token != token:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "管理令牌无效"},
        )


def _add_routes(app: FastAPI) -> None:
    @app.get("/api/v1/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        documents, chunks = counts(request.app.state.db_path)
        model = getattr(request.app.state.provider, "model", request.app.state.settings.model_name)
        return HealthResponse(status="ok", documents=documents, chunks=chunks, model=str(model))

    @app.get("/api/v1/machines", response_model=list[MachineModel])
    def machines() -> list[MachineModel]:
        return [MachineModel(code=code, label=label) for code, label in MACHINE_LABELS.items()]

    @app.post("/api/v1/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        sessions: SessionStore = request.app.state.sessions
        session: Session | None = None
        if payload.session_id:
            session = sessions.get(payload.session_id)
            if session is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "session_not_found", "message": "会话不存在或已过期"},
                )
        if session is None:
            session = sessions.create(payload.machine)
        result = request.app.state.assistant.answer(payload.question, payload.machine, session)
        sessions.save(session)
        return _chat_response(result)

    @app.get("/api/v1/sessions/{session_id}", response_model=SessionModel)
    def get_session(session_id: str, request: Request) -> SessionModel:
        session = _load_session(request, session_id)
        return _session_model(session.summary())

    @app.patch("/api/v1/sessions/{session_id}", response_model=SessionModel)
    def patch_session(session_id: str, payload: SessionPatch, request: Request) -> SessionModel:
        session = _load_session(request, session_id)
        if payload.machine is not None:
            session.correct_machine(payload.machine)
        if payload.reported_issue is not None:
            session.reported_issue = payload.reported_issue.strip()[:200] or None
        if payload.attempted_steps is not None:
            session.attempted_steps = [
                step.strip() for step in payload.attempted_steps if step.strip()
            ][:10]
        session.touch()
        request.app.state.sessions.save(session)
        return _session_model(session.summary())

    @app.delete("/api/v1/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str, request: Request) -> Response:
        if not request.app.state.sessions.delete(session_id):
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "message": "会话不存在或已过期"},
            )
        return Response(status_code=204)

    @app.post("/api/v1/feedback", response_model=FeedbackResponse)
    def create_feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
        feedback_id = request.app.state.feedback.add(
            payload.session_id, payload.solved, payload.comment
        )
        return FeedbackResponse(id=feedback_id)

    @app.get(
        "/api/v1/admin/documents",
        response_model=list[DocumentModel],
        dependencies=[Depends(_require_admin)],
    )
    def admin_documents(request: Request, machine: str | None = None) -> list[DocumentModel]:
        return [
            DocumentModel(**item) for item in list_documents(request.app.state.db_path, machine)
        ]

    @app.patch(
        "/api/v1/admin/documents/{doc_id}",
        response_model=DocumentModel,
        dependencies=[Depends(_require_admin)],
    )
    def admin_patch_document(
        doc_id: str, payload: DocumentPatch, request: Request
    ) -> DocumentModel:
        if not set_enabled(request.app.state.db_path, doc_id, payload.enabled):
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "文档不存在"},
            )
        for item in list_documents(request.app.state.db_path):
            if item["doc_id"] == doc_id:
                return DocumentModel(**item)
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "文档不存在"})

    @app.post(
        "/api/v1/admin/refresh",
        response_model=RefreshResponse,
        dependencies=[Depends(_require_admin)],
    )
    def admin_refresh(payload: RefreshRequest, request: Request) -> RefreshResponse:
        refs = select_refs(request.app.state.inventory_fetcher())
        if payload.paths:
            allowed = {canonical_path(item) for item in payload.paths}
            refs = [ref for ref in refs if ref.path in allowed]
        refs = refs[: payload.limit]
        store = IngestStore(request.app.state.db_path)
        try:
            report = run_ingestion(refs, request.app.state.page_fetcher, store)
        finally:
            store.close()
        request.app.state.retriever = Retriever.from_sqlite(str(request.app.state.db_path))
        request.app.state.assistant = Assistant(
            request.app.state.retriever, request.app.state.provider
        )
        return RefreshResponse(
            run_id=report.run_id,
            parsed=report.parsed,
            inserted=report.inserted,
            updated=report.updated,
            unchanged=report.unchanged,
            failed=report.failed,
            disabled=report.disabled,
            failures=[
                FailureModel(
                    source_url=failure.source_url,
                    stage=failure.stage,
                    error_type=failure.error_type,
                    message=failure.message,
                )
                for failure in report.failures
            ],
        )

    @app.get(
        "/api/v1/admin/feedback",
        response_model=FeedbackSummary,
        dependencies=[Depends(_require_admin)],
    )
    def admin_feedback(request: Request) -> FeedbackSummary:
        return FeedbackSummary(**request.app.state.feedback.summary())


def _load_session(request: Request, session_id: str) -> Session:
    session = request.app.state.sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "session_not_found", "message": "会话不存在或已过期"},
        )
    return session


def _session_model(summary: SessionSummary) -> SessionModel:
    return SessionModel(
        session_id=summary.session_id,
        machine=summary.machine,
        reported_issue=summary.reported_issue,
        attempted_steps=list(summary.attempted_steps),
        updated_at=summary.updated_at,
    )


def _chat_response(result: ChatResult) -> ChatResponse:
    citations = [
        CitationModel(
            chunk_id=citation.chunk_id,
            doc_id=citation.doc_id,
            title=citation.title,
            source_url=citation.source_url,
            section_path=list(citation.section_path),
            anchor=citation.anchor,
            machine=citation.machine,
            official_updated_at=citation.official_updated_at,
            quote=citation.quote,
            quote_truncated=citation.quote_truncated,
        )
        for citation in result.citations
    ]
    return ChatResponse(
        request_id=result.request_id,
        session_id=result.session_id,
        status=result.status,
        answer=result.answer,
        citations=citations,
        missing_information=list(result.missing_information),
        follow_up_question=result.follow_up_question,
        refusal_reason=result.refusal_reason,
        machine_check=MachineCheckModel(
            requested=result.machine_check.requested,
            detected_in_question=list(result.machine_check.detected_in_question),
            result=result.machine_check.result,
        ),
        session=_session_model(result.session),
    )


def _add_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(part) for part in error["loc"][1:]), "message": error["msg"]}
            for error in exc.errors()
        ]
        return _error(request, 422, "validation_failed", "请求字段不合法", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return _error(
                request,
                exc.status_code,
                str(detail["code"]),
                str(detail.get("message") or detail["code"]),
                detail.get("details"),
            )
        code = HTTP_CODE_MAP.get(exc.status_code, "internal_error")
        return _error(request, exc.status_code, code, str(detail))

    @app.exception_handler(UnsupportedMachineError)
    async def unsupported_machine_handler(
        request: Request, exc: UnsupportedMachineError
    ) -> JSONResponse:
        return _error(request, 422, "unsupported_machine", str(exc))

    @app.exception_handler(ProviderError)
    async def provider_handler(request: Request, _exc: ProviderError) -> JSONResponse:
        return _error(request, 503, "source_unavailable", "模型服务暂不可用，请稍后重试")

    @app.exception_handler(ModelOutputError)
    async def model_output_handler(request: Request, _exc: ModelOutputError) -> JSONResponse:
        return _error(request, 503, "source_unavailable", "模型输出无法解析，请稍后重试")

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, _exc: Exception) -> JSONResponse:
        return _error(request, 500, "internal_error", "服务内部错误")


def _error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details, request_id=request_id)
    ).model_dump()
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"X-Request-Id": request_id or ""},
    )
