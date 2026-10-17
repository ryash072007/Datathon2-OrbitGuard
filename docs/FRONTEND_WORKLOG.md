# Frontend implementation handoff

## State

Implemented a complete React/TypeScript/Vite mission-control console in `frontend/`. It has Encounter Monitor, Manoeuvre Lab, and Evidence screens, same-origin `/api` integration, asynchronous screening polling, JSON run download, explicit historical/synthetic labels, missing-artifact states, errors, accessible controls, responsive layout, and locally bundled fonts. Production has no mock data or fixture fallback.

The interface reports the actual backend architecture; local machines are never labelled LinuxONE. ESA later reference estimates are explicitly evaluation-only. No model-performance improvements are hard-coded.

## Files

- `frontend/src/App.tsx`: complete application, screen state and API calls.
- `frontend/src/style.css`: responsive mission-control design.
- `frontend/src/api.ts`: typed request/error helpers and number formatting.
- `frontend/src/main.tsx`: React entry, self-hosted font imports.
- `frontend/scripts/smoke.mjs`: Chrome browser navigation, screening, mobile-overflow and runtime-error checks.
- Vite configuration proxies `/api` to `127.0.0.1:8000`; production output is `frontend/dist` and is served by Flask.

## Commands

```sh
cd frontend
npm ci
npm run build
npm run dev
ORBITGUARD_UI_FIXTURES=1 node scripts/smoke.mjs
ORBITGUARD_BASE_URL=http://127.0.0.1:8000 node scripts/smoke.mjs
```

The smoke runner uses Chrome installed at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`; override with `CHROME_PATH` elsewhere. Fixtures are intercepted in the browser test process only and all fixture identifiers are labelled TEST. They never enter the production bundle.

## Checks completed

- TypeScript strict compilation and Vite production build pass.
- Dependency installation audited with no reported vulnerabilities at installation.
- Isolated browser fixture test passes: all navigation screens, asynchronous manoeuvre screening, policy-tab state, mobile horizontal-overflow check, and no browser runtime exceptions.
- Desktop lab and mobile evidence screenshots were inspected; layouts render coherently.
- Font assets are bundled locally; no third-party font requests are needed at runtime.

## Remaining integration checks

- Run live browser checks once the Flask API and actual model/physics artifacts are available.
- Match the final physics `validation.cases` and scenario benchmark fields.
- Verify filtered manoeuvre-policy trajectory display against actual `encounter_view` output.
- Confirm NASA results, model metrics, and simulator metrics render from real generated artifacts.
- Final production rebuild after the remaining schema alignment.

## Active processes and permissions

- Vite local dev server was started at `http://127.0.0.1:5173` in tool session 78951 for browser QA; stop at teardown.
- npm dependency download, server listening, and Chrome launch needed sandbox escalation. The actions were approved; no auto-review rejection remains.
- The first non-escalated npm install was interrupted after restricted-network stalling; the subsequent approved installation succeeded.

## Ownership

Frontend agent owns `frontend/**`. Root owns Flask/API, production serving, LinuxONE, shared contracts, and root dependencies. ML and physics service implementations are owned by their respective agents.
