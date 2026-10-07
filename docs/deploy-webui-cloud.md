# Cloud Server Web Interface Access Guide

If you have already deployed the project to a cloud server but are not sure what address to type into the browser to reach the web management interface, this guide is for you.

> It really comes down to two steps: make the service listen on the public interface, then type the address into the browser.

---

## Contents

- [Option 1: Direct deployment (pip + python)](#option-1-direct-deployment-pip--python)
- [Option 2: Docker Compose](#option-2-docker-compose)
- [Opening the interface in a browser](#opening-the-interface-in-a-browser)
- [Confirming that a Docker rebuild took effect](#confirming-that-a-docker-rebuild-took-effect)
- [Cannot connect? Check these first](#cannot-connect-check-these-first)
- [Optional: Nginx reverse proxy (custom domain / port 80)](#optional-nginx-reverse-proxy-custom-domain--port-80)
- [Security recommendations](#security-recommendations)

---

## Option 1: Direct deployment (pip + python)

### Step 1: Change the listen address in .env

Open `.env` in an editor (it sits in the project root, the directory that contains `main.py`) and find this line:

```env
WEBUI_HOST=127.0.0.1
```

Change `127.0.0.1` to `0.0.0.0`:

```env
WEBUI_HOST=0.0.0.0
```

> `127.0.0.1` means only the local machine can connect; `0.0.0.0` accepts connections from any source. On a cloud server you have to change `WEBUI_HOST` in `.env` to `0.0.0.0`, or pass `--host 0.0.0.0` explicitly on the start command, before the interface is reachable from outside.

### Step 2: Start the service

Run this from the project root:

```bash
# Start only the web interface (no analysis run)
python main.py --webui-only

# Or: start the web interface and run one analysis at startup; for a daily scheduled analysis add --schedule or set SCHEDULE_ENABLED=true
python main.py --webui
```

On a successful start the terminal prints something like:

```
FastAPI 服务已启动: http://0.0.0.0:8000
```

To keep the service running after you close the terminal, use `nohup`:

```bash
nohup python main.py --webui-only > /dev/null 2>&1 &
```

> The program writes its log files to the `logs/` directory automatically; read them with `tail -f logs/stock_analysis_*.log`.

### Changing the port (optional)

The default port is 8000. To use a different one, set it in `.env`:

```env
WEBUI_PORT=8888
```

Then restart the service.

---

## Option 2: Docker Compose

### Step 1: Confirm the existing .env configuration

The project's `docker/docker-compose.yml` already sets `WEBUI_HOST=0.0.0.0` inside the container, so you do not need to change the listen address in `.env` again — Docker handles it.

`env_file: ../.env` in Docker Compose only injects `.env` into the container as **startup environment variables**. It does not create `/app/.env` inside the container, and it does not make the WebUI write configuration back to the host's `.env`. When the active `.env` file is missing some keys, the current WebUI falls back to showing the identically named environment variables injected at startup, which is why the page shows configuration that Docker injected on start. Exporting `.env`, however, still exports only the contents of the active configuration file.

To keep configuration saved through the WebUI across container deletion, rebuild, or upgrade, put the active configuration file on a mounted volume — for example, add this to the Compose `environment` block:

```yaml
- ENV_FILE=/app/data/runtime.env
```

and keep the `../data:/app/data` mount. Note that if a stale value under the same name is still present in the startup `../.env`, a `docker run -e` flag, or the Compose `environment:` block, those startup environment variables can still override the value stored in the runtime file after a container restart. For the WebUI-saved value to take precedence, update or remove the identically named entry in the startup environment as well.

### Step 2: Start the service

Run this from the project root:

```bash
# Start the scheduled analysis and the web interface together (recommended)
docker-compose -f ./docker/docker-compose.yml up -d

# Or start only the web interface service
docker-compose -f ./docker/docker-compose.yml up -d server
```

Check the status afterwards:

```bash
docker-compose -f ./docker/docker-compose.yml ps
```

Once the `server` service shows status `running`, the web interface is up.

### Changing the port (optional)

The default port is 8000. To use a different one, set it in `.env`:

```env
API_PORT=8888
```

Then restart the container:

```bash
docker-compose -f ./docker/docker-compose.yml down
docker-compose -f ./docker/docker-compose.yml up -d
```

---

## Opening the interface in a browser

Once the service is running, type this into the browser's address bar:

```
http://<your-server-public-ip>:8000
```

For example, if your server's IP is `1.2.3.4`, type:

```
http://1.2.3.4:8000
```

If your domain already resolves to this server, you can use the domain directly:

```
http://your-domain.com:8000
```

> **Where do I find the public IP?** Sign in to your cloud provider's console (Alibaba Cloud, Tencent Cloud, AWS, and so on) and look for "public IP" or "elastic IP" in the instance list.

---

## Confirming that a Docker rebuild took effect

First separate two different things:

1. **The published Docker image version**: the image tag you deployed, for example `ghcr.io/your-org/your-repo:v3.12.0`. The repository's Docker publishing is triggered by `.github/workflows/docker-publish.yml` on `v*.*.*` Git tags, so the image tag and GitHub Releases are the authority on the Docker version.
2. **The frontend build the page actually loaded**: the version info card on the WebUI's System Settings page, which tells you whether the browser has picked up updated static assets.

In other words, **the version info under System Settings is the better signal for whether the frontend was rebuilt, and is not the same thing as the published Docker image version**.

The WebUI now shows a read-only version info card on the System Settings page containing:

- `WebUI version`
- `Revision`
- `Build time`

Official Docker and Desktop releases inject the release tag as `WebUI version` and show the
corresponding commit as `Revision`. When building straight from a Git clone, the WebUI uses
`git describe` and the current commit. If the build environment has neither release
information nor Git metadata, the version is shown explicitly as
`development` rather than passing a build timestamp off as a release version.

After re-running `docker-compose -f ./docker/docker-compose.yml up -d --build`, or re-running the frontend `npm run build` on its own, refresh the browser and open System Settings to check whether the revision and build time have changed. Together the two confirm which code and which build produced the static assets the browser currently has.

To answer "which official release am I actually running", prefer these methods:

```yaml
# Method 1: read the image tag in docker-compose or the deployment script
image: ghcr.io/your-org/your-repo:v3.12.0
```

```bash
# Method 2: look back at your pull command
docker pull ghcr.io/your-org/your-repo:v3.12.0
```

If you have been using `latest`, switch to an explicit version tag; otherwise it is hard to tell from the in-container page alone whether you have repeatedly updated to the same version.

When verifying the local frontend build chain, the following commands make a minimal closed loop:

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

Once `build` succeeds, the `index.html`, JS, and CSS assets generated under `static` carry this
version, commit, and build time, and a `build-info.json` is produced. At startup the source
digest recorded in that file is compared, so even when `rsync -a` preserves old timestamps the
mismatch between sources and static output is detected and a rebuild is triggered.
After a refresh the change should be visible on the version info card.

---

## Cannot connect? Check these first

### 1. The security group / firewall does not allow the port

This is the most common cause. A cloud server opens only port 22 (SSH) by default; you have to allow port 8000 (or whichever port you configured) yourself.

**How to do it** (Alibaba Cloud as an example):
1. Sign in to the Alibaba Cloud console -> ECS -> find your instance
2. Click "Security Groups" -> "Configure Rules" -> "Add Security Group Rule"
3. Set the direction to inbound, the port range to `8000/8000`, and the authorization object to `0.0.0.0/0`, then confirm

Tencent Cloud, AWS, and other providers work much the same way: find "Security Groups" or "Firewall Rules" and add an inbound rule allowing TCP port 8000.

### 2. The server's own firewall blocks it

If `ufw` or `firewalld` is enabled on the system, the port has to be allowed there too:

```bash
# Ubuntu / Debian (ufw)
sudo ufw allow 8000

# CentOS / RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

### 3. WEBUI_HOST in .env was not changed on a direct deployment

This is the second most common cause. `.env` defaults to `WEBUI_HOST=127.0.0.1`, so the service listens only on the local machine and nothing outside can reach it.

The fix: open `.env`, change `WEBUI_HOST=127.0.0.1` to `WEBUI_HOST=0.0.0.0`, and restart the service. You can also add `--host 0.0.0.0` explicitly on the start command.

> Docker deployments do not need this change; skip it.

### 4. The port numbers do not match

Check that the port in the address matches the port set in `.env` or on the start command.

- Direct deployment: 8000 by default, changed with `WEBUI_PORT=xxxx`
- Docker: 8000 by default, changed with `API_PORT=xxxx`

### 5. The page loads, but UI elements are oversized / the layout is broken

**Symptom**: the browser reaches port 8000 and the page has content, but text, buttons, and cards are abnormally large, with no proper layout or colors.

**Root cause**: `static/index.html` exists but the CSS/JS assets are missing (`static/assets/` is empty or absent). The browser loaded the HTML shell but could not fetch the styles and scripts, so it fell back to bare HTML rendering.

Check the browser developer tools first (F12 -> Network tab) for **404** errors on `/assets/index-*.js` and `/assets/index-*.css`. If they are there, fix it as follows:

**Docker users**:

```bash
docker-compose -f ./docker/docker-compose.yml down
docker-compose -f ./docker/docker-compose.yml build --no-cache
docker-compose -f ./docker/docker-compose.yml up -d
```

After the rebuild, force-refresh the browser cache with `Ctrl+Shift+R` and reload the page.

**Direct-deployment users**: make sure Node.js 18+ is installed (20+ recommended), then build the frontend by hand:

```bash
cd apps/dsa-web
npm ci
npm run build
cd ../..
python main.py --webui-only
```

---

## Optional: Nginx reverse proxy (custom domain / port 80)

If you have a domain, or simply do not want `:8000` in the address, use Nginx as a reverse proxy to forward port 80/443 traffic to the backend service.

### Installing Nginx

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y nginx

# CentOS
sudo yum install -y nginx
```

### Example configuration file

Create `/etc/nginx/conf.d/stock-analyzer.conf` with the following contents (replace `your-domain.com` with your own domain or IP):

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (required by the Agent chat page)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Enabling the configuration and restarting Nginx

```bash
sudo nginx -t            # check the configuration for syntax errors
sudo systemctl reload nginx
```

Once that works, reach the application at `http://your-domain.com` with no port number.

> **Notes when running behind Nginx**:
> - If web login authentication is enabled (`ADMIN_AUTH_ENABLED=true`), also set `TRUST_X_FORWARDED_FOR=true` in `.env`; otherwise the system may not identify the real client IP correctly. That option assumes a **single trusted reverse proxy** (Nginx -> App). With multiple proxy layers or a CDN (CDN -> Nginx -> App) the login rate-limit key can degrade to the edge proxy's IP rather than the real client IP, so evaluate it against your actual topology.
> - For HTTPS, [Certbot](https://certbot.eff.org/) can obtain a free Let's Encrypt certificate automatically.

---

## Security recommendations

Before exposing the web interface to the public internet, enabling password protection is strongly recommended:

Set this in `.env`:

```env
ADMIN_AUTH_ENABLED=true
```

After restarting the service, the first visit to the page asks you to set an initial password. From then on every visit to the settings page requires that password, which keeps sensitive configuration such as API keys out of other people's view.

> If you forget the password, run this on the server: `python -m src.auth reset_password`

---

Hit a different problem? Please [open an issue](https://github.com/your-org/your-repo/issues).
