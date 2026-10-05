import json
from pathlib import Path
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

DATA_PATH = Path("data/rfqs.json")

FIELDS = [
    "origin",
    "destination",
    "container_type",
    "raw_equipment",
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
                    "Use OTHER for unsupported equipment such as 40OT."
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
                "schema": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": ["string", "null"]},
                        "destination": {"type": ["string", "null"]},
                        "container_type": {
                            "type": ["string", "null"],
                            "enum": ["20GP", "40GP", "40HC", "OTHER", None],
                        },
                        "raw_equipment": {"type": ["string", "null"]},
                        "container_count": {"type": ["integer", "null"]},
                        "gross_weight_kg": {"type": ["number", "null"]},
                        "commodity": {"type": ["string", "null"]},
                        "cargo_ready_date": {"type": ["string", "null"]},
                        "required_arrival_date": {"type": ["string", "null"]},
                        "incoterm": {"type": ["string", "null"]},
                        "dangerous_goods": {"type": ["boolean", "null"]},
                        "hs_code": {"type": ["string", "null"]},
                        "service_scope": {
                            "type": ["string", "null"],
                            "enum": [
                                "port-port",
                                "door-port",
                                "port-door",
                                "door-door",
                                None,
                            ],
                        },
                        "unsupported_equipment": {"type": "boolean"},
                    },
                    "required": FIELDS,
                    "additionalProperties": False,
                },
            }
        },
    )

    return json.loads(response.output_text)

def load_cases():
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize(value):
    if isinstance(value, str):
        return value.strip().lower()
    return value


def compare_case(expected, actual):
    results = {}

    for field in FIELDS:
        expected_value = normalize(expected.get(field))
        actual_value = normalize(actual.get(field))

        results[field] = expected_value == actual_value

    return results


def calculate_accuracy(all_results):
    correct = 0
    total = 0

    for case_results in all_results:
        for passed in case_results.values():
            total += 1

            if passed:
                correct += 1

    return correct / total if total else 0


def main():
    cases = load_cases()

    all_results = []

    for case in cases:
        # Later this will be replaced with the OpenAI response.
        actual = extract_rfq(case["input"])

        results = compare_case(case["expected"], actual)
        all_results.append(results)

        wrong_fields = [
            field
            for field, passed in results.items()
            if not passed
        ]

        if wrong_fields:
            print(f'{case["id"]}: FAIL')

            for field in wrong_fields:
                print(
                    f"  {field}: "
                    f"expected={case['expected'].get(field)!r}, "
                    f"actual={actual.get(field)!r}"
                )
        else:
            print(f'{case["id"]}: PASS')

    accuracy = calculate_accuracy(all_results)

    print()
    print(f"Field accuracy: {accuracy:.2%}")


if __name__ == "__main__":
    main()