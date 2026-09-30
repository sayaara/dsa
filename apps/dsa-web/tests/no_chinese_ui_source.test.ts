import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The UI is English-only. Chinese may remain in the source for three reasons,
 * and only for these:
 *
 * - `dormant`: the zh / ko halves of `Record<UiLanguage, ...>` maps. The UI
 *   language is locked to `en`, so they are unreachable (F2 in HANDOFF.md
 *   keeps them until the whole frontend is cleaned up at once).
 * - `matcher`: text that recognises backend or model output (operation
 *   advice, hotspot names, error text, the `市场阶段` prefix), plus example
 *   stock names, which are data.
 * - `comment`: doc comments quoting Chinese examples.
 *
 * Each file below is allowed at most this many lines with Chinese. A file that
 * is not listed must have none, and a listed file must not grow: new Chinese in
 * a page or component is a leak in the English UI. If a change really adds a
 * matcher or dormant entry, raise the number here and say why in the review.
 */
type Reason = 'dormant' | 'matcher' | 'comment';

const ALLOWED: Record<string, { max: number; reason: Reason }> = {
  'src/i18n/uiText.ts': { max: 925, reason: 'dormant' },
  'src/locales/settingsHelp.ts': { max: 739, reason: 'dormant' },
  'src/utils/systemConfigI18n.ts': { max: 348, reason: 'dormant' },
  'src/locales/featureText.ts': { max: 28, reason: 'dormant' },
  'src/utils/reportLanguage.ts': { max: 48, reason: 'dormant' },
  'src/components/report/AnalysisContextSummary.tsx': { max: 54, reason: 'dormant' },
  'src/components/report/MarketStructureCard.tsx': { max: 29, reason: 'dormant' },
  'src/components/report/ReportDiagnostics.tsx': { max: 21, reason: 'dormant' },
  'src/components/report/ReportNews.tsx': { max: 2, reason: 'dormant' },
  'src/utils/marketPhase.ts': { max: 14, reason: 'dormant' },
  'src/types/analysis.ts': { max: 10, reason: 'dormant' },
  'src/pages/PortfolioPage.tsx': { max: 4, reason: 'dormant' },
  'src/pages/HomePage.tsx': { max: 1, reason: 'dormant' },
  'src/pages/SettingsPage.tsx': { max: 1, reason: 'dormant' },
  'src/utils/decisionAction.ts': { max: 66, reason: 'matcher' },
  'src/components/report/MarketReviewReportView.tsx': { max: 32, reason: 'matcher' },
  'src/pages/StockScreeningPage.tsx': { max: 21, reason: 'matcher' },
  'src/pages/ChatPage.tsx': { max: 16, reason: 'matcher' },
  'src/utils/chatStockCode.ts': { max: 2, reason: 'matcher' },
  'src/pages/BacktestPage.tsx': { max: 2, reason: 'matcher' },
  'src/components/run-flow/RunFlowEventList.tsx': { max: 2, reason: 'matcher' },
  'src/components/report/ReportOverview.tsx': { max: 2, reason: 'matcher' },
  'src/components/history/StockBarItem.tsx': { max: 2, reason: 'matcher' },
  'src/components/history/HistoryListItem.tsx': { max: 2, reason: 'matcher' },
  'src/components/alerts/AlertTriggerHistory.tsx': { max: 1, reason: 'matcher' },
  'src/api/error.ts': { max: 2, reason: 'matcher' },
  'src/types/stockIndex.ts': { max: 2, reason: 'comment' },
};

// CJK ideographs, plus the full-width and CJK punctuation that leaks into English text
// (comma, full stop, colon, semicolon, enumeration comma and parentheses).
const CHINESE = /[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]/;
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

function chineseLineCounts(): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const file of collectSourceFiles(srcRoot)) {
    const lines = readFileSync(file, 'utf8').split(/\r?\n/).filter((line) => CHINESE.test(line));
    if (lines.length > 0) {
      counts[relative(process.cwd(), file).split(sep).join('/')] = lines.length;
    }
  }
  return counts;
}

describe('English-only UI source', () => {
  const counts = chineseLineCounts();

  it('has no Chinese in files that are not on the allowlist', () => {
    const unlisted = Object.entries(counts).filter(([file]) => !(file in ALLOWED));
    expect(unlisted).toEqual([]);
  });

  it('does not add Chinese lines to an allowlisted file', () => {
    const grown = Object.entries(counts)
      .filter(([file, count]) => file in ALLOWED && count > ALLOWED[file].max)
      .map(([file, count]) => `${file}: ${count} > ${ALLOWED[file].max} (${ALLOWED[file].reason})`);
    expect(grown).toEqual([]);
  });

  it('keeps the allowlist tight so a cleaned-up file cannot regress silently', () => {
    const stale = Object.entries(ALLOWED)
      .filter(([file, { max }]) => (counts[file] ?? 0) < max)
      .map(([file, { max }]) => `${file}: allowed ${max}, found ${counts[file] ?? 0}`);
    expect(stale).toEqual([]);
  });
});
