#!/usr/bin/env python3
import argparse


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate minute poll intervals as powers of base."
    )
    parser.add_argument("--base", type=positive_int, default=3)
    parser.add_argument("--steps", type=positive_int, default=5)
    args = parser.parse_args()

    schedule = [str(args.base**i) for i in range(args.steps)]
    print(" ".join(schedule))


if __name__ == "__main__":
    main()
