"""Generated layer: network, specialties, doctor directory and slot calendar. Plain, seeded code.

Why code and not an LLM for the directory (see ADR-0004): every field is
structured (name, specialty, clinic, languages, years). Seeded code gives the same realism with no
hallucination risk, no API cost and byte-for-byte reproducibility. The rule used for slots
("a calendar is arithmetic, so no LLM touches it") applies to a directory just as well.

Rules kept from p.20: seed from real-world distributions, validate every row with pydantic and
REJECT (never repair) a row that fails, audit for duplicates and bias, version seed + output
together, and tag every generated row synthetic=true.

    uv run --group data python -m data.synthetic.generate
"""

import csv
import json
import random
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError, field_validator

from .reference import (
    CITY_NAME_MIX,
    CLINICS,
    FORMULARY,
    GROUP_LANGUAGES,
    HOSPITALS,
    LANGUAGE_RULES,
    MIN_DOCTORS_PER_SPECIALTY,
    NAME_GROUPS,
    OUT_OF_STOCK_SHARE,
    SPECIALTIES,
    ClinicRef,
)

GENERATOR_VERSION = "1"
DEFAULT_SEED = 20261102
N_DOCTORS = 500
WORKING_DAYS = 60
SLOTS_PER_DAY = 16
SLOT_MINUTES = 15
SECOND_CLINIC_SHARE = 0.20
SECOND_CLINIC_WEEKDAYS = {1, 3, 5}  # Tue, Thu, Sat (Mon=0)
IST = ZoneInfo("Asia/Kolkata")
OUT_DIR = Path("data/synthetic/output")
LANGS = {"en", "hi", "mr", "te", "ur"}

# Stable ids: the same seed and index always give the same uuid.
_NS = uuid.UUID("5a4f0c3e-6b1d-4c1a-9e57-1f0a2b3c4d5e")


