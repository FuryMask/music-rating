import assert from "node:assert/strict";

const env = {
  SUPABASE_URL: "https://project.test",
  SUPABASE_PUBLISHABLE_KEYS: JSON.stringify({ default: "project-public-key" }),
  SPOTIFY_CLIENT_ID: "app-id",
  SPOTIFY_CLIENT_SECRET: "fixture-spotify-secret",
  GENIUS_ACCESS_TOKEN: "fixture-genius-secret",
};
globalThis.Deno = { env: { get: (name) => env[name] }, serve: () => {} };

const albumId = "A".repeat(22);
const artistId = "B".repeat(22);
const artist = { id: artistId, name: "Артист" };
const track = (name) => ({ name, artists: [artist], duration_ms: 180000 });
let providerCalls = 0;
let tokenCalls = 0;
let validNext = true;

globalThis.fetch = async (input, { headers }) => {
  const url = new URL(input);
  if (url.origin === env.SUPABASE_URL) {
    assert.equal(url.pathname, "/rest/v1/music_rating_members");
    assert.equal(headers.apikey, "project-public-key");
    if (headers.Authorization === "Bearer member-token") return Response.json([{ user_id: "member" }]);
    return headers.Authorization === "Bearer other-user" ? Response.json([]) : Response.json({}, { status: 401 });
  }
  providerCalls++;
  if (url.href === "https://accounts.spotify.com/api/token") {
    tokenCalls++;
    assert.equal(atob(headers.Authorization.slice(6)), `${env.SPOTIFY_CLIENT_ID}:${env.SPOTIFY_CLIENT_SECRET}`);
    return Response.json({ access_token: "fixture-spotify-token", expires_in: 3600 });
  }
  if (url.origin === "https://api.spotify.com") {
    assert.equal(headers.Authorization, "Bearer fixture-spotify-token");
    if (url.pathname === `/v1/albums/${albumId}`) return Response.json({
      name: "Альбом", artists: [artist], tracks: { items: [track("Первый")], next: validNext ?
        `https://api.spotify.com/v1/albums/${albumId}/tracks?offset=1` : "https://elsewhere.test/tracks" },
    });
    if (url.pathname === `/v1/albums/${albumId}/tracks`) return Response.json({ items: [track("Второй")] });
    if (url.pathname === `/v1/artists/${artistId}`) return Response.json({ images: [{ url: "https://example.test/photo" }] });
  }
  if (url.origin === "https://api.genius.com") {
    assert.equal(headers.Authorization, `Bearer ${env.GENIUS_ACCESS_TOKEN}`);
    if (url.pathname === "/songs/17") return Response.json({ response: { song: { primary_artist: artist,
      featured_artists: [{ name: "Гость" }], unused_field: "unused" } } });
    if (url.pathname === "/songs/18") return Response.json({}, { status: 404 });
  }
  assert.fail(`Unexpected fetch: ${url.href}`);
};

const { handleRequest } = await import("../supabase/functions/music-catalog/index.ts");
const call = (body, token) => handleRequest(new Request("https://project.test/functions/v1/music-catalog", {
  method: "POST", body: JSON.stringify(body), headers: token ? { Authorization: `Bearer ${token}` } : {},
}));

const spotify = { action: "spotify-album", id: albumId };
assert.equal((await call(spotify)).status, 401);
assert.equal((await call(spotify, "fake")).status, 401);
assert.equal((await call(spotify, "other-user")).status, 403);
assert.equal((await call({ ...spotify, id: "../token" }, "member-token")).status, 400);
assert.equal(providerCalls, 0);

const album = await (await call(spotify, "member-token")).json();
assert.deepEqual(album.album.tracks.items.map(({ name }) => name), ["Первый", "Второй"]);
assert.equal(album.photos[artistId][0].url, "https://example.test/photo");
assert.equal((await call(spotify, "member-token")).status, 200);
assert.equal(tokenCalls, 1);
validNext = false;
assert.equal((await call(spotify, "member-token")).status, 502);

const songs = await (await call({ action: "genius-songs", ids: [17, 18, 17] }, "member-token")).json();
assert.deepEqual(Object.keys(songs), ["17"]);
assert.equal(songs[17].response.song.featured_artists[0].name, "Гость");
assert.equal(songs[17].response.song.unused_field, undefined);
assert.doesNotMatch(JSON.stringify({ album, songs }), /fixture-(spotify|genius)-/);
delete env.GENIUS_ACCESS_TOKEN;
const unconfigured = await call({ action: "genius-songs", ids: [17] }, "member-token");
assert.equal(unconfigured.status, 503);
assert.deepEqual(await unconfigured.json(), { code: "not_configured" });
console.log("Cloud catalog authorization, provider routes, token cache, and responses passed.");
