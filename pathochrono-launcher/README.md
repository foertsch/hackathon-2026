# PathoChrono Launcher — Chrome extension

Tiny MV3 extension that adds a **Scheduler** button next to the "Welcome"
greeting on the SOPHiA DDM Gen2 landing page. Clicking it opens the
chronotype-aware scheduler at <https://patho-chrono-flow.lovable.app/> in a
new tab.

No backend, no API calls — just a single `<a>` injected into the page.

## Install

1. Open `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** and select this `pathochrono-launcher/` directory
4. Visit <https://platform-vandv1.sophiagenetics.com/web/genomics> and log in

The orange→purple gradient pill labeled **Scheduler** should appear right next
to "Welcome, …" once the page settles.

## Files

- `manifest.json` — MV3 manifest, single host permission for the Gen2 origin.
- `content.js` — finds the Welcome element by text, inserts the button as a
  sibling, re-runs on DOM mutations (SPA navigation safe).
- `content.css` — button styling.
