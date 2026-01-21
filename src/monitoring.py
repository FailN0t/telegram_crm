"""
Monitoring module for Contact Manager health checks.

Provides health check and alerting functionality for the Contact Manager system.
Tracks success/failure rates and triggers alerts when failure rate exceeds thresholds.

Usage:
    from src.monitoring import ContactAddMonitor

    health = await ContactAddMonitor.check_health()
    # Returns:
    # {
    #     "hour": {"total": 50, "success": 45, "failures": 5, "failure_rate": 0.1, "status": "ok"},
    #     "day": {"total": 150, "success": 140, "failures": 10, "failure_rate": 0.067, "status": "ok"}
    # }
"""

from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy import select, and_, func

from src.database import SessionLocal, ContactAddLog
from src.logger import logger


class ContactAddMonitor:
    """
    Health monitoring for contact addition system.

    Provides statistics and health status for the last hour and last day.
    Triggers alerts when failure rate exceeds thresholds.

    Thresholds:
        - OK: failure_rate < 30%
        - WARNING: 30% <= failure_rate < 50%
        - CRITICAL: failure_rate >= 50%
    """

    @staticmethod
    async def check_health() -> Dict:
        """
        Check health of contact addition system.

        Calculates statistics for the last hour and last day:
        - Total attempts
        - Successful additions
        - Failures
        - Failure rate
        - Status (ok/warning/critical)

        Returns:
            Dictionary with hour and day statistics:
            {
                "hour": {
                    "total": int,
                    "success": int,
                    "failures": int,
                    "failure_rate": float,  # 0.0 to 1.0
                    "status": str  # "ok", "warning", or "critical"
                },
                "day": { ... }
            }

        Side effects:
            - Logs warnings/errors if failure rate is high
            - TODO: Send alerts to admins
        """
        async with SessionLocal() as db:
            now = datetime.utcnow()
            hour_ago = now - timedelta(hours=1)
            day_ago = now - timedelta(days=1)

            # Statistics for last hour
            hour_total_result = await db.execute(
                select(func.count(ContactAddLog.id)).where(
                    ContactAddLog.created_at >= hour_ago
                )
            )
            hour_success_result = await db.execute(
                select(func.count(ContactAddLog.id)).where(
                    and_(
                        ContactAddLog.created_at >= hour_ago,
                        ContactAddLog.success == True
                    )
                )
            )

            # Statistics for last day
            day_total_result = await db.execute(
                select(func.count(ContactAddLog.id)).where(
                    ContactAddLog.created_at >= day_ago
                )
            )
            day_success_result = await db.execute(
                select(func.count(ContactAddLog.id)).where(
                    and_(
                        ContactAddLog.created_at >= day_ago,
                        ContactAddLog.success == True
                    )
                )
            )

            hour_total = hour_total_result.scalar()
            hour_success = hour_success_result.scalar()
            day_total = day_total_result.scalar()
            day_success = day_success_result.scalar()

            # Calculate failure rates
            hour_failure_rate = 0.0 if hour_total == 0 else (hour_total - hour_success) / hour_total
            day_failure_rate = 0.0 if day_total == 0 else (day_total - day_success) / day_total

            # Determine status based on failure rate
            def get_status(failure_rate: float, total: int) -> str:
                """Get status string based on failure rate."""
                if total == 0:
                    return "ok"
                if failure_rate > 0.5:  # > 50% failures
                    return "critical"
                elif failure_rate > 0.3:  # > 30% failures
                    return "warning"
                return "ok"

            hour_status = get_status(hour_failure_rate, hour_total)
            day_status = get_status(day_failure_rate, day_total)

            health = {
                "hour": {
                    "total": hour_total,
                    "success": hour_success,
                    "failures": hour_total - hour_success,
                    "failure_rate": round(hour_failure_rate, 3),
                    "status": hour_status
                },
                "day": {
                    "total": day_total,
                    "success": day_success,
                    "failures": day_total - day_success,
                    "failure_rate": round(day_failure_rate, 3),
                    "status": day_status
                }
            }

            # ALERT if failure rate is critical
            if hour_status == "critical":
                logger.error(
                    f"🚨 CRITICAL: Contact add failure rate {hour_failure_rate:.1%} "
                    f"in last hour ({hour_total-hour_success}/{hour_total} failed)"
                )
                # TODO: Send critical alert to admins
                # await send_admin_alert(
                #     f"CRITICAL: Contact Manager failure rate {hour_failure_rate:.1%}. "
                #     f"Check /admin/contact-health for details."
                # )

            elif hour_status == "warning":
                logger.warning(
                    f"⚠️ WARNING: Contact add failure rate {hour_failure_rate:.1%} "
                    f"in last hour ({hour_total-hour_success}/{hour_total} failed)"
                )
                # TODO: Send warning alert to admins
                # await send_admin_alert(
                #     f"WARNING: Contact Manager failure rate {hour_failure_rate:.1%}. "
                #     f"Monitor /admin/contact-health."
                # )

            return health
