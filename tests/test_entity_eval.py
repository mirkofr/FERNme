from fernme.eval.entities import run


def test_entity_micro_eval_shows_aggregation_improves_fragment_rank():
    result = run(seeds=3)

    assert len(result["rows"]) == 3
    assert result["on_mean_rank"] < result["off_mean_rank"]
    assert all(row["on_rank"] == 1 for row in result["rows"])
