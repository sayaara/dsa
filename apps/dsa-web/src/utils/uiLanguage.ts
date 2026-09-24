import type { UiLanguage } from '../i18n/uiText';

export const UI_LANGUAGE_STORAGE_KEY = 'dsa.uiLanguage';

/**
 * The product ships an English-only interface.
 *
 * The persistence and normalization helpers below are retained so that stored
 * values from older builds are handled gracefully, but the resolved UI language
 * is always 'en': stored preferences and browser locale no longer select it.
 */
export const UI_LANGUAGE: UiLanguage = 'en';

export function normalizeUiLanguage(value?: string | null): UiLanguage | null {
  if (value === 'zh' || value === 'en') {
    return value;
  }
  return null;
}

export function getUiLanguageStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function persistUiLanguage(storage: Storage | null, language: UiLanguage): void {
  if (!storage) {
    return;
  }

  try {
    storage.setItem(UI_LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Ignore storage failures; in-memory language still updates.
  }
}

export function resolveInitialUiLanguage(options?: {
  storage?: Storage | null;
  navigatorLike?: Pick<Navigator, 'language' | 'languages'> | null;
}): UiLanguage {
  void options;
  return UI_LANGUAGE;
}

export function getRuntimeInitialLanguage(): UiLanguage {
  return UI_LANGUAGE;
}
