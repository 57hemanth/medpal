"""No-Shows transform checks (counts before and after, with the drop reasons tallied)."""

from pathlib import Path

import pandas as pd
import pytest

from data.transforms.no_shows import RAW, clinic_for, load_raw, transform


def row(**over) -> dict:
    base = {
        "PatientId": 29872499824296.0,
        "AppointmentID": 1,
        "Gender": "F",
        "ScheduledDay": "2016-04-29T18:38:08Z",
        "AppointmentDay": "2016-04-29T00:00:00Z",
        "Age": 62,
        "Neighbourhood": "JARDIM DA PENHA",
        "Scholarship": 0,
        "Hipertension": 1,
        "Diabetes": 0,
        "Alcoholism": 0,
        "Handcap": 0,
        "SMS_received": 0,
        "No-show": "No",
    }
    return {**base, **over}


def test_same_day_booking_is_kept_despite_later_timestamp():
    # Scheduled 18:38 on the visit day; AppointmentDay has no time. A naive compare would drop it.
    out, report = transform(pd.DataFrame([row()]))
    assert report.rows_out == 1 and report.dropped == {}


def test_drop_reasons_are_tallied_and_rows_accounted_for():
    raw = pd.DataFrame(
        [
            row(AppointmentID=1),
            row(AppointmentID=2, Age=-1),
            row(AppointmentID=3, Age=115),
            row(AppointmentID=4, ScheduledDay="2016-05-02T09:00:00Z", AppointmentDay="2016-04-29T00:00:00Z"),
            row(AppointmentID=5, **{"No-show": "Maybe"}),
        ]
    )
    out, report = transform(raw)
    assert report.rows_in == 5 and report.rows_out == 1
    assert report.dropped == {
        "age_implausible_gt_110": 1,
        "age_negative": 1,
        "scheduled_after_appointment": 1,
        "target_unknown": 1,
    }


def test_target_is_flipped_to_attended():
    out, _ = transform(pd.DataFrame([row(AppointmentID=1), row(AppointmentID=2, **{"No-show": "Yes"})]))
    assert out.set_index("source_appointment_id")["attended"].to_dict() == {1: True, 2: False}


def test_source_patient_id_is_pseudonymised():
    out, _ = transform(pd.DataFrame([row()]))
    assert "source_patient_id" not in out.columns
    assert len(out.loc[0, "patient_key"]) == 16


def test_clinic_mapping_is_stable_and_in_range():
    assert clinic_for("JARDIM DA PENHA") == clinic_for(" jardim da penha ")
    assert all(1 <= clinic_for(f"N{i}") <= 22 for i in range(200))


@pytest.mark.skipif(not Path(RAW).exists(), reason="raw dataset not downloaded (see data/inventory.md)")
def test_full_dataset_counts_match_inventory():
    out, report = transform(load_raw())
    assert report.rows_in == 110_527
    assert report.dropped == {
        "age_implausible_gt_110": 5,
        "age_negative": 1,
        "scheduled_after_appointment": 5,
    }
    assert report.rows_out == 110_516
    assert out["source_appointment_id"].is_unique
