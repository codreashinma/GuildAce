from fastapi import FastAPI

app = FastAPI(title="Codrea World ID Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
