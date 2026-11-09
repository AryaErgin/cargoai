from email import message_from_bytes
from email.policy import default as default_policy
from io import StringIO
import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import func, select

from conftest import FIXED_NOW
from database.models import CarrierRFQ, Supplier, SupplierContact, SupplierLaneCapability
from database.seed import seed_demo, seed_demo_sourcing
from sourcing import cli, service

pytestmark = pytest.mark.usefixtures("no_network")


def sourcing_counts(session):
    return tuple(session.scalar(select(func.count()).select_from(model))
                 for model in (Supplier, SupplierContact, SupplierLaneCapability))


def test_seed_is_idempotent_and_synthetic(sourcing_world):
    world = sourcing_world
    before = sourcing_counts(world.session)
    assert before == (3, 3, 4)
    assert seed_demo(world.session)["sourcing"] == {"carriers": 0, "contacts": 0, "capabilities": 0}
    assert seed_demo_sourcing(world.session, world.tenant_id) == {"carriers": 0, "contacts": 0, "capabilities": 0}
    world.session.commit()
    assert sourcing_counts(world.session) == before
    emails = list(world.session.scalars(select(SupplierContact.email)))
    assert emails and all(email.endswith("@example.com") for email in emails)
    countries = {(row.origin_country_code, row.destination_country_code)
                 for row in world.session.scalars(select(SupplierLaneCapability))}
    assert {("CN", "TR"), ("TR", "CN")} <= countries


def test_seeded_lane_without_rate_triggers_drafts(sourcing_world):
    world = sourcing_world
    result = service.start_sourcing(world.session, world.tenant_id, world.request(), now=FIXED_NOW)
    assert result["sourcing_status"] == "RFQ_DRAFTED" and result["rfq_drafts_created"] == 2


@pytest.fixture
def cli_run(sourcing_world, sourcing_engine, monkeypatch):
    monkeypatch.setenv("CARGOAI_DEMO_TENANT_ID", str(sourcing_world.tenant_id))

    def run(*argv):
        out, err = StringIO(), StringIO()
        code = cli.main(list(argv), engine=sourcing_engine, stdout=out, stderr=err)
        return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()
    return run


@pytest.fixture
def drafted(sourcing_world):
    result = service.start_sourcing(sourcing_world.session, sourcing_world.tenant_id, sourcing_world.request(),
                                    now=FIXED_NOW)
    sourcing_world.session.commit()
    return result


def test_cli_list_show_edit_approve_mark_sent_export(sourcing_world, drafted, cli_run, tmp_path):
    code, listing, _ = cli_run("list")
    assert code == 0 and [row["quote_request_id"] for row in listing] == [drafted["quote_request_id"]]
    code, detail, _ = cli_run("show", drafted["quote_request_id"])
    assert code == 0 and len(detail["rfqs"]) == 2
    first, second = detail["rfqs"]
    assert first["carrier"] and "@example.com" in first["recipient_email"]

    body_file = tmp_path / "body.txt"
    body_file.write_text(f"Merhaba, lütfen fiyat verin.\n{first['reference_code']}\n", encoding="utf-8")
    code, edited, _ = cli_run("edit", first["rfq_id"], "--subject", f"Quote please {first['reference_code']}",
                              "--body-file", str(body_file))
    assert code == 0 and edited["subject"].startswith("Quote please") and "lütfen" in edited["body"]

    bad = tmp_path / "bad.txt"
    bad.write_text("reference removed", encoding="utf-8")
    code, _, err = cli_run("edit", first["rfq_id"], "--body-file", str(bad))
    assert code == 2 and "REFERENCE_CODE_REQUIRED" in err

    output = tmp_path / "rfq.eml"
    code, _, err = cli_run("export-eml", first["rfq_id"], "--output", str(output))
    assert code == 2 and "INVALID_TRANSITION" in err and not output.exists()
    assert cli_run("approve", first["rfq_id"])[1]["status"] == "APPROVED"
    code, _, err = cli_run("approve", first["rfq_id"])
    assert code == 2 and "INVALID_TRANSITION" in err

    code, exported, _ = cli_run("export-eml", first["rfq_id"], "--output", str(output), "--from-address", "ops@example.com")
    assert code == 0 and exported["sent"] is False
    parsed = message_from_bytes(output.read_bytes(), policy=default_policy)
    assert parsed["Message-ID"] == first["outbound_message_id"] and parsed["To"] == first["recipient_email"]

    code, sent, _ = cli_run("mark-sent", first["rfq_id"])
    assert code == 0 and sent["status"] == "SENT" and sent["send_channel"] == "MANUAL"
    assert cli_run("cancel", second["rfq_id"])[1]["status"] == "CANCELLED"
    code, listing, _ = cli_run("list", "--status", "AWAITING_REPLIES")
    assert listing[0]["rfq_counts"] == {"SENT": 1, "CANCELLED": 1}


def test_cli_tenant_scope_and_errors(sourcing_world, drafted, cli_run, monkeypatch):
    other = sourcing_world.new_tenant("cli-other")
    sourcing_world.session.commit()
    code, _, err = cli_run("--tenant-id", str(other), "show", drafted["quote_request_id"])
    assert code == 2 and "NOT_FOUND" in err
    assert cli_run("--tenant-id", str(other), "list")[1] == []
    monkeypatch.delenv("CARGOAI_DEMO_TENANT_ID")
    code, _, err = cli_run("list")
    assert code == 2 and "--tenant-id" in err
    with pytest.raises(SystemExit):
        cli_run("send", drafted["quote_request_id"])  # there is no send command


def test_cli_module_entrypoint(sourcing_world, sourcing_engine, drafted):
    environment = {**os.environ, "DATABASE_URL": str(sourcing_engine.url),
                   "CARGOAI_DEMO_TENANT_ID": str(sourcing_world.tenant_id)}
    result = subprocess.run([sys.executable, "-m", "sourcing.cli", "list"], capture_output=True, text=True,
                            env=environment, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["quote_request_id"] == drafted["quote_request_id"]
    assert sourcing_world.session.scalar(select(func.count()).select_from(CarrierRFQ)) == 2
