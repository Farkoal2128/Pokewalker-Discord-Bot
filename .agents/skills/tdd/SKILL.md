---
name: tdd
description: Enforce RED → GREEN → REFACTOR → VERIFY for meaningful behavior changes.
---

# TDD

## RED
Identify one required observable behavior, write the smallest meaningful test, run it before production implementation, and confirm it fails for the expected behavioral reason. Record command and failure.

## GREEN
Make the minimum reasonable production change satisfying the test and governing contract. Re-run the focused test.

## REFACTOR
Improve structure only after GREEN, preserving observable behavior and keeping focused tests green.

## VERIFY
Run applicable contract, integration, regression, type, lint, format, build, security, render, and e2e checks.

Never delete, skip, weaken, or rewrite a valid failing test merely to obtain GREEN. If RED is technically impossible or unsafe, document why and obtain an explicit exception with alternative evidence.
