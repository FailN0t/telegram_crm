# Telegram Contact Management - Архитектура безопасного добавления контактов

**Дата создания:** 2026-01-20
**Версия:** 1.0
**Статус:** 📋 Design Document (не реализовано)

---

## Проблема

Необходимо извлекать номера телефонов пользователей Telegram для передачи в Bitrix24 CRM. Telegram предоставляет `User.phone` только если пользователь находится в контактах.

**Риски:**
- Telegram может забанить аккаунт за массовое добавление контактов
- Программный сбой (бесконечный цикл, race condition) может привести к превышению лимитов
- Flood errors от Telegram API при превышении rate limits
- Потеря бизнес-аккаунта из-за нарушения правил Telegram

**Требования:**
- Безопасное добавление контактов без риска бана
- Защита от программных сбоев
- Раздельные лимиты для входящих (inbound) и исходящих (outbound) сообщений
- Мониторинг и алертинг при проблемах
- Audit trail всех операций

---

## Два сценария с разными рисками

### 1️⃣ ВХОДЯЩИЕ (Inbound) - клиент пишет первым

```
Клиент → пишет нам → мы добавляем в контакты → получаем телефон
```

**Характеристики:**
- ✅ Легитимно - клиент инициировал контакт
- ✅ Низкий риск бана - это business communication
- ✅ Ожидаемо - клиент ожидает что вы его запомните

**Лимиты (из Telegram Business documentation):**
- 15 контактов/день для business аккаунтов
- При нарушении - на следующий день только 5 контактов
- **НО**: мы используем консервативные лимиты для безопасности

**Наши лимиты:**
- 50 контактов/час (консервативно)
- 150 контактов/день (консервативно)

### 2️⃣ ИСХОДЯЩИЕ (Outbound) - мы пишем первыми

```
Мы → инициируем контакт → добавляем в контакты → отправляем сообщение
```

**Характеристики:**
- ⚠️ Рискованно - можно воспринять как спам
- ⚠️ Высокий риск бана - массовая рассылка = спам
- ⚠️ Требует согласия - GDPR/антиспам законы

**Наши СТРОГИЕ лимиты:**
- 3 контакта/час
- 10 контактов/день
- Требуется предварительное согласие клиента

---

## Архитектура защиты (Defense in Depth)

### 8 уровней защиты

| Уровень | Защита | Что предотвращает |
|---------|--------|-------------------|
| 1 | **Circuit Breaker** | Бесконечный цикл ошибок |
| 2 | **Burst Limit** | Багованный while loop |
| 3 | **Rate Limits** | Превышение лимитов Telegram |
| 4 | **Timeout** | Зависание операций |
| 5 | **Lock** | Race conditions |
| 6 | **Flood Detection** | Telegram ban |
| 7 | **Audit Logging** | Потеря истории |
| 8 | **Health Monitoring** | Раннее обнаружение проблем |

---

## Компоненты системы

### 1. Database Table: `contact_add_log`

**Назначение:** Audit trail всех попыток добавления контактов + данные для rate limiting

```python
# src/database.py

class ContactAddLog(Base):
    """Лог попыток добавления контактов"""
    __tablename__ = "contact_add_log"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(BigInteger, nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # 'inbound' или 'outbound'
    source = Column(String(50))  # 'incoming_message', 'crm_request', etc
    success = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_contact_add_log_direction_created', 'direction', 'created_at'),
    )
```

**Миграция Alembic:**

```python
# alembic/versions/YYYYMMDD_add_contact_add_log.py

"""Add contact_add_log table for rate limiting and audit

Revision ID: ...
Revises: ...
Create Date: 2026-01-20
"""

from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.create_table(
        'contact_add_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('source', sa.String(50)),
        sa.Column('success', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )

    op.create_index('idx_contact_add_log_user', 'contact_add_log', ['telegram_user_id'])
    op.create_index('idx_contact_add_log_created', 'contact_add_log', ['created_at'])
    op.create_index('idx_contact_add_log_direction_created', 'contact_add_log', ['direction', 'created_at'])

def downgrade() -> None:
    op.drop_index('idx_contact_add_log_direction_created', table_name='contact_add_log')
    op.drop_index('idx_contact_add_log_created', table_name='contact_add_log')
    op.drop_index('idx_contact_add_log_user', table_name='contact_add_log')
    op.drop_table('contact_add_log')
```

