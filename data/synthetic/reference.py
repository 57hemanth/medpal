"""Reference data for the generated layer: the (fictional) network, specialties and name pools.

Everything here is invented for the engagement: hospital and clinic names use real Pune and
Hyderabad localities but describe no real facility, and the people built from these pools are
synthetic. Assumptions that need the client's confirmation are listed in docs/assumptions.md
(Q9 doctor count and split; A12 realism).
"""

from dataclasses import dataclass
from datetime import time

# ---- network: 6 hospitals, 22 clinics ------------------------------------------------


@dataclass(frozen=True)
class HospitalRef:
    key: str
    name: str
    city: str


@dataclass(frozen=True)
class ClinicRef:
    key: str
    name: str
    city: str
    hospital: str  # HospitalRef.key it reports to
    opens_at: time
    closes_at: time


HOSPITALS = [
    HospitalRef("pun-shivajinagar", "MedPal Hospital Shivajinagar", "Pune"),
    HospitalRef("pun-hadapsar", "MedPal Hospital Hadapsar", "Pune"),
    HospitalRef("pun-wakad", "MedPal Hospital Wakad", "Pune"),
    HospitalRef("hyd-banjara", "MedPal Hospital Banjara Hills", "Hyderabad"),
    HospitalRef("hyd-secunderabad", "MedPal Hospital Secunderabad", "Hyderabad"),
    HospitalRef("hyd-gachibowli", "MedPal Hospital Gachibowli", "Hyderabad"),
]

_HOSPITAL_OPD = (time(8, 0), time(20, 0))
_CLINIC = (time(9, 0), time(18, 0))
_LATE_CLINIC = (time(10, 0), time(19, 0))

CLINICS = [
    # Pune (11): three hospital OPDs + eight neighbourhood clinics
    ClinicRef(
        "pun-shivajinagar-opd", "Shivajinagar Hospital OPD", "Pune", "pun-shivajinagar", *_HOSPITAL_OPD
    ),
    ClinicRef("pun-hadapsar-opd", "Hadapsar Hospital OPD", "Pune", "pun-hadapsar", *_HOSPITAL_OPD),
    ClinicRef("pun-wakad-opd", "Wakad Hospital OPD", "Pune", "pun-wakad", *_HOSPITAL_OPD),
    ClinicRef("pun-baner", "Baner Clinic", "Pune", "pun-wakad", *_CLINIC),
    ClinicRef("pun-aundh", "Aundh Clinic", "Pune", "pun-shivajinagar", *_CLINIC),
    ClinicRef("pun-kothrud", "Kothrud Clinic", "Pune", "pun-shivajinagar", *_LATE_CLINIC),
    ClinicRef("pun-viman-nagar", "Viman Nagar Clinic", "Pune", "pun-hadapsar", *_CLINIC),
    ClinicRef("pun-kharadi", "Kharadi Clinic", "Pune", "pun-hadapsar", *_LATE_CLINIC),
    ClinicRef("pun-hinjewadi", "Hinjewadi Clinic", "Pune", "pun-wakad", *_LATE_CLINIC),
    ClinicRef("pun-pimpri", "Pimpri Clinic", "Pune", "pun-wakad", *_CLINIC),
    ClinicRef("pun-camp", "Camp Clinic", "Pune", "pun-shivajinagar", *_CLINIC),
    # Hyderabad (11)
    ClinicRef("hyd-banjara-opd", "Banjara Hills Hospital OPD", "Hyderabad", "hyd-banjara", *_HOSPITAL_OPD),
    ClinicRef(
        "hyd-secunderabad-opd", "Secunderabad Hospital OPD", "Hyderabad", "hyd-secunderabad", *_HOSPITAL_OPD
    ),
    ClinicRef("hyd-gachibowli-opd", "Gachibowli Hospital OPD", "Hyderabad", "hyd-gachibowli", *_HOSPITAL_OPD),
    ClinicRef("hyd-madhapur", "Madhapur Clinic", "Hyderabad", "hyd-gachibowli", *_LATE_CLINIC),
    ClinicRef("hyd-kondapur", "Kondapur Clinic", "Hyderabad", "hyd-gachibowli", *_CLINIC),
    ClinicRef("hyd-kukatpally", "Kukatpally Clinic", "Hyderabad", "hyd-gachibowli", *_CLINIC),
    ClinicRef("hyd-miyapur", "Miyapur Clinic", "Hyderabad", "hyd-gachibowli", *_LATE_CLINIC),
    ClinicRef("hyd-ameerpet", "Ameerpet Clinic", "Hyderabad", "hyd-banjara", *_CLINIC),
    ClinicRef("hyd-begumpet", "Begumpet Clinic", "Hyderabad", "hyd-secunderabad", *_CLINIC),
    ClinicRef("hyd-dilsukhnagar", "Dilsukhnagar Clinic", "Hyderabad", "hyd-secunderabad", *_LATE_CLINIC),
    ClinicRef("hyd-lb-nagar", "LB Nagar Clinic", "Hyderabad", "hyd-secunderabad", *_CLINIC),
]

