# Share image templates and data population

Share images turn single-stock analysis and market review into a 1080px tall image suited to social platforms. Single-stock and market images use two independent information structures, but share the DSA branding, the repository identifier `your-org/your-repo`, and the risk disclaimer. The GitHub area carries no QR code; Web and desktop share images show no social account by default, and deployment configuration can add a Xiaohongshu QR code and account information.

## How the runtime populates them

The existing notification path does not need image data assembled by hand:

```text
Single stock: AnalysisResult
  -> AnalysisResult.to_dict() structured JSON + stable Markdown
  -> share_image reads the JSON first, falling back to Markdown
  -> single-stock decision card HTML
  -> wkhtmltoimage / markdown-to-file / Playwright emits a PNG

Market: MarketOverview + market_light + LLM review
  -> MarketAnalyzer produces market_review_payload + stable Markdown
  -> share_image reads the payload first, falling back to Markdown
  -> market review card HTML
  -> wkhtmltoimage / markdown-to-file / Playwright emits a PNG
```

`MARKDOWN_TO_IMAGE_CHANNELS`, `MD2IMG_ENGINE`, and `MARKDOWN_TO_IMAGE_MAX_CHARS` continue to control which notification channels convert to images, which engine is used, and the maximum input length. A failed conversion still falls back to a text notification.

Share images need the runtime to provide fonts for the relevant language. The official Docker image already bundles Noto CJK fonts; a Debian/Ubuntu source deployment using the default `wkhtmltoimage` engine should install `wkhtmltopdf fonts-noto-cjk`. Installing only the conversion tool without CJK fonts can make Chinese or Korean disappear from the PNG, leaving just digits, Latin text, and borders.
`fonts-noto-cjk` is a Debian font package name and does not imply a new report language. Report output supports only `REPORT_LANGUAGE=zh|en|ko`.

Xiaohongshu branding uses the optional settings below. When all of them are empty, the footer shows no social account and the brand block takes the full width; once any value is set, a Xiaohongshu card with exactly the configured parts (QR code, handle, link) is shown:

```dotenv
SHARE_IMAGE_XIAOHONGSHU_URL=https://example.com/my-xiaohongshu
SHARE_IMAGE_XIAOHONGSHU_HANDLE=@my-account
SHARE_IMAGE_XIAOHONGSHU_QR_PATH=assets/my-xiaohongshu-qr.png
```

The QR-code path accepts an absolute path or one relative to the project root; the frozen desktop backend also resolves relative paths from the PyInstaller resource directory. The account URL accepts only `http://` or `https://`. The QR code is rendered as an inline data URI during conversion, so it does not depend on the network at runtime. No QR code is bundled; when `SHARE_IMAGE_XIAOHONGSHU_QR_PATH` is not configured, no QR code is shown. A configured handle is shown under the QR code, for example `Xiaohongshu@my-account`; a numeric ID from an older configuration takes no part in share-image rendering.

## One-click sharing on the Web

A Share button appears in the top-right corner of the browser's historical single-stock report, market review, and full-report drawer. No image is generated while the page loads the report; only after the user clicks Share does the page call `GET /api/v1/history/{record_id}/share-image` to generate or read a cached PNG on demand. Browsers that support file sharing prompt "click Share again" once the image is ready, so a second click opens the system share sheet synchronously - this avoids the asynchronous generation invalidating the browser's user-activation state. Other browsers download the PNG directly after the first generation completes. If the system share sheet fails to open, the generated PNG is downloaded automatically instead, unless the user cancelled deliberately.

The Electron desktop app shows the same Share button, but does not depend on shipping `wkhtmltoimage`, `markdown-to-file`, or Playwright. After a click, the desktop preload uses restricted IPC to have the main process open the local `GET /api/v1/history/{record_id}/share-image-html` and screenshot the full page height into a PNG through Electron's own hidden Chromium window, then falls back to the same download path as the browser. The IPC accepts only a positive integer record ID, the main process only allows the current desktop window to request the backend origin determined at startup (including an explicitly configured LAN `WEBUI_HOST`), and the HTML response uses a CSP that forbids scripts, external resources, and network loading.

Manual generation on the Web is not limited by `MARKDOWN_TO_IMAGE_CHANNELS`, but the server still needs a working `MD2IMG_ENGINE`. Manual generation on the desktop reuses Electron and does not read `MD2IMG_ENGINE`. When the Web uses Playwright, run this first:

```bash
cd apps/dsa-web
npm ci
npx playwright install chromium
```

The structured data populates the name, action, score, price, breadth, and sector fields precisely, while Markdown still covers compatibility with older calls plus text sections such as the plan and the risks. Some historical JSON only covers the fields it actually has and never clears existing quote, technical-reference, or execution-level rows from the Markdown. The template never derives an action from the score by itself, and never invents a price or an indicator. A card hides automatically when its field is `N/A`, `-`, empty, or has no matching module.

## Single-stock card field mapping

| Image area | Project field / source | Population rule |
| --- | --- | --- |
| Stock name and code | `AnalysisResult.name`, `AnalysisResult.code` | Read from the structured fields directly; the Markdown heading is only a fallback |
| Action, score, trend | `action_label` / `operation_advice`, `sentiment_score`, `trend_prediction`, `confidence_level` | Uses the final calibrated result, a score range of 0-100, and states the conclusion's confidence |
| Core conclusion | `dashboard.core_conclusion.one_sentence` | Hidden when absent |
| Market snapshot | `market_snapshot` | Current/closing price, change percentage, volume ratio, and turnover rate are shown as available; the data source goes into the footer disclaimer |
| Execution plan | `dashboard.battle_plan.sniper_points` | Shows only the ideal/confirmed buy, the stop loss, and the first target price; complex trigger conditions stay in the full report |
| Technical reference | `dashboard.data_perspective` | Shows moving-average state, trend score, MA5 bias, support, and resistance. When a structured volume ratio and turnover are already in the snapshot, the verbose volume description is not repeated; older records lacking structured volume still fall back to Markdown |
| Next observation | `dashboard.phase_decision` | Shows the action window, the next check time, and at most two watch conditions |
| Catalysts and risks | `dashboard.intelligence` | `positive_catalysts` and `risk_alerts` each show at most 2 short summaries |
| Position advice | `core_conclusion.position_advice` | Distinguishes only holding from not holding; the longer position-sizing, entry, and risk-control text stays in the full report |

