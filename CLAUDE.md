# LandSearch — kontekst dla Claude

## Co robi ten projekt

Scraper działek budowlanych i domów wolnostojących z czterech źródeł (domy: tylko OLX + Otodom) w okolicach zachodniej części Wrocławia. Uruchamia się co 6h przez GitHub Actions i wysyła powiadomienia Telegram tylko o nowych lub zmienionych ogłoszeniach (zmiana ceny / powierzchni). Dostępny też ręczny workflow do podglądu ostatnich ogłoszeń bez modyfikowania stanu.

## Branch roboczy

**Cały development idzie bezpośrednio na `claude/olx-land-scraper-8pek3l`.** To jest domyślny branch repo (nie `main`) — na nim działa cron GitHub Actions. Nie twórz feature branchy — commituj i pushuj wprost na ten branch. Wyjątek: jeśli użytkownik wyraźnie poprosi o PR.

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
data/
  seen_ids.json    # Persystencja — commitowana do repo przez Actions
.github/workflows/
  scrape.yml       # Cron co 6h, write permissions, commit seen_ids.json
  recent_listings.yml  # Ręczny (workflow_dispatch), read-only, wysyła 15 ostatnich
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

## Zależności

```
curl_cffi==0.7.4
beautifulsoup4==4.12.3
lxml==5.2.2
```
