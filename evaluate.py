"""Compatibility entry point for the spot RFQ evaluator."""
from evaluation.evaluate_spot import main

if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", nargs="?", type=Path, default=Path("data/rfqs.json"))
    args = parser.parse_args()
    main(args.dataset)
