import type { ReportLanguage } from '../types/analysis';

/**
 * Reports are rendered with English chrome regardless of the language stored on
 * the record. Historical records may still carry 'zh'/'ko' narrative content in
 * their body text; only the surrounding labels are normalized here.
 */
export const normalizeReportLanguage = (value?: string | null): ReportLanguage => {
  void value;
  return 'en';
};

const REPORT_TEXT = {
  en: {
    keyInsights: 'KEY INSIGHTS',
    noAnalysisSummary: 'No analysis summary yet',
    actionAdvice: 'Action Advice',
    noAdvice: 'No advice yet',
    trendPrediction: 'Trend Outlook',
    noPrediction: 'No forecast yet',
    marketSentiment: 'Market Sentiment',
    strategyPoints: 'STRATEGY POINTS',
    sniperLevels: 'Action Levels',
    idealBuy: 'Ideal Entry',
    secondaryBuy: 'Secondary Entry',
    stopLoss: 'Stop Loss',
    takeProfit: 'Take Profit',
    noValue: '—',
    newsFeed: 'NEWS FEED',
    relatedNews: 'Related News',
    refresh: 'Refresh',
    retry: 'Retry',
    dismiss: 'Close',
    details: 'View details',
    loadingNews: 'Loading news...',
    noNews: 'No related news',
    noNewsDescription: 'Refresh later to check for the latest updates.',
    openLink: 'Open',
    transparency: 'TRANSPARENCY',
    traceability: 'Data Traceability',
    rawResult: 'Raw Analysis Result',
    analysisSnapshot: 'Analysis Snapshot',
    copy: 'Copy',
    copied: 'Copied!',
    recordId: 'Record ID',
    fullReport: 'Full analysis report',
    loadingReport: 'Loading report...',
    loadReportFailed: 'Failed to load report',
    copyMarkdownSource: 'Copy Markdown Source',
    copyPlainText: 'Copy Plain Text',
    generateShareImage: 'Share',
    generatingShareImage: 'Preparing...',
    shareImageReadyToShare: 'Share now',
    shareImageReady: 'Ready',
    shareImageFailed: 'Retry',
    analysisModel: 'Model',
    fearGreedIndex: 'Fear & Greed Index',
    boardLinkage: 'BOARD LINKAGE',
    relatedBoards: 'Related Boards',
    leadingBoard: 'Leading',
    laggingBoard: 'Lagging',
    neutralBoard: 'Neutral',
    reanalyze: 'Reanalyze',
  },
} as const;

export const getReportText = (language?: string | null) => REPORT_TEXT[normalizeReportLanguage(language)];
