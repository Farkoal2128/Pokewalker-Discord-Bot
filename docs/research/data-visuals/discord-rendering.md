# Rendering images in Discord

Checked **2026-11-04**. Research and proposed rendering policy; no bot implementation or live Discord test is included.

## Facts — delivery and limits

| Topic | Confirmed behavior | Source / checked |
|---|---|---|
| Image URL | An embed image accepts HTTP(S) or an attachment reference. Upload the file and set `image.url` to `attachment://scene.png`; the filename must match. Embed image dimensions are not client layout controls. | [Message resource][D2], [upload reference][D1] · 2026-11-04 |
| Per-file size | Default upload allowance is **20 MiB**, increased from 10 MiB on **2026-09-03**, including bots, webhooks and interaction responses. The interaction supplies `attachment_size_limit` in bytes; allowances can differ. | [Change log][D3], [upload reference][D1], [interaction object][D4] · 2026-11-04 |
| Request size | **Create Message** separately documents a **25 MiB maximum request**. This is not a second per-file allowance or a verified universal limit for every interaction endpoint. | [Create Message][D2] · 2026-11-04 |
| Attachment embed formats | The attachment-within-embed reference explicitly lists `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`. An arbitrary uploadable file is not necessarily an embeddable image. | [Upload reference][D1] · 2026-11-04 |
| Animation | GIF animation is supported; Discord also explicitly supports **animated WebP** in attachments and embeds. Playback settings can suppress animation; automatic playback is not guaranteed. | [Discord media engineering][D5], [Reduced Motion][D6] · 2026-11-04 |
| Ephemeral attachments | Interaction responses support files and `EPHEMERAL`; ephemeral attachments are eventually removed but are guaranteed while their message exists. The documentation does not specify a universal attachment lifetime. | [Interactions][D4], [Attachment object][D2] · 2026-11-04 |
| Response deadlines | Initial response/defer is due within **3 seconds**; interaction tokens last **15 minutes**. Token validity is not the ephemeral message's deletion timer. | [Interactions][D4] · 2026-11-04 |
| Editing and URLs | Retain the IDs of attachments you want to keep during an edit. Uploaded attachment CDN URLs are signed and expire; Discord refreshes them within its client. | [Attachment requests][D2], [signed URLs][D1] · 2026-11-04 |

**UNVERIFIED:** A universal image-pixel-dimension ceiling for these bot scenes, exact ephemeral deletion timing, and behavior on every Discord client/version were not established. Do not invent these limits.

### Discord library APIs

**Facts:** `discord.py` exposes `Interaction.filesize_limit`, `response.defer(ephemeral=True, thinking=True)` and `edit_original_response(attachments=[...])`; the latter accepts retained attachments and new files. `discord.js` exposes `attachmentSizeLimit`, `deferReply({flags: MessageFlags.Ephemeral})` and `editReply`. Sources: [discord.py interactions][D7], [discord.js interaction][D8]; checked 2026-11-04.

## Recommendations — delivery strategy

The following are design choices, not Discord requirements.

| Choice | Benefits | Costs / appropriate use |
|---|---|---|
| Hotlink a source sprite | Minimal bot CPU/upload work; useful for a prototype's single thumbnail. | Requires a URL Discord can fetch; dependent on host availability and changing assets. Cannot assemble a custom scene from separate images. Check the source's usage policy. |
| Composite locally, attach PNG | Consistent layout, pixel scaling, labels and shiny indication; works from prepared local assets. | Uses CPU and upload bandwidth. Needs bounded workers and caches. **Recommended default.** |
| Host completed scenes yourself | Reusable URLs can avoid repeat uploads. | Additional hosting/access-control work. Public image URLs can expose private storage views; unnecessary for this v1. |

**Recommendation:** Use static PNG initially, with one composed image per view. Proposed canvas sizes: **768×432** for scenes; **768×576**, **12 entries/page** for storage. These are tunable product defaults, not platform limits. Aim for **under 1 MiB per output** and always check the current interaction's file allowance. Downsize, reduce the grid page, or send a text-only view when necessary.

