"""Provider baseline input contracts without calling external services."""

import pytest

from acessilia_benchmark.core.runs import prepare
from acessilia_benchmark.services import inference


def test_structure_rejects_two_page_input_before_provider_calls(workspace, dataset_factory):
    dataset_factory("drdocbench-dev")
    prepare(workspace, "drdocbench-dev", "two", workspace.data, 1, 42)
    with pytest.raises(ValueError, match="uma página"):
        inference.predict(
            workspace, "two", workspace.root, None, engine="structure", provider="docling"
        )
