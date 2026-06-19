# LandSearch — OLX Działki Wrocław

Automatyczny scraper działek budowlanych z OLX.pl. Sprawdza co 4 godziny nowe ogłoszenia w okolicach Wrocławia (zachodnia strona, do 15 km, max 500 000 zł, min 800 m²) i wysyła powiadomienia na kanał Telegram.

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

## Dodanie kolejnego źródła

1. Utwórz `scraper/sources/gratka.py` implementujące `BaseSource`
2. W `scraper/main.py` dodaj `GratkaSource()` do listy `sources`

## Struktura

```
scraper/
  main.py          # Orkiestrator
  models.py        # Listing dataclass
  seen.py          # Śledzenie widzianych ogłoszeń
  notify.py        # Telegram
  sources/
    base.py        # Abstrakcja źródła
    olx.py         # OLX scraper
data/
  seen_ids.json    # Auto-aktualizowany po każdym uruchomieniu
.github/workflows/
  scrape.yml       # Cron co 4h
```
