# Export HACKATHON diagrams to PNG (one page)

The architecture diagrams live in [`HACKATHON.md`](../HACKATHON.md) as Mermaid code blocks. Use any method below to produce **PNG files** for slides, Devpost, or PDF attachments.

**Diagrams to export**

| # | Name in HACKATHON.md | Suggested filename |
|---|----------------------|--------------------|
| 1 | System diagram (`flowchart TB`) | `docs/images/architecture-system.png` |
| 2 | Request sequence (`sequenceDiagram`) | `docs/images/architecture-sequence.png` |
| 3 | Trust boundary (`flowchart LR`) | `docs/images/architecture-trust-boundary.png` |

Create the output folder once: `mkdir -p docs/images`

---

## Option A — Mermaid Live Editor (no install, fastest)

1. Open [https://mermaid.live](https://mermaid.live)
2. In `HACKATHON.md`, copy **one** fenced block (from ` ```mermaid ` through ` ``` `, **without** the fences into the editor left pane).
3. Confirm the preview renders correctly.
4. **Actions → PNG** (or **SVG** then convert) — download.
5. Repeat for all three diagrams.

**Tips:** Zoom the preview before export if text looks small. Use transparent background only if your slide theme needs it.

---

## Option B — `@mermaid-js/mermaid-cli` (repeatable, CI-friendly)

Canonical diagram sources live in **`docs/diagrams/*.mmd`** (kept in sync with the Mermaid blocks in `HACKATHON.md`). A one-command script renders all three PNGs.

### Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Node.js 18+** | `node -v` |
| **Chrome / Chromium** | The script auto-detects macOS Google Chrome or Linux `google-chrome` / `chromium`. Override with `PUPPETEER_EXECUTABLE_PATH=/path/to/chrome`. |
| **Network (first run only)** | `npm install` downloads `@mermaid-js/mermaid-cli` (~30 MB). Browser download is **not** required if system Chrome is found. |

### Quick export (recommended)

From the **repo root**:

```bash
npm install --ignore-scripts   # first time only — skips Puppeteer browser download
bash scripts/export-mermaid-png.sh
```

Once `package-lock.json` is committed, CI and teammates can use `npm ci --ignore-scripts` instead.

Outputs:

| Source | PNG |
|--------|-----|
| `docs/diagrams/system.mmd` | `docs/images/architecture-system.png` |
| `docs/diagrams/sequence.mmd` | `docs/images/architecture-sequence.png` |
| `docs/diagrams/trust-boundary.mmd` | `docs/images/architecture-trust-boundary.png` |

Also write SVG copies:

```bash
bash scripts/export-mermaid-png.sh --svg
```

### npm script (optional, pins CLI version)

A root `package.json` pins `@mermaid-js/mermaid-cli@11.4.0` for reproducible CI:

```bash
npm ci --ignore-scripts
npm run diagrams:export
# or
npm run diagrams:export:svg
```

Override the CLI version for a single run:

```bash
MERMAID_CLI_VERSION=11.4.0 bash scripts/export-mermaid-png.sh
```

### Manual `mmdc` (without the script)

```bash
mkdir -p docs/images
npx --yes @mermaid-js/mermaid-cli@11.4.0 \
  -i docs/diagrams/system.mmd \
  -o docs/images/architecture-system.png \
  -b white -w 1920 -H 1080 -s 2 \
  -p docs/diagrams/puppeteer-config.json
```

Repeat for `sequence.mmd` and `trust-boundary.mmd`.

**Flags used by the script**

| Flag | Purpose |
|------|---------|
| `-b white` | Slide-friendly background |
| `-w 1920 -H 1080` | 16:9 canvas |
| `-s 2` | 2× scale (retina / crisp text) |
| `-p puppeteer-config.json` | `--no-sandbox` for Docker/CI |

Other useful flags: `-b transparent` for dark slides · `-t dark` for dark theme.

### Edit workflow

1. Edit the `.mmd` file under `docs/diagrams/` (or edit `HACKATHON.md` and copy the block back into the matching `.mmd`).
2. Re-run `bash scripts/export-mermaid-png.sh`.
3. Commit **both** the `.mmd` source and the regenerated PNG if you want images in git.

### GitHub Actions (CI)

Add a job that fails if diagrams drift, or uploads PNGs as artifacts:

```yaml
# .github/workflows/diagrams.yml (example)
name: Export Mermaid PNGs

on:
  workflow_dispatch:
  push:
    paths:
      - 'docs/diagrams/**'
      - 'HACKATHON.md'
      - 'scripts/export-mermaid-png.sh'

jobs:
  export:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm

      - run: npm ci --ignore-scripts

      - name: Install Chromium deps (Linux)
        run: |
          sudo apt-get update
          sudo apt-get install -y \
            ca-certificates fonts-liberation libasound2t64 libatk-bridge2.0-0 \
            libatk1.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 \
            libnspr4 libnss3 libx11-xcb1 libxcomposite1 libxdamage1 \
            libxrandr2 xdg-utils \
            chromium-browser || sudo apt-get install -y chromium

      - run: npm run diagrams:export
        env:
          PUPPETEER_EXECUTABLE_PATH: /usr/bin/chromium-browser

      - uses: actions/upload-artifact@v4
        with:
          name: architecture-pngs
          path: docs/images/architecture-*.png
```

To **verify committed PNGs match sources** (optional strict mode):

```bash
bash scripts/export-mermaid-png.sh
git diff --exit-code docs/images/
```

### Docker / sandboxed Linux

If `mmdc` crashes with sandbox errors, the repo ships `docs/diagrams/puppeteer-config.json` (passed via `-p`). For root inside Docker, that is usually enough.

### Global install (alternative)

```bash
npm install -g @mermaid-js/mermaid-cli@11.4.0
mmdc -i docs/diagrams/system.mmd -o docs/images/architecture-system.png -b white -w 1920 -H 1080 -s 2
```

Prefer **`npx` or `npm run diagrams:export`** so local and CI use the same version.

---

## Option C — VS Code / Cursor extension

1. Install **Markdown Preview Mermaid Support** (or **Mermaid Preview**).
2. Open `HACKATHON.md` → preview (`Cmd+Shift+V`).
3. Right-click the rendered diagram → **Copy image** / **Save as PNG** (depends on extension).

Good for quick one-offs; Option B is better for re-exports after edits.

---

## Option D — GitHub (render only)

Push to GitHub and view `HACKATHON.md` in the browser — diagrams render automatically.  
For a PNG, screenshot the rendered diagram or use Option A/B for a clean export.

---

## Hackathon submission

- Attach **diagram #1 (system)** as the primary architecture image in the submission form.
- Optionally zip all three under `docs/images/` and link from `HACKATHON.md`:

  ```markdown
  ![System architecture](docs/images/architecture-system.png)
  ```

- Keep sources in git: **`docs/diagrams/*.mmd`** (canonical) plus the Mermaid blocks in `HACKATHON.md`.
- Regenerate PNGs: `npm install --ignore-scripts && bash scripts/export-mermaid-png.sh`
- Optionally commit PNGs under `docs/images/` for Devpost/slides without re-running the script.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `flowchart` syntax error | Ensure first line is `flowchart TB` / `flowchart LR` with no leading spaces inside the fence |
| Subgraph labels break CLI | Upgrade pinned version: `MERMAID_CLI_VERSION=11.4.0 bash scripts/export-mermaid-png.sh` |
| `Failed to launch browser` / sandbox | macOS: install Google Chrome, or set `PUPPETEER_EXECUTABLE_PATH`. Linux CI: install `chromium-browser` + apt deps (see Option B). |
| `Could not find Chrome` | Run `npm install --ignore-scripts` then retry; script auto-detects system Chrome. Or: `npx puppeteer browsers install chrome-headless-shell` |
| `npm ci` fails (no lockfile) | Use `npm install --ignore-scripts` once, commit `package-lock.json` |
| Text clipped in PNG | Increase `-w` and `-H` in `scripts/export-mermaid-png.sh`, or simplify node labels |
| Colors wrong on dark slides | Export with `-b transparent` or edit in Figma/Keynote |

**Single combined slide (optional):** export three PNGs and place them on one 16:9 slide — system diagram on top, sequence + trust boundary side-by-side below.
