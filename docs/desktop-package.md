# Desktop Packaging Guide (Electron + React UI)

This project can be packaged as a desktop application, using Electron as the desktop shell and the React UI in `apps/dsa-web` as the interface.

## Architecture

- The React UI (built with Vite) is served by the local FastAPI service
- Electron starts the backend automatically on launch and loads the UI once `/api/health` is ready
- In Windows portable/installed mode, the user configuration file `.env` and the database sit next to the exe; the macOS build stores runtime configuration in the Electron user-data directory
- The desktop app picks an available port from `8000-8100` on the local machine and passes the chosen port to the bundled backend. It does not rely on `WEBUI_PORT` from `.env` to decide where the window connects, which prevents a startup timeout when a user changes the port and Electron keeps waiting on the old one
- The desktop backend installs and pins `futu-api==10.8.6808` through `requirements.txt`; the Windows and macOS build scripts run `import futu` in both the source environment and the PyInstaller output, so a release cannot ship with the SDK installed but not bundled.
- The report Share button renders the restricted HTML produced by the local backend in Electron's own hidden Chromium window and saves it as a PNG, so the desktop installer does not need to ship `wkhtmltoimage`, `markdown-to-file`, or a Playwright browser.

## Local development

One-command start (development mode):

```bash
powershell -ExecutionPolicy Bypass -File scripts\run-desktop.ps1
```

Or run the steps manually:

1) Build the React UI (output goes to `static/`)

```bash
cd apps/dsa-web
npm install
npm run build
```

2) Start the Electron app (it launches the backend automatically)

```bash
cd apps/dsa-desktop
npm install
npm run dev
```

On the first run, `.env` is generated automatically by copying `.env.example`.

## Packaging (Windows)

### Prerequisites

- Node.js 18+
- Python 3.10+
- Windows developer mode enabled (electron-builder needs to create symbolic links)
  - Settings -> Privacy & security -> For developers -> Developer Mode

### One-command build

```bash
powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
```

The script runs these steps in order:
1. Build the React UI
2. Install the Python dependencies
3. Package the backend with PyInstaller
4. Package the desktop app with electron-builder

The current Windows installer uses the NSIS wizard flow. It supports per-user installation only, has administrator elevation disabled, and lets you choose the target directory during installation (a drive other than C:, for example). Through the NSIS `.onVerifyInstDir` callback the installer blocks protected system directories such as `Program Files` and `Windows` at the installer level - the Next button is disabled automatically when such a path is selected. After installation the desktop app still generates and reads `.env`, `data/stock_analysis.db` (together with `data/stock_analysis.db-wal` / `data/stock_analysis.db-shm`), and `logs/desktop.log` next to the installation directory, following the existing logic. The default per-user installation directory is recommended. If you would rather not install anything, the `win-unpacked` portable package remains available.

## Automated CI packaging and GitHub Release publishing

The repository can build the desktop app and upload it to GitHub Releases through GitHub Actions:

- Workflow: `.github/workflows/desktop-release.yml`
- Triggers:
  - Automatically after pushing a semantic version tag (such as `v3.2.12`)
  - Manually from the Actions page, specifying `release_tag`
- Artifacts:
  - Windows installer: named `daily-stock-analysis-windows-installer-<tag>.exe` consistently in both the Release attachments and the local `apps/dsa-desktop/dist/`
  - Windows auto-update metadata: the Release attachments also keep `latest.yml` and `*.blockmap` so the installed desktop app can download and verify updates in the background; ordinary users never need to download this metadata by hand. Once the download finishes and the user confirms "restart and install", the desktop app stops the bundled backend, backs up the runtime files, and runs the installer in silent mode.
  - Windows portable package: `daily-stock-analysis-windows-noinstall-<tag>.zip`
  - macOS Intel: `daily-stock-analysis-macos-x64-<tag>.dmg`
  - macOS Apple Silicon: `daily-stock-analysis-macos-arm64-<tag>.dmg`

### macOS says the app is damaged and cannot be opened

