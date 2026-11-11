"""report-cli: print a sales report from a CSV file."""

import argparse
import csv
import sys


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def render_text(rows):
    lines = []
    for row in rows:
        lines.append(f"{row['name']:<12} {row['region']:<8} {row['amount']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="report-cli")
    parser.add_argument("path", help="CSV file with name, region, amount columns")
    parser.add_argument("--format", choices=["text"], default="text")
    args = parser.parse_args(argv)
    rows = load_rows(args.path)
    if args.format == "text":
        print(render_text(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
