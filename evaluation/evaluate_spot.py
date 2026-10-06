import argparse
import json
from pathlib import Path

from app.spot_parser import FIELDS, parse_spot_rfq

DATA_PATH = Path("data/rfqs.json")

def load_cases(dataset_path=DATA_PATH):
    with Path(dataset_path).open("r", encoding="utf-8") as f:
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


def main(dataset_path=DATA_PATH):
    cases = load_cases(dataset_path)

    all_results = []
    failures_by_rfq = []

    for case in cases:
        actual = parse_spot_rfq(case["input"])

        results = compare_case(case["expected"], actual)
        all_results.append(results)

        wrong_fields = [
            field
            for field, passed in results.items()
            if not passed
        ]

        if wrong_fields:
            failures_by_rfq.append(
                (case["id"], case["expected"], actual, wrong_fields)
            )

    total_fields = sum(len(results) for results in all_results)
    correct_fields = sum(
        sum(results.values()) for results in all_results
    )
    accuracy = correct_fields / total_fields if total_fields else 0

    print(f"RFQs tested: {len(cases)}")
    print(f"Total evaluated fields: {total_fields}")
    print(f"Correct fields: {correct_fields}")
    print(f"Field accuracy: {accuracy:.2%}")
    print("Failures by RFQ:")
    if failures_by_rfq:
        for rfq_id, expected, actual, wrong_fields in failures_by_rfq:
            print(f"  {rfq_id}:")
            for field in wrong_fields:
                print(
                    f"    {field}: expected={expected.get(field)!r}, "
                    f"actual={actual.get(field)!r}"
                )
    else:
        print("  None")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", nargs="?", type=Path, default=DATA_PATH)
    args = parser.parse_args()
    main(args.dataset)
