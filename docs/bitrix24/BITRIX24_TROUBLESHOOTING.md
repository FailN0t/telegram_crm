# Bitrix24 Open Channels - Troubleshooting Guide

Подробное руководство по решению проблем при интеграции Bitrix24 Open Channels с Telegram CRM.

Этот документ описывает все проблемы, с которыми мы столкнулись при реализации интеграции, и способы их решения.

---

## Оглавление

1. [Проблема #1: OAuth Flow для локальных приложений](#проблема-1-oauth-flow-для-локальных-приложений)
2. [Проблема #2: Разные форматы токенов от Bitrix24](#проблема-2-разные-форматы-токенов-от-bitrix24)
3. [Проблема #3: Токены не сохраняются в БД](#проблема-3-токены-не-сохраняются-в-бд)
4. [Проблема #4: Белый экран при установке](#проблема-4-белый-экран-при-установке)
5. [Проблема #5: ICON_REQUIRED ошибка](#проблема-5-icon_required-ошибка)
6. [Проблема #6: NO_PLACEMENT_HANDLER ошибка](#проблема-6-no_placement_handler-ошибка)
7. [Итоговое правильное решение](#итоговое-правильное-решение)

---

## Проблема #1: OAuth Flow для локальных приложений

### Что не работало

Изначально мы реализовали стандартный OAuth 2.0 flow с двумя отдельными endpoints:
- `/api/bitrix24/oauth/start` - редирект на Bitrix24
- `/api/bitrix24/oauth/callback` - получение `code` и обмен на токены

**Ошибка:**
```
Ошибка: отсутствуют данные авторизации
Bitrix24 не передал ни code, ни токены авторизации
```

### Почему не работало

Bitrix24 для **локальных приложений** работает по-другому, чем стандартный OAuth 2.0:

1. **Обычный OAuth 2.0 (то что мы реализовали):**
   ```
   GET /api/bitrix24/oauth/start
     → Redirect to Bitrix24
     → User authorizes
     → Redirect to /api/bitrix24/oauth/callback?code=xxx
     → Exchange code for tokens via POST to /oauth/token
   ```

2. **Bitrix24 локальное приложение (правильный способ):**
   ```
   User clicks "Install" in Bitrix24
     → Bitrix24 sends POST to handler URL
     → POST contains tokens DIRECTLY (no code exchange needed)
     → Application saves tokens and confirms installation
   ```

### Исследование

Изучили проект `yclients-bitrix` и обнаружили:
- Используется endpoint `/bitrix-app/install`
- Bitrix24 вызывает его напрямую при установке
- Токены передаются сразу в POST-запросе

Документация Bitrix24 также указывает на событие **ONAPPINSTALL**, которое срабатывает при установке локального приложения.

### Решение

Создали универсальный endpoint `/api/bitrix24/install`, который:
1. Обрабатывает как GET, так и POST запросы
2. Принимает токены напрямую (ONAPPINSTALL)
3. Может работать и с OAuth code flow (на будущее)

```python
@app.api_route("/api/bitrix24/install", methods=["GET", "POST"], tags=["Bitrix24"])
async def bitrix24_install_app(request: Request, code: str = None, domain: str = None):
    # Универсальная обработка установки
```

---

## Проблема #2: Разные форматы токенов от Bitrix24

### Что не работало

После добавления endpoint `/api/bitrix24/install`, Bitrix24 отправлял POST-запрос, но:

**Логи показывали:**
```
📥 Bitrix24 POST form keys: ['AUTH_ID', 'AUTH_EXPIRES', 'REFRESH_ID', 'SERVER_ENDPOINT', ...]
📥 Bitrix24 parsed: access_token=False, refresh_token=False
```

Код искал параметры `auth[access_token]` и `auth[refresh_token]`, но их не было!

### Почему не работало

Bitrix24 передает токены в **разных форматах** в зависимости от типа вызова:

1. **ONAPPINSTALL событие** (при установке через событие):
   ```
   auth[access_token] = xxx
   auth[refresh_token] = yyy
   ```

2. **Frame placement call** (при открытии приложения в iframe):
   ```
   AUTH_ID = xxx
   REFRESH_ID = yyy
   AUTH_EXPIRES = 3600
   SERVER_ENDPOINT = https://oauth.bitrix24.tech/rest/
   APP_SID = ...
   ```

Наш код обрабатывал только первый формат!

### Исследование

Добавили детальное логирование:
```python
for key, value in form_dict.items():
    if 'TOKEN' in key.upper() or 'AUTH' in key.upper():
        logger.info(f"   {key} = {str(value)[:20]}...{str(value)[-10:]}")
    else:
        logger.info(f"   {key} = {value}")
```

Обнаружили что Bitrix24 отправляет:
- `AUTH_ID` вместо `auth[access_token]`
- `REFRESH_ID` вместо `auth[refresh_token]`
- `AUTH_EXPIRES` для времени жизни токена

### Решение

Добавили обработку обоих форматов:

```python
# ONAPPINSTALL формат: auth[access_token], auth[refresh_token]
access_token = form_data.get("auth[access_token]")
refresh_token = form_data.get("auth[refresh_token]")

# Frame placement формат: AUTH_ID, REFRESH_ID
if not access_token:
    access_token = form_data.get("AUTH_ID")
if not refresh_token:
    refresh_token = form_data.get("REFRESH_ID")

# AUTH_EXPIRES
auth_expires = form_data.get("AUTH_EXPIRES")
if auth_expires:
    try:
        auth_expires = int(auth_expires)
    except (ValueError, TypeError):
        auth_expires = 3600
```

Также добавили обработку трёх типов вызовов:
1. **Frame call с токенами** - сохраняем токены
2. **Frame call без токенов** (только APP_SID) - показываем UI
3. **OAuth code flow** - обмениваем code на токены

---

## Проблема #3: Токены не сохраняются в БД

### Что не работало

После успешного получения токенов видели ошибку:

```
⚠️ Ошибка сохранения Bitrix24 токенов: {
  'BITRIX24_ACCESS_TOKEN': 'unsupported_setting',
  'BITRIX24_REFRESH_TOKEN': 'unsupported_setting',
  'BITRIX24_TOKEN_EXPIRES_AT': 'unsupported_setting'
}
```

### Почему не работало

Настройки `BITRIX24_ACCESS_TOKEN`, `BITRIX24_REFRESH_TOKEN` и `BITRIX24_TOKEN_EXPIRES_AT` **не были добавлены** в словарь `ALLOWED_SETTINGS` в файле `src/app_settings.py`.

Функция `update_settings_overrides()` проверяет, что настройка есть в разрешённом списке, и если её там нет - возвращает ошибку `unsupported_setting`.

### Решение

Добавили настройки Bitrix24 в `src/app_settings.py`:

```python
ALLOWED_SETTINGS = {
    # ... существующие настройки ...

    "BITRIX24_ACCESS_TOKEN": {
        "type": str,
        "description": "Bitrix24 access token (OAuth).",
        "requires_restart": False,
    },
    "BITRIX24_REFRESH_TOKEN": {
        "type": str,
        "description": "Bitrix24 refresh token (OAuth).",
        "requires_restart": False,
    },
    "BITRIX24_TOKEN_EXPIRES_AT": {
        "type": str,
        "description": "Bitrix24 token expiry timestamp (ISO8601).",
        "requires_restart": False,
    },
}
```

После этого токены стали успешно сохраняться:
```
✅ Admin settings updated: BITRIX24_ACCESS_TOKEN, BITRIX24_REFRESH_TOKEN, BITRIX24_TOKEN_EXPIRES_AT
```

---

## Проблема #4: Белый экран при установке

### Что не работало

После установки приложения в Bitrix24 пользователь видел **белый экран** вместо подтверждения.

### Почему не работало

Код возвращал `RedirectResponse` на портал Bitrix24:

```python
# Старый код
return RedirectResponse(url=f"https://{actual_domain}/")
```

Но приложение открывается **в iframe** внутри Bitrix24, поэтому редирект не работает корректно - браузер пытается сделать redirect внутри iframe, что приводит к белому экрану.

### Решение

Заменили `RedirectResponse` на `HTMLResponse` с красивой страницей подтверждения:

```python
return HTMLResponse(
    content="""
    <html>
        <head>
            <title>Telegram CRM установлен</title>
            <meta charset="utf-8">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                    max-width: 600px;
                    margin: 40px auto;
                    padding: 20px;
                    text-align: center;
                }
                .success { color: #4CAF50; font-size: 48px; }
                h1 { color: #333; }
                p { color: #666; line-height: 1.6; }
            </style>
        </head>
        <body>
            <div class="success">✓</div>
            <h1>Приложение успешно установлено!</h1>
            <p>Telegram CRM готов к работе.</p>
            <p>Используйте API endpoints для отправки сообщений через Telegram.</p>
        </body>
    </html>
    """,
    status_code=200
)
```

Теперь пользователь видит красивую страницу подтверждения прямо в Bitrix24!

---

## Проблема #5: ICON_REQUIRED ошибка

### Что не работало

При регистрации коннектора Open Channels получали ошибку:

```
❌ Bitrix24 API ошибка: ICON_REQUIRED - Не указана иконка коннектора
```

### Почему не работало

Код передавал **пустую строку** в параметре `ICON.DATA_IMAGE`:

```python
# Старый код
params = {
    "ID": connector_id,
    "NAME": name,
    "ICON": {
        "DATA_IMAGE": icon_url or ""  # Пустая строка!
    }
}
```

Bitrix24 требует, чтобы иконка коннектора была обязательно указана.

### Решение

Добавили SVG иконку Telegram в base64 формате:

```python
# Telegram logo SVG в base64
default_icon = (
    "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDgiIGhlaWdodD0iNDgiIH..."
)

params = {
    "ID": connector_id,
    "NAME": name,
    "ICON": {
        "DATA_IMAGE": icon_url or default_icon  # Используем default иконку
    }
}
```

SVG представляет собой синий круг с белым значком Telegram (самолётик).

После этого коннектор успешно зарегистрировался:
```
✅ Коннектор telegram_mtproto зарегистрирован
```

---

## Проблема #6: NO_PLACEMENT_HANDLER ошибка

### Что не работало

После исправления проблемы с иконкой, получили новую ошибку:

```
❌ Bitrix24 API ошибка: NO_PLACEMENT_HANDLER - Не удалось получить URL обработчика встраивания
```

### Почему не работало

**Первая попытка** - передавали пустую строку:
```python
params = {
    ...
    "PLACEMENT_HANDLER": ""
}
```

**Вторая попытка** - вообще убрали параметр:
```python
params = {
    ...
    # PLACEMENT_HANDLER не указываем - он опционален
}
```

Но оказалось, что `PLACEMENT_HANDLER` **обязателен** для коннектора Open Channels!

### Почему обязателен

`PLACEMENT_HANDLER` - это URL страницы настроек коннектора, которая отображается когда администратор заходит в настройки канала связи в Bitrix24.

### Решение

**Шаг 1:** Создали endpoint для placement handler:

```python
@app.get("/api/bitrix24/openlines/placement", tags=["Bitrix24"])
async def bitrix24_openlines_placement(request: Request):
    """
    Placement handler для Open Channels коннектора

    Отображает UI страницу настроек коннектора в Bitrix24
    """
    return HTMLResponse(
        content="""
        <html>
            <head>
                <title>Telegram MTProto Connector</title>
                <meta charset="utf-8">
                ...
            </head>
            <body>
                <h1>Telegram MTProto Connector</h1>
                <div class="status">
                    <div class="status-icon">✓</div>
                    <strong>Коннектор активен</strong>
                </div>
                ...
            </body>
        </html>
        """,
        status_code=200
    )
```

**Шаг 2:** Добавили параметр `placement_handler_url` в функцию регистрации:

```python
async def register_connector(
    self,
    connector_id: str = "telegram_mtproto",
    name: str = "Telegram MTProto",
    icon_url: Optional[str] = None,
    placement_handler_url: Optional[str] = None  # Новый параметр
) -> bool:
    ...
    params = {
        "ID": connector_id,
        "NAME": name,
        "ICON": {
            "DATA_IMAGE": icon_url or default_icon
        }
    }

    # Добавляем PLACEMENT_HANDLER если указан
    if placement_handler_url:
        params["PLACEMENT_HANDLER"] = placement_handler_url
```

**Шаг 3:** Передали URL при вызове:

```python
host = request.headers.get('host', 'localhost')
setup_result = await crm_client.setup_open_channels(
    connector_id=settings.BITRIX24_CONNECTOR_ID,
    connector_name=settings.BITRIX24_CONNECTOR_NAME,
    webhook_url=f"https://{host}/api/webhook/bitrix24/openlines",
    line_id=settings.BITRIX24_LINE_ID,
    placement_handler_url=f"https://{host}/api/bitrix24/openlines/placement"  # Новый!
)
```

После этого всё заработало:
```
✅ Коннектор telegram_mtproto зарегистрирован
✅ Коннектор активирован на линии 0
✅ События зарегистрированы
```

---

## Итоговое правильное решение

### Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        Bitrix24 Portal                          │
│                                                                 │
│  1. User clicks "Install"                                       │
│     ↓                                                           │
│  2. Bitrix24 sends POST to /api/bitrix24/install               │
│     Parameters: AUTH_ID, REFRESH_ID, AUTH_EXPIRES, DOMAIN      │
│     ↓                                                           │
│  3. Receives HTML confirmation page                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Your Server (telegram-crm)                 │
│                                                                 │
│  Endpoint: /api/bitrix24/install (POST/GET)                    │
│     ↓                                                           │
│  1. Parses AUTH_ID, REFRESH_ID from POST form                  │
│  2. Saves tokens to database (app_settings table)              │
│  3. Calls setup_open_channels()                                │
│     ↓                                                           │
│     a. Registers connector (with icon + placement handler)     │
│     b. Activates connector on line                             │
│     c. Registers webhook events                                │
│  4. Returns HTML confirmation page                             │
│                                                                 │
│  Endpoints created:                                            │
│  - /api/bitrix24/install (installation)                        │
│  - /api/bitrix24/openlines/placement (settings UI)            │
│  - /api/webhook/bitrix24/openlines (webhook handler)          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Ключевые файлы и изменения

#### 1. `src/api_server.py`

**Endpoint установки приложения:**
```python
@app.api_route("/api/bitrix24/install", methods=["GET", "POST"])
async def bitrix24_install_app(request: Request, ...):
    # 1. Парсим токены из POST (AUTH_ID/REFRESH_ID или auth[access_token])
    # 2. Сохраняем токены в БД
    # 3. Настраиваем Open Channels
    # 4. Возвращаем HTML подтверждение
```

**Placement handler:**
```python
@app.get("/api/bitrix24/openlines/placement")
async def bitrix24_openlines_placement(request: Request):
    # Возвращает HTML страницу с информацией о коннекторе
```

#### 2. `src/bitrix24_client.py`

**Регистрация коннектора:**
```python
async def register_connector(
    self,
    connector_id: str,
    name: str,
    icon_url: Optional[str] = None,
    placement_handler_url: Optional[str] = None
):
    # Telegram logo SVG в base64
    default_icon = "data:image/svg+xml;base64,..."

    params = {
        "ID": connector_id,
        "NAME": name,
        "ICON": {"DATA_IMAGE": icon_url or default_icon}
    }

    if placement_handler_url:
        params["PLACEMENT_HANDLER"] = placement_handler_url
```

**Сохранение токенов напрямую:**
```python
async def save_tokens_directly(
    self,
    access_token: str,
    refresh_token: Optional[str],
    domain: str,
    expires_in: int = 3600
):
    self.access_token = access_token
    self.refresh_token = refresh_token
    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
    await self._save_tokens()
```

#### 3. `src/app_settings.py`

**Добавлены настройки:**
```python
ALLOWED_SETTINGS = {
    ...
    "BITRIX24_ACCESS_TOKEN": {"type": str, ...},
    "BITRIX24_REFRESH_TOKEN": {"type": str, ...},
    "BITRIX24_TOKEN_EXPIRES_AT": {"type": str, ...},
}
```

### Настройки приложения в Bitrix24

| Параметр | Значение |
|----------|----------|
| **Тип приложения** | Серверное (обязательно!) |
| **Путь вашего обработчика** | `https://tg.example.com/api/bitrix24/install` |
| **Путь для первоначальной установки** | `https://tg.example.com/api/bitrix24/install` |
| **Права (scopes)** | `imconnector`, `crm`, `user` |

### Переменные окружения

```bash
CRM_PROVIDER=bitrix24
BITRIX24_DOMAIN=mycompany.bitrix24.ru
BITRIX24_CLIENT_ID=local.XXXXXXXX.YYYYYYYY
BITRIX24_CLIENT_SECRET=secret_key
BITRIX24_REDIRECT_URI=https://tg.example.com/api/bitrix24/install
BITRIX24_OPEN_CHANNELS_ENABLED=true
BITRIX24_CONNECTOR_ID=telegram_mtproto
BITRIX24_CONNECTOR_NAME=Telegram CRM
BITRIX24_LINE_ID=0
```

### Последовательность установки

1. **Запустить сервер:**
   ```bash
   docker-compose up -d
   ```

2. **Установить приложение в Bitrix24:**
   - Зайти в настройки приложения
   - Нажать "Установить"

3. **Bitrix24 автоматически:**
   - Отправит POST на `/api/bitrix24/install`
   - Передаст токены в параметрах `AUTH_ID`, `REFRESH_ID`

4. **Сервер автоматически:**
   - Сохранит токены в БД
   - Зарегистрирует коннектор Open Channels
   - Активирует коннектор на линии 0
   - Зарегистрирует webhook события

5. **Результат:**
   ```
   ✅ Bitrix24 приложение установлено
   ✅ Коннектор зарегистрирован
   ✅ Коннектор активирован
   ✅ События зарегистрированы
   ✅ Open Channels интеграция настроена
   ```

### Проверка работоспособности

**Проверка токенов в БД:**
```sql
SELECT key, value
FROM app_settings
WHERE key LIKE 'BITRIX24%TOKEN%';
```

**Проверка статуса коннектора:**
```bash
curl https://tg.example.com/api/bitrix24/openlines/status
```

**Проверка в Bitrix24:**
1. CRM → Контакты → Открыть контакт
2. Раздел "Открытые линии" или "Чаты"
3. Должен быть виден коннектор "Telegram CRM" с синей иконкой

---

## Выводы

### Что мы узнали

1. **Bitrix24 локальные приложения** работают не так, как стандартный OAuth 2.0
   - Токены передаются напрямую при установке
   - Не нужен отдельный code exchange flow
   - Используется событие ONAPPINSTALL

2. **Разные форматы токенов:**
   - ONAPPINSTALL: `auth[access_token]`, `auth[refresh_token]`
   - Frame placement: `AUTH_ID`, `REFRESH_ID`, `AUTH_EXPIRES`

3. **Обязательные параметры коннектора:**
   - `ICON.DATA_IMAGE` - иконка (можно SVG в base64)
   - `PLACEMENT_HANDLER` - URL страницы настроек

4. **Iframe vs Redirect:**
   - Приложение открывается в iframe
   - Нужно возвращать HTML, а не редирект
   - RedirectResponse не работает в iframe

5. **App Settings:**
   - Токены должны быть в `ALLOWED_SETTINGS`
   - Иначе получим `unsupported_setting` ошибку

### Правильный подход

✅ Один универсальный endpoint `/api/bitrix24/install` для всех типов установки
✅ Обработка разных форматов токенов (AUTH_ID и auth[access_token])
✅ HTML responses вместо redirects для iframe
✅ SVG иконка в base64 для коннектора
✅ PLACEMENT_HANDLER endpoint для настроек
✅ Автоматическая регистрация коннектора при установке
✅ Сохранение токенов в app_settings с проверкой ALLOWED_SETTINGS

---

## Полезные ссылки

- [Bitrix24 REST API Documentation](https://dev.1c-bitrix.ru/rest_help/)
- [Open Channels API](https://dev.1c-bitrix.ru/rest_help/scope_im/imconnector/)
- [Local Applications Guide](https://dev.1c-bitrix.ru/learning/course/index.php?COURSE_ID=99&LESSON_ID=2280)
- [OAuth 2.0 in Bitrix24](https://dev.1c-bitrix.ru/rest_help/general/oauth_keys.php)