---

### 2. Circuit Breaker класс

**Назначение:** Автоматическое отключение при повторяющихся ошибках

```python
# src/contact_manager.py

from datetime import datetime, timedelta
from typing import Optional, Tuple, List
import asyncio
from src.logger import logger

class ContactAddCircuitBreaker:
    """
    Circuit Breaker для защиты от программных сбоев

    Паттерн: https://martinfowler.com/bliki/CircuitBreaker.html

    Состояния:
    - CLOSED: Нормальная работа
    - OPEN: Защита активна, операции блокируются
    - HALF_OPEN: Тестирование восстановления

    Автоматически отключает добавление контактов если:
    - Слишком много попыток за короткое время (burst)
    - Слишком много ошибок подряд (failures)
    """

    def __init__(self):
        self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._failure_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._cooldown_until: Optional[datetime] = None

        # КРИТИЧЕСКИЕ лимиты - ЖЁСТКО закодированы (не из env!)
        self.MAX_FAILURES = 3  # После 3 ошибок подряд - отключаемся
        self.COOLDOWN_SECONDS = 300  # 5 минут не добавляем контакты
        self.MAX_BURST = 5  # Не более 5 добавлений за 60 секунд

        self._recent_adds: List[datetime] = []  # Timestamp недавних добавлений

    def is_open(self) -> bool:
        """Circuit breaker открыт (защита активна)?"""
        if self._state == "OPEN":
            # Проверить не истёк ли cooldown
            if self._cooldown_until and datetime.utcnow() >= self._cooldown_until:
                logger.info("🔄 Circuit breaker: переход в HALF_OPEN")
                self._state = "HALF_OPEN"
                self._failure_count = 0
                return False
            return True
        return False

    def check_burst_limit(self) -> Tuple[bool, str]:
        """
        Проверка burst limit - защита от бесконечного цикла

        Если за последнюю минуту было >= MAX_BURST попыток - STOP

        Returns:
            (can_proceed, reason)
        """
        now = datetime.utcnow()
        minute_ago = now - timedelta(seconds=60)

        # Очистить старые записи
        self._recent_adds = [ts for ts in self._recent_adds if ts > minute_ago]

        if len(self._recent_adds) >= self.MAX_BURST:
            logger.error(
                f"🚨 CIRCUIT BREAKER: Burst limit exceeded! "
                f"{len(self._recent_adds)} adds in 60 seconds. "
                f"Possible infinite loop detected!"
            )
            self._open_circuit("burst_limit_exceeded")
            return False, "burst_limit_exceeded"

        return True, "ok"

    def record_add_attempt(self):
        """Записать попытку добавления (для burst detection)"""
        self._recent_adds.append(datetime.utcnow())

    def record_success(self):
        """Успешное добавление - сбросить счётчик ошибок"""
        if self._state == "HALF_OPEN":
            logger.info("✅ Circuit breaker: возврат в CLOSED")

        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self, reason: str):
        """
        Зафиксировать ошибку

        После MAX_FAILURES ошибок подряд - открыть circuit breaker
        """
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()

        logger.warning(
            f"⚠️ Contact add failure #{self._failure_count}: {reason}"
        )

        if self._failure_count >= self.MAX_FAILURES:
            self._open_circuit(reason)

    def _open_circuit(self, reason: str):
        """Открыть circuit breaker - остановить добавление контактов"""
        self._state = "OPEN"
        self._cooldown_until = datetime.utcnow() + timedelta(
            seconds=self.COOLDOWN_SECONDS
        )

        logger.error(
            f"🚨 CIRCUIT BREAKER ОТКРЫТ: Остановка добавления контактов на "
            f"{self.COOLDOWN_SECONDS} секунд. Причина: {reason}"
        )

        # TODO: Отправить критический alert администратору!
        # await send_admin_alert(
        #     f"Circuit breaker открыт: {reason}. "
        #     f"Добавление контактов остановлено до {self._cooldown_until}"
        # )
```

---

### 3. Contact Manager класс

**Назначение:** Управление добавлением контактов с полной защитой

