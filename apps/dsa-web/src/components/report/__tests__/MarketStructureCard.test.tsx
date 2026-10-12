import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { MarketStructureContext } from '../../../types/analysis';
import { MarketStructureCard } from '../MarketStructureCard';

const context: MarketStructureContext = {
  schemaVersion: 'market-structure-v1',
  status: 'partial',
  market: 'us',
  tradeDate: '2026-07-04',
  marketThemeContext: {
    schemaVersion: 'market-theme-v1',
    status: 'partial',
    market: 'us',
    activeThemes: [
      { name: '机器人概念', changePct: 4.2, rank: 1, source: 'concept', phase: 'accelerating' },
    ],
    leadingConcepts: [
      { name: '机器人概念', changePct: 4.2, rank: 1, source: 'concept' },
    ],
    leadingIndustries: [
      { name: '通用设备', changePct: 2.1, rank: 2, source: 'industry' },
    ],
    laggingThemes: [],
    themeBreadth: {
      activeCount: 1,
      leadingConceptCount: 1,
      leadingIndustryCount: 1,
      laggingCount: 0,
    },
    dataQuality: {
      status: 'partial',
      missingFields: ['industry_rankings'],
      sources: [],
      errors: [],
    },
  },
  stockMarketPosition: {
    schemaVersion: 'stock-market-position-v1',
    status: 'partial',
    stockCode: '300024',
    stockName: '机器人',
    market: 'us',
    primaryTheme: {
      name: '机器人概念',
      source: 'concept',
      phase: 'accelerating',
      rank: 1,
      changePct: 4.2,
    },
    relatedBoards: [
      { name: '机器人概念', type: '概念', source: 'concept', rank: 1, changePct: 4.2 },
    ],
    stockRole: 'follower',
    themePhase: 'accelerating',
    riskTags: [
      { code: 'theme_data_partial', message: 'Market theme data is incomplete' },
      { code: 'stock_theme_evidence_partial', message: 'Stock board did not match theme rankings' },
    ],
    missingFields: ['hotspot_constituents', 'leader_stocks'],
  },
};

describe('MarketStructureCard', () => {
  it('renders the market layer and the stock layer', () => {
    render(<MarketStructureCard context={context} />);

    expect(screen.getByRole('region', { name: 'Themes and Stock Position' })).toBeInTheDocument();
    expect(screen.getByText('Market Theme Layer')).toBeVisible();
    expect(screen.getByText('Stock Position Layer')).toBeVisible();
    expect(screen.getAllByText('Partial')).toHaveLength(3);
    expect(screen.getAllByText(/机器人概念/)).toHaveLength(3);
    expect(screen.getByText('Accelerating')).toBeVisible();
    expect(screen.getByText('Follower')).toBeVisible();
    expect(screen.getByText('Market theme data is incomplete')).toBeVisible();
    expect(screen.getByText('leader_stocks')).toBeVisible();
  });

  it('renders English labels', () => {
    render(<MarketStructureCard context={context} language="en" />);

    expect(screen.getByRole('region', { name: 'Themes and Stock Position' })).toBeInTheDocument();
    expect(screen.getByText('Market Theme Layer')).toBeVisible();
    expect(screen.getByText('Stock Position Layer')).toBeVisible();
    expect(screen.getByText('Accelerating')).toBeVisible();
    expect(screen.getByText('Follower')).toBeVisible();
    expect(screen.getByText('Missing Evidence')).toBeVisible();
    expect(screen.getByText('Market theme data is incomplete')).toBeVisible();
    expect(screen.getByText('Stock board did not match theme rankings')).toBeVisible();
  });

  it('does not render unsupported or invalid context', () => {
    const unsupported = {
      ...context,
      status: 'not_supported',
    } satisfies MarketStructureContext;

    const { container, rerender } = render(<MarketStructureCard context={unsupported} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<MarketStructureCard context={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
