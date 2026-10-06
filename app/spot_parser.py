import json
import argparse
from pathlib import Path
import os
import re
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "rfq.schema.json"
with SCHEMA_PATH.open("r", encoding="utf-8") as f:
    RFQ_SCHEMA = json.load(f)

SCHEMA_FIELDS = RFQ_SCHEMA["required"]

FIELDS = [
    "origin",
    "destination",
    "container_type",
    "container_count",
    "gross_weight_kg",
    "commodity",
    "cargo_ready_date",
    "required_arrival_date",
    "incoterm",
    "dangerous_goods",
    "hs_code",
    "service_scope",
    "unsupported_equipment",
]

def extract_rfq(email_text):
    response = client.responses.create(
        model="gpt-6-luna",
        reasoning={"effort": "none"},
        temperature=0,
        input=[
            {
                "role": "system",
                "content": (
                    "Extract freight RFQ data exactly from the provided text. "
                    "Do not infer missing information. "
                    "If a value is not explicitly stated or cannot be determined "
                    "without guessing, return null. "
                    "Normalize weights to kilograms. "
                    "Normalize 40HQ as 40HC. "
                    "Use OTHER for unsupported equipment such as 40OT. "
                    "Never infer service_scope from an Incoterm alone. "
                    "Only return service_scope when the requested pickup/delivery scope is explicitly stated in the text. "
                    "If multiple origins or multiple destinations represent separate shipment options, do not combine them into one location string. Return null for the ambiguous field. "
                    "For cargo_ready_date and required_arrival_date, return only YYYY-MM-DD. If the year is absent and cannot be determined explicitly, return null. "
                    "raw_equipment refers only to the container/equipment description, not the cargo description. "
                    "Commodity refers to the goods being shipped. Do not treat cargo descriptions such as 'reefer boxes' as container equipment unless the text explicitly says the container itself is refrigerated."
                ),
            },
            {
                "role": "user",
                "content": email_text,
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "rfq_extraction",
                "strict": True,
                "schema": RFQ_SCHEMA,
            }
        },
    )

    return json.loads(response.output_text)

def valid_full_date(value):
    if value is None:
        return False

    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def post_process_rfq(data, email_text):
    if data["cargo_ready_date"] is not None:
        if not valid_full_date(data["cargo_ready_date"]):
            data["cargo_ready_date"] = None

    if data["required_arrival_date"] is not None:
        if not valid_full_date(data["required_arrival_date"]):
            data["required_arrival_date"] = None

    final_destination_pattern = re.compile(
        r"\bfinal\s+(?:transit\s+to|destination(?:\s+to)?)\s+(.+?)"
        r"(?=(?:,\s*(?:\d+\s*[x×]|please\b|total\b|gross\b|approx(?:imately)?\b))|[.;\n]|$)",
        re.IGNORECASE,
    )
    final_destination_match = final_destination_pattern.search(email_text)
    if final_destination_match:
        destination = final_destination_match.group(1).strip(" ,.;:")
        if destination:
            data["destination"] = destination

    explicit_scopes = set()
    scope_pattern = re.compile(
        r"\b(door|port)(?:\s*-\s*|\s+)to(?:\s*-\s*|\s+)(door|port)\b",
        re.IGNORECASE,
    )
    for match in scope_pattern.finditer(email_text):
        explicit_scopes.add(
            f"{match.group(1).lower()}-{match.group(2).lower()}"
        )
    data["service_scope"] = (
        explicit_scopes.pop() if len(explicit_scopes) == 1 else None
    )

    has_unqualified_20_foot_equipment = re.search(
        r"(?<!\d)20\s*(?:-\s*)?(?:foot|feet|ft)(?:\s*-\s*|\s+)"
        r"(?:shipping\s+)?(?:containers?|FCL)\b"
        r"|(?<!\d)20\s*['\u2032](?:\s*-\s*|\s+)(?:shipping\s+)?(?:containers?|FCL)\b"
        r"|\bFCL\s+(?<!\d)20\s*(?:-\s*)?(?:foot|feet|ft)\b",
        email_text,
        re.IGNORECASE,
    ) is not None
    has_explicit_container_type = re.search(
        r"\b(?:gp|dry|standard|general purpose)\b", email_text, re.IGNORECASE
    ) is not None
    if (
        data["container_type"] == "20GP"
        and has_unqualified_20_foot_equipment
        and not has_explicit_container_type
    ):
        data["container_type"] = None

    if not explicit_container_quantity_matches(email_text):
        data["container_count"] = None

    generic_logistics_descriptors = {
        "cargo",
        "oog cargo",
        "general cargo",
        "dg cargo",
        "non-dg cargo",
    }
    if (
        isinstance(data["commodity"], str)
        and data["commodity"].strip().lower() in generic_logistics_descriptors
    ):
        data["commodity"] = None

    return data


