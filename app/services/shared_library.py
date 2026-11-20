"""Map cloud records to the local library while keeping unsent edits."""

import hashlib
import json
import mimetypes
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models import Album, AlbumRatings, Artist, ArtistDraft, TrackDraft
from app.services.cloud_library import CloudError, LibraryItem, snapshot_library
from app.store import COVERS_DIR

BASELINE = "shared-baseline"


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _digest(value) -> str:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _album_key(payload: dict) -> str:
    return _digest([_normalized(payload["title"]), payload.get("year", ""),
                    sorted(_normalized(name) for name in payload.get("artists", []))])


def _track_keys(titles) -> list[str]:
    counts: Counter = Counter()
    keys = []
    for title in titles:
        name = _normalized(title)
        counts[name] += 1
        keys.append(_digest([name, counts[name]]))
    return keys


def _album_ids(store, remote=()) -> dict[str, str]:
    sources = {item.payload["source_id"]: item.item_id for item in remote
               if item.kind == "album" and item.payload.get("source_id")}
    return {album.id: album.cloud_id or sources.get(album.source_id) or _album_key({
        "title": album.title, "year": album.year, "artists": album.artist_names,
    }) for album in store.albums}


def member_names(status: dict) -> dict[str, str]:
    try:
        return {str(UUID(member["id"])): member["name"].strip() for member in status["members"]}
    except (TypeError, ValueError, KeyError, AttributeError):
        raise CloudError("Supabase вернул некорректный список участников.") from None


def _participant_key(name: str, user_id: str | None, members: dict[str, str]) -> str:
    if user_id:
        return user_id
    matches = [member for member, display_name in members.items() if _normalized(display_name) == _normalized(name)]
    return matches[0] if len(matches) == 1 else f"local-{_digest(_normalized(name))}"


def _columns(album_id: str, title: str, names, ids, grid, track_keys, members, updated_at="") -> list[LibraryItem]:
    columns = {}
    for index, name in enumerate(names):
        user_id = ids[index] if index < len(ids) else None
        rater_key = _participant_key(name, user_id, members)
        if rater_key in columns and user_id is None:
            continue
        scores = {key: float(row[index]) for key, row in zip(track_keys, grid) if row[index] is not None}
        if scores:
            average = min(AlbumRatings.AVERAGE_CAP, round(sum(scores.values()) / len(scores), 1))
            columns[rater_key] = LibraryItem("rating", f"{album_id}:{rater_key}", f"{title} · {name} — {average:g}", {
                "album_id": album_id, "rater_key": rater_key, "name": members.get(rater_key, name), "scores": scores,
            }, updated_at=updated_at)
    return list(columns.values())


def shared_items(store, members: dict[str, str], album_ids: dict[str, str]) -> list[LibraryItem]:
    albums = {album.id: album for album in store.albums}
    result = {}
    for item in snapshot_library(store):
        if item.kind == "artist":
            converted = [item]
        else:
            album = albums[item.item_id]
            album_id = album_ids[album.id]
            if item.kind == "album":
                payload = {key: value for key, value in item.payload.items() if key != "created_at"}
                converted = [replace(item, item_id=album_id, payload=payload)]
            elif album.ratings and album.ratings.filled_count():
                ratings = album.ratings
                converted = _columns(album_id, album.title, ratings.rater_names, ratings.rater_ids, ratings.values,
                                     _track_keys(track.title for track in album.tracks), members, album.rated_at or "")
            else:
                converted = [LibraryItem("summary", album_id, item.label, {"average": album.rating})]
        result.update((record.key, record) for record in converted)
    return list(result.values())


def record_hash(item: LibraryItem) -> str:
    if item.kind == "rating":
        # Display names can change independently of the scores.
        return _digest({key: float(value) for key, value in item.payload["scores"].items()})
    return item.record()["snapshot_hash"]


