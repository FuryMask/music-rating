const SPOTIFY = "https://api.spotify.com";
const SPOTIFY_ID = /^[A-Za-z0-9]{22}$/;
const MAX_TRACK_PAGES = 10;
const MAX_ARTIST_PHOTOS = 30;
const MAX_GENIUS_SONGS = 20;

type Json = Record<string, any>;
type SpotifyToken = { value: string; expiresAt: number };
let spotifyToken: SpotifyToken | undefined;
let pendingToken: Promise<SpotifyToken> | undefined;

class CatalogFailure extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

function json(value: Json, status = 200): Response {
  return Response.json(value, { status, headers: { "Cache-Control": "no-store" } });
}

function secret(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) throw new CatalogFailure(503, name.startsWith("SUPABASE_") ? "membership_unavailable" : "missing_credentials");
  return value;
}

async function requireMember(authorization: string | null, signal: AbortSignal) {
  if (!authorization || !/^Bearer [\w.-]+$/i.test(authorization)) {
    throw new CatalogFailure(401, "sign_in_required");
  }
  const namedKeys = Deno.env.get("SUPABASE_PUBLISHABLE_KEYS");
  const apikey = (namedKeys ? JSON.parse(namedKeys).default : undefined) ?? secret("SUPABASE_ANON_KEY");
  const response = await fetch(`${secret("SUPABASE_URL")}/rest/v1/music_rating_members?select=user_id&limit=1`, {
    headers: { apikey, Authorization: authorization }, redirect: "error", signal,
  });
  if (response.status === 401) throw new CatalogFailure(401, "sign_in_required");
  if (response.status === 403) throw new CatalogFailure(403, "membership_required");
  if (!response.ok) throw new CatalogFailure(503, "membership_unavailable");
  if ((await response.json()).length !== 1) throw new CatalogFailure(403, "membership_required");
}

async function callProvider(url: string, token: string, signal: AbortSignal): Promise<Json> {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` }, redirect: "error", signal });
  if (response.status === 404) throw new CatalogFailure(404, "not_found");
  if (response.status === 401) throw new CatalogFailure(502, "credentials_rejected");
  if (response.status === 403) throw new CatalogFailure(502, "provider_forbidden");
  if (response.status === 429) throw new CatalogFailure(429, "rate_limited");
  if (!response.ok) throw new CatalogFailure(502, "provider_unavailable");
  return await response.json();
}

async function requestSpotifyToken(): Promise<SpotifyToken> {
  const id = secret("SPOTIFY_CLIENT_ID");
  const clientSecret = secret("SPOTIFY_CLIENT_SECRET");
  const response = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      Authorization: `Basic ${btoa(`${id}:${clientSecret}`)}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials",
    redirect: "error",
    signal: AbortSignal.timeout(8000),
  });
  if (response.status === 429) throw new CatalogFailure(429, "rate_limited");
  if (response.status >= 500) throw new CatalogFailure(502, "provider_unavailable");
  if (!response.ok) throw new CatalogFailure(502, "credentials_rejected");
  const data = await response.json();
  if (typeof data.access_token !== "string" || !Number.isFinite(data.expires_in)) {
    throw new CatalogFailure(502, "provider_unavailable");
  }
  return { value: data.access_token, expiresAt: Date.now() + Math.max(data.expires_in - 60, 0) * 1000 };
}

async function getSpotifyToken(): Promise<string> {
  if (spotifyToken && spotifyToken.expiresAt > Date.now()) return spotifyToken.value;
  pendingToken ??= requestSpotifyToken().then((token) => spotifyToken = token).finally(() => pendingToken = undefined);
  return (await pendingToken).value;
}

async function inBatches<T>(values: T[], call: (value: T) => Promise<void>) {
  for (let offset = 0; offset < values.length; offset += 6) {
    await Promise.all(values.slice(offset, offset + 6).map(call));
  }
}

