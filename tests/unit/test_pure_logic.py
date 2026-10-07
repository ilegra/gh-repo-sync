from src.core.sync import is_exclusive_path, parse_author, validate_branch_name


def test_validate_branch_name() -> None:
    # Valid branches
    assert validate_branch_name("main") is True
    assert validate_branch_name("feature/ABC-123") is True
    assert validate_branch_name("bugfix.name") is True
    assert validate_branch_name("releases/v1.0.0") is True

    # Invalid branches
    assert validate_branch_name("") is False
    assert validate_branch_name("-starts-with-dash") is False
    assert validate_branch_name("has spaces") is False
    assert validate_branch_name("has~tilde") is False
    assert validate_branch_name("has^caret") is False
    assert validate_branch_name("has:colon") is False
    assert validate_branch_name("has?question") is False
    assert validate_branch_name("has*star") is False
    assert validate_branch_name("has[bracket") is False
    assert validate_branch_name("has..dotdot") is False
    assert validate_branch_name("/starts-with-slash") is False
    assert validate_branch_name("ends-with-slash/") is False


def test_is_exclusive_path() -> None:
    exclusive = [".github", ".pipeline", "azure-pipelines*.yml", "charts"]

    # Exact matches and subpath matches
    assert is_exclusive_path(".github", exclusive) is True
    assert is_exclusive_path(".github/workflows/ci.yml", exclusive) is True
    assert is_exclusive_path(".pipeline/build.sh", exclusive) is True
    assert is_exclusive_path("charts/values.yaml", exclusive) is True
    assert is_exclusive_path("sub/folder/charts/Chart.yaml", exclusive) is True

    # Glob matches
    assert is_exclusive_path("azure-pipelines.yml", exclusive) is True
    assert is_exclusive_path("azure-pipelines-ci.yml", exclusive) is True
    assert is_exclusive_path("ci/azure-pipelines-prod.yml", exclusive) is True

    # Non-matches (should NOT match partial or unrelated)
    assert is_exclusive_path(".github2/file", exclusive) is False
    assert is_exclusive_path("my_charts_folder", exclusive) is False
    assert is_exclusive_path("azure-pipelines.txt", exclusive) is False
    assert is_exclusive_path("src/index.js", exclusive) is False


def test_parse_author() -> None:
    bot_name = "test-bot"
    bot_email = "bot@example.com"

    # Valid author
    name, email = parse_author("Alice Doe\talice@example.com", bot_name, bot_email)
    assert name == "Alice Doe"
    assert email == "alice@example.com"

    # Missing email separator
    name, email = parse_author("Alice Doe", bot_name, bot_email)
    assert name == bot_name
    assert email == bot_email

    # Email missing @
    name, email = parse_author("Alice Doe\tnot-an-email", bot_name, bot_email)
    assert name == bot_name
    assert email == bot_email

    # Empty string
    name, email = parse_author("", bot_name, bot_email)
    assert name == bot_name
    assert email == bot_email