The template supports the project's current Chinese, English, and Korean report labels, and the poster sections, metric labels, and footer disclaimer follow the report language. When a Decision Dashboard contains a single stock, the single-stock card is used automatically; with multiple stocks the multi-stock report layout is kept, which avoids mistaking the first stock for the whole report. Compound actions such as `强烈买入` and `Strong Buy` keep their complete action label.

## Market card field mapping

| Image area | Project field / source | Population rule |
| --- | --- | --- |
| Date, market scope | `MarketOverview.date`, the review region | Generates the A-share/US/Hong Kong market review title; a multi-market report matches `market_review_payload.markets` section by section |
| Market signal | `market_light.score`, `temperature_label`, `label`, `guidance` | Uses the deterministic market-light result; the template never re-scores it |
| Index performance | `MarketOverview.indices`, `color_scheme` | Shows the latest value and change for at most 4 major indices; the structured payload persists the `green_up` / `red_up` colour semantics used at generation time |
| Market breadth | `up_count`, `down_count`, `limit_up_count`, `limit_down_count`, `total_amount` | Shown only when the data source supports it and the report contains structured data |
| Signal breakdown | `market_light.dimensions` | Shows only deterministic scores where `available != false`; an unsupported dimension's placeholder score of 50 is never treated as real data |
| Strong and weak sectors | `sectors.top`, `sectors.bottom` | Shows the top 3 gainers and top 3 losers; a market with no sector ranking is hidden automatically |
| Capital flow observation | The review's 「资金与情绪」 section | Distils the advance/decline ratio, incremental turnover, and capital style, without disguising turnover or a news inference as net inflow |
| Focus list | The watch/avoid directions in the review's 「明日交易计划」 | Shows at most 2 sectors or themes each; the current payload has no `leader_stocks`, so no individual stocks are invented |
| Tomorrow's strategy | The review's 「明日交易计划」 section | Shows the conclusion, the position range, and the invalidation condition, without duplicating the focus list |
| Risk warnings | The review's 「风险提示」 section | Shows at most 2, filtering duplicate disclaimers |

## Manual population or local preview

The template still accepts the Markdown the project generates; the newer path additionally passes `AnalysisResult.to_dict()` or `market_review_payload`. To debug the compatibility fallback alone, prepare a minimal single-stock report. Note that the section headings below are the exact tokens `src/share_image.py` matches, so they stay in Chinese:

```markdown
## 🟢 贵州茅台 (600519)

> 2026-07-31 15:00 | 评分: **72** | 看多

### 📌 核心结论

**买入**: 趋势偏强，等待回踩支撑后分批执行。

| 持仓情况 | 操作建议 |
| --- | --- |
| 空仓者 | 等待回踩确认，不追高。 |
| 持仓者 | 继续持有，跌破止损位退出。 |

### 🎯 作战计划

| 点位类型 | 价格 |
| --- | --- |
| 理想买入点 | 1420-1450 |
| 次优买入点 | 1380-1400 |
| 止损位 | 1350 |
| 目标位 | 1580 |
```

Generate an HTML preview:

```python
from pathlib import Path
from src.share_image import ShareImageBranding, build_share_image_html

markdown_text = Path("reports/example.md").read_text(encoding="utf-8")
branding = ShareImageBranding(
    xiaohongshu_url="https://example.com/my-xiaohongshu",
    xiaohongshu_handle="@my-account",
    xiaohongshu_qr_path="assets/my-xiaohongshu-qr.png",
)
html = build_share_image_html(markdown_text, branding=branding)
Path("share-preview.html").write_text(html, encoding="utf-8")
```

To preview with real runtime data, pass the structured result:

```python
html = build_share_image_html(
    markdown_text,
    structured_payload=analysis_result.to_dict(),
)
```

The actual notification-to-PNG conversion still calls:

```python
from src.md2img import markdown_to_image

png_bytes = markdown_to_image(
    markdown_text,
    structured_payload=analysis_result.to_dict(),
)
```

A market report should keep the sections `MarketAnalyzer` generates - market signal, index structure, sector leadership, news catalysts, tomorrow's trading plan, and risk warnings. Inventing a separate set of field names externally is discouraged, because the template then treats them as missing.

## Visual and content boundaries

- Up/down colours use the `color_scheme` persisted in the structured payload first, and older records recover it from the final report's colour markers; the template never hardcodes an up/down colour by market region.
- The buy, stop-loss, and target values in a share image keep only a scannable price or a "wait for stabilization" note; the complete conditions always stay in the original report.
- No fake candlesticks are drawn when there is no real price series; the top keeps only a non-data brand glow.
- The Xiaohongshu URL, handle, and QR-code path can be overridden by runtime configuration. Only the handle is shown under the QR code, never a numeric ID. When all of them are empty, no social account is shown. GitHub always shows the repository identifier `your-org/your-repo` and generates no QR code.
- When the core modules extract successfully, a market report does not append the complete Markdown again; the extra detail sections stay in the original report and the share image presents only the structured summary.
- The bottom of the image always carries the note that the content is AI-generated, for research and discussion only, and not investment advice.