```python
# src/contact_manager.py (продолжение)

from telethon import TelegramClient, functions
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import SessionLocal, ContactAddLog

class ContactManager:
    """
    Управление добавлением контактов с защитой от сбоев

    Singleton - использовать один экземпляр на всё приложение
    """

    # Лимиты для ВХОДЯЩИХ (inbound) - консервативные
    INBOUND_MAX_PER_HOUR = 50
    INBOUND_MAX_PER_DAY = 150  # Telegram позволяет 200, но мы консервативнее

    # Лимиты для ИСХОДЯЩИХ (outbound) - ОЧЕНЬ строгие
    OUTBOUND_MAX_PER_HOUR = 3
    OUTBOUND_MAX_PER_DAY = 10

    def __init__(self):
        self.circuit_breaker = ContactAddCircuitBreaker()
        self._lock = asyncio.Lock()  # Защита от race conditions

    async def can_add_contact(
        self,
        direction: str,
        telegram_user_id: int
    ) -> Tuple[bool, str]:
        """
        Проверка можем ли добавить контакт (с защитой от сбоев)

        Args:
            direction: 'inbound' (клиент пишет) или 'outbound' (мы пишем)
            telegram_user_id: ID пользователя Telegram

        Returns:
            (can_add, reason)
            reason может быть:
            - "ok" - можно добавить
            - "already_in_contacts" - уже добавлен
            - "circuit_breaker_open" - защита активна
            - "burst_limit_exceeded" - слишком быстро
            - "hourly_limit_inbound" / "hourly_limit_outbound"
            - "daily_limit_inbound" / "daily_limit_outbound"
        """
        # 1. ПРОВЕРКА CIRCUIT BREAKER (высший приоритет)
        if self.circuit_breaker.is_open():
            logger.error(
                "🚨 Circuit breaker OPEN - contact additions disabled"
            )
            return False, "circuit_breaker_open"

        # 2. ПРОВЕРКА BURST LIMIT (защита от бесконечных циклов)
        can_burst, reason = self.circuit_breaker.check_burst_limit()
        if not can_burst:
            return False, reason

        # 3. Проверить не добавляли ли уже этого пользователя
        async with SessionLocal() as db:
            existing = await db.execute(
                select(ContactAddLog).where(
                    and_(
                        ContactAddLog.telegram_user_id == telegram_user_id,
                        ContactAddLog.success == True
                    )
                )
            )
            if existing.scalars().first():
                return True, "already_in_contacts"

            # 4. Выбрать лимиты в зависимости от направления
            if direction == 'inbound':
                max_hour = self.INBOUND_MAX_PER_HOUR
                max_day = self.INBOUND_MAX_PER_DAY
            else:  # outbound
                max_hour = self.OUTBOUND_MAX_PER_HOUR
                max_day = self.OUTBOUND_MAX_PER_DAY

            # 5. Проверить часовой лимит
            hour_ago = datetime.utcnow() - timedelta(hours=1)
            hour_result = await db.execute(
                select(func.count(ContactAddLog.id)).where(
                    and_(
                        ContactAddLog.direction == direction,
                        ContactAddLog.created_at >= hour_ago,
                        ContactAddLog.success == True
                    )
                )
            )
            hour_count = hour_result.scalar()

            if hour_count >= max_hour:
                logger.warning(
                    f"⚠️ Hourly limit reached for {direction}: "
                    f"{hour_count}/{max_hour}"
                )
                return False, f"hourly_limit_{direction}"

            # 6. Проверить суточный лимит
            day_ago = datetime.utcnow() - timedelta(days=1)
            day_result = await db.execute(
                select(func.count(ContactAddLog.id)).where(
                    and_(
                        ContactAddLog.direction == direction,
                        ContactAddLog.created_at >= day_ago,
                        ContactAddLog.success == True
                    )
                )
            )
            day_count = day_result.scalar()

            if day_count >= max_day:
                logger.warning(
                    f"⚠️ Daily limit reached for {direction}: "
                    f"{day_count}/{max_day}"
                )
                return False, f"daily_limit_{direction}"

            return True, "ok"

    async def add_to_contacts_with_protection(
        self,
        client: TelegramClient,
        telegram_user_id: int,
        first_name: str,
        last_name: Optional[str],
        username: Optional[str],
        direction: str,
        source: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Добавить в контакты с полной защитой от сбоев

        Этот метод:
        - Проверяет все лимиты
        - Использует timeout для Telegram API
        - Логирует все операции
        - Обновляет circuit breaker
        - Защищён от race conditions через asyncio.Lock

        Args:
            client: TelegramClient instance
            telegram_user_id: ID пользователя
            first_name: Имя
            last_name: Фамилия (опционально)
            username: Username (опционально)
            direction: 'inbound' или 'outbound'
            source: 'incoming_message', 'crm_request', etc

        Returns:
            (success, phone_number)
            phone_number может быть None если:
            - Не удалось добавить
            - Настройки приватности скрывают номер
        """
        # КРИТИЧНО: Lock для защиты от параллельных вызовов
        async with self._lock:
            # Проверить все лимиты
            can_add, reason = await self.can_add_contact(direction, telegram_user_id)

            if not can_add:
                # НЕ можем добавить - возвращаем False
                logger.info(
                    f"ℹ️ Cannot add contact: {reason} "
                    f"(user_id={telegram_user_id}, direction={direction})"
                )
                return False, None

            if reason == "already_in_contacts":
                # Уже в контактах - просто получить phone
                try:
                    sender = await asyncio.wait_for(
                        client.get_entity(telegram_user_id),
                        timeout=5.0
                    )
                    phone_number = getattr(sender, 'phone', None)
                    logger.info(
                        f"ℹ️ User already in contacts, phone: {phone_number or 'hidden'}"
                    )
                    return True, phone_number
                except asyncio.TimeoutError:
                    logger.error("❌ Timeout getting entity for existing contact")
                    return False, None
                except Exception as e:
                    logger.error(f"❌ Error getting entity: {e}")
                    return False, None

            # Записать попытку (для burst detection)
            self.circuit_breaker.record_add_attempt()

            # ПОПЫТКА ДОБАВЛЕНИЯ с полной защитой
            try:
                logger.info(
                    f"📇 [{direction}] Добавление контакта: "
                    f"{first_name} {last_name or ''} (@{username})"
                )

                # TIMEOUT на операцию - 10 секунд максимум
                result = await asyncio.wait_for(
                    client(functions.contacts.AddContactRequest(
                        id=username or telegram_user_id,
                        first_name=first_name,
                        last_name=last_name or "",
                        phone="",
                        add_phone_privacy_exception=False
                    )),
                    timeout=10.0
                )

                # Подождать обновления от Telegram
                await asyncio.sleep(1)

                # Получить обновленные данные пользователя
                sender = await asyncio.wait_for(
                    client.get_entity(telegram_user_id),
                    timeout=5.0
                )
                phone_number = getattr(sender, 'phone', None)

                # УСПЕХ - залогировать в БД
                async with SessionLocal() as db:
                    log_entry = ContactAddLog(
                        telegram_user_id=telegram_user_id,
                        direction=direction,
                        source=source,
                        success=True
                    )
                    db.add(log_entry)
                    await db.commit()

                # Сбросить circuit breaker (успешная операция)
                self.circuit_breaker.record_success()

                if phone_number:
                    logger.info(
                        f"✅ Контакт добавлен успешно, phone: {phone_number}"
                    )
                else:
                    logger.info(
                        f"✅ Контакт добавлен, но phone скрыт настройками приватности"
                    )

                return True, phone_number

            except asyncio.TimeoutError:
                logger.error(
                    f"❌ Timeout при добавлении контакта "
                    f"(user_id={telegram_user_id}, direction={direction})"
                )
                self.circuit_breaker.record_failure("timeout")

                # Залогировать неудачу
                async with SessionLocal() as db:
                    log_entry = ContactAddLog(
                        telegram_user_id=telegram_user_id,
                        direction=direction,
                        source=source,
                        success=False
                    )
                    db.add(log_entry)
                    await db.commit()

                return False, None

            except Exception as e:
                error_str = str(e).lower()

                # Специальная обработка Telegram flood errors
                if "flood" in error_str or "too many" in error_str:
                    logger.error(
                        f"🚨 TELEGRAM FLOOD LIMIT HIT: {e}. "
                        f"Немедленно открываем circuit breaker!"
                    )
                    # КРИТИЧНО - открыть circuit breaker СРАЗУ
                    self.circuit_breaker._open_circuit("telegram_flood_limit")

                elif "user_privacy" in error_str or "privacy" in error_str:
                    # Это не ошибка - просто privacy настройки пользователя
                    logger.info(
                        f"ℹ️ Пользователь запретил добавление в контакты "
                        f"(user_id={telegram_user_id})"
                    )
                    # НЕ считаем это failure для circuit breaker

                else:
                    # Другая ошибка - залогировать и увеличить failure count
                    logger.error(
                        f"❌ Ошибка добавления контакта: {e} "
                        f"(user_id={telegram_user_id}, direction={direction})"
                    )
                    self.circuit_breaker.record_failure(str(e)[:100])

                # Залогировать неудачу в БД
                async with SessionLocal() as db:
                    log_entry = ContactAddLog(
                        telegram_user_id=telegram_user_id,
                        direction=direction,
                        source=source,
                        success=False
                    )
                    db.add(log_entry)
                    await db.commit()

                return False, None


# Singleton instance
contact_manager = ContactManager()
```

