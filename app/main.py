"""
ReguSense FastAPI Application Factory.

Main application module with router registration, middleware, and lifecycle events.
"""

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.logging import setup_logging, get_logger, RequestContext


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events.
    """
    # Startup
    logger = get_logger(__name__)
    logger.info("Starting ReguSense API...")
    
    # Ensure directories exist
    settings.ensure_directories()
    
    # Pre-initialize memory (loads embedding model)
    try:
        from core.deps import get_memory
        memory = get_memory()
        logger.info(f"PoliticalMemory initialized with {memory.count()} documents")
    except Exception as e:
        logger.warning(f"Failed to initialize memory: {e}")
    
    logger.info(f"ReguSense API started on {settings.api_host}:{settings.api_port}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down ReguSense API...")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application instance
    """
    # Setup logging
    setup_logging(
        level="DEBUG" if settings.api_debug else "INFO",
        json_logs=not settings.api_debug,
    )
    
    logger = get_logger(__name__)
    
    # Create app
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "ReguSense API - Political Contradiction Detection and Legislative Risk Monitoring. "
            "Analyzes Turkish Parliament (TBMM) transcripts to detect contradictions and risks."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Request ID middleware
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        import uuid
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        RequestContext.set_request_id(request_id)
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        
        RequestContext.clear()
        return response
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "timestamp": datetime.now().isoformat(),
            },
        )
    
    # Register routers
    from api.routes.health import router as health_router
    from api.routes.detection import router as detection_router
    from api.routes.ingestion import router as ingestion_router
    
    app.include_router(health_router)
    app.include_router(detection_router)
    app.include_router(ingestion_router)
    
    logger.info("FastAPI application created successfully")
    
    return app


# Application instance for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_debug,
    )