The macOS DMG is not yet signed with an Apple Developer certificate or notarized. The build configuration deliberately produces an unsigned application, clears the incomplete signature before the PyInstaller output runs for the first time, and clears the full `.app` again before DMG creation through the electron-builder `afterPack` hook. CI additionally inspects both the original Electron `.app` and the `.app` inside the mounted DMG, which blocks another release carrying a damaged signature such as `code has no resources but signature indicates they must be present`. This only mitigates the incomplete-signature defect from v3.27.0 and **does not make the app trusted by Apple**. After downloading through a browser, macOS Gatekeeper may still report that the developer cannot be verified, block startup, or ask the user to confirm manually.

Work through these steps in order:

1. Download attachments only from the project's [GitHub Releases](https://github.com/ZhuLinsen/daily_stock_analysis/releases), and confirm the installer architecture matches your Mac: Apple silicon (M1/M2/M3/M4 and so on) uses `daily-stock-analysis-macos-arm64-<tag>.dmg`, and Intel uses `daily-stock-analysis-macos-x64-<tag>.dmg`. Never bypass Gatekeeper for a re-upload or a package of unknown origin.
2. Open the DMG, drag `Daily Stock Analysis` into Applications, and try launching it once. If it is blocked, open System Settings -> Privacy & Security, confirm the application name at the security prompt, click Open Anyway, and confirm again when the system asks. On older macOS versions the equivalent location is System Preferences -> Security & Privacy -> General.
3. Only when the package is confirmed to come from the official Release above and Open Anyway still does not let it through, open Terminal, clear the download quarantine attribute for that application, and start it again:

```bash
xattr -dr com.apple.quarantine "/Applications/Daily Stock Analysis.app"
open "/Applications/Daily Stock Analysis.app"
```

Replace the path if the app is not in `/Applications`. Never run `xattr` against the entire Applications directory, and never run it against an application of unknown origin. Some macOS versions still refuse an unsigned application, and clearing quarantine does not guarantee it will be allowed. Removing the prompt permanently requires Apple Developer signing and notarization in the release pipeline, which is outside these temporary steps.

Maintainers can tell an expected unsigned rejection apart from an unpublishable damaged signature with:

```bash
codesign -d "/Applications/Daily Stock Analysis.app"
spctl --assess --type execute --verbose=4 "/Applications/Daily Stock Analysis.app"
```

For the current unsigned artifacts, `codesign -d` is expected to include `code object is not signed at all` and `spctl` is expected to reject. Output such as `code has no resources but signature indicates they must be present`, or any other signature-corruption message, should be treated as a release blocker.

Recommended release flow:

1. Merge the code into `main`
2. Let the auto-tag workflow generate the version (or create the tag manually)
3. The `desktop-release` workflow builds automatically and attaches both platform installers to the matching GitHub Release

## Reproducible pre-release verification (desktop update path)

The desktop auto-update path depends on the Windows NSIS installer artifacts plus the `latest.yml` and `*.blockmap` metadata. The current desktop CI does not cover the publishable path of the `desktop-release` artifacts, so running the following locally before submitting is recommended:

Note: this checklist focuses on the Windows NSIS installer and the `electron-updater` release metadata. A Linux environment cannot produce Windows installers or updater metadata (`latest.yml` / `*.blockmap`) directly, so that path must be reviewed on a Windows release runner or a Windows machine.

If you cannot complete the verification outside Windows, state in the PR acceptance notes who reviewed the Windows release path, the review time window, and the `desktop-release` artifact check results (consistency and downloadability of the release/tag against `daily-stock-analysis-windows-installer-<tag>.exe`, `latest.yml`, and `*.blockmap`).

1. Build the web static assets first (the desktop main window and settings entry depend on them)

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

2. Return to the desktop app, install dependencies, run the preload unit tests, then run the Electron build

```bash
cd ../dsa-desktop
npm ci
npm test
npm run build
```

In a Windows release-review environment you can additionally run:

```powershell
./scripts/verify-desktop-updater-artifacts.ps1 -ReleaseTag v$(node -p "require('./apps/dsa-desktop/package.json').version")
```

> When the current environment cannot produce a Windows NSIS installer, state the platform limitation explicitly in the delivery notes and ask the designated Windows release-path reviewer to complete this verification.

3. Check that the update metadata was produced

