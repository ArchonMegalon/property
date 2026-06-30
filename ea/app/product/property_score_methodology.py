from __future__ import annotations

from app.services.property_market_catalog import COUNTRIES, default_language_for_country, normalize_language_code


_LANGUAGE_NAMES = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Francais",
    "es": "Espanol",
    "it": "Italiano",
    "nl": "Nederlands",
    "pt": "Portugues",
    "pl": "Polski",
    "sv": "Svenska",
}

_PREFERENCE_TERM_REPLACEMENTS: dict[str, dict[str, str]] = {
    "de": {
        "Neutral": "Neutral",
        "Nice-to-have": "Wünschenswert",
        "Strong wish": "Starker Wunsch",
        "Must-have": "Must-have",
        "Avoid": "Vermeiden",
        "nice-to-have": "wünschenswert",
        "strong wish": "starker Wunsch",
        "must-have": "Must-have",
        "avoid": "vermeiden",
    },
    "es": {
        "Neutral": "Neutral",
        "Nice-to-have": "Deseable",
        "Strong wish": "Deseo fuerte",
        "Must-have": "Imprescindible",
        "Avoid": "Evitar",
        "nice-to-have": "deseable",
        "strong wish": "deseo fuerte",
        "must-have": "imprescindible",
        "avoid": "evitar",
    },
    "fr": {
        "Neutral": "Neutre",
        "Nice-to-have": "Souhaitable",
        "Strong wish": "Souhait fort",
        "Must-have": "Indispensable",
        "Avoid": "Eviter",
        "nice-to-have": "souhaitable",
        "strong wish": "souhait fort",
        "must-have": "indispensable",
        "avoid": "eviter",
    },
    "it": {
        "Neutral": "Neutrale",
        "Nice-to-have": "Gradito",
        "Strong wish": "Desiderio forte",
        "Must-have": "Indispensabile",
        "Avoid": "Da evitare",
        "nice-to-have": "gradito",
        "strong wish": "desiderio forte",
        "must-have": "indispensabile",
        "avoid": "da evitare",
    },
    "nl": {
        "Neutral": "Neutraal",
        "Nice-to-have": "Graag",
        "Strong wish": "Sterke wens",
        "Must-have": "Vereist",
        "Avoid": "Vermijden",
        "nice-to-have": "graag",
        "strong wish": "sterke wens",
        "must-have": "vereist",
        "avoid": "vermijden",
    },
    "pt": {
        "Neutral": "Neutro",
        "Nice-to-have": "Bom ter",
        "Strong wish": "Desejo forte",
        "Must-have": "Essencial",
        "Avoid": "Evitar",
        "nice-to-have": "bom ter",
        "strong wish": "desejo forte",
        "must-have": "essencial",
        "avoid": "evitar",
    },
    "pl": {
        "Neutral": "Neutralnie",
        "Nice-to-have": "Milo miec",
        "Strong wish": "Silne zyczenie",
        "Must-have": "Konieczne",
        "Avoid": "Unikaj",
        "nice-to-have": "milo miec",
        "strong wish": "silne zyczenie",
        "must-have": "konieczne",
        "avoid": "unikaj",
    },
    "sv": {
        "Neutral": "Neutral",
        "Nice-to-have": "Garna",
        "Strong wish": "Starkt onskemal",
        "Must-have": "Krav",
        "Avoid": "Undvik",
        "nice-to-have": "garna",
        "strong wish": "starkt onskemal",
        "must-have": "krav",
        "avoid": "undvik",
    },
}