| Scene | Proposed image contents and cache-sensitive state |
|---|---|
| Encounter | Terrain background, correct front sprite/form/gender/shiny palette, fixed sparkle glyph and visible `Shiny` text when applicable. Use the encounter's saved state; rendering must not reroll it. |
| Catch result | Same specimen and background, result banner, CP and awarded resources from the committed result. A catch image is not authority for the game transaction. |
| Gym battle frame | Friendly back sprite, opponent front sprite, names, CP labels, current/max HP and bars. Clamp drawn HP fractions to `[0,1]`; preserve the actual values in text. Resolve theme from the server/gym snapshot. |
| Storage grid | Small front sprites, CP, shiny/favorite markers, short display labels and stable selection IDs. Include filter/sort/page and storage revision in the key. Keep selection controls outside the raster. |

**Recommendation:** Use ordinary embed text as an accessible companion: names, CP, HP, shiny state and catch result must remain readable if the image fails. Use a drawn sparkle plus text, not color or animation alone. A missing asset must never change stored shiny state or form; follow [sprite fallbacks](sprites.md).

### Private `/walker` flow

**Recommendation:** Authorize the player/context, defer ephemerally immediately, load a consistent game snapshot, render in a worker, then edit the original private response with the attachment and buttons. For button presses, acknowledge/defer the component update and edit the existing private view. After a restart or expired response token, let `/walker` reconstruct a new view from persisted game state.

**Recommendation:** Set the ephemeral flag on the initial defer, upload a fresh `scene-<revision>.png`, point the embed at that exact filename, and remove obsolete attachments in the same edit. In `discord.py`, pass the new `File` in `attachments`; in `discord.js`, use `files` for the upload and `attachments` for existing files to retain. Serialize view updates or discard stale render jobs so an older battle frame cannot overwrite the latest one. Never use an ephemeral CDN URL as the durable asset cache.

## Facts — compositing APIs

- **Pillow:** `Image.resize(..., Image.Resampling.NEAREST)` provides nearest-neighbor scaling; RGBA images can be placed with `alpha_composite`. [Pillow Image reference][D9] · checked 2026-11-04.
- **sharp:** `kernel: sharp.kernel.nearest` controls resizing; `composite` positions overlays with `left`/`top`. Overlays must fit the processed base; pipeline resizing applies to the base before composition. [Resize][D10], [composite][D11] · checked 2026-11-04.
- **@napi-rs/canvas:** provides a Skia-backed Canvas implementation, drawing/text APIs and PNG encoding. [Project documentation][D12] · checked 2026-11-04.

## Recommendations — library and minimal examples

**Recommendation:** Python: **Pillow**, with its synchronous rendering off the Discord event loop. Node: **sharp** for resize/composite/encode; choose **@napi-rs/canvas** instead when imperative HP bars, labels and shapes dominate. With Canvas, disable image smoothing for pixel sprites. Pin dependencies and fonts in the eventual application build. Do not choose the entire bot language solely for image rendering.

These are original minimal examples, not production handlers. They consume approved local **static PNGs**; no network request or Discord token is needed. Example constants are design choices: a background at its final dimensions, integer **3×** sprite scale, **24 px** bottom margin. Reject an oversized sprite rather than silently crop it. Choose a smaller integer scale in production when needed.

### Python / Pillow

```python
from io import BytesIO
from PIL import Image

def render_scene(background_path, sprite_path):
    with Image.open(background_path) as source:
        scene = source.convert("RGBA")
    with Image.open(sprite_path) as source:
        sprite = source.convert("RGBA")
    sprite = sprite.resize(
        (sprite.width * 3, sprite.height * 3),
        Image.Resampling.NEAREST,
    )
    x = (scene.width - sprite.width) // 2
    y = scene.height - sprite.height - 24
    if x < 0 or y < 0:
        raise ValueError("Sprite does not fit the scene")
    scene.alpha_composite(sprite, dest=(x, y))
    output = BytesIO()
    scene.save(output, format="PNG")
    return output.getvalue()
```

### Node / sharp (ES module)

