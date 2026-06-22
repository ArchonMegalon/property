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


_LOCALIZED_COPY: dict[str, dict[str, object]] = {
    "en": {
        "title": "Behind the score",
        "subtitle": "How PropertyQuarry turns a listing into a personal fit score.",
        "summary": "The score is not portal popularity. It is a 0-100 personal fit estimate built from hard eligibility, verified listing facts, soft preferences, route and neighbourhood evidence, missing facts, and your saved feedback.",
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
            ("Real tour available", "A Matterport, 3DVista, or verified 360 source improves remote-screening confidence."),
        ],
        "bands": [("0-34", "Watch only"), ("35-44", "Possible fit"), ("45-59", "Good fit"), ("60+", "Strong fit")],
        "pdf_title": "How the PropertyQuarry score is calculated",
        "candidate_title": "Current candidate score read",
        "calculation_title": "Example calculation: why this property lands at 62",
        "steps_label": "Rules applied",
        "examples_label": "Examples",
        "positive_label": "Signals lifting the score",
        "negative_label": "Signals reducing confidence or score",
        "neutral_note": "Exact weights can vary by market and search mode, but hard rules, evidence quality, soft preferences, and feedback are always separated.",
        "calculation_rows": [
            ("Start", "+50", "A candidate starts neutral once it has passed the hard gate."),
            ("Hard gate passed", "+8", "Country, selected area, rent/buy mode, property type, budget, rooms and size do not conflict."),
            ("Evidence quality", "+10", "Floorplan, costs and a real 360/tour source make the listing easier to verify remotely."),
            ("Soft preferences", "+6", "Daily-life, commute and family preferences fit well enough to lift rank."),
            ("Location confidence", "+4", "The listing location is specific enough to compare against selected districts and nearby evidence."),
            ("Missing heating detail", "-8", "Heating is still unknown, so confidence drops until verified."),
            ("One soft wish missing", "-3", "A missing nice-to-have lowers rank but does not filter the home."),
            ("Open verification risk", "-5", "Remaining unknowns are kept as viewing questions."),
            ("Final score", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
    "de": {
        "title": "Blick hinter den Score",
        "subtitle": "Wie PropertyQuarry aus einem Inserat eine persoenliche Passung berechnet.",
        "summary": "Kurzfassung: Harte Regeln entscheiden, ob ein Objekt ueberhaupt in Frage kommt. Danach startet die Rechnung neutral bei 50 Punkten. Belegte Staerken heben den Score, offene Fakten und passende Gegenargumente senken ihn.",
        "principles": [
            "Harte Regeln entfernen ein Objekt vor dem Scoring: Land, Bezirk, Transaktionsart, Objekttyp, Budget und echte Must-haves.",
            "Weiche Praeferenzen bewegen nur den Score. Ein fehlender Balkon als Nice-to-have versteckt kein gutes Objekt.",
            "Belegqualitaet zaehlt. Grundriss, echte 360-Tour, Betriebskosten, Energie- und Standortdaten erhoehen die Sicherheit.",
            "Fehlende Fakten gelten nicht automatisch als falsch. Sie senken Vertrauen und werden zu konkreten Fragen.",
            "Gespeichertes Feedback veraendert kuenftige Rankings, waehrend die aktuelle Beleglage sichtbar bleibt.",
        ],
        "steps": [
            ("1. Harte Vorauswahl", "Zuerst prueft die Engine Markt, Gebiet, Miete/Kauf, Objekttyp, Budget, Mindestgroesse, Zimmer und explizite Must-haves."),
            ("2. Faktennormalisierung", "Providerseiten, strukturierte Daten, Titel, Snippets, Grundrisse, Kosten, Medien und offizielle Quellen werden vergleichbar gemacht."),
            ("3. Persoenliche Passung", "Das Inserat wird gegen What matters geprueft: Wege, Alltag, Schule, Kindergarten, Barrierefreiheit, Freiraum, Parken, Internet, Risiken und Haushaltsfeedback."),
            ("4. Weiche Bewertung", "Wuensche, starke Wuensche, Vermeiden-Regeln und Distanzen bewegen den Score. Sie filtern nicht, solange sie nicht als harte Regel markiert sind."),
            ("5. Vertrauen und offene Punkte", "Fehlende Kosten, unklare Heizung, kein Grundriss, schwache Lagebelege oder veraltete Quellen senken das Vertrauen und erzeugen Rueckfragen."),
            ("6. Ranking und Reparatur", "Der Rang kombiniert Passung, Evidenz, Aktualitaet, Duplikate und Reparaturstatus. Gescheiterte Quellen werden getrennt repariert."),
        ],
        "examples": [
            ("Falscher Bezirk", "Ein Inserat in 1220 wird ausgeschlossen, wenn nur 1010 gewaehlt ist. Das ist eine harte Regel."),
            ("Balkon als Wunsch", "Fehlt der Balkon nur als Wunsch, bleibt das Objekt sichtbar und verliert lediglich Score."),
            ("Sicherer Schulweg", "Ein plausibel sicherer Weg zur Schule oder zum Kindergarten kann den Score erhoehen."),
            ("Kosten fehlen", "Fehlende Betriebskosten senken Vertrauen und werden als Rueckfrage markiert, statt erfunden zu werden."),
            ("Echte Tour vorhanden", "Matterport, 3DVista oder eine verifizierte 360-Quelle erhoeht die Remote-Screening-Sicherheit."),
        ],
        "bands": [("0-34", "Nur beobachten"), ("35-44", "Moegliche Passung"), ("45-59", "Gute Passung"), ("60+", "Starke Passung")],
        "pdf_title": "Wie der PropertyQuarry-Score berechnet wird",
        "candidate_title": "Score-Lesart fuer dieses Objekt",
        "calculation_title": "Beispielrechnung: warum dieses Objekt bei 62 landet",
        "steps_label": "Angewendete Regeln",
        "examples_label": "Beispiele",
        "positive_label": "Signale, die den Score heben",
        "negative_label": "Signale, die Vertrauen oder Score senken",
        "neutral_note": "Die genaue Gewichtung kann je Markt und Suchmodus variieren, aber harte Regeln, Evidenz, weiche Praeferenzen und Feedback bleiben getrennt.",
        "calculation_rows": [
            ("Start", "+50", "Ein Objekt startet neutral, sobald es die harten Regeln bestanden hat."),
            ("Harte Regeln bestanden", "+8", "Land, Bezirk, Miete/Kauf, Objekttyp, Budget, Zimmer und Flaeche widersprechen der Suche nicht."),
            ("Evidenzqualitaet", "+10", "Grundriss, Kosten und echte 360-/Tour-Quelle machen das Objekt aus der Ferne besser pruefbar."),
            ("Weiche Praeferenzen", "+6", "Alltag, Wege und Familienwunsch passen gut genug, um den Rang zu heben."),
            ("Lagevertrauen", "+4", "Die Lage ist konkret genug, um Bezirk und Umfeld sinnvoll zu pruefen."),
            ("Heizung offen", "-8", "Die Heizungsinformation fehlt, daher sinkt das Vertrauen bis zur Klaerung."),
            ("Ein Wunsch fehlt", "-3", "Ein fehlender Wunsch senkt nur den Rang und filtert das Objekt nicht aus."),
            ("Offenes Pruefrisiko", "-5", "Restliche Unklarheiten bleiben als Fragen fuer Besichtigung oder Makler sichtbar."),
            ("Endwert", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
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
            ("Tour real disponible", "Matterport, 3DVista o una fuente 360 verificada mejora la confianza remota."),
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
            ("Vrai tour disponible", "Matterport, 3DVista ou une source 360 verifiee augmente la confiance a distance."),
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
            ("Tour reale disponibile", "Matterport, 3DVista o una fonte 360 verificata aumenta la fiducia da remoto."),
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
            ("Echte tour beschikbaar", "Matterport, 3DVista of een geverifieerde 360 bron verhoogt remote vertrouwen."),
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
            ("Tour real disponivel", "Matterport, 3DVista ou uma fonte 360 verificada aumenta a confianca remota."),
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
            ("Prawdziwy tour dostepny", "Matterport, 3DVista lub zweryfikowane 360 zwieksza zaufanie zdalne."),
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
            ("Riktig tour finns", "Matterport, 3DVista eller verifierad 360-kalla hojer fjarrgranskningsfortroendet."),
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
        "calculation_title": "Calculo de ejemplo: por que esta vivienda llega a 62",
        "steps_label": "Reglas aplicadas",
        "examples_label": "Ejemplos",
        "calculation_rows": [
            ("Inicio", "+50", "La vivienda empieza neutral cuando supera las reglas duras."),
            ("Reglas duras superadas", "+8", "Pais, zona, alquiler/compra, tipo, presupuesto, habitaciones y superficie no contradicen la busqueda."),
            ("Calidad de evidencia", "+10", "Plano, gastos y una fuente 360/tour real hacen la vivienda mas verificable a distancia."),
            ("Preferencias flexibles", "+6", "Vida diaria, trayectos y preferencias familiares encajan lo suficiente para subir el rango."),
            ("Confianza de ubicacion", "+4", "La ubicacion es concreta para comparar zonas elegidas y evidencia cercana."),
            ("Calefaccion pendiente", "-8", "La calefaccion sigue sin confirmar, asi que baja la confianza."),
            ("Un deseo falta", "-3", "Un deseo ausente baja el rango, pero no filtra la vivienda."),
            ("Riesgo abierto", "-5", "Las incognitas restantes quedan como preguntas de visita."),
            ("Resultado", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
    "fr": {
        "calculation_title": "Calcul d'exemple: pourquoi ce bien arrive a 62",
        "steps_label": "Regles appliquees",
        "examples_label": "Exemples",
        "calculation_rows": [
            ("Depart", "+50", "Le bien commence neutre apres avoir passe les regles strictes."),
            ("Regles strictes passees", "+8", "Pays, zone, location/achat, type, budget, pieces et surface ne contredisent pas la recherche."),
            ("Qualite des preuves", "+10", "Plan, charges et vraie source 360/tour rendent le bien plus verifiable a distance."),
            ("Preferences souples", "+6", "Quotidien, trajets et preferences familiales correspondent assez pour relever le rang."),
            ("Confiance de localisation", "+4", "La localisation est assez concrete pour comparer zones choisies et preuves proches."),
            ("Chauffage inconnu", "-8", "Le chauffage reste a confirmer, donc la confiance baisse."),
            ("Un souhait manque", "-3", "Un souhait manquant baisse le rang, mais ne filtre pas le bien."),
            ("Risque a verifier", "-5", "Les inconnues restantes deviennent des questions de visite."),
            ("Resultat", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
    "it": {
        "calculation_title": "Calcolo di esempio: perche questa casa arriva a 62",
        "steps_label": "Regole applicate",
        "examples_label": "Esempi",
        "calculation_rows": [
            ("Inizio", "+50", "La casa parte neutra dopo aver superato le regole dure."),
            ("Regole dure superate", "+8", "Paese, area, affitto/acquisto, tipo, budget, stanze e superficie non sono in conflitto."),
            ("Qualita prove", "+10", "Planimetria, costi e una vera fonte 360/tour rendono la casa piu verificabile da remoto."),
            ("Preferenze morbide", "+6", "Vita quotidiana, spostamenti e preferenze familiari alzano abbastanza il rango."),
            ("Fiducia posizione", "+4", "La posizione e abbastanza concreta per confrontare aree e prove vicine."),
            ("Riscaldamento aperto", "-8", "Il riscaldamento e ancora da confermare, quindi la fiducia scende."),
            ("Un desiderio manca", "-3", "Un desiderio mancante abbassa il rango, ma non filtra la casa."),
            ("Rischio da verificare", "-5", "Le incognite restanti diventano domande per la visita."),
            ("Risultato", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
    "nl": {
        "calculation_title": "Voorbeeldberekening: waarom deze woning op 62 uitkomt",
        "steps_label": "Toegepaste regels",
        "examples_label": "Voorbeelden",
        "calculation_rows": [
            ("Start", "+50", "De woning start neutraal zodra de harde regels zijn gehaald."),
            ("Harde regels gehaald", "+8", "Land, gebied, huur/koop, type, budget, kamers en oppervlakte spreken de zoekopdracht niet tegen."),
            ("Bewijskwaliteit", "+10", "Plattegrond, kosten en een echte 360/tourbron maken de woning beter op afstand te controleren."),
            ("Zachte voorkeuren", "+6", "Dagelijks leven, routes en gezinsvoorkeuren passen goed genoeg om de rang te verhogen."),
            ("Locatievertrouwen", "+4", "De locatie is concreet genoeg om gekozen gebieden en nabije evidence te vergelijken."),
            ("Verwarming open", "-8", "De verwarming is nog onbekend, dus vertrouwen daalt tot verificatie."),
            ("Een wens ontbreekt", "-3", "Een ontbrekende wens verlaagt de rang, maar filtert de woning niet."),
            ("Open verificatierisico", "-5", "Resterende onbekenden blijven als kijkvragen staan."),
            ("Eindscore", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
    "pt": {
        "calculation_title": "Calculo de exemplo: porque esta casa chega a 62",
        "steps_label": "Regras aplicadas",
        "examples_label": "Exemplos",
        "calculation_rows": [
            ("Inicio", "+50", "A casa comeca neutra depois de passar as regras duras."),
            ("Regras duras cumpridas", "+8", "Pais, zona, arrendar/comprar, tipo, orcamento, quartos e area nao entram em conflito."),
            ("Qualidade da evidencia", "+10", "Planta, custos e uma fonte 360/tour real tornam a casa mais verificavel remotamente."),
            ("Preferencias suaves", "+6", "Vida diaria, trajetos e preferencias familiares encaixam o suficiente para subir o ranking."),
            ("Confianca de localizacao", "+4", "A localizacao e concreta o suficiente para comparar zonas escolhidas e evidencia proxima."),
            ("Aquecimento em aberto", "-8", "O aquecimento ainda precisa de confirmacao, entao a confianca baixa."),
            ("Um desejo falta", "-3", "Um desejo em falta baixa o ranking, mas nao filtra a casa."),
            ("Risco a verificar", "-5", "As restantes incertezas ficam como perguntas de visita."),
            ("Resultado", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
    "pl": {
        "calculation_title": "Przykladowe obliczenie: dlaczego ta nieruchomosc ma 62",
        "steps_label": "Zastosowane reguly",
        "examples_label": "Przyklady",
        "calculation_rows": [
            ("Start", "+50", "Nieruchomosc startuje neutralnie po przejsciu twardych regul."),
            ("Twarde reguly spelnione", "+8", "Kraj, obszar, najem/zakup, typ, budzet, pokoje i metraz nie kloca sie z wyszukiwaniem."),
            ("Jakosc dowodow", "+10", "Plan, koszty i prawdziwe 360/tour ulatwiaja zdalna weryfikacje."),
            ("Miekkie preferencje", "+6", "Codziennosc, dojazdy i potrzeby rodzinne pasuja na tyle, by podniesc ranking."),
            ("Zaufanie lokalizacji", "+4", "Lokalizacja jest dosc konkretna do porownania z wybranymi obszarami i pobliskimi dowodami."),
            ("Ogrzewanie otwarte", "-8", "Ogrzewanie nadal wymaga potwierdzenia, wiec zaufanie spada."),
            ("Brakuje jednego zyczenia", "-3", "Brak zyczenia obniza ranking, ale nie filtruje oferty."),
            ("Otwarte ryzyko", "-5", "Pozostale niewiadome zostaja pytaniami na ogladanie."),
            ("Wynik koncowy", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
    "sv": {
        "calculation_title": "Exempelberakning: varfor bostaden landar pa 62",
        "steps_label": "Tillampade regler",
        "examples_label": "Exempel",
        "calculation_rows": [
            ("Start", "+50", "Bostaden startar neutralt nar den passerat de harda reglerna."),
            ("Harda regler passerade", "+8", "Land, omrade, hyra/kop, typ, budget, rum och yta motsager inte sokningen."),
            ("Evidenskvalitet", "+10", "Planritning, kostnader och riktig 360/tour-kalla gor bostaden lattare att fjarrverifiera."),
            ("Mjuka preferenser", "+6", "Vardag, rutter och familjepreferenser passar nog for att hoja rankingen."),
            ("Platsfortroende", "+4", "Platsen ar tillrackligt konkret for att jamfora valda omraden och nara evidens."),
            ("Varme okand", "-8", "Varmeinformation saknas fortfarande, sa fortroendet sjunker."),
            ("Ett onskemal saknas", "-3", "Ett saknat onskemal sanker rang men filtrerar inte bort bostaden."),
            ("Oppen verifieringsrisk", "-5", "Kvarvarande okanda blir fragor vid visning."),
            ("Slutpoang", "=62", "50 + 8 + 10 + 6 + 4 - 8 - 3 - 5 = 62."),
        ],
    },
}


_LOCALIZED_PDF_EXAMPLE_COPY: dict[str, dict[str, tuple[str, ...] | str]] = {
    "en": {
        "source_label": "PropertyQuarry scoring engine",
        "recommendation": "Strong fit",
        "match_reasons": (
            "Selected area is respected.",
            "Verified costs, floorplan, and 360 evidence raise confidence.",
            "Commute and daily-life preferences score well.",
        ),
        "mismatch_reasons": (
            "One soft preference is missing and lowers rank without excluding.",
            "Heating detail still needs confirmation before a final decision.",
        ),
        "viewing_questions": (
            "Verify the still-missing fact with the agent.",
            "Compare the route and noise evidence during an actual viewing.",
        ),
        "postal_name": "Demo market",
        "price_display": "Example budget",
    },
    "de": {
        "source_label": "PropertyQuarry-Scoring-Engine",
        "recommendation": "Starke Passung",
        "match_reasons": (
            "Das ausgewaehlte Gebiet wird respektiert.",
            "Belegte Kosten, Grundriss und 360-Evidenz erhoehen das Vertrauen.",
            "Wege und Alltagspraeferenzen schneiden gut ab.",
        ),
        "mismatch_reasons": (
            "Ein weicher Wunsch fehlt und senkt den Rang ohne Ausschluss.",
            "Das Heizungsdetail muss vor der finalen Entscheidung bestaetigt werden.",
        ),
        "viewing_questions": (
            "Den noch fehlenden Fakt mit Makler oder Anbieter bestaetigen.",
            "Weg- und Laermbelege bei einer echten Besichtigung vergleichen.",
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


def supported_property_score_methodology_languages() -> tuple[str, ...]:
    return tuple(sorted({str(country.default_language or "en").strip().lower() for country in COUNTRIES if str(country.default_language or "").strip()}))


def _localized(language_code: object = "", *, country_code: object = "") -> dict[str, object]:
    code = normalize_language_code(language_code, country_code=str(country_code or "AT")).lower()
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
    candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    copy = _localized(language_code, country_code=country_code)
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
            "Verified facts improve confidence.",
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
) -> dict[str, object]:
    copy = _localized(language_code, country_code=country_code)
    candidate = {
        "fit_score": 62,
        "match_reasons": list(copy.get("match_reasons") or ()),
        "mismatch_reasons": list(copy.get("mismatch_reasons") or ()),
    }
    methodology = build_property_score_methodology(
        language_code=language_code,
        country_code=country_code,
        candidate=candidate,
    )
    return {
        "title": str(methodology.get("pdf_title") or "PropertyQuarry score methodology"),
        "summary": str(methodology.get("summary") or ""),
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
