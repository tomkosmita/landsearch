# LandSearch — Działki Wrocław

Automatyczny scraper działek budowlanych z OLX.pl i Otodom.pl. Sprawdza co 6 godzin nowe ogłoszenia w okolicach zachodniej części Wrocławia i wysyła powiadomienia na kanał Telegram. Wysyła tylko nowe ogłoszenia lub te ze zmienioną ceną/powierzchnią.

## Filtry

**OLX**: zachodnia strona Wrocławia (`lon < 17.04`), działki budowlane, max 500 000 zł, min 800 m²

**Otodom**: obszar geograficzny zachodniego Wrocławia (polygon), `plotType=BUILDING`, max 600 000 zł, limit 36

## Konfiguracja (jednorazowo)

### 1. Uprawnienia GitHub Actions

Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save.

### 2. GitHub Secrets

Settings → Secrets and variables → Actions → New repository secret:

| Nazwa | Wartość |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token bota z BotFather |
| `TELEGRAM_CHAT_ID` | ID kanału (np. `-1004333744933`) |

Aby pobrać Chat ID kanału:
1. Dodaj bota jako administratora kanału
2. Wyślij dowolną wiadomość na kanał
3. Otwórz: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Znajdź pole `"chat":{"id": ...}` — skopiuj wartość

### 3. Test manualny

Actions → **Land Plot Scraper** → Run workflow

## Jak to działa

1. Co 6 godzin GitHub Actions uruchamia scraper
2. Pobiera listę ogłoszeń z OLX i Otodom
3. Porównuje z `data/seen_ids.json` (przechowuje ID + cena + powierzchnia)
4. Dla nowych ogłoszeń: pobiera stronę szczegółową, sprawdza media, wysyła na Telegram
5. Dla zmienionych ogłoszeń (cena / powierzchnia): wysyła alert ze starą i nową wartością
6. Zapisuje `seen_ids.json` z powrotem do repo (commit `[skip ci]`)

## Dodanie kolejnego źródła

1. Utwórz `scraper/sources/gratka.py` implementujące `BaseSource`
2. W `scraper/main.py` dodaj `GratkaSource()` do listy `sources`

## Struktura

```
scraper/
  main.py          # Orkiestrator
  models.py        # Listing dataclass
  seen.py          # Śledzenie widzianych ogłoszeń (ID + snapshot ceny/powierzchni)
  notify.py        # Telegram (HTML, obsługa 429, format zmian)
  sources/
    base.py        # Abstrakcja źródła
    olx.py         # OLX scraper (curl_cffi Chrome impersonation)
    otodom.py      # Otodom scraper (__NEXT_DATA__ JSON)
data/
  seen_ids.json    # Auto-aktualizowany po każdym uruchomieniu
.github/workflows/
  scrape.yml       # Cron co 6h
```
