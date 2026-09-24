import type React from 'react';
import { createContext, useContext, useEffect, useMemo } from 'react';
import { formatUiText, UI_TEXT, type UiLanguage, type UiTextKey, type UiTextParams } from '../i18n/uiText';
import { UI_LANGUAGE } from '../utils/uiLanguage';

type UiLanguageContextValue = {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  t: (key: UiTextKey, params?: UiTextParams) => string;
};

/**
 * The interface is English-only. `setLanguage` is kept on the context so that
 * existing consumers keep compiling, but it is intentionally inert: there is no
 * longer a second language to switch to.
 */
const noopSetLanguage = (): void => undefined;

const fallbackContext: UiLanguageContextValue = {
  language: UI_LANGUAGE,
  setLanguage: noopSetLanguage,
  t: (key, params) => formatUiText(UI_TEXT[UI_LANGUAGE][key], params),
};

const UiLanguageContext = createContext<UiLanguageContextValue | null>(null);

export const UiLanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.lang = 'en';
    }
  }, []);

  const value = useMemo<UiLanguageContextValue>(() => ({
    language: UI_LANGUAGE,
    setLanguage: noopSetLanguage,
    t: (key, params) => formatUiText(UI_TEXT[UI_LANGUAGE][key], params),
  }), []);

  return (
    <UiLanguageContext.Provider value={value}>
      {children}
    </UiLanguageContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components -- useUiLanguage is a hook, co-located for context access
export function useUiLanguage(): UiLanguageContextValue {
  return useContext(UiLanguageContext) ?? fallbackContext;
}
