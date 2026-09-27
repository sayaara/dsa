# -*- coding: utf-8 -*-
"""Prompt-language evaluation package.

Compares analyzer prompt variants (for example the shipped Chinese base
prompt with its English output override against a translated English base
prompt) on frozen analyzer inputs. ``capture_fixtures.py`` records the
inputs, ``run_eval.py`` replays them per variant, and ``metrics.py`` is the
pure scoring layer.
"""