def stable_id(kind: str, key: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{key}"))


class DoctorRow(BaseModel):
    """Contract for a generated doctor. A row that fails validation is rejected, never repaired."""

    doctor_id: str
    name: str = Field(min_length=5, max_length=80)
    gender: Literal["f", "m"]
    specialty: str
    primary_clinic: str
    second_clinic: str | None
    session: Literal["morning", "evening"]
    languages: list[str] = Field(min_length=1)
    years: int = Field(ge=1, le=40)
    synthetic: Literal[True] = True

    @field_validator("specialty")
    @classmethod
    def _known_specialty(cls, v: str) -> str:
        if v not in SPECIALTIES:
            raise ValueError(f"unknown specialty {v!r}")
        return v

    @field_validator("languages")
    @classmethod
    def _known_languages(cls, v: list[str]) -> list[str]:
        if "en" not in v or not set(v) <= LANGS or len(set(v)) != len(v):
            raise ValueError(f"bad languages {v!r}")
        return v


@dataclass
class Audit:
    seed: int
    version: str = GENERATOR_VERSION
    doctors: int = 0
    rejected: int = 0
    slots: int = 0
    start_date: str = ""
    per_specialty: dict[str, int] = field(default_factory=dict)
    per_clinic: dict[str, int] = field(default_factory=dict)
    gender_share_f: float = 0.0
    gender_share_f_by_specialty: dict[str, float] = field(default_factory=dict)
    max_name_repeats: int = 0
    language_share: dict[str, float] = field(default_factory=dict)
    clinics_without_doctors: list[str] = field(default_factory=list)


# ---- doctors ------------------------------------------------------------------------------------


def specialty_quota(n_doctors: int = N_DOCTORS) -> dict[str, int]:
    """Floor of MIN per specialty; the rest by demand weight (largest remainder, deterministic)."""
    base = {s: MIN_DOCTORS_PER_SPECIALTY for s in SPECIALTIES}
    extra = n_doctors - sum(base.values())
    if extra < 0:
        raise ValueError("not enough doctors to give every specialty its minimum")
    total_w = sum(SPECIALTIES.values())
    raw = {s: extra * w / total_w for s, w in SPECIALTIES.items()}
    alloc = {s: int(v) for s, v in raw.items()}
    for s in sorted(raw, key=lambda s: (raw[s] - alloc[s], s), reverse=True)[: extra - sum(alloc.values())]:
        alloc[s] += 1
    return {s: base[s] + alloc[s] for s in SPECIALTIES}


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _languages(rng: random.Random, city: str, group: str) -> list[str]:
    langs = ["en"] + [lang for lang, p in LANGUAGE_RULES[city].items() if rng.random() < p]
    langs += GROUP_LANGUAGES.get(group, [])
    return list(dict.fromkeys(langs))  # dedupe, keep order


def generate_doctors(seed: int = DEFAULT_SEED, n_doctors: int = N_DOCTORS) -> tuple[list[DoctorRow], int]:
    rng = random.Random(seed)
    quotas = specialty_quota(n_doctors)
    specialties = [s for s, q in quotas.items() for _ in range(q)]
    rng.shuffle(specialties)
    used_names: set[str] = set()
    doctors: list[DoctorRow] = []
    rejected = 0

    for i, specialty in enumerate(specialties):
        # Round-robin over clinics so every clinic gets doctors; shuffle-free for determinism.
        clinic = CLINICS[i % len(CLINICS)]
        group = _pick(rng, CITY_NAME_MIX[clinic.city])
        gender = rng.choice(["f", "m"])
        pool = NAME_GROUPS[group]
        name = f"{rng.choice(pool[gender])} {rng.choice(pool['surname'])}"
        for _ in range(20):  # avoid exact duplicate names; give up after 20 draws
            if name not in used_names:
                break
            name = f"{rng.choice(pool[gender])} {rng.choice(pool['surname'])}"
        same_city = [c for c in CLINICS if c.city == clinic.city and c.key != clinic.key]
        second = rng.choice(same_city).key if rng.random() < SECOND_CLINIC_SHARE else None
        try:
            row = DoctorRow(
                doctor_id=stable_id("doctor", f"{seed}:{i}"),
                name=name,
                gender=gender,  # type: ignore[arg-type]
                specialty=specialty,
                primary_clinic=clinic.key,
                second_clinic=second,
                session=rng.choice(["morning", "evening"]),  # type: ignore[arg-type]
                languages=_languages(rng, clinic.city, group),
                years=max(1, min(40, round(rng.triangular(1, 35, 10)))),
            )
        except ValidationError:
            rejected += 1
            continue
        if row.name in used_names:
            rejected += 1  # duplicate full name after 20 draws: reject, never rename
            continue
        used_names.add(row.name)
        doctors.append(row)
    return doctors, rejected


# ---- slots --------------------------------------------------------------------------------------


def working_days(start: date, n: int) -> list[date]:
    """Mon-Sat; Sundays closed. Public holidays are not modelled (noted in the inventory)."""
    days, d = [], start
    while len(days) < n:
        if d.weekday() != 6:
            days.append(d)
        d += timedelta(days=1)
    return days


def next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def session_start(clinic: ClinicRef, session: str) -> time:
    length = timedelta(minutes=SLOTS_PER_DAY * SLOT_MINUTES)
    opens = datetime.combine(date.min, clinic.opens_at)
    closes = datetime.combine(date.min, clinic.closes_at)
    start = opens if session == "morning" else closes - length
    if start < opens or start + length > closes:
        raise ValueError(f"session does not fit clinic hours: {clinic.key}")
    return start.time()


def generate_slots(doctors: list[DoctorRow], start: date, days: int = WORKING_DAYS) -> Iterator[tuple]:
    """(doctor_id, clinic_key, starts_at) for every doctor, working day and slot."""
    by_key = {c.key: c for c in CLINICS}
    for doc in doctors:
        for day in working_days(start, days):
            key = (
                doc.second_clinic
                if doc.second_clinic and day.weekday() in SECOND_CLINIC_WEEKDAYS
                else (doc.primary_clinic)
            )
            clinic = by_key[key]
            first = datetime.combine(day, session_start(clinic, doc.session), IST)
            for k in range(SLOTS_PER_DAY):
                yield doc.doctor_id, key, first + timedelta(minutes=k * SLOT_MINUTES)


# ---- audit + output -----------------------------------------------------------------------------


def audit(doctors: list[DoctorRow], rejected: int, seed: int) -> Audit:
    a = Audit(seed=seed, doctors=len(doctors), rejected=rejected)
    a.per_specialty = dict(sorted(Counter(d.specialty for d in doctors).items()))
    clinic_counts = Counter(d.primary_clinic for d in doctors) + Counter(
        d.second_clinic for d in doctors if d.second_clinic
    )
    a.per_clinic = {c.key: clinic_counts.get(c.key, 0) for c in CLINICS}
    a.clinics_without_doctors = [k for k, n in a.per_clinic.items() if n == 0]
    a.gender_share_f = round(sum(d.gender == "f" for d in doctors) / max(len(doctors), 1), 3)
    by_spec: dict[str, list[str]] = {}
    for d in doctors:
        by_spec.setdefault(d.specialty, []).append(d.gender)
    a.gender_share_f_by_specialty = {s: round(g.count("f") / len(g), 2) for s, g in sorted(by_spec.items())}
    a.max_name_repeats = max(Counter(d.name for d in doctors).values(), default=0)
    langs = Counter(lang for d in doctors for lang in d.languages)
    a.language_share = {k: round(v / max(len(doctors), 1), 3) for k, v in sorted(langs.items())}
    return a


def write_outputs(seed: int = DEFAULT_SEED, start: date | None = None, out_dir: Path = OUT_DIR) -> Audit:
    start = start or next_monday()
    doctors, rejected = generate_doctors(seed)
    report = audit(doctors, rejected, seed)
    report.start_date = start.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "hospitals.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hospital_id", "name", "city"])
        w.writerows([stable_id("hospital", h.key), h.name, h.city] for h in HOSPITALS)
    with (out_dir / "clinics.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clinic_id", "hospital_id", "name", "city", "district", "opens_at", "closes_at"])
        w.writerows(
            [
                stable_id("clinic", c.key),
                stable_id("hospital", c.hospital),
                c.name,
                c.city,
                c.city,
                c.opens_at.isoformat(),
                c.closes_at.isoformat(),
            ]
            for c in CLINICS
        )
    with (out_dir / "specialties.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["specialty_id", "name"])
        w.writerows([stable_id("specialty", s), s] for s in SPECIALTIES)
    with (out_dir / "doctors.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doctor_id", "name", "specialty_id", "languages", "years", "synthetic"])
        w.writerows(
            [
                d.doctor_id,
                d.name,
                stable_id("specialty", d.specialty),
                "{" + ",".join(d.languages) + "}",
                d.years,
                "true",
            ]
            for d in doctors
        )
    with (out_dir / "doctor_clinic.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doctor_id", "clinic_id"])
        for d in doctors:
            w.writerow([d.doctor_id, stable_id("clinic", d.primary_clinic)])
            if d.second_clinic:
                w.writerow([d.doctor_id, stable_id("clinic", d.second_clinic)])
    with (out_dir / "slots.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doctor_id", "clinic_id", "starts_at", "capacity", "synthetic"])
        for doctor_id, clinic_key, starts_at in generate_slots(doctors, start):
            w.writerow([doctor_id, stable_id("clinic", clinic_key), starts_at.isoformat(), 1, "true"])
            report.slots += 1

    write_formulary(seed, out_dir)
    (out_dir / "generated_manifest.json").write_text(json.dumps(asdict(report), indent=2))
    return report


