# personal-page

The personal site of **Alex Saoulis** — a clean, minimal-academic portfolio whose centrepiece is
a live earthquake-monitoring + ML-inference demo for the Japan (F-net) region.

Built with **Astro** (static) + **React islands** + **TypeScript**, deployed on **Vercel**.

> 📐 The full design, target architecture, data contracts, costs and roadmap live in
> **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**. Read that first to understand where this is
> going. Stage-1 (this repo today) is the polished static site + a `/demo` _interface preview_;
> the live data pipeline is the next milestone.

## Quickstart

Requires **Node ≥ 22.12** (an `.nvmrc` pins 22):

```sh
nvm use            # or: nvm install 22
npm install
npm run dev        # http://localhost:4321
```

### Commands

| Command                | Action                                           |
| ---------------------- | ------------------------------------------------ |
| `npm run dev`          | Dev server at `localhost:4321`                   |
| `npm run build`        | Build the static site to `./dist/`               |
| `npm run preview`      | Preview the production build locally             |
| `npm run check`        | Type-check `.astro`/`.ts`/`.tsx` (`astro check`) |
| `npm run lint`         | ESLint (flat config: ts + astro + react-hooks)   |
| `npm run format`       | Prettier write                                   |
| `npm run format:check` | Prettier check (CI-friendly)                     |

## Project structure

```text
personal-page/
├── public/                 # static assets served as-is
│   ├── favicon.svg         # branded mark
│   ├── og.png              # social card
│   ├── cv.pdf              # placeholder CV (replace)
│   └── demo/               # mock demo data + per-event images
│       ├── events.json     # GeoJSON the /demo island fetches (the DATA CONTRACT)
│       └── <event-id>/     # lune.png + beachball.png per mock event
├── src/
│   ├── config.ts           # ← site metadata, nav, social links (edit this first)
│   ├── content.config.ts   # projects content-collection schema
│   ├── content/projects/   # one Markdown file per project (data-driven cards)
│   ├── styles/             # tokens.css (design system) + global.css
│   ├── layouts/            # BaseLayout.astro (head/SEO, header, footer, reveal)
│   ├── components/         # Header, Footer, Icon, PageHeader, ProjectCard
│   │   └── demo/           # the /demo React island (MapView, EventPanel, TimeSlider…)
│   └── pages/              # index, about, cv, projects, contact, demo
└── docs/ARCHITECTURE.md    # the project proposal / architecture
```

## Editing content

- **Identity / links:** `src/config.ts` (name, role, affiliation, nav, socials, email).
- **Add a project:** drop a Markdown file in `src/content/projects/` with the frontmatter shown
  in the existing files (`title`, `blurb`, `status`, `tags`, `order`, optional `href`/`featured`).
- **Design tokens:** `src/styles/tokens.css` (accent colour, type scale, spacing).
- **CV:** structured entries are in `src/pages/cv.astro`; the download PDF is `public/cv.pdf`.

Placeholder copy is marked `TODO` throughout — search for it before launch.

## The `/demo` page

`/demo` renders the **intended** live-monitor interface against **mock** data
(`public/demo/events.json`): a MapLibre map over Japan, clickable event markers, a diagnostic side
panel (source-type lune + beachball + Kagan angle), and a client-side month-long time-slider. The
live worker (see the architecture doc) will emit the **same** `events.json` schema, so the
frontend won't need to change to go live.

## Deploy (Vercel)

Astro builds to static and Vercel auto-detects it (zero config). To deploy:

1. Push this repo to GitHub (under your **personal** account — Vercel Hobby can't import org repos).
2. On [vercel.com](https://vercel.com) → **Add New → Project** → import the repo.
3. Framework preset auto-detects **Astro**; build `npm run build`, output `dist/`. Node is pinned
   via `.nvmrc` / `engines.node`.
4. Deploy → live on `*.vercel.app`. Add a custom domain later under **Project → Domains**.

## What's next

The live F-net inference worker + wiring the real data contract — tracked as the **Flagship demo**
milestones in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

[MIT](LICENSE)
