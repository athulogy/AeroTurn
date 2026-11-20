import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aircraft_turnaround_disruption.sqlite")

MIN_TURNAROUND_MINS = 45

VULNERABLE_TIERS = {"WCHR", "UMNR", "MEDICAL"}

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all previous",
    "override duty limits",
    "override crew",
    "disregard safety",
    "bypass maintenance",
    "forget your instructions",
    "you are now",
    "act as",
    "jailbreak",
]

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/aeroturn")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
