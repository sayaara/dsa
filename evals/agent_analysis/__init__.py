# -*- coding: utf-8 -*-
"""Agent analysis evaluation package.

Compares the Agent analysis path (``AgentExecutor.run``, the decision dashboard
the pipeline builds in agent mode) between prompt versions on frozen tool
outputs. ``capture_fixtures.py`` records the tool outputs with the chat eval's
capture, ``run_eval.py`` replays them through the production executor and scores
the dashboard with the prompt-language metrics plus the tool trajectory, and
``metrics.py`` is the pure scoring layer.
"""
