# CargoAI RFQ Parser

Small prototype that extracts structured freight RFQ data from shipment quote requests using the OpenAI API.

## Setup

```bash
git clone https://github.com/AryaErgin/cargoai.git
cd cargoai

python -m venv .venv
```

Activate the environment:

**Windows**
```bash
.venv\Scripts\activate
```

**macOS/Linux**
```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```text
OPENAI_API_KEY=your_api_key_here
```

Run the RFQ benchmark:

```bash
python evaluate.py
```

The script tests the parser against the RFQs in `data/rfqs.json` and prints field-level extraction errors and overall accuracy.

## Structure

```text
cargoai/
├─ data/
│  └─ rfqs.json
├─ schemas/
│  └─ rfq.schema.json
├─ evaluate.py
├─ requirements.txt
└─ .env
```

`.env` is excluded from Git and should never be committed.