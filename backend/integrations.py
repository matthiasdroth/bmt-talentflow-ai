"""Integration boundaries for SAP and GenAI providers.

The demo uses local adapters, while the application code talks to these
interfaces instead of depending directly on demo.json or analysis rules.
Real SAP/OData and hosted-LLM adapters can be added without changing the API
routes or frontend contract.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class SapClient(Protocol):
    def get_job(self) -> dict[str, Any]: ...
    def get_candidate(self) -> dict[str, Any]: ...
    def update_status(self, status: str) -> dict[str, Any]: ...


@dataclass
class MockSapClient:
    data: dict[str, Any]
    last_status: str | None = None

    def get_job(self) -> dict[str, Any]:
        return self.data["job"]

    def get_candidate(self) -> dict[str, Any]:
        return self.data["candidate"]

    def update_status(self, status: str) -> dict[str, Any]:
        self.last_status = status
        return {
            "status": "saved",
            "system": "mock-sap",
            "message": "Recruiting-Status im Mock-SAP aktualisiert",
            "value": status,
        }


class GenAIProvider(Protocol):
    def analyze(self, document_text: str, job: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class RulesGenAIProvider:
    """Deterministic demo provider with the same contract as an LLM adapter."""

    provider_name: str = "rules-provider"
    prompt_version: str = "v0.3"
    signals: dict[str, list[str]] = field(default_factory=lambda: {
        "API- und Systemintegration": ["api", "rest", "integration", "schnittstelle", "middleware"],
        "Python": ["python", "fastapi", "django", "pandas"],
        "GenAI- und LLM-APIs": ["genai", "generative ai", "llm", "openai", "deepseek", "langchain"],
        "SAP- oder ERP-Erfahrung": ["sap", "s/4hana", "erp", "successfactors"],
        "Cloud-Dienste": ["azure", "aws", "gcp", "cloud"],
        "OAuth und API-Sicherheit": ["oauth", "oauth2", "api-key", "authentication", "authentifizierung"],
    })

    def analyze(self, document_text: str, job: dict[str, Any]) -> dict[str, Any]:
        document_text = (document_text or "").lower()
        has_document = bool(document_text.strip())
        evidence_defaults = {
            requirement: "Keine passende Evidenz im Dokument gefunden."
            for requirement in self.signals
        }
        matched = []
        for requirement, keywords in self.signals.items():
            found = [keyword for keyword in keywords if keyword in document_text]
            score = min(96, 62 + len(found) * 8) if found else 35
            evidence = (
                f"Erkannte Begriffe: {', '.join(found[:3])}."
                if found else evidence_defaults[requirement]
            )
            matched.append({"requirement": requirement, "evidence": evidence, "score": score})
        score = round(sum(item["score"] for item in matched) / len(matched)) if has_document else 89
        gaps = [
            f"Für folgende Anforderung wurde keine eindeutige Evidenz gefunden: {item['requirement']}."
            for item in matched if item["score"] == 35
        ]
        if not gaps:
            gaps = ["Erfahrung mit GraphQL und iPaaS sollte im Gespräch vertieft werden."]
        return {
            "status": "completed",
            "score": score,
            "confidence": 0.84 if has_document else 0.91,
            "recommendation": "Zum technischen Erstgespräch einladen" if score >= 70 else "Profil im Fachgespräch vertiefen",
            "matched": matched,
            "gaps": gaps[:3],
            "questions": [
                "Wie würden Sie einen LLM-Service sicher an SAP S/4HANA anbinden?",
                "Wie behandeln Sie Timeouts, Retries und Rate Limits bei GenAI-APIs?",
                "Wie stellen Sie Nachvollziehbarkeit und Datenschutz bei Bewerberdaten sicher?",
            ],
            "audit": {
                "model": self.provider_name,
                "prompt_version": self.prompt_version,
                "source": "uploaded-document" if has_document else "mock-sap",
            },
        }
