# Mobile / Android release report

- Package: `KARDS-AUTO-Mobile-v0.2.0.zip`
- APK: code57 / versionName 0.8.31
- KARDS: 1.60.27292/code2703
- Verification system: runtime-test emulator
- Scope: casual mode

## Verification

The code57 run completed five consecutive casual matches: 5/5 wins, 330 battle inputs accepted and completed, and result/return confirmation on every match. Twelve ordinary action outcomes remained unknown without stopping the APK. The observer read-retry fix raises the bounded consecutive read-failure threshold to six and backs off for 1–5 seconds before retrying.

The package does not claim physical-phone, host-free, or complete disconnect/reconnect validation. The PC client and its validation are maintained separately.