```bash
ls -1 dist | sort
ls -1 dist/*.yml dist/*.blockmap 2>/dev/null || true
```

4. Force-align the version with the release attachments (review this on Windows, or on a runner that can produce NSIS artifacts)

```bash
RELEASE_TAG="v$(node -p \"require('./package.json').version\")"
REPO="ZhuLinsen/daily_stock_analysis"

for f in dist/*latest.yml dist/*.blockmap dist/daily-stock-analysis-windows-installer-*.exe; do
  [ -f \"$f\" ] && echo \"[FOUND] $f\"
done

if [ -f dist/latest.yml ]; then
  echo \"---- latest.yml version excerpt ----\"
  grep -E \"^version:|^files:|^sha512:\" dist/latest.yml
fi

echo \"---- Release checklist (manual review) ----\"
echo \"Release Tag: $RELEASE_TAG\"
echo \"Release URL: https://github.com/$REPO/releases/tag/$RELEASE_TAG\"
echo \"Attachments to verify:\"
echo \"- daily-stock-analysis-windows-installer-*.exe\"
echo \"- latest.yml\"
echo \"- *.blockmap\"
echo \"and confirm latest.yml version matches the tag semantically, and path/url match the installer attachment name\"
```

5a. Reviewable output worth recording in the PR description (Windows):

```bash
echo "release-tag=${RELEASE_TAG}"
echo "latest.yml version:"
grep -E "^version:" dist/latest.yml
echo "latest.yml files:"
sed -n '1,80p' dist/latest.yml
echo "packaging artifacts:"
ls -1 dist/*.yml dist/*.blockmap dist/*installer*.exe 2>/dev/null | sort
```

Windows release-path review checklist (performed by the release team or a maintainer after the PR):

- The release/tag version matches `daily-stock-analysis-windows-installer-<tag>.exe`;
- `latest.yml`, `daily-stock-analysis-windows-installer-<tag>.exe`, and `*.blockmap` all appear together under the same tag and are downloadable;
- `version` in `latest.yml` matches the release tag semantically (compare after stripping the `v` prefix), and `path` / `files.url` match the installer attachment name;
- If any of those files is missing or `release-tag` does not match, flag it as a blocker and complete the `desktop-release` packaging flow.

5. Verify Windows/NSIS artifacts and release attachments manually on Windows (the release flow can be triggered by hand), and check that runtime files survive the upgrade:

   1. Record the SHA256 of `.env`, `data/stock_analysis.db`, `data/stock_analysis.db-wal`, `data/stock_analysis.db-shm`, and `logs/desktop.log` in the installation directory both before and after installing;
   2. Confirm that after the next desktop startup those files still exist and match what you recorded before installing;
   3. If they differ, quit the app, check whether `.dsa-desktop-update-backup` in the user-data directory was cleaned up completely, and correlate that with the latest logs.

On Windows, running this through PowerShell is recommended:

```bash
Get-FileHash .env,data\\stock_analysis.db,data\\stock_analysis.db-wal,data\\stock_analysis.db-shm,logs\\desktop.log -Algorithm SHA256
```

Note: before the "restart and install" step of the Windows NSIS installed version, the app already stops the bundled backend, backs up the runtime files next to the installation directory, and runs the update installer in silent mode. The aim is to stop the install wizard from overwriting a still-running desktop process and to reduce the risk of losing files during the update. If restoration fails, the desktop app shows an update-installation error and keeps the manual download path available as a fallback. This fix changed only the Windows update-installation path and the bundled backend's process lifecycle; it does not touch settings-save semantics, model runtime cleanup policy, or configuration migration behaviour.

### Step-by-step packaging

1) Build the React UI

```bash
cd apps/dsa-web
npm install
npm run build
```

2) Package the Python backend with the existing scripts (they collect the DSA screening engine, the Futu SDK)

- Windows:

```bash
powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1
```

- macOS:

```bash
bash scripts/build-backend-macos.sh
```

