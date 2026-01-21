# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Contact Manager System (2026-01-20)

Comprehensive system for safe phone number extraction from Telegram users with multi-layer protection to prevent account bans.

**New Components:**
- `src/contact_manager.py` - Core Contact Manager with Circuit Breaker and rate limiting
- `src/monitoring.py` - Health monitoring for contact addition system
- `contact_add_log` table - Database audit trail for all contact addition attempts
- Migration: `20260120_add_contact_add_log.py` - Creates contact_add_log table with indexes

**Features:**
- **Circuit Breaker Pattern**: Automatic shutoff after 3 consecutive failures with 5-minute cooldown
- **Burst Detection**: Maximum 5 contact additions per 60 seconds to prevent infinite loops
- **Direction-Aware Rate Limiting**:
  - Inbound (customer writes first): 50/hour, 150/day (safer, higher limits)
  - Outbound (we write first): 3/hour, 10/day (risky, strict limits)
- **8-Layer Protection System**:
  1. Circuit Breaker state check
  2. Burst limit detection (5/minute)
  3. Rate limit enforcement (direction-specific)
  4. Already-added verification
  5. Telegram API call with 10s timeout
  6. Error categorization (flood/privacy/timeout)
  7. Database audit logging
  8. Circuit Breaker state updates
- **Automatic Phone Extraction**: When incoming messages arrive without phone numbers, system automatically attempts to add user to contacts
- **Health Monitoring**: Admin endpoint `/api/admin/contact-health` shows Circuit Breaker state, limits, and statistics

**Integration Points:**
- `src/telegram_client.py` - Automatic phone extraction in `_handle_incoming_message`
- `src/bridge.py` - Updated to accept and forward `phone` parameter to CRM
- `src/api_server.py` - New admin endpoint for health monitoring

**Testing:**
- 16 unit tests in `tests/test_contact_manager.py`
- Coverage: Circuit Breaker behavior, burst detection, rate limiting, concurrency

**Documentation:**
- Updated `CLAUDE.md` - Added Contact Manager to Core Components and Critical Development Notes
- Updated `API.md` - Documented `/api/admin/contact-health` endpoint

**Error Handling:**
- Flood errors immediately open Circuit Breaker
- Privacy errors don't count as failures (user choice)
- Timeout errors count as failures
- All attempts logged to database for compliance and debugging

**Benefits:**
- Prevents Telegram account bans from aggressive contact additions
- Enables better CRM contact enrichment with phone numbers
- Provides audit trail for compliance
- Self-healing system with automatic cooldown and recovery

---

## Template for future entries

### Added
- New features

### Changed
- Changes in existing functionality

### Deprecated
- Soon-to-be removed features

### Removed
- Removed features

### Fixed
- Bug fixes

### Security
- Vulnerability fixes
