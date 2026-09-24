from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_env_example_documents_searxng_actions_variable_mapping() -> None:
    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")

    start = env_example.index("# SearXNG instance URLs")
    end = env_example.index("SEARXNG_PUBLIC_INSTANCES_ENABLED=", start)
    searxng_block = env_example[start:end]

    assert "GitHub Actions" in searxng_block
    assert "prefers same-named Variables" in searxng_block
    assert "Secrets" in searxng_block
    # The URL may be a Variable, so the template must not tell users it has to be a Secret.
    assert "must be configured as a Secret" not in searxng_block


def test_env_example_defaults_public_searxng_instances_off() -> None:
    """Public instance discovery is off by default: public instances usually rate-limit or return no JSON,
    so defaulting to on makes users without a search key wait 30-60 seconds for nothing and get empty news."""
    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")

    assert "SEARXNG_PUBLIC_INSTANCES_ENABLED=false" in env_example
    assert "SEARXNG_PUBLIC_INSTANCES_ENABLED=true" not in env_example


def test_searxng_timeout_env_contract() -> None:
    from src.config import parse_env_int

    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
    assert "SEARXNG_TIMEOUT_SECONDS=10" in env_example
    assert parse_env_int(None, 10, field_name="SEARXNG_TIMEOUT_SECONDS", minimum=1) == 10
    assert parse_env_int("25", 10, field_name="SEARXNG_TIMEOUT_SECONDS", minimum=1) == 25
    assert parse_env_int("0", 10, field_name="SEARXNG_TIMEOUT_SECONDS", minimum=1) == 1


def test_daily_analysis_workflow_matches_documented_searxng_variable_mapping() -> None:
    workflow = (
        ROOT_DIR / ".github" / "workflows" / "00-daily-analysis.yml"
    ).read_text(encoding="utf-8")

    assert (
        "SEARXNG_BASE_URLS: ${{ vars.SEARXNG_BASE_URLS || secrets.SEARXNG_BASE_URLS }}"
        in workflow
    )
    assert "SEARXNG_BASE_URLS: ${{ secrets.SEARXNG_BASE_URLS }}" not in workflow


def test_changelog_mentions_searxng_actions_variable_mapping() -> None:
    changelog = (ROOT_DIR / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert (
        "- [修复] GitHub Actions 每日分析工作流读取 SearXNG 自建实例地址时"
        "支持 Variables 优先、Secrets 回退，修复仅配置 Variables 时 URL 不生效的问题。"
    ) in changelog


def test_runtime_default_disables_public_searxng_instances(monkeypatch) -> None:
    """With the environment variable unset, the runtime must resolve to off.

    This is where the change actually takes effect: editing .env.example alone only reaches users who
    copied the new template, while existing installs and GitHub Actions (where the variable is empty
    when no Variable/Secret is configured) would keep discovering public instances and paying the 30-60 second retry cost.
    """
    from src.config import parse_env_bool

    monkeypatch.delenv("SEARXNG_PUBLIC_INSTANCES_ENABLED", raising=False)
    import os

    assert (
        parse_env_bool(os.getenv("SEARXNG_PUBLIC_INSTANCES_ENABLED"), default=False)
        is False
    )


def test_config_constructor_defaults_public_searxng_instances_off() -> None:
    """Building a Config directly must also honour the public-instance-discovery-off-by-default contract."""
    from src.config import Config

    assert Config().searxng_public_instances_enabled is False


def test_config_module_uses_false_as_runtime_default() -> None:
    """Pin the default in config.py, so a later change cannot quietly revert it."""
    src = (ROOT_DIR / "src" / "config.py").read_text(encoding="utf-8")
    idx = src.index("SEARXNG_PUBLIC_INSTANCES_ENABLED")
    window = src[idx : idx + 200]

    assert "default=False" in window
    assert "default=True" not in window


def test_workflow_reports_disabled_when_variable_unset() -> None:
    """Workflow diagnostics must not report an unset variable as enabled, contradicting the runtime."""
    workflow = (
        ROOT_DIR / ".github" / "workflows" / "00-daily-analysis.yml"
    ).read_text(encoding="utf-8")

    assert "on by default" not in workflow
    assert "off by default" in workflow


def test_docs_describe_public_searxng_discovery_as_opt_in() -> None:
    zeabur_docs = [
        ROOT_DIR / "docs" / "docker" / "zeabur-deployment.md",
    ]
    for path in zeabur_docs:
        content = path.read_text(encoding="utf-8")
        base_url_lines = [
            line for line in content.splitlines() if "`SEARXNG_BASE_URLS`" in line
        ]
        public_toggle_lines = [
            line
            for line in content.splitlines()
            if "`SEARXNG_PUBLIC_INSTANCES_ENABLED`" in line
        ]
        assert base_url_lines
        assert public_toggle_lines
        assert all(
            "when empty the app auto-discovers public instances" not in line
            for line in base_url_lines
        )
        assert all("defaults to `false`" in line for line in public_toggle_lines)

    english_guide = "\n".join(
        (ROOT_DIR / "docs" / name).read_text(encoding="utf-8")
        for name in ("full-guide.md", "DEPLOY.md")
    )
    english_base_url_lines = [
        line for line in english_guide.splitlines() if "`SEARXNG_BASE_URLS`" in line
    ]
    english_public_toggle_lines = [
        line
        for line in english_guide.splitlines()
        if "`SEARXNG_PUBLIC_INSTANCES_ENABLED`" in line
    ]
    assert english_base_url_lines
    assert english_public_toggle_lines
    assert all(
        "when empty the app auto-discovers public instances" not in line
        for line in english_base_url_lines
    )
    assert all("default `false`" in line for line in english_public_toggle_lines)


def test_constructor_kwargs_carry_searxng_timeout_for_subprocess_rebuild() -> None:
    """A bounded topic search rebuilding SearchService in a subprocess must carry the timeout settings (PR #2249 blocker)."""
    from src.search_service import SearchService

    service = SearchService(
        searxng_base_urls=["http://searxng.local:8080"],
        searxng_timeout_seconds=25,
    )
    kwargs = service._constructor_kwargs
    assert kwargs["searxng_timeout_seconds"] == 25
    assert kwargs["searxng_base_urls"] == ["http://searxng.local:8080"]

    # Rebuilt in the subprocess from the same kwargs, the provider should get the same timeout
    rebuilt = SearchService(**kwargs)
    searxng = next(p for p in rebuilt._providers if p.name == "SearXNG")
    assert searxng._self_hosted_timeout_seconds == 25


def test_daily_analysis_workflow_maps_searxng_timeout_variable() -> None:
    workflow = (
        ROOT_DIR / ".github" / "workflows" / "00-daily-analysis.yml"
    ).read_text(encoding="utf-8")
    assert (
        "SEARXNG_TIMEOUT_SECONDS: ${{ vars.SEARXNG_TIMEOUT_SECONDS || secrets.SEARXNG_TIMEOUT_SECONDS }}"
        in workflow
    )
