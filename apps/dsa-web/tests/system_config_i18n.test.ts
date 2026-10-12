import { describe, expect, it } from 'vitest';
import { UI_TEXT } from '../src/i18n/uiText';
import { getSettingsHelpContent, getSettingsHelpFieldTitle } from '../src/locales/settingsHelp';
import { getFieldOptionLabel } from '../src/utils/systemConfigI18n';

const helpText = (help: ReturnType<typeof getSettingsHelpContent>) => [
  help?.title,
  help?.summary,
  help?.usage,
  ...(help?.valueNotes ?? []),
  ...(help?.impact ?? []),
  ...(help?.notes ?? []),
].join('\n');

describe('settings help content', () => {
  it('documents LLM usage HMAC privacy boundaries', () => {
    const help = getSettingsHelpContent('settings.ai_model.LLM_USAGE_HMAC_SECRET');

    expect(help?.summary).toContain('HMAC');
    expect(help?.notes?.join(' ')).toContain('Do not');
  });

  it('documents the runtime scheduler timeout', () => {
    const text = JSON.stringify(getSettingsHelpContent('settings.system.schedule'));

    expect(text).toContain('DSA_RUNTIME_SCHEDULER_TIMEOUT_SECONDS');
    expect(text).toContain('2700');
    expect(text).toContain('60');
  });

  it('describes only the supported markets', () => {
    const marketText = [
      helpText(getSettingsHelpContent('settings.system.market_review')),
      helpText(getSettingsHelpContent('settings.system.TRADING_DAY_CHECK_ENABLED')),
    ].join('\n');

    expect(marketText).toContain('Canad');
    expect(marketText).toContain('US');
    expect(marketText).not.toMatch(/\bhk\b|Hong Kong|A-share/i);
  });
});

describe('systemConfigI18n option label localization', () => {
  const realSelectOptionCases = [
    ['NEWS_STRATEGY_PROFILE', 'ultra_short', undefined, 'Ultra short (1 day)'],
    ['NEWS_STRATEGY_PROFILE', 'short', undefined, 'Short (3 days)'],
    ['NEWS_STRATEGY_PROFILE', 'medium', undefined, 'Medium (7 days)'],
    ['NEWS_STRATEGY_PROFILE', 'long', undefined, 'Long (30 days)'],
    ['REPORT_TYPE', 'simple', undefined, 'Simple'],
    ['REPORT_TYPE', 'full', undefined, 'Full'],
    ['REPORT_TYPE', 'brief', undefined, 'Brief'],
    ['REPORT_LANGUAGE', 'en', undefined, 'English'],
    ['NOTIFICATION_MIN_SEVERITY', '', undefined, 'Not set'],
    ['NOTIFICATION_MIN_SEVERITY', 'info', undefined, 'Info'],
    ['NOTIFICATION_MIN_SEVERITY', 'critical', undefined, 'Critical'],
    ['LOG_LEVEL', 'DEBUG', undefined, 'Debug'],
    ['LOG_LEVEL', 'CRITICAL', undefined, 'Critical'],
    ['LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL', 'off', undefined, 'Off'],
    ['MARKET_REVIEW_COLOR_SCHEME', 'green_up', undefined, 'Green up / red down'],
    ['MARKET_REVIEW_COLOR_SCHEME', 'red_up', undefined, 'Red up / green down'],
    ['GENERATION_BACKEND', 'litellm', undefined, 'Default model settings'],
    ['GENERATION_FALLBACK_BACKEND', '', undefined, 'Disabled'],
    ['AGENT_GENERATION_BACKEND', 'auto', undefined, 'Auto'],
    ['AGENT_ARCH', 'multi', undefined, 'Multi Agent (orchestrator)'],
    ['AGENT_ORCHESTRATOR_MODE', 'specialist', undefined, 'Specialist'],
    ['AGENT_SKILL_ROUTING', 'manual', undefined, 'Manual (use AGENT_SKILLS)'],
    ['AGENT_SKILL_ROUTING', 'x', 'Auto (Regime-based)', 'Auto (regime-based)'],
  ] as const;

  it('labels the select options exposed by the system config schema', () => {
    realSelectOptionCases.forEach(([key, value, fallbackLabel, expectedLabel]) => {
      expect(getFieldOptionLabel(key, value, fallbackLabel)).toBe(expectedLabel);
    });
  });

  it('treats free-text config keys as passthrough for option labels', () => {
    expect(getFieldOptionLabel('MARKET_REVIEW_REGION', 'ca')).toBe('ca');
    expect(getFieldOptionLabel('MARKET_REVIEW_REGION', 'ca,us')).toBe('ca,us');
  });
});

