# Solution Blueprint – BMT TalentFlow AI

## Produktziel

TalentFlow AI unterstützt Recruiter:innen bei der strukturierten, nachvollziehbaren Bewertung von Bewerbungen auf technische GenAI- und Integrationsrollen. Die finale Entscheidung bleibt beim Menschen.

## Primärer Demo-Use-Case

> Eine Recruiterin bewertet eine Bewerbung auf die Position „GenAI Entwickler/Integrator“ und erhält eine begründete Match-Analyse mit Quellen, Lücken und Interviewfragen.

## Integrationsfluss

```text
Mock SAP Recruiting API
        │
        ▼
FastAPI Integration Layer ──► GenAI Provider Abstraction
        │                               │
        ▼                               ▼
Audit/Event Store              OpenAI / Azure OpenAI
        │
        ▼
Recruiter UI
```

## Fachliche Objekte

- `JobPosting`: Stellenprofil, Anforderungen, Muss-/Kann-Kriterien
- `Candidate`: Stammdaten und Bewerbungsdokumente
- `MatchAnalysis`: Scores, Evidenz, Lücken, Risiken und Empfehlung
- `InterviewQuestion`: fachliche und verhaltensorientierte Folgefragen
- `AuditEvent`: Zeitpunkt, Akteur, Aktion und Modell-/Prompt-Version

## Qualitäts- und Sicherheitsprinzipien

- Keine automatische Einstellungsentscheidung
- Ergebnis immer mit Begründung und fehlenden Informationen
- Personenbezogene Daten nur zweckgebunden verarbeiten
- Provider und Modell austauschbar halten
- Strukturierte JSON-Ausgaben statt unkontrolliertem Freitext
- Jede Analyse und Statusänderung auditierbar machen

## Nächste Ausbaustufen

1. Echte SAP SuccessFactors-OData-Anbindung
2. PDF/DOCX-Upload und Textextraktion
3. Azure-OpenAI-Adapter mit Secret-Management
4. Rollen, OAuth2 und feinere Auditierung
5. Evaluation mit anonymisierten Bewerbungsbeispielen
