from fastapi import FastAPI

app = FastAPI(title="Mneme API")

@app.get("/")
async def root():
    return {"message": "Mneme API is running"}
