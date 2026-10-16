import sys
import os
import traceback
import logging

logger = logging.getLogger("app")

# ==========================================
# Domain-Specific App Exceptions
# ==========================================

class QuoMatchException(Exception):
    """Base exception for all application-specific errors."""
    pass

class LLMClientError(QuoMatchException):
    """Raised when an inference call or API communication fails."""
    pass

class ClassificationError(QuoMatchException):
    """Raised when page classification fails or returns invalid bounds."""
    pass

class ExtractionError(QuoMatchException):
    """Raised when line items or totals cannot be parsed from document."""
    pass

class MathInvariantError(QuoMatchException):
    """Raised when deterministic arithmetic validation fails."""
    pass


# ==========================================
# Global Unhandled Exception Hook
# ==========================================

def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception hook:
    - User terminal: Clean, human-readable summary (or full traceback if DEBUG=true).
    - Log file: Full stack trace is always preserved for debugging.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    debug_mode = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    if debug_mode:
        # Full stack trace to terminal
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    else:
        # Concise, readable error for terminal
        tb = traceback.extract_tb(exc_traceback)
        if tb:
            filename, line_no, func_name, text = tb[-1]
            filename = os.path.basename(filename)
            location_info = f"at {filename}:{line_no} in '{func_name}'"
        else:
            location_info = "at unknown location"

        print(f"\n❌[Error] {exc_type.__name__}: {exc_value}", file=sys.stderr)
        print(f"📍 Location: {location_info}", file=sys.stderr)
        print("💡 Tip: Set DEBUG=true to view the full stack trace.\n", file=sys.stderr)

    # In background log files, ALWAYS persist full trace info
    logger.error(
        f"Unhandled Exception: {exc_type.__name__}: {exc_value}",
        exc_info=(exc_type, exc_value, exc_traceback)
    )

def setup_exception_handler():
    """Activates the custom global exception hook."""
    sys.excepthook = handle_exception