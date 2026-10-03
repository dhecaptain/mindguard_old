# Adult Self-Service Delivery Report

Date: 2026-09-17

## 1. Changed / added files

### Frontend (new — self-service layer)
- `frontend/src/types/self.ts` — PlatformKey, VerificationStatus, AnalysisStatus,
  PlatformCredentialsSpec/PlatformSpec, SelfSocialAccount, AddAccountPayload,
  TrendInfo, TopPost, PlatformBreakdown, SocioeconomicSignal, Findings,
  SessionStatus/SessionProgress/PlatformProgress, AnalysisSession, VerifyResult.
- `frontend/src/api/self.ts` — getSelfPlatforms, getSocialAccounts,
  addSocialAccount, deleteSocialAccount, verifySocialAccount, analyzeSelfAll,
  analyzeSelfPlatform, getAnalysisSessions, getAnalysisSession.
- `frontend/src/lib/selfPlatformConfig.ts` — accountStage, stageMeta, canAnalyze,
  credentialNote, handleField, credentialFields, riskLevelTone,
  platformLabelByKey, formatDate/formatDateTime/formatElapsed (registry-driven).
- `frontend/src/store/selfStore.ts` — zustand store: loadCatalog (accounts +
  sessions + platforms in parallel), addAccount/removeAccount/verifyAccount,
  runAnalysis(targets?) with honest per-platform final mapping from
  `session.progress.platforms`.
- `frontend/src/components/self/{SelfStatusBadge,EmptyState,AccountCard,AnalysisRunner,FindingsPanel,SessionCard}.tsx`
- `frontend/src/pages/{AdultDashboardPage,AdultAccountsPage,AnalysisHistoryPage,AnalysisSessionPage}.tsx`

### Frontend (modified)
- `frontend/src/App.tsx` — `AdultPageRouter()` + `PageRouter` branch on
  `userCategory === 'adult'`; counsellor/admin switches untouched (additive diff).
- `frontend/src/components/layout/Sidebar.tsx` — `ADULT_STUDENT_NAV_ITEMS`
  (Analysis History inserted), `isAdult` flag; admin nav **label only** change
  (Consent → Consent Tracker, see §8).
- `frontend/src/store/uiStore.ts` — new PageKeys `self-history`, `self-session`.
- `frontend/src/store/index.ts` — exports useSelfStore.
- `frontend/src/types/index.ts` — UserInfo + `user_category?`, `onboarding_completed?`.
- `frontend/src/api/analysis.ts` — removed stale `analyzeSelfAccount` +
  `SelfAnalysisPayload` (wrong shape vs backend).

### Backend (modified this session)
- `backend/main.py` — `/api/auth/login` response now includes `user_category`
  (§8 regression fix).
- `backend/e2e/seed_db.py` — seeded staff accounts get
  `user_category = 'institution_managed'` so the onboarding gate is bypassed for
  e2e staff (§8 regression fix).

### Backend (superset, already green from earlier work — unchanged this session)
- `backend/services/self_analysis.py`, `backend/services/platform_registry.py`,
  `backend/database.py` (session persistence), `/api/self/*` endpoints,
  `backend/tests/test_self_analyze.py`, `alembic/versions/0010_adult_self_analysis.py`.

## 2. Adult capabilities delivered
- Adult-role workspace in the Sidebar (My Accounts, Analysis History) and
  `AdultPageRouter` routes (dashboard / my-accounts / self-history / self-session
  + shared student pages).
- Fully self-service: users connect their **own** accounts via guided per-platform
  forms and run analysis over their own connected accounts in one session.
- Real, persistent results via `/api/self/*` (analysis_sessions); dashboard stats
  derive only from actual sessions with findings.
- No UI path analyzes arbitrary third-party handles — ownership only.

## 3. Multi-account connection flow
- Platform picker grid showing every registered platform with a connected check.
- Guided form per platform: identifier field + example (from registry
  `identifier_example`), credential fields with “How to get your {label}” steps,
  capabilities / limitations / `requires_public` rendered from the backend
  registry — not hard-coded.
- Validation: per-field required, URL-only platforms require an http(s) URL
  (facebook enforces `https://`).
- Per-account lifecycle driven by backend states via `accountStage()`:
  not_connected → running → failed → analysed → verified → connected.
- Verify/Analyse/Re-analyse/Remove actions; remove is a destructive confirm.

## 4. Per-platform authentication requirements
- Full requirements come from `GET /api/self/platforms` (PLATFORM_SPECS):
  `handle_label`, `identifier_example`, `credential_fields` (secret fields +
  selectors), `instructions`, `capabilities`, `limitations`, `requires_public`,
  `analyzable`.
