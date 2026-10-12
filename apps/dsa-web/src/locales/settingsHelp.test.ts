import { describe, expect, it } from 'vitest';

import { getSettingsHelpContent } from './settingsHelp';

const flattenHelp = (help: ReturnType<typeof getSettingsHelpContent>) => [
  help?.summary,
  help?.usage,
  ...(help?.valueNotes ?? []),
  ...(help?.impact ?? []),
  ...(help?.notes ?? []),
].filter(Boolean).join(' ');

describe('Skill Outcome auto-weight settings help', () => {
  it('describes the attributable Outcome threshold', () => {
    const help = getSettingsHelpContent('settings.agent.AGENT_SKILL_AUTOWEIGHT');
    const visibleCopy = flattenHelp(help);

    expect(visibleCopy).toContain('Outcome');
    expect(visibleCopy).toContain('30');
    expect(visibleCopy).toContain('1.0');
    expect(visibleCopy).toContain('Global backtest win rates never substitute');
    expect(visibleCopy).not.toContain('Depends on backtest');
  });

  it('does not present Backtest as the Skill auto-weight data source', () => {
    const help = flattenHelp(getSettingsHelpContent('settings.backtest.BACKTEST_ENABLED'));

    expect(help).toContain('Skill Outcome');
    expect(help).toContain('does not directly');
  });
});

describe('settings help fallback', () => {
  it('wraps a schema description in an English help card when no curated entry exists', () => {
    expect(getSettingsHelpContent('settings.unknown.NOT_A_FIELD', 'Schema text')).toEqual({
      title: 'Configuration help',
      summary: 'Schema text',
    });
    expect(getSettingsHelpContent('settings.unknown.NOT_A_FIELD')).toBeNull();
  });
});
