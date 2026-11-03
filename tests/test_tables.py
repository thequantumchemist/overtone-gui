import io

import pandas as pd
import pytest

from overtone_gui.run_data import RunData
from overtone_gui.tables import csv_bytes, latex_bytes, transitions_frame


@pytest.fixture(scope="module")
def frame(water_run):
    run = RunData.load(water_run)
    return transitions_frame({"GVPT2": run.result_for("gvpt2"),
                              "Standard VPT2": run.result_for("standard")})


def test_one_column_per_method(frame):
    assert {"GVPT2", "Standard VPT2"} <= set(frame.columns)


def test_rows_follow_primary_result(frame, water_run):
    run = RunData.load(water_run)
    assert list(frame["Band"]) == [t.label for t in run.result.transitions]


def test_experimental_column_and_deviation(water_run):
    run = RunData.load(water_run)
    df = transitions_frame({"GVPT2": run.result}, reference={"v7": 1595.0})
    row = df[df["Band"] == "v7"].iloc[0]
    assert row["Δ"] == pytest.approx(round(row["GVPT2"] - 1595.0, 1))


def test_csv_round_trip(frame):
    back = pd.read_csv(io.BytesIO(csv_bytes(frame).read()))
    assert list(back["Band"]) == list(frame["Band"])


def test_latex_uses_nu_labels_and_booktabs(frame):
    tex = latex_bytes(frame).read().decode()
    assert r"\nu_{7}" in tex
    assert r"\toprule" in tex