- `canAnalyze()` honors `analyzable: false` platforms — they surface honest
  “cannot be analysed” results rather than pretending.
- Credential type mapping: fields containing `password` render as password
  inputs; others as text; `server_key`-style single values render as a note.

## 5. Analysis response UI
- Runner: optimistic per-platform stage progression grounded in the registry
  `analyze_step_label`, then the **real** per-platform statuses
  (`ok` / `no_data` / `error` / `unsupported` + message) from
  `session.progress.platforms`.
- Honest final states only — `run.status` is strictly `complete | failed`; no
  fabricated percentages, no invented scores.
- FindingsPanel renders only real `findings` (overall risk, trend, top posts,
  per-platform distribution, keywords, insights, recommendations, `posts_analyzed`).
- `no_data` sessions explain why (private profile / no posts / unavailable
  source) and suggest the next action; partial sessions call out failed platforms.
- Re-run from the runner and per-account “Re-analyse”; failed platforms get
  their backend message and retry.

## 6. History / session detail
- Analysis History list: SessionCard with platform names, status/level badges,
  `posts_analysed`, started/completed times (real session rows).
- Session detail: header metadata (started/completed/platforms), status badge,
  per-platform status rows, insights, recommendations, no-data / partial
  explanation boxes, and an explicit “This is a historical report — not a live
  re-run” note.

## 7. Privacy / ownership verification
- Ownership enforced server-side: `/api/self/*` scopes to the authenticated
  user; third-party-handle analysis 404s (`test_self_social_ownership_enforced`
  green).
- No backend permission changes were needed to ship the UI; permissions.py
  untouched.
- Frontend hides any arbitrary-handle input; AddAccountPayload only carries the
  user’s own platform + credentials.
- PII-like fields (handles/credentials) handled via existing `api/client.ts`
  (JWT + CSRF + retry); no raw `fetch` in new code; no `any` in new code.

## 8. Tests run
- Backend (targeted, relevant):
  - `PYTHONPATH=..:. python3.13 -m pytest tests/test_self_analyze.py` → 7 passed.
  - `tests/test_self_analyze.py` + `product_architecture::test_self_social_ownership_enforced`
    + login/auth/onboarding selection → 9 passed.
- Frontend static: `npx tsc --noEmit --project tsconfig.app.json` → clean
  (0 errors). `npm run build` (tsc -b + vite) → green (chunk-size warning
  pre-existing).
- End-to-end (Playwright, `cd frontend && npx playwright test`):
  - **consent-workflow (3 tests): PASS** — roster upload dispatch, parent
    ACCEPTED flip, adult DECLINED + 403 analysis block.
  - **marketing-demo (1 test): FAIL (pre-existing)** — axe color-contrast on
    `.mg-eyebrow` (marketing app, untouched; `#3f8a6c` on `#f7f8f5`, 3.89:1 <
    4.5:1 at 11.5px).
- Full backend suite note: 270 passed, 44 errors + 8 failures are **pre-existing
  test-harness fragility** — module-scoped `TestClient(app)` startup re-runs
  Alembic `0009`’s `op.create_table('analysis_sessions')` against a DB that
  already has the table (conftest documents the same collision for `db`
  fixture users; TestClient-only tests aren’t covered). Unrelated to the login
  response change and any self-service code.

### Regression fixes made along the way (pre-existing blockers to green e2e)
1. `/api/auth/login` did not return `user_category`, so the frontend onboarding
   gate logged staff users into OnboardingPage after every login. Added
   `"user_category": user.get("user_category") or "pending"` to the login response.
2. e2e seeds gave staff no `user_category`; now seeded as
   `institution_managed` (bypasses onboarding, semantic for staff).
3. Admin sidebar label “Consent” vs the page/e2e “Consent Tracker” mismatch —
   label aligned to “Consent Tracker”.

## 9. Platform API / scraper limitations
- Live social data is fetched by the existing platform connectors (Reddit,
  Bluesky, Mastodon, YouTube, IG, X, Facebook, LinkedIn, TikTok) subject to each
  platform’s auth and endpoint constraints; offline/demo environments produce
  honest `no_data` rather than fabricated results.
- `analyzable: false` platforms can never report findings — UI states this.
- Analysis sessions persist a snapshot (`analysis_sessions` table) for history;
  results are not live — the session page says so.
- E2E runs fully offline: email delivery fails by design and is asserted; seeded
  accounts exercise the consent lifecycle deterministically.