#!/usr/bin/env python3
"""demo-cli: CLI de texto de juguete del arnés del A/B de orquestadores."""
import argparse
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="demo-cli", description="CLI de juguete")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("saluda", help="imprime un saludo")
    args = p.parse_args(argv)
    if args.cmd == "saluda":
        print("hola")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