def baseline(store) -> dict[str, str]:
    try:
        value = json.loads(store.cloud_state(BASELINE) or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _rows(rows) -> list[LibraryItem]:
    return [LibraryItem(row["kind"], row["item_id"], "", row["payload"], updated_at=row.get("updated_at", ""))
            for row in rows]


def _personal_items(rows, members, shared) -> list[LibraryItem]:
    items = _rows(rows)
    albums = {item.item_id: item for item in items if item.kind == "album"}
    sources = {item.payload["source_id"]: item.item_id for item in shared
               if item.kind == "album" and item.payload.get("source_id")}
    album_ids = {key: sources.get(album.payload.get("source_id")) or _album_key(album.payload)
                 for key, album in albums.items()}
    result = []
    for item in items:
        if item.kind == "artist":
            result.append(item)
        elif item.kind == "album":
            payload = {key: value for key, value in item.payload.items() if key != "created_at"}
            result.append(replace(item, item_id=album_ids[item.item_id], payload=payload,
                                  updated_at=item.payload.get("created_at") or ""))
        elif item.kind == "rating" and (album := albums.get(item.item_id)) is not None:
            album_id = album_ids[item.item_id]
            if item.payload.get("participants") and item.payload.get("track_scores"):
                result.extend(_columns(album_id, album.payload["title"], item.payload["participants"], [],
                                       item.payload["track_scores"],
                                       _track_keys(track["title"] for track in album.payload["tracks"]), members,
                                       item.payload.get("rated_at") or ""))
            elif item.payload.get("average") is not None:
                result.append(LibraryItem("summary", album_id, "", {"average": item.payload["average"]},
                                          updated_at=item.payload.get("rated_at") or ""))
    return result


def upload_plan(store, status: dict, previous: dict[str, str]):
    remote_items = _rows(status["shared"])
    remote = {item.key: record_hash(item) for item in remote_items}
    remote_ratings = {item.key: item.payload["scores"] for item in remote_items if item.kind == "rating"}
    album_ids = _album_ids(store, remote_items)
    tracks = {album_ids[album.id]: set(_track_keys(track.title for track in album.tracks)) for album in store.albums}
    pending = []
    acknowledged = {}
    sent_hashes = {}
    for item in shared_items(store, member_names(status), album_ids):
        digest = record_hash(item)
        if remote.get(item.key) == digest:
            acknowledged[item.key] = digest
        elif previous.get(item.key) != digest:
            sent_hashes[item.key] = digest
            if item.kind == "rating" and item.key in remote_ratings:
                keys = tracks[item.payload["album_id"]]
                scores = {key: value for key, value in remote_ratings[item.key].items() if key not in keys}
                scores.update(item.payload["scores"])
                item = replace(item, payload={**item.payload, "scores": scores})
            pending.append(item)
    return pending, acknowledged, album_ids, sent_hashes


def _save_artwork(cloud, session, reference: dict | None, *, personal: bool) -> str | None:
    if reference is None:
        return None
    digest, content_type = reference["sha256"], reference["content_type"]
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None or not content_type.startswith("image/"):
        raise CloudError("В облаке найдена некорректная ссылка на изображение.")
    suffix = mimetypes.guess_extension(content_type) or ".img"
    if content_type == "image/jpeg":
        suffix = ".jpg"
    target = COVERS_DIR / f"cloud-{digest}{suffix}"
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        data = cloud.download_artwork(session, digest, personal=personal)
        if hashlib.sha256(data).hexdigest() != digest:
            raise CloudError("Изображение в облаке повреждено.")
        COVERS_DIR.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=COVERS_DIR, delete=False) as temp:
            temporary = Path(temp.name)
        try:
            temporary.write_bytes(data)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return f"data/covers/{target.name}"


def _local_date(timestamp: str) -> str:
    if not timestamp:
        return ""
    date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if date.tzinfo is not None:
        date = date.astimezone().replace(tzinfo=None)
    return date.isoformat(timespec="seconds")


