# LandSearch — kontekst dla Claude

## Co robi ten projekt

Scraper działek budowlanych i domów wolnostojących z czterech źródeł (domy: tylko OLX + Otodom) w okolicach zachodniej części Wrocławia. Uruchamia się co 6h przez GitHub Actions i wysyła powiadomienia Telegram tylko o nowych lub zmienionych ogłoszeniach (zmiana ceny / powierzchni). Dostępny też ręczny workflow do podglądu ostatnich ogłoszeń bez modyfikowania stanu.

## Branch roboczy

**Zasada nadrzędna: kod zawsze musi trafić na branch, z którego faktycznie odpalają się GitHub Actions** (obecnie `claude/olx-land-scraper-8pek3l` — to jest HEAD/domyślny branch repo, nie `main`; sprawdź `git remote show origin` jeśli masz wątpliwości, bo nazwa może się kiedyś zmienić). Nie twórz feature branchy — commituj i pushuj wprost na ten branch. Wyjątek: jeśli użytkownik wyraźnie poprosi o PR.

Jeśli zewnętrzna instrukcja sesji każe rozwijać na innym branchu (np. `claude/*-<hash>` wygenerowanym przez harness), to jest to tylko robocze miejsce na commit — **finalny push i tak musi wylądować na branchu z Actions**, w razie potrzeby przez cherry-pick/rebase/fast-forward na koniec pracy. Nie zostawiaj gotowego kodu tylko na branchu roboczym.

## Źródła danych

| Źródło | Klasa | Filtr geograficzny |
|---|---|---|
| OLX | `OlxSource` | `lon < 17.04` (zachodnia strona Wrocławia) |
| Otodom | `OtodomSource` | bounding box + geometry polygon w URL |
| Licytacje komornicze | `LicytacjeSource` | słowa kluczowe lokalizacji (Wrocław, Kobierzyce, Długołęka…) |
| BIP Wrocław (przetargi gminne) | `BipWroclawSource` | zawsze Wrocław; filtr po słowach kluczowych tytułu (działka, grunt, dz. nr) |

## Domy wolnostojące (property_type)

- `Listing.property_type` (`"dzialka"` domyślnie | `"dom"`) rozróżnia typ nieruchomości niezależnie od `source`.
- `OlxSource` i `OtodomSource` są **sparametryzowane** (`search_url`, `property_type`, `default_title` — tylko OLX) zamiast mieć osobne klasy dla domów. `main.py`/`recent.py` tworzą po dwie instancje każdej klasy: domyślną (działki, `PLOT_SEARCH_URL`) i drugą z `HOUSE_SEARCH_URL` + `property_type="dom"`.
- `HOUSE_SEARCH_URL` w obu modułach to URL-e dostarczone ręcznie przez użytkownika (nie zgadywane) — mają **inny obszar geograficzny/promień** niż `PLOT_SEARCH_URL` (świadomy wybór użytkownika, nie kopia 1:1). Przy zmianie tych URL-i zachować `viewType=listing` (Otodom) i istniejące parametry lokalizacji.
- Licytacje i BIP Wrocław **nie** obsługują domów — strukturalnie ograniczone do gruntów (filtr `Notice/Filter/28` = grunty; słowa kluczowe tytułu BIP).
- `source_counts` w `main.py`/`send_scan_summary` jest kluczowany krotką `(source, property_type)`, nie samym `source` — inaczej druga instancja OLX/Otodom (domy) nadpisałaby liczniki działek pod tym samym kluczem.
- `seen.py` `make_snapshot()` zapisuje `"type"` w snapshocie; stare wpisy bez tego pola traktowane jako `"dzialka"` (fallback `.get("type", "dzialka")`).

## Monitor brukselski (mieszkania studenckie) — drugi, niezależny monitor

Osobny monitor pokoi studenckich (kot/studio) w Brukseli dla syna użytkownika:
kampus KU Leuven Brussels / Odisee / EhB (centrum), dostępność wrzesień–październik 2026,
do 700 €/mc. **Całkowicie niezależny od monitora działek**: własny plik stanu, własny
kanał Telegram, własny workflow. Awaria jednego nie dotyka drugiego.

### Kanał i sekrety