After installing dependencies, the script runs `--collect-all src.services.screening` and `--collect-all futu`. Once the build completes it uses the frozen executable to verify that `src.services.screening.pipeline`, `futu`, and `orjson` all import, and checks the number of screening strategies. That prevents a release from degrading in the screening, Futu portfolio-import, or daily-bar enrichment paths because a module or package data file is missing. The screening implementation is modelled on AlphaSift. When `requirements.txt`, the Futu broker, the desktop packaging entrypoint, or a related workflow changes, the main PR CI runs the blocking `desktop-futu-package-windows` and `desktop-futu-package-macos` checks.

3) Package the Electron desktop app

```bash
cd apps/dsa-desktop
npm install
npm run build
```

The build output lands in `apps/dsa-desktop/dist/`. The Windows installer is generated as `daily-stock-analysis-windows-installer-<tag>.exe`, and the install wizard lets you choose the installation directory.

## Directory layout

In Windows installer mode the installer supports per-user installation only and has administrator elevation disabled. You can choose the installation directory in the wizard, and the installer blocks protected system directories such as `Program Files` and `Windows` at the installer level (the Next button is disabled automatically when one is selected). After installation the app generates and reads `.env`, `data/stock_analysis.db` (together with `data/stock_analysis.db-wal` / `data/stock_analysis.db-shm`), and `logs/desktop.log` next to the installation directory. Keep the default per-user location, or pick another user-writable directory.

In `win-unpacked` portable mode the layout is:

```
win-unpacked/
  Daily Stock Analysis.exe    <- double-click to start
  .env                        <- user config file (generated on first launch)
  data/
    stock_analysis.db         <- main database file
    stock_analysis.db-wal     <- WAL journal (update backup/restore)
    stock_analysis.db-shm     <- WAL shared metadata (update backup/restore)
  logs/
    desktop.log               <- runtime log
  resources/
    .env.example              <- config template
    backend/
      stock_analysis.exe      <- backend service
```

## Configuration files

- The `.env` for the Windows desktop app sits in the same directory as the exe
- For the macOS build, `.env`, `data/`, and `logs/` live in the Electron user-data directory, so replacing the `.app` does not lose them
- `.env` is generated on first launch by copying `.env.example`
- When upgrading from an older version, if `.env`, `data/stock_analysis.db`, or the log files inside the old `.app` bundle are still reachable, the new version migrates them into the user-data directory when the target file does not already exist; existing target files are never overwritten
- Users need to configure the following in `.env`:
  - `GEMINI_API_KEY` or `OPENAI_API_KEY`: required for AI analysis
  - `STOCK_LIST`: the watchlist (comma-separated)
  - See `.env.example` for the other optional settings

### Backing up and restoring `.env`

- Both the WebUI and the desktop app expose `Export .env` and `Import .env` buttons under `System Settings -> Configuration backup`
- Outside the desktop app, the WebUI requires administrator authentication to be enabled and a completed login; with authentication disabled the buttons are disabled and the API returns `403`
- `Export .env` exports a backup of the **saved** `.env`; a local draft you have not yet saved on the page is not exported
- `Import .env` reads the keys and values from the backup file and merges them into the current configuration, triggering a configuration reload immediately afterwards
- The import is a key-level overwrite rather than a whole-file replacement: keys present in the backup overwrite the current values, and keys that are absent are left unchanged
- If the page still has an unsaved draft, you are asked to confirm before importing, which avoids mixing a local draft with the saved configuration
- On the web side, when `ADMIN_AUTH_ENABLED=false` (the default) the settings page shows the buttons disabled and prompts you to enable administrator authentication first; the desktop app is unaffected by that setting and can use backup and restore directly

> Recommendation: macOS users upgrading from an older version should still run `Export .env` once before upgrading as insurance. If the old `.app` has already been replaced wholesale, the files inside it cannot be recovered, and only a backup import will restore them.

### Version information in the settings page

- The desktop version shown under `System Settings -> Version information` comes from `app.getVersion()` in the Electron main process and is exposed to the frontend through the preload bridge
- Development mode (`npm run dev`) and packaged builds (`npm run build` and the installer) reuse the same version-injection path, so there is no separate hardcoded version maintained in `preload.js`
- `README.md` keeps the installation and startup entry points; desktop runtime details like these live in this topic document, which stops the introductory docs from growing

### Reaching the Windows desktop WebUI from the local network

