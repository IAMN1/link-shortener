import threading
from typing import List, Tuple
from link_shortener.application import Logger
from link_shortener.application.ports.logger.null_logger import NullLogger


class FailoverLogger(Logger):
    """
    Logger that can switch between multiple underlying loggers
    (primary, secondary, fallback) based on their availability.

    It periodically attempts to upgrade to a higher-priority logger
    and downgrades if the current logger fails.
    """

    def __init__(
        self, loggers: List[Tuple[Logger, str]], check_interval: float = 30.0
    ):
        """Initialize the failover logger.

        Args:
            loggers (List[Tuple[Logger, str]]): List of (logger, name) 
        in priority order (highest first). The first logger is the most desired.
            check_interval (float, optional): Seconds between attempts 
        to upgrade to a higher-priority logger. Defaults to 30.0.
        """

        self._loggers = loggers
        self._check_interval = check_interval
        self._lock = threading.RLock()
        self._current_index = 0 # index of currently active logger
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._periodic_check, 
            daemon=True
        )
        self._thread.start()

    def _periodic_check(self):
        """
        Background thread that periodically tries to upgrade
          to a higher-priority logger.
        """
        while not self._stop_event.wait(self._check_interval):
            self._attempt_upgrade()

    def _attempt_upgrade(self):
        """
        Try to switch to a logger 
        with higher priority (lower index) than current.
        """

        with self._lock:
            if self._current_index == 0:
                return # already best

            for idx, (logger, name) in enumerate(self._loggers[:self._current_index]):

                if self._is_logger_working(logger):
                    # Successfully connected to higher-priority logger
                    old_logger, old_name = self._loggers[self._current_index]
                    self._log(
                        f"Switching logger from {old_name} to {name} (upgrade)",
                        level="info"
                    )
                    self._current_index = idx
                    return

    def _is_logger_working(self, logger: Logger) -> bool:
        """Test if a logger is usable by attempting to write a test message."""
        try:
            # Use a low-level method to avoid recursion
            if isinstance(logger, NullLogger):
                return True # NullLogger always works

            # For real loggers, try to write a debug message (should not raise)
            logger.debug("FailoverLogger health check")
            return True

        except Exception:
            return False

    def _switch_to_next(self) -> bool:
        """Switch to the next available logger (higher index) if possible."""

        with self._lock:

            for idx in range(self._current_index + 1, len(self._loggers)):
                
                logger, name = self._loggers[idx]
                if self._is_logger_working(logger):
                    
                    old_logger, old_name = self._loggers[self._current_index]
                    
                    self._log(
                        f"Switching logger from {old_name} \
                            to {name} (downgrade due to error)", 
                        level="warning"
                    )
                self._current_index = idx
                return True
            
            # No working logger found, stay at current 
            # (which may also be broken, but we tried)
            return False

    def _log(self, message: str, level: str = "info") -> None:
        """
        Internal logging for failover events (uses current logger, but safe).
        """
        try:
            
            logger, _ = self._loggers[self._current_index]
            
            getattr(logger, level)(f"[FailoverLogger] {message}")
        except Exception:
            pass # nothing we can do unlucko :(

    # =============== Logger interface methods ===================================
    def debug(self, message: str, **kwargs):
        self._log_with_failover("debug", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log_with_failover("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log_with_failover("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log_with_failover("error", message, **kwargs)

    def exception(self, message: str, exc_info=None, **kwargs):
        self._log_with_failover("exception", message, exc_info=exc_info, **kwargs)

    def _log_with_failover(self, log_method: str, message: str, **kwargs):
        """
        Attempt to log with current logger; if it fails, try to switch to next.

        Args:
            log_method: Logger method name (e.g., 'debug', 'info').
            message: Log message.
            **kwargs: Additional structured data.
        """
        with self._lock:
            attempts = 0
            max_attempts = len(self._loggers)

            while attempts < max_attempts:
                
                logger, name = self._loggers[self._current_index]
                try:
                    
                    getattr(logger, log_method)(message, **kwargs)
                    return
                
                except Exception as e:
                    # Log failure (using the same logger may fail,
                    #  so we use internal method)

                    self._log(
                        f"Logger {name} failed for {log_method}: {e}. Attempting switch.", 
                        level="error"
                    )
                    if not self._switch_to_next():
                        # No more loggers, break out
                        break
                attempts += 1