---

### 4. Monitoring класс

**Назначение:** Health check и алертинг

```python
# src/monitoring.py

from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy import select, and_, func
from src.database import SessionLocal, ContactAddLog
from src.logger import logger

class ContactAddMonitor:
    """Мониторинг системы добавления контактов"""

    @staticmethod
    async def check_health() -> Dict:
        """
        Проверка здоровья системы добавления контактов

        Returns:
            {
                "hour": {
                    "total": int,
                    "success": int,
                    "failure_rate": float,
                    "status": "ok" | "warning" | "critical"
                },
                "day": { ... }
            }
        """
        async with SessionLocal() as db:
            now = datetime.utcnow()
            hour_ago = now - timedelta(hours=1)
            day_ago = now - timedelta(days=1)

            # Статистика за час
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

            # Статистика за день
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

            # Вычислить failure rate
            hour_failure_rate = 0.0 if hour_total == 0 else (hour_total - hour_success) / hour_total
            day_failure_rate = 0.0 if day_total == 0 else (day_total - day_success) / day_total

            # Определить статус
            def get_status(failure_rate: float, total: int) -> str:
                if total == 0:
                    return "ok"
                if failure_rate > 0.5:  # > 50% ошибок
                    return "critical"
                elif failure_rate > 0.3:  # > 30% ошибок
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

            # ALERT если failure rate критический
            if hour_status == "critical":
                logger.error(
                    f"🚨 CRITICAL: Contact add failure rate {hour_failure_rate:.1%} "
                    f"in last hour ({hour_total-hour_success}/{hour_total} failed)"
                )
                # TODO: Отправить критический alert

            elif hour_status == "warning":
                logger.warning(
                    f"⚠️ WARNING: Contact add failure rate {hour_failure_rate:.1%} "
                    f"in last hour ({hour_total-hour_success}/{hour_total} failed)"
                )
                # TODO: Отправить warning alert

            return health
```

