# Repository Guidelines

## Project Structure & Module Organization
`backend/` contains the FastAPI service, async data collectors, signal engine, ML pipeline, and database layer. Main runtime code lives under `backend/app/` with subpackages such as `api/`, `collector/`, `db/`, `engine/`, `exchange/`, `ml/`, and `push/`. Backend tests mirror those areas under `backend/tests/`.

`web/` is the React 19 PWA. Feature code is organized by slice in `web/src/features/`; shared UI, hooks, and API utilities live in `web/src/shared/`. `docs/` holds design and implementation notes. `mobile/` is currently unused, so new mobile work should be discussed before adding structure there.

## Build, Test, and Development Commands
Backend is intended to run through Docker Compose from `backend/`:

```bash
cd backend
docker compose up -d           # API + Postgres + Redis
docker exec krypton-api-1 python -m pytest
docker exec krypton-api-1 alembic upgrade head
```

Frontend commands run from `web/`:

```bash
cd web
pnpm dev                       # Vite dev server
pnpm build                     # TypeScript build + production bundle
pnpm lint                      # ESLint
pnpm exec vitest run           # Frontend tests
```

## Coding Style & Naming Conventions
Python follows existing 4-space indentation, `snake_case` functions/modules, and `PascalCase` classes. TypeScript/React uses 2-space indentation, `PascalCase` components, and colocated feature files such as `store.ts`, `types.ts`, and `*.test.tsx`. Keep new code inside the relevant feature or backend domain package instead of adding cross-cutting misc folders.

## Testing Guidelines
Backend uses `pytest` with `pytest-asyncio`; prefer `test_*.py` names under the matching domain folder, for example `backend/tests/engine/test_cooldown.py`. Frontend uses Vitest with Testing Library and `jsdom`; use `*.test.ts` or `*.test.tsx` near the code under test. Add or update tests with every behavior change.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commits with scopes, for example `feat(engine): ...`, `fix(nginx): ...`, and `docs(engine): ...`. Follow that format and keep scopes aligned with the touched area.

Work directly on `main` unless the user explicitly asks for a separate branch. Do not create git worktrees or feature branches by default.

Do not create standalone commits that contain only specs or docs unless the user explicitly asks for a docs-only commit. Design docs and specs should normally be committed together with the related implementation or planning work.

PRs should describe the user-visible impact, note any config or migration changes, link the related issue, and include screenshots for UI work. Before opening a PR, run the relevant backend and frontend test commands plus `pnpm lint`.
