begin;

create table public.music_rating_library (
    owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
    kind text not null check (kind in ('album', 'artist', 'rating')),
    item_id text not null,
    snapshot_hash text not null check (snapshot_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    updated_at timestamptz not null default now(),
    primary key (owner_id, kind, item_id)
);

alter table public.music_rating_library enable row level security;
revoke all on public.music_rating_library from public, anon, authenticated;
grant select, insert, update on public.music_rating_library to authenticated;

create policy music_rating_read on public.music_rating_library
    for select to authenticated using ((select auth.uid()) = owner_id);
create policy music_rating_insert on public.music_rating_library
    for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy music_rating_update on public.music_rating_library
    for update to authenticated using ((select auth.uid()) = owner_id)
    with check ((select auth.uid()) = owner_id);

create function public.music_rating_upload(p_items jsonb) returns void
    language sql security invoker set search_path = '' as $$
    insert into public.music_rating_library (owner_id, kind, item_id, snapshot_hash, payload)
    select auth.uid(), item.kind, item.item_id, item.snapshot_hash, item.payload
    from jsonb_to_recordset(p_items) as item(kind text, item_id text, snapshot_hash text, payload jsonb)
    on conflict (owner_id, kind, item_id) do update
        set snapshot_hash = excluded.snapshot_hash, payload = excluded.payload, updated_at = now();
$$;

revoke all on function public.music_rating_upload(jsonb) from public, anon;
grant execute on function public.music_rating_upload(jsonb) to authenticated;

insert into storage.buckets (id, name, public) values
    ('music-rating-artwork', 'music-rating-artwork', false);

-- Preserve isolation even when the project has other permissive Storage policies.
create policy music_rating_artwork_account_boundary on storage.objects
    as restrictive for all to anon, authenticated using (
        bucket_id <> 'music-rating-artwork'
        or (storage.foldername(name))[1] = (select auth.uid()::text)
    ) with check (
        bucket_id <> 'music-rating-artwork'
        or (storage.foldername(name))[1] = (select auth.uid()::text)
    );

create policy music_rating_artwork_read on storage.objects
    for select to authenticated using (
        bucket_id = 'music-rating-artwork'
        and (storage.foldername(name))[1] = (select auth.uid()::text)
    );
create policy music_rating_artwork_insert on storage.objects
    for insert to authenticated with check (
        bucket_id = 'music-rating-artwork'
        and (storage.foldername(name))[1] = (select auth.uid()::text)
    );
create policy music_rating_artwork_update on storage.objects
    for update to authenticated using (
        bucket_id = 'music-rating-artwork'
        and (storage.foldername(name))[1] = (select auth.uid()::text)
    ) with check (
        bucket_id = 'music-rating-artwork'
        and (storage.foldername(name))[1] = (select auth.uid()::text)
    );

commit;
