# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog],
and this project adheres to [Semantic Versioning].

## [Unreleased]

- /

## [0.2.2] - 2025-09-23

### Fixed

- Removed VerificationHeaders defaults so it throws ValidationError as expected.

## [0.2.1] - 2025-09-23

### Fixed

- Webhook.handle_incoming() now properly unsubscribes from unhandled events, even when not using internal server.

## [0.2.0] - 2025-09-17

### Added

- Proper rate limit handler.
- Webhook.handle_incoming() now supports headers as raw dict too.
- Added 401 status_code error handling for token_validate.

### Changed

- Improved object models.
- Improved status_code handling.
- Improved Webhook shutting down.

### Fixed

- Socketify server loggers didn't worked.

## [0.1.0] - 2025-09-16

- initial release

<!-- Links -->
[keep a changelog]: https://keepachangelog.com/en/1.0.0/
[semantic versioning]: https://semver.org/spec/v2.0.0.html
