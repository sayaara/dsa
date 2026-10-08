# -*- coding: utf-8 -*-
"""Chat-prompt language evaluation package.

Compares Agent Chat system-prompt variants (for example the shipped Chinese
chat prompts against translated English ones) on frozen tool outputs.
``capture_fixtures.py`` records the tool outputs, ``replay.py`` serves them to
the production chat executor, ``run_eval.py`` runs each variant, and
``metrics.py`` is the pure scoring layer.
"""
