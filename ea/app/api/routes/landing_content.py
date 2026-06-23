from __future__ import annotations

PUBLIC_NAV = (
    {"href": "/", "label": "Product", "key": "product"},
    {"href": "/directory", "label": "Directory", "key": "directory"},
    {"href": "/how-it-works", "label": "How it works", "key": "how-it-works"},
    {"href": "/pricing", "label": "Pricing", "key": "pricing"},
    {"href": "/sign-in?signing_in=1", "label": "Sign in", "key": "sign-in"},
)

EA_APP_NAV_GROUPS = (
    {
        "label": "Workspace",
        "items": (
            {"href": "/app/today", "label": "Today", "key": "today"},
            {"href": "/app/queue", "label": "Queue", "key": "queue"},
            {"href": "/app/commitments", "label": "Commitments", "key": "commitments"},
            {"href": "/app/people", "label": "People", "key": "people"},
            {"href": "/app/evidence", "label": "Evidence", "key": "evidence"},
            {"href": "/app/settings", "label": "Settings", "key": "settings"},
        ),
    },
)

PROPERTY_APP_NAV_GROUPS = (
    {
        "label": "PropertyQuarry",
        "items": (
            {"href": "/app/properties", "label": "Home", "key": "properties"},
            {"href": "/app/search", "label": "Search", "key": "search"},
            {"href": "/app/agents", "label": "Search agents", "key": "agents"},
            {"href": "/app/account", "label": "Account", "key": "account"},
        ),
    },
)


def app_nav_groups_for_brand(brand_key: str) -> tuple[dict[str, object], ...]:
    if str(brand_key or "").strip().lower() == "propertyquarry":
        return PROPERTY_APP_NAV_GROUPS
    return EA_APP_NAV_GROUPS


APP_NAV_GROUPS = EA_APP_NAV_GROUPS

ADMIN_NAV_GROUPS = (
    {
        "label": "Operator center",
        "items": (
            {"href": "/admin/policies", "label": "Policies", "key": "policies"},
            {"href": "/admin/office", "label": "Office", "key": "office"},
            {"href": "/admin/providers", "label": "Providers", "key": "providers"},
            {"href": "/admin/audit-trail", "label": "Audit Trail", "key": "audit-trail"},
            {"href": "/admin/operators", "label": "Operators", "key": "operators"},
            {"href": "/admin/community", "label": "Access", "key": "community"},
            {"href": "/admin/api", "label": "Runtime", "key": "api"},
        ),
    },
)

FEATURE_CARDS = (
    {
        "title": "Search across portals in one place",
        "body": "Start with one property brief, one ranked sweep, and one shortlist that is easier to review than raw listing tabs.",
    },
    {
        "title": "Explain why a match is good",
        "body": "Show fit reasons, likely weak spots, and concrete research gaps before the user wastes time opening ten listings.",
    },
    {
        "title": "Learn from each review",
        "body": "Capture likes, dislikes, and hard rules so later searches get sharper instead of repeating the same weak matches.",
    },
)

HOW_STEPS = (
    {"title": "Create the account", "body": "Use email first, then optional Google identity so return access stays simple and narrow."},
    {"title": "Set your search brief", "body": "Define market, budget, household needs, and hard rules before the first sweep runs."},
    {"title": "Review the shortlist", "body": "Keep the first run focused on ranked candidates, property pages, and visible feedback."},
)

PERSONAS = (
    {"title": "Private search first", "body": "Start alone, prove the ranking and research quality quickly, and add shared review only if the buying process really needs it."},
    {"title": "Guided shortlist review", "body": "The first session should end with a useful shortlist and visible fit logic, not with another saved-search graveyard."},
    {"title": "Commercial depth later", "body": "Paid research, broader portal coverage, and heavier agent work should expand only after the first shortlist proves useful."},
)

TRUST_CARDS = (
    {"title": "Tight account permissions", "body": "Google is optional identity and return access, not a hidden demand for broad mailbox permissions."},
    {"title": "Visible research", "body": "The product should make clear which portals were scanned, which assumptions were made, and what still needs checking."},
    {"title": "Saved learning loop", "body": "Feedback, property reasons, and shortlist context stay visible so search quality improves instead of drifting."},
)

LANDING_FAQS = (
    {
        "question": "What does it connect to?",
        "answer": "Start with account creation and property preferences. Google is optional for sign-in continuity. Portal coverage and research expand from there.",
    },
    {
        "question": "Does it auto-research every listing?",
        "answer": "No. The product stays explicit about what was scanned, what was enriched, and which deeper research steps still need to run.",
    },
    {
        "question": "Can I start alone and add others later?",
        "answer": "Yes. Start with a private account, then add shared review and commercial seats later from Account, with Connections inside it.",
    },
)

