import os
import structlog
from alembic.config import Config
from alembic import command
from app.core.config import settings

log = structlog.get_logger()

def run_migrations():
    """
    Run database migrations programmatically on startup.
    Ensures that the production database is always in sync with the latest models.
    """
    try:
        log.info("Checking for pending database migrations...")
        
        # Initialize Alembic configuration
        # Assuming we are running from the root of the project
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ini_path = os.path.join(base_dir, "alembic.ini")
        
        if not os.path.exists(ini_path):
            log.error("alembic.ini not found", path=ini_path)
            return

        alembic_cfg = Config(ini_path)
        
        # Explicitly set the database URL from settings to override any local ini defaults
        # Migration uses sync driver (psycopg2) usually, so we ensure standard postgresql://
        db_url = settings.SYNC_DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
            
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        
        # Run the upgrade to the latest revision (head)
        command.upgrade(alembic_cfg, "head")
        
        log.info("Database migrations applied successfully")
    except Exception as e:
        log.error("Database migration failed", error=str(e))
        # We don't want to crash the whole app if migrations fail (unless critical), 
        # but the next DB operation will likely fail anyway.
