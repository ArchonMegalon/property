from __future__ import annotations

PUBLIC_NAV = (
    {"href": "/", "label": "Product", "key": "product"},
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
            {"href": "/app/properties", "label": "Results", "key": "properties"},
            {"href": "/app/search", "label": "Search", "key": "search"},
            {"href": "/app/agents", "label": "Saved searches", "key": "agents"},
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
        "body": "Capture likes, dislikes, and requirements so later searches get sharper instead of repeating the same weak matches.",
    },
)

HOW_STEPS = (
    {
        "title": "Describe the home",
        "body": "Set the market, budget, must-haves, and preferences once so every listing starts from the same brief.",
    },
    {
        "title": "Compare matching homes",
        "body": "Search selected listing sites, then compare the strongest matches with fit reasons and missing details in view.",
    },
    {
        "title": "Research before deciding",
        "body": "Open the homes that deserve attention, verify important facts, and save the next action or decision for later.",
    },
)

PERSONAS = (
    {"title": "Private search first", "body": "Start alone, see whether the matches are useful quickly, and add shared review only if the buying process really needs it."},
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
        "answer": "No. The product stays explicit about what was checked, what was enriched, and which deeper research steps are still needed.",
    },
    {
        "question": "Can I start alone and add others later?",
        "answer": "Yes. Start with a private account, then add shared review and commercial seats later from Account, with Connections inside it.",
    },
)

PRODUCT_MODULES = (
    {"title": "Property brief", "body": "Capture country, search mode, budget, household needs, and requirements once so every later search starts from the same frame."},
    {"title": "Listing-site search", "body": "Check the selected listing sites in one search instead of forcing the user to maintain separate browser rituals for every portal."},
    {"title": "Property page", "body": "Attach fit reasons, missing information, distances, and follow-up cues to each strong home."},
    {"title": "Shortlist review", "body": "Keep the best homes in one place with review links, tours, and clear next actions."},
    {"title": "Learning loop", "body": "Turn likes, dislikes, and requirements into better future matches instead of leaving them as forgotten opinions."},
    {"title": "Preferences", "body": "Keep profile, limits, integrations, and billing visible without dragging the user through unrelated assistant tooling."},
)

SIGN_IN_NOTES = (
    "Return through a current session, a secure email link, an account invite, or SSO.",
    "Use the email setup path at /register if you prefer not to start with connected sign-in.",
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
            "More site coverage",
            "Deeper property research",
            "Email alerts and search history",
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
    {"title": "Docs", "href": "/docs", "body": "Product references for search, ranking, checks, sharing, and account setup."},
    {"title": "Integrations", "href": "/integrations", "body": "Connection details for Google identity, notifications, and later delivery options."},
    {"title": "Support", "href": "/support", "body": "Help for failed runs, wrong-area matches, missing facts, billing, and deletion requests."},
)

