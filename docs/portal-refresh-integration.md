# Automatische koppeling van de zaterdagse herpublicaties

## Wat deze uitbreiding doet

De refresh-tool maakt een nieuwe Bright-vacature en sluit de oude. Na een geslaagde VDAB-multipost bewaart ze daarom de oude Bright-ID, nieuwe Bright-ID en de publicatiereactie in een aanvullende outboxtabel in haar bestaande SQLite-statebestand. Het portaal ontvangt alleen de referenties, geen cv's of kandidaatdata.

Het portaal gebruikt de bestaande Byner-Bright-koppeling als bewijs, neemt de nieuwe Bright-ID over en voegt het nieuwe VDAB-nummer toe. Oude VDAB-nummers blijven behouden. Wachtende sollicitaties met het nieuwe nummer komen in de bestaande koppelwachtrij. Dit endpoint publiceert of sluit zelf geen vacatures en maakt geen kandidaten aan.

Onbekende oorspronkelijke Bright-ID's, gesloten Byner-vacatures en conflicterende nummers verschijnen onder **Sollicitaties per mail → Herpublicaties ter controle**. Er is geen automatische titelmatching. Oudere Bright-vacatures zonder bekende Byner-Bright-koppeling vereisen eerst een bevestigde basiskoppeling; de tool kan die identiteit niet achteraf raden.

## Configuratie (standaard uitgeschakeld)

Genereer één willekeurige geheime waarde van minstens 32 tekens, bijvoorbeeld met `openssl rand -hex 32`. Bewaar dezelfde waarde als:

Portaal `.env`:

```dotenv
BRIGHT_REFRESH_PORTAL_TOKEN=<dezelfde-geheime-waarde>
```

Python-tool `.env` of omgevingsvariabelen van de bestaande zaterdagtaak:

```dotenv
PORTAL_REFRESH_ENDPOINT=https://portal.match-jobs.be/api/integrations/bright-refresh
PORTAL_REFRESH_TOKEN=<dezelfde-geheime-waarde>
PORTAL_VDAB_JSON_PATH=
```

Laat het JSON-pad leeg totdat het echte VDAB-nummer in een geslaagde `multiposting/addVacancy`-reactie voor jobboard 3 is bevestigd. Het betreft een intern Bright-endpoint waarvan de publieke documentatie het antwoord niet specificeert. De tool behandelt momenteel een publicatie als geslaagd op basis van de bestaande Bright-successrespons; dat is geen extra controle dat VDAB de vacature al zichtbaar heeft gemaakt.

Zonder endpoint of token worden geen HTTP-doorgiften gedaan. De bestaande publicatiewerking en planning blijven behouden. Configureer de nieuwe variabelen op de host die de Python-tool werkelijk uitvoert; alleen een lokale `.env` aanpassen activeert de zaterdagtaak op een andere host niet.

## Eenmalig het VDAB-antwoord controleren

De bestaande code en fixtures bevatten geen bevestigd veld voor het VDAB-publicatienummer. De eerstvolgende gewone, geslaagde VDAB-publicatie bewaart haar response in `portal_refresh_outbox.publication_response`. Dit vraagt geen extra publicatie. Open dit SQLite-bestand lokaal of lees een reactie met een databaseviewer. Deel geen volledige configuratie of tokens.

Bevestig welk veld het nummer uit een echte sollicitatiemail bevat. Stel pas daarna `PORTAL_VDAB_JSON_PATH` in: puntnotatie voor objecten en nulgebaseerde lijstindexen. Als een gecontroleerde reactie bijvoorbeeld `{"publication":{"number":"74809933"}}` bevat, is het pad `publication.number`. Dit is uitsluitend een voorbeeld, geen vastgesteld Bright-contract. Een Bright-ID of willekeurig numeriek result mag niet als VDAB-nummer gebruikt worden.

Als het nummer niet in deze reactie zit of pas asynchroon beschikbaar komt, is een betrouwbare vervolgrespons/API/export nodig. De uitbreiding vraagt die niet op en mag dan niet als volledig automatische VDAB-nummerkoppeling beschouwd worden. Wel kan het portaal de bewezen Bright-herpublicatieketen bewaren; de status blijft `awaiting_vdab`.

## Uitrollen

1. Deploy de Laravel-wijzigingen naar het portaal en voer `php artisan migrate --force` uit.
2. Configureer de portaal-token. Als configuratie gecachet is: `php artisan config:clear` (geen algemene cache- of lockreset).
3. Deploy de Python-wijzigingen op de bestaande uitvoerhost; er zijn geen nieuwe pip-dependencies nodig. De extra SQLite-tabel wordt automatisch aangemaakt bij initialisatie.
4. Configureer endpoint en dezelfde token op die host. Controleer productie versus staging: de Bright-host moet overeenkomen met de ingestelde Bright-omgeving van het portaal.
5. Laat de gewone zaterdagtaak lopen; er hoeft niets aan het tijdstip aangepast te worden.
6. Bevestig het VDAB-JSON-pad zoals hierboven beschreven en verstuur de opgeslagen reacties opnieuw.

## Opgeslagen doorgiften opnieuw versturen

```sh
python -m src.main portal-sync
```

Dit publiceert of dupliceert geen vacatures. Het verstuurt alleen opgeslagen outbox-events. Na een verloren HTTP-antwoord wordt hetzelfde event-ID herhaald, zodat de doorgifte idempotent blijft. Netwerkfouten en tijdelijke blokkades blijven pending en worden opnieuw geprobeerd bij een volgende normale run of `portal-sync`. `needs_review` wordt bij gewone runs niet herhaald; `portal-sync` controleert die wel opnieuw nadat een basiskoppeling gecorrigeerd is.

De gewone run verstuurt oude pending-events bij aanvang en afloop, en nieuwe events direct na iedere geslaagde VDAB-multipost. Er is geen afzonderlijke permanent draaiende retry-worker toegevoegd. Indien snelle retries tussen de zaterdagruns nodig zijn, kan op dezelfde host een taak `portal-sync` gepland worden; die planning is nog niet geïnstalleerd.

Een event dat eerder de status `awaiting_vdab` kreeg, wordt na configuratie van het JSON-pad opnieuw verwerkt. Een later aangekomen VDAB-nummer zet een recentere Bright-referentie nooit terug naar een oudere week.

## Grenzen van deze wijziging

Dit verandert de bestaande volgorde van publiceren/sluiten, rollback en multipost-foutafhandeling niet. Het is geen reparatie van de oude publicatiepipeline. De SQLite-state moet bewaard blijven voor retries; een overstap naar een ander statebestand neemt de outbox niet automatisch mee.
