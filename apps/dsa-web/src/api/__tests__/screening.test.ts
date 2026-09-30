import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screeningApi } from '../screening';

const { get, post, getConfig, updateConfig } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getConfig: vi.fn(),
  updateConfig: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    get,
    post,
  },
}));

vi.mock('../systemConfig', () => ({
  systemConfigApi: {
    getConfig: (...args: unknown[]) => getConfig(...args),
    update: (...args: unknown[]) => updateConfig(...args),
  },
}));

describe('screeningApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    getConfig.mockReset();
    updateConfig.mockReset();
    window.localStorage.clear();
    window.localStorage.setItem('dsa.screening.variantSeed.v1', 'browser-seed');
  });

  it('enables the config and checks built-in screening availability', async () => {
    getConfig.mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' });
    updateConfig.mockResolvedValueOnce({ success: true });
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        available: true,
      },
    });

    await screeningApi.enable();

    expect(updateConfig).toHaveBeenCalledWith({
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'SCREENING_ENABLED', value: 'true' }],
    });
    expect(get).toHaveBeenCalledWith('/api/v1/screening/status');
    expect(updateConfig).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });

  it('keeps enable behavior when called without object binding', async () => {
    getConfig.mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' });
    updateConfig.mockResolvedValueOnce({ success: true });
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        available: true,
      },
    });

    const enable = screeningApi.enable;
    await enable();

    expect(updateConfig).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });

  it('rolls back SCREENING_ENABLED when the built-in engine is unavailable', async () => {
    getConfig
      .mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' })
      .mockResolvedValueOnce({ configVersion: 'v2', maskToken: '******' });
    updateConfig.mockResolvedValue({ success: true });
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        available: false,
        diagnostics: { reason: 'missing_module' },
      },
    });

    await expect(screeningApi.enable()).rejects.toThrow('Screening is unavailable');

    expect(updateConfig).toHaveBeenNthCalledWith(1, {
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'SCREENING_ENABLED', value: 'true' }],
    });
    expect(updateConfig).toHaveBeenNthCalledWith(2, {
      configVersion: 'v2',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'SCREENING_ENABLED', value: 'false' }],
    });
    expect(post).not.toHaveBeenCalled();
  });

  it('loads strategies from the built-in screening API', async () => {
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        strategies: [
          {
            id: 'dual_low',
            name: 'Dual Low',
            description: 'value',
            category: 'value',
            market_scope: ['us'],
          },
        ],
        strategy_count: 1,
      },
    });

    const result = await screeningApi.getStrategies();

    expect(get).toHaveBeenCalledWith('/api/v1/screening/strategies', { timeout: 300000 });
    expect(result.enabled).toBe(true);
    expect(result.strategyCount).toBe(1);
    expect(result.strategies[0].id).toBe('dual_low');
    expect(result.strategies[0].marketScope).toEqual(['us']);
  });

  it('uses a long timeout for LLM-backed screening', async () => {
    post.mockResolvedValueOnce({
      data: {
        enabled: true,
        candidates: [],
        candidate_count: 0,
        llm_ranked: true,
      },
    });

    await screeningApi.screen({ market: 'cn', strategy: 'dual_low', maxResults: 3 });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/screening/screen',
      { market: 'cn', strategy: 'dual_low', max_results: 3, variant_seed: 'browser-seed' },
      { timeout: 180000 }
    );
  });

  it('starts an async screening task', async () => {
    post.mockResolvedValueOnce({
      data: {
        task_id: 'screen-task-1',
        trace_id: 'screen-task-1',
        status: 'pending',
        message: 'Screening Screening task submitted',
        strategy: 'dual_low',
        market: 'cn',
        max_results: 3,
      },
    });

    const result = await screeningApi.startScreen({ market: 'cn', strategy: 'dual_low', maxResults: 3 });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/screening/screen/tasks',
      { market: 'cn', strategy: 'dual_low', max_results: 3, variant_seed: 'browser-seed' }
    );
    expect(result.taskId).toBe('screen-task-1');
    expect(result.maxResults).toBe(3);
  });

  it('keeps one opaque screening variant seed per browser', async () => {
    window.localStorage.removeItem('dsa.screening.variantSeed.v1');
    vi.resetModules();
    const isolatedScreening = await import('../screening');

    const first = isolatedScreening.getScreeningVariantSeed();
    const second = isolatedScreening.getScreeningVariantSeed();

    expect(first).not.toBe('');
    expect(second).toBe(first);
    expect(window.localStorage.getItem('dsa.screening.variantSeed.v1')).toBe(first);
  });

  it('reuses one session seed across sync and async requests when browser storage rejects access', async () => {
    window.localStorage.removeItem('dsa.screening.variantSeed.v1');
    vi.resetModules();
    const isolatedScreening = await import('../screening');
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('storage disabled');
    });
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('storage disabled');
    });
    post
      .mockResolvedValueOnce({ data: { enabled: true, candidates: [], candidate_count: 0 } })
      .mockResolvedValueOnce({
        data: {
          task_id: 'screen-task-storage-disabled',
          trace_id: 'screen-task-storage-disabled',
          status: 'pending',
          message: 'Screening task submitted',
          strategy: 'dual_low',
          market: 'cn',
          max_results: 3,
        },
      });

    try {
      const first = isolatedScreening.getScreeningVariantSeed();
      const second = isolatedScreening.getScreeningVariantSeed();
      expect(first).not.toBe('');
      expect(second).toBe(first);

      await isolatedScreening.screeningApi.screen({ market: 'cn', strategy: 'dual_low', maxResults: 3 });
      await isolatedScreening.screeningApi.startScreen({ market: 'cn', strategy: 'dual_low', maxResults: 3 });

      expect(post.mock.calls[0]?.[1]).toMatchObject({ variant_seed: first });
      expect(post.mock.calls[1]?.[1]).toMatchObject({ variant_seed: first });
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });

  it('loads async screening task status', async () => {
    get.mockResolvedValueOnce({
      data: {
        task_id: 'screen-task-1',
        trace_id: 'screen-task-1',
        status: 'completed',
        progress: 100,
        message: 'Task 执行完成',
        result: {
          enabled: true,
          candidates: [],
          candidate_count: 0,
          daily_enriched: true,
          daily_enrich_count: 4,
          post_analyzers: ['scorecard'],
        },
      },
    });

    const result = await screeningApi.getScreenTask('screen-task-1');

    expect(get).toHaveBeenCalledWith('/api/v1/screening/screen/tasks/screen-task-1');
    expect(result.taskId).toBe('screen-task-1');
    expect(result.result?.candidateCount).toBe(0);
    expect(result.result?.dailyEnriched).toBe(true);
    expect(result.result?.dailyEnrichCount).toBe(4);
    expect(result.result?.postAnalyzers).toEqual(['scorecard']);
  });
});
