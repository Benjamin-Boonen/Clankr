# Mobile layout

Handoff for contributors touching the UI. Written by Claude, 2026-11-02. Keep it updated when you change the topbar,
sidebar, composer, modals or any CSS in the mobile block.

## What changed

Files: `pyggie/home/templates/home/index.html`, `pyggie/home/templates/registration/login.html`. No backend change, no migration.

The UI used to be desktop-only (one `@media` rule, fixed 240px sidebar, `100vh`, 14.5px inputs). Now:

| Area | On a phone |
|---|---|
| Sidebar | Off-canvas **drawer** (fixed, 86vw up to 320px) with a dimming scrim. Closed on load, closes after you open a chat, start a new one, tap the scrim or press Escape. |
| Topbar | Row 1: drawer button, "Clank.r" title, action buttons. Row 2: the model picker, full width. |
| Model menus | Span the whole picker (they used to hang off their button and run off-screen). |
| Messages | 14px side padding, user avatar hidden, tables scroll sideways inside themselves, long URLs wrap. |
| Composer | 16px text (iOS Safari zooms the page below 16px), safe-area padding, keyboard hint hidden. **Enter inserts a newline**, the send button sends (touch keyboards have no Shift). |
| Modals | Full-width bottom sheets (Settings, Artifacts, Skills). |
| Viewport | `100dvh` (visible height), `viewport-fit=cover` + `env(safe-area-inset-*)` for notches, `interactive-widget=resizes-content` so the composer stays above the Android keyboard. |

Login page: 16px inputs and bigger buttons below 760px.

## The one rule that must stay in sync

"Mobile" is defined **twice**, and both must match:

- CSS: `@media (max-width: 760px), (pointer: coarse) and (max-height: 500px)` (the block at the end of `<style>`)
- JS: `const mobileMQ = matchMedia('...same query...')` next to `setSidebar()`

The second clause makes **landscape phones** count as mobile (844x390 is wider than 760px but too short for a desktop layout).
Desktop and tablets in portrait (>760px, mouse or tall) are unchanged.

## Conventions

- `.shell.collapsed` means "sidebar closed" on both layouts. On mobile it is the default state.
- On mobile the drawer state is **not** saved to `localStorage['clankr.sidebarCollapsed']`, so a phone session never overwrites the desktop choice (`setSidebar(collapsed, persist)`).
- Add phone-specific overrides **inside the mobile block, which must stay last in `<style>`**. It overrides desktop rules by order, not with `!important`.
- Use `dvh` (keep a `vh` line before it as fallback), never bare `100vh`, for anything sized to the screen.
- New text inputs on mobile: `font-size: 16px`. New buttons: at least 36px touch target. Don't rely on `:hover`.
- Don't put `overflow-wrap: anywhere` on a table: it lets columns shrink to one character (`Mod/el`). The `.ai-body` text may use it, tables reset it to `normal`.
- The 760px `.cap` rule (hides chip labels) predates this and is separate.

## How it was tested

Headless Chrome (Playwright), iPhone-sized touch context 390x844, then 844x390 landscape, then a 1280x800 desktop regression,
against a fake Ollama. 26 assertions: drawer closed on load / opens / scrim closes / closes after opening a chat / not persisted,
no horizontal overflow (home, long reply with URL + table + code, landscape), model menu inside the screen,
Enter = newline on touch but sends on desktop, 16px inputs, settings is a full-width bottom sheet, table cells not broken per letter,
desktop sidebar still 240px and still persists, no JS errors. The script is not in the repo (needs Playwright and local copies of
the CDN libraries); to repeat by hand use Chrome DevTools, device toolbar, 390x844 (and 844x390), and walk the same list.

**Not tested:** real iOS Safari or Android devices (on-screen keyboard behaviour, notch insets, `dvh` while the URL bar collapses),
real models, and the particle background's battery cost on phones.

## Known gaps / ideas

- The topbar takes about 136px (16% of the screen): the model picker wraps to two rows. A collapsible "model settings" row would win it back.
- Landscape phone leaves little room for messages (topbar + composer use most of 390px).
- The Share button has no handler (placeholder, pre-existing).
- Escape closes Settings (and the drawer) but not the Artifacts / Skills sheets (pre-existing).
- No PWA manifest / home-screen install yet.

## Pitfall when testing

`python manage.py runserver --noreload` keeps Django's template cache: after editing `index.html` restart the server, or you
will be testing the old page. (Plain `runserver` reloads by itself.)


## Message action controls (2026-11-11)

Desktop message actions (Copy / Retry) appear on row hover or keyboard focus. On touch layouts they are always visible; keep the visibility override and 36px minimum touch target inside the final mobile CSS block. Retry is intentionally disabled for assistant responses whose preceding user turn contained attachments, because original file objects are not retained when a conversation is reloaded.