def recover_missing_commodity(email_text, data):
    if data["commodity"] is not None:
        return data

    response = client.responses.create(
        model="gpt-6-luna",
        reasoning={"effort": "none"},
        temperature=0,
        input=[
            {
                "role": "system",
                "content": (
                    "Determine whether the freight request explicitly identifies the goods being shipped. "
                    "Any explicit noun phrase describing the shipped goods counts as a commodity, including generic physical goods descriptions such as equipment, machinery, spare parts, boxes, vehicles, textiles, or chemicals. "
                    "Cargo descriptors such as 'OOG cargo', 'general cargo', 'DG cargo', 'non-DG cargo', and plain 'cargo' must return null; they do not identify the goods. "
                    "Prefer the exact phrase from the RFQ. "
                    "Do not infer a commodity that is not present in the text."
                ),
            },
            {
                "role": "user",
                "content": email_text,
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "commodity_recovery",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "commodity": {
                            "type": ["string", "null"]
                        }
                    },
                    "required": ["commodity"],
                    "additionalProperties": False,
                },
            }
        },
    )

    recovered = json.loads(response.output_text)

    if recovered["commodity"] is not None:
        data["commodity"] = recovered["commodity"]

    return data


def explicit_container_quantity_matches(email_text):
    patterns = [
        re.compile(
            r"(?<!\w)(?P<quantity>\d+)\s*[x\u00d7]\s*"
            r"(?:20\s*GP|40\s*(?:GP|HC|HQ|OT))\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?<!\w)(?P<quantity>\d+)\s*[x\u00d7]\s*"
            r"(?:(?:20|40)\s*(?:ft|foot|feet|['\u2032])"
            r"(?:[-\s]+[A-Za-z]+){0,3}\s+)?(?:shipping\s+)?containers?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:shipping\s+)?containers?\s+quantity\s*"
            r"(?:is\s+|of\s+|[:=]\s*)?(?P<quantity>\d+)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?<!\w)(?P<quantity>\d+)\s+(?:shipping\s+)?containers?\b",
            re.IGNORECASE,
        ),
    ]
    matches = [match for pattern in patterns for match in pattern.finditer(email_text)]
    return sorted(matches, key=lambda match: match.start())


def recover_explicit_container_count(email_text, data):
    matches = explicit_container_quantity_matches(email_text)
    if not matches:
        return data

    for previous, current in zip(matches, matches[1:]):
        if re.search(
            r"\bor\b",
            email_text[previous.end():current.start()],
            re.IGNORECASE,
        ):
            data["container_count"] = None
            return data

    data["container_count"] = sum(
        int(match.group("quantity")) for match in matches
    )
    return data


def recover_explicit_commodity(email_text, data):
    if data["commodity"] is not None:
        return data

    equipment_pattern = re.compile(
        r"\b(?:\d+\s*[x×]\s*)?(?:20\s*GP|40\s*(?:GP|HC|HQ|OT))\b",
        re.IGNORECASE,
    )
    generic_descriptors = {
        "cargo",
        "oog cargo",
        "general cargo",
        "dg cargo",
        "non-dg cargo",
    }
    candidate_prefixes = re.compile(
        r"^(?:(?:containing|contains|loaded\s+with|carrying|with|of)\b\s*)+",
        re.IGNORECASE,
    )
    candidate_end = re.compile(
        r"(?=,|;|\.|\n|!|\?|\b(?:approximately|approx\.?|about|around|gross\s+weight|total\s+weight|weight|weighing|please\s+(?:quote|provide))\b|$)",
        re.IGNORECASE,
    )
    rejected_start = re.compile(
        r"^(?:from|to|via)\b|^(?:approximately|approx\.?|about|around)\b"
        r"|^\d|^(?:gross\s+)?weight\b|^total\s+weight\b",
        re.IGNORECASE,
    )
    weight_candidate = re.compile(
        r"\b\d[\d,]*(?:\.\d+)?\s*(?:kg|kgs|kilograms?|g|grams?|lb|lbs|pounds?|mt|tonnes?|tons?)\b",
        re.IGNORECASE,
    )

    for equipment_match in equipment_pattern.finditer(email_text):
        remainder = email_text[equipment_match.end():].lstrip(" \t:-")
        remainder = candidate_prefixes.sub("", remainder, count=1).strip()
        end_match = candidate_end.search(remainder)
        candidate = remainder[:end_match.start()] if end_match else remainder
        candidate = candidate.strip(" \t:-")
        if not candidate or rejected_start.search(candidate):
            continue

        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate.lower() in generic_descriptors or weight_candidate.search(candidate):
            continue

        data["commodity"] = candidate
        break

    return data

def parse_spot_rfq(text: str) -> dict:
    actual = extract_rfq(text)
    actual = recover_explicit_container_count(text, actual)
    actual = post_process_rfq(actual, text)
    actual = recover_explicit_commodity(text, actual)

    if actual["commodity"] is None:
        actual = recover_missing_commodity(text, actual)

    actual = post_process_rfq(actual, text)
    return actual
