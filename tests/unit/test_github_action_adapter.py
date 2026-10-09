import json
from unittest.mock import patch

import pytest

from src.adapters.github_action import GithubActionOutputAdapter
from src.config import SyncResult


def test_publish_outputs_sync_result_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = GithubActionOutputAdapter()
    result = SyncResult(
        repo_name="destination-repo",
        origin_repo="https://dev.azure.com/org/project/_git/origin-repo",
        destination_repo="https://github.com/org/destination-repo.git",
        evaluated_branches=["main", "feature/test"],
        updated_branches=["feature/test"],
        removed_branches=["feature/old"],
        synced_tags=["v1.0.0"],
        already_disabled=False,
        errors=[],
    )

    with patch("builtins.open") as mock_open:
        adapter.publish(result)
        mock_open.assert_not_called()

    captured = capsys.readouterr()
    expected_prefix = "::set-output name=sync-result::"
    assert captured.out.startswith(expected_prefix)

    json_str = captured.out.strip()[len(expected_prefix) :]
    parsed = json.loads(json_str)
    assert parsed["repo_name"] == "destination-repo"
    assert parsed["evaluated_branches"] == ["main", "feature/test"]
    assert parsed["updated_branches"] == ["feature/test"]
    assert parsed["removed_branches"] == ["feature/old"]
    assert parsed["synced_tags"] == ["v1.0.0"]
    assert parsed["already_disabled"] is False
    assert parsed["errors"] == []
