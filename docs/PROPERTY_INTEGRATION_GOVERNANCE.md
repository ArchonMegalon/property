# Property Integration Governance

PropertyQuarry integrates external tools only as governed lanes. The application remains the source of truth for property facts, ranking, decisions, billing, publications, approvals, and user data lifecycle.

## Priority Order

1. MetaSurvey and Lunacal: product learning, post-viewing feedback, rejection reasons, consultations, and viewing scheduling.
2. ApiX-Drive and Invoiless: agent workflow exports and invoice/VAT documents.
3. Documentation.AI: reviewed public help-center and market documentation.
4. Paperguide and Internxt: controlled document-research pilot and encrypted off-site recovery.
5. ApproveThis: optional Agent-plan approval workflows.
6. Unmixr and Deftform: optional audio briefings and public intake.

## Required Boundary

Every lane must define:

- allowed use and forbidden use;
- allowed data classes;
- exact-address and private-document posture;
- verification receipts;
- an env-level enable flag and kill switch;
- fail-closed behavior when provider proof is missing.

External providers may transport, draft, schedule, survey, store encrypted backups, or create document candidates. They must not own canonical property truth, personal fit, ranking, legal/financial conclusions, entitlement, publication approval, or customer decisions.

The executable catalog lives in `app.services.property_integration_governance`.