def write_formulary(seed: int, out_dir: Path) -> None:
    """Medicines and per-clinic stock. `as_of` is set at load time by the seed (a nightly feed)."""
    rng = random.Random(seed + 1)
    with (out_dir / "medicines.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["medicine_id", "name", "composition", "pack_size", "price_inr", "source"])
        for name, composition, pack, price in FORMULARY:
            w.writerow([stable_id("medicine", name), name, composition, pack, price, "generated-formulary"])
    with (out_dir / "medicine_stock.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clinic_id", "medicine_id", "qty", "as_of"])
        for clinic in CLINICS:
            for name, *_ in FORMULARY:
                qty = 0 if rng.random() < OUT_OF_STOCK_SHARE else rng.randint(20, 400)
                placeholder_as_of = "1970-01-01T00:00:00Z"  # replaced at load time by the seed
                w.writerow(
                    [stable_id("clinic", clinic.key), stable_id("medicine", name), qty, placeholder_as_of]
                )


def main() -> None:
    report = write_outputs()
    skip = ("per_specialty", "per_clinic", "gender_share_f_by_specialty")
    summary = {k: v for k, v in asdict(report).items() if k not in skip}
    print(json.dumps(summary, indent=2))
    print(f"specialties: min {min(report.per_specialty.values())}, max {max(report.per_specialty.values())}")
    print(f"clinics: min {min(report.per_clinic.values())}, max {max(report.per_clinic.values())} doctors")
    g = report.gender_share_f_by_specialty.values()
    print(f"female share by specialty: min {min(g)}, max {max(g)}")


if __name__ == "__main__":
    main()