def download_plan(cloud, session, store, status: dict, previous: dict[str, str]):
    members = member_names(status)
    shared = {item.key: item for item in _rows(status["shared"])}
    remote = {item.key: item for item in _personal_items(status["personal"], members, shared.values())}
    remote.update(shared)
    album_ids = _album_ids(store, remote.values())
    local = {item.key: item for item in shared_items(store, members, album_ids)}
    accepted = {}
    next_baseline = dict(previous)
    skipped = 0
    for key, item in remote.items():
        personal = key not in shared
        digest = record_hash(item)
        existing = local.get(key)
        local_digest = record_hash(existing) if existing is not None else None
        if local_digest != digest and existing is not None and local_digest != previous.get(key):
            skipped += 1
            continue
        if not personal:
            next_baseline[key] = digest
        if item.kind == "rating" or local_digest != digest:
            accepted[key] = item, personal

    albums = {album_ids[album.id]: album for album in reversed(store.albums)}
    artists = {artist.name: artist for artist in store.artists}
    ratings_by_album = defaultdict(dict)
    for item in local.values():
        if item.kind == "rating":
            ratings_by_album[item.payload["album_id"]][item.payload["rater_key"]] = item

    for item, personal in accepted.values():
        data = item.payload
        if item.kind == "artist":
            artists[item.item_id] = Artist(data["name"], data.get("genre", ""),
                _save_artwork(cloud, session, data.get("photo"), personal=personal),
                _save_artwork(cloud, session, data.get("avatar"), personal=personal))
        elif item.kind == "album":
            old = albums.get(item.item_id)
            cover = _save_artwork(cloud, session, data.get("cover"), personal=personal)
            tracks = [TrackDraft(track["title"], [ArtistDraft(name, existing=True) for name in track["artists"]])
                      for track in data["tracks"]]
            albums[item.item_id] = replace(old or Album(data["title"], id=f"cloud-{item.item_id}"),
                cloud_id=item.item_id, title=data["title"], year=data["year"], genre=data["genre"],
                region=data["region"], source_id=data.get("source_id") or (old.source_id if old else ""),
                cover_path=cover if not personal else cover or (old.cover_path if old else None),
                created_at=old.created_at if old else _local_date(data.get("created_at") or item.updated_at),
                artist_names=list(data["artists"]), tracks=tracks)
        elif item.kind == "rating":
            ratings_by_album[data["album_id"]][data["rater_key"]] = item

    for album_id, album in albums.items():
        rating_items = list(ratings_by_album[album_id].values())
        columns = [item.payload for item in rating_items]
        if columns:
            keys = _track_keys(track.title for track in album.tracks)
            for item in rating_items:
                if item.key in shared and item.key in accepted:
                    visible = {key: float(item.payload["scores"][key]) for key in keys if key in item.payload["scores"]}
                    next_baseline[item.key] = _digest(visible)
            ratings = AlbumRatings(
                rater_names=[members.get(column["rater_key"], column["name"]) for column in columns],
                rater_ids=[None if column["rater_key"].startswith("local-") else column["rater_key"]
                           for column in columns],
                values=[[column["scores"].get(key) for column in columns] for key in keys],
                rated_at=max([album.rated_at or "", *(_local_date(item.updated_at) for item in rating_items)]),
            )
            if ratings.filled_count():
                albums[album_id] = replace(album, cloud_id=album_id, ratings=ratings,
                                           rating=ratings.album_average(), rated_at=ratings.rated_at or None)
            else:
                albums[album_id] = replace(album, ratings=None, rating=None, rated_at=None)
        elif (summary := accepted.get(f"summary:{album_id}")) is not None:
            albums[album_id] = replace(album, rating=summary[0].payload["average"],
                                       rated_at=_local_date(summary[0].updated_at) or album.rated_at)
        if f"album:{album_id}" in shared and not albums[album_id].cloud_id:
            albums[album_id] = replace(albums[album_id], cloud_id=album_id)
    imported_ids = {album.id: album for album in albums.values()}
    ordered = [imported_ids.pop(album.id, album) for album in store.albums]
    return list(imported_ids.values()) + ordered, list(artists.values()), next_baseline, skipped