# ---- 38 bookable outpatient specialties, with relative demand ------------------------------------
# Our own list of 38 outpatient-bookable
# specialties typical of an Indian multi-specialty network. The client must confirm it (assumption A12).
# Weight = share of the doctors above the 10-per-specialty floor.

SPECIALTIES: dict[str, int] = {
    "General Medicine": 30,
    "Paediatrics": 14,
    "Obstetrics and Gynaecology": 14,
    "Orthopaedics": 12,
    "Cardiology": 10,
    "Dermatology": 8,
    "ENT": 7,
    "Ophthalmology": 7,
    "General Surgery": 8,
    "Endocrinology": 6,
    "Gastroenterology": 5,
    "Pulmonology": 5,
    "Neurology": 5,
    "Psychiatry": 4,
    "Nephrology": 3,
    "Urology": 3,
    "Dentistry": 5,
    "Physiotherapy": 5,
    "Rheumatology": 2,
    "Medical Oncology": 2,
    "Surgical Oncology": 1,
    "Haematology": 1,
    "Infectious Diseases": 1,
    "Neurosurgery": 1,
    "Cardiothoracic Surgery": 1,
    "Plastic Surgery": 1,
    "Vascular Surgery": 1,
    "Paediatric Surgery": 1,
    "Neonatology": 1,
    "Geriatric Medicine": 1,
    "Allergy and Immunology": 1,
    "Hepatology": 1,
    "Pain Medicine": 1,
    "Sleep Medicine": 0,
    "Sports Medicine": 1,
    "Nutrition and Dietetics": 2,
    "Clinical Psychology": 1,
    "Bariatric Surgery": 0,
}

MIN_DOCTORS_PER_SPECIALTY = 10  # "enough data" check: every specialty has at least ten doctors

# ---- name pools ----------------------------------------------------------------------------------
# Grouped so given names and surnames stay culturally coherent within one person.

