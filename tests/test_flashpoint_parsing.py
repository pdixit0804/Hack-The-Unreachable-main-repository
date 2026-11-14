from stress_tester.panel.flashpoint import _fill, extract_scores, result_payload


def test_list_of_scores():
    assert extract_scores({"responses": [7, 8, 6, 9]}) == ([7, 8, 6, 9], None)


def test_per_persona_dicts_and_strings():
    payload = {"personas": [{"id": 3, "rating": 7}, {"id": 4, "rating": "8 - quite appealing"}]}
    assert extract_scores(payload)[0] == [7, 8]


def test_mean_only():
    assert extract_scores({"mean": 6.4, "notes": "ok"}) == (None, 6.4)


def test_ignores_unrelated_numbers_and_out_of_range_values():
    resp, mean = extract_scores({"n_personas": 40, "request_id": 7, "cost": 3, "scores": [11, 0, 12]})
    assert resp is None and mean is None  # nothing valid -> caller raises instead of guessing


def test_nothing_found():
    assert extract_scores({"error": "none"}) == (None, None)


def test_result_payload_prefers_structured_then_json_text_then_embedded_json():
    assert result_payload({"structuredContent": {"a": 1}, "content": []}) == {"a": 1}
    assert result_payload({"content": [{"type": "text", "text": '{"b": 2}'}]}) == {"b": 2}
    assert result_payload({"content": [{"type": "text", "text": 'Here you go: {"c": 3} done'}]}) == {"c": 3}


def test_fill_keeps_native_types():
    out = _fill({"n_personas": "{n}", "q": "{question}", "mix": "seg={segment}"}, {"n": 40, "question": "Q?", "segment": "S"})
    assert out == {"n_personas": 40, "q": "Q?", "mix": "seg=S"}


def test_job_status_ignores_task_envelope():
    from stress_tester.panel.flashpoint import job_status

    running = {"task_id": "t", "status": "completed", "result": {"status": "running", "stage": "answering", "progress": 0.4}}
    assert job_status(running) == "running"
    done = {"task_id": "t", "status": "completed", "result": {"status": "completed", "result": {"answers": []}}}
    assert job_status(done) == "completed"
    failed = {"status": "completed", "result": {"status": "failed", "error": "x"}}
    assert job_status(failed) == "failed"