---

## Интеграция в существующий код

### 1. Модификация `src/telegram_client.py`

**Метод:** `_handle_incoming_message` (~строка 1167)

**Изменения:**

```python
# src/telegram_client.py

async def _handle_incoming_message(self, event):
    """Обработка ВХОДЯЩИХ сообщений от пользователей"""

    sender = await event.get_sender()
    phone_number = getattr(sender, 'phone', None)

    # НОВОЕ: Если телефона нет - попробовать добавить в контакты
    if not phone_number and sender.username:
        from src.contact_manager import contact_manager

        logger.info(
            f"📞 Телефон не доступен для @{sender.username}, "
            f"пробуем добавить в контакты"
        )

        success, phone_number = await contact_manager.add_to_contacts_with_protection(
            client=self.client,
            telegram_user_id=sender.id,
            first_name=sender.first_name or "Клиент",
            last_name=sender.last_name,
            username=sender.username,
            direction='inbound',  # ✅ ВХОДЯЩИЙ - безопасно
            source='incoming_message'
        )

        if success and phone_number:
            logger.info(f"✅ Телефон получен: {phone_number}")
        elif success:
            logger.info("ℹ️ Контакт добавлен, но телефон скрыт")
        else:
            logger.warning("⚠️ Не удалось добавить контакт (проверьте лимиты)")

    # Передать phone (если получили) в bridge
    await self.bridge.handle_incoming_message(
        db=db,
        telegram_chat_id=sender.id,
        telegram_user_id=sender.id,
        user_first_name=sender.first_name or "",
        user_last_name=sender.last_name,
        username=sender.username,
        phone=phone_number,  # ✅ НОВЫЙ ПАРАМЕТР
        message_text=message.text,
        message_id=message.id
    )
```

