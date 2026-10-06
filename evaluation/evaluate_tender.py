import argparse
import json
from pathlib import Path

from app.tender_parser import FIELDS, parse_freight_tender

DEFAULT_DATA_PATH = Path("data/freight_tender_company_test.json")

def load_cases(dataset_path):
    with Path(dataset_path).open("r", encoding="utf-8") as data_file:
        return json.load(data_file)


def compare_case(expected, actual):
    return {
        field: expected.get(field) == actual.get(field)
        for field in FIELDS
    }


def main(dataset_path=DEFAULT_DATA_PATH):
    cases = load_cases(dataset_path)
    all_results = []
    failures_by_case = []

    for case in cases:
        actual = parse_freight_tender(case["input"])
        results = compare_case(case["expected"], actual)
        all_results.append(results)

        failed_fields = [field for field, passed in results.items() if not passed]
        if failed_fields:
            failures_by_case.append(
                (case["id"], case["expected"], actual, failed_fields)
            )

    total_fields = sum(len(result) for result in all_results)
    correct_fields = sum(sum(result.values()) for result in all_results)
    accuracy = correct_fields / total_fields if total_fields else 0

    print(f"Tender cases tested: {len(cases)}")
    print(f"Total evaluated fields: {total_fields}")
    print(f"Correct fields: {correct_fields}")
    print(f"Field accuracy: {accuracy:.2%}")
    print("Failures by case:")
    if failures_by_case:
        for case_id, expected, actual, failed_fields in failures_by_case:
            print(f"  {case_id}:")
            for field in failed_fields:
                print(
                    f"    {field}: expected={expected.get(field)!r}, "
                    f"actual={actual.get(field)!r}"
                )
    else:
        print("  None")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset",
        nargs="?",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help="Tender dataset JSON path",
    )
    arguments = parser.parse_args()
    main(arguments.dataset)
