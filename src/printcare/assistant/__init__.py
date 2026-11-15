"""Assistant package: model providers, prompts, citations and orchestration."""

from printcare.assistant.assistant import Assistant, ChatResult, MachineCheck
from printcare.assistant.context import Citation, ModelOutputError
from printcare.assistant.provider import DeepSeekProvider, FakeProvider, ProviderError
from printcare.assistant.session import Session, SessionSummary

__all__ = [
    "Assistant",
    "ChatResult",
    "Citation",
    "DeepSeekProvider",
    "FakeProvider",
    "MachineCheck",
    "ModelOutputError",
    "ProviderError",
    "Session",
    "SessionSummary",
]