---

### 2. Модификация `src/bridge.py`

**Метод:** `handle_incoming_message` (~строка 727)

**Добавить параметр `phone`:**

```python
# src/bridge.py

async def handle_incoming_message(
    self,
    db: AsyncSession,
    telegram_chat_id: int,
    telegram_user_id: int,
    user_first_name: str,
    user_last_name: Optional[str],
    username: Optional[str],
    phone: Optional[str],  # ✅ НОВЫЙ ПАРАМЕТР
    message_text: str,
    message_id: int
):
    """Обработка входящего сообщения из Telegram"""

    # ... существующий код ...

    # При создании/обновлении контакта в CRM - передать phone
    if self.crm_provider == "bitrix24":
        contact_data = await self.crm.create_contact(
            first_name=user_first_name,
            last_name=user_last_name,
            phone=phone,  # ✅ Передаём телефон
            telegram_username=username,
            telegram_chat_id=telegram_chat_id
        )

    # ... остальной код ...
```

**Метод:** `send_message_from_crm` (для ИСХОДЯЩИХ)

**Добавить проверку лимитов перед добавлением:**

```python
# src/bridge.py

async def send_message_from_crm(
    self,
    db: AsyncSession,
    contact_id: int,
    phone: Optional[str],
    username: Optional[str],
    message: str,
    account_id: Optional[int] = None
) -> Tuple[bool, str]:
    """Отправка сообщения из CRM (ИСХОДЯЩЕЕ)"""

    # Проверить есть ли mapping
    mapping = await get_chat_mapping_by_contact(db, contact_id)

    if not mapping:
        # Новый контакт - нужно добавить в Telegram
        from src.contact_manager import contact_manager

        logger.info(
            f"🆕 Новый контакт (CRM ID {contact_id}), "
            f"проверяем возможность добавления"
        )

        # ⚠️ ИСХОДЯЩЕЕ - строгие лимиты
        can_add, reason = await contact_manager.can_add_contact(
            direction='outbound',
            telegram_user_id=0  # Еще не знаем user_id
        )

        if not can_add:
            error_msg = (
                f"Не могу добавить контакт: {reason}. "
                f"Исходящие лимиты: {contact_manager.OUTBOUND_MAX_PER_HOUR}/час, "
                f"{contact_manager.OUTBOUND_MAX_PER_DAY}/день"
            )
            logger.warning(f"⚠️ {error_msg}")
            return False, error_msg

        # Можем добавлять - продолжить...
        # (Здесь нужна логика поиска пользователя по username/phone
        #  и добавления через contact_manager.add_to_contacts_with_protection)

    # ... остальная логика отправки ...
```

---

### 3. Добавление Admin Endpoint

**Файл:** `src/api_server.py`

**Новый endpoint для мониторинга:**

```python
# src/api_server.py

from src.monitoring import ContactAddMonitor
from src.contact_manager import contact_manager

@app.get("/admin/contact-health")
async def get_contact_health(
    current_user: dict = Depends(admin_required)
):
    """
    Здоровье системы добавления контактов

    Требует: admin роль

    Returns:
        {
            "circuit_breaker": {
                "state": "CLOSED" | "OPEN" | "HALF_OPEN",
                "failure_count": int,
                "cooldown_until": str | null,
                "recent_adds_count": int
            },
            "health": {
                "hour": { ... },
                "day": { ... }
            }
        }
    """
    health = await ContactAddMonitor.check_health()

    return {
        "circuit_breaker": {
            "state": contact_manager.circuit_breaker._state,
            "failure_count": contact_manager.circuit_breaker._failure_count,
            "cooldown_until": (
                contact_manager.circuit_breaker._cooldown_until.isoformat()
                if contact_manager.circuit_breaker._cooldown_until
                else None
            ),
            "recent_adds_count": len(contact_manager.circuit_breaker._recent_adds),
            "max_burst": contact_manager.circuit_breaker.MAX_BURST,
            "max_failures": contact_manager.circuit_breaker.MAX_FAILURES,
            "cooldown_seconds": contact_manager.circuit_breaker.COOLDOWN_SECONDS
        },
        "limits": {
            "inbound": {
                "per_hour": contact_manager.INBOUND_MAX_PER_HOUR,
                "per_day": contact_manager.INBOUND_MAX_PER_DAY
            },
            "outbound": {
                "per_hour": contact_manager.OUTBOUND_MAX_PER_HOUR,
                "per_day": contact_manager.OUTBOUND_MAX_PER_DAY
            }
        },
        "health": health
    }
```

