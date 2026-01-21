# План миграции дизайна UI (multi-account console)

Цель: перенести новый дизайн из `stitch_multi_account_telegram_crm_console/code.html` в рабочий UI без потери функций, кнопок и связей.

---

## 1) Инвентаризация UI-функций (что обязано работать)

### Основной статус и системные действия
- Статус соединения Telegram (`/api/ui/status`)
- Статус авторизации (authorized + user)
- Статус сессии (session path, updated_at)
- Антиспам-лимиты (messages/hour, new chats/day, delay)
- Кнопки: `Refresh`, `Logout`
- Блок онбординга (авторизация/пустые чаты)

### Чаты и поиск
- Список чатов (`/api/ui/chats`)
- Поиск по чатам
- Фильтры: All / Unread / New / Errors
- Счётчик чатов
- Клик на чат → загрузка сообщений и контакт-карты
- Очистка активного чата

### Сообщения
- История сообщений (`/api/ui/messages`)
- Рендер inbound/outbound, статус доставки (queued/sent/failed)
- Отправка в выбранный чат (`/api/ui/send`)
- Отправка в новый чат (`/api/ui/send`)
- Retry последнего сообщения
- Горячие клавиши (Ctrl/⌘ + Enter, Ctrl/⌘ + K, Ctrl/⌘ + Shift + N, Esc)

### Контактная карточка
- Имя, username, phone, chat id
- Теги, заметки
- Consent / Opt-out
- Quiet hours + timezone
- Сохранение профиля (`/api/ui/chat/{chat_id}/profile`)
- История взаимодействий (summary + recent)

### Журнал событий
- Список событий (`/api/ui/events`)
- SSE поток (`/api/ui/stream`) — ui_event/ui_message
- Кнопка Refresh

### Multi-account UI (пока визуально)
- Сайдбар аккаунтов (аватар/телефон/статус/лимиты)
- Свернуть/развернуть сайдбар аккаунтов
- Переключение (визуальное; backend позже)

---

## 2) Карта обязательных элементов (id → назначение)

### Статусы/шапка
- `status-connection`, `status-connection-meta`
- `status-auth`, `status-user`
- `status-session`, `status-session-meta`
- `status-limits`, `status-limits-meta`
- `btn-refresh`, `btn-logout`

### Чаты/фильтры
- `chat-list`, `chat-search`, `chat-count`, `empty-chats`
- `chat-filters` (кнопки с `data-filter`)

### Диалог
- `message-list`, `active-title`, `active-meta`
- `message-text`, `btn-send`, `btn-retry`, `send-result`, `send-hint`
- `btn-clear`

### Новый чат
- `new-username`, `new-phone`, `new-message`
- `btn-send-new`, `new-result`

### Контакт
- `btn-refresh-contact`, `btn-save-profile`
- `contact-name`, `contact-username`, `contact-id`, `contact-phone`
- `contact-tags`, `contact-notes`
- `contact-consent`, `contact-optout`
- `quiet-start`, `quiet-end`, `contact-timezone`
- `profile-result`
- `history-total`, `history-inbound`, `history-outbound`, `history-last-in`, `history-last-out`
- `recent-list`

### Онбординг
- `auth-banner`, `onboarding`, `onboarding-empty`, `btn-recheck`

### Events
- `event-list`, `btn-refresh-events`

### Accounts (layout)
- `btn-collapse-accounts`
- `account-name`, `account-phone`, `account-status`, `account-limits`
- `account-list`, `empty-accounts`

---

## 3) План переноса разметки

1. Взять структуру из `stitch_multi_account_telegram_crm_console/code.html`.
2. Вставить в `static/ui.html`.
3. Сохранить все id из раздела 2.
4. Все новые кнопки добавить к JS:
   - Refresh → `btn-refresh`
   - Logout → `btn-logout`
   - Toggle Theme → отдельный обработчик (см. раздел 5)
   - Search/More → пока без логики (добавить `data-action`, чтобы не потерялись)
5. Удалить сторонние CDN, если переходим на локальные стили.

---

## 4) План переноса стилей

Вариант A (быстро): оставить Tailwind CDN.
- Минус: внешний доступ, не prod-ready.

Вариант B (prod-ready): переписать в `static/styles.css`.
- Перенести базовые цвета/типографику.
- Сохранить текущие UI-переменные (`:root`) и расширить, если нужно.
- Все новые классы из дизайна задокументировать.

---

## 5) JS-логика и новые элементы

### Обязательные действия
- `btn-refresh` → `refreshStatus()`, `loadChats()`, `loadMessages()`, `loadEvents()`
- `btn-logout` → `logout()`
- `btn-send` → `sendToSelected()`
- `btn-send-new` → `sendNewChat()`
- `btn-retry` → `retryLast()`
- `btn-clear` → очистка активного чата
- `btn-save-profile` → `saveProfile()`
- `btn-refresh-contact` → `loadChatDetails()`
- `btn-refresh-events` → `loadEvents()`
- `btn-recheck` → `refreshStatus()` + `loadChats()`
- `btn-collapse-accounts` → toggle классов body + localStorage

### Новые элементы из дизайна (без backend)
- Toggle Theme: `document.documentElement.classList.toggle('dark')` или класс на `body`.
- Quick Replies: маппинг на шаблоны (из existing templates).
- Attach/Emoji: пока без логики → оставить disabled/placeholder.

---

## 6) SSE и обновление UI

Проверить, что новые элементы не ломают:
- `/api/ui/stream` события (`ui_message`, `ui_event`)
- Автообновление чатов/сообщений/событий
- Статусы доставки (queued/sent/failed)

---

## 7) Accessibility и UX

- Все кнопки имеют `title`/`aria-label`.
- Фокус и tab-навигация для чатов/поиска.
- Empty-states отображаются корректно.
- Mobile layout: сайдбары уходят в стек.

---

## 8) Минификация и релиз

- Обновить `static/styles.css` и `static/app.js`.
- Запустить `python3 scripts/minify_assets.py`.
- Убедиться, что `static/ui.html` подключает `*.min.css/js`.

---

## 9) Проверка (ручная)

- `/ui/auth` авторизация.
- `/ui` загрузка: статусы + список чатов.
- Поиск + фильтры.
- Отправка в активный чат и в новый.
- Retry, logout.
- Обновление событий и SSE.
- Свернуть/развернуть аккаунты.

---

## 10) Риски и блокеры

- Потеря `id` → ломает JS.
- Tailwind CDN → блок сети/политики безопасности.
- Иконки/шрифты по CDN → недоступность в offline/prod.
- Несовместимость темной темы с реальными данными (контраст).
