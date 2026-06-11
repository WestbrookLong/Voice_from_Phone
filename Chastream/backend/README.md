# Chastream Mobile Backend

Independent FastAPI backend for the Android application. The desktop Chastream
package is copied into `app/chastream_core` so server changes do not affect the
working desktop application.

## Local run

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-api.txt
$env:CHASTREAM_MOBILE_DATA_ROOT="$PWD\data"
$env:DASHSCOPE_API_KEY="..."
.\.venv\Scripts\uvicorn app.main:app --reload
```

Quick notes need only the API requirements. Full conversation processing also
requires `requirements-worker.txt` and enough memory for CAM++/SCL.

## API workflows

- `POST /api/v1/quick-notes`: transcribe an idea, create its title, summary and
  organized body.
- `POST /api/v1/conversations`: run Paraformer timestamps, optional SCL
  refinement, CAM++ collection matching and the selected Qwen organization
  style.
- `/api/v1/voiceprints`: manage speaker collections and their independently
  matched elements.

Jobs are persisted in SQLite and processed one at a time. Uploads and model
data are stored under `CHASTREAM_MOBILE_DATA_ROOT`, never under the system
drive used by the desktop application.

## Server paths

```text
/home/ubuntu/projects/chastream-mobile/backend
/home/ubuntu/projects/chastream-mobile/shared/.env
/home/ubuntu/projects/chastream-mobile/shared/data
```

Production is currently exposed at:

```text
http://106.53.94.254/chastream/
```