---

## Deployment Checklist

### Шаг 1: Создать файлы

- [ ] `src/contact_manager.py` - ContactManager + CircuitBreaker
- [ ] `src/monitoring.py` - ContactAddMonitor
- [ ] Добавить `ContactAddLog` в `src/database.py`

### Шаг 2: Миграция БД

```bash
# Создать миграцию
python3 -m alembic revision --autogenerate -m "add_contact_add_log_table"

# Проверить созданную миграцию
# Убедиться что таблица contact_add_log и индексы создаются

# Применить миграцию
python3 -m alembic upgrade head
```

### Шаг 3: Модификация существующего кода

- [ ] Модифицировать `src/telegram_client.py:_handle_incoming_message`
- [ ] Модифицировать `src/bridge.py:handle_incoming_message` (добавить параметр phone)
- [ ] Модифицировать `src/bridge.py:send_message_from_crm` (добавить проверку лимитов)
- [ ] Добавить endpoint `/admin/contact-health` в `src/api_server.py`

### Шаг 4: Тестирование

**Тест 1: Входящее сообщение (inbound)**

1. Пользователь пишет в Telegram
2. Проверить логи: "Телефон не доступен, пробуем добавить в контакты"
3. Проверить логи: "Контакт добавлен, phone: +..."
4. Проверить БД: `SELECT * FROM contact_add_log WHERE direction='inbound'`
5. Проверить Bitrix24: контакт создан с телефоном

**Тест 2: Circuit Breaker (burst limit)**

```python
# Создать тестовый скрипт для проверки burst limit
for i in range(10):
    await contact_manager.add_to_contacts_with_protection(...)

# Ожидаем:
# - После 5 попыток - circuit breaker OPEN
# - Логи: "🚨 CIRCUIT BREAKER: Burst limit exceeded!"
```

**Тест 3: Health Endpoint**

```bash
curl -u admin:password http://localhost:8000/admin/contact-health

# Ожидаем JSON:
# {
#   "circuit_breaker": {"state": "CLOSED", ...},
#   "limits": {...},
#   "health": {...}
# }
```

### Шаг 5: Мониторинг в production

- [ ] Настроить алерты на `/admin/contact-health` endpoint
- [ ] Мониторить логи на предмет "CIRCUIT BREAKER OPEN"
- [ ] Настроить дашборд для `contact_add_log` таблицы
- [ ] Добавить алерты на failure_rate > 30%

---

## Безопасность и Best Practices

### ✅ DO (Что НУЖНО делать)

1. **Всегда используйте ContactManager**
   - НЕ вызывайте `AddContactRequest` напрямую
   - Используйте только `contact_manager.add_to_contacts_with_protection()`

2. **Всегда проверяйте direction**
   - Inbound (клиент пишет) = `direction='inbound'`
   - Outbound (мы пишем) = `direction='outbound'`

3. **Мониторьте health endpoint**
   - Проверяйте `/admin/contact-health` минимум раз в час
   - Настройте алерты на circuit breaker OPEN

4. **Логируйте source**
   - `source='incoming_message'` - входящие Telegram
   - `source='crm_request'` - запросы из CRM
   - `source='manual_admin'` - ручное добавление админом

5. **Обрабатывайте privacy errors как INFO**
   - `user_privacy` ошибка - это нормально
   - НЕ считайте это failure для circuit breaker

### ❌ DON'T (Что НЕ НУЖНО делать)

1. **НЕ вызывайте AddContactRequest напрямую**
   ```python
   # ❌ ПЛОХО
   await client(functions.contacts.AddContactRequest(...))

   # ✅ ХОРОШО
   await contact_manager.add_to_contacts_with_protection(...)
   ```

2. **НЕ игнорируйте circuit breaker**
   ```python
   # ❌ ПЛОХО - обход защиты
   if contact_manager.circuit_breaker.is_open():
       contact_manager.circuit_breaker._state = "CLOSED"  # ОПАСНО!
   ```

