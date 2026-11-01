# Expense Tracker: the phone app

The iPhone and Android app (also runnable in a browser), built with Expo SDK 58
and Expo Router. It shows what the API in `../api` works out; see the main
[README](../README.md) for what the app does and how to set up the API and Google.

```bash
npm install
cp .env.example .env.local   # EXPO_PUBLIC_API_URL: where the API is
npm start                    # then i (iOS simulator), a (Android emulator), w (browser), or scan with Expo Go
```

Before committing: `npm run typecheck` and `npm run lint`.

## How it's put together

| Where | What |
|---|---|
| `src/app/` | Screens, by route (Expo Router). `(tabs)/` holds Home, Activity, Accounts and Settings; the others open as sheets over them: `payment/[item]`, `drill` (the payments behind a figure), `add-expense`, `sync-options`, `bank/[key]`. `sign-in` is the only screen before signing in; `auth` is where Google sign-in comes back to. |
| `src/sections/` | One component per sub-tab (Overview, Trends, …), each fetching its own endpoint. |
| `src/components/` | The look: `ui.tsx` (cards, buttons, fields, lists, sheets to pick from), `charts.tsx` (SVG), `icon.tsx` (SF Symbols on iOS, Material Symbols elsewhere), the date picker, the payment list. |
| `src/lib/` | `api.ts` (requests, with the session token and the phone's time zone), `session.tsx` (Continue with Google, PKCE), `sync.tsx` (starting a sync and following it), `query.ts` (React Query), `theme.tsx` (light and dark, the website's colors), `types.ts` (what each endpoint returns). |

The API sends each screen's figures ready to show ("Rs 2.53 lakh", "Yesterday",
a category's color slot), so the app holds no money or date logic of its own.
Text with `**bold**` parts goes through `RichText`; the consent and privacy
texts through `Markdown`.

Everything used is in Expo Go, so no development build is needed. The sub-tab
of each tab is in the address (`/activity?tab=transfers`), so it can be linked to.

## Building

`eas.json` has two profiles: `preview` (an APK to install directly, and ad hoc
iOS builds) and `production` (for the stores). See "Publishing the app" in the
main README.
