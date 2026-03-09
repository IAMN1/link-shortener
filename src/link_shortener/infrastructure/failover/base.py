import datetime
import sys
import threading
from typing import Callable, Generic, List, Optional, Tuple, TypeVar


T = TypeVar('T')

class FailoverService(Generic[T]):
    """
    GGeneric failover mechanism that switches between multiple implementations
    of a service interface.

    Features:
    - On each method call, if the current service raises an exception,
      it automatically switches to the next available service.
    - A background thread periodically checks if a higher-priority service
      has become available and upgrades to it.
    - Custom health check function can be provided to determine service availability.
    """

    def __init__(
        self, 
        services: List[Tuple[T, str]], 
        check_interval: Optional[float] = 30.0,
        health_checker: Optional[Callable[[T], bool]] = None
    ):
        """
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
        #self._last_attempt = 0.0

        self._stop_event = threading.Event()
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
        """Background thread: periodically try to upgrade to a higher-priority service."""
        while not self._stop_event.wait(self._check_interval):
            self._attempt_upgrade()

    def _attempt_upgrade(self):
        """Try to switch to a service with higher priority (lower index) if it's healthy."""
        with self._lock:
            if self._current_index == 0:
                return # already the best
            
            for idx, (service, name) in enumerate(self._services[:self._current_index]):
                if self._is_service_healthly(service):
                    self._log(f"Upgrading from {self._services[self._current_index][1]} to {name}")
                    self._current_index = idx
                    return

    def _is_service_healthly(self, service: T) -> bool:
        """Use health checker if provided; otherwise assume it's healthy."""

        if self._health_checker is None:
            return True

        try:
            return self._health_checker(service)
        except Exception:
            return False

    def _switсh_to_next(self) -> bool:
        """Switch to the next available service (higher index)"""
        with self._lock:
            for idx in range(self._current_index + 1, len(self._services)):
                self._current_index = idx
                self._log(f"Switched to {self._services[idx][1]}")
                return True
            return False
    
    def _log(self, message: str):
        """Internal logging for failover events"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp} [FailoverService] {message}", file=sys.stderr)
    
    def execute(self, method_name: str, *args, **kwargs):
        """
        Call a method on the current active service.
        If it fails, automatically switch to the next service and retry.
        Returns the result of the successful call, or None if all services fail.
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

                    if not self._switсh_to_next():
                        break
                attempts += 1
            
            # All services failed
            return None