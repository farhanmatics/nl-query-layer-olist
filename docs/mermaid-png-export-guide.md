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

From the repo root:

```bash
npm install -g @mermaid-js/mermaid-cli   # one-time
mkdir -p docs/images
```

Save each diagram as a `.mmd` file, then render:

```bash
# Example after saving diagram 1 to docs/diagrams/system.mmd
mmdc -i docs/diagrams/system.mmd -o docs/images/architecture-system.png -b white -w 1920 -H 1080
mmdc -i docs/diagrams/sequence.mmd   -o docs/images/architecture-sequence.png -b white -w 1920 -H 1080
mmdc -i docs/diagrams/trust.mmd      -o docs/images/architecture-trust-boundary.png -b white -w 1920 -H 1080
```

**Flags:** `-b white` background · `-w`/`-H` size for slide decks · add `-s 2` for retina.

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

- Keep sources in git: either the `.mmd` files under `docs/diagrams/` or the Mermaid blocks in `HACKATHON.md` (already there).

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `flowchart` syntax error | Ensure first line is `flowchart TB` / `flowchart LR` with no leading spaces inside the fence |
| Subgraph labels break CLI | Upgrade `mmdc`: `npm update -g @mermaid-js/mermaid-cli` |
| Text clipped in PNG | Increase `-w` and `-H`, or simplify node labels |
| Colors wrong on dark slides | Export with `-b transparent` or edit in Figma/Keynote |

**Single combined slide (optional):** export three PNGs and place them on one 16:9 slide — system diagram on top, sequence + trust boundary side-by-side below.
