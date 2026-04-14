"""TopDev FastAPI Application Entry Point."""
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.exceptions import RequestValidationError
from app.core.config import settings
from app.api.router import api_router

log = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="TopDev API",
    description="AI-powered IT Recruitment SaaS — Top Talent. Top Scores.",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# ─── Rate Limiting ────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS ─────────────────────────────────────────────────────────────────────
origins = settings.allowed_origins_list
always_allow = ["https://www.topdevhq.com", "https://topdevhq.com", "https://topdev.ai", "https://www.topdev.ai", "http://localhost:5173"]
for origin in always_allow:
    if origin not in origins:
        origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*(topdevhq\.com|topdev\.ai|vercel\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Request Logging ──────────────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    log.info("request", method=request.method, path=request.url.path, status=response.status_code)
    return response

# ─── Global Exception Handler ─────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Try to grab form keys for debugging
    form_keys = []
    try:
        form = await request.form()
        form_keys = list(form.keys())
    except Exception:
        pass

    log.error("validation_error", 
              path=request.url.path, 
              detail=exc.errors(),
              headers=dict(request.headers),
              form_keys=form_keys)
              
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    log.error("unhandled_exception", path=request.url.path, error=error_msg)
    return JSONResponse(
        status_code=500, 
        content={"detail": f"Internal server error: {error_msg}"},
        headers={
            "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
            "Access-Control-Allow-Credentials": "true"
        }
    )

# ─── Routes ───────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "TopDev API", "version": "1.0.0"}

@app.on_event("startup")
async def startup():
    log.info("TopDev API starting", env=settings.APP_ENV)

@app.on_event("shutdown")
async def shutdown():
    log.info("TopDev API shutting down")