- The desktop app still defaults to `WEBUI_HOST=127.0.0.1`, allowing local access only, so installing it does not unintentionally expose the backend
- To let other devices on the same network reach it, set `WEBUI_HOST=0.0.0.0` in the desktop `.env` or under `System Settings -> WebUI listen address`, save, and restart the desktop app
- The desktop app picks an available port in `8000-8100` and passes it to the backend; it is usually still `8000`, and if the port is taken you can check `Using port ...` and `Backend launch command=...` in `logs/desktop.log`
- The Windows firewall or your server security group still has to allow the port actually in use; enabling `ADMIN_AUTH_ENABLED` as well is recommended before exposing it
- Even when the backend binds `0.0.0.0`, the desktop window itself still uses a locally reachable address for the health check and page load

### Desktop update notifications

- After the main interface finishes loading, the app checks the latest stable GitHub release in the background and compares it semantically against the current `app.getVersion()`
- The Windows NSIS installed version downloads new releases automatically through the built-in GitHub update source; once the download completes a one-time prompt appears, and after the user confirms it restarts silently and installs
- A silent auto-update reuses the current installation directory, so if the user chose a non-default directory or one containing spaces at install time, later auto-updates still overwrite that same directory
- At desktop runtime an update entry appears in the global top-right corner, where you can check status, check manually, open the Release page, or run "restart and install" once an update has downloaded; the entry is not shown in an ordinary browser WebUI
- The Desktop update area under `System Settings -> Version information` remains available as the detailed entry point and fallback. The global entry and the settings page share one update state, and both are disabled while a check, download, or installation is in progress, so a manual check cannot be started twice
- The main-process manual check path also has in-flight de-duplication, which avoids concurrent requests to GitHub Releases
- The Windows portable package, development mode, and the macOS DMG keep the compatible "notify and open the download page" path, so a network failure never blocks desktop startup
- A failed version check, a GitHub API timeout, missing update metadata, or a download/installation error is written to `logs/desktop.log`, and a manual check from the settings page or the top-right entry shows the error state

## Troubleshooting

### It keeps showing "Preparing backend..." after startup

1. Check `logs/desktop.log` for the error
2. Confirm that `.env` exists and is configured correctly
3. Confirm that ports 8000-8100 are free; the desktop app picks one of them automatically, so there is no need to change `WEBUI_PORT` in `.env` by hand
4. If the log shows the port Electron is waiting on differing from the port the backend actually listens on, upgrade to a version that includes the desktop port-synchronization fix

### The backend reports ModuleNotFoundError at startup

A module was missing when PyInstaller packaged the app. Add the matching `--hidden-import` to both the Windows and macOS backend build scripts, and run a runtime import check against the frozen output. The current scripts explicitly install, freeze, and probe `orjson`, which the LiteLLM runtime path needs. If the log contains `No module named 'orjson'`, upgrade to the fixed version and rebuild rather than installing the dependency by hand into an already-published directory.

### The UI loads blank

Confirm that `static/index.html` exists; if it does not, rebuild the React UI.

### Configuration migration after a macOS upgrade

Older versions wrote the runtime `.env`, database, and logs inside the `.app` bundle. Newer versions use the Electron user-data directory instead and perform a one-time migration while the files inside the old `.app` bundle are still reachable. The migration rule is copy-only-if-the-target-is-missing, so configuration you already saved in the new version is never overwritten.

If the old `.app` has already been replaced wholesale, the new version cannot recover the `.env` inside it. In that case import the `.env` you exported before upgrading under `System Settings -> Configuration backup`. After one migration or a fresh setup, later versions keep reusing the user-data directory and no longer lose data when the `.app` is replaced.

## Distributing to users

There are now two ways to distribute on Windows:

1. Installer: distribute `daily-stock-analysis-windows-installer-<tag>.exe` from `apps/dsa-desktop/dist/`, letting users choose the target directory during installation
2. Portable package: zip up the whole `apps/dsa-desktop/dist/win-unpacked/` folder and send it to users

With the `win-unpacked` portable package, users only need to:

1. Extract the folder
2. Edit `.env` to configure the API key and stock list
3. Double-click `Daily Stock Analysis.exe` to start
