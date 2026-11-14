#!/data/data/com.termux/files/usr/bin/env python
import contextlib
import datetime as dt
import json
import sys
from argparse import ArgumentParser, ArgumentTypeError, Namespace
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import JsonLexer

try:
    import idna
except ImportError:
    idna = None

VERSION = "0.1.0"
MYNAME = (sys.argv[0] if sys.argv else "bestwhois").replace("./", "")
RC_FILE_LOCS: tuple[Path, ...] = (
    Path(".bestwhoisrc"),
    Path("~/.bestwhoisrc").expanduser(),
    Path("data/data/com.termux/files/usr/etc/bestwhois/bestwhoisrc"),
)
TEXT_FIELDS: tuple[str, ...] = ("rawText", "strippedText", "cleanText", "header", "footer")
HISTORY_BASE = "https://whois-history-api.whoisxmlapi.com/api/v1"
WHOIS_BASE = "https://www.whoisxmlapi.com/whoisserver/WhoisService"


def valid_date(s: str) -> str:
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        raise ArgumentTypeError(f"Not a valid date: '{s}'.")
    return s


def is_empty_field(field: Any) -> bool:
    if field is None:
        return True
    return isinstance(field, (str, dict, list)) and not field


def purge_empty_fields(structure: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field, value in structure.items():
        if isinstance(value, dict):
            value = purge_empty_fields(value)
        if not is_empty_field(value):
            result[field] = value
    return result


def _format_text(structure: dict[str, Any], depth: int, lines: list[str]) -> None:
    for field, value in structure.items():
        tabs = "\t" * depth
        if isinstance(value, list):
            lines.append(f"{tabs}{field}: {', '.join(str(item) for item in value)}")
        elif isinstance(value, dict):
            lines.append(f"{tabs}{field}: ")
            _format_text(value, depth + 1, lines)
        else:
            lines.append(f"{tabs}{field}: {value}")


def format_text(structure: dict[str, Any]) -> str:
    lines: list[str] = []
    _format_text(structure, 0, lines)
    return "\n".join(lines)


def process_raw_text(record: dict[str, Any], *, full: bool, stripped: bool) -> None:
    if stripped:
        for field in TEXT_FIELDS:
            with contextlib.suppress(KeyError, TypeError):
                record[field] = record[field][:64] + "..."
        for value in record.values():
            if isinstance(value, dict):
                for field in TEXT_FIELDS:
                    with contextlib.suppress(KeyError, TypeError):
                        value[field] = value[field][:64] + "..."
    elif not full:
        for field in TEXT_FIELDS:
            record.pop(field, None)
        for value in record.values():
            if isinstance(value, dict):
                for field in TEXT_FIELDS:
                    value.pop(field, None)


def find_api_key(args: Namespace) -> str | None:
    if args.apikey is not None:
        return args.apikey
    candidates: list[Path] = []
    if args.rcfile is not None:
        candidates.append(args.rcfile)
    candidates.extend(RC_FILE_LOCS)
    for rc in candidates:
        try:
            return rc.read_text().strip()
        except (OSError, ValueError):
            continue
    return None


def encode_domain(domain: str) -> str:
    if idna is not None:
        return idna.encode(domain).decode("utf-8")
    if not all(ord(c) < 128 for c in domain):
        sys.stderr.write(
            'Please install the "idna" Python package to query non-ASCII unicode domain names.\nExiting.\n'
        )
        sys.exit(3)
    return domain


def build_url(args: Namespace, api_key: str, domain: str) -> tuple[str, bool]:
    history = args.history or any((
        args.since_date,
        args.created_date_from,
        args.created_date_to,
        args.updated_date_from,
        args.updated_date_to,
        args.expired_date_from,
        args.expired_date_to,
    ))
    params: dict[str, Any]
    if history:
        base = HISTORY_BASE
        params = {"apiKey": api_key, "outputformat": "JSON", "mode": "purchase", "domainName": domain}
        if args.since_date is not None:
            params["sinceDate"] = args.since_date
        if args.created_date_from is not None:
            params["createdDateFrom"] = args.created_date_from
        if args.created_date_to is not None:
            params["createdDateTo"] = args.created_date_to
        if args.updated_date_from is not None:
            params["updatedDateFrom"] = args.updated_date_from
        if args.updated_date_to is not None:
            params["updatedDateTo"] = args.updated_date_to
        if args.expired_date_from is not None:
            params["expiredDateFrom"] = args.expired_date_from
        if args.expired_date_to is not None:
            params["expiredDateTo"] = args.expired_date_to
    else:
        base = WHOIS_BASE
        params = {"apiKey": api_key, "outputformat": "JSON", "ip": 1, "domainName": domain}
    return f"{base}?{urlencode(params)}", history


def build_parser() -> ArgumentParser:
    p = ArgumentParser(
        prog=MYNAME,
        description="Command-line utility to query domains in the WhoisXML API WHOIS service similarly to the whois command.",
    )
    p.add_argument(
        "domainName", help="The domain to be queried. Domains with national characters can be Unicode or IDN."
    )
    p.add_argument("--version", action="version", version=f"{MYNAME} ver. {VERSION}\n    (c) WhoisXML API Inc.")
    p.add_argument("--rcfile", type=Path, help="Use this rc file. Will override all default ini locations.")
    p.add_argument("--apikey", help="Directly specify the API key. Overrides any ini file.")
    p.add_argument(
        "--nocolor",
        action="store_true",
        help="Do not colorize output. Useful in scripts. Colors are not supported on Windows, so there it is default.",
    )
    p.add_argument(
        "--text",
        action="store_true",
        help="Print a textual output instead of a JSON-style format. Results in a behavior similar to the whois command.",
    )
    p.add_argument(
        "--fullrawtext",
        action="store_true",
        help="Print all raw text field contents. The default is to suppress raw texts fully.",
    )
    p.add_argument(
        "--strippedrawtext",
        action="store_true",
        help="Print the first 128 characters of raw text fields. The default is to suppress raw texts fully.",
    )
    p.add_argument("--keep-empty", action="store_true", help="Keep and display fields with empty and null values")
    p.add_argument(
        "--history",
        action="store_true",
        help="Get historic records from the history API. The following option imply this automatically.",
    )
    p.add_argument(
        "--since-date",
        type=valid_date,
        metavar="YYYY-MM-DD",
        help="(history) If present, search through activities discovered since the given date. Sometimes there is a latency between the actual added/renewal/expired date and the date when our system detected this change. We recommend using this field in your monitoring tools for filtering daily changes.",
    )
    p.add_argument(
        "--created-date-from",
        type=valid_date,
        metavar="YYYY-MM-DD",
        help="(history) If present, search through domains created after the given date.",
    )
    p.add_argument(
        "--created-date-to",
        type=valid_date,
        metavar="YYYY-MM-DD",
        help="(history) If present, search through domains created before the given date.",
    )
    p.add_argument(
        "--updated-date-from",
        type=valid_date,
        metavar="YYYY-MM-DD",
        help="(history) If present, search through domains updated after the given date.",
    )
    p.add_argument(
        "--updated-date-to",
        type=valid_date,
        metavar="YYYY-MM-DD",
        help="(history) If present, search through domains updated before the given date.",
    )
    p.add_argument(
        "--expired-date-from",
        type=valid_date,
        metavar="YYYY-MM-DD",
        help="(history) If present, search through domains expired after the given date.",
    )
    p.add_argument(
        "--expired-date-to",
        type=valid_date,
        metavar="YYYY-MM-DD",
        help="(history) If present, search through domains expired before the given date.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    api_key = find_api_key(args)
    if api_key is None:
        raise ValueError("No API key found. Check rc files or specify directly.")
    domain_name = encode_domain(args.domainName)
    url, history = build_url(args, api_key, domain_name)
    try:
        result = requests.get(url, timeout=30).json()
    except (requests.RequestException, ValueError) as e:
        sys.stderr.write("Error invoking API. The API key or the domain name is probably invalid.\n")
        sys.stderr.write(f"Error text: {e!s}\n")
        return 1
    if history:
        record_count = result.get("recordsCount", 0)
        if record_count == 0:
            print("No records found. The output of the API was:")
            print(json.dumps(result, indent=1, sort_keys=False))
            return 2
        records = result["records"]
    else:
        the_record = result.get("WhoisRecord")
        if the_record is None:
            print("No records found. The output of the API was:")
            print(json.dumps(result, indent=1, sort_keys=False))
            return 2
        records = [the_record]
        record_count = 1
    for record_number, whois_record in enumerate(records, start=1):
        if not args.keep_empty:
            whois_record = purge_empty_fields(whois_record)
        process_raw_text(whois_record, full=args.fullrawtext, stripped=args.strippedrawtext)
        json_str = json.dumps(whois_record, indent=1, sort_keys=False)
        if history:
            print(f"Historic record no. {record_number} of {record_count} for {args.domainName}:\n------------\n")
        if args.text:
            print(format_text(whois_record))
        elif args.nocolor or sys.platform in {"win32", "win64"}:
            print(json_str)
        else:
            print(highlight(json_str, JsonLexer(), TerminalFormatter()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
