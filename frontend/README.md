# OrbitGuard mission console

The console consumes the Flask `/api` endpoints. It never fabricates missing model, simulator, or benchmark results. Historical ESA records and synthetic planning scenarios are labelled separately.

## Development

Start the Python backend on port 8000, then:

```sh
npm ci
npm run dev
```

Vite serves the interface on port 5173 and proxies `/api` to `http://127.0.0.1:8000`.

## Production

```sh
npm ci
npm run build
```

The output is `dist/`. Flask serves this directory and its locally bundled fonts. Building assets on a laptop and copying `dist/` to LinuxONE avoids requiring Node on the VM.

## Browser verification

```sh
# Against the actual running application
ORBITGUARD_BASE_URL=http://127.0.0.1:8000 npm run test:smoke

# Isolated UI regression fixtures, intercepted only by the test runner
ORBITGUARD_UI_FIXTURES=1 npm run test:smoke
```

Set `CHROME_PATH` to the executable of an installed Chromium-compatible browser if the default macOS Chrome path does not apply. The test checks navigation, browser runtime errors and mobile overflow. Fixture mode also checks job completion, policy selection and that historical replay submits only the selected prefix of messages.

Screenshots are written under ignored `test-results/`. Test fixtures never enter production source code or the build.