Bot `@kotobruxbot`, **osobny kanał** od działek: supergrupa „Brukselka
mieszkania", w której bot jest administratorem. Uwaga — grupa powstała jako
zwykła `group`, a Telegram zmigrował ją do `supergroup`; po migracji obowiązuje
**nowe** id (`-100…`), stare jest martwe. Nowe sekrety:
`TELEGRAM_BRUSSELS_BOT_TOKEN`, `TELEGRAM_BRUSSELS_CHAT_ID`. Monitor działek dalej
używa `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — nie mieszać.

### Architektura — dwa generyki zamiast 13 parserów

Przy 13 portalach ręczne pisanie 13 prawie identycznych parserów jest nie do utrzymania.
Wszystko portalowo-specyficzne siedzi w `scraper/brussels/config.py`:

- `HtmlSource` (`sources/html_source.py`) — sterowany selektorami CSS z configu.
- `JsonSource` (`sources/json_source.py`) — czyta osadzony JSON (`__NEXT_DATA__`,
  `window.__NUXT__`, `application/json`, `ld+json`); **dziedziczy po `HtmlSource`
  i cofa się do parsowania kart**, gdy JSON-a nie ma.

`SOURCES[nazwa]["enabled"] = False` wyłącza zepsuty portal bez zmiany kodu — przy
13 źródłach to najważniejszy zawór bezpieczeństwa. `SOURCES[...]["card"]` to
**lista kandydatów** selektorów; wygrywa pierwszy, który da najwięcej kart z linkiem.

### Źródła (13)

| Grupa | Portale |
|---|---|
| Rdzeń | Brukot (`/en/new`, `/en/updated`), Immoweb |
| Kotowe | Kotplace, Skot, Kotzoeker, Student.be |
| Ogłoszeniowe | 2ememain, Immovlan, Zimmo, Appartager |
| Agregatory | HousingAnywhere, Spotahome, Erasmus Play |

Żaden nie ma darmowego, oficjalnego API do **czytania** ofert (sprawdzone):
Immoweb API służy tylko do publikowania, HousingAnywhere API działa w drugą
stronę (partner wystawia feed) i nie przyjmuje nowych partnerów.

### Kluczowe decyzje

- **Selektory są zgadywane, dopóki nie potwierdzi ich probe.** Sandbox deweloperski
  ma zablokowany egress do wszystkich tych domen **i do `api.telegram.org`**.
  `python -m scraper.brussels.probe [portale]` odpala się na runnerze Actions
  (workflow `brussels_probe.yml`) i wypisuje realną strukturę strony do logu:
  `robots.txt`, obecność RSS/sitemap, tagi `<script>`, ścieżki kluczy JSON,
  trafienia selektorów i przycięte próbki kart. Log czyta się przez
  `mcp__github__get_job_logs`. **Nie zgaduj selektorów bez probe'a.**
- **Brak danych nigdy nie odrzuca ogłoszenia.** Nieznana cena/data/gmina przechodzą
  filtr. Lepiej jedno powiadomienie za dużo niż przegapiony pokój.
- **ID z prefiksem portalu** (`brukot:12345`). `data/seen_ids.json` (działki) trzyma
  ID z OLX i Otodomu w jednej płaskiej przestrzeni nazw — utajona kolizja, której
  przy 13 portalach nie powtarzamy.
- **Tryb zasiewu**: pusty `data/brussels_seen.json` → pierwszy przebieg zapisuje stan
  i wysyła **tylko podsumowanie**, zamiast wysypać setki ofert.
- **`NOTIFY_CAP_PER_RUN = 30`**: nadmiar **nie jest** oznaczany jako widziany, więc
  wraca w następnym skanie zamiast zniknąć.
- **Dedup między portalami**: klucz `cena|gmina|metraż`, aktywny **tylko gdy wszystkie
  trzy pola są znane** — częściowy klucz sklejałby różne oferty.
- **Szybkie odpuszczanie portalu**: gdy pierwszy URL portalu padnie, pomijamy resztę
  jego URL-i. Bez tego 13 niedostępnych portali to ~30 min samego backoffu.
- `scraper/brussels/seen.py` diffuje `("price", "available")`, nie `("price", "area")`.

### Stan portali — żywy dry-run (run 33298338982, 2026-08-30)

**242 oferty z 5 działających portali, 125 po filtrach.** Zielony, 2 min.
**Cena wypełniona w 100% na każdym aktywnym źródle.**

| Portal | Ofert | Braki pól (po filtrach) | Jak czytane |
|---|---|---|---|
| **Brukot** | 92 | cena 0, gmina 0, metraż 0, data 22/81 | `article.listing-teaser` + `data-listing-id`. Cena **bez opłat** („excl. charges"), więc `charges=None` i realny koszt bywa wyższy. |
| **Immoweb** | 60 | cena 0, gmina 0, metraż i data brak | `article.card--result`. **Cena w atrybucie, nie w tekście**: `<iw-price :price='{"mainValue":450,"additionalValue":100}'>` — `get_text()` atrybutów nie widzi, stąd wcześniejsze 67/69 bez ceny. `mainValue`/`additionalValue` to czynsz i opłaty **osobno**, więc suma jest uczciwa. ID i gmina ze ścieżki URL-a. |
| **Immovlan** | 40 | cena 0, gmina 0 | `article.list-view-item` **z fallbackiem na `article`** — probe widział pierwszą klasę, a żywy przebieg minutę później już nie; serwis zmienia markup po wizycie na stronie głównej. Cena w `strong.list-item-price`. |
| **Appartager** | 30 | cena 0, gmina 0 | `div.listing_item`. Tytuł i gmina ze sluga URL-a (`/colocation-ixelles-elsene/studio-a-ixelles/`), bo w karcie tytułu nie ma — bez tego tytuł był ścianą opisu. |
| **Erasmus Play** | 20 | cena 0, gmina 10/11 | `ld+json` Schema.org, tablica `offers[]`: `sku`, `name`, `url`, `price`, `availabilityStarts`. Pewniejsze niż markup Nuxta, którego klasy to hashe builda. |

Wyłączone lub niedziałające: Skot i Kotzoeker (JS, wymagają Playwrighta),
Spotahome (jedna „oferta" to nagłówek strony), Zimmo (403), 2ememain (404),
Student.be (React-on-Rails), HousingAnywhere, Kotplace (throttluje IP runnera —
zamiast tego jego darmowy alert mailowy).

**Bramka jakości** (`drop_mis_parsed_sources` w `main.py`): źródło z ≥5 ofertami,
z których mniej niż połowa ma cenę, jest **wstrzymywane** i nazwane w
podsumowaniu jako problem parsera. „Brak danych nie odrzuca" jest słuszne dla
pojedynczej luki i błędne dla zepsutego parsera — to rozróżnia te przypadki.
Małych próbek nie ocenia.

### Testy

`tests/` — 50 przypadków na stdlib `unittest`, bez nowych zależności,
uruchamiane w `brussels.yml` **przed** krokiem scrapującym, żeby zepsuty parser
wywalił joba zamiast po cichu wysłać śmieci.

```bash
python -m unittest discover -s tests
```

Testy sprawdzają **wartości pól** na markupie z logów probe'a, nie samo „nie
rzuciło wyjątkiem". To rozróżnienie jest sednem: każda awaria parsera w tej
sesji wyglądała zdrowo w liczniku ofert. Dwa przypadki pilnują `format_message`
i domyślnych `get_changes` monitora działek, żeby prace nad Brukselą nie
zmieniły po cichu tego, co wysyła stary monitor.

Testy chronią przed regresją **kodu**, nie przed zmianą stron — od tego jest ⚠️
przy zerze w podsumowaniu Telegram i ponowny probe.

### Filtr lokalizacji

`parsing.is_outside_brussels()` odsiewa oferty spoza Brukseli. **Celowo
asymetryczny**: odrzuca tylko to, co da się jednoznacznie rozpoznać jako gdzie
indziej (belgijski kod pocztowy poza 1000–1210 albo nazwa innego miasta
studenckiego bez żadnej brukselskiej gminy obok). Nieznana lokalizacja
przechodzi — spójnie z zasadą „brak danych nie odrzuca". Zna wszystkie 19 gmin
Regionu Stołecznego w obu językach urzędowych.

Jest potrzebny, bo `robots.txt` Student.be zabrania URL-i z query stringiem, więc
jedyny dozwolony adres zwraca oferty z **całej Belgii** — bez tego filtru pokoje
z Leuven i Gandawy szłyby na Telegram jako trafienia.

**Zasada: przed dopisaniem selektorów przeczytaj `robots.txt` z logu probe'a.**
Kilka portali ma zakazy wykluczające oczywiste podejście (endpoint JSON u Kotplace
i Skot, query string u Student.be i Kotplace).

**Autodetekcja siatki ofert** (`find_repeated_structures` w `probe.py`) rozgryzła
Appartager i Kotzoeker bez ręcznego oglądania HTML-a: szuka rodzeństwa o wspólnym
`tag.klasa`, gdzie każdy element ma link, i promuje grupy zawierające cenę. Uwaga —
promowanie po cenie potrafi wypchnąć na górę widget cenowy zamiast ofert, więc
wynik trzeba przejrzeć, a nie brać pierwszy z brzegu.

### Zmiany w kodzie współdzielonym (wstecznie zgodne)

- `scraper/http.py` — **nowy**, `make_session()` + `get_html()` z backoffem `[2,8,32]`.
  Cztery źródła działkowe mają własne kopie tej pętli i **celowo zostały nietknięte**;
  nowy kod używa tego modułu.
- `scraper/seen.py` — `load_seen(path=SEEN_FILE)`, `save_seen(seen, path=SEEN_FILE)`,
  `get_changes(old, new, fields=("price","area"))`. Same domyślne argumenty, zachowanie
  dla działek bez zmian.
- `scraper/notify.py` — wydzielone `send_message(text, token, chat_id)` z pętlą retry/429;
  `send_telegram` i `send_scan_summary` wołają je. `format_message` **nietknięte**.

### Workflowy

| Plik | Rola |
|---|---|
| `.github/workflows/brussels.yml` | Cron `30 */6 * * *` (przesunięty o 30 min od `scrape.yml`, żeby oba nie pushowały naraz), `contents: write`, `concurrency`, działający input `dry_run`, commit `data/brussels_seen.json` z pętlą ponawiania pushu |
| `.github/workflows/brussels_probe.yml` | Ręczny, `contents: read`. Input `portals` (partiami, żeby log był czytelny) + opcjonalny `chat_id_lookup` (`scraper/brussels/chatid.py` — wypisuje tylko tytuł i id czatu, **nigdy tokena**) |

## Kluczowe decyzje techniczne

- **curl_cffi** z `impersonate="chrome120"` zamiast `requests` — OLX/Otodom nie blokują GitHub Actions gdy używamy Chrome TLS fingerprint. Bez proxy.
- **OLX**: dane ogłoszeń w `<script type="application/json">` tagach. Fallback: parsowanie kart HTML.
- **Otodom**: dane w `<script id="__NEXT_DATA__">` (Next.js). Wymaga `viewType=listing` w URL (nie `viewType=map`). Przed scrapingiem search page: GET homepage żeby dostać cookies.
- **Licytacje**: tabela HTML `licytacje.komornik.pl/Notice/Filter/28` (filter 28 = grunty). Paginacja do 10 stron.
- **BIP Wrocław**: `bip.um.wroc.pl/przetargi-nieruchomosci/3/10`. Dwa etapy: lista przetargów → szczegóły każdej działki (cena/adres/powierzchnia wyciągane ze struktury tabelarycznej strony szczegółowej przez `_extract_table_field()`).
- **Enrich z utilities**: `BipWroclawSource.fetch_utilities()` zwraca dodatkowo `_price`, `_location`, `_area` w słowniku utilities. `main.py` przenosi te wartości do pól `Listing` przez `_enrich_from_utilities()` przed zapisem snapshotu.
- **seen_ids.json**: dict `{id: {price, area, type}}` — nie plain lista. Migracja ze starego formatu (lista) odbywa się automatycznie w `load_seen()`. Plik jest commitowany do repo po każdym uruchomieniu przez Actions (`[skip ci]`).
- **Zmiana detekcja**: `get_changes()` w `seen.py` — stary snapshot `{}` (migracja) nie triggeruje false positive bo warunek `old_val is None and old == {}` go wyklucza.
- **git push**: workflow robi `git pull --rebase` przed `git push` bo code commity mogą trafić do brancha w trakcie runu i odrzucić push.

## Telegram

- Bot: `@kosdzialki_bot`
- Kanał: "Dzialki" (prywatny), chat_id: `-1004333744933`
- Sekrety GitHub: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Format: HTML parse_mode, emoji, `<s>stara wartość</s>` przy zmianach ceny/powierzchni

## Zameldowanie po skanie

- Po każdym skanie wysyłane jest podsumowanie na tę samą grupę Telegram (bez dodatkowych sekretów)
- Format: liczba ogłoszeń per (źródło, typ nieruchomości) + łączna liczba nowych/zmienionych powiadomień

## Architektura

```
scraper/
  main.py          # Orkiestrator: fetch → diff → notify → save
  seen.py          # load/save/snapshot/get_changes — persystencja seen_ids.json
  notify.py        # format_message, send_telegram (retry 429), send_scan_summary
  recent.py        # Tryb ręczny: wysyła N ostatnich ogłoszeń BEZ modyfikowania seen_ids.json
  models.py        # Listing dataclass: id, title, url, location, source, price, area, utilities, property_type
  sources/
    base.py        # BaseSource ABC: fetch_listings() + fetch_utilities()
    olx.py         # OLX fetch + geo filter + utilities keyword search; PLOT_SEARCH_URL/HOUSE_SEARCH_URL
    otodom.py      # Otodom fetch via __NEXT_DATA__ + utilities; PLOT_SEARCH_URL/HOUSE_SEARCH_URL
    licytacje.py   # licytacje.komornik.pl — licytacje komornicze, grunty
    bip_wroclaw.py # bip.um.wroc.pl — przetargi gminne, tylko działki
  http.py          # Współdzielony transport: make_session + get_html (używany przez brussels/)
  brussels/        # DRUGI, NIEZALEŻNY MONITOR — mieszkania studenckie w Brukseli
    main.py        # Orkiestrator: fetch → filtr → dedup → diff → notify → save
    config.py      # 13 portali: URL-e, selektory (kandydaci), filtry, flagi enabled
    models.py      # KotListing dataclass + dup_key()
    parsing.py     # Parsery pól: € (formaty EU), m², daty EN/FR/NL, kod pocztowy
    seen.py        # data/brussels_seen.json; diffuje (price, available)
    notify.py      # format_message (PL) + send_scan_summary
    probe.py       # Rozpoznanie struktury stron — tylko przez Actions
    chatid.py      # Ustalenie chat_id przez getUpdates — tylko przez Actions
    sources/
      base.py          # KotSource ABC
      html_source.py   # GENERYK: karty HTML wg selektorów z configu
      json_source.py   # GENERYK: osadzony JSON, z fallbackiem na HtmlSource
