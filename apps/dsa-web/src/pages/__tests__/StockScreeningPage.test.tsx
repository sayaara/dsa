import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StockScreeningPage from '../StockScreeningPage';

const {
  enableScreening,
  getHistory,
  getRun,
  getScreeningStatus,
  getStrategies,
  getScreenTask,
  navigate,
  resetLastScreenResult,
  screenStocks,
  startScreenTask,
} = vi.hoisted(() => {
  let lastScreenResult: unknown = null;
  const screenStocks = vi.fn();
  const startScreenTask = vi.fn(async (payload: unknown) => {
    lastScreenResult = await screenStocks(payload);
    return {
      taskId: 'screen-task-1',
      traceId: 'screen-task-1',
      status: 'pending',
      message: 'Screening Screening task submitted',
      strategy: 'dual_low',
      market: 'us',
      maxResults: 3,
    };
  });
  const getScreenTask = vi.fn(async (taskId: string) => {
    void taskId;
    return {
      taskId: 'screen-task-1',
      traceId: 'screen-task-1',
      status: 'completed',
      progress: 100,
      message: 'Task 执行完成',
      result: lastScreenResult,
    };
  });
  return {
    enableScreening: vi.fn(),
    getHistory: vi.fn(),
    getRun: vi.fn(),
    getScreeningStatus: vi.fn(),
    getStrategies: vi.fn(),
    getScreenTask,
    navigate: vi.fn(),
    resetLastScreenResult: () => {
      lastScreenResult = null;
    },
    screenStocks,
    startScreenTask,
  };
});

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock('../../api/screening', () => ({
  screeningApi: {
    enable: () => enableScreening(),
    getStatus: () => getScreeningStatus(),
    getHistory: (payload: unknown) => getHistory(payload),
    getRun: (runId: string) => getRun(runId),
    getStrategies: () => getStrategies(),
    getScreenTask: (taskId: string) => getScreenTask(taskId),
    screen: (payload: unknown) => screenStocks(payload),
    startScreen: (payload: unknown) => startScreenTask(payload),
  },
}));

const mockStrategiesResponse = {
  enabled: true,
  strategies: [
    {
      id: 'dual_low',
      name: 'Dual Low',
      title: 'Dual Low',
      description: 'Low valuation strategy',
      category: 'value',
      tag: 'value',
      tags: ['value'],
      marketScope: ['us'],
    },
  ],
  strategyCount: 1,
};

