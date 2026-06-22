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
        "positive_label": "Signals lifting the score",
        "negative_label": "Signals reducing confidence or score",
        "neutral_note": "Exact weights can vary by market and search mode, but hard rules, evidence quality, soft preferences, and feedback are always separated.",
    },
    "de": {
        "title": "Blick hinter den Score",
        "subtitle": "Wie PropertyQuarry aus einem Inserat eine persoenliche Passung macht.",
        "summary": "Der Score ist keine Portal-Beliebtheit. Er ist eine 0-100 Einschaetzung der persoenlichen Passung aus harten Regeln, verifizierten Fakten, weichen Praeferenzen, Wegen, Umfeldsignalen, fehlenden Fakten und gespeichertem Feedback.",
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
            ("4. Weiche Bewertung", "Nice-to-have, Strong wish, Avoid und Distanzen bewegen den Score. Sie filtern nicht, solange sie nicht als harte Regel markiert sind."),
            ("5. Vertrauen und offene Punkte", "Fehlende Kosten, unklare Heizung, kein Grundriss, schwache Lagebelege oder veraltete Quellen senken das Vertrauen und erzeugen Rueckfragen."),
            ("6. Ranking und Reparatur", "Der Rang kombiniert Passung, Evidenz, Aktualitaet, Duplikate und Reparaturstatus. Gescheiterte Quellen werden getrennt repariert."),
        ],
        "examples": [
            ("Falscher Bezirk", "Ein Inserat in 1220 wird ausgeschlossen, wenn nur 1010 gewaehlt ist. Das ist eine harte Regel."),
            ("Balkon als Nice-to-have", "Fehlt der Balkon nur als Wunsch, bleibt das Objekt sichtbar und verliert lediglich Score."),
            ("Sicherer Schulweg", "Ein plausibel sicherer Weg zur Schule oder zum Kindergarten kann den Score erhoehen."),
            ("Kosten fehlen", "Fehlende Betriebskosten senken Vertrauen und werden als Rueckfrage markiert, statt erfunden zu werden."),
            ("Echte Tour vorhanden", "Matterport, 3DVista oder eine verifizierte 360-Quelle erhoeht die Remote-Screening-Sicherheit."),
        ],
        "bands": [("0-34", "Nur beobachten"), ("35-44", "Moegliche Passung"), ("45-59", "Gute Passung"), ("60+", "Starke Passung")],
        "pdf_title": "Wie der PropertyQuarry-Score berechnet wird",
        "candidate_title": "Score-Lesart fuer dieses Objekt",
        "positive_label": "Signale, die den Score heben",
        "negative_label": "Signale, die Vertrauen oder Score senken",
        "neutral_note": "Die genaue Gewichtung kann je Markt und Suchmodus variieren, aber harte Regeln, Evidenz, weiche Praeferenzen und Feedback bleiben getrennt.",
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
        "positive_label": str(copy.get("positive_label") or "Signals lifting the score"),
        "negative_label": str(copy.get("negative_label") or "Signals reducing confidence or score"),
        "neutral_note": str(copy.get("neutral_note") or ""),
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
    candidate = {
        "fit_score": 62,
        "match_reasons": [
            "Selected area is respected.",
            "Verified costs, floorplan, and 360 evidence raise confidence.",
            "Commute and daily-life preferences score well.",
        ],
        "mismatch_reasons": [
            "One soft preference is missing and lowers rank without excluding.",
            "Heating detail still needs confirmation before a final decision.",
        ],
    }
    methodology = build_property_score_methodology(
        language_code=language_code,
        country_code=country_code,
        candidate=candidate,
    )
    return {
        "title": str(methodology.get("pdf_title") or "PropertyQuarry score methodology"),
        "summary": str(methodology.get("summary") or ""),
        "source_label": "PropertyQuarry scoring engine",
        "language_code": str(methodology.get("language_code") or "en"),
        "country_code": str(country_code or "").strip().upper(),
        "fit_score": candidate["fit_score"],
        "recommendation": "Strong fit",
        "match_reasons": list(candidate["match_reasons"]),
        "mismatch_reasons": list(candidate["mismatch_reasons"]),
        "viewing_questions": [
            "Verify the still-missing fact with the agent.",
            "Compare the route and noise evidence during an actual viewing.",
        ],
        "property_facts": {
            "language_code": str(methodology.get("language_code") or "en"),
            "country_code": str(country_code or "").strip().upper(),
            "postal_name": "Demo market",
            "price_display": "Example budget",
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
