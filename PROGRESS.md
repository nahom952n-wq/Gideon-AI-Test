# Progress

Last updated: 2026-08-26

## Completed

- Fixed Telethon client creation from Flask request threads by constructing the client on the dedicated asyncio loop.
- Added Telegram two-step verification support:
  - Detects when an OTP requires a 2FA password.
  - Retrieves and displays the Telegram password hint.
  - Verifies the password without storing or logging it.
- Updated Gemini configuration:
  - Default model is `gemini-3.5-flash`.
  - Added the requested Gemini model recommendations.
  - Legacy `gemini-2.5-flash` configuration falls back to the new default.
- Fixed AI chat database grounding:
  - `ChatService._build_context()` now queries `Opportunity`.
  - Searches title, organization, country, summary, and keywords.
  - Includes title, organization, opportunity type, country, deadline, funding, and summary in context.
  - Uses a lazy model import to avoid circular imports.

## Validation

Python compilation passed for the changed Python files.

## Current stopping point

The requested fixes are implemented. The next useful step is an end-to-end manual test of Telegram 2FA and Gemini chat using valid local credentials.
