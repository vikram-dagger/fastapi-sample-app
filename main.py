from fastapi import FastAPI, Depends
from routers import router
from dependencies import init_db, get_db


def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""
    app = FastAPI()

    # Initialize database
    init_db()

    # Include routers
    app.include_router(router, prefix="/api", dependencies=[Depends(get_db)])

    return app


app = create_app()
