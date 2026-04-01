# Booksarr

Booksarr is a Docker-based ebook library manager inspired by Radarr/Sonarr. It scans your local ebook collection, matches files against full author catalogs, and gives you visibility into all the books an author has written, not just the ones you already own. It highlights owned titles inside that larger catalog, enriches metadata from multiple sources, and gives you tools to review hidden books, override covers, refresh individual titles, search IRC for missing books, and track scan outcomes.

## Screenshots

![Authors view](media/authorpng.png)

![Author detail view](media/authordetail.png)

![Books view](media/books.png)

## Features

- **Local library scanning** — Discovers EPUBs from your mounted library, reads sidecar `metadata.opf` when present, and falls back to internal EPUB metadata and filename parsing.
- **Full author catalog visibility** — Shows the broader author bibliography alongside your collection so you can see what you own, what is missing, and where you are complete.
- **Multi-source metadata** — Uses [Hardcover](https://hardcover.app), Google Books, Open Library, and Wikimedia where appropriate for books, covers, publish dates, ISBNs, and author portraits.
- **Configurable visibility profiles** — Control which books are shown with profile rules such as non-English, upcoming releases, pending Hardcover records, likely collections, and valid ISBN requirements.
- **Hidden books review** — Dedicated hidden-books page shows every hidden title and every rule that hid it, with support for manual hide/unhide overrides.
- **Series-aware browsing** — Author pages group books by series and preserve reading-order positions.
- **Owned-book highlighting** — Marks which books you own inside the full visible catalog, including duplicate copy counts when the same title exists more than once locally.
- **Poster and portrait management** — Manually choose a book poster or author portrait from available candidates and keep that choice through future refreshes.
- **Per-book actions** — Refresh one book from scratch, download its local file, hide it, or launch an IRC search from either table or grid view.
- **IRC book acquisition workflow** — Search for a missing book from the book UI, get parsed results back in the app, download a selection over DCC, extract supported archives, and optionally move the result straight into your library.
- **API usage and scan summaries** — Settings shows daily API call counts plus a persisted last-run dashboard with counts for owned books found, authors added, books added, hidden books, and lookup failures.
- **Grid and table views** — Browse books in poster view or compact table view, with badges for owned copies, ISBN validity, and Google/Open Library matches.

## Quick Start

### docker-compose.yml

```yaml
services:
  booksarr:
    image: powertowerpro/booksarr:latest
    container_name: booksarr
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Los_Angeles
      - HARDCOVER_API_KEY=
      - GOOGLE_BOOKS_API_KEY=    # Optional but recommended
      - DOWNLOADS_DIR=/downloads # Used by IRC downloads
    volumes:
      - ./config:/config
      - ./downloads:/downloads
      - /path/to/your/ebooks:/books
    ports:
      - 8889:8889
    restart: unless-stopped
```

```bash
docker compose up -d
```

If you plan to use PIA VPN routing for IRC, the host must expose `/dev/net/tun` to Docker and allow `NET_ADMIN`. On some VPS, rootless Docker, or nested-container setups, TUN devices may be unavailable.

To track the published development image instead, use:

```yaml
image: powertowerpro/booksarr:dev
```

Then open `http://localhost:8889`.

### Library Structure

Booksarr expects ebooks under your `/books` mount, typically organized by author:

```text
/books/
  Brandon Sanderson/
    The Way of Kings (123)/
      The Way of Kings - Brandon Sanderson.epub
      metadata.opf
      cover.jpg
  John Grisham/
    Theodore Boone 04 - The Activist/
      John Grisham - [Theodore Boone 04] - The Activist.epub
```

### Setup

1. Open **Settings > API Keys** and enter your Hardcover API key.
2. Optionally add a Google Books API key for better date and ISBN enrichment.
3. Open **Settings > Profiles** and adjust **Book Visibility** rules.
4. Open **Settings > Metadata Refreshes** and run **Scan Library** or **Full Refresh**.
5. Optionally configure **Settings > IRC** if you want IRC search/download support.
6. If you want IRC traffic routed through PIA, enable **VPN Routing for IRC** in **Settings > IRC** and enter your PIA account credentials plus region.
7. Use the magnifying-glass **IRC Search** action on any book to search your configured IRC channel and download a match directly from the app.

## Configuration

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `PUID` | `1000` | User ID for file permissions |
| `PGID` | `1000` | Group ID for file permissions |
| `TZ` | `UTC` | Container timezone |
| `HARDCOVER_API_KEY` | | Hardcover API key, also configurable in the UI |
| `GOOGLE_BOOKS_API_KEY` | | Optional Google Books API key, also configurable in the UI |
| `CONFIG_DIR` | `/config` | Config, SQLite database, cache, and app state directory |
| `BOOKS_DIR` | `/books` | Mounted ebook library directory |
| `DOWNLOADS_DIR` | `/downloads` | IRC download staging directory |
| `IRC_STATE_DIR` | `/config/irc` | IRC worker state directory |
| `PORT` | `8889` | Web UI port |

## Settings Pages

- **API Keys** — Hardcover and Google Books keys, plus the daily API usage table.
- **Profiles** — Book visibility rules and access to the hidden-books review page.
- **Metadata Refreshes** — Library scan, full refresh, scan schedule, last run summary, and reset actions.
- **IRC** — IRC connection settings, auto-move toggle, connection status, and recent search/download activity.
- **Logs** — In-app log viewer and log download endpoint.

## Notable UI Workflows

- **Hidden books review** — Visit `/books/hidden` to see all hidden titles, the rules that hid them, and manual unhide controls.
- **Manual poster selection** — Use the poster picker from table view or the three-dot grid menu to compare cover candidates by source, resolution, and ratio fit.
- **Manual portrait selection** — On author pages, use the hover menu on the portrait to choose a replacement author image.
- **Single-book refresh** — Refresh one book from scratch to re-parse local metadata, clear imported metadata, and rerun external lookups and cover selection.
- **Book download** — Download an owned local file directly from table view or from the grid action menu.
- **IRC search and import** — Launch a book search from the magnifying-glass action, review parsed results inside the dialog, watch live download/import status, and let Booksarr mark the title owned after import.

## IRC Integration

Booksarr supports one IRC profile at a time from **Settings > IRC**.

- Search any visible book directly from the grid or table view with the **IRC Search** action.
- Optionally route IRC control connections and DCC transfers through a PIA OpenVPN tunnel.
- Sends `@search {query}` to the configured public channel.
- Waits for a DCC-delivered `.zip` archive containing a single `.txt` result file.
- Parses each downloadable result line and stores the exact command needed to request that file.
- Shows live status updates in the UI while a selection is downloading, extracting, importing, and refreshing library state.
- Receives the selected book via DCC into `/downloads`.
- Automatically extracts supported archives when possible and can keep the original download in `/downloads` if auto-move is disabled.
- Optionally moves completed downloads into `/books` and triggers a targeted library refresh so the book becomes owned in the UI quickly.

For auto-move to work, your `/books` mount must be writable.

For PIA VPN routing to work, the container must be started with:

```yaml
cap_add:
  - NET_ADMIN
devices:
  - /dev/net/tun:/dev/net/tun
```

If `/dev/net/tun` is missing inside the container, VPN connection attempts will fail before IRC connects.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, SQLite
- **Frontend:** React 18, TypeScript, Vite, TanStack Query, Tailwind CSS
- **Container:** Multi-stage Docker build

## Building from Source

```bash
git clone https://github.com/apollolabsai/booksarr.git
cd booksarr
docker compose up --build -d
```
