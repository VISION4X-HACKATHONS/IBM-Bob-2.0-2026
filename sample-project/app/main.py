from fastapi import FastAPI

from app.auth.routes import router as auth_router

app = FastAPI(title="Sample Account Service")
app.include_router(auth_router)
