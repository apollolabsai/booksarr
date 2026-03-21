# Booksarr

A Docker-based ebook library manager inspired by Radarr/Sonarr. Scans your local ebook collection, enriches metadata from [Hardcover](https://hardcover.app), and shows all books by each author — marking which you own and which you're missing.

## Features

- **Library Scanning** — Automatically discovers EPUBs organized in `Author/Book/` folders with Calibre `metadata.opf` support
- **Hardcover Integration** — Fetches complete author catalogs, book metadata, series info, covers, and author photos via the Hardcover GraphQL API
- **Series Reading Order** — Books grouped by series with position badges (supports novellas at positions like 1.5, 2.5)
- **Owned vs Missing** — Green checkmark badge on owned books; missing books shown dimmed with dashed borders
- **Incremental Sync** — Only fetches new authors and books on subsequent scans; recently synced authors are skipped (7-day cooldown). Full refresh available when needed
- **Smart Matching** — Matches local files to Hardcover entries by ISBN first, then normalized title similarity
- **Image Caching** — Author photos and book covers cached locally for fast loading
- **Filtering** — Excludes unreleased books and non-English books (unless locally owned)
- **Grid & Table Views** — Toggle between card grid and compact table layout on all pages
- **Dark Theme** — Radarr/Sonarr-style dark UI with emerald accents
- **Docker** — Multi-stage Docker build with LinuxServer-style PUID/PGID support

## Quick Start

### docker-compose.yml

```yaml
services:
  booksarr:
    image: apollolabsai/booksarr:latest
    container_name: booksarr
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Los_Angeles
      - HARDCOVER_API_KEY=         # Optional: or set via Settings UI
      - GOOGLE_BOOKS_API_KEY=      # Optional but recommended: for accurate publish dates (free)
    volumes:
      - ./config:/config           # Database, settings, image cache
      - /path/to/your/ebooks:/books:ro
    ports:
      - 8889:8889
    restart: unless-stopped
```

```bash
docker-compose up -d
```

Then open `http://localhost:8889`.

### Library Structure

Booksarr expects your ebooks organized by author:

```
/books/
  Brandon Sanderson/
    The Way of Kings (123)/
      The Way of Kings - Brandon Sanderson.epub
      metadata.opf    # Calibre metadata (optional but recommended)
      cover.jpg       # Cover image (optional)
    Mistborn (456)/
      ...
  John Grisham/
    ...
```

### Setup

1. Navigate to **Settings**
2. Enter your [Hardcover API key](https://hardcover.app/account/api)
3. *(Optional but recommended)* Enter a [Google Books API key](https://console.cloud.google.com/apis/library/books.googleapis.com) for more accurate publish dates — free, 1,000 requests/day
4. Click **Scan Library**
5. Browse your collection on the **Authors** and **Books** pages

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PUID` | `1000` | User ID for file permissions |
| `PGID` | `1000` | Group ID for file permissions |
| `TZ` | `UTC` | Timezone |
| `HARDCOVER_API_KEY` | | Hardcover API key (overrides UI setting) |
| `GOOGLE_BOOKS_API_KEY` | | Optional. Google Books API key for accurate publish dates (overrides UI setting) |
| `CONFIG_DIR` | `/config` | Config/database directory |
| `BOOKS_DIR` | `/books` | Ebook library mount point |
| `PORT` | `8889` | Web UI port |

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), SQLite
- **Frontend:** React 18, TypeScript, Vite, TanStack Query, Tailwind CSS
- **Container:** Multi-stage Docker build (Node 20 + Python 3.12)

## Building from Source

```bash
git clone https://github.com/apollolabsai/booksarr.git
cd booksarr
docker-compose up --build
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/authors` | GET | List authors (sort, search) |
| `/api/authors/:id` | GET | Author detail with books and series |
| `/api/books` | GET | List books (sort, filter, search) |
| `/api/books/:id` | GET | Book detail |
| `/api/library/scan` | POST | Trigger library scan (`?force=true` for full refresh) |
| `/api/library/status` | GET | Scan progress |
| `/api/settings` | GET/PUT | App settings |
| `/api/health` | GET | Health check |
