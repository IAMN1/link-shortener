import datetime
import sys
import threading
from typing import Callable, Generic, List, Optional, Tuple, TypeVar


T = TypeVar('T')

class FailoverService(Generic[T]):
    """
    Generic failover mechanism that switches between multiple service implementations.

    Maintains an ordered list of services (primary, secondary, etc.). When a call to the
    current service fails, it automatically switches to the next available service.
    Optionally runs a background health check thread to attempt upgrading to a higher-priority
    service when it becomes healthy again.

    Type parameter T represents the service interface (e.g., Logger, AuditLogger).
    """

    def __init__(
        self, 
        services: List[Tuple[T, str]], 
        check_interval: Optional[float] = 30.0,
        health_checker: Optional[Callable[[T], bool]] = None
    ):
        """
        Initialize the failover service.

        Args:
            services: List of (service_instance, service_name) in priority order
                      (highest first). The first service is the most desired.
            check_interval: Seconds between background health checks.
                            If None, background checks are disabled.
            health_checker: Optional function that takes a service instance and
                            returns True if it's healthy, False otherwise.
                            If not provided, only failures during actual calls
                            trigger switching.
        """

        if not services:
            raise ValueError("At least one service required")
        
        self._services = services
        self._check_interval = check_interval
        self._health_checker = health_checker
        self._lock = threading.RLock()
        self._current_index = 0 # index of currently active service

        self._stop_event = threading.Event()
        self._thread = None

        if self._check_interval is not None:
            self._thread = threading.Thread(
                target=self._periodic_check,
                daemon=True
            )
            self._thread.start()

    def get_current_service_name(self) -> str:
        """Return the name of the currently active service"""
        with self._lock:
            return self._services[self._current_index][1]

    def _periodic_check(self):
        """
        Background thread: periodically try to upgrade to a higher-priority service.
        Runs every `_check_interval` seconds until `shutdown()` is called.
        """
        while not self._stop_event.wait(self._check_interval):
            self._attempt_upgrade()

    def _attempt_upgrade(self):
        """
        Try to switch to a service with higher priority (lower index) if it is healthy.
        If a healthy higher-priority service is found, switch to it and log the event.
        """
        with self._lock:
            if self._current_index == 0:
                return # already the best
            
            for idx, (service, name) in enumerate(self._services[:self._current_index]):
                if self._is_service_healthly(service):
                    self._log(f"Upgrading from {self._services[self._current_index][1]} to {name}")
                    self._current_index = idx
                    return

    def _is_service_healthly(self, service: T) -> bool:
        """Use the health checker if provided; otherwise assume it's healthy."""

        if self._health_checker is None:
            return True

        try:
            return self._health_checker(service)
        except Exception:
            return False

    def _switch_to_next(self) -> bool:
        """
        Switch to the next available service (higher index).

        Returns:
            True if a fallback service was found and switched to, False if none left.
        """
        with self._lock:
            for idx in range(self._current_index + 1, len(self._services)):
                self._current_index = idx
                self._log(f"Switched to {self._services[idx][1]}")
                return True
            return False
    
    def _log(self, message: str):
        """Internal logging for failover events (printed to stderr)."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp} [FailoverService] {message}", file=sys.stderr)
    
    def execute(self, method_name: str, *args, **kwargs):
        """
        Call a method on the current active service.

        If the call fails, automatically switch to the next service and retry.
        Returns the result of the successful call, or None if all services fail.

        Args:
            method_name: Name of the method to call on the service.
            *args, **kwargs: Arguments to pass to the method.

        Returns:
            Result of the method call, or None if all services failed.
        """
        with self._lock:
            attempts = 0
            max_attempts = len(self._services)
            while attempts < max_attempts:
                service, name = self._services[self._current_index]
                try:
                    method = getattr(service, method_name)
                    return method(*args, **kwargs)
                except Exception as e:
                    self._log(f"Service {name} failed for {method_name}: {e}. Attempting switch.")

                    if not self._switch_to_next():
                        break
                attempts += 1
            
            # All services failed
            return None

    def shutdown(self):
        """Stop the background health check thread and wait for it to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)