```javascript
import sharp from "sharp";

export async function renderScene(backgroundPath, spritePath) {
  const bg = await sharp(backgroundPath).metadata();
  const source = await sharp(spritePath).metadata();
  if (!bg.width || !bg.height || !source.width || !source.height) {
    throw new Error("Missing image dimensions");
  }
  const width = source.width * 3;
  const height = source.height * 3;
  const left = Math.floor((bg.width - width) / 2);
  const top = bg.height - height - 24;
  if (left < 0 || top < 0) throw new Error("Sprite does not fit");
  const sprite = await sharp(spritePath)
    .resize(width, height, { kernel: sharp.kernel.nearest })
    .png().toBuffer();
  return sharp(backgroundPath)
    .composite([{ input: sprite, left, top }])
    .png().toBuffer();
}
```

**Recommendation:** Precompute each sprite's content bounds and ground anchor. Bottom-align opaque artwork, not a transparent file's arbitrary canvas edge. Preserve aspect ratio and integer scaling; do not mix smooth artwork downsampling with pixel-sprite enlargement. Pin/escape text inputs and use a font with the required language coverage. Animation would require explicit frame composition/timing; these examples intentionally render static inputs.

## Recommendations — caches and performance

**Asset cache:** Prepare the approved allowlist out of band. Map species/Pokémon/form IDs, gender, shiny state, view and style to validated local files. Record source revision, checksum, format, dimensions and attribution. Download once with bounded concurrency/timeouts, write atomically, and remember missing assets to avoid repeated failing requests. Decode/resize hot assets in a bounded memory cache. Do not render from user-supplied arbitrary URLs or paths.

**Render cache:** Hash canonical JSON containing `renderer_version`, asset/font/content revisions, scene kind, dimensions, terrain/palette, ordered actors with exact variant IDs, CP/HP, result/rewards, locale and all displayed text. Storage also needs ordered specimen IDs, page/filter/sort, storage revision, and owner/server scope where relevant. Shiny and non-shiny scenes must have different keys. Keep immutable bytes on disk with bounded size/LRU eviction; a cached private image still requires authorization before delivery. Never put an interaction token in a cache key or filename. Deduplicate concurrent identical renders.

**Work scheduling:** Render only when a requested view changes, never per chat message. Use a bounded worker queue; keep Discord heartbeats and interactions responsive. Proposed starting point: **one render job at a time** on a shared small host; tune after measurement. Keep decoded assets read-only and copy the base per job.

**Expected small-VPS render time — UNVERIFIED estimate:** for warm local assets and static output below a megapixel, provisionally budget **10–100 ms** for an encounter/battle and **30–250 ms** for a 12-cell grid, including PNG encoding but excluding queue wait, asset fetch and Discord upload. These are planning estimates, not measured results or service guarantees; compression settings, CPU sharing and fonts can change them substantially. A render-cache hit avoids composition/encoding, not disk/network latency.

**Recommendation:** Benchmark on the actual always-on Ubuntu host (and any proposed VPS): separate cold asset load, warm decode/compose/encode, cache-hit read and Discord upload. Sample **100 renders per scene** as a proposed initial protocol; report median/p95, bytes, peak memory and queue delay under expected concurrent services. Defer interactions before rendering regardless of an optimistic benchmark. Live client animation, ephemeral attachment replacement and actual host latency remain acceptance checks for implementation.

## Sources

All checked **2026-11-04**; facts above cite the applicable source.

[D1]: https://docs.discord.com/developers/reference#uploading-files
[D2]: https://docs.discord.com/developers/resources/message
[D3]: https://docs.discord.com/developers/change-log#default-file-upload-limit-increase
[D4]: https://docs.discord.com/developers/interactions/receiving-and-responding
[D5]: https://discord.com/blog/modern-image-formats-at-discord-supporting-webp-and-avif
[D6]: https://support.discord.com/hc/en-us/articles/360040613412-Reduced-Motion-Setting
[D7]: https://discordpy.readthedocs.io/en/stable/interactions/api.html
[D8]: https://discord.js.org/docs/packages/discord.js/main/ChatInputCommandInteraction:Class
[D9]: https://pillow.readthedocs.io/en/stable/reference/Image.html
[D10]: https://sharp.pixelplumbing.com/api-resize/
[D11]: https://sharp.pixelplumbing.com/api-composite/
[D12]: https://github.com/Brooooooklyn/canvas