3. **НЕ изменяйте лимиты в рантайме без тестирования**
   ```python
   # ❌ ПЛОХО
   contact_manager.INBOUND_MAX_PER_HOUR = 1000  # Слишком высоко!
   ```

4. **НЕ удаляйте записи из `contact_add_log`**
   - Это нарушит rate limiting
   - Для очистки старых данных используйте retention policy

---

## Troubleshooting

### Проблема: Circuit breaker постоянно открывается

**Симптомы:**
- Логи: "🚨 CIRCUIT BREAKER ОТКРЫТ" каждые 5 минут
- `/admin/contact-health` показывает `state: "OPEN"`

**Причины:**
1. Реальные ошибки от Telegram (flood limit достигнут)
2. Privacy настройки большинства пользователей
3. Неправильный username/user_id

**Решение:**
1. Проверить `contact_add_log` - какие ошибки:
   ```sql
   SELECT * FROM contact_add_log
   WHERE success = false
   ORDER BY created_at DESC
   LIMIT 20;
   ```

2. Если много `user_privacy` - это нормально, игнорировать
3. Если `flood` ошибки - снизить лимиты или увеличить COOLDOWN_SECONDS

---

### Проблема: Телефоны не извлекаются

**Симптомы:**
- Контакты добавляются (`success=true`)
- Но `phone_number = None`

**Причины:**
1. Пользователь скрыл номер в настройках приватности
2. Слишком быстро запрашиваем после добавления (нужна задержка)

**Решение:**
1. Увеличить задержку после `AddContactRequest`:
   ```python
   await asyncio.sleep(2)  # Было 1, стало 2
   ```

2. Это нормально - не все пользователи раскрывают номер

---

### Проблема: Hourly limit достигнут для inbound

**Симптомы:**
- Логи: "Hourly limit reached for inbound: 50/50"
- Входящие сообщения не обрабатываются

**Причины:**
- Слишком много новых входящих чатов за час

**Решение:**
1. Проверить не спам ли это:
   ```sql
   SELECT COUNT(*), DATE_TRUNC('hour', created_at) as hour
   FROM contact_add_log
   WHERE direction = 'inbound'
   GROUP BY hour
   ORDER BY hour DESC;
   ```

2. Если легитимный трафик - увеличить `INBOUND_MAX_PER_HOUR`
3. Если спам - добавить антиспам проверки в `_handle_incoming_message`

---

## Метрики и Мониторинг

### Prometheus Metrics (опционально)

Если используете Prometheus, добавить метрики:

```python
# src/contact_manager.py

from prometheus_client import Counter, Gauge

contact_add_total = Counter(
    'telegram_contact_add_total',
    'Total contact add attempts',
    ['direction', 'success']
)

circuit_breaker_state = Gauge(
    'telegram_contact_circuit_breaker_state',
    'Circuit breaker state (0=CLOSED, 1=OPEN, 2=HALF_OPEN)'
)

# В методе add_to_contacts_with_protection:
if success:
    contact_add_total.labels(direction=direction, success='true').inc()
else:
    contact_add_total.labels(direction=direction, success='false').inc()

# Обновлять gauge:
state_map = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
circuit_breaker_state.set(state_map[self.circuit_breaker._state])
```

---

## Changelog

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 2026-01-20 | Первая версия - полная архитектура защиты |

---

## TODO / Будущие улучшения

- [ ] Добавить алерты через Telegram Bot API (уведомления админу)
- [ ] Реализовать graceful degradation (если circuit breaker открыт долго)
- [ ] Добавить metrics в Prometheus
- [ ] Реализовать dashboard для Grafana
- [ ] Добавить A/B тестирование разных лимитов
- [ ] Реализовать автоматическую адаптацию лимитов на основе ошибок
- [ ] Добавить whitelist для VIP контактов (обход лимитов)

---

## References

- [Telegram Business Features](https://telegram.org/tour/business)
- [Telethon Documentation - Contacts](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.users.UserMethods.add_contact)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Rate Limiting Best Practices](https://cloud.google.com/architecture/rate-limiting-strategies-techniques)

---

**Последнее обновление:** 2026-01-20
**Автор:** Telegram CRM Development Team
**Статус:** 📋 Ready for Implementation
