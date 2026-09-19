# Backend (Person B)

Fake endpoints first so the app can build against a real URL.

## Run

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Then expose with ngrok when ready:

```bash
ngrok http 8000
```

Open API docs: http://127.0.0.1:8000/docs
