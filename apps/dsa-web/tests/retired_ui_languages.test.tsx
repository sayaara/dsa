import type React from 'react';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { UiLanguageProvider, useUiLanguage } from '../src/contexts/UiLanguageContext';
import { UI_TEXT, type UiTextKey } from '../src/i18n/uiText';
import * as featureText from '../src/locales/featureText';
import { normalizeReportLanguage } from '../src/utils/reportLanguage';
import {
  getRuntimeInitialLanguage,
  resolveInitialUiLanguage,
  UI_LANGUAGE_STORAGE_KEY,
} from '../src/utils/uiLanguage';

/**
 * Chinese and Korean are retired UI languages (R14 in HANDOFF.md). Their data
 * is kept (F2 is deferred), but nothing may reach it, and the English data next
 * to it must stay clean. These tests make that dormancy a contract instead of an
 * assumption.
 */

const CHINESE = /[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]/;
const KOREAN = /[\uac00-\ud7af]/;

const Probe: React.FC = () => {
  const { language, setLanguage, t } = useUiLanguage();
  return (
    <div>
      <span data-testid="language">{language}</span>
      <span data-testid="sample">{t(Object.keys(UI_TEXT.en)[0] as UiTextKey)}</span>
      <button type="button" onClick={() => setLanguage('zh')}>
        switch to zh
      </button>
    </div>
  );
};

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = join(dir, entry);
    if (statSync(fullPath).isDirectory()) {
      return entry === '__tests__' || entry === 'node_modules' ? [] : collectSourceFiles(fullPath);
    }
    return /\.(ts|tsx)$/.test(fullPath) && !/\.test\.(ts|tsx)$/.test(fullPath) ? [fullPath] : [];
  });
}

/** Every string under an `en` key, for any object that has both `zh` and `en`. */
function englishStrings(value: unknown, path: string, found: Array<[string, string]> = []): Array<[string, string]> {
  if (typeof value !== 'object' || value === null) {
    return found;
  }
  const record = value as Record<string, unknown>;
  const collect = (node: unknown, where: string) => {
    if (typeof node === 'string') {
      found.push([where, node]);
    } else if (typeof node === 'object' && node !== null) {
      for (const [key, child] of Object.entries(node)) {
        collect(child, `${where}.${key}`);
      }
    }
  };
  if ('zh' in record && 'en' in record) {
    collect(record.en, `${path}.en`);
    return found;
  }
  for (const [key, child] of Object.entries(record)) {
    englishStrings(child, `${path}.${key}`, found);
  }
  return found;
}

describe('retired UI languages stay unreachable', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.lang = '';
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it('resolves the UI language to en whatever is stored or the browser asks for', () => {
    for (const stored of ['zh', 'ko', 'en', 'fr', null]) {
      const storage = { getItem: () => stored } as unknown as Storage;
      for (const language of ['zh-CN', 'ko-KR', 'en-US']) {
        expect(
          resolveInitialUiLanguage({ storage, navigatorLike: { language, languages: [language] } }),
        ).toBe('en');
      }
    }
    expect(getRuntimeInitialLanguage()).toBe('en');
  });

  it('ignores a stored zh preference and cannot be switched away from en', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    render(
      <UiLanguageProvider>
        <Probe />
      </UiLanguageProvider>,
    );

    expect(screen.getByTestId('language')).toHaveTextContent('en');
    expect(document.documentElement.lang).toBe('en');
    expect(CHINESE.test(screen.getByTestId('sample').textContent ?? '')).toBe(false);

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'switch to zh' }));
    });
    expect(screen.getByTestId('language')).toHaveTextContent('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('has no language toggle in the source tree', () => {
    expect(existsSync(join(process.cwd(), 'src', 'components', 'i18n', 'UiLanguageToggle.tsx'))).toBe(false);
    const users = collectSourceFiles(join(process.cwd(), 'src')).filter((file) =>
      readFileSync(file, 'utf8').includes('UiLanguageToggle'),
    );
    expect(users).toEqual([]);
  });

  it('renders report chrome in English for every language a stored record may carry', () => {
    for (const value of ['zh', 'ko', 'en', 'zh-CN', 'fr', '', undefined, null]) {
      expect(normalizeReportLanguage(value)).toBe('en');
    }
  });
});

describe('English data is clean', () => {
  it('has no Chinese or Korean in the English UI text', () => {
    // The native short name of the Chinese language, left over from the removed language toggle.
    const nativeLanguageNames = new Set(['language.short.zh']);
    const leaks = Object.entries(UI_TEXT.en).filter(
      ([key, text]) => !nativeLanguageNames.has(key) && (CHINESE.test(text) || KOREAN.test(text)),
    );
    expect(leaks).toEqual([]);
  });

  it('has no Chinese or Korean in the English side of the feature text tables', () => {
    const leaks = englishStrings(featureText, 'featureText').filter(
      ([, text]) => CHINESE.test(text) || KOREAN.test(text),
    );
    expect(leaks).toEqual([]);
  });
});
