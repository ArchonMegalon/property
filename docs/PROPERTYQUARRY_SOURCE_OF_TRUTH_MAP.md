# PropertyQuarry Source Of Truth Map

PropertyQuarry is one decision loop:

```text
Brief -> Search -> Compare -> Dossier -> Tour -> Decide -> Explain why -> Learn -> Improve the next search / aggregate market risk
```

Anything that does not serve that loop belongs in an operator-only lane.

| Domain | Source of truth | Consumers | Forbidden consumers |
| --- | --- | --- | --- |
| Property facts | PropertyQuarry research, provider extractors, document intake, verified evidence graph | search ranking, dossier writer, review pages, agent questions | NeuronWriter, Dadan, FlipLink, Telegram |
| Evidence and claims | `property_evidence_graph` / claim-bound research output | dossier writer, decision ledger, risk register, public-safe aggregates | direct public pages without redaction |
| Decisions | `property_decision_ledger` | search learning, Telegram buttons, workbench, review pages, risk aggregates | raw channel feedback as final state |
| PDF narrative | Dossier writer verified narrative | PremiumDossier renderer | MarkupGo, FlipLink, NeuronWriter as truth author |
| PDF rendering | PremiumDossier via MarkupGo or local Playwright | FlipLink, Email, Telegram | legacy renderer except explicit emergency mode |
| Human video feedback | Dadan untrusted inbox | owner review, accepted claims after review | direct learning, public reports, private dossier truth |
| 3D tours | Matterport / 3DVista tour providers | review pages, Telegram titled buttons, dossier links | cube fallback, fake viewer labels |
| Fly-through video | MagicFit or approved photorealistic video lane | Telegram, dossier, review page | generic 3D-object renderer as final output |
| Public content intelligence | NeuronWriter public-safe mode | public city guides, public market reports, public explainers | private owner/family/agent packets by default |
| Publishing | FlipLink / signed packet links | sharing and analytics | source of truth for ranking or research |
| Operator projection | Teable and admin dashboards | operations | public pages, dossier content |
| Analytics | Rybbit public-safe taxonomy | product improvement | private identifiers, raw exact-property payloads |

## Required Product Objects

`property_decision_ledger`:

```text
property_ref
decision_state: unseen / reviewing / shortlisted / blocked / needs_documents / needs_agent_answer / viewing_requested / offer_candidate / rejected / archived
reason_keys
source: workbench / telegram / email / dadan / packet / tour
actor
confidence
created_at
supersedes_decision_id
learning_applied
aggregate_candidate
```

`property_evidence_graph`:

```text
claim_id
property_ref
claim_type: fact / source / risk / media / human_feedback / authority / investment_assumption / decision
text
source_type
source_ref
confidence
verification_state: confirmed / likely / unclear / missing / needs_owner_review / official_source_backed / provider_only / user_reported
privacy_class
allowed_outputs
freshness / expires_at
```

`agent_question_tasks`:

```text
property_ref
question_text
reason_key
source_claim_id
status: drafted / sent / answered / verified / contradicted / ignored
answer_source: email / Dadan / manual / document
updated_claim_id
```

`property_documents`:

```text
document_type
source
privacy_class
verified
extracted_claims
missing_pages
redaction_state
linked_risks
```

