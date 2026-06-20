# LandSearch — kontekst dla Claude

## Co robi ten projekt

Scraper działek budowlanych z OLX.pl i Otodom.pl w okolicach zachodniej części Wrocławia. Uruchamia się co 6h przez GitHub Actions i wysyła powiadomienia Telegram tylko o nowych lub zmienionych ogłoszeniach (zmiana ceny / powierzchni).

## Branch roboczy

**Cały development idzie bezpośrednio na `claude/olx-land-scraper-8pek3l`.** To jest domyślny branch repo (nie `main`) — na nim działa cron GitHub Actions. Nie twórz feature branchy — commituj i pushuj wprost na ten branch. Wyjątek: jeśli użytkownik wyraźnie poprosi o PR.

## Kluczowe decyzje techniczne

- **curl_cffi** z `impersonate="chrome120"` zamiast `requests` — OLX/Otodom nie blokują GitHub Actions gdy używamy Chrome TLS fingerprint. Bez proxy.
- **OLX**: dane ogłoszeń w `<script type="application/json">` tagach. Filtr geograficzny `lon < 17.04` (zachodnia strona Wrocławia).
- **Otodom**: dane w `<script id="__NEXT_DATA__">` (Next.js). Wymaga `viewType=listing` w URL (nie `viewType=map`). Przed scrapingiem search page: GET homepage żeby dostać cookies.
- **seen_ids.json**: dict `{id: {price, area}}` — nie plain lista. Migracja ze starego formatu (lista) odbywa się automatycznie w `load_seen()`. Plik jest commitowany do repo po każdym uruchomieniu przez Actions (`[skip ci]`).
- **Zmiana detekcja**: `get_changes()` w `seen.py` — stary snapshot `{}` (migracja) nie triggeruje false positive bo warunek `old == {}` go wyklucza.
- **git push**: workflow robi `git pull --rebase` przed `git push` bo code commity mogą trafić do brancha w trakcie runu i odrzucić push.

## Telegram

- Bot: `@kosdzialki_bot`
- Kanał: "Dzialki" (prywatny), chat_id: `-1004333744933`
- Sekrety GitHub: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Format: HTML parse_mode, emoji, `<s>stara wartość</s>` przy zmianach

## Zameldowanie po skanie

- Po każdym skanie wysyłana jest podsumowanie na tę samą grupę Telegram (bez dodatkowych sekretów)
- Format: liczba ogłoszeń per źródło + łączna liczba nowych/zmienionych powiadomień

## Pliki kluczowe

| Plik | Opis |
|---|---|
| `scraper/main.py` | Orkiestrator: fetch → diff → notify → save |
| `scraper/seen.py` | load/save/snapshot/get_changes |
| `scraper/notify.py` | format_message, send_telegram (retry 429) |
| `scraper/sources/olx.py` | OLX fetch + utilities + geo filter |
| `scraper/sources/otodom.py` | Otodom fetch + utilities via __NEXT_DATA__ |
| `data/seen_ids.json` | Persystencja — commitowana do repo |
| `.github/workflows/scrape.yml` | Cron co 6h, write permissions |

## Zależności

```
curl_cffi==0.7.4
beautifulsoup4==4.12.3
lxml==5.2.2
```
