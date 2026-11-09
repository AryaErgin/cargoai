"""Internal RFQ draft review CLI (backend host only; shows carrier names and recipient emails).

    python -m sourcing.cli [--tenant-id UUID] list [--status S] [--limit N] [--offset N]
    python -m sourcing.cli show REQUEST_ID
    python -m sourcing.cli edit RFQ_ID [--subject TEXT] [--body-file PATH]
    python -m sourcing.cli approve RFQ_ID
    python -m sourcing.cli cancel RFQ_ID
    python -m sourcing.cli mark-sent RFQ_ID [--sent-at ISO8601]
    python -m sourcing.cli export-eml RFQ_ID --output PATH [--from-address ADDRESS]

Tenant defaults to CARGOAI_DEMO_TENANT_ID. Nothing is ever sent from this tool.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from uuid import UUID

from database.session import get_engine, session_scope
from sourcing import config, service
from sourcing.exceptions import SourcingError

SOURCING_STATUSES = ["NO_CARRIER_AVAILABLE", "RFQ_DRAFTED", "AWAITING_REPLIES", "RATE_RECEIVED", "CANCELLED"]


def _parser():
    parser = argparse.ArgumentParser(prog="python -m sourcing.cli", description="Review carrier RFQ drafts (nothing is sent).")
    parser.add_argument("--tenant-id", type=UUID, default=None, help="defaults to CARGOAI_DEMO_TENANT_ID")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list sourcing requests")
    listing.add_argument("--status", choices=SOURCING_STATUSES)
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)
    commands.add_parser("show", help="show a request with its RFQ drafts").add_argument("request_id", type=UUID)
    edit = commands.add_parser("edit", help="edit a DRAFT subject/body (reference code must remain)")
    edit.add_argument("rfq_id", type=UUID)
    edit.add_argument("--subject")
    edit.add_argument("--body-file", type=Path)
    commands.add_parser("approve", help="approve a DRAFT").add_argument("rfq_id", type=UUID)
    commands.add_parser("cancel", help="cancel a DRAFT/APPROVED/SENT RFQ").add_argument("rfq_id", type=UUID)
    sent = commands.add_parser("mark-sent", help="record a manual send of an APPROVED RFQ")
    sent.add_argument("rfq_id", type=UUID)
    sent.add_argument("--sent-at", type=datetime.fromisoformat)
    export = commands.add_parser("export-eml", help="write an APPROVED/SENT RFQ as .eml for manual sending")
    export.add_argument("rfq_id", type=UUID)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--from-address", default=None, help="defaults to rfq@<CARGOAI_RFQ_MESSAGE_DOMAIN>")
    return parser


def _tenant(args):
    if args.tenant_id is not None:
        return args.tenant_id
    try:
        return UUID(os.environ["CARGOAI_DEMO_TENANT_ID"])
    except (KeyError, ValueError):
        raise SourcingError("Pass --tenant-id or set CARGOAI_DEMO_TENANT_ID") from None


def _run(session, tenant_id, args):
    if args.command == "list":
        return service.list_requests(session, tenant_id, status=args.status, limit=args.limit, offset=args.offset)
    if args.command == "show":
        return service.get_request_detail(session, tenant_id, args.request_id)
    if args.command == "edit":
        current = service.get_rfq(session, tenant_id, args.rfq_id)
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else current["body"]
        return service.update_rfq_draft(session, tenant_id, args.rfq_id,
                                        {"subject": args.subject or current["subject"], "body": body})
    if args.command == "approve":
        return service.approve_rfq(session, tenant_id, args.rfq_id)
    if args.command == "cancel":
        return service.cancel_rfq(session, tenant_id, args.rfq_id)
    if args.command == "mark-sent":
        return service.mark_rfq_sent(session, tenant_id, args.rfq_id, {"sent_at": args.sent_at})
    if args.command == "export-eml":
        from_address = args.from_address or f"rfq@{config.message_domain()}"
        eml = service.export_rfq_eml(session, tenant_id, args.rfq_id, from_address=from_address)
        args.output.write_bytes(eml)
        return {"rfq_id": str(args.rfq_id), "written": str(args.output), "bytes": len(eml), "sent": False}
    raise SourcingError(f"Unknown command {args.command}")


def main(argv=None, *, engine=None, stdout=None, stderr=None):
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    args = _parser().parse_args(argv)
    try:
        tenant_id = _tenant(args)
        with session_scope(engine if engine is not None else get_engine()) as session:
            result = _run(session, tenant_id, args)
    except SourcingError as error:
        print(f"error: {error.code}: {error}", file=stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"error: {type(error).__name__}: {error}", file=stderr)
        return 2
    try:
        print(json.dumps(result, indent=2, ensure_ascii=False), file=stdout)
    except UnicodeEncodeError:  # legacy console code pages
        print(json.dumps(result, indent=2), file=stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
