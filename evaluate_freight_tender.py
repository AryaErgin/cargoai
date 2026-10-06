"""Compatibility entry point for the freight tender evaluator."""
from evaluation.evaluate_tender import main

if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset", nargs="?", type=Path,
        default=Path("data/freight_tender_company_test.json"),
        help="Tender dataset JSON path",
    )
    args = parser.parse_args()
    main(args.dataset)