PRODUCT_MODULES = (
    {"title": "Property brief", "body": "Capture country, search mode, budget, household needs, and hard rules once so every later search starts from the same frame."},
    {"title": "Provider sweep", "body": "Scan the selected portals as one run instead of forcing the user to maintain separate browser rituals for every source."},
    {"title": "Property page", "body": "Attach fit reasons, missing information, distances, and follow-up cues to each strong candidate."},
    {"title": "Shortlist review", "body": "Keep the best candidates in one place with review links, tours, and clear next actions."},
    {"title": "Learning loop", "body": "Turn likes, dislikes, and hard rules into better ranking on the next run instead of leaving them as forgotten opinions."},
    {"title": "Preferences", "body": "Keep profile, limits, integrations, and billing visible without dragging the user through unrelated assistant tooling."},
)

SIGN_IN_NOTES = (
    "Return through a current session, a secure email link, an account invite, or SSO.",
    "Create a PropertyQuarry account from /register if you are starting fresh.",
    "Google connection is optional identity and return access, not the required center of the product.",
    "Shared review, billing, and broader account controls come later from Account, with Connections inside it, after the first shortlist proves useful.",
)

PRICING_TIERS = (
    {
        "title": "Free",
        "price": "0",
        "body": "A focused entry path for account creation, profile setup, and a first useful shortlist.",
        "facts": (
            "1 account",
            "Limited shortlist volume",
            "Google identity optional",
            "Basic saved preferences",
            "Review-first experience",
        ),
    },
    {
        "title": "Plus",
        "price": "Paid",
        "body": "For users who want more searches, deeper property research, and more persistent review coverage.",
        "facts": (
            "More source coverage",
            "Deeper property research",
            "Email alerts and saved runs",
            "Longer shortlist history",
            "Self-serve billing",
        ),
    },
    {
        "title": "Agent",
        "price": "Premium",
        "body": "For users who want heavier research agents, richer enrichment, and more hands-off search coverage.",
        "facts": (
            "Deep research runs",
            "Higher portal and result limits",
            "Stronger enrichment budget",
            "Priority notifications",
            "Priority support",
        ),
    },
)

DOC_LINKS = (
    {"title": "Docs", "href": "/docs", "body": "Product references for search, ranking, evidence, sharing, and account setup."},
    {"title": "Integrations", "href": "/integrations", "body": "Connection details for Google identity, notifications, and later delivery options."},
    {"title": "Support", "href": "/support", "body": "Help for failed runs, wrong-area matches, missing facts, billing, and deletion requests."},
)

