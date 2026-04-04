from fastapi import FastAPI

app = FastAPI(title="Unified Migration Accelerator API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
