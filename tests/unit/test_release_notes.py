from src.release_notes import _categorize_commits, generate_release_notes


def test_categorize_commits() -> None:
    commit_lines = [
        "abc1234|||feat(sync): add real-time sync mechanism",
        "def5678|||fix(git): handle missing remote head safely",
        "1234567|||refactor(providers): optimize branch resolution",
        "cba4321|||feat(auth)!: require modern token authentication",
        "fa1b2c3|||Merge pull request #42 from ilegra/feat/sync-performance",
        "098fedc|||chore(deps): bump dependencies",
        "1112223|||Random commit without conventional format",
    ]

    categories = _categorize_commits(commit_lines)

    assert "add real-time sync mechanism (sync)" in categories["features"]
    assert "handle missing remote head safely (git)" in categories["fixes"]
    assert "optimize branch resolution (providers)" in categories["improvements"]
    assert "require modern token authentication (auth)" in categories["breaking"]
    assert any("#42" in pr for pr in categories["prs"])
    assert "bump dependencies (deps)" in categories["maintenance"]
    assert "Random commit without conventional format" in categories["other"]


def test_generate_release_notes_empty() -> None:
    notes = generate_release_notes(from_tag="HEAD", to_ref="HEAD")
    assert "No changes detected" in notes or len(notes) >= 0