_LOCALIZED_COPY: dict[str, dict[str, object]] = {
    "en": {
        "title": "Behind the score",
        "subtitle": "How PropertyQuarry turns a listing into a personal fit score.",
        "summary": "The score is not portal popularity. It is a 0-100 personal fit estimate built from hard eligibility, confirmed listing facts, soft preferences, route and neighbourhood evidence, missing facts, and your saved feedback.",
        "principles": [
            "Hard rules remove a listing before scoring: country, selected districts, listing mode, property type, budget, and explicit must-have rules.",
            "Soft preferences only move the score. A missing nice-to-have balcony should not hide a home; it should explain why it ranks lower.",
            "Evidence quality matters. Floorplans, real 360 tours, operating costs, energy data, and official location evidence raise confidence.",
            "Missing facts are not treated as false. They lower confidence and become questions for the viewing or agent.",
            "Saved feedback changes future ranking, but the dossier keeps the current evidence visible.",
        ],
        "steps": [
            ("1. Eligibility gate", "The engine first checks hard constraints: market, area, transaction type, property class, budget, minimum rooms or area, and explicit must-have preferences."),
            ("2. Fact extraction", "Provider pages, structured data, titles, snippets, floorplans, costs, media, and official evidence are normalized into comparable facts."),
            ("3. Personal fit", "The listing is compared with What matters: commute, daily life, school and childcare context, accessibility, outdoor space, parking, internet, risks, and household feedback."),
            ("4. Soft scoring", "Nice-to-have, strong wish, avoid, and distance preferences move the score up or down. They do not exclude unless the user marked them as a hard rule."),
            ("5. Confidence and unknowns", "Missing costs, unclear heating, no floorplan, weak location evidence, or stale provider data reduce confidence and create follow-up questions."),
            ("6. Ranking and repair", "The final rank combines personal fit, evidence confidence, freshness, duplicate handling, and repair status. Failed provider lanes are retried separately."),
        ],
        "examples": [
            ("District mismatch", "A listing in 1220 is excluded when only 1010 is selected. This is a hard rule, not a score penalty."),
            ("Balcony nice-to-have", "If balcony is nice-to-have and missing, the listing stays visible but loses score."),
            ("School route looks safe", "A safer school or kindergarten route can upgrade the score when family preferences are active."),
            ("Costs missing", "Missing operating costs lower confidence and become a follow-up question instead of silently inventing a value."),
            ("Real tour available", "A real 360 source or interactive tour improves remote-screening confidence."),
        ],
        "bands": [("0-34", "Watch only"), ("35-44", "Possible fit"), ("45-59", "Good fit"), ("60+", "Strong fit")],
        "pdf_title": "How the PropertyQuarry score is calculated",
        "candidate_title": "Score at a glance",
        "calculation_title": "Example calculation: why this property lands at 58",
        "steps_label": "Rules applied",
        "examples_label": "Examples",
        "positive_label": "Best signals",
        "negative_label": "Main caution",
        "neutral_note": "Exact weights can vary by market and search mode, but hard rules, evidence quality, soft preferences, and feedback are always separated.",
        "calculation_rows": [
            ("Start", "+50", "A candidate starts neutral once it has passed the hard gate."),
            ("Hard gate passed", "+8", "Country, rent/buy mode, property type, budget, rooms and size do not conflict. Selected area is checked as eligibility only."),
            ("Evidence quality", "+10", "Floorplan, costs and a real 360/tour source make the listing easier to verify remotely."),
            ("Soft preferences", "+6", "Daily-life, commute and family preferences fit well enough to lift rank."),
            ("Location checked", "+0", "The selected district is an eligibility check, not a reward. Central, edge, or border position inside an allowed district does not add points; only missing or contradictory location evidence hurts the score."),
            ("Missing heating detail", "-8", "Heating is still unknown, so confidence drops until it is confirmed."),
            ("One soft wish missing", "-3", "A missing nice-to-have lowers rank but does not filter the home."),
            ("Open questions", "-5", "Remaining unknowns are kept as viewing questions."),
            ("Final score", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. The rows below explain every delta and show how neutral, nice-to-have, strong wish, must-have, and avoid settings change the movement."),
        ],
    },
    "de": {
        "title": "Blick hinter den Score",
        "subtitle": "Wie PropertyQuarry aus einem Inserat eine persönliche Passung berechnet.",
        "summary": "Kurzfassung: Harte Regeln entscheiden, ob ein Objekt überhaupt in Frage kommt. Danach startet die Rechnung neutral bei 50 Punkten. Belegte Stärken heben den Score, offene Fakten und passende Gegenargumente senken ihn.",
        "principles": [
            "Harte Regeln entfernen ein Objekt vor dem Scoring: Land, Bezirk, Transaktionsart, Objekttyp, Budget und echte Must-haves.",
            "Weiche Präferenzen bewegen nur den Score. Ein fehlender Balkon als Nice-to-have versteckt kein gutes Objekt.",
            "Belegqualität zählt. Grundriss, echte 360-Tour, Betriebskosten, Energie- und Standortdaten erhöhen die Sicherheit.",
            "Fehlende Fakten gelten nicht automatisch als falsch. Sie senken Vertrauen und werden zu konkreten Fragen.",
            "Gespeichertes Feedback verändert künftige Rankings, während die aktuelle Beleglage sichtbar bleibt.",
        ],
        "steps": [
            ("1. Harte Vorauswahl", "Zuerst prüft die Engine Markt, Gebiet, Miete/Kauf, Objekttyp, Budget, Mindestgröße, Zimmer und explizite Must-haves."),
            ("2. Faktennormalisierung", "Providerseiten, strukturierte Daten, Titel, Snippets, Grundrisse, Kosten, Medien und offizielle Quellen werden vergleichbar gemacht."),
            ("3. Persönliche Passung", "Das Inserat wird gegen What matters geprüft: Wege, Alltag, Schule, Kindergarten, Barrierefreiheit, Freiraum, Parken, Internet, Risiken und Haushaltsfeedback."),
            ("4. Weiche Bewertung", "Wünsche, starke Wünsche, Vermeiden-Regeln und Distanzen bewegen den Score. Sie filtern nicht, solange sie nicht als harte Regel markiert sind."),
            ("5. Vertrauen und offene Punkte", "Fehlende Kosten, unklare Heizung, kein Grundriss, schwache Lagebelege oder veraltete Quellen senken das Vertrauen und erzeugen Rückfragen."),
            ("6. Ranking und Reparatur", "Der Rang kombiniert Passung, Evidenz, Aktualität, Duplikate und Reparaturstatus. Gescheiterte Quellen werden getrennt repariert."),
        ],
        "examples": [
            ("Falscher Bezirk", "Ein Inserat in 1220 wird ausgeschlossen, wenn nur 1010 gewählt ist. Das ist eine harte Regel."),
            ("Balkon als Wunsch", "Fehlt der Balkon nur als Wunsch, bleibt das Objekt sichtbar und verliert lediglich Score."),
            ("Sicherer Schulweg", "Ein plausibel sicherer Weg zur Schule oder zum Kindergarten kann den Score erhöhen."),
            ("Kosten fehlen", "Fehlende Betriebskosten senken Vertrauen und werden als Rueckfrage markiert, statt erfunden zu werden."),
            ("Echte Tour vorhanden", "Eine echte 360-Quelle oder interaktive Tour erhöht die Sicherheit beim Vorsortieren aus der Ferne."),
        ],
        "bands": [("0-34", "Nur beobachten"), ("35-44", "Mögliche Passung"), ("45-59", "Gute Passung"), ("60+", "Starke Passung")],
        "pdf_title": "Wie der PropertyQuarry-Score berechnet wird",
        "candidate_title": "Score-Lesart für dieses Objekt",
        "calculation_title": "Beispielrechnung: warum dieses Objekt bei 58 landet",
        "steps_label": "Angewendete Regeln",
        "examples_label": "Beispiele",
        "positive_label": "Signale, die den Score heben",
        "negative_label": "Signale, die Vertrauen oder Score senken",
        "neutral_note": "Die genaue Gewichtung kann je Markt und Suchmodus variieren, aber harte Regeln, Evidenz, weiche Präferenzen und Feedback bleiben getrennt.",
        "calculation_rows": [
            ("Start", "+50", "Ein Objekt startet neutral, sobald es die harten Regeln bestanden hat."),
            ("Harte Regeln bestanden", "+8", "Land, Miete/Kauf, Objekttyp, Budget, Zimmer und Fläche widersprechen der Suche nicht. Der gewählte Bezirk wird nur als Eignung geprüft."),
            ("Evidenzqualität", "+10", "Grundriss, Kosten und echte 360-/Tour-Quelle machen das Objekt aus der Ferne besser prüfbar."),
            ("Weiche Präferenzen", "+6", "Alltag, Wege und Familienwunsch passen gut genug, um den Rang zu heben."),
            ("Lage geprüft", "+0", "Der gewählte Bezirk ist eine harte Eignungsprüfung, keine Belohnung. Zentrum, Randlage oder Grenze innerhalb eines erlaubten Bezirks geben keine Zusatzpunkte; nur fehlende oder widersprüchliche Lageevidenz senkt den Score."),
            ("Heizung offen", "-8", "Die Heizungsinformation fehlt, daher sinkt das Vertrauen bis zur Klärung."),
            ("Ein Wunsch fehlt", "-3", "Ein fehlender Wunsch senkt nur den Rang und filtert das Objekt nicht aus."),
            ("Offenes Prüfrisiko", "-5", "Restliche Unklarheiten bleiben als Fragen für Besichtigung oder Makler sichtbar."),
            ("Endwert", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. Die Zeilen darunter erklären jedes Delta und zeigen, wie Neutral, Nice-to-have, starker Wunsch, Must-have und Avoid die Bewegung verändern."),
        ],
    },
}


_TRANSLATION_HINTS: dict[str, dict[str, object]] = {
    "es": {
        "title": "Detras de la puntuacion",
        "subtitle": "Como PropertyQuarry convierte un anuncio en una puntuacion personal.",
        "summary": "La puntuacion no mide popularidad del portal. Es una estimacion personal de 0 a 100 basada en reglas duras, datos verificados, preferencias flexibles, rutas, entorno, datos ausentes y feedback guardado.",
        "principles": [
            "Las reglas duras eliminan un anuncio antes de puntuar: pais, zonas seleccionadas, modo, tipo de inmueble, presupuesto y must-haves explicitos.",
            "Las preferencias flexibles solo mueven la puntuacion. Un balcon nice-to-have ausente no debe ocultar una vivienda.",
            "La calidad de evidencia cuenta. Planos, tours 360 reales, gastos, energia y ubicacion oficial aumentan la confianza.",
            "Los datos ausentes no se tratan como falsos. Bajan la confianza y se convierten en preguntas concretas.",
            "El feedback guardado cambia rankings futuros, pero la evidencia actual queda visible.",
        ],
        "steps": [
            ("1. Filtro de elegibilidad", "La engine comprueba mercado, zona, alquiler/compra, clase de inmueble, presupuesto, habitaciones, superficie y must-haves."),
            ("2. Extraccion de hechos", "Paginas, datos estructurados, titulos, snippets, planos, costes, medios y fuentes oficiales se normalizan."),
            ("3. Encaje personal", "El anuncio se compara con What matters: trayectos, vida diaria, colegio, guarderia, accesibilidad, exterior, aparcamiento, internet, riesgos y feedback."),
            ("4. Puntuacion flexible", "Nice-to-have, strong wish, avoid y distancias suben o bajan el score. No excluyen salvo que sean regla dura."),
            ("5. Confianza e incognitas", "Costes ausentes, calefaccion dudosa, falta de plano o ubicacion debil reducen confianza y generan preguntas."),
            ("6. Ranking y reparacion", "El ranking combina encaje, evidencia, frescura, duplicados y estado de reparacion. Fuentes fallidas se reintentan aparte."),
        ],
        "examples": [
            ("Zona equivocada", "Un anuncio en 1220 se excluye si solo 1010 esta seleccionado. Es regla dura."),
            ("Balcon nice-to-have", "Si falta un balcon deseado, la vivienda sigue visible pero baja en puntuacion."),
            ("Ruta escolar segura", "Una ruta mas segura a colegio o guarderia puede mejorar el score."),
            ("Costes ausentes", "Los gastos ausentes bajan la confianza y quedan como pregunta, no como valor inventado."),
            ("Tour real disponible", "Una fuente 360 real o un tour interactivo mejora la confianza remota."),
        ],
        "bands": [("0-34", "Solo vigilar"), ("35-44", "Encaje posible"), ("45-59", "Buen encaje"), ("60+", "Encaje fuerte")],
        "pdf_title": "Como se calcula la puntuacion de PropertyQuarry",
        "candidate_title": "Lectura de score de este inmueble",
        "positive_label": "Senales que suben el score",
        "negative_label": "Senales que bajan confianza o score",
        "neutral_note": "Los pesos exactos pueden variar por mercado y modo, pero reglas duras, evidencia, preferencias flexibles y feedback siempre estan separados.",
    },
    "fr": {
        "title": "Dans les coulisses du score",
        "subtitle": "Comment PropertyQuarry transforme une annonce en score personnel.",
        "summary": "Le score n'est pas une popularite de portail. C'est une estimation personnelle de 0 a 100 fondee sur les regles strictes, les faits verifies, les preferences souples, les trajets, le contexte local, les inconnues et le feedback memorise.",
        "principles": [
            "Les regles strictes retirent une annonce avant le calcul: pays, zones choisies, type de transaction, bien, budget et must-haves.",
            "Les preferences souples ne font que deplacer le score. Un balcon nice-to-have absent ne doit pas masquer un bien.",
            "La qualite des preuves compte. Plans, vrais tours 360, charges, energie et evidence de localisation augmentent la confiance.",
            "Les faits manquants ne sont pas consideres comme faux. Ils baissent la confiance et deviennent des questions.",
            "Le feedback enregistre influence les prochains rankings, mais les preuves actuelles restent visibles.",
        ],
        "steps": [
            ("1. Porte d'eligibilite", "Le moteur verifie marche, zone, location/achat, type, budget, surface, pieces et must-haves explicites."),
            ("2. Extraction des faits", "Pages fournisseur, donnees structurees, titres, extraits, plans, couts, medias et sources officielles sont normalises."),
            ("3. Adequation personnelle", "L'annonce est comparee a What matters: trajets, quotidien, ecole, garde, accessibilite, exterieur, parking, internet, risques et feedback."),
            ("4. Score souple", "Nice-to-have, strong wish, avoid et distances montent ou baissent le score. Ils n'excluent pas sauf regle dure."),
            ("5. Confiance et inconnues", "Charges absentes, chauffage flou, pas de plan ou localisation faible reduisent la confiance et creent des questions."),
            ("6. Ranking et reparation", "Le rang combine fit personnel, preuves, fraicheur, doublons et etat de reparation. Les sources en echec sont retentees separement."),
        ],
        "examples": [
            ("Mauvaise zone", "Une annonce en 1220 est exclue si seul 1010 est choisi. C'est une regle dure."),
            ("Balcon nice-to-have", "Si le balcon manque seulement comme souhait, le bien reste visible mais perd du score."),
            ("Trajet ecole sur", "Un trajet ecole ou garde plus sur peut augmenter le score."),
            ("Charges manquantes", "Les charges absentes baissent la confiance et deviennent une question au lieu d'etre inventees."),
            ("Vrai tour disponible", "Une vraie source 360 ou un tour interactif augmente la confiance a distance."),
        ],
        "bands": [("0-34", "A surveiller"), ("35-44", "Fit possible"), ("45-59", "Bon fit"), ("60+", "Fit fort")],
        "pdf_title": "Comment le score PropertyQuarry est calcule",
        "candidate_title": "Lecture du score de ce bien",
        "positive_label": "Signaux qui augmentent le score",
        "negative_label": "Signaux qui baissent confiance ou score",
        "neutral_note": "Les poids exacts varient selon marche et mode, mais regles strictes, preuves, preferences souples et feedback restent separes.",
    },
    "it": {
        "title": "Dietro il punteggio",
        "subtitle": "Come PropertyQuarry trasforma un annuncio in un punteggio personale.",
        "summary": "Il punteggio non e popolarita del portale. E una stima personale 0-100 basata su regole dure, fatti verificati, preferenze morbide, percorsi, contesto, fatti mancanti e feedback salvato.",
        "principles": [
            "Le regole dure eliminano un annuncio prima del punteggio: paese, zone selezionate, modalita, tipo, budget e must-have espliciti.",
            "Le preferenze morbide muovono solo il punteggio. Un balcone nice-to-have mancante non deve nascondere una casa.",
            "La qualita delle prove conta. Planimetrie, veri tour 360, costi, energia e posizione ufficiale aumentano la fiducia.",
            "I fatti mancanti non sono trattati come falsi. Abbassano la fiducia e diventano domande.",
            "Il feedback salvato modifica i ranking futuri, ma le prove correnti restano visibili.",
        ],
        "steps": [
            ("1. Filtro di idoneita", "Il motore controlla mercato, area, affitto/acquisto, classe, budget, stanze, superficie e must-have."),
            ("2. Estrazione fatti", "Pagine, dati strutturati, titoli, snippet, planimetrie, costi, media e fonti ufficiali vengono normalizzati."),
            ("3. Fit personale", "L'annuncio viene confrontato con What matters: spostamenti, vita quotidiana, scuola, asilo, accessibilita, spazi esterni, parcheggio, internet, rischi e feedback."),
            ("4. Valutazione morbida", "Nice-to-have, strong wish, avoid e distanze alzano o abbassano il score. Non escludono salvo regola dura."),
            ("5. Fiducia e incognite", "Costi mancanti, riscaldamento poco chiaro, assenza di planimetria o posizione debole riducono la fiducia e creano domande."),
            ("6. Ranking e riparazione", "Il ranking combina fit, prove, freschezza, duplicati e stato di riparazione. Le fonti fallite vengono ritentate a parte."),
        ],
        "examples": [
            ("Area sbagliata", "Un annuncio in 1220 viene escluso se e selezionato solo 1010. E una regola dura."),
            ("Balcone nice-to-have", "Se manca solo un desiderio di balcone, la casa resta visibile ma perde score."),
            ("Percorso scuola sicuro", "Un percorso piu sicuro verso scuola o asilo puo aumentare lo score."),
            ("Costi mancanti", "I costi mancanti abbassano la fiducia e diventano una domanda, non un valore inventato."),
            ("Tour reale disponibile", "Una vera fonte 360 o un tour interattivo aumenta la fiducia da remoto."),
        ],
        "bands": [("0-34", "Solo monitorare"), ("35-44", "Fit possibile"), ("45-59", "Buon fit"), ("60+", "Fit forte")],
        "pdf_title": "Come viene calcolato il punteggio PropertyQuarry",
        "candidate_title": "Lettura score di questo immobile",
        "positive_label": "Segnali che alzano lo score",
        "negative_label": "Segnali che riducono fiducia o score",
        "neutral_note": "I pesi esatti variano per mercato e modalita, ma regole dure, prove, preferenze morbide e feedback restano separati.",
    },
    "nl": {
        "title": "Achter de score",
        "subtitle": "Hoe PropertyQuarry een advertentie omzet in een persoonlijke fit-score.",
        "summary": "De score is geen portaalpopulariteit. Het is een persoonlijke 0-100 inschatting op basis van harde regels, geverifieerde feiten, zachte voorkeuren, routes, buurtcontext, ontbrekende feiten en opgeslagen feedback.",
        "principles": [
            "Harde regels verwijderen een advertentie voor scoring: land, geselecteerde gebieden, transactie, type woning, budget en expliciete must-haves.",
            "Zachte voorkeuren bewegen alleen de score. Een ontbrekend nice-to-have balkon mag een woning niet verbergen.",
            "Bewijskwaliteit telt. Plattegronden, echte 360 tours, kosten, energie en officiele locatiegegevens verhogen vertrouwen.",
            "Ontbrekende feiten gelden niet als onwaar. Ze verlagen vertrouwen en worden vragen.",
            "Opgeslagen feedback wijzigt toekomstige ranking, maar actuele evidence blijft zichtbaar.",
        ],
        "steps": [
            ("1. Geschiktheidspoort", "De engine controleert markt, gebied, huur/koop, woningklasse, budget, kamers, oppervlakte en must-haves."),
            ("2. Feitenextractie", "Providerpagina's, gestructureerde data, titels, snippets, plattegronden, kosten, media en officiele bronnen worden genormaliseerd."),
            ("3. Persoonlijke fit", "De woning wordt vergeleken met What matters: reistijd, dagelijks leven, school, opvang, toegankelijkheid, buitenruimte, parkeren, internet, risico's en feedback."),
            ("4. Zachte scoring", "Nice-to-have, strong wish, avoid en afstanden verhogen of verlagen score. Ze sluiten niet uit tenzij hard gemarkeerd."),
            ("5. Vertrouwen en onbekenden", "Ontbrekende kosten, onduidelijke verwarming, geen plattegrond of zwakke locatie-evidence verlagen vertrouwen en maken vragen."),
            ("6. Ranking en repair", "De rank combineert fit, evidence, versheid, duplicaten en repair-status. Mislukte bronnen worden apart opnieuw geprobeerd."),
        ],
        "examples": [
            ("Verkeerd gebied", "Een woning in 1220 wordt uitgesloten als alleen 1010 gekozen is. Dat is een harde regel."),
            ("Balkon nice-to-have", "Ontbreekt het balkon alleen als wens, dan blijft de woning zichtbaar maar verliest score."),
            ("Veilige schoolroute", "Een veiligere route naar school of opvang kan de score verhogen."),
            ("Kosten ontbreken", "Ontbrekende kosten verlagen vertrouwen en worden een vraag, geen verzonnen waarde."),
            ("Echte tour beschikbaar", "Een echte 360 bron of interactieve tour verhoogt remote vertrouwen."),
        ],
        "bands": [("0-34", "Alleen volgen"), ("35-44", "Mogelijke fit"), ("45-59", "Goede fit"), ("60+", "Sterke fit")],
        "pdf_title": "Hoe de PropertyQuarry-score wordt berekend",
        "candidate_title": "Scorelezing voor deze woning",
        "positive_label": "Signalen die de score verhogen",
        "negative_label": "Signalen die vertrouwen of score verlagen",
        "neutral_note": "Exacte gewichten verschillen per markt en modus, maar harde regels, evidence, zachte voorkeuren en feedback blijven gescheiden.",
    },
    "pt": {
        "title": "Por tras da pontuacao",
        "subtitle": "Como o PropertyQuarry transforma um anuncio numa pontuacao pessoal.",
        "summary": "A pontuacao nao e popularidade do portal. E uma estimativa pessoal 0-100 baseada em regras duras, factos verificados, preferencias suaves, trajetos, contexto local, factos em falta e feedback guardado.",
        "principles": [
            "Regras duras removem um anuncio antes da pontuacao: pais, zonas escolhidas, modo, tipo, orcamento e must-haves explicitos.",
            "Preferencias suaves so movem a pontuacao. Uma varanda nice-to-have em falta nao deve esconder uma casa.",
            "A qualidade da evidencia conta. Plantas, tours 360 reais, custos, energia e localizacao oficial aumentam a confianca.",
            "Factos em falta nao sao tratados como falsos. Baixam a confianca e viram perguntas.",
            "Feedback guardado altera rankings futuros, mas a evidencia atual fica visivel.",
        ],
        "steps": [
            ("1. Porta de elegibilidade", "O motor verifica mercado, zona, arrendar/comprar, classe, orcamento, quartos, area e must-haves."),
            ("2. Extracao de factos", "Paginas, dados estruturados, titulos, excertos, plantas, custos, media e fontes oficiais sao normalizados."),
            ("3. Ajuste pessoal", "O anuncio e comparado com What matters: trajetos, vida diaria, escola, creche, acessibilidade, exterior, estacionamento, internet, riscos e feedback."),
            ("4. Pontuacao suave", "Nice-to-have, strong wish, avoid e distancias sobem ou descem o score. Nao excluem salvo regra dura."),
            ("5. Confianca e desconhecidos", "Custos em falta, aquecimento incerto, sem planta ou evidencia de local fraca reduzem confianca e geram perguntas."),
            ("6. Ranking e reparacao", "O ranking combina ajuste, evidencia, frescura, duplicados e estado de reparacao. Fontes falhadas sao repetidas em separado."),
        ],
        "examples": [
            ("Zona errada", "Um anuncio em 1220 e excluido se apenas 1010 estiver selecionado. E regra dura."),
            ("Varanda nice-to-have", "Se a varanda faltar apenas como desejo, a casa continua visivel mas perde score."),
            ("Caminho escolar seguro", "Um caminho mais seguro para escola ou creche pode aumentar o score."),
            ("Custos em falta", "Custos em falta baixam a confianca e viram pergunta, nao valor inventado."),
            ("Tour real disponivel", "Uma fonte 360 real ou tour interativo aumenta a confianca remota."),
        ],
        "bands": [("0-34", "Apenas observar"), ("35-44", "Ajuste possivel"), ("45-59", "Bom ajuste"), ("60+", "Ajuste forte")],
        "pdf_title": "Como a pontuacao PropertyQuarry e calculada",
        "candidate_title": "Leitura do score deste imovel",
        "positive_label": "Sinais que elevam o score",
        "negative_label": "Sinais que reduzem confianca ou score",
        "neutral_note": "Os pesos exatos variam por mercado e modo, mas regras duras, evidencia, preferencias suaves e feedback ficam separados.",
    },
    "pl": {
        "title": "Za kulisami wyniku",
        "subtitle": "Jak PropertyQuarry zamienia ogloszenie w osobisty wynik dopasowania.",
        "summary": "Wynik nie jest popularnoscia portalu. To osobista ocena 0-100 oparta o twarde reguly, zweryfikowane fakty, miekkie preferencje, trasy, otoczenie, brakujace fakty i zapisany feedback.",
        "principles": [
            "Twarde reguly usuwaja ogloszenie przed scoringiem: kraj, wybrane obszary, tryb, typ nieruchomosci, budzet i must-have.",
            "Miekkie preferencje tylko przesuwaja wynik. Brak balkonu nice-to-have nie powinien ukrywac mieszkania.",
            "Jakosc dowodow ma znaczenie. Plany, prawdziwe 360, koszty, energia i oficjalna lokalizacja zwiekszaja zaufanie.",
            "Brakujace fakty nie sa traktowane jako falsz. Obnizaja zaufanie i staja sie pytaniami.",
            "Zapisany feedback zmienia przyszle rankingi, ale aktualne dowody pozostaja widoczne.",
        ],
        "steps": [
            ("1. Bramka kwalifikacji", "Silnik sprawdza rynek, obszar, najem/zakup, klase, budzet, pokoje, metraz i must-have."),
            ("2. Ekstrakcja faktow", "Strony, dane strukturalne, tytuly, fragmenty, plany, koszty, media i zrodla oficjalne sa normalizowane."),
            ("3. Osobiste dopasowanie", "Ogloszenie jest porownywane z What matters: dojazd, codziennosc, szkola, przedszkole, dostepnosc, zewnetrze, parking, internet, ryzyka i feedback."),
            ("4. Miekki scoring", "Nice-to-have, strong wish, avoid i odleglosci podnosza lub obnizaja score. Nie wykluczaja bez twardej reguly."),
            ("5. Zaufanie i niewiadome", "Brak kosztow, niejasne ogrzewanie, brak planu lub slaba lokalizacja obnizaja zaufanie i tworza pytania."),
            ("6. Ranking i naprawa", "Ranking laczy fit, dowody, swiezosc, duplikaty i status naprawy. Zrodla z bledem sa ponawiane oddzielnie."),
        ],
        "examples": [
            ("Zly obszar", "Ogloszenie w 1220 jest wykluczone, gdy wybrano tylko 1010. To twarda regula."),
            ("Balkon nice-to-have", "Jesli balkon jest tylko zyczeniem, oferta zostaje widoczna, ale traci score."),
            ("Bezpieczna droga do szkoly", "Bezpieczniejsza trasa do szkoly lub przedszkola moze podniesc score."),
            ("Brak kosztow", "Brakujace koszty obnizaja zaufanie i sa pytaniem, nie wymyslona wartoscia."),
            ("Prawdziwy tour dostepny", "Prawdziwe 360 lub interaktywny tour zwieksza zaufanie zdalne."),
        ],
        "bands": [("0-34", "Tylko obserwuj"), ("35-44", "Mozliwe dopasowanie"), ("45-59", "Dobre dopasowanie"), ("60+", "Silne dopasowanie")],
        "pdf_title": "Jak obliczany jest wynik PropertyQuarry",
        "candidate_title": "Odczyt wyniku tej nieruchomosci",
        "positive_label": "Sygnaly podnoszace wynik",
        "negative_label": "Sygnaly obnizajace zaufanie lub wynik",
        "neutral_note": "Dokladne wagi roznia sie wedlug rynku i trybu, ale twarde reguly, dowody, miekkie preferencje i feedback pozostaja oddzielone.",
    },
    "sv": {
        "title": "Bakom poangen",
        "subtitle": "Hur PropertyQuarry omvandlar en annons till ett personligt matchningsbetyg.",
        "summary": "Poangen ar inte portalpopularitet. Det ar en personlig 0-100 bedomning byggd pa harda regler, verifierade fakta, mjuka preferenser, rutter, omgivning, saknade fakta och sparad feedback.",
        "principles": [
            "Harda regler tar bort en annons fore scoring: land, valda omraden, transaktion, bostadstyp, budget och explicita must-haves.",
            "Mjuka preferenser flyttar bara poangen. En saknad nice-to-have balkong ska inte gomma en bostad.",
            "Beviskvalitet raknas. Planritning, riktig 360, kostnader, energi och officiell platsdata hojer fortroendet.",
            "Saknade fakta ses inte som falska. De sanker fortroendet och blir fragor.",
            "Sparad feedback andrar framtida ranking, men aktuell evidens forblir synlig.",
        ],
        "steps": [
            ("1. Kvalificeringsport", "Motorn kontrollerar marknad, omrade, hyra/kop, bostadsklass, budget, rum, yta och must-haves."),
            ("2. Faktaextraktion", "Leverantorssidor, strukturerad data, titlar, snippets, planritningar, kostnader, media och officiella kallor normaliseras."),
            ("3. Personlig matchning", "Annonsen jamfors med What matters: pendling, vardag, skola, forskola, tillganglighet, utemiljo, parkering, internet, risker och feedback."),
            ("4. Mjuk scoring", "Nice-to-have, strong wish, avoid och avstand hojer eller sanker score. De exkluderar inte om de inte ar hard regel."),
            ("5. Fortroende och okanda", "Saknade kostnader, oklar varme, ingen planritning eller svag platsdata sanker fortroendet och skapar fragor."),
            ("6. Ranking och reparation", "Rankingen kombinerar personlig fit, evidens, aktualitet, duplicering och reparationsstatus. Misslyckade kallor provas om separat."),
        ],
        "examples": [
            ("Fel omrade", "En annons i 1220 utesluts om endast 1010 ar valt. Det ar en hard regel."),
            ("Balkong nice-to-have", "Om balkong bara ar ett onskemal ligger bostaden kvar men tappar score."),
            ("Saker skolrutt", "En sakrare vag till skola eller forskola kan hoja score."),
            ("Kostnader saknas", "Saknade kostnader sanker fortroende och blir en fraga, inte ett pahittat varde."),
            ("Riktig tour finns", "En riktig 360-kalla eller interaktiv tour hojer fjarrgranskningsfortroendet."),
        ],
        "bands": [("0-34", "Bara bevaka"), ("35-44", "Mojlig match"), ("45-59", "Bra match"), ("60+", "Stark match")],
        "pdf_title": "Hur PropertyQuarry-poangen beraknas",
        "candidate_title": "Score-lasning for denna bostad",
        "positive_label": "Signaler som hojer score",
        "negative_label": "Signaler som sanker fortroende eller score",
        "neutral_note": "Exakta vikter varierar med marknad och lage, men harda regler, evidens, mjuka preferenser och feedback halles isar.",
    },
}


_LOCALIZED_CALCULATION_COPY: dict[str, dict[str, object]] = {
    "es": {
        "calculation_title": "Calculo de ejemplo: por que esta vivienda llega a 58",
        "steps_label": "Reglas aplicadas",
        "examples_label": "Ejemplos",
        "calculation_rows": [
            ("Inicio", "+50", "La vivienda empieza neutral cuando supera las reglas duras."),
            ("Reglas duras superadas", "+8", "Pais, zona, alquiler/compra, tipo, presupuesto, habitaciones y superficie no contradicen la busqueda."),
            ("Calidad de evidencia", "+10", "Plano, gastos y una fuente 360/tour real hacen la vivienda mas verificable a distancia."),
            ("Preferencias flexibles", "+6", "Vida diaria, trayectos y preferencias familiares encajan lo suficiente para subir el rango."),
            ("Ubicacion verificada", "+0", "La zona elegida es una regla de elegibilidad, no una recompensa. Solo penaliza si falta evidencia o contradice la zona."),
            ("Calefaccion pendiente", "-8", "La calefaccion sigue sin confirmar, asi que baja la confianza."),
            ("Un deseo falta", "-3", "Un deseo ausente baja el rango, pero no filtra la vivienda."),
            ("Riesgo abierto", "-5", "Las incognitas restantes quedan como preguntas de visita."),
            ("Resultado", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. Las filas siguientes explican cada delta y como Neutral, Nice-to-have, Strong wish, Must-have y Avoid cambian el movimiento."),
        ],
    },
    "fr": {
        "calculation_title": "Calcul d'exemple: pourquoi ce bien arrive a 58",
        "steps_label": "Regles appliquees",
        "examples_label": "Exemples",
        "calculation_rows": [
            ("Depart", "+50", "Le bien commence neutre apres avoir passe les regles strictes."),
            ("Regles strictes passees", "+8", "Pays, zone, location/achat, type, budget, pieces et surface ne contredisent pas la recherche."),
            ("Qualite des preuves", "+10", "Plan, charges et vraie source 360/tour rendent le bien plus verifiable a distance."),
            ("Preferences souples", "+6", "Quotidien, trajets et preferences familiales correspondent assez pour relever le rang."),
            ("Localisation verifiee", "+0", "La zone choisie est une regle d'eligibilite, pas une recompense. Seule une preuve absente ou contradictoire penalise."),
            ("Chauffage inconnu", "-8", "Le chauffage reste a confirmer, donc la confiance baisse."),
            ("Un souhait manque", "-3", "Un souhait manquant baisse le rang, mais ne filtre pas le bien."),
            ("Risque a verifier", "-5", "Les inconnues restantes deviennent des questions de visite."),
            ("Resultat", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. Les lignes suivantes expliquent chaque delta et comment Neutral, Nice-to-have, Strong wish, Must-have et Avoid changent le mouvement."),
        ],
    },
    "it": {
        "calculation_title": "Calcolo di esempio: perche questa casa arriva a 58",
        "steps_label": "Regole applicate",
        "examples_label": "Esempi",
        "calculation_rows": [
            ("Inizio", "+50", "La casa parte neutra dopo aver superato le regole dure."),
            ("Regole dure superate", "+8", "Paese, area, affitto/acquisto, tipo, budget, stanze e superficie non sono in conflitto."),
            ("Qualita prove", "+10", "Planimetria, costi e una vera fonte 360/tour rendono la casa piu verificabile da remoto."),
            ("Preferenze morbide", "+6", "Vita quotidiana, spostamenti e preferenze familiari alzano abbastanza il rango."),
            ("Posizione verificata", "+0", "L'area scelta e una regola di idoneita, non un premio. Penalizza solo se la prova manca o contraddice l'area."),
            ("Riscaldamento aperto", "-8", "Il riscaldamento e ancora da confermare, quindi la fiducia scende."),
            ("Un desiderio manca", "-3", "Un desiderio mancante abbassa il rango, ma non filtra la casa."),
            ("Rischio da verificare", "-5", "Le incognite restanti diventano domande per la visita."),
            ("Risultato", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. Le righe seguenti spiegano ogni delta e come Neutral, Nice-to-have, Strong wish, Must-have e Avoid cambiano il movimento."),
        ],
    },
    "nl": {
        "calculation_title": "Voorbeeldberekening: waarom deze woning op 58 uitkomt",
        "steps_label": "Toegepaste regels",
        "examples_label": "Voorbeelden",
        "calculation_rows": [
            ("Start", "+50", "De woning start neutraal zodra de harde regels zijn gehaald."),
            ("Harde regels gehaald", "+8", "Land, gebied, huur/koop, type, budget, kamers en oppervlakte spreken de zoekopdracht niet tegen."),
            ("Bewijskwaliteit", "+10", "Plattegrond, kosten en een echte 360/tourbron maken de woning beter op afstand te controleren."),
            ("Zachte voorkeuren", "+6", "Dagelijks leven, routes en gezinsvoorkeuren passen goed genoeg om de rang te verhogen."),
            ("Locatie gecontroleerd", "+0", "Het gekozen gebied is een harde geschiktheidscheck, geen beloning. Alleen ontbrekend of tegenstrijdig locatiebewijs verlaagt de score."),
            ("Verwarming open", "-8", "De verwarming is nog onbekend, dus vertrouwen daalt tot verificatie."),
            ("Een wens ontbreekt", "-3", "Een ontbrekende wens verlaagt de rang, maar filtert de woning niet."),
            ("Open verificatierisico", "-5", "Resterende onbekenden blijven als kijkvragen staan."),
            ("Eindscore", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. De rijen hieronder leggen elke delta uit en hoe Neutral, Nice-to-have, Strong wish, Must-have en Avoid de beweging veranderen."),
        ],
    },
    "pt": {
        "calculation_title": "Calculo de exemplo: porque esta casa chega a 58",
        "steps_label": "Regras aplicadas",
        "examples_label": "Exemplos",
        "calculation_rows": [
            ("Inicio", "+50", "A casa comeca neutra depois de passar as regras duras."),
            ("Regras duras cumpridas", "+8", "Pais, zona, arrendar/comprar, tipo, orcamento, quartos e area nao entram em conflito."),
            ("Qualidade da evidencia", "+10", "Planta, custos e uma fonte 360/tour real tornam a casa mais verificavel remotamente."),
            ("Preferencias suaves", "+6", "Vida diaria, trajetos e preferencias familiares encaixam o suficiente para subir o ranking."),
            ("Localizacao verificada", "+0", "A zona escolhida e uma regra de elegibilidade, nao uma recompensa. So penaliza se a evidencia faltar ou contradizer a zona."),
            ("Aquecimento em aberto", "-8", "O aquecimento ainda precisa de confirmacao, entao a confianca baixa."),
            ("Um desejo falta", "-3", "Um desejo em falta baixa o ranking, mas nao filtra a casa."),
            ("Risco a verificar", "-5", "As restantes incertezas ficam como perguntas de visita."),
            ("Resultado", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. As linhas abaixo explicam cada delta e como Neutral, Nice-to-have, Strong wish, Must-have e Avoid mudam o movimento."),
        ],
    },
    "pl": {
        "calculation_title": "Przykladowe obliczenie: dlaczego ta nieruchomosc ma 58",
        "steps_label": "Zastosowane reguly",
        "examples_label": "Przyklady",
        "calculation_rows": [
            ("Start", "+50", "Nieruchomosc startuje neutralnie po przejsciu twardych regul."),
            ("Twarde reguly spelnione", "+8", "Kraj, obszar, najem/zakup, typ, budzet, pokoje i metraz nie kloca sie z wyszukiwaniem."),
            ("Jakosc dowodow", "+10", "Plan, koszty i prawdziwe 360/tour ulatwiaja zdalna weryfikacje."),
            ("Miekkie preferencje", "+6", "Codziennosc, dojazdy i potrzeby rodzinne pasuja na tyle, by podniesc ranking."),
            ("Lokalizacja sprawdzona", "+0", "Wybrany obszar to twarda regola kwalifikacji, nie nagroda. Brak lub sprzecznosc dowodu obniza wynik."),
            ("Ogrzewanie otwarte", "-8", "Ogrzewanie nadal wymaga potwierdzenia, wiec zaufanie spada."),
            ("Brakuje jednego zyczenia", "-3", "Brak zyczenia obniza ranking, ale nie filtruje oferty."),
            ("Otwarte ryzyko", "-5", "Pozostale niewiadome zostaja pytaniami na ogladanie."),
            ("Wynik koncowy", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. Wiersze ponizej wyjasniaja kazda delte i jak Neutral, Nice-to-have, Strong wish, Must-have oraz Avoid zmieniaja ruch."),
        ],
    },
    "sv": {
        "calculation_title": "Exempelberakning: varfor bostaden landar pa 58",
        "steps_label": "Tillampade regler",
        "examples_label": "Exempel",
        "calculation_rows": [
            ("Start", "+50", "Bostaden startar neutralt nar den passerat de harda reglerna."),
            ("Harda regler passerade", "+8", "Land, omrade, hyra/kop, typ, budget, rum och yta motsager inte sokningen."),
            ("Evidenskvalitet", "+10", "Planritning, kostnader och riktig 360/tour-kalla gor bostaden lattare att fjarrverifiera."),
            ("Mjuka preferenser", "+6", "Vardag, rutter och familjepreferenser passar nog for att hoja rankingen."),
            ("Plats kontrollerad", "+0", "Valt omrade ar en hard behorighetsregel, inte en bonus. Endast saknad eller motsagd platsevidens sanker score."),
            ("Varme okand", "-8", "Varmeinformation saknas fortfarande, sa fortroendet sjunker."),
            ("Ett onskemal saknas", "-3", "Ett saknat onskemal sanker rang men filtrerar inte bort bostaden."),
            ("Oppen verifieringsrisk", "-5", "Kvarvarande okanda blir fragor vid visning."),
            ("Slutpoang", "=58", "50 + 8 + 10 + 6 + 0 - 8 - 3 - 5 = 58. Raderna nedan forklarar varje delta och hur Neutral, Nice-to-have, Strong wish, Must-have och Avoid andrar rorelsen."),
        ],
    },
}


_LOCALIZED_PDF_EXAMPLE_COPY: dict[str, dict[str, tuple[str, ...] | str]] = {
    "en": {
        "source_label": "PropertyQuarry scoring engine",
        "recommendation": "Strong fit",
        "match_reasons": (
            "Selected area is respected.",
            "Confirmed costs, floorplan, and 360 evidence raise confidence.",
            "Commute and daily-life preferences score well.",
        ),
        "mismatch_reasons": (
            "One soft preference is missing and lowers rank without excluding.",
            "Heating detail still needs confirmation before a final decision.",
        ),
        "viewing_questions": (
            "Check the remaining gap with the agent.",
            "Compare the route and noise evidence during an actual viewing.",
        ),
        "postal_name": "Demo market",
        "price_display": "Example budget",
    },
    "de": {
        "source_label": "PropertyQuarry-Scoring-Engine",
        "recommendation": "Starke Passung",
        "match_reasons": (
            "Das ausgewählte Gebiet wird respektiert.",
            "Belegte Kosten, Grundriss und 360-Evidenz erhöhen das Vertrauen.",
            "Wege und Alltagspräferenzen schneiden gut ab.",
        ),
        "mismatch_reasons": (
            "Ein weicher Wunsch fehlt und senkt den Rang ohne Ausschluss.",
            "Das Heizungsdetail muss vor der finalen Entscheidung bestätigt werden.",
        ),
        "viewing_questions": (
            "Den noch fehlenden Fakt mit Makler oder Anbieter bestätigen.",
            "Weg- und Lärmbelege bei einer echten Besichtigung vergleichen.",
        ),
        "postal_name": "Demomarkt",
        "price_display": "Beispielbudget",
    },
    "es": {
        "source_label": "Motor de puntuacion PropertyQuarry",
        "recommendation": "Encaje fuerte",
        "match_reasons": (
            "La zona seleccionada se respeta.",
            "Costes verificados, plano y evidencia 360 aumentan la confianza.",
            "Trayectos y preferencias diarias puntuan bien.",
        ),
        "mismatch_reasons": (
            "Falta una preferencia flexible y baja el rango sin excluir.",
            "La calefaccion necesita confirmacion antes de decidir.",
        ),
        "viewing_questions": (
            "Verificar el dato pendiente con el agente.",
            "Comparar ruta y ruido durante una visita real.",
        ),
        "postal_name": "Mercado demo",
        "price_display": "Presupuesto de ejemplo",
    },
    "fr": {
        "source_label": "Moteur de score PropertyQuarry",
        "recommendation": "Fit fort",
        "match_reasons": (
            "La zone choisie est respectee.",
            "Charges verifiees, plan et preuve 360 augmentent la confiance.",
            "Trajets et preferences du quotidien scorent bien.",
        ),
        "mismatch_reasons": (
            "Une preference souple manque et baisse le rang sans exclure.",
            "Le chauffage doit encore etre confirme avant decision.",
        ),
        "viewing_questions": (
            "Verifier le fait manquant avec l'agent.",
            "Comparer trajet et bruit pendant une vraie visite.",
        ),
        "postal_name": "Marche demo",
        "price_display": "Budget d'exemple",
    },
    "it": {
        "source_label": "Motore di scoring PropertyQuarry",
        "recommendation": "Fit forte",
        "match_reasons": (
            "L'area selezionata e rispettata.",
            "Costi verificati, planimetria e 360 aumentano la fiducia.",
            "Spostamenti e preferenze quotidiane hanno buon punteggio.",
        ),
        "mismatch_reasons": (
            "Manca una preferenza morbida e abbassa il rango senza escludere.",
            "Il riscaldamento va ancora confermato prima della decisione.",
        ),
        "viewing_questions": (
            "Verificare il fatto mancante con l'agente.",
            "Confrontare percorso e rumore durante una visita reale.",
        ),
        "postal_name": "Mercato demo",
        "price_display": "Budget di esempio",
    },
    "nl": {
        "source_label": "PropertyQuarry score-engine",
        "recommendation": "Sterke fit",
        "match_reasons": (
            "Het geselecteerde gebied wordt gerespecteerd.",
            "Geverifieerde kosten, plattegrond en 360-evidence verhogen vertrouwen.",
            "Route- en dagelijkse voorkeuren scoren goed.",
        ),
        "mismatch_reasons": (
            "Een zachte voorkeur ontbreekt en verlaagt rang zonder uitsluiting.",
            "Verwarming moet nog bevestigd worden voor een eindbesluit.",
        ),
        "viewing_questions": (
            "Verifieer het ontbrekende feit met de makelaar.",
            "Vergelijk route- en geluidsevidence tijdens een echte bezichtiging.",
        ),
        "postal_name": "Demomarkt",
        "price_display": "Voorbeeldbudget",
    },
    "pt": {
        "source_label": "Motor de pontuacao PropertyQuarry",
        "recommendation": "Ajuste forte",
        "match_reasons": (
            "A zona selecionada e respeitada.",
            "Custos verificados, planta e evidencia 360 aumentam a confianca.",
            "Trajetos e preferencias diarias pontuam bem.",
        ),
        "mismatch_reasons": (
            "Falta uma preferencia suave e baixa o ranking sem excluir.",
            "O aquecimento ainda precisa de confirmacao antes da decisao.",
        ),
        "viewing_questions": (
            "Confirmar o facto em falta com o agente.",
            "Comparar trajeto e ruido numa visita real.",
        ),
        "postal_name": "Mercado demo",
        "price_display": "Orcamento de exemplo",
    },
    "pl": {
        "source_label": "Silnik scoringowy PropertyQuarry",
        "recommendation": "Silne dopasowanie",
        "match_reasons": (
            "Wybrany obszar jest respektowany.",
            "Zweryfikowane koszty, plan i 360 zwiekszaja zaufanie.",
            "Dojazdy i codzienne preferencje wypadaja dobrze.",
        ),
        "mismatch_reasons": (
            "Brakuje jednej miekkiej preferencji i obniza ranking bez wykluczenia.",
            "Ogrzewanie trzeba jeszcze potwierdzic przed decyzja.",
        ),
        "viewing_questions": (
            "Potwierdz brakujacy fakt z agentem.",
            "Porownaj droge i halas podczas prawdziwego ogladania.",
        ),
        "postal_name": "Rynek demo",
        "price_display": "Przykladowy budzet",
    },
    "sv": {
        "source_label": "PropertyQuarry scoringmotor",
        "recommendation": "Stark match",
        "match_reasons": (
            "Valt omrade respekteras.",
            "Verifierade kostnader, planritning och 360-evidens hojer fortroendet.",
            "Pendling och vardagspreferenser scorer bra.",
        ),
        "mismatch_reasons": (
            "En mjuk preferens saknas och sanker rang utan att exkludera.",
            "Varmeuppgift maste fortfarande bekraftas fore beslut.",
        ),
        "viewing_questions": (
            "Verifiera den saknade uppgiften med maklaren.",
            "Jamfor rutt- och bullerevidens vid en riktig visning.",
        ),
        "postal_name": "Demomarknad",
        "price_display": "Exempelbudget",
    },
}


_LOCALIZED_WEIGHT_EXPLAINER_COPY: dict[str, dict[str, object]] = {
    "en": {
        "calculation_detail_title": "Where each number comes from",
        "calculation_detail_note": "The example uses the same scoring ladder as the search engine: hard rules gate first, then evidence and soft preferences move the visible rank.",
        "weight_ladder_title": "How preference strength changes a delta",
        "weight_ladder_note": "A stronger preference changes the size of the score move. It does not become a filter unless the user marks it as a must-have or explicit hard rule.",
        "weight_ladder_rows": [
            ("Neutral", "+0 / -0", "The signal is shown as context but normally does not move the score."),
            ("Nice to have", "small move", "A matched nice-to-have usually adds a small lift; a missing one causes a small penalty."),
            ("Strong wish", "larger move", "The same matched signal receives a larger boost, and the same missing signal costs more."),
            ("Must have", "gate or cap", "If the fact contradicts the must-have, the listing is filtered or score-capped instead of merely lowered."),
            ("Avoid", "negative move", "If the avoided condition is present, the score drops; only explicit hard avoid rules exclude."),
        ],
        "source_sections_label": "Where the information comes from",
        "source_sections": [
            ("Listing pages", "Provider pages, structured data, titles, snippets, photos, floorplans, costs, availability, and source 360 links are extracted and normalized. Unsupported claims stay open questions."),
            ("Official geo data", "Official sources such as data.gv.at, climate maps, air-quality, noise, flood, broadband, school, childcare, and other public datasets are attached as evidence lanes when they cover the location."),
            ("Maps and routes", "OpenStreetMap/Overpass, route checks, and distance calculations turn errands, transit, schools, parks, shade, and services into comparable proximity facts."),
            ("User preferences", "What Matters settings and saved feedback decide whether a fact is neutral, a wish, a strong wish, a must-have, or an avoid signal."),
            ("How facts are checked", "Prices, costs, energy data, tours, floorplans, and location facts are promoted only when source evidence supports them. Missing evidence lowers confidence instead of being invented."),
        ],
        "calculation_detail_rows": [
            ("Start", "+50", "Neutral baseline after hard-gate eligibility.", "Every reviewable candidate starts from 50 so positive and negative evidence can both move it.", "Preference strength does not change the baseline."),
            ("Hard gate passed", "+8", "Country, transaction type, home type, budget, rooms and area do not conflict; selected district is only a pass/fail gate.", "This is an eligibility confidence lift, not a soft preference or district reward.", "If a selected district, buy/rent mode, budget, rooms or hard type fails, the candidate is excluded instead of scored."),
            ("Evidence quality", "+10", "Floorplan, operating costs and real 360/tour evidence are available in the example.", "More confirmed facts make the remote decision safer, so confidence rises.", "Floorplan only would be closer to +4; floorplan plus costs closer to +7; full evidence earns the +10 example."),
            ("Soft preferences", "+6", "Commute, daily-life and family preferences match at nice-to-have strength.", "Soft matches raise rank but never hide other homes by themselves.", "Neutral would be +0; nice-to-have gives about +6 here; strong wish would be about +12; a must-have contradiction would gate or cap."),
            ("Location checked", "+0", "The listing has candidate-level postal or district evidence, not only provider search-scope text.", "Specific location evidence checks eligibility and nearby context. Being central, at the edge, or on a border inside an allowed district is not rewarded.", "Coarse evidence stays neutral; a contradicted postal code such as 1220 during a hard 1010 search excludes."),
            ("Missing heating detail", "-8", "Heating is relevant but unknown in the reviewed source.", "Missing facts are not invented; important unknowns reduce confidence until they are confirmed.", "If heating detail were neutral it might be -2 or 0; as a strong wish it can be -8 to -12; as a hard must-have it can cap or exclude."),
            ("One soft wish missing", "-3", "A non-critical desired feature is absent or unproven.", "A soft miss lowers rank only.", "Neutral would be 0; nice-to-have is about -3; strong wish about -6; must-have missing would gate or cap."),
            ("Open questions", "-5", "There are still unresolved viewing or agent questions.", "The score keeps uncertainty visible instead of pretending the listing is complete.", "Minor risk would be about -2; unresolved important risk about -5; high risk can cap below the strong-fit band."),
        ],
    },
    "de": {
        "calculation_detail_title": "Wo jede Zahl herkommt",
        "calculation_detail_note": "Das Beispiel nutzt dieselbe Logik wie die Suche: harte Regeln zuerst, danach bewegen Evidenz und weiche Präferenzen den sichtbaren Rang.",
        "weight_ladder_title": "Wie die Präferenzstärke ein Delta verändert",
        "weight_ladder_note": "Eine stärkere Präferenz verändert die Höhe des Score-Schritts. Sie wird erst dann zum Filter, wenn sie als Must-have oder harte Regel markiert ist.",
        "weight_ladder_rows": [
            ("Neutral", "+0 / -0", "Das Signal bleibt Kontext und bewegt den Score normalerweise nicht."),
            ("Nice to have", "kleiner Schritt", "Ein Treffer hebt leicht; ein fehlender Wunsch senkt leicht."),
            ("Starker Wunsch", "größerer Schritt", "Dasselbe passende Signal zählt stärker, und dasselbe fehlende Signal kostet mehr."),
            ("Must-have", "Filter oder Deckel", "Widerspricht der Fakt dem Must-have, wird gefiltert oder gedeckelt statt nur gesenkt."),
            ("Avoid", "negativer Schritt", "Ist das zu vermeidende Merkmal vorhanden, sinkt der Score; nur harte Avoid-Regeln schließen aus."),
        ],
        "source_sections_label": "Woher die Informationen kommen",
        "source_sections": [
            ("Inserate", "Providerseiten, strukturierte Daten, Titel, Kurztexte, Fotos, Grundrisse, Kosten, Verfügbarkeit und 360-Links werden extrahiert und normalisiert. Nicht belegte Aussagen bleiben offene Fragen."),
            ("Offizielle Geodaten", "Offizielle Quellen wie data.gv.at, Stadtklimakarten, Luftgüte, Lärm, Hochwasser, Breitband, Schulen, Kindergarten und weitere öffentliche Datensätze werden als Evidenz-Lanes angehängt, wenn sie den Standort abdecken."),
            ("Karten und Wege", "OpenStreetMap/Overpass, Routenprüfungen und Distanzen machen Alltag, Öffis, Schulen, Parks, Schatten und Services vergleichbar."),
            ("Nutzerwünsche", "What Matters und gespeichertes Feedback bestimmen, ob ein Fakt neutral, Wunsch, starker Wunsch, Must-have oder Avoid-Signal ist."),
            ("Prüfregeln", "Preise, Kosten, Energie, Touren, Grundrisse und Lagefakten werden nur hervorgehoben, wenn die Quelle sie stützt. Fehlende Evidenz senkt Vertrauen, statt erfunden zu werden."),
        ],
        "calculation_detail_rows": [
            ("Start", "+50", "Neutraler Ausgangswert nach bestandener harter Vorauswahl.", "Jedes prüfbare Objekt startet bei 50, damit positive und negative Evidenz wirken können.", "Die Präferenzstärke verändert den Startwert nicht."),
            ("Harte Regeln bestanden", "+8", "Land, Miete/Kauf, Objekttyp, Budget, Zimmer und Fläche widersprechen nicht; der ausgewählte Bezirk ist nur ein Ja/Nein-Gate.", "Das ist ein Eligibility-Boost, keine weiche Präferenz und keine Bezirksbelohnung.", "Wenn Bezirk, Modus, Budget, Zimmer oder harter Typ scheitern, wird ausgeschlossen statt niedriger bewertet."),
            ("Evidenzqualität", "+10", "Im Beispiel sind Grundriss, Betriebskosten und echte 360-/Tour-Evidenz vorhanden.", "Mehr belegte Fakten machen die Remote-Entscheidung sicherer, daher steigt das Vertrauen.", "Nur Grundriss wäre eher +4; Grundriss plus Kosten eher +7; volle Evidenz ergibt hier +10."),
            ("Weiche Präferenzen", "+6", "Wege, Alltag und Familienkontext passen auf Nice-to-have-Stärke.", "Weiche Treffer heben den Rang, verstecken aber keine anderen Objekte.", "Neutral wäre +0; Nice-to-have hier etwa +6; starker Wunsch etwa +12; Must-have-Widerspruch würde filtern oder deckeln."),
            ("Lage geprüft", "+0", "Die Lage stammt aus Objekt-Postleitzahl oder Bezirk, nicht nur aus dem Suchumfang des Providers.", "Konkrete Lagebelege prüfen Eignung und Umfeld. Zentrum, Randlage oder Bezirksgrenze innerhalb eines erlaubten Bezirks werden nicht belohnt.", "Grobe Evidenz bleibt neutral; eine widersprechende PLZ wie 1220 bei harter Suche 1010 schließt aus."),
            ("Heizung offen", "-8", "Heizung ist relevant, aber in der Quelle unbekannt.", "Fehlende Fakten werden nicht erfunden; wichtige Unbekannte senken Vertrauen bis zur Klärung.", "Neutral wäre eher -2 oder 0; als starker Wunsch -8 bis -12; als hartes Must-have Deckel oder Ausschluss."),
            ("Ein Wunsch fehlt", "-3", "Ein nicht kritisches Wunschmerkmal fehlt oder ist nicht belegt.", "Ein weicher Fehltreffer senkt nur den Rang.", "Neutral wäre 0; Nice-to-have etwa -3; starker Wunsch etwa -6; fehlendes Must-have würde filtern oder deckeln."),
            ("Offenes Prüfrisiko", "-5", "Es bleiben offene Fragen für Besichtigung oder Anbieter.", "Der Score macht Unsicherheit sichtbar, statt Vollständigkeit vorzutäuschen.", "Kleines Risiko wäre etwa -2; wichtiges offenes Risiko etwa -5; hohes Risiko kann unter die starke Passung deckeln."),
        ],
    },
    "es": {
        "calculation_detail_title": "De donde sale cada numero",
        "calculation_detail_note": "El ejemplo usa la misma escalera que la busqueda: reglas duras primero, luego evidencia y preferencias flexibles mueven el rango visible.",
        "weight_ladder_title": "Como cambia el delta segun la fuerza",
        "weight_ladder_note": "Una preferencia mas fuerte cambia el tamano del movimiento. Solo filtra si el usuario la marca como must-have o regla dura.",
        "weight_ladder_rows": [
            ("Neutral", "+0 / -0", "El senal queda como contexto y normalmente no mueve el score."),
            ("Nice to have", "movimiento pequeno", "Si coincide sube poco; si falta baja poco."),
            ("Strong wish", "movimiento mayor", "El mismo senal pesa mas cuando coincide y cuesta mas cuando falta."),
            ("Must-have", "filtro o techo", "Si contradice el must-have, se filtra o se limita el score."),
            ("Avoid", "movimiento negativo", "Si aparece lo evitado, baja el score; solo una regla dura excluye."),
        ],
        "calculation_detail_rows": [
            ("Inicio", "+50", "Base neutral tras pasar las reglas duras.", "Todo candidato revisable empieza en 50 para que evidencia positiva y negativa pueda moverlo.", "La fuerza de preferencia no cambia la base."),
            ("Reglas duras superadas", "+8", "Pais, zona, modo, tipo, presupuesto, habitaciones y superficie no chocan.", "Es un aumento de elegibilidad, no una preferencia flexible.", "Si falla zona, modo, presupuesto, habitaciones o tipo duro, se excluye en vez de puntuar."),
            ("Calidad de evidencia", "+10", "Plano, gastos y evidencia real 360/tour estan disponibles.", "Mas hechos verificados hacen mas segura la decision remota.", "Solo plano seria cerca de +4; plano mas gastos cerca de +7; evidencia completa da +10."),
            ("Preferencias flexibles", "+6", "Trayectos, vida diaria y familia coinciden como nice-to-have.", "Los matches flexibles suben rango sin ocultar viviendas.", "Neutral +0; nice-to-have aqui +6; strong wish cerca de +12; must-have contrario filtra o limita."),
            ("Ubicacion verificada", "+0", "La ubicacion viene del candidato, no solo del alcance de busqueda del proveedor.", "Sirve para verificar elegibilidad y contexto cercano, no para premiar estar en la zona correcta.", "Evidencia gruesa queda neutral; codigo postal contradictorio excluye si la zona es dura."),
            ("Calefaccion pendiente", "-8", "La calefaccion importa pero esta desconocida.", "Los datos ausentes no se inventan; bajan confianza hasta verificarse.", "Neutral seria -2 o 0; strong wish -8 a -12; must-have duro puede limitar o excluir."),
            ("Un deseo falta", "-3", "Una caracteristica deseada no critica falta o no esta probada.", "Un fallo flexible solo baja el rango.", "Neutral 0; nice-to-have -3; strong wish -6; must-have ausente filtra o limita."),
            ("Riesgo abierto", "-5", "Quedan preguntas para visita o agente.", "El score muestra incertidumbre en vez de fingir completitud.", "Riesgo menor -2; riesgo importante -5; riesgo alto puede limitar bajo strong-fit."),
        ],
    },
    "fr": {
        "calculation_detail_title": "D'ou vient chaque nombre",
        "calculation_detail_note": "L'exemple suit la meme logique que la recherche: regles strictes d'abord, puis preuves et preferences souples deplacent le rang visible.",
        "weight_ladder_title": "Comment la force change le delta",
        "weight_ladder_note": "Une preference plus forte change l'ampleur du mouvement. Elle ne filtre que si l'utilisateur la marque must-have ou regle stricte.",
        "weight_ladder_rows": [
            ("Neutre", "+0 / -0", "Le signal reste du contexte et ne deplace normalement pas le score."),
            ("Nice to have", "petit mouvement", "Un match ajoute peu; une absence coute peu."),
            ("Strong wish", "mouvement plus fort", "Le meme signal pese plus quand il matche et coute plus quand il manque."),
            ("Must-have", "filtre ou plafond", "Une contradiction filtre ou plafonne au lieu de seulement baisser."),
            ("Avoid", "mouvement negatif", "La condition evitee baisse le score; seule une regle stricte exclut."),
        ],
        "calculation_detail_rows": [
            ("Depart", "+50", "Base neutre apres les regles strictes.", "Tout candidat revisable commence a 50 pour laisser agir preuves positives et negatives.", "La force de preference ne change pas la base."),
            ("Regles strictes passees", "+8", "Pays, zone, mode, type, budget, pieces et surface ne contredisent pas la recherche.", "C'est un bonus d'eligibilite, pas une preference souple.", "Si zone, mode, budget, pieces ou type strict echoue, le bien est exclu."),
            ("Qualite des preuves", "+10", "Plan, charges et vraie evidence 360/tour sont presents.", "Plus de faits verifies rend la decision a distance plus sure.", "Plan seul environ +4; plan plus charges environ +7; evidence complete +10."),
            ("Preferences souples", "+6", "Trajets, quotidien et famille matchent en nice-to-have.", "Les matches souples montent le rang sans cacher d'autres biens.", "Neutre +0; nice-to-have ici +6; strong wish environ +12; must-have contraire filtre ou plafonne."),
            ("Localisation verifiee", "+0", "La localisation vient du candidat, pas seulement du perimetre fournisseur.", "Elle verifie l'eligibilite et le contexte proche, sans bonus pour etre dans la bonne zone.", "Evidence grossiere reste neutre; code postal contradictoire exclut si zone stricte."),
            ("Chauffage inconnu", "-8", "Le chauffage est pertinent mais inconnu.", "Les faits manquants ne sont pas inventes; ils baissent la confiance.", "Neutre serait -2 ou 0; strong wish -8 a -12; must-have strict peut plafonner ou exclure."),
            ("Un souhait manque", "-3", "Un souhait non critique manque ou n'est pas prouve.", "Un manque souple baisse seulement le rang.", "Neutre 0; nice-to-have -3; strong wish -6; must-have absent filtre ou plafonne."),
            ("Risque a verifier", "-5", "Il reste des questions pour visite ou agent.", "Le score garde l'incertitude visible.", "Risque mineur -2; risque important -5; risque eleve peut plafonner sous strong-fit."),
        ],
    },
    "it": {
        "calculation_detail_title": "Da dove viene ogni numero",
        "calculation_detail_note": "L'esempio usa la stessa scala della ricerca: prima regole dure, poi prove e preferenze morbide muovono il rango visibile.",
        "weight_ladder_title": "Come la forza cambia il delta",
        "weight_ladder_note": "Una preferenza piu forte cambia la dimensione del movimento. Filtra solo se marcata come must-have o regola dura.",
        "weight_ladder_rows": [
            ("Neutrale", "+0 / -0", "Il segnale resta contesto e normalmente non muove lo score."),
            ("Nice to have", "movimento piccolo", "Un match alza poco; una mancanza costa poco."),
            ("Strong wish", "movimento maggiore", "Lo stesso segnale pesa di piu quando combacia e costa di piu quando manca."),
            ("Must-have", "filtro o tetto", "Una contraddizione filtra o limita invece di abbassare soltanto."),
            ("Avoid", "movimento negativo", "La condizione evitata abbassa lo score; solo una regola dura esclude."),
        ],
        "calculation_detail_rows": [
            ("Inizio", "+50", "Base neutra dopo le regole dure.", "Ogni candidato rivedibile parte da 50 per far agire prove positive e negative.", "La forza della preferenza non cambia la base."),
            ("Regole dure superate", "+8", "Paese, area, modo, tipo, budget, stanze e superficie non confliggono.", "E un boost di idoneita, non una preferenza morbida.", "Se area, modo, budget, stanze o tipo duro falliscono, la casa viene esclusa."),
            ("Qualita prove", "+10", "Sono presenti planimetria, costi e vera evidenza 360/tour.", "Piu fatti verificati rendono piu sicura la decisione remota.", "Solo planimetria circa +4; planimetria piu costi circa +7; evidenza completa +10."),
            ("Preferenze morbide", "+6", "Spostamenti, vita quotidiana e famiglia combaciano come nice-to-have.", "I match morbidi alzano il rango senza nascondere case.", "Neutrale +0; nice-to-have qui +6; strong wish circa +12; must-have contrario filtra o limita."),
            ("Posizione verificata", "+0", "La posizione viene dal candidato, non solo dallo scope del provider.", "Verifica idoneita e contesto vicino, senza premio per essere nell'area giusta.", "Evidenza grossolana resta neutra; CAP contraddittorio esclude se area dura."),
            ("Riscaldamento aperto", "-8", "Il riscaldamento e rilevante ma ignoto.", "I fatti mancanti non si inventano; abbassano fiducia.", "Neutrale sarebbe -2 o 0; strong wish -8 a -12; must-have duro puo limitare o escludere."),
            ("Un desiderio manca", "-3", "Una caratteristica desiderata non critica manca o non e provata.", "Una mancanza morbida abbassa solo il rango.", "Neutrale 0; nice-to-have -3; strong wish -6; must-have assente filtra o limita."),
            ("Rischio da verificare", "-5", "Restano domande per visita o agente.", "Lo score rende visibile l'incertezza.", "Rischio minore -2; importante -5; alto puo limitare sotto strong-fit."),
        ],
    },
    "nl": {
        "calculation_detail_title": "Waar elk getal vandaan komt",
        "calculation_detail_note": "Het voorbeeld gebruikt dezelfde ladder als de zoekmachine: eerst harde regels, daarna verplaatsen evidence en zachte voorkeuren de zichtbare rang.",
        "weight_ladder_title": "Hoe voorkeursterkte de delta verandert",
        "weight_ladder_note": "Een sterkere voorkeur verandert de grootte van de scorestap. Ze filtert pas wanneer de gebruiker haar als must-have of harde regel markeert.",
        "weight_ladder_rows": [
            ("Neutraal", "+0 / -0", "Het signaal blijft context en beweegt de score normaal niet."),
            ("Nice to have", "kleine stap", "Een match verhoogt licht; een gemis kost licht."),
            ("Strong wish", "grotere stap", "Hetzelfde signaal telt sterker bij match en kost meer bij gemis."),
            ("Must-have", "filter of plafond", "Een tegenspraak filtert of plafonneert in plaats van alleen te verlagen."),
            ("Avoid", "negatieve stap", "De vermeden conditie verlaagt de score; alleen een harde regel sluit uit."),
        ],
        "calculation_detail_rows": [
            ("Start", "+50", "Neutrale basis na de harde regels.", "Elke reviewbare kandidaat start op 50 zodat positieve en negatieve evidence kunnen werken.", "Voorkeursterkte verandert de basis niet."),
            ("Harde regels gehaald", "+8", "Land, gebied, modus, type, budget, kamers en oppervlakte botsen niet.", "Dit is een geschiktheidsboost, geen zachte voorkeur.", "Als gebied, modus, budget, kamers of hard type faalt, wordt de woning uitgesloten."),
            ("Bewijskwaliteit", "+10", "Plattegrond, kosten en echte 360/tour-evidence zijn aanwezig.", "Meer geverifieerde feiten maken de remote beslissing veiliger.", "Alleen plattegrond ongeveer +4; plattegrond plus kosten +7; volledige evidence +10."),
            ("Zachte voorkeuren", "+6", "Routes, dagelijks leven en gezin matchen als nice-to-have.", "Zachte matches verhogen rang zonder woningen te verbergen.", "Neutraal +0; nice-to-have hier +6; strong wish ongeveer +12; must-have-tegenspraak filtert of plafonneert."),
            ("Locatie gecontroleerd", "+0", "De locatie komt van kandidaatbewijs, niet alleen provider-scope.", "Dit verifieert geschiktheid en nabijheid, maar beloont het juiste gebied niet.", "Grove evidence blijft neutraal; tegengesproken postcode sluit uit bij hard gebied."),
            ("Verwarming open", "-8", "Verwarming is relevant maar onbekend.", "Ontbrekende feiten worden niet verzonnen; ze verlagen vertrouwen.", "Neutraal zou -2 of 0 zijn; strong wish -8 tot -12; hard must-have kan plafonneren of uitsluiten."),
            ("Een wens ontbreekt", "-3", "Een niet-kritische wens ontbreekt of is onbewezen.", "Een zachte misser verlaagt alleen rang.", "Neutraal 0; nice-to-have -3; strong wish -6; must-have ontbrekend filtert of plafonneert."),
            ("Open verificatierisico", "-5", "Er blijven vragen voor bezichtiging of makelaar.", "De score houdt onzekerheid zichtbaar.", "Klein risico -2; belangrijk risico -5; hoog risico kan onder strong-fit plafonneren."),
        ],
    },
    "pt": {
        "calculation_detail_title": "De onde vem cada numero",
        "calculation_detail_note": "O exemplo usa a mesma escala da pesquisa: regras duras primeiro, depois evidencia e preferencias suaves movem o ranking visivel.",
        "weight_ladder_title": "Como a forca muda o delta",
        "weight_ladder_note": "Uma preferencia mais forte muda o tamanho do movimento. So filtra se o utilizador marcar como must-have ou regra dura.",
        "weight_ladder_rows": [
            ("Neutro", "+0 / -0", "O sinal fica como contexto e normalmente nao move o score."),
            ("Nice to have", "movimento pequeno", "Um match sobe pouco; uma falta custa pouco."),
            ("Strong wish", "movimento maior", "O mesmo sinal pesa mais quando bate e custa mais quando falta."),
            ("Must-have", "filtro ou teto", "Uma contradicao filtra ou limita em vez de apenas baixar."),
            ("Avoid", "movimento negativo", "A condicao evitada baixa o score; so uma regra dura exclui."),
        ],
        "calculation_detail_rows": [
            ("Inicio", "+50", "Base neutra depois das regras duras.", "Todo candidato revisavel parte de 50 para evidencia positiva e negativa moverem.", "A forca da preferencia nao muda a base."),
            ("Regras duras cumpridas", "+8", "Pais, zona, modo, tipo, orcamento, quartos e area nao conflitam.", "E um boost de elegibilidade, nao uma preferencia suave.", "Se zona, modo, orcamento, quartos ou tipo duro falham, a casa e excluida."),
            ("Qualidade da evidencia", "+10", "Planta, custos e evidencia real 360/tour estao presentes.", "Mais factos verificados tornam a decisao remota mais segura.", "So planta cerca de +4; planta mais custos +7; evidencia completa +10."),
            ("Preferencias suaves", "+6", "Trajetos, vida diaria e familia combinam como nice-to-have.", "Matches suaves sobem ranking sem esconder casas.", "Neutro +0; nice-to-have aqui +6; strong wish cerca de +12; must-have contrario filtra ou limita."),
            ("Localizacao verificada", "+0", "A localizacao vem do candidato, nao apenas do scope do fornecedor.", "Verifica elegibilidade e contexto proximo, sem bonus por estar na zona certa.", "Evidencia grosseira fica neutra; postal contraditorio exclui se a zona for dura."),
            ("Aquecimento em aberto", "-8", "O aquecimento e relevante mas desconhecido.", "Factos em falta nao sao inventados; baixam confianca.", "Neutro seria -2 ou 0; strong wish -8 a -12; must-have duro pode limitar ou excluir."),
            ("Um desejo falta", "-3", "Uma caracteristica desejada nao critica falta ou nao esta provada.", "Uma falta suave baixa apenas ranking.", "Neutro 0; nice-to-have -3; strong wish -6; must-have ausente filtra ou limita."),
            ("Risco a verificar", "-5", "Restam perguntas para visita ou agente.", "O score mantem incerteza visivel.", "Risco menor -2; importante -5; alto pode limitar abaixo de strong-fit."),
        ],
    },
    "pl": {
        "calculation_detail_title": "Skad bierze sie kazda liczba",
        "calculation_detail_note": "Przyklad uzywa tej samej drabiny co wyszukiwarka: najpierw twarde reguly, potem dowody i miekkie preferencje przesuwaja widoczny ranking.",
        "weight_ladder_title": "Jak sila preferencji zmienia delte",
        "weight_ladder_note": "Silniejsza preferencja zmienia wielkosc ruchu. Filtruje dopiero, gdy uzytkownik oznaczy ja jako must-have lub twarda regule.",
        "weight_ladder_rows": [
            ("Neutralnie", "+0 / -0", "Sygnal zostaje kontekstem i zwykle nie zmienia wyniku."),
            ("Nice to have", "maly ruch", "Dopasowanie lekko podnosi; brak lekko kosztuje."),
            ("Strong wish", "wiekszy ruch", "Ten sam sygnal wazy wiecej przy dopasowaniu i kosztuje wiecej przy braku."),
            ("Must-have", "filtr lub pulap", "Sprzecznosc filtruje lub naklada pulap zamiast tylko obnizac."),
            ("Avoid", "ruch ujemny", "Warunek unikany obniza wynik; tylko twarda regula wyklucza."),
        ],
        "calculation_detail_rows": [
            ("Start", "+50", "Neutralna baza po twardych regulach.", "Kazdy oceniany kandydat startuje z 50, aby dowody dodatnie i ujemne mogly dzialac.", "Sila preferencji nie zmienia bazy."),
            ("Twarde reguly spelnione", "+8", "Kraj, obszar, tryb, typ, budzet, pokoje i metraz nie koliduja.", "To boost kwalifikacji, nie miekka preferencja.", "Jesli obszar, tryb, budzet, pokoje lub twardy typ nie przejda, oferta jest wykluczona."),
            ("Jakosc dowodow", "+10", "Plan, koszty i prawdziwe 360/tour sa dostepne.", "Wiecej zweryfikowanych faktow zwieksza bezpieczenstwo decyzji zdalnej.", "Sam plan okolo +4; plan plus koszty +7; pelne dowody +10."),
            ("Miekkie preferencje", "+6", "Dojazdy, codziennosc i rodzina pasuja jako nice-to-have.", "Miekkie trafienia podnosza ranking bez ukrywania ofert.", "Neutralnie +0; nice-to-have tu +6; strong wish okolo +12; sprzeczny must-have filtruje lub naklada pulap."),
            ("Lokalizacja sprawdzona", "+0", "Lokalizacja pochodzi z kandydata, nie tylko ze scope dostawcy.", "Sprawdza kwalifikacje i pobliski kontekst, ale nie nagradza za wlasciwy obszar.", "Grube dowody zostaja neutralne; sprzeczny kod pocztowy wyklucza przy twardym obszarze."),
            ("Ogrzewanie otwarte", "-8", "Ogrzewanie jest wazne, ale nieznane.", "Brakujace fakty nie sa wymyslane; obnizaja zaufanie.", "Neutralnie byloby -2 lub 0; strong wish -8 do -12; hard must-have moze dac pulap lub wykluczenie."),
            ("Brakuje jednego zyczenia", "-3", "Nie-krytyczna cecha po prostu nie jest potwierdzona.", "Miekki brak obniza tylko ranking.", "Neutralnie 0; nice-to-have -3; strong wish -6; brak must-have filtruje lub daje pulap."),
            ("Otwarte ryzyko", "-5", "Zostaja pytania na ogladanie lub do agenta.", "Wynik pokazuje niepewnosc.", "Male ryzyko -2; wazne -5; wysokie moze ograniczyc ponizej strong-fit."),
        ],
    },
    "sv": {
        "calculation_detail_title": "Varje siffra i berakningen",
        "calculation_detail_note": "Exemplet anvander samma stege som sokningen: harda regler forst, sedan flyttar evidens och mjuka preferenser synlig ranking.",
        "weight_ladder_title": "Hur preferensstyrka andrar deltat",
        "weight_ladder_note": "En starkare preferens andrar storleken pa score-rorelsen. Den filtrerar bara nar anvandaren markerar den som must-have eller hard regel.",
        "weight_ladder_rows": [
            ("Neutral", "+0 / -0", "Signalen ar kontext och flyttar normalt inte score."),
            ("Nice to have", "liten rorelse", "En match hojer lite; en saknad kostar lite."),
            ("Strong wish", "storre rorelse", "Samma signal vager mer vid match och kostar mer nar den saknas."),
            ("Must-have", "filter eller tak", "En motsagelse filtrerar eller satter tak istallet for bara sankning."),
            ("Avoid", "negativ rorelse", "Det undvikta villkoret sanker score; bara hard regel exkluderar."),
        ],
        "calculation_detail_rows": [
            ("Start", "+50", "Neutral bas efter harda regler.", "Varje granskningsbar kandidat startar pa 50 sa positiv och negativ evidens kan verka.", "Preferensstyrka andrar inte basen."),
            ("Harda regler passerade", "+8", "Land, omrade, lage, typ, budget, rum och yta krockar inte.", "Detta ar en behorighetsboost, inte mjuk preferens.", "Om omrade, lage, budget, rum eller hard typ faller, exkluderas bostaden."),
            ("Evidenskvalitet", "+10", "Planritning, kostnader och riktig 360/tour-evidens finns.", "Fler verifierade fakta gor fjarrbeslutet tryggare.", "Endast plan cirka +4; plan plus kostnader +7; full evidens +10."),
            ("Mjuka preferenser", "+6", "Pendling, vardag och familj matchar som nice-to-have.", "Mjuka matchningar hojer ranking utan att gomma bostader.", "Neutral +0; nice-to-have har +6; strong wish cirka +12; must-have-motsagelse filtrerar eller satter tak."),
            ("Plats kontrollerad", "+0", "Platsen kommer fran kandidatens evidens, inte bara leverantorens sokomrade.", "Den verifierar behorighet och narliggande kontext, utan bonus for ratt omrade.", "Grov evidens ar neutral; motsagd postkod exkluderar vid hardt omrade."),
            ("Varme okand", "-8", "Varme ar relevant men okand.", "Saknade fakta hittas inte pa; de sanker fortroende.", "Neutral vore -2 eller 0; strong wish -8 till -12; hard must-have kan satta tak eller exkludera."),
            ("Ett onskemal saknas", "-3", "En icke-kritisk onskad egenskap saknas eller ar obevisad.", "En mjuk miss sanker bara ranking.", "Neutral 0; nice-to-have -3; strong wish -6; saknat must-have filtrerar eller satter tak."),
            ("Oppen verifieringsrisk", "-5", "Fragor aterstar for visning eller maklare.", "Score haller osakerhet synlig.", "Liten risk -2; viktig risk -5; hog risk kan satta tak under strong-fit."),
        ],
    },
}


def supported_property_score_methodology_languages() -> tuple[str, ...]:
    return tuple(sorted({str(country.default_language or "en").strip().lower() for country in COUNTRIES if str(country.default_language or "").strip()}))


def resolve_property_score_methodology_language(
    *,
    language_code: object = "",
    country_code: object = "",
    accept_language: object = "",
    fallback_language_code: object = "",
) -> str:
    normalized_country = str(country_code or "AT").strip().upper() or "AT"
    supported = set(supported_property_score_methodology_languages())
    explicit_raw = str(language_code or "").strip()
    if explicit_raw:
        explicit = normalize_language_code(explicit_raw, country_code=normalized_country).lower()
        if explicit in supported:
            return explicit
    header = str(accept_language or "").strip()
    if header:
        for raw_part in header.split(","):
            token = raw_part.split(";", 1)[0].strip()
            if not token:
                continue
            normalized = normalize_language_code(token, country_code=normalized_country).lower()
            if normalized in supported:
                return normalized
    fallback_raw = str(fallback_language_code or "").strip()
    if fallback_raw:
        fallback_language = normalize_language_code(fallback_raw, country_code=normalized_country).lower()
        if fallback_language in supported:
            return fallback_language
    fallback = default_language_for_country(normalized_country).lower()
    if fallback in supported:
        return fallback
    return "en"


def _localize_preference_terms(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, str):
        localized = value
        for old, new in replacements.items():
            localized = localized.replace(old, new)
        return localized
    if isinstance(value, list):
        return [_localize_preference_terms(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(_localize_preference_terms(item, replacements) for item in value)
    return value


def _localized(language_code: object = "", *, country_code: object = "", accept_language: object = "") -> dict[str, object]:
    code = resolve_property_score_methodology_language(
        language_code=language_code,
        country_code=country_code,
        accept_language=accept_language,
    )
    if code not in supported_property_score_methodology_languages():
        code = default_language_for_country(country_code).lower()
    base = dict(_LOCALIZED_COPY["en"])
    if code == "de":
        base.update(_LOCALIZED_COPY["de"])
    elif code in _TRANSLATION_HINTS:
        base.update(_TRANSLATION_HINTS[code])
    if code in _LOCALIZED_CALCULATION_COPY:
        base.update(_LOCALIZED_CALCULATION_COPY[code])
    if code in _LOCALIZED_PDF_EXAMPLE_COPY:
        base.update(_LOCALIZED_PDF_EXAMPLE_COPY[code])
    if code in _LOCALIZED_WEIGHT_EXPLAINER_COPY:
        base.update(_LOCALIZED_WEIGHT_EXPLAINER_COPY[code])
    if not base.get("source_sections"):
        base["source_sections_label"] = _LOCALIZED_WEIGHT_EXPLAINER_COPY["en"]["source_sections_label"]
        base["source_sections"] = _LOCALIZED_WEIGHT_EXPLAINER_COPY["en"]["source_sections"]
    replacements = _PREFERENCE_TERM_REPLACEMENTS.get(code)
    if replacements:
        for key, value in list(base.items()):
            base[key] = _localize_preference_terms(value, replacements)
    base["language_code"] = code
    base["language_label"] = _LANGUAGE_NAMES.get(code, code.upper())
    return base


def _text_items(value: object, *, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value[:limit] if str(item or "").strip()]


def _score_band(score: int, bands: list[tuple[str, str]]) -> str:
    if score >= 60:
        return bands[-1][1]
    if score >= 45:
        return bands[2][1]
    if score >= 35:
        return bands[1][1]
    return bands[0][1]


def build_property_score_methodology(
    *,
    language_code: object = "",
    country_code: object = "",
    accept_language: object = "",
    candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    copy = _localized(language_code, country_code=country_code, accept_language=accept_language)
    candidate_payload = dict(candidate or {})
    try:
        fit_score = max(0, min(100, int(float(candidate_payload.get("fit_score") or 0))))
    except Exception:
        fit_score = 0
    bands = [(str(a), str(b)) for a, b in list(copy.get("bands") or [])]
    positive = _text_items(candidate_payload.get("match_reasons"), limit=4)
    negative = _text_items(candidate_payload.get("mismatch_reasons"), limit=4)
    if not positive:
        positive = [
            "Confirmed facts improve confidence.",
            "Good matches in What matters move the score upward.",
        ]
    if not negative:
        negative = [
            "Missing evidence reduces confidence until the fact is checked.",
            "Soft preferences lower rank without hiding the home.",
        ]
    return {
        "contract_name": "propertyquarry.score_methodology.v1",
        "version": "2026-06-22",
        "language_code": str(copy.get("language_code") or "en"),
        "country_code": str(country_code or "").strip().upper(),
        "language_label": str(copy.get("language_label") or "English"),
        "title": str(copy.get("title") or "Behind the score"),
        "subtitle": str(copy.get("subtitle") or ""),
        "summary": str(copy.get("summary") or ""),
        "principles": list(copy.get("principles") or []),
        "steps": [
            {"title": str(title), "detail": str(detail)}
            for title, detail in list(copy.get("steps") or [])
        ],
        "examples": [
            {"title": str(title), "detail": str(detail)}
            for title, detail in list(copy.get("examples") or [])
        ],
        "score_bands": [{"range": str(label), "meaning": str(meaning)} for label, meaning in bands],
        "pdf_title": str(copy.get("pdf_title") or "How the PropertyQuarry score is calculated"),
        "candidate_title": str(copy.get("candidate_title") or "Current candidate score read"),
        "calculation_title": str(copy.get("calculation_title") or "Example calculation"),
        "steps_label": str(copy.get("steps_label") or "Rules applied"),
        "examples_label": str(copy.get("examples_label") or "Examples"),
        "positive_label": str(copy.get("positive_label") or "Signals lifting the score"),
        "negative_label": str(copy.get("negative_label") or "Signals reducing confidence or score"),
        "neutral_note": str(copy.get("neutral_note") or ""),
        "calculation_rows": [
            {"label": str(label), "delta": str(delta), "why": str(why)}
            for label, delta, why in list(copy.get("calculation_rows") or [])
        ],
        "calculation_detail_title": str(copy.get("calculation_detail_title") or "Where each number comes from"),
        "calculation_detail_note": str(copy.get("calculation_detail_note") or ""),
        "calculation_detail_rows": [
            {
                "label": str(label),
                "delta": str(delta),
                "source": str(source),
                "rule": str(rule),
                "alternatives": str(alternatives),
            }
            for label, delta, source, rule, alternatives in list(copy.get("calculation_detail_rows") or [])
        ],
        "weight_ladder_title": str(copy.get("weight_ladder_title") or "How preference strength changes a delta"),
        "weight_ladder_note": str(copy.get("weight_ladder_note") or ""),
        "weight_ladder_rows": [
            {"level": str(level), "effect": str(effect), "rule": str(rule)}
            for level, effect, rule in list(copy.get("weight_ladder_rows") or [])
        ],
        "source_sections_label": str(copy.get("source_sections_label") or "Where the information comes from"),
        "source_sections": [
            {"title": str(title), "detail": str(detail)}
            for title, detail in list(copy.get("source_sections") or [])
        ],
        "candidate_application": {
            "fit_score": fit_score,
            "band_label": _score_band(fit_score, bands) if fit_score else "",
            "positive_signals": positive,
            "negative_signals": negative,
        },
    }


def build_property_score_methodology_pdf_source(
    *,
    language_code: object = "",
    country_code: object = "",
    accept_language: object = "",
) -> dict[str, object]:
    copy = _localized(language_code, country_code=country_code, accept_language=accept_language)
    candidate = {
        "fit_score": 62,
        "match_reasons": list(copy.get("match_reasons") or ()),
        "mismatch_reasons": list(copy.get("mismatch_reasons") or ()),
    }
    methodology = build_property_score_methodology(
        language_code=language_code,
        country_code=country_code,
        accept_language=accept_language,
        candidate=candidate,
    )
    return {
        "title": str(methodology.get("pdf_title") or "PropertyQuarry score methodology"),
        "summary": str(methodology.get("summary") or ""),
        "score_methodology_only": True,
        "source_label": str(copy.get("source_label") or "PropertyQuarry scoring engine"),
        "language_code": str(methodology.get("language_code") or "en"),
        "country_code": str(country_code or "").strip().upper(),
        "fit_score": candidate["fit_score"],
        "recommendation": str(copy.get("recommendation") or "Strong fit"),
        "match_reasons": list(candidate["match_reasons"]),
        "mismatch_reasons": list(candidate["mismatch_reasons"]),
        "viewing_questions": list(copy.get("viewing_questions") or ()),
        "property_facts": {
            "language_code": str(methodology.get("language_code") or "en"),
            "country_code": str(country_code or "").strip().upper(),
            "postal_name": str(copy.get("postal_name") or "Demo market"),
            "price_display": str(copy.get("price_display") or "Example budget"),
            "area_m2": 82,
            "rooms": 3,
            "has_floorplan": True,
            "nearest_school_m": 430,
            "nearest_supermarket_m": 260,
        },
        "score_methodology": methodology,
    }


def build_property_score_methodology_for_supported_languages() -> list[dict[str, object]]:
    return [
        build_property_score_methodology(language_code=language_code)
        for language_code in supported_property_score_methodology_languages()
    ]
