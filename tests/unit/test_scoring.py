import pytest

from acessilia_benchmark.core.scoring import compute_overall, overall_details, unit_score
from acessilia_benchmark.io import write


def test_omni_uses_official_page_average_not_block_or_whole_document():
    metrics = {
        "text_block": {"all": {"Edit_dist": {"ALL_page_avg": 0.1, "edit_whole": 0.9}}},
        "table": {"page": {"TEDS": {"ALL": 0.6}}, "all": {"TEDS": {"all": 0.9}}},
        "display_formula": {"page": {"CDM": {"ALL": 0.3}}, "all": {"CDM": {"all": 0.8}}},
    }
    assert compute_overall(metrics) == pytest.approx(60)
    del metrics["table"]["page"]
    assert compute_overall(metrics) is None  # Never silently change weighting.


@pytest.mark.parametrize("value", [True, False, -0.1, 1.01, 90, "0.9"])
def test_invalid_units_and_booleans_are_rejected(value):
    with pytest.raises(ValueError):
        unit_score(value, "metric")


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "NaN"])
def test_non_finite_components_are_unavailable(value):
    assert unit_score(value, "metric") is None


def dr_artifacts(tmp_path):
    folder = tmp_path / "result"
    write(folder / "sample_text_block_result.json", [{"img_id": "a.jpg"}, {"img_id": "b.jpg"}])
    write(folder / "sample_text_block_per_page_edit.json", {"a.jpg": 0.1, "b.jpg": 0.5})
    write(folder / "sample_reading_order_result.json", [{"img_id": "a.jpg"}])
    write(folder / "sample_reading_order_per_page_edit.json", {"a.jpg": 0.2})
    write(folder / "sample_table_result.json", [{"img_id": "b.jpg", "metric": {"TEDS": 0.8}}])
    write(
        folder / "sample_display_formula_result.json",
        [{"img_id": "b.jpg", "metric": {"CDM": value}} for value in (0.2, 0.6)],
    )
    return [{"id": key, "prediction": key + ".md"} for key in ("a", "b", "blank")]


def test_dr_averages_available_components_per_window_then_windows(tmp_path):
    cases = dr_artifacts(tmp_path)
    details = overall_details({}, "drdocbench-dev", "full", tmp_path, cases)
    assert details["case_scores"]["a"]["overall"] == pytest.approx(85)
    assert details["case_scores"]["b"]["overall"] == pytest.approx((50 + 80 + 40) / 3)
    assert details["value"] == pytest.approx((85 + (50 + 80 + 40) / 3) / 2)
    assert details["excluded_cases"] == ["blank"]
    assert not details["leaderboard_comparable"]


def test_dr_missing_formula_metric_is_a_failure_not_an_absent_component(tmp_path):
    cases = dr_artifacts(tmp_path)
    write(tmp_path / "result/sample_display_formula_result.json", [{"img_id": "b.jpg"}])
    with pytest.raises(ValueError, match="ausente/não finita"):
        overall_details({}, "drdocbench-dev", "full", tmp_path, cases)


def test_basic_does_not_claim_overall(tmp_path):
    details = overall_details({}, "drdocbench-dev", "basic", tmp_path, [])
    assert details["value"] is None
    assert "basic" in details["reason"]


def test_dr_missing_window_distance_cannot_silently_drop_a_component(tmp_path):
    cases = dr_artifacts(tmp_path)
    write(tmp_path / "result/sample_text_block_per_page_edit.json", {"a.jpg": 0.1})
    with pytest.raises(ValueError, match="Cobertura de distâncias"):
        overall_details({}, "drdocbench-dev", "full", tmp_path, cases)
