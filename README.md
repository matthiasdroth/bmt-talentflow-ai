# BMT TalentFlow AI

Ein SAP-integrierter GenAI-Recruiting-Copilot für die Bewertung von Bewerbungen.

## MVP-Demo

Die erste Demo zeigt den durchgängigen Ablauf:

1. Eine Recruiterin wählt die Stelle „GenAI Entwickler/Integrator“.
2. Ein Kandidatenprofil wird aus dem Mock-SAP-Service geladen.
3. TalentFlow AI erstellt eine nachvollziehbare Match-Analyse.
4. Interviewfragen werden vorgeschlagen.
5. Der Analyse-Status wird über die API zurück in den Recruiting-Prozess geschrieben.

## Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Danach: http://127.0.0.1:8000

Die GenAI-Analyse ist im MVP deterministisch simuliert. Die Provider-Schnittstelle ist bereits so angelegt, dass später OpenAI oder Azure OpenAI angeschlossen werden kann.

## Projektstruktur

```text
backend/              FastAPI und Mock-SAP-Integration
frontend/             Recruiter-Oberfläche
docs/                 Solution Blueprint und Architekturentscheidungen
data/                 Demo-Daten
```