function createDeferred<T>() {
  let resolve: (value: T) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('StockScreeningPage', () => {
  beforeEach(() => {
    enableScreening.mockReset();
    getHistory.mockReset();
    getRun.mockReset();
    getScreeningStatus.mockReset();
    getStrategies.mockReset();
    getScreenTask.mockClear();
    navigate.mockReset();
    resetLastScreenResult();
    screenStocks.mockReset();
    startScreenTask.mockClear();
    getStrategies.mockResolvedValue(mockStrategiesResponse);
    getHistory.mockResolvedValue({ runs: [] });
    getRun.mockRejectedValue(Object.assign(new Error('run not found'), {
      parsedError: {
        title: 'Screening task cannot be recovered',
        message: '服务端没有找到这次选股任务，可能后端已重启或任务记录已清理，请重新运行选股。',
        rawMessage: 'screening_screen_task_not_found',
        category: 'http_error',
      },
    }));
    window.sessionStorage.clear();
  });

  it('keeps implementation attribution and repeated guidance off the operation page', async () => {
    getScreeningStatus.mockResolvedValueOnce({ enabled: true, available: true });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    expect(screen.queryByText(/AlphaSift/)).not.toBeInTheDocument();
    expect(screen.queryByText(/theme_heat/)).not.toBeInTheDocument();
    expect(screen.queryByText('实验功能与风险提示')).not.toBeInTheDocument();
    expect(screen.queryByText('Screening results')).not.toBeInTheDocument();
  });

  it('re-syncs enabled state when Screening availability check fails after config is enabled', async () => {
    getScreeningStatus
      .mockResolvedValueOnce({
        enabled: false,
        available: false,
      })
      .mockResolvedValueOnce({
        enabled: true,
        available: false,
      });
    enableScreening.mockRejectedValueOnce(new Error('选股功能不可用，请检查后端日志'));

    render(<StockScreeningPage />);

    expect((await screen.findAllByText('Screening disabled')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /Run screening/ })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Enable screening' }));

    await waitFor(() => expect(getScreeningStatus).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText('Screening disabled').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /Run screening/ })).toBeDisabled();
    expect(screen.getByText('Screening unavailable')).toBeInTheDocument();
    expect(screen.getByText('选股功能不可用，请检查后端日志')).toBeInTheDocument();
  });

  it('shows input strategy when strategy is not in preset list', async () => {
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValue({
      enabled: true,
      candidates: [],
      candidateCount: 0,
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Strategy'), {
      target: { value: '__custom_strategy__' },
    });
    fireEvent.change(screen.getByLabelText('Custom strategy ID'), {
      target: { value: 'custom_strategy_alpha' },
    });

    expect(screen.getByDisplayValue('custom_strategy_alpha')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));
    await waitFor(() => expect(screenStocks).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText(/Custom strategy \(custom_strategy_alpha\)/)).toBeInTheDocument());
  });

  it('uses supported Screening strategy ids and us market', async () => {
    getStrategies.mockResolvedValueOnce({
      enabled: true,
      strategies: [
        { id: 'balanced_alpha', name: '平衡选股', description: 'desc', category: '框架' },
        { id: 'capital_heat', name: '资金热度', description: 'desc', category: 'Momentum' },
        { id: 'dual_low', name: '双低', description: 'desc', category: '价值' },
        { id: 'oversold_reversal', name: '超跌', description: 'desc', category: 'Reversal' },
        { id: 'shrink_pullback', name: '缩量回踩', description: 'desc', category: 'Trend' },
      ],
      strategyCount: 5,
    });
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValue({
      enabled: true,
      candidates: [],
      candidateCount: 0,
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();

    const marketSelect = screen.getByLabelText('Market') as HTMLSelectElement;
    expect(Array.from(marketSelect.options).map((option) => option.value)).toEqual(['us']);

    const strategySelect = screen.getByLabelText('Strategy') as HTMLSelectElement;
    expect(Array.from(strategySelect.options).map((option) => option.textContent)).toEqual([
      '平衡选股',
      '资金热度',
      '双低',
      '超跌',
      '缩量回踩',
      'Custom strategy...',
    ]);

    ['balanced_alpha', 'capital_heat', 'oversold_reversal', 'shrink_pullback'].forEach((id) => {
      fireEvent.change(strategySelect, { target: { value: id } });
      expect(strategySelect.value).toBe(id);
    });

    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));
    await waitFor(() => expect(screenStocks).toHaveBeenCalledTimes(1));
    expect(screenStocks).toHaveBeenCalledWith({
      market: 'us',
      strategy: 'shrink_pullback',
      maxResults: 3,
    });
  });

  it('clears previous screening candidates when strategy changes', async () => {
    getStrategies.mockResolvedValueOnce({
      enabled: true,
      strategies: [
        { id: 'dual_low', name: '双低选股', description: 'desc', category: '价值' },
        { id: 'capital_heat', name: '资金热度', description: 'desc', category: 'Momentum' },
      ],
      strategyCount: 2,
    });
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '旧策略股票',
          score: 88.5,
          reason: 'old result',
          raw: {},
        },
      ],
      candidateCount: 1,
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));

    expect(await screen.findByText('旧策略股票')).toBeInTheDocument();
    expect(screen.getByText('Screening complete')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Strategy'), { target: { value: 'capital_heat' } });

    expect(screen.queryByText('旧策略股票')).not.toBeInTheDocument();
    expect(screen.queryByText('Screening complete')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Strategy')).toHaveValue('capital_heat');
  });

  it('hands a screening candidate to DSA analysis with mapped skills', async () => {
    getStrategies.mockResolvedValueOnce({
      enabled: true,
      strategies: [
        {
          id: 'dual_low',
          name: '双低选股',
          description: 'desc',
          category: '价值',
          analysisSkills: ['growth_quality'],
        },
      ],
      strategyCount: 1,
    });
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '600519',
          name: '贵州茅台',
          score: 88.5,
          reason: '候选摘要',
          raw: {},
        },
      ],
      candidateCount: 1,
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument();
    const expandButton = screen.queryByRole('button', { name: 'Expand' });
    if (expandButton) {
      fireEvent.click(expandButton);
    }
    fireEvent.click(screen.getByRole('button', { name: 'Run deeper analysis' }));

    expect(navigate).toHaveBeenCalledWith('/', {
      state: {
        stockCode: '600519',
        stockName: '贵州茅台',
        autoAnalyze: true,
        selectionSource: 'screening_result',
        skills: ['growth_quality'],
      },
    });
  });

  it('restores an in-flight screening task after remounting the page', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '恢复后的候选',
          score: 88.5,
          reason: 'restored result',
          raw: {},
        },
      ],
      candidateCount: 1,
    });
    getScreenTask
      .mockResolvedValueOnce({
        taskId: 'screen-task-1',
        traceId: 'screen-task-1',
        status: 'processing',
        progress: 35,
        message: '正在执行 Screening 选股',
        result: null,
      })
      .mockResolvedValueOnce({
        taskId: 'screen-task-1',
        traceId: 'screen-task-1',
        status: 'completed',
        progress: 100,
        message: 'Task 执行完成',
        result: {
          enabled: true,
          candidates: [
            {
              rank: 1,
              code: '000001',
              name: '恢复后的候选',
              score: 88.5,
              reason: 'restored result',
              raw: {},
            },
          ],
          candidateCount: 1,
        },
      });

    const firstRender = render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));

    expect(await screen.findByText('Screening running')).toBeInTheDocument();
    expect(window.sessionStorage.getItem('dsa.screening.activeScreenTask.v1')).toContain('screen-task-1');

    firstRender.unmount();
    render(<StockScreeningPage />);

    expect(await screen.findByText('恢复后的候选')).toBeInTheDocument();
    expect(screen.getByText('Screening complete')).toBeInTheDocument();
    // Option A: keep runId after the task finishes (instead of clearing it) so a refresh can restore from the history API
    expect(window.sessionStorage.getItem('dsa.screening.activeScreenTask.v1')).toContain('screen-task-1');
  });

  it('keeps a restored screening task recoverable when status polling times out', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    window.sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'screen-task-1',
      market: 'us',
      strategy: 'dual_low',
      maxResults: 3,
    }));
    getScreenTask.mockRejectedValueOnce(Object.assign(new Error('timeout of 30000ms exceeded'), {
      code: 'ECONNABORTED',
    }));

    render(<StockScreeningPage />);

    await waitFor(() => expect(getScreenTask).toHaveBeenCalledTimes(1));
    // The notice renders only after the rejected poll is handled, so wait for it rather than for the call.
    expect(await screen.findByText('The screening task is still running in the background. Status polling timed out and will retry automatically.')).toBeInTheDocument();
    expect(screen.getByText('Screening running')).toBeInTheDocument();
    expect(screen.queryByText(/连接上游服务超时/)).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem('dsa.screening.activeScreenTask.v1')).toContain('screen-task-1');
  });

  it('clears the persisted recovery state when a restored task becomes unrecoverable', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    window.sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'screen-task-1',
      market: 'us',
      strategy: 'dual_low',
      maxResults: 3,
    }));
    getScreenTask.mockRejectedValueOnce(Object.assign(new Error('Screening task cannot be recovered'), {
      parsedError: {
        title: 'Screening task cannot be recovered',
        message: '服务端没有找到这次选股任务，可能后端已重启或任务记录已清理，请重新运行选股。',
        rawMessage: 'screening_screen_task_not_found',
        category: 'http_error',
      },
    }));

    render(<StockScreeningPage />);

    await waitFor(() => expect(getScreenTask).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/Screening task cannot be recovered/)).toBeInTheDocument();
    expect(screen.queryByText('Screening running')).not.toBeInTheDocument();
    // An unrecoverable branch must clear the persisted restore state, so a refresh does not keep restoring the same dead task
    expect(window.sessionStorage.getItem('dsa.screening.activeScreenTask.v1')).toBeNull();
  });

  it('keeps the persisted recovery state and history visible after filters change', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '旧筛选条件下的候选',
          score: 88.5,
          reason: 'old filter result',
          raw: {},
        },
      ],
      candidateCount: 1,
      runId: 'run-1',
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));

    expect(await screen.findByText('旧筛选条件下的候选')).toBeInTheDocument();
    expect(window.sessionStorage.getItem('dsa.screening.activeScreenTask.v1')).toContain('run-1');

    // Change the filter (result count 3 -> 5): the current result view clears, but the persisted restore state must survive
    fireEvent.change(screen.getByRole('spinbutton', { name: /Result count/ }), { target: { value: '5' } });
    expect(screen.queryByText('旧筛选条件下的候选')).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem('dsa.screening.activeScreenTask.v1')).toContain('run-1');

    // The history block stays visible (switching filters does not affect history availability)
    expect(screen.getByText('History')).toBeInTheDocument();
  });

  it('shows the screening conditions on each history entry', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-1',
          strategy: 'dual_low',
          market: 'us',
          candidateCount: 3,
          snapshotCount: 50,
          llmRanked: true,
          createdAt: '2026-08-05T10:00:00Z',
        },
      ],
      runCount: 1,
    });

    render(<StockScreeningPage />);

    // History entries show the filter: strategy display name + market label + result count (the candidates that run actually produced)
    expect(await screen.findByText(/Returned 3/)).toBeInTheDocument();
    expect(screen.getAllByText('Dual Low').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('US stocks').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Snapshot 50/)).toBeInTheDocument();
    expect(screen.getByText(/Smart re-rank/)).toBeInTheDocument();
  });

  it('syncs strategy and market context when opening a history run', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-1',
          strategy: 'capital_heat',
          market: 'us',
          candidateCount: 3,
          snapshotCount: 50,
          llmRanked: true,
          createdAt: '2026-08-05T10:00:00Z',
        },
      ],
      runCount: 1,
    });
    getRun.mockResolvedValue({
      runId: 'run-1',
      strategy: 'capital_heat',
      market: 'us',
      candidateCount: 3,
      enabled: true,
      result: {
        enabled: true,
        candidates: [
          {
            rank: 1,
            code: '00700',
            name: '腾讯控股',
            score: 88.5,
            reason: '热度因子领先',
            amount: 1042000000,
            factorScores: { heat: 92 },
            raw: {},
          },
        ],
        candidateCount: 1,
        snapshotCount: 50,
        afterFilterCount: 10,
        llmRanked: true,
      },
    });

    render(<StockScreeningPage />);

    // Click a run in the history (strategy capital_heat, unlike the form default dual_low)
    fireEvent.click(await screen.findByText('capital_heat'));

    // The result area syncs to that history run's strategy and market
    expect(await screen.findByText(/Custom strategy \(capital_heat\) · US stocks/)).toBeInTheDocument();
    expect(getRun).toHaveBeenCalledWith('run-1');
  });

  it('ignores stale history-detail responses when switching runs quickly', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-a',
          strategy: 'capital_heat',
          market: 'us',
          candidateCount: 1,
          createdAt: '2026-08-05T10:00:00Z',
        },
        {
          runId: 'run-b',
          strategy: 'dual_low',
          market: 'us',
          candidateCount: 1,
          createdAt: '2026-08-06T10:00:00Z',
        },
      ],
      runCount: 2,
    });
    const runADetail = createDeferred<unknown>();
    const runBDetail = createDeferred<unknown>();
    getRun.mockImplementation((runId: string) => {
      if (runId === 'run-a') {
        return runADetail.promise;
      }
      if (runId === 'run-b') {
        return runBDetail.promise;
      }
      return Promise.reject(new Error(`unexpected runId: ${runId}`));
    });

    render(<StockScreeningPage />);

    // Click run-a first (capital_heat, request left pending), then run-b (dual_low)
    fireEvent.click(await screen.findByText('capital_heat'));
    fireEvent.click(screen.getByRole('button', { name: /Dual Low/ }));
    await waitFor(() => expect(getRun).toHaveBeenLastCalledWith('run-b'));

    // run-b returns first: the result area shows the dual_low context
    await act(async () => {
      runBDetail.resolve({
        runId: 'run-b',
        strategy: 'dual_low',
        market: 'us',
        candidateCount: 1,
        enabled: true,
        result: {
          enabled: true,
          candidates: [
            {
              rank: 1,
              code: '000001',
              name: '平安银行',
              score: 88.5,
              reason: '双低策略',
              amount: 1042000000,
              factorScores: { value: 92 },
              raw: {},
            },
          ],
          candidateCount: 1,
          snapshotCount: 50,
          afterFilterCount: 10,
          llmRanked: true,
        },
      });
    });
    expect(await screen.findByText(/Dual Low · US stocks/)).toBeInTheDocument();

    // run-a returns late: it must not overwrite run-b's results or context
    await act(async () => {
      runADetail.resolve({
        runId: 'run-a',
        strategy: 'capital_heat',
        market: 'us',
        candidateCount: 1,
        enabled: true,
        result: {
          enabled: true,
          candidates: [
            {
              rank: 1,
              code: '00700',
              name: '腾讯控股',
              score: 90,
              reason: '热度因子领先',
              amount: 1042000000,
              factorScores: { heat: 92 },
              raw: {},
            },
          ],
          candidateCount: 1,
          snapshotCount: 50,
          afterFilterCount: 10,
          llmRanked: true,
        },
      });
    });
    expect(screen.getByText(/Dual Low · US stocks/)).toBeInTheDocument();
    expect(screen.queryByText(/Custom strategy \(capital_heat\)/)).not.toBeInTheDocument();
    expect(screen.queryByText('腾讯控股')).not.toBeInTheDocument();
  });

  it('ignores late auto-restore responses after the user manually picks a history run', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    // Persisted run-a: mounting triggers the automatic restore getRun('run-a')
    window.sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'task-a',
      runId: 'run-a',
      strategy: 'capital_heat',
      market: 'us',
      maxResults: 3,
    }));
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-b',
          strategy: 'dual_low',
          market: 'us',
          candidateCount: 1,
          createdAt: '2026-08-05T10:00:00Z',
        },
      ],
      runCount: 1,
    });

    const runA = createDeferred();
    getRun.mockImplementation((runId: string) => {
      if (runId === 'run-a') {
        return runA.promise;
      }
      return Promise.resolve({
        runId: 'run-b',
        strategy: 'dual_low',
        market: 'us',
        candidateCount: 1,
        enabled: true,
        result: {
          enabled: true,
          candidates: [
            {
              rank: 1,
              code: '600000',
              name: '浦发银行',
              score: 88,
              reason: '低估值',
              amount: 1042000000,
              factorScores: { value: 87 },
              raw: {},
            },
          ],
          candidateCount: 1,
          snapshotCount: 50,
          afterFilterCount: 10,
          llmRanked: true,
        },
      });
    });

    render(<StockScreeningPage />);

    // While the automatic restore of run-a is still pending, the user opens run-b from the history (strategy dual_low -> shows Dual Low)
    fireEvent.click(await screen.findByText(/Returned 1/));
    expect(await screen.findByText(/Dual Low · US stocks/)).toBeInTheDocument();
    expect(screen.getByText('浦发银行')).toBeInTheDocument();

    // run-a returns later: it must not overwrite the run-b the user picked
    await act(async () => {
      runA.resolve({
        runId: 'run-a',
        strategy: 'capital_heat',
        market: 'us',
        candidateCount: 1,
        enabled: true,
        result: {
          enabled: true,
          candidates: [
            {
              rank: 1,
              code: '00700',
              name: '腾讯控股',
              score: 90,
              reason: '热度因子领先',
              amount: 1042000000,
              factorScores: { heat: 92 },
              raw: {},
            },
          ],
          candidateCount: 1,
          snapshotCount: 50,
          afterFilterCount: 10,
          llmRanked: true,
        },
      });
    });
    expect(screen.getByText(/Dual Low · US stocks/)).toBeInTheDocument();
    expect(screen.getByText('浦发银行')).toBeInTheDocument();
    expect(screen.queryByText(/Custom strategy \(capital_heat\)/)).not.toBeInTheDocument();
    expect(screen.queryByText('腾讯控股')).not.toBeInTheDocument();
  });

  it('cancels an in-flight screening task when a history run is selected', async () => {
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-hist',
          strategy: 'capital_heat',
          market: 'us',
          candidateCount: 1,
          createdAt: '2026-08-05T10:00:00Z',
        },
      ],
      runCount: 1,
    });
    // Submit an unfinished task (pending): background polling starts
    getScreenTask.mockResolvedValueOnce({
      taskId: 'screen-task-1',
      traceId: 'screen-task-1',
      status: 'running',
      progress: 40,
      message: 'Screening 正在分析...',
      result: null,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '600000',
          name: 'Task 候选',
          score: 80,
          reason: 'Task 原因',
          amount: 100,
          factorScores: { value: 80 },
          raw: {},
        },
      ],
      candidateCount: 1,
      snapshotCount: 50,
      afterFilterCount: 10,
      llmRanked: true,
    });
    getRun.mockResolvedValueOnce({
      runId: 'run-hist',
      strategy: 'capital_heat',
      market: 'us',
      candidateCount: 1,
      enabled: true,
      result: {
        enabled: true,
        candidates: [
          {
            rank: 1,
            code: '00700',
            name: '历史候选',
            score: 90,
            reason: '历史原因',
            amount: 1042000000,
            factorScores: { heat: 92 },
            raw: {},
          },
        ],
        candidateCount: 1,
        snapshotCount: 50,
        afterFilterCount: 10,
        llmRanked: true,
      },
    });

    render(<StockScreeningPage />);

    // Once screening is enabled, submit a screening task and start polling
    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));
    await waitFor(() => expect(startScreenTask).toHaveBeenCalled());
    await waitFor(() => expect(getScreenTask).toHaveBeenCalled());

    // While the task is still polling, click a history run (strategy capital_heat)
    fireEvent.click(await screen.findByText('capital_heat'));
    expect(await screen.findByText(/Custom strategy \(capital_heat\)/)).toBeInTheDocument();
    expect(screen.getByText('历史候选')).toBeInTheDocument();

    // The background task then finishes, and must still not write its candidates back into the history context
    expect(screen.queryByText('Task 候选')).not.toBeInTheDocument();
    expect(screen.getByText(/Custom strategy \(capital_heat\)/)).toBeInTheDocument();
  });

  it('surfaces Screening LLM fallback instead of showing empty LLM fields as normal', async () => {
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '平安银行',
          score: 88.5,
          reason: '本地后置评分: value_quality',
          amount: 1042000000,
          factorScores: {
            value: 87.44,
            liquidity: 93.33,
          },
          raw: {},
        },
      ],
      candidateCount: 1,
      snapshotCount: 5193,
      afterFilterCount: 20,
      llmRanked: false,
      rankingMode: 'factor',
      llmFailureReason: 'invalid_response',
      llmParseErrors: ['no_json_found'],
      warnings: ['LLM ranking failed, falling back to screen_score: Missing gemini_api_key'],
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));

    expect(await screen.findByText('Using factor ranking')).toBeInTheDocument();
    expect(screen.getByText(/No usable LLM API key/)).toBeInTheDocument();
    expect(screen.queryByText(/Missing gemini_api_key/)).not.toBeInTheDocument();
    expect(screen.getByText(/Ranking: Deterministic factors/)).toBeInTheDocument();
    expect(screen.getByText('Factor ranking')).toBeInTheDocument();
    expect(screen.getByText(/Key strengths: Liquidity 93, Valuation 87/)).toBeInTheDocument();
    expect(screen.queryByText(/LLM 已降级/)).not.toBeInTheDocument();
  });

  it('deduplicates Screening snapshot fallback warnings and source errors', async () => {
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '601919',
          name: '中远海控',
          score: 82.88,
          llmScore: 82,
          riskLevel: 'low',
          raw: {},
        },
      ],
      candidateCount: 1,
      llmRanked: true,
      warnings: ['Snapshot source fallback: yfinance: yfinance request timed out'],
      sourceErrors: ['yfinance: yfinance request timed out'],
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));

    expect(await screen.findByText('Screening notice')).toBeInTheDocument();
    expect(screen.getAllByText('Data source degraded: yfinance (Request timed out)')).toHaveLength(1);
    expect(screen.queryByText(/yfinance request timed out/)).not.toBeInTheDocument();
  });

  it('sanitizes long Screening source diagnostics and keeps the alert constrained', async () => {
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '600016',
          name: '民生银行',
          score: 80.12,
          raw: {},
        },
      ],
      candidateCount: 1,
      llmRanked: true,
      warnings: [
        "Snapshot source fallback: efinance: HTTPConnectionPool(host='push2.eastmoney.com', port=80): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=200&po=1&fields=f12%2Cf14%2Cf2%2Cf3 (Caused by ProtocolError('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')))",
        "Snapshot source fallback: akshare_em: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))",
      ],
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));

    const efinanceWarning = await screen.findByText('Data source degraded: efinance (Network connection lost)');
    const alert = efinanceWarning.closest('[role="alert"]');
    expect(alert).toHaveClass('max-w-full');
    expect(efinanceWarning).toBeInTheDocument();
    expect(screen.getByText('Data source degraded: akshare_em (Network connection lost)')).toBeInTheDocument();
    expect(screen.queryByText(/HTTPConnectionPool/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/api\/qt\/clist\/get/)).not.toBeInTheDocument();
    expect(screen.queryByText(/RemoteDisconnected/)).not.toBeInTheDocument();
  });

  it('shows DSA enrichment summary, news, and enrichment metadata', async () => {
    getScreeningStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '600519',
          name: '贵州茅台',
          score: 91.2,
          reason: 'Screening pick',
          dsaAnalysisSummary: 'DSA行情：现价 1688，涨跌幅 1.2%；DSA新闻：贵州茅台最新公告',
          dsaNews: [{ title: '贵州茅台最新公告', source: '测试源' }],
          dsaContext: {
            enriched: true,
            warnings: ['stock_news_unavailable'],
          },
          raw: {},
        },
      ],
      candidateCount: 1,
      dsaEnrichment: {
        enabled: true,
        requestedCount: 1,
        enrichedCount: 1,
      },
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));

    expect(await screen.findByText('Deep enrichment: 1 / 1')).toBeInTheDocument();

    expect(screen.getByText('Enhanced summary')).toBeInTheDocument();
    expect(screen.getByText(/Quote: 现价 1688/)).toBeInTheDocument();
    expect(screen.getByText('Related news')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台最新公告')).toBeInTheDocument();
    expect(screen.getByText('Data enrichment notes')).toBeInTheDocument();
    expect(screen.getByText('stock_news_unavailable')).toBeInTheDocument();
  });
  it('keeps the shared loading held when a stale auto-restore finishes while a manual history request is in flight', async () => {
    // Regression OR-COR-9b1f8c4e: a stale automatic restore must not clear the shared loading flag unconditionally in finally,
    // or "Run screening" would be re-enabled while a manual history-detail request is still in flight.
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    window.sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'task-a',
      runId: 'run-a',
      strategy: 'capital_heat',
      market: 'us',
      maxResults: 3,
    }));
    let resolveRunA: (value: unknown) => void = () => {};
    let resolveRunB: (value: unknown) => void = () => {};
    getRun.mockImplementation((runId: string) => {
      if (runId === 'run-a') {
        return new Promise((resolve) => {
          resolveRunA = resolve;
        });
      }
      if (runId === 'run-b') {
        return new Promise((resolve) => {
          resolveRunB = resolve;
        });
      }
      return Promise.reject(new Error('run not found'));
    });
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-b',
          strategy: 'dual_low',
          market: 'us',
          candidateCount: 1,
          createdAt: '2026-08-05T10:00:00Z',
        },
      ],
      runCount: 1,
    });
    render(<StockScreeningPage />);
    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    // While the automatic restore of run-a is still in flight, the user opens run-b from the history
    fireEvent.click(await screen.findByRole('button', { name: /Dual Low/ }));
    // First let the stale automatic restore of run-a finish (its response is already judged stale by request id)
    resolveRunA({
      runId: 'run-a',
      strategy: 'capital_heat',
      market: 'us',
      candidateCount: 1,
      enabled: true,
      result: {
        enabled: true,
        candidates: [
          {
            rank: 1,
            code: '600519',
            name: '贵州茅台',
            score: 90,
            reason: '热度',
            raw: {},
          },
        ],
        candidateCount: 1,
        snapshotCount: 50,
        afterFilterCount: 10,
        llmRanked: true,
      },
    });
    await act(async () => {});
    // The stale finally does not clear the shared loading flag: the form stays disabled (the button renders as a spinner while
    // loading, so the market dropdown is asserted instead), and the page has not switched to any history result
    expect(screen.getByLabelText('Market')).toBeDisabled();
    expect(screen.queryByText(/Dual Low · US stocks/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Custom strategy \(capital_heat\)/)).not.toBeInTheDocument();
    // run-b then returns normally: the results come back and loading is closed out by that request itself
    resolveRunB({
      runId: 'run-b',
      strategy: 'dual_low',
      market: 'us',
      candidateCount: 1,
      enabled: true,
      result: {
        enabled: true,
        candidates: [
          {
            rank: 1,
            code: '600000',
            name: '浦发银行',
            score: 88,
            reason: '低估值',
            raw: {},
          },
        ],
        candidateCount: 1,
        snapshotCount: 50,
        afterFilterCount: 10,
        llmRanked: true,
      },
    });
    expect(await screen.findByText(/Dual Low · US stocks/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('Market')).toBeEnabled());
  });
  it('polls a newly submitted task immediately while a stale auto-restore request is still pending', async () => {
    // Regression OR-COR-2c71d8af: handleSubmit must release the automatic-restore latch and invalidate the in-flight restore request,
    // or the new task's polling would be blocked until the old request times out and the page would freeze on the submit progress.
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    window.sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'task-a',
      runId: 'run-a',
      strategy: 'capital_heat',
      market: 'us',
      maxResults: 3,
    }));
    // The automatic restore of run-a hangs forever (simulating a wedged old request)
    getRun.mockImplementation((runId: string) => {
      if (runId === 'run-a') {
        return new Promise(() => {});
      }
      return Promise.resolve({
        runId: 'run-b',
        strategy: 'dual_low',
        market: 'us',
        candidateCount: 1,
        enabled: true,
        result: {
          enabled: true,
          candidates: [
            {
              rank: 1,
              code: '600000',
              name: '历史候选',
              score: 80,
              reason: 'History',
              raw: {},
            },
          ],
          candidateCount: 1,
          snapshotCount: 50,
          afterFilterCount: 10,
          llmRanked: true,
        },
      });
    });
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-b',
          strategy: 'dual_low',
          market: 'us',
          candidateCount: 1,
          createdAt: '2026-08-05T10:00:00Z',
        },
      ],
      runCount: 1,
    });
    screenStocks.mockResolvedValue({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '新任务候选',
          score: 88,
          reason: '新任务',
          raw: {},
        },
      ],
      candidateCount: 1,
    });
    render(<StockScreeningPage />);
    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    // While the automatic restore hangs, the user opens history run-b first (it returns normally and closes out loading itself)
    fireEvent.click(await screen.findByRole('button', { name: /Dual Low/ }));
    expect(await screen.findByText(/Dual Low · US stocks/)).toBeInTheDocument();
    // A new task is then submitted: polling must start immediately, unblocked by the still-pending automatic-restore latch
    fireEvent.click(screen.getByRole('button', { name: /Run screening/ }));
    await waitFor(() => expect(getScreenTask).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/新任务候选/)).toBeInTheDocument();
  });
  it('does not rewrite a restored custom strategy when the strategy list arrives late', async () => {
    // Regression: a late /strategies response must not rewrite a custom strategy from the history/restore context back to the default.
    let resolveStrategies: (value: unknown) => void = () => {};
    getStrategies.mockImplementation(
      () => new Promise((resolve) => {
        resolveStrategies = resolve;
      }),
    );
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    window.sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'task-a',
      runId: 'run-a',
      strategy: 'capital_heat',
      market: 'us',
      maxResults: 3,
    }));
    getRun.mockResolvedValue({
      runId: 'run-a',
      strategy: 'capital_heat',
      market: 'us',
      candidateCount: 1,
      enabled: true,
      result: {
        enabled: true,
        candidates: [
          {
            rank: 1,
            code: '600519',
            name: '贵州茅台',
            score: 90,
            reason: '热度',
            raw: {},
          },
        ],
        candidateCount: 1,
        snapshotCount: 50,
        afterFilterCount: 10,
        llmRanked: true,
      },
    });
    getHistory.mockResolvedValue({ enabled: true, runs: [], runCount: 0 });
    render(<StockScreeningPage />);
    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    // The automatic restore applies the history context first (the strategy list request is still pending)
    expect(await screen.findByText(/Custom strategy \(capital_heat\) · US stocks/)).toBeInTheDocument();
    // The late strategy list does not contain that history strategy
    resolveStrategies({
      enabled: true,
      strategies: [
        { id: 'dual_low', name: '双低', description: 'desc', category: '价值' },
      ],
      strategyCount: 1,
    });
    await act(async () => {});
    // Normalisation is skipped: the form dropdown switches to the custom entry, the input keeps the raw ID, and the result heading is unchanged
    expect(screen.getByLabelText('Strategy')).toHaveValue('__custom_strategy__');
    expect(screen.getByLabelText('Custom strategy ID')).toHaveValue('capital_heat');
    expect(screen.getByText(/Custom strategy \(capital_heat\) · US stocks/)).toBeInTheDocument();
  });
  it('persists the selected history run so a refresh restores that run instead of the stale task', async () => {
    // Regression OR-COR-4d1a7e90: opening a history record manually must also sync the persisted restore pointer,
    // so a refresh restores the history run the user just picked rather than an earlier task.
    getScreeningStatus.mockResolvedValue({
      enabled: true,
      available: true,
    });
    window.sessionStorage.setItem('dsa.screening.activeScreenTask.v1', JSON.stringify({
      taskId: 'task-a',
      strategy: 'dual_low',
      market: 'us',
      maxResults: 3,
    }));
    getHistory.mockResolvedValue({
      enabled: true,
      runs: [
        {
          runId: 'run-b',
          strategy: 'capital_heat',
          market: 'us',
          candidateCount: 1,
          createdAt: '2026-08-05T10:00:00Z',
        },
      ],
      runCount: 1,
    });
    getRun.mockResolvedValue({
      runId: 'run-b',
      strategy: 'capital_heat',
      market: 'us',
      candidateCount: 1,
      enabled: true,
      result: {
        enabled: true,
        candidates: [
          {
            rank: 1,
            code: '600519',
            name: '贵州茅台',
            score: 90,
            reason: '热度',
            raw: {},
          },
        ],
        candidateCount: 1,
        snapshotCount: 50,
        afterFilterCount: 10,
        llmRanked: true,
      },
    });
    getScreenTask.mockResolvedValue({
      taskId: 'task-a',
      traceId: 'task-a',
      status: 'processing',
      progress: 10,
      message: '正在执行 Screening 选股',
      result: null,
    });
    const first = render(<StockScreeningPage />);
    expect(await screen.findByText('Screening enabled')).toBeInTheDocument();
    // Manually select history run-b (strategy capital_heat)
    fireEvent.click(await screen.findByText('capital_heat'));
    expect(await screen.findByText(/Custom strategy \(capital_heat\) · US stocks/)).toBeInTheDocument();
    // The persisted pointer has switched to the history run just selected
    const stored = JSON.parse(
      window.sessionStorage.getItem('dsa.screening.activeScreenTask.v1') || '{}',
    );
    expect(stored.runId).toBe('run-b');
    expect(stored.taskId).toBe('run-b');
    // After a refresh (remount) the new pointer restores run-b, not the old task-a
    first.unmount();
    render(<StockScreeningPage />);
    await waitFor(() => expect(getRun).toHaveBeenLastCalledWith('run-b'));
    expect(await screen.findByText(/Custom strategy \(capital_heat\) · US stocks/)).toBeInTheDocument();
    // A successful restore must not trigger polling on the placeholder taskId
    expect(getScreenTask).not.toHaveBeenCalledWith('run-b');
  });
});