async function spotifyAlbum(id: string, signal: AbortSignal): Promise<Json> {
  const token = await getSpotifyToken();
  const configuredMarket = Deno.env.get("SPOTIFY_MARKET")?.trim().toUpperCase() ?? "";
  const market = /^[A-Z]{2}$/.test(configuredMarket) ? configuredMarket : "US";
  let album;
  try {
    album = await callProvider(`${SPOTIFY}/v1/albums/${id}?market=${market}`, token, signal);
  } catch (error) {
    if (error instanceof CatalogFailure && error.code === "credentials_rejected" && spotifyToken?.value === token) {
      spotifyToken = undefined;
    }
    throw error;
  }
  const tracks = [...(album.tracks?.items ?? [])].filter(Boolean);
  let next = album.tracks?.next;
  for (let page = 1; typeof next === "string" && page < MAX_TRACK_PAGES; page++) {
    const url = new URL(next);
    if (url.origin !== SPOTIFY || url.pathname !== `/v1/albums/${id}/tracks`) {
      throw new CatalogFailure(502, "provider_unavailable");
    }
    const data = await callProvider(url.href, token, signal);
    tracks.push(...(data.items ?? []).filter(Boolean));
    next = data.next;
  }
  const artists = [...(album.artists ?? []), ...tracks.flatMap((track) => track.artists ?? [])];
  const ids = [...new Set<string>(artists.map((artist) => artist?.id).filter((id) => typeof id === "string" && SPOTIFY_ID.test(id)))];
  const photos: Json = {};
  await inBatches(ids.slice(0, MAX_ARTIST_PHOTOS), async (artistId) => {
    if (signal.aborted) return;
    try {
      const data = await callProvider(`${SPOTIFY}/v1/artists/${artistId}`, token, signal);
      photos[artistId] = data.images ?? [];
    } catch {
      // Artist photos are optional.
    }
  });
  return { album: { name: album.name, release_date: album.release_date, images: album.images,
                     artists: album.artists, genres: album.genres, tracks: {
                       items: tracks.map(({ name, artists }) => ({ name, artists })),
                     } }, photos };
}

async function geniusSongs(ids: number[], signal: AbortSignal): Promise<Json> {
  const token = secret("GENIUS_ACCESS_TOKEN");
  const result: Json = {};
  await inBatches([...new Set(ids)], async (id) => {
    try {
      const data = await callProvider(`https://api.genius.com/songs/${id}`, token, signal);
      const song = data.response?.song;
      if (song) result[id] = { response: { song: {
        primary_artist: song.primary_artist,
        featured_artists: song.featured_artists,
      } } };
    } catch (error) {
      if (!(error instanceof CatalogFailure) || error.status !== 404) throw error;
    }
  });
  return result;
}

export async function handleRequest(request: Request): Promise<Response> {
  if (request.method !== "POST") return json({ code: "method_not_allowed" }, 405);
  try {
    const body = await request.text();
    if (body.length > 2048) return json({ code: "invalid_request" }, 400);
    const input = JSON.parse(body);
    const spotify = input?.action === "spotify-album" && typeof input.id === "string" && SPOTIFY_ID.test(input.id);
    const genius = input?.action === "genius-songs" && Array.isArray(input.ids) &&
      input.ids.length >= 1 && input.ids.length <= MAX_GENIUS_SONGS &&
      input.ids.every((id: number) => Number.isSafeInteger(id) && id > 0);
    if (!spotify && !genius) return json({ code: "invalid_request" }, 400);
    const signal = AbortSignal.timeout(18000);
    await requireMember(request.headers.get("Authorization"), signal);
    return json(spotify ? await spotifyAlbum(input.id, signal) : await geniusSongs(input.ids, signal));
  } catch (error) {
    if (error instanceof CatalogFailure) return json({ code: error.code }, error.status);
    if (error instanceof SyntaxError) return json({ code: "invalid_request" }, 400);
    return json({ code: "provider_unavailable" }, 502);
  }
}

Deno.serve(handleRequest);