PUBLIC_TRUST_PAGES = {
    "privacy": {
        "path": "/privacy",
        "nav": "privacy",
        "title": "Privacy",
        "kicker": "Data protection",
        "summary": "PropertyQuarry keeps search preferences, listing context, generated media, and shared links scoped to the property decision they support.",
        "band": (
            {
                "title": "Data stays contextual",
                "body": "Property preferences, shortlist decisions, uploaded documents, and delivery history are handled as property-workflow data, not generic assistant memory.",
            },
            {
                "title": "Sharing is explicit",
                "body": "Shared property pages and tour links are separate publication events. They should expose only the redacted details needed for review.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Account data",
                "title": "What the product stores",
                "body": "The app can store account identity, saved search preferences, search history, shortlist decisions, feedback, generated review files, tour history, and delivery settings.",
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
                "answer": "Listings from external sites are external content, but the user's brief, ranking, feedback, documents, and decisions are account data.",
            },
            {
                "question": "Can a shared tour reveal the original listing URL?",
                "answer": "Public tours should use a narrow public manifest. Private listing URLs and exact-location details stay out of public tour files.",
            },
        ),
    },
    "terms": {
        "path": "/terms",
        "nav": "terms",
        "title": "Terms",
        "kicker": "Product terms",
        "summary": "Use PropertyQuarry as a property research tool. Verify property facts with official documents, the listing contact, and an in-person review.",
        "band": (
            {
                "title": "Research aids",
                "body": "Scores, summaries, tours, and investment views are research aids. They are not legal, financial, valuation, or survey advice.",
            },
            {
                "title": "Listing-site boundaries",
                "body": "Listing-site content may be incomplete, stale, duplicated, or restricted by platform rights. The product must surface uncertainty clearly.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Use",
                "title": "Expected use",
                "body": "Users should provide truthful search settings, respect listing-site rights, and verify important facts before contacting, renting, buying, or investing.",
                "items": (
                    "Do not use the product to bypass listing-site access restrictions or scrape at abusive volume.",
                    "Do not publish private pages, documents, or generated media without the rights to do so.",
                    "Do not rely on generated visuals as measured floorplans or construction documentation.",
                ),
            },
            {
                "eyebrow": "Availability",
                "title": "Service limits",
                "body": "Search, enrichment, media generation, notifications, and listing-site repair can be degraded by site outages, rate limits, page changes, and external services.",
                "items": (
                    "A partial search can still be useful, but it must say which sites need another pass.",
                    "Repair attempts should be bounded and visible instead of silently consuming resources.",
                    "Unsupported sites and markets should stay marked as coming soon until they are available here.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "Is a score a recommendation to buy or rent?",
                "answer": "No. A score is a ranking signal based on your search and the available listing details. The final decision remains with the user.",
            },
            {
                "question": "Can generated tours replace a viewing?",
                "answer": "No. Generated or embedded tours help screening, but dimensions, finishes, noise, light, and condition still need a real-world check.",
            },
        ),
    },
    "imprint": {
        "path": "/imprint",
        "nav": "imprint",
        "title": "Imprint",
        "kicker": "Legal notice",
        "summary": "Contact routes and the current publication status of PropertyQuarry's legal operator details.",
        "band": (
            {
                "title": "Operator details incomplete",
                "body": "The verified legal operator name, service address, company-register details, and tax identifiers are not yet published on this surface.",
            },
            {
                "title": "Contact",
                "body": "Use Support for product questions, security reports, billing questions, public sharing requests, deletion requests, and wrong-area search reports.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Contact",
                "title": "How to reach PropertyQuarry",
                "body": "PropertyQuarry is the product name shown on this site, not a substitute for the legal operator identity. Support remains the narrow contact path while the verified operator fields are completed.",
                "items": (
                    "Product, billing, and account requests: save a signed-in Support reference to keep the account and search context attached, then email support for a reply.",
                    "Security, privacy, deletion, and shared-link revocation: email property@propertyquarry.com; a signed-in Support reference can attach safe account context first.",
                    "Search repair reports: include the search ID, listing URL, site, and the expected district or listing mode",
                ),
            },
            {
                "eyebrow": "Market boundaries",
                "title": "Jurisdiction and listing-site boundaries",
                "body": "PropertyQuarry is a property research product. Listing-site content, public data, generated media, and investment views stay bound to their origin, observation date, and disclosure limits.",
                "items": (
                    "Generated tours and summaries are screening aids, not measured surveys.",
                    "Scores rank fit against your search; they are not legal, financial, valuation, or safety advice.",
                    "Listing-site rights, availability, and market readiness can limit which sites appear in a search.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "Is this legal notice complete?",
                "answer": "No. Do not rely on it as a complete legal notice until the verified operator and registration details appear above.",
            },
            {
                "question": "Where should urgent data or wrong-area issues go?",
                "answer": "Save a Support reference with the affected URL or search ID, then email property@propertyquarry.com and include that reference.",
            },
        ),
    },
    "support": {
        "path": "/support",
        "nav": "support",
        "title": "Support",
        "kicker": "Help",
        "summary": "Sign in to save a traceable account reference for failed searches, wrong-area matches, missing facts, billing, deletion, or account access, then email support when you need a reply.",
        "band": (
            {
                "title": "Search problems",
                "body": "Include the search ID, listing site, property title, and what looked wrong: area, listing mode, price, media, review file, or repair status.",
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
                "body": "The fastest repair report includes the affected URL, search ID, and what looked wrong.",
                "items": (
                    "Search ID or shared property URL",
                    "Expected location, transaction mode, and hard filters",
                    "Original listing URL when the listing page itself contradicts the normalized result",
                ),
            },
            {
                "eyebrow": "Security",
                "title": "Sensitive reports",
                "body": "Report exposed private data, unsafe public tour assets, or account access issues as security-sensitive support items.",
                "items": (
                    "Do not paste passwords, access tokens, or full private documents into a public channel.",
                    "Do not send private share tokens or exact private addresses in an initial email.",
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
                "answer": "A failing source is retried a limited number of times. If it still cannot be reached, the search continues and shows partial coverage.",
            },
            {
                "question": "What if I cannot sign in?",
                "answer": "Email property@propertyquarry.com with a safe description and correlation ID. Do not include passwords, access tokens, private share tokens, or full documents.",
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
                "body": "Research, media generation, and listing-site processing have real costs, so refund policy should distinguish unused access from consumed work.",
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
                    "Refund requests should be attached to plan, search, and invoice context.",
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
        "summary": "Generated visuals, summaries, scores, and investment views are decision aids. They are not replacements for official documents or professional advice.",
        "band": (
            {
                "title": "Generated visualization",
                "body": "Tours and furnished images are illustrative unless they come from a live provider embed. Check dimensions, finishes, and condition in the real property.",
            },
            {
                "title": "Investment research",
                "body": "Yield, cost, risk, and neighborhood signals must distinguish observed facts, official data, third-party feeds, cached data, assumptions, and inferences.",
            },
        ),
        "sections": (
            {
                "eyebrow": "Checks",
                "title": "Check before deciding",
                "body": "PropertyQuarry should show uncertainty, missing facts, and repair status so users can decide what still needs manual review.",
                "items": (
                    "Verify price, operating costs, availability, and eligibility with the listing contact.",
                    "Verify legal, financial, tax, zoning, and construction questions with qualified professionals.",
                    "Treat low-confidence or partial-coverage runs as screening output, not final due diligence.",
                ),
            },
        ),
        "faqs": (
            {
                "question": "Is an embedded source tour generated?",
                "answer": "No. It is a source-hosted 3D tour when available, but the listing details and usage rights still come from the source.",
            },
            {
                "question": "Is a generated 3D tour measured?",
                "answer": "No. It is illustrative and should be checked against official floorplans and an in-person viewing.",
            },
        ),
    },
}
