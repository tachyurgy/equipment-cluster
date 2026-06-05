# Releases — Equipment Cluster

Release history for the visual-history viewer at https://tachyurgy.github.io/equipment-cluster/
(GitHub Pages, built from `app/` by `.github/workflows/deploy.yml` on every push to `main`).

## 2026-06-05 — Fix collapsed/overlapping grid, lighten load, angle-first framing
- **What deployed:** https://tachyurgy.github.io/equipment-cluster/ — new bundle `index-DqerLIIo.js`. Pages deploy run `27041526803` green.
- **Changed:**
  - **Cluster grid no longer overlaps.** Cards were rendering as ~20px-tall overlapping bands. Root cause: `grid-auto-rows: auto` + an aspect-ratio/padding-ratio card — neither contributes to a grid item's *intrinsic* height, so row tracks collapsed to the button's ~20px intrinsic height and the aspect-sized boxes piled on top of each other (516 overlapping pairs measured). Fixed with explicit `grid-auto-rows: 190px` + `object-fit: cover`. Verified 0 overlaps at 1440 / 768 / 390px.
  - **Faster initial load.** Removed an on-mount preloader that eagerly fetched all 576 thumbnails + 36 **full-res** covers (~30MB). Grid now lazy/eager-loads its own thumbnails natively → initial load ~3MB / ~44 images, thumbnails only (0 full-res on the overview).
  - **Progressive drilldown.** The per-angle timeline now shows the thumbnail instantly as a blurred placeholder, then fades the full-res image in on top once it downloads.
  - **Angle-first copy.** Unit header and sidebar now lead with the angle count (the app's whole point — the history of one camera angle over time); inspection count demoted to secondary.
- **How:** edit `app/src/**`, `cd app && npm run build` to sanity-check, then `git push origin main` (the `deploy.yml` workflow rebuilds + publishes Pages). Verified locally and live with cached Playwright Chromium before/after.
- **Verified:** live bundle hash matches the local build; live Playwright run reports 0 overlaps, 190px cards, header "100 angles · 1512 photos across 86 inspections", 0 full-res image loads on the overview. Drilldown shows placeholder→full-res and an 11-photo angle timeline.
