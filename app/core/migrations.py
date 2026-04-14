import os
import structlog
from alembic.config import Config
from alembic import command
from app.core.config import settings

from sqlalchemy import text
from app.core.database import engine

log = structlog.get_logger()

async def run_migrations():
    """
    Run database migrations programmatically on startup.
    Ensures that the production database is always in sync with the latest models.
    """
    # 1. First, attempt a manual DDL fallback for critical missing columns.
    # This ensures that even if Alembic fails, registration won't crash.
    try:
        async with engine.begin() as conn:
            log.info("Running manual DDL sync for critical columns...")
            await conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS location VARCHAR(255)"))
            await conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS hiring_budget INTEGER"))
            
            # Also ensure candidates has expected fields
            await conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS current_salary INTEGER"))
            await conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS expected_salary INTEGER"))
            log.info("Manual DDL sync complete")
    except Exception as ddl_err:
        log.warning("Manual DDL sync failed (might be fine if columns exist)", error=str(ddl_err))

    # 2. Attempt full Alembic migration
    try:
        log.info("Checking for pending database migrations via Alembic...")
        
        # Initialize Alembic configuration
        # Robust path finding: find the project root by looking for alembic.ini
        current_dir = os.path.dirname(os.path.abspath(__file__))
        ini_path = None
        
        # Traverse up to 4 levels to find alembic.ini
        for _ in range(4):
            potential_path = os.path.join(current_dir, "alembic.ini")
            if os.path.exists(potential_path):
                ini_path = potential_path
                break
            current_dir = os.path.dirname(current_dir)
        
        if not ini_path:
            log.error("alembic.ini not found in parent directories")
            return

        alembic_cfg = Config(ini_path)
        
        db_url = settings.SYNC_DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
            
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        
        # Run the upgrade
        command.upgrade(alembic_cfg, "head")
        log.info("Alembic migrations applied successfully")
    except Exception as e:
        log.error("Alembic migration failed", error=str(e))
