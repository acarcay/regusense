from dotenv import load_dotenv

load_dotenv()

from config.settings import settings

settings.ensure_directories()

from core.logging_config import setup_logging
setup_logging(level="INFO", log_file=settings.logs_dir / "pipeline.log")

from cli.commands import main

if __name__ == "__main__":
    main()