NAME_GROUPS: dict[str, dict[str, list[str]]] = {
    "marathi": {
        "f": [
            "Aarti",
            "Aparna",
            "Gauri",
            "Madhuri",
            "Manasi",
            "Prachi",
            "Rupali",
            "Vaishali",
            "Smita",
            "Sneha",
            "Shilpa",
            "Swati",
            "Archana",
            "Pallavi",
            "Rekha",
            "Sunita",
            "Kavita",
            "Meera",
            "Neha",
            "Tanvi",
        ],
        "m": [
            "Shrikant",
            "Sachin",
            "Nitin",
            "Mahesh",
            "Ganesh",
            "Yogesh",
            "Sandeep",
            "Prasad",
            "Chetan",
            "Ajay",
            "Amol",
            "Girish",
            "Jayant",
            "Madhav",
            "Pranav",
            "Rohan",
            "Sameer",
            "Satish",
            "Vinod",
            "Ashok",
        ],
        "surname": [
            "Kulkarni",
            "Deshpande",
            "Joshi",
            "Patil",
            "Deshmukh",
            "Gokhale",
            "Pawar",
            "Jadhav",
            "Shinde",
            "Bhosale",
            "Kale",
            "Apte",
            "Bapat",
            "Gadgil",
            "Karve",
            "Paranjape",
            "Sathe",
            "Phadke",
            "Ranade",
            "Chavan",
            "Kadam",
            "Salunkhe",
            "Mane",
            "Khare",
        ],
    },
    "telugu": {
        "f": [
            "Lakshmi",
            "Haritha",
            "Keerthi",
            "Lavanya",
            "Mounika",
            "Sravani",
            "Swapna",
            "Anusha",
            "Sowmya",
            "Padma",
            "Yamini",
            "Bhavana",
            "Divya",
            "Deepika",
            "Radhika",
            "Hema",
            "Sudha",
            "Uma",
            "Kalyani",
            "Aruna",
        ],
        "m": [
            "Venkatesh",
            "Srinivas",
            "Srikanth",
            "Vamsi",
            "Pavan",
            "Karthik",
            "Naveen",
            "Raghav",
            "Sai",
            "Krishna",
            "Ramesh",
            "Suresh",
            "Mohan",
            "Prakash",
            "Ravi",
            "Kiran",
            "Harish",
            "Anil",
            "Vijay",
            "Chandra",
        ],
        "surname": [
            "Reddy",
            "Rao",
            "Naidu",
            "Chowdary",
            "Varma",
            "Murthy",
            "Goud",
            "Raju",
            "Sastry",
            "Prasad",
            "Kumar",
            "Yadav",
            "Chari",
            "Babu",
            "Setty",
            "Rajulu",
        ],
    },
    "deccani": {
        "f": ["Zainab", "Farah", "Ayesha", "Sadia", "Shabnam", "Nazia", "Fatima", "Rukhsar", "Sana", "Heena"],
        "m": ["Imran", "Irfan", "Faisal", "Abdul", "Arif", "Salman", "Zaheer", "Mujeeb", "Rizwan", "Asif"],
        "surname": [
            "Siddiqui",
            "Hussain",
            "Khan",
            "Ahmed",
            "Ali",
            "Qureshi",
            "Pasha",
            "Rizvi",
            "Ansari",
            "Shaikh",
            "Baig",
            "Mirza",
        ],
    },
    "pan_indian": {
        "f": [
            "Ananya",
            "Aditi",
            "Anjali",
            "Priya",
            "Pooja",
            "Shreya",
            "Shweta",
            "Nisha",
            "Geeta",
            "Jyoti",
            "Shalini",
            "Sangeeta",
            "Deepa",
            "Vidya",
            "Seema",
        ],
        "m": [
            "Aditya",
            "Amit",
            "Anand",
            "Arjun",
            "Deepak",
            "Gaurav",
            "Nikhil",
            "Rahul",
            "Rajesh",
            "Rakesh",
            "Sanjay",
            "Siddharth",
            "Tarun",
            "Varun",
            "Vikram",
        ],
        "surname": [
            "Sharma",
            "Gupta",
            "Mehta",
            "Shah",
            "Patel",
            "Singh",
            "Agarwal",
            "Banerjee",
            "Mukherjee",
            "Kapoor",
            "Malhotra",
            "Fernandes",
            "D'Souza",
            "Srivastava",
            "Saxena",
        ],
    },
    "south": {
        "f": ["Meenakshi", "Revathi", "Kavya", "Nandini", "Shobha", "Vasudha"],
        "m": ["Ramesh", "Karthik", "Subramaniam", "Gopal", "Hari", "Shankar"],
        "surname": ["Iyer", "Nair", "Menon", "Pillai", "Bhat", "Shetty", "Kamath", "Iyengar"],
    },
}

# Probability of drawing a name group, per city.
CITY_NAME_MIX: dict[str, dict[str, float]] = {
    "Pune": {"marathi": 0.55, "pan_indian": 0.30, "deccani": 0.10, "south": 0.05},
    "Hyderabad": {"telugu": 0.55, "deccani": 0.20, "pan_indian": 0.20, "south": 0.05},
}

# Languages a doctor consults in (ISO 639-1). English always; regional languages by city and group.
LANGUAGE_RULES: dict[str, dict[str, float]] = {
    "Pune": {"hi": 0.85, "mr": 0.70},
    "Hyderabad": {"te": 0.75, "hi": 0.60},
}
GROUP_LANGUAGES: dict[str, list[str]] = {"marathi": ["mr"], "telugu": ["te"], "deccani": ["ur", "hi"]}