data/
  seen_ids.json        # Persystencja działek — commitowana przez Actions
  brussels_seen.json   # Persystencja Brukseli — osobny plik, osobny workflow
.github/workflows/
  scrape.yml       # Cron co 6h, write permissions, commit seen_ids.json
  recent_listings.yml  # Ręczny (workflow_dispatch), read-only, wysyła 15 ostatnich
  brussels.yml         # Cron co 6h (+30 min), write, commit brussels_seen.json
  brussels_probe.yml   # Ręczny, read-only, rozpoznanie struktury portali
```

## Pliki kluczowe

| Plik | Opis |
|---|---|
| `scraper/main.py` | Orkiestrator: fetch → diff → notify → save |
| `scraper/seen.py` | load/save/snapshot/get_changes |
| `scraper/notify.py` | format_message, send_telegram (retry 429) |
| `scraper/recent.py` | Ręczny podgląd 15 ostatnich ogłoszeń (OLX + Otodom, działki + domy), nie modyfikuje seen_ids.json |
| `scraper/models.py` | Listing dataclass |
| `scraper/sources/base.py` | BaseSource ABC |
| `scraper/sources/olx.py` | OLX fetch + utilities + geo filter |
| `scraper/sources/otodom.py` | Otodom fetch + utilities via __NEXT_DATA__ |
| `scraper/sources/licytacje.py` | Licytacje komornicze — grunty w obszarze Wrocławia |
| `scraper/sources/bip_wroclaw.py` | BIP Wrocław — przetargi gminne działek |
| `data/seen_ids.json` | Persystencja — commitowana do repo |
| `.github/workflows/scrape.yml` | Cron co 6h, write permissions |
| `.github/workflows/recent_listings.yml` | Ręczny workflow, read-only |
| `scraper/http.py` | Współdzielony transport HTTP (curl_cffi + backoff) |
| `scraper/brussels/` | Monitor mieszkań studenckich w Brukseli — patrz sekcja wyżej |
| `data/brussels_seen.json` | Persystencja Brukseli — osobna od działek |
| `.github/workflows/brussels.yml` | Monitor brukselski, cron co 6h |
| `.github/workflows/brussels_probe.yml` | Rozpoznanie struktury portali, ręczny |

## Zależności

```
curl_cffi==0.7.4
beautifulsoup4==4.12.3
lxml==5.2.2
```
