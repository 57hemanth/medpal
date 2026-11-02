"""No-Shows (OpenML 43439 / Kaggle joniarroba/noshowappointments, CC BY-NC-SA 4.0): clean and map.

Known mess and what we do about it:
  * negative ages, and ages > 110            → drop, tallied by reason
  * schedule date after the visit date       → drop, compared on DATES: AppointmentDay carries no time
    (always 00:00), so a naive timestamp comparison wrongly flags 38,568 same-day bookings (35%)
  * target "No-show" reads backwards         → `attended` = (No-show == "No")
  * source PatientId                          → pseudonymised `patient_key` (sha256, truncated)
  * Brazilian neighbourhoods                  → stable mapping onto the 22 fictional MedPal clinics

Proof it worked: counts before/after with every drop reason tallied (tests in data/transforms/tests).

    uv run --group data python -m data.transforms.no_shows
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/no_shows/Medical-Appointment-No-Shows.arff")
OUT_DIR = Path("data/synthetic/output")
N_CLINICS = 22
MAX_PLAUSIBLE_AGE = 110

COLUMNS = {
    "PatientId": "source_patient_id",
    "AppointmentID": "source_appointment_id",
    "Gender": "gender",
    "ScheduledDay": "scheduled_at",
    "AppointmentDay": "appointment_date",
    "Age": "age",
    "Neighbourhood": "neighbourhood",
    "Scholarship": "scholarship",
    "Hipertension": "hypertension",
    "Diabetes": "diabetes",
    "Alcoholism": "alcoholism",
    "Handcap": "handicap_level",
    "SMS_received": "sms_received",
    "No-show": "no_show_raw",
}


@dataclass
class Report:
    source: str = "OpenML 43439 Medical-Appointment-No-Shows (CC BY-NC-SA 4.0)"
    rows_in: int = 0
    rows_out: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    attended_rate: float = 0.0
    clinics_used: int = 0

    def check(self) -> None:
        """Every input row is accounted for: kept or dropped with a reason."""
        if self.rows_in != self.rows_out + sum(self.dropped.values()):
            raise ValueError(f"row accounting broken: {self}")


def clinic_for(neighbourhood: str) -> int:
    """Stable neighbourhood → clinic number (1..22). Same input, same clinic, across runs."""
    digest = hashlib.sha256(neighbourhood.strip().upper().encode()).digest()
    return int.from_bytes(digest[:4], "big") % N_CLINICS + 1


def pseudonymise(source_id: object) -> str:
    return hashlib.sha256(f"noshow:{source_id}".encode()).hexdigest()[:16]


def transform(raw: pd.DataFrame) -> tuple[pd.DataFrame, Report]:
    report = Report(rows_in=len(raw))
    df = raw.rename(columns=COLUMNS).copy()

    df["scheduled_at"] = pd.to_datetime(df["scheduled_at"], utc=True)
    df["appointment_date"] = pd.to_datetime(df["appointment_date"], utc=True).dt.date
    scheduled_date = df["scheduled_at"].dt.date

    reasons = pd.Series("", index=df.index)
    reasons[df["age"] < 0] = "age_negative"
    reasons[(reasons == "") & (df["age"] > MAX_PLAUSIBLE_AGE)] = "age_implausible_gt_110"
    reasons[(reasons == "") & (scheduled_date > df["appointment_date"])] = "scheduled_after_appointment"
    reasons[(reasons == "") & ~df["no_show_raw"].isin(["Yes", "No"])] = "target_unknown"

    report.dropped = {k: int(v) for k, v in reasons[reasons != ""].value_counts().sort_index().items()}
    df = df[reasons == ""].copy()

    df["attended"] = df["no_show_raw"].eq("No")  # the source target reads backwards
    df["patient_key"] = df["source_patient_id"].map(pseudonymise)
    df["clinic_no"] = df["neighbourhood"].map(clinic_for)
    df["lead_days"] = (
        pd.to_datetime(df["appointment_date"]) - pd.to_datetime(scheduled_date[df.index])
    ).dt.days
    for col in ("scholarship", "hypertension", "diabetes", "alcoholism", "sms_received"):
        df[col] = df[col].astype(bool)

    out = df[
        [
            "source_appointment_id",
            "patient_key",
            "gender",
            "age",
            "clinic_no",
            "scheduled_at",
            "appointment_date",
            "lead_days",
            "scholarship",
            "hypertension",
            "diabetes",
            "alcoholism",
            "handicap_level",
            "sms_received",
            "attended",
        ]
    ].reset_index(drop=True)

    report.rows_out = len(out)
    report.attended_rate = round(float(out["attended"].mean()), 4) if len(out) else 0.0
    report.clinics_used = int(out["clinic_no"].nunique())
    report.check()
    return out, report


def load_raw(path: Path = RAW) -> pd.DataFrame:
    import arff  # liac-arff, data dependency group only

    with path.open(encoding="utf-8") as f:
        payload = arff.load(f)
    return pd.DataFrame(payload["data"], columns=[a[0] for a in payload["attributes"]])


def main() -> None:
    out, report = transform(load_raw())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_DIR / "no_shows_clean.csv", index=False)
    (OUT_DIR / "no_shows_report.json").write_text(json.dumps(asdict(report), indent=2))
    print(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    main()
