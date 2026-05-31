# QA Report — 动食日记 Fit01

**Date:** 2026-05-31  
**Target:** http://localhost:8080  
**Framework:** Flask + Vanilla JS  
**Duration:** 3 min (API-only, no browse binary)  

---

## Health Score

| Category | Score | Weight | Weighted |
|----------|-------|--------|----------|
| Console | N/A | 15% | — |
| Links | N/A | 10% | — |
| Visual | N/A | 10% | — |
| Functional | 75 | 20% | 15.0 |
| UX | N/A | 15% | — |
| Performance | 100 | 10% | 10.0 |
| Content | 100 | 5% | 5.0 |
| Accessibility | N/A | 15% | — |

**Estimated Score (API-only): ~75/100**  
*Browse binary not available — visual, console, and links not tested.*

---

## API Test Results

| # | Endpoint | Result | Details |
|---|----------|--------|---------|
| 1 | GET /api/user | ✅ PASS | Returns user data (nickname, weight, etc.) |
| 2 | POST /api/nutrition | ✅ PASS | BMR:1612, TDEE:2498, Protein:140g |
| 3 | GET /api/meals | ✅ PASS | Returns meals for date |
| 4 | GET /api/dishes | ✅ PASS | Returns saved dishes |
| 5 | GET /api/workouts | ✅ PASS | Returns workouts |
| 6 | GET /api/measurements | ✅ PASS | Returns measurements |
| 7 | POST /api/parse-food | ❌ FAIL | Gemini API key denied (403) |
| 8 | GET / | ✅ PASS | Serves HTML (22820 bytes) |

---

## Issues Found

### ISSUE-001 — Gemini API Key Denied (CRITICAL)
- **Severity:** Critical
- **Category:** Functional
- **Evidence:** `POST /api/parse-food` returns `{"error":"gemini failed"}`
- **Root Cause:** API key `AQ.Ab8RN6...` returns 403 PERMISSION_DENIED from Google
- **Impact:** AI food parsing and meal recommendations are completely broken
- **Fix:** Get a new API key from https://aistudio.google.com/app/apikey and set `GEMINI_API_KEY` env var

### ISSUE-002 — No visual/console testing (MEDIUM)
- **Severity:** Medium
- **Category:** QA Coverage
- **Impact:** Can't verify frontend rendering, JS errors, responsive layout
- **Fix:** Install gstack browse binary or open in browser for manual testing

---

## Summary
- **Total:** 2 issues (1 critical, 1 medium)
- **Blocked:** Browse binary not installed — cannot do visual / interactive testing
- **Action:** Get new Gemini API key, then re-run QA with browse
