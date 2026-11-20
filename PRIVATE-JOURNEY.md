# Private walks in the CoDoc deployment

Public URL: `https://www.codoc.site/private-journey/`.

The existing external Nginx forwards requests to the application container. Only
the container's `nginx.conf` changes: it serves the private application under
`/private-journey/`, its versioned assets and the SPA fallback. No external Nginx
configuration, certificate, upstream port or extra service is required.

## Sources and build

The deployment workspace contains four repositories:

```
ticket-editor/
ticket-pdf/
ticket-infra/
private_jorney/   # git@github.com:octopus-domino/private-jorney.git
```

`deploy.sh` clones the private repository if missing, then updates all four
repositories with `git pull --ff-only` before stopping services. For uploaded
source snapshots, use the existing `SKIP_GIT_PULL=true` option; all four folders
must then already be present.

The Dockerfile builds the editor, then private walks with Vite base
`/private-journey/`, then the backend. The stages are serialized for the small VM.
The final runtime contains both frontends in the same Nginx document root.
The deployment default leaves the external Nginx configuration untouched:
`CODOC_UPDATE_EXTERNAL_NGINX=false`.

Optional `MOS_DATA_API_KEY` is passed to the private frontend build as the BuildKit
secret `mos_data_api_key`; keep its value in the existing private environment,
never in Git. As with the Android client, a public Moscow API key used by the
frontend will be included in the compiled client JavaScript.

## House sources

The published browser frontend requests third-party house sources directly,
subject to each source's CORS and access rules. Android uses the native
`PublicSources` transport. Local Vite development can use its own
`/history-source` helper. Caches for house history and CIAN areas live on
the client.

## Travel construction

CoDoc retains the general trip, flights, accommodation and final PDF workflow.
Its private-walk action opens this same-origin application. Completed walk
transfers validate origin, iframe window, channel, points and per-leg geometry.
The resulting child snapshot is attached through the existing `walkId` contract;
its map, descriptions and duration survive in the trip and PDF.

All three Petersburg presets now belong to private walks. They are available on
its home page and from the map's ready-made walks button, including inside CoDoc.

After deploying, check `/private-journey/`, direct asset URLs, a preset, a house
card, and a round trip from `/start/tours` back to the travel constructor.

## Раздельная публикация

Команды публикации только фронта или только классов бэка, сборки APK, чтения логов и проверок описаны в [RUNTIME-PUBLISH.md](RUNTIME-PUBLISH.md).