PUBLIC_TRUST_PAGES = {
    "privacy": {
        "path": "/privacy",
        "nav": "privacy",
        "title": "Privacy",
        "kicker": "Data protection",
        "summary": "PropertyQuarry keeps search preferences, listing evidence, generated media, and shared links scoped to the property decision they support.",
        "band": (
            {
                "title": "Data stays contextual",
                "body": "Property preferences, shortlist decisions, uploaded documents, and delivery history are handled as property-workflow data, not generic assistant memory.",
            },
            {
                "title": "Sharing is explicit",
                "body": "Public packet and tour links are separate publication events. They should expose only the redacted manifest needed for review.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Account data",
                "title": "What the product stores",
                "body": "The app can store account identity, saved search preferences, run history, shortlist decisions, feedback, generated packets, tour history, and delivery settings.",
                "items": (
                    "Exact addresses, documents, and internal source URLs stay private unless a user explicitly shares a redacted page or file.",
                    "Preference learning is used to improve ranking for the account and must stay separable from cross-customer analytics.",
                    "Connected services should use the narrowest practical permission set for the selected workflow.",
                ),
            },
            {
                "eyebrow": "Controls",
                "title": "User lifecycle controls",
                "body": "Account export, deletion, shared-link revocation, session revocation, and retention controls are first-class product responsibilities.",
                "items": (
                    "Search history and research output should be removable without deleting the entire account.",
                    "Public share links need expiry and revocation, not just hidden navigation.",
                    "Delivery channels need clear opt-in, opt-out, and quiet-hour controls.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "Are listings treated as private user data?",
                "answer": "Provider listings are external source data, but the user's brief, ranking, feedback, documents, and decisions are account data.",
            },
            {
                "question": "Can a shared tour reveal the original listing URL?",
                "answer": "Public tours should use a narrow public manifest. Private listing URLs and exact-location evidence stay out of public tour files.",
            },
        ),
    },
    "terms": {
        "path": "/terms",
        "nav": "terms",
        "title": "Terms",
        "kicker": "Product terms",
        "summary": "Use PropertyQuarry as a research and decision-support tool. Verify property facts with official documents, the provider, and an in-person review.",
        "band": (
            {
                "title": "Decision support",
                "body": "Scores, summaries, tours, and investment views are research aids. They are not legal, financial, valuation, or survey advice.",
            },
            {
                "title": "Source boundaries",
                "body": "Provider content may be incomplete, stale, duplicated, or restricted by provider rights. The product must surface uncertainty clearly.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Use",
                "title": "Expected use",
                "body": "Users should provide truthful search settings, respect provider rights, and verify important facts before contacting, renting, buying, or investing.",
                "items": (
                    "Do not use the product to bypass provider access restrictions or scrape at abusive volume.",
                    "Do not publish private packets, documents, or generated media without the rights to do so.",
                    "Do not rely on generated visuals as measured floorplans or construction documentation.",
                ),
            },
            {
                "eyebrow": "Availability",
                "title": "Service limits",
                "body": "Search, enrichment, media generation, notifications, and provider repair can be degraded by provider outages, rate limits, source drift, and external services.",
                "items": (
                    "A completed-partial run can still be useful, but it must say which providers need another pass.",
                    "Repair attempts should be bounded and visible instead of silently consuming resources.",
                    "Unsupported providers and markets should stay marked as coming soon until verified.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "Is a score a recommendation to buy or rent?",
                "answer": "No. A score is a ranking signal based on the current brief and available evidence. The final decision remains with the user.",
            },
            {
                "question": "Can generated tours replace a viewing?",
                "answer": "No. Generated or embedded tours help screening, but dimensions, finishes, noise, light, and condition must be verified.",
            },
        ),
    },
    "imprint": {
        "path": "/imprint",
        "nav": "imprint",
        "title": "Imprint",
        "kicker": "Company information",
        "summary": "Public contact, responsible-party, and escalation information for PropertyQuarry.",
        "band": (
            {
                "title": "Responsible owner",
                "body": "PropertyQuarry is responsible for this public product surface and the property-research workflows it offers.",
            },
            {
                "title": "Contact",
                "body": "Use Support for product questions, security reports, billing questions, public sharing requests, deletion requests, and wrong-area search reports.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Responsible party",
                "title": "How to reach PropertyQuarry",
                "body": "PropertyQuarry keeps the public contact path intentionally narrow so support requests include a traceable run, account, or shared-link reference.",
                "items": (
                    "Product, billing, and account requests: /support",
                    "Security, privacy, deletion, and shared-link revocation: /support",
                    "Search repair reports: include the run ID, listing URL, provider, and the expected district or listing mode",
                ),
            },
            {
                "eyebrow": "Market boundaries",
                "title": "Jurisdiction and provider boundaries",
                "body": "PropertyQuarry is a property research and decision-support product. Provider content, public data, generated media, and investment views stay bound to their source, observation date, and disclosure limits.",
                "items": (
                    "Generated tours and summaries are screening aids, not measured surveys.",
                    "Scores rank fit against the current brief; they are not legal, financial, valuation, or safety advice.",
                    "Provider rights, availability, and market readiness can limit which sources appear in a search.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "Why is this page explicit?",
                "answer": "A paid property product needs a visible responsible-party surface, especially when it handles household preferences and shared pages.",
            },
            {
                "question": "Where should urgent data or wrong-area issues go?",
                "answer": "Use Support and include the affected URL or run ID. That gives the repair workflow enough evidence to reproduce the issue.",
            },
        ),
    },
    "support": {
        "path": "/support",
        "nav": "support",
        "title": "Support",
        "kicker": "Help",
        "summary": "Use Support for failed runs, wrong-area matches, missing facts, billing questions, deletion requests, and search repair.",
        "band": (
            {
                "title": "Run problems",
                "body": "Include the run ID, source label, candidate title, and what looked wrong: area, listing mode, price, media, packet, or repair status.",
            },
            {
                "title": "Data requests",
                "body": "Use the account surface for ordinary changes. Contact support when export, deletion, revocation, or shared-link removal needs help.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Fast triage",
                "title": "What to send",
                "body": "The fastest repair report includes the affected URL, run ID, and what looked wrong.",
                "items": (
                    "Run ID or shared property URL",
                    "Expected location, transaction mode, and hard filters",
                    "Provider URL when the source page itself contradicts the normalized result",
                ),
            },
            {
                "eyebrow": "Security",
                "title": "Sensitive reports",
                "body": "Report exposed private data, unsafe public tour assets, or account access issues as security-sensitive support items.",
                "items": (
                    "Do not paste passwords, access tokens, or full private documents into a public channel.",
                    "Ask for public share-link revocation if a link was sent to the wrong person.",
                    "Include a correlation ID from an error response when available.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "What is the best bug report for wrong-area matches?",
                "answer": "Send the selected area, the listing URL or title, the normalized postal code shown, and why that postal code should have been excluded.",
            },
            {
                "question": "What if a listing source keeps failing?",
                "answer": "Source failures should trigger bounded repair attempts and then a visible partial-coverage status if that source cannot be recovered.",
            },
        ),
    },
    "cookies": {
        "path": "/cookies",
        "nav": "cookies",
        "title": "Cookies and Analytics",
        "kicker": "Preferences",
        "summary": "PropertyQuarry should use essential cookies for sign-in and explicit analytics preferences for product measurement.",
        "band": (
            {
                "title": "Essential access",
                "body": "Session and anti-abuse cookies are required for signed-in app use and shared-link safety.",
            },
            {
                "title": "Measurement",
                "body": "Analytics should measure product reliability and funnel quality without exposing private property decisions.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Controls",
                "title": "Preference model",
                "body": "Cookie and analytics controls should be visible from Account, with Connections inside it where appropriate, and respected by public pages where legally required.",
                "items": (
                    "Separate essential access from analytics and marketing.",
                    "Keep signed-in preference changes durable across devices.",
                    "Avoid sending exact addresses, documents, or private shortlist content to analytics vendors.",
                ),
            },
        ),
        "faqs": (),
    },
    "subprocessors": {
        "path": "/subprocessors",
        "nav": "subprocessors",
        "title": "Subprocessors",
        "kicker": "Vendors",
        "summary": "PropertyQuarry integrations should be limited by purpose, data class, region, retention, usage limits, and off-switch state.",
        "band": (
            {
                "title": "Purpose-limited",
                "body": "A rendering service does not need payment data, and public pages should receive only public-safe content.",
            },
            {
                "title": "Replaceable",
                "body": "External services should sit behind stable internal interfaces so the product is not shaped by one temporary partner.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Registry",
                "title": "Service partner registry",
                "body": "Each integration should record enabled state, allowed data classes, exact-location permissions, retention, quota, health, and backup options.",
                "items": (
                    "Identity and authentication services",
                    "Email, WhatsApp, and Telegram delivery services",
                    "PDF, tour, media, analytics, and external research services",
                ),
            },
        ),
        "faqs": (),
    },
    "refunds": {
        "path": "/refunds",
        "nav": "refunds",
        "title": "Refunds and Cancellation",
        "kicker": "Billing",
        "summary": "Paid property research needs clear cancellation, failed-payment, downgrade, entitlement, and refund handling.",
        "band": (
            {
                "title": "Self-service first",
                "body": "Users should be able to see plan status, renewal, invoices, cancellation, and entitlement limits from Account, with Connections inside it where appropriate.",
            },
            {
                "title": "Usage-aware",
                "body": "Research, media generation, and provider processing have real costs, so refund policy should distinguish unused access from consumed work.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Lifecycle",
                "title": "Billing states",
                "body": "The billing system should define invoice creation, VAT handling, retries, failed payment recovery, grace periods, downgrades, and payment records.",
                "items": (
                    "Cancellation should preserve export and deletion controls.",
                    "Downgrades should keep historical results readable unless retention settings remove them.",
                    "Refund requests should be attached to plan, run, and invoice context.",
                ),
            },
        ),
        "faqs": (),
    },
    "disclaimers": {
        "path": "/disclaimers",
        "nav": "disclaimers",
        "title": "Disclaimers",
        "kicker": "Generated and inferred content",
        "summary": "Generated visuals, summaries, scores, and investment views are evidence-linked aids. They are not replacements for official documents or professional advice.",
        "band": (
            {
                "title": "Generated visualization",
                "body": "Tours and furnished previews are illustrative unless they come from a verified live provider embed. Verify dimensions, finishes, and condition.",
            },
            {
                "title": "Investment research",
                "body": "Yield, cost, risk, and neighborhood signals must distinguish observed facts, official data, third-party feeds, cached data, assumptions, and inferences.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Evidence",
                "title": "Verification required",
                "body": "PropertyQuarry should show uncertainty, missing facts, source trail, and repair status so users can decide what still needs manual review.",
                "items": (
                    "Verify price, operating costs, availability, and eligibility with the provider.",
                    "Verify legal, financial, tax, zoning, and construction questions with qualified professionals.",
                    "Treat low-confidence or partial-coverage runs as screening output, not final due diligence.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "Is an embedded Matterport or 3DVista tour generated?",
                "answer": "No. It is a provider-hosted source when available, but the listing and rights still need provider verification.",
            },
            {
                "question": "Is a generated 3D tour measured?",
                "answer": "No. It is illustrative and should be checked against official floorplans and an in-person viewing.",
            },
        ),
    },
}
