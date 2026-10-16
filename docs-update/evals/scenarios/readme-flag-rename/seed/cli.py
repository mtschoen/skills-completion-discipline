#!/usr/bin/env python3
"""Simple CLI that exports data to a file."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Export data to a file.")
    parser.add_argument("--output", required=True, help="Path to the output file.")
    parser.add_argument(
        "--format", default="json", choices=["json", "csv"], help="Output format."
    )
    args = parser.parse_args()
    print(f"Exporting to {args.output} as {args.format}")


if __name__ == "__main__":
    main()
