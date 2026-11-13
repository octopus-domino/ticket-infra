# Address search without API tokens

The application uses the open-source Photon API with OpenStreetMap data. It does
not consume commercial geocoding tokens. The public demo endpoint is rate limited
and has no availability guarantee. Do not evade its limits with rotating endpoints.

## Current host: 2 CPUs, 4 GiB RAM

Do not deploy Photon/OpenSearch on this host alongside the application. A global
index is outside its memory budget; upstream recommends 64 GiB RAM for smooth
planet-wide operation. Country extracts need their own measured budget too.
The existing app, gateway and Redis container limits already total 2336 MiB,
before PostgreSQL (if local), the OS, filesystem cache and other processes.
Container limits are ceilings, not proof of actual or peak memory usage.

On this host keep only the bounded application-side search cache and request
limiter. The public Photon endpoint is suitable only for reasonable traffic
within its policy; it cannot provide guaranteed unlimited address search.
A private geocoder, if needed, belongs on separate infrastructure. Neither a
second public endpoint nor retries remove the underlying capacity constraint.

For an independently hosted production geocoder, follow upstream instructions:
https://github.com/komoot/photon

Import an appropriate regional dataset, plan disk/RAM capacity and data updates,
and expose only its search API on the private network. The geocoder is independent
of the application database; do not put a planet index inside the app container.

Set the deployment variable (the URL must include the API path):

```dotenv
GEOCODER_URL=http://your-private-geocoder:2322/api/
```

`compose.api.yml` forwards this as `APP_JOURNEYS_GEOCODER_URL`. Restart/recreate
the application after changing it. Keep the service private and retain request
bounds and the shared cache. There are no per-request licence/token charges;
hosting, storage and maintenance still cost resources. This configuration does
not provision a server or download a dataset automatically.

Validate in staging: search an address, select it, build a route; repeat in all
supported UI languages and check server errors for 429/503. A failed external
search is not evidence of exhausted tokens. Check provider status and connection
timeouts before diagnosing the cause. Preserve OpenStreetMap attribution.