describe('SAVE_CONTEXT_SNAPSHOT settings help contract', () => {
  it('describes the persistence boundary without implying old records are changed', () => {
    const text = helpText(getSettingsHelpContent('settings.system.SAVE_CONTEXT_SNAPSHOT'));

    expect(text).toContain('new history records do not persist');
    expect(text).toContain('does not disable AnalysisContextPack construction');
    expect(text).toContain('does not remove the low-sensitivity pack summary from LLM prompts');
    expect(text).not.toMatch(/old records|existing records/i);
  });
});

describe('generation backend settings help contract', () => {
  it('uses user-facing generation channel copy instead of implementation terms', () => {
    const enBackend = getSettingsHelpContent('settings.ai_model.GENERATION_BACKEND');
    const enFallback = getSettingsHelpContent('settings.ai_model.GENERATION_FALLBACK_BACKEND');
    const enAgent = getSettingsHelpContent('settings.agent.AGENT_GENERATION_BACKEND');
    const enText = [helpText(enBackend), helpText(enFallback), helpText(enAgent)].join('\n');

    expect(enBackend?.title).toBe('Analysis Generation Method');
    expect(enFallback?.title).toBe('Fallback Generation Method');
    expect(enAgent?.title).toBe('Ask-Stock Generation Method');
    expect(enText).toContain('stock analysis');
    expect(enText).toContain('market reviews');
    expect(enText).toContain('Auto');
    expect(enBackend?.usage).toContain('Default model settings');
    expect(enFallback?.usage).toContain('Default model settings');
    expect(enAgent?.usage).toContain('currently available method');
    expect(enAgent?.valueNotes).toContain('If you are unsure, choose Auto.');
    expect(enBackend?.notes?.join('\n')).toContain('Default model settings continue');
    expect(enBackend?.notes?.join('\n')).not.toContain('Advanced note');
    expect(enBackend?.notes?.join('\n')).not.toContain('LiteLLM');
    expect(enText).not.toContain('current available model channel');
    expect(enText).not.toContain('unsupported_tool_calling');
    expect(enText).not.toContain('run_agent_loop');
  });
});

describe('generation backend status panel i18n contract', () => {
  it('keeps the status panel copy in the UI text table', () => {
    expect(UI_TEXT.en['settings.generationBackendStatus']).toBe('Generation backend status');
    expect(UI_TEXT.en['settings.generationBackendSmokeTest']).toBe('JSON smoke test');
    expect(UI_TEXT.en['settings.generationBackendPrimary']).toBe('Primary backend');
    expect(UI_TEXT.en['settings.generationBackendFallback']).toBe('Fallback backend');
    expect(UI_TEXT.en['settings.generationBackendGenerationOnly']).toBe('Generation only');
  });
});

describe('decision signal settings guard', () => {
  it('does not add placeholder DecisionSignal setting help without a real schema field', () => {
    const placeholderKeys = [
      'DECISION_SIGNAL_ENABLED',
      'DECISION_SIGNALS_ENABLED',
      'DECISION_SIGNAL_WRITE_ENABLED',
      'DECISION_SIGNAL_EXTRACT_ENABLED',
    ];

    placeholderKeys.forEach((key) => {
      expect(getSettingsHelpFieldTitle(key)).toBeNull();
    });
  });
});
