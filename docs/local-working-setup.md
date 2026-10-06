# Saved local working setup

Verified on 2026-10-07 on this PC.

## Start the app

Open two ordinary PowerShell terminals. Run these commands from the repository root:

Backend terminal:

```powershell
cd C:\Users\PC\cargoai
.\start-backend.ps1
```

Frontend terminal:

```powershell
cd C:\Users\PC\cargoai
.\start-frontend.ps1
```

Keep both terminals open. Visit http://localhost:3000. Stop each server with Ctrl+C before starting another instance.

The backend launcher uses the project virtual environment, migrates and seeds the persistent `cargoai-demo.db` database, selects the seeded demo tenant, and enables local demo pricing. It listens on http://127.0.0.1:8000 with proxy headers disabled. The frontend launcher explicitly selects this backend address.

The existing `.env` supplies `OPENAI_API_KEY`. Keep the key private. Extraction requires outbound access to OpenAI; a restricted agent terminal previously produced a connection error. Run the launcher in ordinary PowerShell.

## Verified behavior

Extraction returned HTTP 200 for a sample shipment. The pricing endpoint returned HTTP 200 with the frontend origin allowed for Shanghai to Ambarli, 2 x 40HC, automotive parts, 36,000 kg, FOB, non-DG, pricing date 2026-10-15, currency USD. The synthetic demo sell total was USD 3,544.80.

Demo rates and FX are valid during October 2026. These are synthetic values, not live market quotes. Other dates, lanes, or equipment may have no matching demo rate. Company authentication and internal rate administration remain unimplemented; demo pricing is restricted to local access.

## Troubleshooting

- `RFQ parsing service failed`: check the backend terminal and `backend.log`. Both parser endpoints log exception tracebacks through the Uvicorn error logger.
- `Pricing disabled: authenticated company access is not implemented`: start with `start-backend.ps1`, which sets the required demo configuration.
- Port 8000 already in use: stop the existing backend before restarting. Two backend process trees were removed during troubleshooting.
- Health check: http://127.0.0.1:8000/health should return `{"status":"ok"}`.

The database and backend log stay on this PC and are excluded from Git. The launchers and these notes are saved project files.
