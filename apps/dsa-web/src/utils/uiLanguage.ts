import type { UiLanguage } from '../i18n/uiText';

/** Key older builds stored the UI language under; it no longer selects anything. */
export const UI_LANGUAGE_STORAGE_KEY = 'dsa.uiLanguage';

/**
 * The product ships an English-only interface: stored preferences and the
 * browser locale do not select the UI language.
 */
export const UI_LANGUAGE: UiLanguage = 'en';

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
