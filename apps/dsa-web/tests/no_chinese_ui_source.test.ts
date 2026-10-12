import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The UI is English-only. Chinese may remain in the source for two reasons,
 * and only for these:
 *
 * - `matcher`: text that recognises backend or model output (operation
 *   advice, hotspot names, error text, the `市场阶段` prefix), plus example
 *   stock names, which are data.
 * - `comment`: doc comments quoting Chinese examples.
 *
 * A file that is not listed below must have no Chinese. A listed file may only
 * keep the exact lines recorded in `no_chinese_ui_source.baseline.json` (a
 * fingerprint of each trimmed line, with a count), so a new Chinese line is
 * caught even when a line of the same file was removed in the same change, and
 * a removed line makes the baseline stale. After a deliberate change, review the
 * diff and regenerate the baseline:
 *
 *   UPDATE_CHINESE_BASELINE=1 npx vitest run tests/no_chinese_ui_source.test.ts
 *
 * Say in the review why a matcher line was added.
 *
 * Keep the \u escapes in the CHINESE regex and the \r?\n split below as escapes:
 * a copy-paste or tool round trip can turn them into literal characters, which ESLint's
 * no-irregular-whitespace rule rejects.
 */
type Reason = 'matcher' | 'comment';

const ALLOWED: Record<string, Reason> = {
  'src/utils/decisionAction.ts': 'matcher',
  'src/components/report/MarketReviewReportView.tsx': 'matcher',
  'src/pages/StockScreeningPage.tsx': 'matcher',
  'src/pages/ChatPage.tsx': 'matcher',
  'src/utils/chatStockCode.ts': 'matcher',
  'src/pages/BacktestPage.tsx': 'matcher',
  'src/components/run-flow/RunFlowEventList.tsx': 'matcher',
  'src/components/report/ReportOverview.tsx': 'matcher',
  'src/components/history/StockBarItem.tsx': 'matcher',
  'src/components/history/HistoryListItem.tsx': 'matcher',
  'src/components/alerts/AlertTriggerHistory.tsx': 'matcher',
  'src/api/error.ts': 'matcher',
  'src/types/stockIndex.ts': 'comment',
};

// CJK ideographs, plus the full-width and CJK punctuation that leaks into English text
// (comma, full stop, colon, semicolon, enumeration comma and parentheses), and Hangul
// (jamo and syllables), so retired Korean copy cannot come back either.
const CHINESE = /[\u1100-\u11ff\u3000-\u303f\u3130-\u318f\u3400-\u9fff\uac00-\ud7af\uff00-\uffef]/;
const srcRoot = join(process.cwd(), 'src');

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = join(dir, entry);
    if (statSync(fullPath).isDirectory()) {
      return entry === '__tests__' || entry === 'node_modules' ? [] : collectSourceFiles(fullPath);
    }
    if (!/\.(ts|tsx)$/.test(fullPath) || /\.test\.(ts|tsx)$/.test(fullPath)) {
      return [];
    }
    return [fullPath];
  });
}

type Fingerprints = Record<string, Record<string, number>>;

const BASELINE_PATH = join(process.cwd(), 'tests', 'no_chinese_ui_source.baseline.json');

function fingerprint(line: string): string {
  return createHash('sha1').update(line.trim()).digest('hex').slice(0, 10);
}

/** Chinese lines per file: fingerprint -> count, plus the text for failure messages. */
function chineseLines(): { counts: Fingerprints; text: Record<string, string> } {
  const counts: Fingerprints = {};
  const text: Record<string, string> = {};
  for (const file of collectSourceFiles(srcRoot)) {
    const key = relative(process.cwd(), file).split(sep).join('/');
    for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
      if (!CHINESE.test(line)) continue;
      const fp = fingerprint(line);
      counts[key] ??= {};
      counts[key][fp] = (counts[key][fp] ?? 0) + 1;
      text[`${key}:${fp}`] = line.trim();
    }
  }
  return { counts, text };
}

function loadBaseline(): Fingerprints {
  try {
    return JSON.parse(readFileSync(BASELINE_PATH, 'utf8')) as Fingerprints;
  } catch {
    return {};
  }
}

const { counts, text } = chineseLines();
if (process.env.UPDATE_CHINESE_BASELINE) {
  const sorted = Object.fromEntries(
    Object.entries(counts)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([file, fps]) => [file, Object.fromEntries(Object.entries(fps).sort(([a], [b]) => a.localeCompare(b)))]),
  );
  writeFileSync(BASELINE_PATH, `${JSON.stringify(sorted, null, 1)}\n`);
}
const baseline = loadBaseline();

describe('English-only UI source', () => {
  it('has no Chinese in files that are not on the allowlist', () => {
    const unlisted = Object.keys(counts).filter((file) => !(file in ALLOWED));
    expect(unlisted).toEqual([]);
  });

  it('adds no Chinese line that is not in the baseline', () => {
    const added: string[] = [];
    for (const [file, fps] of Object.entries(counts)) {
      for (const [fp, count] of Object.entries(fps)) {
        const extra = count - (baseline[file]?.[fp] ?? 0);
        if (extra > 0) added.push(`${file} (${ALLOWED[file] ?? 'unlisted'}) x${extra}: ${text[`${file}:${fp}`]}`);
      }
    }
    expect(added).toEqual([]);
  });

  it('keeps the baseline tight so a cleaned-up line cannot regress silently', () => {
    const stale: string[] = [];
    for (const [file, fps] of Object.entries(baseline)) {
      for (const [fp, count] of Object.entries(fps)) {
        const missing = count - (counts[file]?.[fp] ?? 0);
        if (missing > 0) stale.push(`${file}: ${missing} baseline line(s) gone (${fp})`);
      }
    }
    expect(stale).toEqual([]);
  });
});
