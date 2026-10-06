import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "freight_tender.schema.json"

with SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
    TENDER_SCHEMA = json.load(schema_file)

FIELDS = TENDER_SCHEMA["required"]
INCOTERM_PATTERN = re.compile(
    r"\b(EXW|FCA|CPT|CIP|DAP|DPU|DDP|FAS|FOB|CFR|CIF)\b",
    re.IGNORECASE,
)

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def extract_freight_tender(input_text):
    response = client.responses.create(
        model="gpt-6-luna",
        reasoning={"effort": "none"},
        temperature=0,
        input=[
            {
                "role": "system",
                "content": (
                    "Extract freight tender or rate-request fields explicitly stated in the supplied text. "
                    "Do not infer missing or ambiguous values. "
                    "Return the transport mode only when sea or road is explicit. "
                    "Equipment descriptions are equipment only, not commodity or cargo. "
                    "Preserve explicit location, port, equipment, and Incoterm wording. "
                    "Return null for any field not explicitly present."
                ),
            },
            {
                "role": "user",
                "content": input_text,
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "freight_tender_extraction",
                "strict": True,
                "schema": TENDER_SCHEMA,
            }
        },
    )
    return json.loads(response.output_text)


def normalize_incoterm(value):
    if not isinstance(value, str):
        return None

    codes = {match.group(1).upper() for match in INCOTERM_PATTERN.finditer(value)}
    return codes.pop() if len(codes) == 1 else None


def parse_freight_tender(text: str) -> dict:
    actual = extract_freight_tender(text)
    actual["incoterm"] = normalize_incoterm(actual.get("incoterm"))
    return actual
